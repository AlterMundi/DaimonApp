"""Finite, server-owned Live language producer using canonical history/outbox.

No browser-authored assistant text, audio replay, model client or independent
memory corpus. The native Store owns incorporation and transport uncertainty.
"""
import asyncio
import hashlib
import json
import re
from .provider import ProviderUnavailable
from .native_dialogue import DialogueCapacity


class NativeContext:
    max_producers=64
    max_sources=4096

    def __init__(self,history,provider,human,dialogue,binding,owner):
        self.history,self.provider,self.human=history,provider,human
        self.dialogue,self.binding,self.owner=dialogue,binding,owner
        self.dirty=asyncio.Event();self.record=None
        self.runner=None;self.stopping=False;self.failed=False;self.failed_sync=False;self.status='not_started'
        self.guidance_lock=asyncio.Lock();self.guidance_attempts=set()
        self.operation_lock=asyncio.Lock()
        self.checkpoint_requested_generation=None

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
        if record.get('rollover') is not None:
            # An old process owns no surviving voice socket. Resolve its one
            # exact transition, never reopen/replay the candidate or tool calls.
            await self._resolve_rollover(record,json.loads(record['rollover']))
        return await self._call(record,'open',binding=record['binding'])

    async def request_checkpoint(self,pressure):
        """One owner-local request per physical generation, including quiet speech.

        The native projection freezes the exact range/control packet for Sol.
        A request receipt is not a semantic checkpoint or handover approval.
        """
        if pressure is None:return False
        async with self.operation_lock:
            if (self.stopping or self.failed or self.record is None
                    or self.record.get('rollover') is not None
                    or self.checkpoint_requested_generation==self.record['generation']):return False
            value=await self._call(self.record,'checkpoint_needed',**pressure)
            request=value.get('checkpoint_request')
            if not isinstance(request,dict) or request.get('generation')!=self.record['generation']:
                raise ValueError('Live checkpoint pressure receipt changed generation')
            self.checkpoint_requested_generation=self.record['generation']
            return True

    async def prepare_rollover(self):
        async with self.operation_lock:
            if self.stopping or self.failed or self.record.get('rollover') is not None:return None
            # Catch up actual pending terminal sources once. An idle failed
            # checkpoint read must not write sync repeatedly and wake its own
            # database watcher while waiting for Sol incorporation.
            if await asyncio.to_thread(self.history.context_pending,self.record):
                try:await self._sync_unlocked(self.record)
                except BaseException:
                    self.failed=True;self.failed_sync=True;self.status='needs_review';raise
            try:value=await self._call(self.record,'rollover_read')
            except ProviderUnavailable:return None
            return value.get('rollover_basis')

    async def begin_rollover(self,basis,next_generation):
        """Retain the exact candidate intent BEFORE opening a replacement."""
        async with self.operation_lock:
            if self.stopping or self.failed or self.record.get('rollover') is not None:return None
            try:current=await self._call(self.record,'rollover_read')
            except ProviderUnavailable:return None
            if current.get('rollover_basis')!=basis:return None
            intent=await asyncio.to_thread(self.history.context_rollover_intent,self.record,next_generation,basis['revision'])
            self.record['rollover']=json.dumps(intent,separators=(',',':'))
            return intent

    async def _resolve_rollover(self,record,intent):
        # Read-only status=false cannot settle an in-flight commit. The native
        # abort either observes its commit or fences this exact candidate UUID
        # so a delayed command cannot change generation after our observation.
        if record.get('rollover') is None or json.loads(record['rollover'])!=intent:
            raise ValueError('Select the retained Live rollover intent')
        value=await self.owner(self.provider.conversation_live_context,{
            'action':'rollover_abort','dialogue':record['dialogue'],'generation':intent['previous'],
            'next_generation':intent['next'],'revision':intent['revision']})
        committed=value.get('rollover_committed')
        if (type(committed) is not bool or value.get('dialogue')!=record['dialogue']
                or value.get('generation')!=intent['next' if committed else 'previous']
                or not committed and value.get('rollover_fenced') is not True
                or committed and (value.get('rollover',{}).get('committed') is not True
                    or any(value.get('rollover',{}).get(k)!=intent[k] for k in ('previous','next','revision')))):
            raise ValueError('Live rollover outcome was not confirmed')
        updated=await asyncio.to_thread(self.history.context_rollover_settle,record,intent,committed=committed)
        record.clear();record.update(updated)
        return committed

    async def abort_rollover(self,intent):
        async with self.operation_lock:
            try:return await self._resolve_rollover(self.record,intent)
            except BaseException:
                self.failed=True;self.status='needs_review';raise

    async def commit_rollover(self,intent):
        """Caller owns the prepared socket and final acoustic/output boundary.

        Only native/local journal state changes here. No provider reconnect,
        socket write, original replay or inference retry is performed.
        """
        async with self.operation_lock:
            if self.stopping or self.failed:raise ValueError('Live context is not active')
            if self.record.get('rollover') is None or json.loads(self.record['rollover'])!=intent:
                raise ValueError('Select the retained Live rollover intent')
            try:
                try:
                    value=await self.owner(self.provider.conversation_live_context,{
                        'action':'rollover_commit','dialogue':self.dialogue,'generation':intent['previous'],
                        'next_generation':intent['next'],'revision':intent['revision']})
                except ProviderUnavailable:
                    return await self._resolve_rollover(self.record,intent)
                receipt=value.get('rollover',{})
                if (value.get('dialogue')!=self.dialogue or value.get('generation')!=intent['next']
                        or any(receipt.get(k)!=intent[v] for k,v in (('previous','previous'),('next','next'),('revision','revision')))
                        or receipt.get('committed') is not True):
                    raise ValueError('Live rollover commit was not confirmed')
                updated=await asyncio.to_thread(self.history.context_rollover_settle,self.record,intent,committed=True)
                self.record.clear();self.record.update(updated)
                return True
            except BaseException:
                self.failed=True;self.status='needs_review';raise

    def notify(self):
        self.dirty.set()

    async def run(self):
        self.runner=asyncio.current_task()
        while True:
            await self.dirty.wait();self.dirty.clear()
            try:await self._sync(self.record)
            except BaseException:
                self.failed=True;self.failed_sync=True;self.status='needs_review';raise
            if self.stopping:return

    async def _sync(self,record):
        async with self.operation_lock:
            await self._sync_unlocked(record)

    async def _sync_unlocked(self,record):
        # Pending rows reference immutable canonical terminal utterances. Do not
        # use playback-dependent revisions or a row cursor that misses closure.
        # Exact idempotent source reconciliation can resume after a lost owner
        # receipt; native return IDs/uncertain effects are never reauthored.
        sent=False
        for _ in range(self.max_sources+1):
            sources=await asyncio.to_thread(self.history.context_pending,record)
            if not sources and sent:return
            payload=[{k:s[k] for k in ('source','text','interrupted','audio_without_transcript','derived_caption') if k in s} for s in sources]
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
        if self.record is None or self.stopping or self.failed or self.guidance_lock.locked() or self.operation_lock.locked():return False
        async with self.operation_lock,self.guidance_lock:
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
            except BaseException as error:
                outcome='unsent' if isinstance(error,DialogueCapacity) else 'uncertain'
                try:await asyncio.shield(self._call(self.record,'guidance_outcome',id=ident,outcome=outcome))
                except (ProviderUnavailable,ValueError):pass
                raise
            if not sent:self.guidance_attempts.discard(ident)
            try:await self._call(self.record,'guidance_outcome',id=ident,outcome='sent' if sent else 'unsent')
            except ProviderUnavailable:pass
            return sent

    async def close(self):
        if self.record is None:return
        await asyncio.to_thread(self.history.context_phase,self.record,'closing')
        self.stopping=True
        if self.record.get('rollover') is not None:
            try:
                async with self.operation_lock:
                    await self._resolve_rollover(self.record,json.loads(self.record['rollover']))
                # Resolving a transition is not permission to retry an unknown
                # source-retention write. Preserve that separate failure.
                if not self.failed_sync:self.failed=False
            except BaseException:
                self.failed=True;self.status='needs_review'
        self.notify()
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
    """Language/state or missing-caption evidence; independent of playback."""
    data=[row['id'],row['dialogue'],row['binding'],row['text'],bool(row['interrupted']),bool(row['closed'])]
    if not row['text'] and row['closed'] and row['generated_bytes']:
        data.append({'pcm_sha256':row['audio_sha256'],'generated_bytes':row['generated_bytes']})
    if 'derived_caption' in row.keys() and row['derived_caption'] is not None:
        data.append({'derived_caption':json.loads(row['derived_caption'])})
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
    columns={r[1] for r in db.execute('PRAGMA table_info(foreground_context_producers)')}
    for column in ('rollover','rollover_settled'):
        if column not in columns:
            db.execute(f'ALTER TABLE foreground_context_producers ADD COLUMN {column} TEXT')


def enqueue(db,row):
    if not row['closed'] or not row['text'] and not row['generated_bytes']:return
    registered=db.execute('SELECT phase FROM foreground_context_producers WHERE dialogue=? AND human=? AND scope=? AND binding=?',
        (row['dialogue'],row['human'],row['scope'],row['binding'])).fetchone()
    if registered is None:return
    previous=db.execute('SELECT revision FROM foreground_context_outbox WHERE source=?',(row['id'],)).fetchone()
    revision=semantic_revision(row)
    if previous is not None:
        if previous['revision']!=revision:raise ValueError('Final Live context source changed')
        return
    if registered['phase']=='closed' and ('derived_caption' not in row.keys() or row['derived_caption'] is None):
        raise ValueError('Closed Live producer cannot acquire another terminal source')
    count=db.execute('SELECT count(*) FROM foreground_context_outbox WHERE dialogue=?',(row['dialogue'],)).fetchone()[0]
    if count>=NativeContext.max_sources:raise ValueError('Live context source outbox reached its bound')
    db.execute("INSERT INTO foreground_context_outbox(source,dialogue,revision,phase) VALUES(?,?,?,'pending')",
        (row['id'],row['dialogue'],revision))
