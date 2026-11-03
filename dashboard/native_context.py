"""Finite, server-owned Live language producer using canonical history/outbox.

No browser-authored assistant text, audio replay, model client or independent
memory corpus. The native Store owns incorporation and transport uncertainty.
"""
import asyncio
import hashlib
import json
import re
from .provider import ProviderUnavailable


class NativeContext:
    max_producers=64
    max_sources=4096

    def __init__(self,history,provider,human,dialogue,binding,owner):
        self.history,self.provider,self.human=history,provider,human
        self.dialogue,self.binding,self.owner=dialogue,binding,owner
        self.dirty=asyncio.Event();self.record=None
        self.runner=None;self.stopping=False;self.failed=False;self.status='not_started'
        self.guidance_lock=asyncio.Lock();self.guidance_attempts=set()

    async def open(self):
        # Called only for an authenticated explicit avatar open, after the
        # receiving owner has excluded another live producer for this human.
        for record in await asyncio.to_thread(self.history.context_unfinished,self.human,self.binding,self.dialogue):
            await self._open_record(record)
            await asyncio.to_thread(self.history.context_seal,record)
            await self._finish(record)
        self.record=await asyncio.to_thread(self.history.context_register,self.human,self.dialogue,self.binding)
        outcome=await self._open_record(self.record)
        if outcome.get('closed') is not False:
            raise ValueError('Selected Live producer already closed')
        self.status='active'
        self.notify()

    async def _call(self,record,action,**values):
        result=await self.owner(self.provider.conversation_live_context,{
            'action':action,'dialogue':record['dialogue'],'generation':record['generation'],**values})
        if result.get('dialogue')!=record['dialogue'] or result.get('generation')!=record['generation']:
            raise ValueError('Live context receipt changed producer')
        return result

    async def _open_record(self,record):
        return await self._call(record,'open',binding=record['binding'])

    def notify(self):
        self.dirty.set()

    async def run(self):
        self.runner=asyncio.current_task()
        while True:
            await self.dirty.wait();self.dirty.clear()
            try:await self._sync(self.record)
            except BaseException:
                self.failed=True;self.status='needs_review';raise
            if self.stopping:return

    async def _sync(self,record):
        # Pending rows reference immutable canonical terminal utterances. Do not
        # use playback-dependent revisions or a row cursor that misses closure.
        # Exact idempotent source reconciliation can resume after a lost owner
        # receipt; native return IDs/uncertain effects are never reauthored.
        sent=False
        for _ in range(self.max_sources+1):
            sources=await asyncio.to_thread(self.history.context_pending,record)
            if not sources and sent:return
            payload=[{'source':s['source'],'text':s['text'],'interrupted':s['interrupted']} for s in sources]
            result=await self._call(record,'sync',assistant=payload)
            receipts=result.get('assistant_receipts')
            if not isinstance(receipts,list) or len(receipts)!=len(sources):
                raise ValueError('Incomplete Live context retention receipt')
            expected={s['source'] for s in sources}
            if ({r.get('source') for r in receipts}!=expected
                    or any(type(r.get('sequence')) is not int or not 0<r['sequence']<=2**63-1
                           or not isinstance(r.get('revision'),str) or not re.fullmatch('[a-f0-9]{64}',r['revision']) for r in receipts)):
                raise ValueError('Live context receipt does not match canonical sources')
            await asyncio.to_thread(self.history.context_retained,record,sources,receipts)
            sent=True
            if not sources:return
        raise ValueError('Live context catch-up exceeds its retained bound')

    async def _finish(self,record):
        await asyncio.to_thread(self.history.context_phase,record,'closing')
        await self._sync(record)
        result=await self._call(record,'close')
        if result.get('closed') is not True:raise ValueError('Live producer close unconfirmed')
        await asyncio.to_thread(self.history.context_phase,record,'closed')

    async def offer_guidance(self,deliver,ready=None):
        if self.record is None or self.stopping or self.failed or self.guidance_lock.locked():return False
        async with self.guidance_lock:
            try:result=await self._call(self.record,'guidance')
            except ProviderUnavailable:return False
            guide=result.get('guidance')
            if guide is None:return False
            if guide.get('generation')!=self.record['generation'] or guide.get('phase')!='pending':
                raise ValueError('Live guidance generation or pending state changed')
            ident=guide.get('id')
            if ident in self.guidance_attempts:return False
            if len(self.guidance_attempts)>=64:raise ValueError('Live guidance attempt bound reached')
            frame={k:guide[k] for k in ('id','generation','basis','mode','text')}
            frame['dialogue']=self.dialogue
            if ready is not None and not await ready(frame):return False
            self.guidance_attempts.add(ident)
            try:claim=await self._call(self.record,'guidance_begin',id=ident)
            except ProviderUnavailable:return False
            if claim.get('guidance',{}).get('phase')!='submitting':
                raise ValueError('Live guidance claim was not confirmed')
            try:
                sent=await deliver(frame)
                if type(sent) is not bool:raise ValueError('Live guidance send outcome unavailable')
            except BaseException:
                try:await asyncio.shield(self._call(self.record,'guidance_outcome',id=ident,outcome='uncertain'))
                except (ProviderUnavailable,ValueError):pass
                raise
            if not sent:self.guidance_attempts.discard(ident)
            try:await self._call(self.record,'guidance_outcome',id=ident,outcome='sent' if sent else 'unsent')
            except ProviderUnavailable:pass
            return sent

    async def close(self):
        if self.record is None:return
        await asyncio.to_thread(self.history.context_phase,self.record,'closing')
        self.stopping=True;self.notify()
        if self.runner is not None:
            try:await asyncio.wait_for(asyncio.shield(self.runner),18)
            except BaseException:
                self.failed=True;self.status='needs_review'
                if not self.runner.done():self.runner.cancel()
                return
        if self.failed:return
        try:await self._finish(self.record)
        except BaseException:
            self.failed=True;self.status='needs_review';raise
        self.status='closed'


