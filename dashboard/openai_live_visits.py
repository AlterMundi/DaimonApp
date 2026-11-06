"""Durable public Live creation receipts, not another conversation/work store.

The authenticated service supplies the frozen human/conversation owner. These
checks bind receipts to that owner; they do not authorize a browser or grant
tools. No route is mounted here. Existing native and provider modes stay intact.
"""
import hashlib
import json
import math
import os
import stat
import time
import uuid

from .codex_voice_history import history_lock
from .openai_live import LiveCall, LiveUnavailable, creation_request, _text
from .private_state import private_directory
from scripts.speech_render import atomic, private_bytes, sync_directory, RenderError


class LiveCreations:
    max_records = 512
    max_record_bytes = 262144
    max_total_bytes = 32 * 1024 * 1024
    max_active = 2
    unsettled = frozenset(('prepared', 'creating', 'creation_unconfirmed', 'created'))

    def __init__(self, directory):
        self.root = private_directory(directory)
        self.epoch = str(uuid.uuid4())
        self._sources = {}

    @staticmethod
    def _ident(ident):
        if not isinstance(ident, str) or str(uuid.UUID(ident)) != ident:
            raise ValueError('Select one public Live creation identity')
        return ident

    @staticmethod
    def _owner(human, frozen):
        if (type(human) is not int or human <= 0 or not isinstance(frozen, dict)
                or set(frozen) != {'binding', 'entry_binding', 'native_thread'}
                or not isinstance(frozen['binding'], str) or len(frozen['binding']) != 64
                or any(c not in '0123456789abcdef' for c in frozen['binding'])
                or not isinstance(frozen['entry_binding'], list)
                or len(frozen['entry_binding']) != 4 or frozen['entry_binding'][0] != human
                or not _text(frozen['native_thread'], 128)
                or frozen['entry_binding'][3] != frozen['native_thread']):
            raise ValueError('Select a frozen authenticated voice owner')
        raw = json.dumps({'human': human, 'frozen': frozen}, allow_nan=False,
                         ensure_ascii=False, separators=(',', ':'))
        if len(raw.encode()) > 8192:
            raise ValueError('Public Live owner snapshot exceeds its bound')
        return json.loads(raw)

    def _path(self, ident):
        return self.root / (self._ident(ident) + '.json')

    def _read(self, ident):
        value = json.loads(private_bytes(self._path(ident), self.max_record_bytes))
        if (not isinstance(value, dict) or value.get('schema') != 'daimon.live-creation/v1'
                or value.get('id') != ident or value.get('state') not in
                self.unsettled | {'creation_rejected', 'project_key_unavailable', 'closed', 'not_created'}):
            raise ValueError('Public Live creation record is unavailable')
        owner = value.get('owner')
        if (not isinstance(owner, dict)
                or self._owner(owner.get('human'), owner.get('frozen')) != owner):
            raise ValueError('Public Live creation owner is unavailable')
        if value['state'] in ('created', 'closed'):
            call = value.get('call')
            if (not isinstance(call, dict) or not _text(call.get('session_id'), 1024)
                    or not _text(call.get('sdp'), 65536) or not call['sdp'].startswith('v=0')):
                raise ValueError('Public Live creation receipt is unavailable')
        return value

    @staticmethod
    def _matches(value, owner, request_sha=None):
        if (value.get('owner') != owner
                or request_sha is not None and value.get('request_sha256') != request_sha):
            raise ValueError('Public Live creation belongs to another request or owner')

    def _records(self):
        records = []
        other_bytes = 0
        for index, path in enumerate(self.root.iterdir()):
            if index >= 2 * self.max_records + 1:
                raise ValueError('Public Live creation storage contains too many entries')
            if path.name == '.lock':
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError('Public Live state contains an unsafe entry')
            if len(records) >= self.max_records or other_bytes > self.max_total_bytes:
                raise ValueError('Public Live creation storage is full')
            if path.suffix == '.json':
                value = self._read(path.stem)
                records.append((value, path.stat().st_size))
            else:
                # Interrupted atomic-write fragments count toward capacity too.
                other_bytes += path.stat().st_size
        return records, other_bytes

    def _write(self, value):
        raw = json.dumps(value, allow_nan=False, ensure_ascii=False,
                         separators=(',', ':')).encode()
        if len(raw) > self.max_record_bytes:
            raise ValueError('Public Live creation receipt exceeds its bound')
        records, other_bytes = self._records()
        charged = other_bytes
        for existing, size in records:
            if existing['id'] != value['id']:
                charged += self._reserved(existing, size)
        charged += self._reserved(value, len(raw))
        if charged + len(raw) > self.max_total_bytes:  # Include the temporary atomic write.
            raise ValueError('Public Live receipt storage is full')
        atomic(self._path(value['id']), raw)

    def _reserved(self, value, size):
        if value['state'] not in self.unsettled:return size
        path = self.root / (value['id']+'.events')
        used = path.stat().st_size if path.exists() else 0
        return self.max_record_bytes + max(0, value.get('source_bound',0)-used)

    def read(self, ident, human, frozen):
        owner = self._owner(human, frozen)
        value = self._read(ident)
        self._matches(value, owner)
        return value

    def owned(self, ident, human, binding):
        """Recover this human's originals even while native work is held."""
        value = self._read(ident)
        if value['owner']['human'] != human or value['owner']['frozen']['binding'] != binding:
            raise ValueError('Public Live receipt belongs to another conversation')
        return value

    def prepare(self, ident, human, frozen, seconds=600):
        """Admit one finite microphone visit before permission or billable POST."""
        owner = self._owner(human, frozen)
        if type(seconds) is not int or not 300 <= seconds <= 600:
            raise ValueError('Keep the diagnostic capture deadline')
        with history_lock(self.root / '.lock'):
            if self._path(ident).exists():
                raise ValueError('An existing microphone admission cannot be restarted')
            records, other = self._records()
            active = [v for v, _ in records if v['state'] in self.unsettled]
            if any(v['owner']['human'] == human for v in active) or len(active) >= self.max_active:
                raise LiveUnavailable('prior_creation_needs_review')
            charged = other + sum(self._reserved(v,size) for v,size in records)
            if len(records) >= self.max_records or charged + 2*self.max_record_bytes + 2*1024*1024 > self.max_total_bytes:
                raise LiveUnavailable('creation_storage_full')
            value = {'schema':'daimon.live-creation/v1', 'id':ident, 'owner':owner,
                'state':'prepared', 'created_at':time.time(), 'source_bound':2*1024*1024, 'recordings':[],
                'delegations':{}, 'max_input_pcm_bytes':seconds*32000,
                'admission':{'epoch':self.epoch, 'expires':time.monotonic()+seconds, 'ended':False}}
            self._write(value)
            return {'id':ident, 'remaining_seconds':seconds, 'max_input_pcm_bytes':seconds*32000}

    def end_capture(self, ident, human, binding):
        with history_lock(self.root / '.lock'):
            value = self.owned(ident, human, binding)
            value['admission']['ended'] = True
            if value['state'] == 'prepared':value['state'] = 'not_created'
            self._write(value)

    def check_capture(self, value):
        admission = value.get('admission', {})
        if (admission.get('epoch') != self.epoch or admission.get('ended') is not False
                or time.monotonic() >= admission.get('expires', 0)):
            raise ValueError('Public Live microphone admission ended or needs review')

    def recording(self, ident, human, binding, ordinal, data, provider, *, capture_stop=None):
        """Same receiver media budget; no ASR, utterance inference or work dispatch."""
        from .live_transcription import wav_bytes
        if (capture_stop not in (None,'interrupted_prefix')
                or type(ordinal) is not int or not 0 <= ordinal < 32 or not isinstance(data, bytes)
                or not 44 < len(data) <= 120*32000+44 or (len(data)-44)%2
                or wav_bytes(data[44:]) != data):
            raise ValueError('Select one bounded canonical microphone original')
        digest = hashlib.sha256(data).hexdigest()
        original = str(uuid.uuid5(uuid.UUID(self._ident(ident)), 'public-live-human-recording:'+str(ordinal)))
        directory = private_directory(str(provider.receiver['db_path'])+'.voice')
        with history_lock(self.root / '.lock'):
            value = self.owned(ident, human, binding)
            if 'admission' not in value:raise ValueError('Public Live capture was not admitted')
            if capture_stop and value['admission'].get('ended') is not True:
                raise ValueError('Keep the prefix until its capture is confirmed ended')
            old = next((v for v in value['recordings'] if v['ordinal']==ordinal), None)
            if old is not None and old['audio_sha256'] != digest:
                raise ValueError('Original microphone bytes cannot be replaced')
            if old is not None and old.get('capture_stop') != capture_stop:
                raise ValueError('Original microphone provenance cannot be replaced')
            sizes = {v['ordinal']:v['audio_bytes']-44 for v in value['recordings']}
            # Count bytes durable before a failed receipt write as well.
            for index in range(32):
                key = str(uuid.uuid5(uuid.UUID(ident), 'public-live-human-recording:'+str(index)))
                try:info = (directory/key).lstat()
                except FileNotFoundError:continue
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_mode&0o077 or not 44 < info.st_size <= 120*32000+44):
                    raise ValueError('Public Live original storage changed')
                sizes[index] = max(sizes.get(index, 0), info.st_size-44)
            sizes[ordinal] = max(sizes.get(ordinal, 0), len(data)-44)
            if sum(sizes.values()) > value['max_input_pcm_bytes']:
                raise ValueError('Public Live original audio reached its admitted bound')
            provider.retain_voice_capture(directory, original, data, digest)
            if old is not None and old['archive'] != 'pending':return old
            archive = 'not_selected'
            retention = getattr(provider, 'media_retention', None)
            source = {'id':original, 'entry_binding':value['owner']['frozen']['entry_binding'],
                      'kind':'public_live_voice_recording'}
            if retention and retention.selected(source):
                from .media_retention import RetentionUnavailable
                try:retention.retain(source, 'human', 'audio/wav', data);archive='retained'
                except RetentionUnavailable:archive='pending'
            receipt = {'id':original, 'ordinal':ordinal, 'audio_sha256':digest,
                'audio_bytes':len(data), 'mime':'audio/wav', 'archive':archive, 'work_replay':'never',
                'meaning':'Original microphone recording; no inferred delivery, utterance boundary or work admission'}
            if capture_stop:
                receipt.update(capture_stop=capture_stop,
                    meaning='Client-reported recovered microphone prefix; its unsaved ending may be missing. No inferred delivery or work admission')
            if old is None:value['recordings'].append(receipt)
            else:value['recordings'][value['recordings'].index(old)] = receipt
            self._write(value)
            return receipt

    def event(self, ident, human, frozen, event):
        """Fsync ordered source deltas before forwarding; no inferred utterances."""
        if (not isinstance(event,dict) or not _text(event.get('event_id'),1024)
                or not _text(event.get('type'),128)):
            raise ValueError('Public Live source identity is unavailable')
        raw = json.dumps(event,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()
        digest = hashlib.sha256(raw).hexdigest()
        with history_lock(self.root / '.lock'):
            value = self.read(ident,human,frozen)
            if value['state'] != 'created' or 'source_bound' not in value:
                raise ValueError('Public Live source is not open')
            if event['type']=='session.usage.updated':
                # Cumulative counters are not a second growing diagnostic log.
                if len(raw)>4096:raise ValueError('Public Live usage exceeds bound')
                value['latest_usage'] = event
                self._write(value)
                return True
            # Configuration snapshots can repeat trusted instructions. Retain
            # their source hash and identity, not another serialized context.
            stored = event
            if event['type'] in ('session.started','session.updated'):
                stored = {'type':event['type'],'event_id':event['event_id'],
                          'session_id':event.get('session',{}).get('id')}
            if event['type'] not in ('session.started','session.updated','session.closed',
                    'session.input_transcript.delta','session.output_transcript.delta',
                    'session.delegation.created','response.event','error'):
                return False
            body = json.dumps({'event_id':event['event_id'],'sha256':digest,'event':stored},
                              ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()+b'\n'
            if len(body)>32768:raise ValueError('Public Live source requires an artifact reader')
            path = self.root / (ident+'.events')
            fd = os.open(path,os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'a+b') as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077
                        or info.st_size>value['source_bound']):
                    raise ValueError('Public Live source storage changed')
                cached = self._sources.get(ident)
                file = (info.st_dev,info.st_ino,info.st_size)
                if cached is None or cached['file']!=file:
                    stream.seek(0);data=stream.read(value['source_bound']+1)
                    if data and not data.endswith(b'\n'):raise ValueError('Public Live source append is unconfirmed')
                    rows=[json.loads(line) for line in data.splitlines()]
                    if len(rows)>8192:raise ValueError('Public Live source count exceeds bound')
                    cached={'file':file,'seen':{row['event_id']:row['sha256'] for row in rows}}
                    self._sources[ident]=cached
                duplicate = event['event_id'] in cached['seen']
                if duplicate:
                    if cached['seen'][event['event_id']]!=digest:raise ValueError('Public Live source identity changed')
                else:
                    if info.st_size+len(body)>value['source_bound'] or len(cached['seen'])>=8192:
                        raise ValueError('Public Live source history is full')
                    stream.write(body);stream.flush();os.fsync(stream.fileno())
                    if info.st_size==0:sync_directory(self.root)
                    cached['file']=(info.st_dev,info.st_ino,info.st_size+len(body))
                    cached['seen'][event['event_id']]=digest
            changed = False
            if event['type']=='session.delegation.created':
                delegation=event.get('delegation',{});key=delegation.get('id')
                if (not _text(key,1024) or key in value['delegations'] and
                        value['delegations'][key]['created_source']!=event['event_id']
                        or key not in value['delegations'] and len(value['delegations'])>=32):
                    raise ValueError('Public Live delegation source exceeds bound')
                if key not in value['delegations']:
                    value['delegations'][key]={'state':'pending','source':event['event_id'],'created_source':event['event_id'],
                        'target':delegation.get('target'),'response_id':delegation.get('response_id')}
                changed=True
            if event['type']=='response.event':
                nested=event.get('event',{});key=event.get('delegation_id')
                if key not in value['delegations']:raise ValueError('Backend source has no retained delegation')
                if nested.get('type')=='response.output_item.done':
                    item=nested.get('item',{})
                    if (item.get('type') in ('function_call','custom_tool_call','computer_call',
                            'shell_call','apply_patch_call','mcp_approval_request') or
                            item.get('type')=='tool_search_call' and item.get('execution')=='client'):
                        value['delegations'][key]['needs_client']=True
                        changed=True
                if nested.get('type') in ('response.completed','response.failed','response.incomplete'):
                    value['delegations'][key].update(state=nested['type'],source=event['event_id'])
                    changed=True
            if changed:self._write(value)
            return not duplicate

    def close_intent(self,ident,human,frozen):
        """Never close over a known pending Responses delegation or retry a write."""
        with history_lock(self.root / '.lock'):
            value=self.read(ident,human,frozen)
            if (value['state']!='created' or value.get('close_intent')
                    or any(v['state']=='pending' or v.get('needs_client') for v in value['delegations'].values())):
                return None
            event={'type':'session.close','event_id':str(uuid.uuid4())}
            value['close_intent']=event
            self._write(value)
            return event

    def release_sources(self,ident):
        self._sources.pop(ident,None)

    def source_page(self,ident,human,binding,*,after=0,revision=None):
        value=self.owned(ident,human,binding)
        if type(after) is not int or after<0:raise ValueError('Select an exact source cursor')
        path=self.root/(self._ident(ident)+'.events')
        if not path.exists():
            if after or revision:raise ValueError('Source cursor unavailable')
            return {'items':[],'after':0,'revision':None,'more':False}
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size>value.get('source_bound',0):
                raise ValueError('Public Live source storage changed')
            current=hashlib.sha256(f'{ident}:{info.st_dev}:{info.st_ino}'.encode()).hexdigest()
            if revision is not None and revision!=current or after and revision is None or after>info.st_size:
                raise ValueError('Public Live source cursor changed')
            if after:
                stream.seek(after-1)
                if stream.read(1)!=b'\n':raise ValueError('Select an exact source boundary')
            stream.seek(after);items=[];used=0
            while stream.tell()<info.st_size and len(items)<64 and used<65536:
                start=stream.tell();raw=stream.readline(32769)
                if len(raw)>32768 or not raw.endswith(b'\n'):break
                if used+len(raw)>65536:stream.seek(start);break
                items.append(json.loads(raw));used+=len(raw)
            return {'items':items,'after':stream.tell(),'revision':current,'more':stream.tell()<info.st_size}

    def attach(self, ident, human, frozen, client, *, connect=None):
        value = self.read(ident, human, frozen)
        if value['state'] != 'created':
            raise LiveUnavailable('session_not_attachable')
        return client.attach(self._result(value), connect=connect)

    def create(self, ident, human, frozen, sdp, spec, client):
        """Retain intent before one POST; exact retries only read its outcome.

        A crash after intent is uncertain even if the request might not have
        left. A changed offer/spec/owner cannot reuse that ID. Unknown or active
        public calls block another call for that human, including after restart.
        The caller must freshly authenticate/recheck the frozen owner first.
        """
        owner = self._owner(human, frozen)
        path = self._path(ident)
        request = creation_request(sdp, spec)
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, allow_nan=False, ensure_ascii=False,
            separators=(',', ':')).encode()).hexdigest()
        with history_lock(self.root / '.lock'):
            if path.exists() or path.is_symlink():
                value = self._read(ident)
                self._matches(value, owner)
                if value['state'] != 'prepared':
                    self._matches(value, owner, digest)
                    return self._result(value)
                self.check_capture(value)
                value.update(request_sha256=digest, state='creating')
            else:
                records, other_bytes = self._records()
                active = [v for v, _ in records if v['state'] in self.unsettled]
                if any(v['owner']['human'] == human for v in active):
                    raise LiveUnavailable('prior_creation_needs_review')
                if len(active) >= self.max_active:
                    raise LiveUnavailable('public_voice_capacity')
                charged = other_bytes + sum(self._reserved(v,size) for v,size in records)
                if len(records) >= self.max_records or charged + 2*self.max_record_bytes > self.max_total_bytes:
                    raise LiveUnavailable('creation_storage_full')
                value = {'schema': 'daimon.live-creation/v1', 'id': ident, 'owner': owner,
                    'request_sha256': digest, 'created_at': time.time(), 'state': 'creating'}
            self._write(value)
        # No filesystem lock spans network I/O. The durable intent owns this
        # call across process loss; another writer cannot create or replace it.
        try:
            call = client.create(request['transport']['sdp'], request['session'])
        except Exception as error:
            outcome = error.outcome if isinstance(error, LiveUnavailable) else 'creation_unconfirmed'
            if outcome not in ('creation_rejected', 'project_key_unavailable'):
                outcome = 'creation_unconfirmed'
            status = error.status if isinstance(error, LiveUnavailable) else None
            try:
                with history_lock(self.root / '.lock'):
                    current = self._read(ident)
                    self._matches(current, owner, digest)
                    current.update(state=outcome)
                    if type(status) is int:
                        current['http_status'] = status
                    self._write(current)
            except (OSError, ValueError, RenderError):
                # The already durable creating record remains uncertain.
                raise LiveUnavailable('creation_unconfirmed') from None
            raise LiveUnavailable(outcome, status=status) from None
        try:
            with history_lock(self.root / '.lock'):
                current = self._read(ident)
                self._matches(current, owner, digest)
                if current['state'] != 'creating':
                    raise LiveUnavailable('creation_unconfirmed')
                if (not isinstance(call, LiveCall) or not _text(call.session_id, 1024)
                        or not _text(call.sdp, 65536) or not call.sdp.startswith('v=0')):
                    raise LiveUnavailable('creation_unconfirmed')
                current.update(state='created', call={'session_id': call.session_id, 'sdp': call.sdp})
                self._write(current)
        except (OSError, ValueError, RenderError):
            raise LiveUnavailable('creation_unconfirmed') from None
        return call

    @staticmethod
    def _result(value):
        if value['state'] == 'created':
            return LiveCall(value['call']['session_id'], value['call']['sdp'])
        if value['state'] == 'closed':
            raise LiveUnavailable('session_closed')
        outcome = value['state'] if value['state'] in ('creation_rejected', 'project_key_unavailable') else 'creation_unconfirmed'
        raise LiveUnavailable(outcome, status=value.get('http_status'))

    def observe_closed(self, ident, human, frozen, event):
        """Trusted server-side provider event only; never a browser assertion.

        This records voice finalization/usage. It does not cancel, complete or
        rewrite any independent native/client-delegated work or human question.
        """
        owner = self._owner(human, frozen)
        if (not isinstance(event, dict) or event.get('type') != 'session.closed'
                or not _text(event.get('event_id'), 1024)
                or not isinstance(event.get('session'), dict)
                or event.get('reason') not in ('close_requested', 'expired', 'content',
                    'remote_hangup', 'connection_lost')):
            raise ValueError('Select a confirmed public Live finalization event')
        with history_lock(self.root / '.lock'):
            value = self._read(ident)
            self._matches(value, owner)
            if (value['state'] not in ('created', 'closed')
                    or event['session'].get('id') != value['call']['session_id']):
                raise ValueError('Public Live finalization belongs to another session')
            usage = event.get('usage')
            seconds = usage.get('seconds') if isinstance(usage, dict) else None
            confirmed = type(seconds) in (int, float) and math.isfinite(seconds) and seconds >= 0
            receipt = {'provider_event_id': event['event_id'],
                       'reason': event['reason'], 'usage_seconds': seconds if confirmed else None,
                       'voice_usage_confirmed': confirmed}
            if value['state'] == 'closed':
                previous = value['finalization']
                if (previous['reason'] != receipt['reason']
                        or previous['voice_usage_confirmed'] and confirmed
                        and previous['usage_seconds'] != receipt['usage_seconds']):
                    raise ValueError('Public Live finalization changed')
                if not previous['voice_usage_confirmed'] and confirmed:
                    previous.update(usage_seconds=seconds, voice_usage_confirmed=True,
                                    usage_event_id=event['event_id'])
                    self._write(value)
                return value
            value.update(state='closed', finalization=receipt)
            self._write(value)
            return value
