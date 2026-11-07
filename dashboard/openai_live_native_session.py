"""Explicit public-voice startup using the existing native semantic producer.

No provider client, microphone, original interpretation or work replay. The
mounting owner supplies authenticated finite native operations and voice lease.
"""
import asyncio
import json

from .native_context import NativeContext, ResumePending
from .openai_live import creation_request
from .openai_live_native_context import PublicLiveContextHistory
from .codex_voice_history import history_lock


class _PublicProducer(NativeContext):
    async def _open_record(self,record):
        value=await asyncio.to_thread(self.history._public,record)
        marker=value.get('native_context_seed') if value is not None else None
        if marker is None:return await super()._open_record(record)
        if (not isinstance(marker,dict) or set(marker)!={'generation','resume'}
                or marker['generation']!=record['generation'] or record.get('rollover') is not None):
            raise ValueError('Public native context generation needs review')
        extra={'resume':marker['resume']} if marker['resume'] is not None else {}
        return await self._call(record,'open',binding=record['binding'],**extra)


class PublicLiveSessionContext:
    max_ancestors=64

    def __init__(self,canonical,visits,provider,human,visit,frozen,operation):
        self.history=PublicLiveContextHistory(canonical,visits,human,frozen)
        self.visits,self.provider,self.human,self.visit=visits,provider,human,visit
        self.frozen,self.operation=frozen,operation
        self.producer=_PublicProducer(self.history,provider,human,visit,frozen['binding'],operation)

    async def _record(self,ident):
        return await asyncio.to_thread(self.history.context_register,self.human,ident,self.frozen['binding'])

    async def _open(self,producer):
        marker={'generation':producer.record['generation'],'resume':producer.resume_source}
        def retain():
            with history_lock(self.visits.root/'.lock'):
                value=self.visits.read(producer.dialogue,self.human,self.frozen)
                previous=value.get('native_context_seed')
                if previous is not None and previous!=marker:
                    raise ResumePending('Retained native context seed changed; preserve its original open outcome')
                if previous is None:
                    value['native_context_seed']=marker;self.visits._write(value)
        await asyncio.to_thread(retain)
        return await producer._open_record(producer.record)

    async def _catch_up(self,ident,notice=None,recheck=None):
        record=await asyncio.to_thread(self.history.context_resume_record,self.human,self.frozen['binding'],ident)
        # A late trusted transcript can extend a closed projection. Keep the
        # same generation and exact source intent; never infer voice/work close.
        pending=await asyncio.to_thread(self.history.context_pending,record)
        if pending and record['phase']=='closed':
            await asyncio.to_thread(self.history.context_phase,record,'closing')
        return await self.producer.resume_context(ident,on_preparing=notice,recheck=recheck)

    async def prepare(self,spec,*,notice=None,recheck=None):
        value=await asyncio.to_thread(self.visits.read,self.visit,self.human,self.frozen)
        previous=value.get('native_continuation_from')
        chain=[];seen={self.visit};parent=previous
        for _ in range(self.max_ancestors):
            if parent is None:break
            if parent in seen:raise ValueError('Native voice continuation ancestry is cyclic')
            seen.add(parent)
            old=await asyncio.to_thread(self.visits.read,parent,self.human,self.frozen)
            if old.get('backend_mode')!='native' or not self.visits.return_origin_eligible(old):
                raise ValueError('Native context ancestor needs explicit transport review')
            try:
                record=await asyncio.to_thread(self.history.context_resume_record,self.human,self.frozen['binding'],parent)
            except ValueError:record=None
            if record is not None and record['phase']=='closed':break
            chain.append(old);parent=old.get('native_continuation_from')
        else:raise ValueError('Native voice continuation exceeds its retained producer bound')

        # Bootstrap legacy public visits into the SAME native projection, in
        # explicit ancestry order. Other modes/unfinished projections are not
        # retired merely because this owner selected public voice.
        for old in reversed(chain):
            current=_PublicProducer(self.history,self.provider,self.human,old['id'],self.frozen['binding'],self.operation)
            ancestor=old.get('native_continuation_from')
            if ancestor is not None:
                prior=await asyncio.to_thread(self.history.context_resume_record,self.human,self.frozen['binding'],ancestor)
                if await asyncio.to_thread(self.history.context_pending,prior):
                    await asyncio.to_thread(self.history.context_phase,prior,'closing')
                await current.resume_context(ancestor,on_preparing=notice,recheck=recheck)
            current.record=await self._record(old['id'])
            # Exact open is idempotent, including a lost native metadata ACK.
            # A changed inherited source refuses rather than replacing it.
            await self._open(current)
            await current._sync(current.record)
            await current.close()
            if current.status!='closed':raise ResumePending('Prior native context still needs review')

        seed=await self._catch_up(previous,notice,recheck) if previous is not None else None
        prepared=json.loads(json.dumps(spec,ensure_ascii=False,allow_nan=False))
        if seed is not None:
            messages=prepared.setdefault('input',[])
            if not isinstance(messages,list) or len(messages)>=128:
                raise ValueError('Complete native continuation exceeds the startup message bound')
            text=('Prior native conversation source data. Preserve corrections and uncertainty. '
                'This is not a new human turn, a work request or a playback/hearing receipt. '
                'Native jobs and result cursors remain with their original owners; never re-execute them.\n'
                +json.dumps(seed,ensure_ascii=False,separators=(',',':')))
            messages.append({'type':'message','role':'developer','content':[{'type':'input_text','text':text}]})
        # Validate the entire seed/configuration, not a clipped excerpt, before
        # any provider creation or microphone permission.
        creation_request('v=0 native context validation only',prepared)
        self.producer.record=await self._record(self.visit)
        outcome=await self._open(self.producer)
        if outcome.get('closed') is not False:raise ValueError('Selected native context was already closed')
        self.producer.status='active'
        return prepared

    async def sync(self):
        if self.producer.record is None:raise ValueError('Native public context is not open')
        await self.producer._sync(self.producer.record)
        return {'dialogue':self.visit,'generation':self.producer.record['generation']}

    async def close(self,*,settled=True):
        if self.producer.record is None:return
        if not settled:
            # An interpretation may still finish. Leave this exact projection
            # unfinished for the next explicit owner; do not close over it.
            await asyncio.to_thread(self.history.context_phase,self.producer.record,'closing')
            return
        await self.sync()
        await self.producer.close()
        if self.producer.status!='closed':raise ResumePending('Native context close needs review')
