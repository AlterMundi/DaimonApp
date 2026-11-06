"""Exact public transcript sources for the existing native semantic producer.

No ASR, microphone, work submission, model client or independent transcript store.
The public journal owns original deltas; native context owns idempotent source
receipts/checkpoints. A constant cursor joins them without a copied archive.
"""
import hashlib
import json
import math
import uuid

from .codex_voice_history import history_lock


class PublicLiveContextHistory:
    """Adapt NativeContext's existing history/outbox interface, not its owner.

    The mounting caller must retain the authenticated app voice lease and use
    the actual native foreground_public_live_transcripts=v1 capability. This
    adapter is not itself a voice/provider activation or a work authority.
    """
    def __init__(self, canonical, visits, human, frozen):
        self.canonical,self.visits=canonical,visits
        self.human,self.owner=human,visits._owner(human,frozen)['frozen']

    def __getattr__(self,name):
        return getattr(self.canonical,name)

    def _public(self,record):
        if record['human']!=self.human or record['binding']!=self.owner['binding']:
            raise ValueError('Public context producer belongs to another actor')
        path=self.visits._path(record['dialogue'])
        if not path.exists() and not path.is_symlink():return None
        value=self.visits.read(record['dialogue'],self.human,self.owner)
        if value.get('backend_mode')!='native':
            raise ValueError('Select the native public context producer')
        return value

    @staticmethod
    def _cursor(value,record):
        cursor=value.get('native_context_cursor')
        if cursor is None:return {'generation':record['generation'],'after':0,'revision':None}
        if (not isinstance(cursor,dict) or set(cursor)!={'generation','after','revision'}
                or cursor['generation']!=record['generation']
                or type(cursor['after']) is not int or cursor['after']<0):
            raise ValueError('Native public source cursor changed; preserve its outcome')
        return dict(cursor)

    def _advance(self,record,before,after,claim=None):
        with history_lock(self.visits.root/'.lock'):
            value=self._public(record)
            current=self._cursor(value,record)
            if current==after and 'native_context_batch' not in value:return
            if current!=before or value.get('native_context_batch')!=claim:
                raise ValueError('Native public context source claim changed')
            value['native_context_cursor']=after
            value.pop('native_context_batch',None)
            self.visits._write(value)

    def context_pending(self,record):
        canonical=self.canonical.context_pending(record)
        if canonical:return canonical
        value=self._public(record)
        if value is None or value['state'] not in ('created','closed'):return []
        cursor=self._cursor(value,record)
        for _ in range(128):
            claim=value.get('native_context_batch')
            if claim is not None and (not isinstance(claim,dict) or set(claim)!={'before','after','source','sha256'}
                    or claim['before']!=cursor or claim['after'].get('generation')!=record['generation']):
                raise ValueError('Preserve the exact native public context batch intent')
            page=self.visits.source_page(value['id'],self.human,self.owner['binding'],
                after=cursor['after'],revision=cursor['revision'],with_offsets=True,with_raw_records=True)
            if not page['items']:
                if page['more'] or claim:raise ValueError('Public transcript append remains unconfirmed')
                return []
            before=dict(cursor);text='';spans=[];raw=[]
            metadata={'model':'gpt-live-1','session_id':value['call']['session_id'],
                'authority':'transcript_context_only','journal_revision':page['revision'],
                'journal_from':before['after'],'journal_after':before['after'],
                'journal_sha256':'0'*64,'spans':spans}
            for row,offset,line in zip(page['items'],page['offsets'],page['raw_records'],strict=True):
                if claim and offset>claim['after']['after']:break
                event=row['event'];kind=event['type']
                if kind in ('session.input_transcript.delta','session.output_transcript.delta'):
                    encoded=json.dumps(event,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()
                    delta=event.get('delta');start=event.get('start_ms');end=event.get('end_ms')
                    if (hashlib.sha256(encoded).hexdigest()!=row['sha256'] or event.get('event_id')!=row['event_id']
                            or not isinstance(delta,str) or not delta or '\0' in delta or len(delta.encode())>12000
                            or any(type(n) not in (int,float) or not math.isfinite(n) for n in (start,end))
                            or not 0<=start<=end<=86400000):
                        raise ValueError('Public transcript source is incomplete or exceeds its bound')
                    next_text=text+delta
                    next_spans=spans+[['input' if kind=='session.input_transcript.delta' else 'output',
                        start,end,len(next_text.encode()),offset]]
                    proposed={**metadata,'spans':next_spans,'journal_after':offset}
                    charged=len(json.dumps({'text':next_text,'live_transcript':proposed},ensure_ascii=False).encode())+1024
                    if charged>12000:
                        if not spans:raise ValueError('Complete public transcript fragment needs a bounded source read')
                        break
                    text=next_text;spans=next_spans;metadata['spans']=spans
                raw.append(line)
                cursor={'generation':record['generation'],'after':offset,'revision':page['revision']}
            if spans:
                digest=hashlib.sha256(b''.join(raw)).hexdigest()
                metadata.update(journal_after=cursor['after'],journal_sha256=digest)
                source=str(uuid.uuid5(uuid.UUID(value['id']),'gpt-live-context-block:'+str(before['after'])+':'+str(cursor['after'])))
                current_claim={'before':before,'after':dict(cursor),'source':source,'sha256':digest}
                if claim is not None and claim!=current_claim:
                    raise ValueError('Native public context batch source changed; never replace its intent')
                if claim is None:
                    # Freeze the byte range BEFORE native retention. Otherwise a
                    # lost ACK followed by new deltas could regroup old language.
                    with history_lock(self.visits.root/'.lock'):
                        fresh=self._public(record)
                        if self._cursor(fresh,record)!=before or fresh.get('native_context_batch') is not None:
                            raise ValueError('Native public context batch changed before intent')
                        fresh['native_context_batch']=current_claim;self.visits._write(fresh)
                return [{'source':source,'text':text,'interrupted':True,
                    'live_transcript':metadata,'_public_cursor':current_claim}]
            if claim:raise ValueError('Retained public context batch lost its source language')
            self._advance(record,before,cursor)
            value=self._public(record)
            if not page['more']:return []
        raise ValueError('Public source scan reached its retained event bound')

    def context_retained(self,record,sources,receipts):
        public=[source for source in sources if '_public_cursor' in source]
        if not public:return self.canonical.context_retained(record,sources,receipts)
        if (len(public)!=len(sources) or {s['source'] for s in sources}!={r.get('source') for r in receipts}
                or len(receipts)!=len(sources)
                or any(type(r.get('sequence')) is not int or r['sequence']<=0
                    or not isinstance(r.get('revision'),str) or len(r['revision'])!=64
                    or any(c not in '0123456789abcdef' for c in r['revision']) for r in receipts)):
            raise ValueError('Native public context receipts do not match the exact sources')
        cursor=public[0]['_public_cursor']
        if any(s['_public_cursor']!=cursor for s in public):
            raise ValueError('Native public context receipt crossed a source page')
        self._advance(record,cursor['before'],cursor['after'],cursor)
