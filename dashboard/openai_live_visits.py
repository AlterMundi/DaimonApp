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
from .openai_live import LiveCall, LiveUnavailable, creation_request, fork_request, _text
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
        if 'replacement_review' in value:
            review=value['replacement_review']
            if (not isinstance(review,dict) or set(review)!={'target','revision','reviewed_at','final_usage'}
                    or not isinstance(review.get('revision'),str) or len(review['revision'])!=64
                    or any(c not in '0123456789abcdef' for c in review['revision'])
                    or type(review.get('reviewed_at')) not in (int,float)
                    or not math.isfinite(review['reviewed_at']) or review['final_usage']!='unconfirmed'
                    or value.get('backend_mode')!='native' or value['state'] not in ('created','closed')
                    or value.get('admission',{}).get('ended') is not True):
                raise ValueError('Public Live replacement review is unavailable')
            self._ident(review['target'])
        for key in ('replaces','renewal_from','renewal_target'):
            if key in value:self._ident(value[key])
        if 'renewal_ready' in value:
            ready=value['renewal_ready']
            if not isinstance(ready,dict) or set(ready)!={'token','epoch'}:
                raise ValueError('Native renewal readiness is unavailable')
            self._ident(ready['token']);self._ident(ready['epoch'])
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
            if path.suffix == '.json':
                if len(records) >= self.max_records:
                    raise ValueError('Public Live creation storage is full')
                value = self._read(path.stem)
                records.append((value, path.stat().st_size))
            else:
                # Interrupted atomic-write fragments count toward capacity too.
                other_bytes += path.stat().st_size
                if other_bytes > self.max_total_bytes:
                    raise ValueError('Public Live source storage is full')
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

    def _revision(self, value):
        path=self.root/(value['id']+'.events')
        source=hashlib.sha256(private_bytes(path,value.get('source_bound',0))).hexdigest() if path.exists() else None
        return hashlib.sha256(json.dumps([value,source], sort_keys=True, allow_nan=False,
            ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

    def _active(self, records):
        by_id = {v['id']:v for v, _ in records}
        active = []
        for value, _ in records:
            if value.get('renewal_target'):
                target=by_id.get(value['renewal_target'])
                if (target is None or target.get('renewal_from')!=value['id']
                        or target['owner']!=value['owner']):
                    raise ValueError('Renewal admission is unconfirmed; preserve its exact intent')
            if value['state'] not in self.unsettled:continue
            replacement = value.get('replacement_review')
            if replacement:
                target = by_id.get(replacement['target'])
                if (target is None or target.get('replaces') != value['id']
                        or target['owner'] != value['owner']):
                    raise ValueError('Replacement admission is unconfirmed; preserve its exact intent')
                continue
            active.append(value)
        return active

    def return_origin_eligible(self, value):
        """Retired transport is distinct from trusted provider finalization."""
        if value['state']=='closed':return True
        review=value.get('replacement_review')
        if value['state']!='created' or not review:return False
        target=self._read(review['target'])
        return target.get('replaces')==value['id'] and target['owner']==value['owner']

    def replacement_offer(self, human, frozen):
        """Read-only review; never opens voice, ends capture or dispatches work."""
        owner=self._owner(human,frozen)
        with history_lock(self.root / '.lock'):
            records,_=self._records()
            active=[v for v in self._active(records) if v['owner']['human']==human]
            if len(active)!=1:return None
            value=active[0]
            if (value['owner']!=owner or value['state']!='created'
                    or value.get('backend_mode')!='native'
                    or value.get('admission',{}).get('ended') is not True):return None
            return {'id':value['id'],'revision':self._revision(value)}

    def accepted_replacement(self,human,frozen,replacement):
        """Read a consumed review only when its new attempt never created a call."""
        if not isinstance(replacement,dict) or set(replacement)!={'id','revision'}:return None
        owner=self._owner(human,frozen)
        with history_lock(self.root/'.lock'):
            value=self._read(replacement['id']);self._matches(value,owner)
            review=value.get('replacement_review')
            if (value['state']!='created' or value.get('backend_mode')!='native'
                    or value.get('admission',{}).get('ended') is not True
                    or not review or review['revision']!=replacement['revision']):return None
            target=self._read(review['target']);self._matches(target,owner)
            if (target.get('replaces')!=value['id'] or target['state']!='not_created'
                    or target.get('backend_mode')!='native' or target.get('admission',{}).get('ended') is not True
                    or target.get('request_sha256') or target.get('call')):return None
            return dict(replacement)

    def startup_failure(self,ident,human,frozen,stage,code):
        """One fixed diagnostic; no exception text, retries or outcome rewriting."""
        if (stage not in ('configuration','native_context','offer','creation','sideband') or code not in (
                'context_changed','context_pending','startup_bound','native_unavailable',
                'client_disconnected','timeout','unavailable','invalid_state','transport_unavailable')):
            raise ValueError('Select a fixed voice startup diagnostic')
        with history_lock(self.root/'.lock'):
            value=self.read(ident,human,frozen)
            if 'startup_failure' not in value:
                value['startup_failure']={'stage':stage,'code':code};self._write(value)

    def recording_failure(self, ident, human, binding, ordinal, stage, status, code):
        """First bounded technical observation; never a retry or source receipt."""
        if (type(ordinal) is not int or not 0 <= ordinal < 32
                or stage not in ('admission','body','retention','native_enrollment')
                or type(status) is not int or not 400 <= status <= 599
                or code not in ('http_error','client_disconnected','storage_unavailable',
                                'io_error','invalid_state','native_unavailable')):
            raise ValueError('Select a fixed original-upload diagnostic')
        with history_lock(self.root/'.lock'):
            value=self.owned(ident,human,binding)
            if 'recording_failure' not in value:
                value['recording_failure']={'ordinal':ordinal,'stage':stage,
                    'status':status,'code':code,'observed_at':time.time(),
                    'original_retained':any(r['ordinal']==ordinal for r in value['recordings'])}
                self._write(value)

    def prepare(self, ident, human, frozen, seconds=600, *, resume_spec=None, backend_mode=None, replacement=None, voice_choice=None, voice_continuation=None, renewal=None):
        """Admit one finite microphone visit before permission or billable POST."""
        owner = self._owner(human, frozen)
        if backend_mode is not None and backend_mode not in ('responses','native'):
            raise ValueError('Select the admitted public voice backend')
        if resume_spec is not None:
            creation_request('v=0 validation only',resume_spec)
            if resume_spec.get('store') is not True:raise ValueError('Stored continuation requires explicit project storage selection')
        if type(seconds) is not int or not 300 <= seconds <= 600:
            raise ValueError('Keep the diagnostic capture deadline')
        with history_lock(self.root / '.lock'):
            if self._path(ident).exists():
                raise ValueError('An existing microphone admission cannot be restarted')
            records, other = self._records()
            active = self._active(records)
            reviewed=None
            predecessor=None
            if renewal is not None:
                if (backend_mode!='native' or replacement is not None or resume_spec is not None
                        or not isinstance(renewal,dict) or set(renewal)!={'id','token'}):
                    raise ValueError('Select one confirmed native transport renewal')
                predecessor=self._read(self._ident(renewal['id']))
                self._matches(predecessor,owner)
                ready=predecessor.get('renewal_ready',{})
                if (predecessor['state']!='closed' or predecessor.get('backend_mode')!='native'
                        or predecessor.get('finalization',{}).get('reason') not in ('close_requested','expired')
                        or (predecessor.get('finalization',{}).get('reason')=='expired'
                            and predecessor['finalization'].get('voice_usage_confirmed') is not True)
                        or ready.get('epoch')!=self.epoch or ready.get('token')!=renewal['token']
                        or not ready.get('token') or predecessor.get('renewal_target')
                        or voice_continuation!=predecessor['id']):
                    raise ValueError('Prior transport/context renewal is not confirmed or already claimed')
            if replacement is not None:
                if (backend_mode!='native' or resume_spec is not None
                        or not isinstance(replacement,dict) or set(replacement)!={'id','revision'}):
                    raise ValueError('Select an explicit fresh native replacement')
                reviewed=self._read(replacement['id'])
                self._matches(reviewed,owner)
                if (reviewed['id']==ident or reviewed not in active or reviewed['state']!='created'
                        or reviewed.get('backend_mode')!='native'
                        or reviewed.get('admission',{}).get('ended') is not True
                        or self._revision(reviewed)!=replacement['revision']):
                    raise ValueError('The disconnected visit changed; review its current state')
                active=[v for v in active if v['id']!=reviewed['id']]
            if any(v['owner']['human'] == human for v in active) or len(active) >= self.max_active:
                raise LiveUnavailable('prior_creation_needs_review')
            charged = other + sum(self._reserved(v,size) for v,size in records)
            if len(records) >= self.max_records or charged + 2*self.max_record_bytes + 2*1024*1024 > self.max_total_bytes:
                raise LiveUnavailable('creation_storage_full')
            value = {'schema':'daimon.live-creation/v1', 'id':ident, 'owner':owner,
                'state':'prepared', 'created_at':time.time(), 'source_bound':2*1024*1024, 'recordings':[],
                'delegations':{}, 'max_input_pcm_bytes':seconds*32000,
                'admission':{'epoch':self.epoch, 'expires':time.monotonic()+seconds, 'ended':False}}
            if backend_mode is not None:value['backend_mode']=backend_mode
            if backend_mode=='native':
                previous=[v for v,_ in records if v['owner']==owner and self.return_origin_eligible(v)
                          and v.get('backend_mode')=='native']
                if reviewed is not None:previous.append(reviewed)
                if previous:
                    parent=predecessor or max(previous,key=lambda v:(v['created_at'],v['id']))
                    value['native_continuation_from']=parent['id']
                    if parent.get('native_return_scan'):
                        value['native_return_scan']=parent['native_return_scan']
            if voice_choice is not None or voice_continuation is not None:
                from .voice_studio import validate_choice
                inherited=reviewed
                if voice_continuation is not None:
                    inherited=self._read(self._ident(voice_continuation))
                    self._matches(inherited,owner)
                    if (inherited['id']==ident or inherited.get('backend_mode')!=backend_mode
                            or not self.return_origin_eligible(inherited) and (reviewed is None or reviewed['id']!=inherited['id'])
                            or reviewed is not None and reviewed['id']!=inherited['id']):
                        raise ValueError('Voice continuation needs the same closed or reviewed visit')
                if inherited is not None and inherited.get('voice_choice') is not None:
                    value['voice_choice']=validate_choice(inherited['voice_choice'])
                    value['voice_continuation_from']=inherited['id']
                elif voice_choice is not None or renewal is None:
                    value['voice_choice']=validate_choice(voice_choice)
            if resume_spec is not None:
                value['continuity']='stored_fork'
                value['configuration_sha256']=self._configuration(resume_spec)
                previous=[v for v,_ in records if v['owner']==owner and v['state']=='closed']
                if previous:
                    ancestors={v.get('continuation_from') for v in previous}
                    tips=[v for v in previous if v['id'] not in ancestors]
                    if len(tips)!=1:raise LiveUnavailable('stored_continuation_needs_review')
                    parent=tips[0]
                    value['source_session_id']=self._fork_source(parent,owner,value['configuration_sha256'])
                    value['continuation_from']=parent['id']
            if reviewed is not None:
                # Claim before destination admission. A partial two-file write
                # remains held; neither creation nor native work is replayable.
                value['replaces']=reviewed['id']
                reviewed['replacement_review']={'target':ident,'revision':replacement['revision'],
                    'reviewed_at':time.time(),'final_usage':'unconfirmed'}
                self._write(reviewed)
            if predecessor is not None:
                # Freeze the sole successor before destination admission. Lost
                # receipts/partial writes never authorize another provider POST.
                value['renewal_from']=predecessor['id']
                predecessor['renewal_target']=ident
                self._write(predecessor)
            self._write(value)
            return {'id':ident, 'remaining_seconds':seconds, 'max_input_pcm_bytes':seconds*32000,
                'continuity':value.get('continuity','fresh'),'continued':value.get('continuation_from') is not None,
                **({'voice_choice':value['voice_choice']} if 'voice_choice' in value else {})}


    def ready_for_renewal(self,ident,human,frozen,*,allow_expired=False):
        """Server-only barrier, after confirmed close AND settled native context."""
        with history_lock(self.root / '.lock'):
            value=self.read(ident,human,frozen)
            final=value.get('finalization',{})
            planned=(value.get('client_close_reason')=='transport_renewal'
                     and final.get('reason')=='close_requested')
            expired=(allow_expired is True and final.get('reason')=='expired'
                     and final.get('voice_usage_confirmed') is True
                     and value.get('client_close_reason') in (None,'transport_renewal'))
            if (value['state']!='closed' or value.get('backend_mode')!='native'
                    or not (planned or expired)
                    or value.get('admission',{}).get('ended') is not True
                    or any(work.get('target')=='client' and
                        ('source_seal' not in work or 'native_pipeline' not in work)
                        for work in value['delegations'].values())
                    or value.get('renewal_ready') or value.get('renewal_target')):
                raise ValueError('Native transport is not ready for automatic renewal')
            ready={'token':str(uuid.uuid4()),'epoch':self.epoch}
            value['renewal_ready']=ready;self._write(value)
            return {'id':ident,'token':ready['token']}

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
        if isinstance(event,dict) and event.get('type') in (
                'session.input_audio.append','session.output_audio.delta'):
            # The trusted sideband also carries raw media without event IDs.
            # WebRTC owns audio; never journal or forward these frame payloads.
            return False
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
                    'session.thinking.appended','session.commentary.appended',
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
            if event['type'] in ('session.thinking.appended','session.commentary.appended'):
                from .openai_live_native_results import observe_append
                changed = observe_append(value, event)
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
                work=value['delegations'][key]
                if nested.get('type')=='response.created':
                    response=nested.get('response',{}).get('id')
                    if not _text(response,1024):raise ValueError('Backend response identity unavailable')
                    previous=work.get('continuation_intent')
                    work['response_id']=response
                    if previous and response!=previous['response_id'] and not work.get('unsupported_client'):
                        work['needs_client']=False
                    work['state']='pending';changed=True
                if nested.get('type')=='response.output_item.done':
                    item=nested.get('item',{})
                    if (item.get('type') in ('function_call','custom_tool_call','computer_call',
                            'shell_call','apply_patch_call','mcp_approval_request') or
                            item.get('type')=='tool_search_call' and item.get('execution')=='client'):
                        value['delegations'][key]['needs_client']=True
                        calls=value.setdefault('client_calls',{})
                        call_id=item.get('call_id')
                        if (item.get('type')=='function_call' and _text(call_id,1024)
                                and _text(item.get('name'),128) and _text(item.get('arguments'),4096)):
                            selected={'delegation':key,'name':item['name'],'arguments':item['arguments'],
                                'response_id':work.get('response_id')}
                            if call_id in calls:
                                if any(calls[call_id][k]!=v for k,v in selected.items()):
                                    raise ValueError('Backend tool call identity changed')
                            else:
                                if len(calls)>=16:raise ValueError('Backend tool call capacity reached')
                                calls[call_id]={**selected,'state':'observed','source':event['event_id']}
                        else:work['unsupported_client']=True
                        changed=True
                if nested.get('type') in ('response.completed','response.failed','response.incomplete'):
                    if work.get('continuation_intent') and nested.get('response',{}).get('id')!=work.get('response_id'):
                        raise ValueError('Backend completion belongs to another response')
                    value['delegations'][key].update(state=nested['type'],source=event['event_id'])
                    changed=True
            if changed:self._write(value)
            return not duplicate

    def tool_command(self,ident,human,frozen,call_id,output):
        """Persist the exact result intent before one sideband write, never retry."""
        if not _text(output,8192):raise ValueError('Bounded tool result required')
        with history_lock(self.root / '.lock'):
            value=self.read(ident,human,frozen)
            if value['state']!='created':raise ValueError('Tool visit is not open')
            call=value.get('client_calls',{}).get(call_id)
            if call is None:raise ValueError('Tool call has no trusted source')
            if call['state']!='observed':return None
            command={'type':'response.item.create','event_id':str(uuid.uuid4()),
                'item':{'type':'function_call_output','call_id':call_id,'output':output}}
            call.update(state='result_intent',command=command)
            self._write(value)
            return command

    def tool_sent(self,ident,human,frozen,call_id):
        """Record a completed socket send, not a provider acknowledgment."""
        with history_lock(self.root / '.lock'):
            value=self.read(ident,human,frozen);call=value['client_calls'][call_id]
            if call['state']!='result_intent':raise ValueError('Tool result intent changed')
            call['state']='result_sent';self._write(value)

    def tool_continue(self,ident,human,frozen,delegation):
        with history_lock(self.root / '.lock'):
            value=self.read(ident,human,frozen);work=value['delegations'][delegation]
            response=work.get('response_id')
            calls=[c for c in value.get('client_calls',{}).values()
                   if c['delegation']==delegation and c['response_id']==response]
            previous=work.get('continuation_intent')
            if (value['state']!='created' or work['state']!='response.completed'
                    or work.get('unsupported_client') or not _text(response,1024)
                    or not calls or any(c['state']!='result_sent' for c in calls)
                    or previous and previous['response_id']==response):return None
            command={'type':'response.create','event_id':str(uuid.uuid4())}
            work['continuation_intent']={'response_id':response,'command':command}
            work['state']='pending'
            self._write(value)
            return command

    # Fixed browser observations, not a claim about hardware/network cause.
    source_close_reasons=frozenset(('source_owner_changed','source_boundary_limit',
        'source_boundary_overlap','source_boundary_timeout','source_capture_unavailable',
        'source_upload_unconfirmed','source_boundary_changed'))
    close_reasons=source_close_reasons|frozenset(('explicit_stop','source_unconfirmed','local_storage','event_processing',
        'native_output','transport_failed','capture_unavailable','capture_bound','binding_changed',
        'visit_deadline','activation_failed','server_finishing','transport_renewal'))

    def record_close_reason(self,ident,human,frozen,reason):
        # A bounded browser diagnostic is not evidence of physical/network cause.
        # It never changes close commands, source authority or native work.
        if not isinstance(reason,str) or reason not in self.close_reasons:raise ValueError('Select a known voice close diagnostic')
        with history_lock(self.root / '.lock'):
            value=self.read(ident,human,frozen)
            if 'client_close_reason' not in value:
                value['client_close_reason']=reason;self._write(value)

    def close_intent(self,ident,human,frozen):
        """Drain session-owned Responses; native client work keeps its own owner."""
        with history_lock(self.root / '.lock'):
            value=self.read(ident,human,frozen)
            if (value['state']!='created' or value.get('close_intent')
                    or any((v['state']=='pending' or v.get('needs_client'))
                        and not (value.get('backend_mode')=='native' and v.get('target')=='client')
                        for v in value['delegations'].values())):
                return None
            event={'type':'session.close','event_id':str(uuid.uuid4())}
            value['close_intent']=event
            self._write(value)
            return event

    def release_sources(self,ident):
        self._sources.pop(ident,None)

    def visits(self,human,binding,*,before=None):
        """One owner-scoped source visit per page; never controls or model input."""
        with history_lock(self.root / '.lock'):
            records,_=self._records()
            selected=[v for v,_ in records if v['owner']['human']==human
                and v['owner']['frozen']['binding']==binding and v['state'] in ('created','closed')]
            selected.sort(key=lambda v:(v['created_at'],v['id']),reverse=True)
            if before is not None:
                self._ident(before)
                index=next((n for n,v in enumerate(selected) if v['id']==before),None)
                if index is None:raise ValueError('Voice history cursor belongs to another conversation')
                selected=selected[index+1:]
            page=selected[:1]
            return {'visits':[{k:v[k] for k in ('id','created_at','state')} for v in page],
                'more':len(selected)>1,'before':page[-1]['id'] if len(selected)>1 else None}

    def native_return_origin(self,ident,human,frozen):
        """One historical work reference per live poll, within existing journal bounds.

        All owners/512records/32MiB remain bounded by _records. The cursor is two
        identifiers, never a copied archive. No media, inference or work dispatch.
        """
        owner=self._owner(human,frozen)
        with history_lock(self.root / '.lock'):
            current=self.read(ident,human,frozen)
            self.check_capture(current)
            if current.get('backend_mode')!='native':raise ValueError('Select the native voice comparison')
            records,_=self._records()
            # Closure/owner/work proofs establish eligibility. Wall-clock
            # ordering is presentation, not authority to lose a retained job.
            records=[v for v,_ in records if v['owner']==owner and self.return_origin_eligible(v) and v['id']!=ident]
            records.sort(key=lambda v:(v['created_at'],v['id']))
            origins=[{'visit':v['id'],'delegation':key} for v in records
                     for key,work in sorted(v['delegations'].items())
                     if work.get('target')=='client' and work.get('native_work',{}).get('state')=='observed']
            if not origins:return None
            previous=current.get('native_return_scan')
            index=0
            if previous is not None:
                if previous not in origins:raise ValueError('Native return cursor needs review; no reset or work replay')
                index=(origins.index(previous)+1)%len(origins)
            selected=origins[index]
            current['native_return_scan']=selected
            self._write(current)
            return dict(selected)

    def source_page(self,ident,human,binding,*,after=0,revision=None,with_offsets=False,with_raw_records=False):
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
            stream.seek(after);items=[];offsets=[];raw_records=[];used=0
            while stream.tell()<info.st_size and len(items)<64 and used<65536:
                start=stream.tell();raw=stream.readline(32769)
                if len(raw)>32768 or not raw.endswith(b'\n'):
                    stream.seek(start);break
                if used+len(raw)>65536:stream.seek(start);break
                items.append(json.loads(raw));offsets.append(stream.tell());used+=len(raw)
                if with_raw_records:raw_records.append(raw)
            return {'items':items,'after':stream.tell(),'revision':current,'more':stream.tell()<info.st_size,
                **({'offsets':offsets} if with_offsets else {}),
                **({'raw_records':raw_records} if with_raw_records else {})}

    def attach(self, ident, human, frozen, client, *, connect=None):
        value = self.read(ident, human, frozen)
        if value['state'] != 'created':
            raise LiveUnavailable('session_not_attachable')
        return client.attach(self._result(value), connect=connect)

    @staticmethod
    def _configuration(spec):
        return hashlib.sha256(json.dumps(spec,sort_keys=True,ensure_ascii=False,
            allow_nan=False,separators=(',',':')).encode()).hexdigest()

    @staticmethod
    def _fork_source(parent,owner,configuration):
        if (parent['owner']!=owner or parent['state']!='closed'
                or parent.get('store_requested') is not True
                or parent.get('configuration_sha256')!=configuration
                or any(v.get('state')!='response.completed' or v.get('needs_client')
                    for v in parent.get('delegations',{}).values())):
            raise LiveUnavailable('stored_continuation_needs_review')
        return parent['call']['session_id']

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
        configuration=self._configuration(spec)
        source=None
        with history_lock(self.root / '.lock'):
            retained=self._read(ident) if path.exists() or path.is_symlink() else None
            if retained is not None:
                self._matches(retained,owner)
                if retained.get('continuity')=='stored_fork' and retained.get('configuration_sha256')!=configuration:
                    raise ValueError('Stored continuation configuration changed')
                if retained.get('continuation_from'):
                    source=retained.get('source_session_id')
                    if retained['state']=='prepared':
                        parent=self._read(retained['continuation_from'])
                        if source!=self._fork_source(parent,owner,configuration):
                            raise ValueError('Stored source changed before creation')
                    request=fork_request(source,sdp)
            # Include the operation target in the durable request identity; a
            # fork can never be retried as fresh creation or another parent.
            identity={'request':request,'source_session':source} if source is not None else request
            digest = hashlib.sha256(json.dumps(identity,
                sort_keys=True,allow_nan=False,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
            if retained is not None:
                value = retained
                self._matches(value, owner)
                if value['state'] != 'prepared':
                    self._matches(value, owner, digest)
                    return self._result(value)
                self.check_capture(value)
                value.update(request_sha256=digest, state='creating',configuration_sha256=configuration,store_requested=spec.get('store') is True)
            else:
                records, other_bytes = self._records()
                active = self._active(records)
                if any(v['owner']['human'] == human for v in active):
                    raise LiveUnavailable('prior_creation_needs_review')
                if len(active) >= self.max_active:
                    raise LiveUnavailable('public_voice_capacity')
                charged = other_bytes + sum(self._reserved(v,size) for v,size in records)
                if len(records) >= self.max_records or charged + 2*self.max_record_bytes > self.max_total_bytes:
                    raise LiveUnavailable('creation_storage_full')
                value = {'schema': 'daimon.live-creation/v1', 'id': ident, 'owner': owner,
                    'request_sha256': digest, 'created_at': time.time(), 'state': 'creating',
                    'configuration_sha256':configuration,'store_requested':spec.get('store') is True}
            self._write(value)
        # No filesystem lock spans network I/O. The durable intent owns this
        # call across process loss; another writer cannot create or replace it.
        try:
            call = (client.fork(source,request['transport']['sdp']) if source is not None
                else client.create(request['transport']['sdp'], request['session']))
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
                        or source is not None and call.session_id==source
                        or not _text(call.sdp, 65536) or not call.sdp.startswith('v=0')):
                    raise LiveUnavailable('creation_unconfirmed')
                current.update(state='created', call={'session_id': call.session_id, 'sdp': call.sdp})
                self._write(current)
        except (OSError, ValueError, RenderError):
            raise LiveUnavailable('creation_unconfirmed') from None
        return call

    @staticmethod
    def _result(value):
        if value.get('replacement_review'):
            raise LiveUnavailable('session_retired')
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