def semantic_revision(row):
    """Language/state identity only, independent of generated/played PCM."""
    data=[row['id'],row['dialogue'],row['binding'],row['text'],bool(row['interrupted']),bool(row['closed'])]
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def install_schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS foreground_context_producers(
        dialogue TEXT PRIMARY KEY,human INTEGER NOT NULL,scope TEXT NOT NULL,
        binding TEXT NOT NULL,generation TEXT NOT NULL,phase TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS foreground_context_outbox(
        source TEXT PRIMARY KEY,dialogue TEXT NOT NULL,revision TEXT NOT NULL,
        phase TEXT NOT NULL,native_sequence INTEGER,native_revision TEXT);
        CREATE INDEX IF NOT EXISTS foreground_context_pending ON foreground_context_outbox(dialogue,phase);
        CREATE TRIGGER IF NOT EXISTS foreground_context_source_deleted AFTER DELETE ON foreground_utterances
        BEGIN DELETE FROM foreground_context_outbox WHERE source=OLD.id; END;''')


def enqueue(db,row):
    if not row['closed'] or not row['text']:return
    registered=db.execute('SELECT phase FROM foreground_context_producers WHERE dialogue=? AND human=? AND scope=? AND binding=?',
        (row['dialogue'],row['human'],row['scope'],row['binding'])).fetchone()
    if registered is None:return
    previous=db.execute('SELECT revision FROM foreground_context_outbox WHERE source=?',(row['id'],)).fetchone()
    revision=semantic_revision(row)
    if previous is not None:
        if previous['revision']!=revision:raise ValueError('Final Live context source changed')
        return
    if registered['phase']=='closed':raise ValueError('Closed Live producer cannot acquire another terminal source')
    count=db.execute('SELECT count(*) FROM foreground_context_outbox WHERE dialogue=?',(row['dialogue'],)).fetchone()[0]
    if count>=NativeContext.max_sources:raise ValueError('Live context source outbox reached its bound')
    db.execute("INSERT INTO foreground_context_outbox(source,dialogue,revision,phase) VALUES(?,?,?,'pending')",
        (row['id'],row['dialogue'],revision))
