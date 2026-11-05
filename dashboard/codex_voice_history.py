"""Bounded app projection of native voice visits and immutable media receipts.

Core's original thread history remains canonical. These records link its public
transcripts to app-captured original audio; they are not a model memory/context
store. A bounded flat startup window restores actual voice sources through
V3 initialItems; previous startup envelopes are never included recursively.
"""
from contextlib import contextmanager, ExitStack
import hashlib
import json
import os
import re
import stat
import time
import uuid

from .private_state import private_directory, read_json, write_json
from scripts.speech_render import lock, RenderError


@contextmanager
def history_lock(path):
    """Serialize short metadata/media commits with a finite acquisition bound."""
    deadline=time.monotonic()+2
    with ExitStack()as stack:
        while True:
            try:
                stack.enter_context(lock(path));break
            except RenderError as error:
                if str(error)!='render-in-progress':
                    raise ValueError('Native voice history lock is unavailable')from None
                if time.monotonic()>=deadline:
                    raise ValueError('Native voice history writer is still busy')from None
                time.sleep(.01)
        yield


class IncompleteTranscript(ValueError):
    """Retained sources are not confirmed complete for a safe reconnect."""


class CodexVoiceHistory:
    max_visits=512
    max_total_bytes=32*1024*1024
    max_record_bytes=65536

    def __init__(self, directory):
        self.root=private_directory(directory)

    @staticmethod
    def ident(value):
        if not isinstance(value,str) or str(uuid.UUID(value))!=value:
            raise ValueError('Select one native voice visit')
        return value

    def _write(self,value):
        raw=json.dumps(value).encode()
        files=list(self.root.glob('*.json'))
        path=self.root/(self.ident(value['id'])+'.json')
        old=path.stat().st_size if path.exists() else 0
        if (len(raw)>self.max_record_bytes or len(files)+(not path.exists())>self.max_visits
                or sum(p.stat().st_size for p in files)-old+len(raw)>self.max_total_bytes):
            raise ValueError('Native voice history reached its retention bound')
        write_json(path,value)

    def open(self,ident,human,frozen,native_session,session_seconds=600,*,identity_sha256=None,startup=None):
        self.ident(ident);self.ident(native_session)
        if type(session_seconds)is not int or not 1<=session_seconds<=600:
            raise ValueError('Select a bounded native voice duration')
        if identity_sha256 is not None and (not isinstance(identity_sha256,str)or not re.fullmatch('[a-f0-9]{64}',identity_sha256)):
            raise ValueError('Select one owner identity revision')
        with history_lock(self.root/'.lock'):
            if (self.root/(ident+'.json')).exists():
                raise ValueError('Native voice visit already exists; inspect it instead of starting again')
            sequence=max((read_json(path).get('sequence',0)for path in self.root.glob('*.json')),default=0)+1
            value={'schema':'daimon.codex-voice-visit/v1','id':ident,'human':human,
                'binding':frozen['binding'],'entry_binding':frozen['entry_binding'],
                'native_thread':frozen['native_thread'],'native_session':native_session,
                'identity_sha256':identity_sha256,'sequence':sequence,
                'startup_sources':[]if startup is None else startup['sources'],
                'startup_digest':None if startup is None else startup['digest'],
                'startup_more':False if startup is None else startup['more'],
                'created_at':time.time(),'state':'opening','transcript_complete':False,'items':[],'recordings':[],
                'max_input_pcm_bytes':session_seconds*32000}
            self._write(value)
            return value

    def continuation(self,human,frozen):
        """Flat immutable source window, never another visit's startup envelope."""
        with history_lock(self.root/'.lock'):
            visits=[read_json(path)for path in self.root.glob('*.json')]
            visits=[value for value in visits if value.get('human')==human
                and value.get('binding')==frozen['binding']
                and value.get('entry_binding')==frozen['entry_binding']
                and value.get('native_thread')==frozen['native_thread']]
            if any(value.get('transcript_complete')is not True for value in visits):
                raise IncompleteTranscript('Previous native voice transcript needs reconciliation before reconnecting')
            visits.sort(key=lambda value:(value.get('sequence',0),value['created_at'],value['id']))
            rows=[(value,item)for value in visits for item in value['items']]
            selected=[]
            # Complete newest items only. No clipping, summary inference or
            # previously serialized startup history becomes a source again.
            for value,item in reversed(rows):
                role=item['role'];text=item['text']
                if role not in ('user','assistant')or not isinstance(text,str)or not text or'\0'in text:
                    raise ValueError('Retained native transcript changed')
                row={'item':{'role':role,'text':text},'source':{'visit':value['id'],
                    'id':item['id'],'sha256':hashlib.sha256(text.encode()).hexdigest()}}
                candidate=[row,*selected]
                if len(candidate)>32 or len(json.dumps(candidate,ensure_ascii=False).encode())>18432:break
                selected=candidate
            sources=[row['source']for row in selected];items=[row['item']for row in selected]
            digest=hashlib.sha256(json.dumps(selected,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
            return {'items':items,'sources':sources,'digest':digest,'more':len(selected)<len(rows)}

    def incomplete(self,human,frozen):
        with history_lock(self.root/'.lock'):
            return [value['native_session']for path in self.root.glob('*.json')
                if (value:=read_json(path)).get('human')==human
                and value.get('binding')==frozen['binding']and value.get('entry_binding')==frozen['entry_binding']
                and value.get('native_thread')==frozen['native_thread']and value.get('transcript_complete')is not True]

    def reconcile(self,human,frozen,sources):
        """Recover missing items from exact closed native generations, never replace."""
        with history_lock(self.root/'.lock'):
            for path in self.root.glob('*.json'):
                value=read_json(path)
                if(value.get('human')!=human or value.get('binding')!=frozen['binding']
                        or value.get('entry_binding')!=frozen['entry_binding']
                        or value.get('native_thread')!=frozen['native_thread']or value.get('transcript_complete')is True):continue
                source=sources[value['native_session']]
                old={item['id']:item for item in value['items']}
                native={item['id']:item for item in source['items']}
                if any(ident not in native or {key:item[key]for key in ('id','role','text')}!=native[ident]
                        for ident,item in old.items()):
                    raise ValueError('Retained transcript differs from canonical native source')
                value['items']=[old[item['id']]if item['id']in old else {**item,'observed_at':time.time()}
                    for item in source['items']]
                value.update(transcript_complete=True,reconciliation_sha256=source['source_sha256'])
                self._write(value)

    def abandon_unstarted(self,ident,human,binding):
        """Caller confirms voice.start was never invoked; no native media existed."""
        with history_lock(self.root/'.lock'):
            value=self.read(ident,human,binding)
            if value['state']!='opening' or value['items']:
                raise ValueError('Only an empty unstarted visit can be abandoned')
            value.update(state='closed',transcript_complete=True,native_start='not_attempted')
            self._write(value);return value

    def complete_transcript(self,ident,human,binding):
        """Commit after observed native closure and successful event drain.

        Independent of backend collector completion. Failed item writes or a
        process crash leave this false and prevent silent incomplete restore.
        """
        with history_lock(self.root/'.lock'):
            value=self.read(ident,human,binding)
            value['transcript_complete']=True
            self._write(value);return value

    def read(self,ident,human,binding):
        value=read_json(self.root/(self.ident(ident)+'.json'))
        if value.get('human')!=human or value.get('binding')!=binding:
            raise ValueError('Native voice history belongs to another binding')
        return value

    def state(self,ident,human,binding,state):
        if state not in ('active','closed','review'):raise ValueError('Unknown native voice state')
        with history_lock(self.root/'.lock'):
            value=self.read(ident,human,binding)
            if value['state']=='closed' and state!='closed':return value
            value['state']=state
            self._write(value);return value

    def item(self,ident,human,binding,item):
        if (not isinstance(item,dict) or item.get('type')!='transcriptSegment'
                or item.get('role') not in ('user','assistant')
                or not isinstance(item.get('id'),str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}',item['id'])
                or not isinstance(item.get('text'),str) or len(item['text'].encode())>16384 or '\0' in item['text']):
            raise ValueError('Select a completed native transcript source')
        with history_lock(self.root/'.lock'):
            value=self.read(ident,human,binding)
            if item.get('realtimeSessionId')!=value['native_session']:
                raise ValueError('Native transcript belongs to another voice generation')
            selected={k:item[k]for k in ('id','role','text')}
            old=next((v for v in value['items']if v['id']==item['id']),None)
            if old is not None:
                if {k:old[k]for k in selected}!=selected:raise ValueError('Completed native transcript changed')
                return value
            if len(value['items'])>=256:raise ValueError('Native transcript source capacity reached')
            selected['observed_at']=time.time()
            value['items'].append(selected);self._write(value);return value

    def recording(self,ident,human,binding,ordinal,data,provider):
        if type(ordinal)is not int or not 0<=ordinal<32:
            raise ValueError('Native voice recording index exceeds bound')
        from .live_transcription import wav_bytes
        if (not isinstance(data,bytes) or not 44<len(data)<=120*32000+44
                or (len(data)-44)%2 or wav_bytes(data[44:])!=data):
            raise ValueError('Select canonical bounded original PCM audio')
        digest=hashlib.sha256(data).hexdigest()
        original=str(uuid.uuid5(uuid.UUID(self.ident(ident)),'human-recording:'+str(ordinal)))
        with history_lock(self.root/'.lock'):
            value=self.read(ident,human,binding)
            old=next((r for r in value['recordings']if r['ordinal']==ordinal),None)
            if old is not None:
                if old['audio_sha256']!=digest:raise ValueError('Original recording cannot be replaced')
            # Preserve the same shared receiver store/budgets as ordinary voice.
            # This path never invokes ASR, input dispatch, native work or Retry.
            from pathlib import Path
            directory=private_directory(Path(str(provider.receiver['db_path'])+'.voice'))
            if old is None:
                # A crash/write failure can leave original bytes durable before
                # their receipt. Count those deterministic ordinals as well as
                # committed records; changing ordinal cannot evade visit bounds.
                sizes={r['ordinal']:r['audio_bytes']-44 for r in value['recordings']}
                for index in range(32):
                    key=str(uuid.uuid5(uuid.UUID(ident),'human-recording:'+str(index)))
                    try:info=(directory/key).lstat()
                    except FileNotFoundError:continue
                    if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid()
                            or info.st_mode&0o077 or not 44<info.st_size<=120*32000+44):
                        raise ValueError('Native voice original storage changed')
                    sizes[index]=max(sizes.get(index,0),info.st_size-44)
                sizes[ordinal]=max(sizes.get(ordinal,0),len(data)-44)
                if sum(sizes.values())>value['max_input_pcm_bytes']:
                    raise ValueError('Native voice visit reached its original audio bound')
            provider.retain_voice_capture(directory,original,data,digest)
            if old is not None and old['archive']!='pending':return old
            archive='not_selected'
            retention=getattr(provider,'media_retention',None)
            source={'id':original,'entry_binding':value['entry_binding'],'kind':'native_codex_voice_recording'}
            if retention and retention.selected(source):
                from .media_retention import RetentionUnavailable
                try:retention.retain(source,'human','audio/wav',data);archive='retained'
                except RetentionUnavailable:archive='pending'
            receipt={'id':original,'ordinal':ordinal,'audio_sha256':digest,'audio_bytes':len(data),
                'mime':'audio/wav','archive':archive,'native_replay':'never',
                'meaning':'App microphone recording for this visit; no inferred word timing or new work admission'}
            if old is None:value['recordings'].append(receipt)
            else:value['recordings'][value['recordings'].index(old)]=receipt
            self._write(value)
            return receipt

    def list(self,human,binding):
        values=[]
        for path in self.root.glob('*.json'):
            value=read_json(path)
            if value.get('human')==human and value.get('binding')==binding:
                values.append({k:value[k]for k in ('id','created_at','state')})
        return sorted(values,key=lambda v:v['created_at'],reverse=True)[:16]


def native_transcripts(path,native,sessions,*,expected_file):
    """Bounded canonical closed-generation recovery; no RPC/input or inference."""
    from pathlib import Path
    sessions=set(sessions)
    if not sessions or len(sessions)>512:raise ValueError('Select bounded native voice generations')
    for ident in sessions:CodexVoiceHistory.ident(ident)
    fd=os.open(Path(path),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb')as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode)or(info.st_dev,info.st_ino)!=expected_file:
            raise ValueError('Native history changed before recovery')
        header=stream.readline(2*1024*1024+1)
        if len(header)>2*1024*1024 or not header.endswith(b'\n'):
            raise ValueError('Native history identity exceeds bound')
        first=json.loads(header)
        if first.get('type')!='session_meta'or first.get('payload',{}).get('id')!=native:
            raise ValueError('Native history belongs to another thread')
        begin=stream.tell();end=info.st_size
        start=max(begin,end-4*1024*1024)
        stream.seek(start)
        if start>begin:stream.readline(2*1024*1024+1)  # Discard crossing record.
        values={key:{'items':[],'started':False,'closed':False,'source_sha256':hashlib.sha256(header)}for key in sessions}
        while stream.tell()<end:
            raw=stream.readline(min(2*1024*1024+1,end-stream.tell()))
            if len(raw)>2*1024*1024 or not raw.endswith(b'\n'):
                raise ValueError('Native history has an incomplete or oversized record')
            row=json.loads(raw)
            if row.get('type')!='realtime_item':continue
            item=row.get('payload',{});value=values.get(item.get('realtime_session_id'))
            if value is None:continue
            value['source_sha256'].update(raw)
            if value['closed']:raise ValueError('Native voice has sources after closure')
            kind=item.get('type')
            if kind=='realtime_session_started':
                if value['started']:raise ValueError('Native voice generation repeated')
                value['started']=True
            elif not value['started']:raise ValueError('Native voice start is outside recovery window')
            elif kind=='transcript_segment':
                source={'id':item.get('id'),'role':item.get('role'),'text':item.get('text')}
                if (not isinstance(source['id'],str)or not re.fullmatch('[A-Za-z0-9_-]{1,128}',source['id'])
                        or source['role']not in ('user','assistant')or not isinstance(source['text'],str)
                        or not source['text']or'\0'in source['text']or len(source['text'].encode())>16384
                        or len(value['items'])>=256 or any(v['id']==source['id']for v in value['items'])):
                    raise ValueError('Native voice transcript exceeds source bounds')
                value['items'].append(source)
            elif kind=='realtime_session_closed':
                if item.get('outcome')not in ('ended','failed'):raise ValueError('Unknown native voice closure')
                value['closed']=True
        fresh=os.fstat(stream.fileno())
        if(fresh.st_dev,fresh.st_ino,fresh.st_size)!=(info.st_dev,info.st_ino,info.st_size):
            raise ValueError('Native history changed during recovery')
    if any(not value['started']or not value['closed']for value in values.values()):
        raise IncompleteTranscript('Native closure sources are not yet available in the recovery window')
    return {key:{'items':value['items'],'source_sha256':value['source_sha256'].hexdigest()}for key,value in values.items()}
