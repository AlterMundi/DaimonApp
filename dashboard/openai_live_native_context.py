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

    def _advance(self,record,before,after):
        with history_lock(self.visits.root/'.lock'):
            value=self._public(record)
            current=self._cursor(value,record)
            if current==after:return
            if current!=before:raise ValueError('Native public context source cursor changed')
            value['native_context_cursor']=after
            self.visits._write(value)

    def context_pending(self,record):
        # Preserve the canonical assistant outbox and all other existing modes.
        canonical=self.canonical.context_pending(record)
        if canonical:return canonical
        value=self._public(record)
        if value is None:return []
        if value['state'] not in ('created','closed'):
            return []
        cursor=self._cursor(value,record)
        for _ in range(128):  # At most the existing8192event source bound.
            page=self.visits.source_page(value['id'],self.human,self.owner['binding'],
                after=cursor['after'],revision=cursor['revision'],with_offsets=True)
            if not page['items']:
                if page['more']:raise ValueError('Public transcript append remains unconfirmed')
                return []
            before=dict(cursor);sources=[];size=0
            for row,offset in zip(page['items'],page['offsets'],strict=True):
                event=row['event'];kind=event['type']
                if kind in ('session.input_transcript.delta','session.output_transcript.delta'):
                    raw=json.dumps(event,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()
                    text=event.get('delta');start=event.get('start_ms');end=event.get('end_ms')
                    if (hashlib.sha256(raw).hexdigest()!=row['sha256']
                            or event.get('event_id')!=row['event_id']
                            or not isinstance(text,str) or not text or '\0' in text
                            or len(text.encode())>12000
                            or any(type(n) not in (int,float) or not math.isfinite(n) for n in (start,end))
                            or not 0<=start<=end<=86400000):
                        raise ValueError('Public transcript source is incomplete or exceeds its bound')
                    source={'source':str(uuid.uuid5(uuid.UUID(value['id']),'gpt-live-context:'+row['event_id'])),
                        'text':text,'interrupted':True,'live_transcript':{
                            'model':'gpt-live-1','session_id':value['call']['session_id'],
                            'provider_event_id':row['event_id'],'event_sha256':row['sha256'],
                            'speaker':'input' if kind=='session.input_transcript.delta' else 'output',
                            'start_ms':start,'end_ms':end,'authority':'transcript_context_only'}}
                    # Count text escaping and all provenance, with room for
                    # the native typed envelope inside its unchanged64KiB cap.
                    charged=len(json.dumps(source,ensure_ascii=False,allow_nan=False).encode())+512
                    if size+charged>60000:break
                    size+=charged
                    sources.append(source)
                cursor={'generation':record['generation'],'after':offset,'revision':page['revision']}
                if len(sources)==8:break
            if sources:
                # Local bookkeeping is excluded from the native payload by
                # NativeContext. Commit this cursor only after exact receipts.
                for source in sources:source['_public_cursor']={'before':before,'after':dict(cursor)}
                return sources
            self._advance(record,before,cursor)
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
        self._advance(record,cursor['before'],cursor['after'])
