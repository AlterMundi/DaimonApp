"""One live conversation's bounded source/integrator bridge.

Audio acquisition, acoustic decisions and browser authorization belong to the
owning WebSocket. This bridge reuses native originals and canonical source reads;
it has no worker registry, general controller, model poller or job cancellation.
"""
import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import uuid

from .live_transcription import save_prepared, wav_bytes
from .private_state import private_directory
from .provider import Provider, ProviderUnavailable


class ForegroundUnavailable(Exception):
    pass


@dataclass
class Capture:
    ident: str
    pcm: bytes
    digest: str
    questions: dict
    reservation: asyncio.Task | None = None
    completion: asyncio.Task | None = None
    phase: str = 'retaining'
    transcript: str | None = None
    interpretation_ready: asyncio.Event = field(default_factory=asyncio.Event)


class ForegroundBridge:
    max_captures = 128
    max_pcm_bytes = 300 * 32000
    max_pending = 4

    def __init__(self, provider, stream, cache_root, dialogue, binding, authorize, *, speech_context=None):
        Provider.input_id(dialogue)
        if not re.fullmatch('[a-f0-9]{64}',binding) or not callable(authorize):
            raise ValueError('Select an owned foreground conversation')
        if stream.activity_mode not in ('manual','automatic'):
            raise ValueError('Select an owned native acoustic protocol')
        self.provider,self.stream = provider,stream
        self.dialogue,self.binding = dialogue,binding
        self.authorize = authorize
        self.speech_context = speech_context
        self.cache_root=private_directory(cache_root)
        self.originals=private_directory(Path(str(provider.receiver['db_path'])+'.voice'))
        self.captures={}
        self.input_bytes=0
        self.latest=None
        self.pending_acoustic=None
        self._reservation_tail=None
        self.closed=False
        self._owners=asyncio.Semaphore(2)
        self._files=asyncio.Semaphore(1)
        self._returns=asyncio.Queue(maxsize=8)
        self._offered={}
        self._queued=set()
        self._watching=False
        self.offer_generation=0
        self.noticed_generation=0
        self._tool_calls=set()

    async def _run(self, limit, function, *args, **kwargs):
        # A cancelled waiter cannot release a slot while its owning file/control
        # thread is still running. There are at most two owner calls/one writer.
        await asyncio.wait_for(limit.acquire(),2)
        task=asyncio.create_task(asyncio.to_thread(function,*args,**kwargs))
        def done(future):
            limit.release()
            if not future.cancelled():future.exception()
        task.add_done_callback(done)
        return await asyncio.wait_for(asyncio.shield(task),18)

    async def _owner(self,function,*args,**kwargs):
        if self.closed:raise ForegroundUnavailable('Foreground conversation ended')
        await self.authorize()
        return await self._run(self._owners,function,*args,**kwargs)

    def capture(self,ident,pcm,questions):
        """Retain a complete acoustic span before its provider transcript arrives.

        Caller has already authorized and stopped that acoustic activity. No
        provider/native work is replayed, and no partial caption is an original.
        """
        Provider.input_id(ident);Provider.check_capture_questions(questions)
        if (self.closed or ident in self.captures or len(self.captures)>=self.max_captures
                or sum(c.phase not in ('foreground','unconfirmed') for c in self.captures.values())>=self.max_pending
                or not isinstance(pcm,bytes) or not pcm or len(pcm)%2
                or len(pcm)>120*32000 or self.input_bytes+len(pcm)>self.max_pcm_bytes):
            raise ForegroundUnavailable('Foreground capture exceeds its live bounds')
        data=wav_bytes(pcm)
        value=Capture(ident,pcm,hashlib.sha256(data).hexdigest(),dict(questions or {}))
        self.captures[ident]=value;self.latest=ident;self.input_bytes+=len(pcm)
        previous=self._reservation_tail
        async def retain():
            try:
                # Preserve already-authorized bytes before a later control or
                # session check can fail. Same private bounded capture store.
                await self._run(self._files,Provider.retain_voice_capture,
                                self.originals,ident,data,value.digest)
                # File completion cannot reorder the native ingress journal.
                # An uncertain earlier reservation is retained, not overtaken.
                if previous is not None:
                    await asyncio.shield(previous)
                result=await self._owner(self.provider.conversation_voice_submit,
                    {'id':ident,'binding':self.binding,'audio_sha256':value.digest,
                     'mime':'audio/wav','capture_questions':value.questions},data,
                    foreground_dialogue=self.dialogue,defer_foreground=True)
                if (result.get('id')!=ident or result.get('foreground_dialogue')!=self.dialogue
                        or result.get('phase') not in ('foreground_captured','foreground')):
                    raise ForegroundUnavailable('Original retention was not confirmed')
                value.phase=result['phase']
                return result
            except BaseException:
                value.phase='unconfirmed'
                raise
        value.reservation=asyncio.create_task(retain())
        self._reservation_tail=value.reservation
        value.reservation.add_done_callback(self._observe)
        return value

    def transcript(self,ident,text):
        """Bind a noninterim transcript to an explicitly correlated closed span.

        The caller must match the selected provider boundary and transcript
        to this acoustic span. Output/turnComplete is not that correlation.
        """
        capture=self.captures.get(ident)
        if (self.closed or capture is None or not isinstance(text,str) or not text.strip()
                or len(text.encode())>16000 or '\0' in text):
            raise ForegroundUnavailable('Select a complete captured interpretation')
        if capture.transcript is not None:
            if capture.transcript!=text:
                raise ForegroundUnavailable('A retained interpretation cannot be rewritten')
            return capture.completion
        capture.transcript=text
        # Own immutable bytes before close can release the live capture buffer.
        pcm=capture.pcm
        async def complete():
            try:
                await asyncio.shield(capture.reservation)
                await self._run(self._files,save_prepared,self.cache_root,ident,self.binding,pcm,
                    {'text':text,'final':True,'model':self.stream.model,
                     'pcm_sha256':hashlib.sha256(pcm).hexdigest(),'audio_millis':len(pcm)*1000//32000})
                result=await self._owner(self.provider.conversation_foreground_complete,
                                        ident,self.binding,self.dialogue)
                # Observe the existing retained source, never repeat completion,
                # recognition or native admission to repair an unknown outcome.
                for delay in (0,.05,.1,.2,.4,.8):
                    if result.get('phase')=='foreground':break
                    if result.get('phase') not in ('preparing','foreground_captured'):
                        raise ForegroundUnavailable('Original completion needs review')
                    await asyncio.sleep(delay)
                    result=await self._owner(self.provider.conversation_input_status,ident)
                if (result.get('id')!=ident or result.get('phase')!='foreground'
                        # Native voice originals use the owner's existing outer
                        # whitespace normalization. Keep the provider's exact
                        # interpretation in the prepared receipt, but compare
                        # the retained source using that established contract.
                        or result.get('text')!=text.strip() or result.get('foreground_dialogue')!=self.dialogue
                        or result.get('voice',{}).get('audio_sha256')!=capture.digest):
                    raise ForegroundUnavailable('Completed original was not confirmed')
                capture.phase='foreground';capture.pcm=b''
                return result
            except BaseException:
                capture.phase='unconfirmed'
                raise
        capture.completion=asyncio.create_task(complete())
        capture.interpretation_ready.set()
        capture.completion.add_done_callback(self._observe)
        return capture.completion

    @staticmethod
    def _observe(task):
        if not task.cancelled():
            task.exception()

    async def tool(self,event):
        """Answer only declared live tools; effects still belong to the owner."""
        ident=event['call_id']
        if self.closed:raise ForegroundUnavailable('Foreground conversation ended')
        if ident in self._tool_calls or len(self._tool_calls)>=self.stream.max_tools:
            raise ForegroundUnavailable('A foreground tool cannot be replayed')
        self._tool_calls.add(ident)
        source_root=self.latest
        try:
            # Automatic transcription/tool calls may precede activity END.
            # Answer explicitly, without blocking the event reader needed to
            # close that source or silently selecting the previous original.
            if (event['type'] in ('source_query','delegation_proposed')
                    and self.pending_acoustic is not None):
                raise ForegroundUnavailable('The current spoken original is still pending')
            if event['type']=='source_query':
                # Recognition/storage may finish while the native voice speaks.
                capture=self.captures.get(self.latest)
                if capture:
                    try:
                        await asyncio.wait_for(capture.interpretation_ready.wait(),10)
                    except TimeoutError:
                        raise ForegroundUnavailable('Original interpretation is still pending') from None
                    if self.closed or capture.completion is None:
                        raise ForegroundUnavailable('Foreground conversation ended')
                    await asyncio.shield(capture.completion)
                if self.pending_acoustic is not None or self.latest!=(capture.ident if capture else None):
                    raise ForegroundUnavailable('A newer spoken correction is pending')
                result=await self._owner(self.provider.conversation_foreground_originals,
                                         self.dialogue,self.binding,event['before'])
                if self.speech_context is not None:
                    # A read of existing app history, never a hearing receipt,
                    # human original or reason to start another native job.
                    speech=await self._owner(self.speech_context)
                    result=dict(result)
                    for item in speech[:4]:
                        candidate={**result,'assistant_speech':result.get('assistant_speech',[])+[item]}
                        if len(json.dumps(candidate,allow_nan=False).encode())>16384:break
                        result=candidate
            elif event['type']=='integrating_source_query':
                source=self._offered.get((event['source'],event['revision']))
                if source is None:
                    raise ForegroundUnavailable('Select a source already offered in this foreground dialogue')
                result=await self._integrating_part(source,event['offset'])
                if result is None:
                    raise ForegroundUnavailable('Selected integrating source is no longer current')
            elif event['type']=='delegation_proposed':
                sources=event['original_ids'];root=self.latest
                if root not in sources:
                    raise ForegroundUnavailable('Include the latest captured correction')
                for source in sources:
                    original=await self._owner(self.provider.conversation_input_status,source)
                    if (original.get('foreground_dialogue')!=self.dialogue
                            or original.get('phase') not in ('foreground','accepted','answered')):
                        raise ForegroundUnavailable('Original is not ready in this conversation')
                if self.pending_acoustic is not None or self.latest!=root:
                    raise ForegroundUnavailable('A newer spoken correction is pending')
                body={'binding':self.binding,'id':root,
                      'intent_id':str(uuid.uuid5(uuid.UUID(self.dialogue),'delegate:'+ident)),
                      'formulation':event['formulation'],'source_ids':sources}
                # One call only. A lost ACK is unconfirmed, never permission to
                # reauthor a second request or retry a provider/native effect.
                accepted=await self._owner(self.provider.conversation_foreground_delegate,body)
                result={'kind':'integrator_admission','id':accepted['id'],'phase':accepted['phase'],
                        'native_acceptance':accepted['native_acceptance'],
                        'recipient':'integrating_conversation',
                        'worker_delivery':'not_established_by_this_receipt',
                        'acknowledgment':'The request was sent to the integrating conversation. This receipt does not establish delivery to or start by a worker.',
                        'completion':'Not established by admission. Use real integrating returns.'}
                if not self._watching:
                    # The admitted nonblocking call itself carries returns; no
                    # extra model-selected subscription is required.
                    await self._watch(ident,result)
                    return
            elif event['type']=='integrator_watch':
                await self._watch(ident)
                return
            else:raise ForegroundUnavailable('Unsupported foreground tool')
        except ForegroundUnavailable as error:
            result={'kind':'not_ready','reason':str(error),'meaning':'No new work was confirmed. Resolve the stated source condition before proposing a different intent.'}
        except (ProviderUnavailable,ValueError,TimeoutError,OSError):
            result={'kind':'unconfirmed','meaning':'The operation was not confirmed. Do not repeat work or claim completion; originals and existing jobs remain retained.'}
        if (event['type']=='source_query'
                and (self.pending_acoustic is not None or self.latest!=source_root)):
            result={'kind':'not_ready','reason':'A newer spoken correction is pending',
                    'meaning':'Read the current original after its interpretation is complete.'}
        if not self.closed:
            await asyncio.to_thread(self.stream.tool_result,ident,result)
        return result

    async def _integrating_part(self,source,offset):
        """Reuse the scoped canonical reader, revalidating every requested page."""
        if type(offset) is not int or not 0<=offset<=10**9:
            raise ForegroundUnavailable('Select a bounded integrating source offset')
        try:
            result=await self._owner(self.provider.presentation_part,source['id'],source['revision'],offset)
        except (ProviderUnavailable,ValueError):
            # Answered/changed canonical questions reject their old revision in
            # the existing reader. Retire that offer without ending the watch.
            if source['kind']=='question' and source['id'].startswith('request:'):return None
            raise
        next_offset=result.get('next_offset')
        if (result.get('id')!=source['id'] or result.get('revision')!=source['revision']
                or result.get('offset')!=offset or result.get('entry_binding') is None
                or result.get('current') is False or result.get('correction_pending') is True
                or result.get('native_binding_current') is False
                or result.get('kind') not in ('integrator_answer','integrator_progress','native_question','route_clarification')
                or result.get('kind')=='integrator_progress' and not result.get('native_returns')
                or not isinstance(result.get('text'),str) or not result['text'].strip()
                or next_offset is not None and (type(next_offset) is not int or not offset<next_offset<=10**9)):
            return None
        return {'kind':'integrating_source','source':dict(source),'text':result['text'],
                'offset':offset,'next_offset':next_offset,'text_bounded':next_offset is not None,
                'meaning':'Attributed integrating content, not human speech. Native acceptance/progress is not task completion.'}

    async def _watch(self,ident,initial=None):
        if self._watching:raise ForegroundUnavailable('An integrating watch is already pending')
        self._watching=True
        source=None
        try:
            if initial is not None:
                await asyncio.to_thread(self.stream.tool_result,ident,initial,will_continue=True)
            while True:
                source=await self._returns.get()
                if source is None:
                    raise ForegroundUnavailable('Foreground conversation ended')
                self._queued.discard((source['id'],source['revision']))
                # Re-read the exact canonical revision at offer time. The
                # queue stores only references, never an authoritative copy.
                result=await self._integrating_part(source,0)
                if result is None:
                    # A newer owner invalidation may offer a current revision.
                    source=None
                    continue
                self._offered[(source['id'],source['revision'])]=dict(source)
                await asyncio.to_thread(self.stream.tool_result,ident,result,will_continue=True)
                source=None
        except asyncio.CancelledError:
            # Cancelling an unoffered read can return its canonical
            # reference to the next watch. An attempted provider response
            # stays terminal/uncertain and is never offered twice.
            if source is not None and not self.closed:
                key=(source['id'],source['revision'])
                if key not in self._offered and key not in self._queued and not self._returns.full():
                    self._returns.put_nowait(source);self._queued.add(key)
                    self.offer_generation+=1  # Only a known-unoffered read can rearm attention.
            raise
        finally:self._watching=False

    def integrating_source(self,source,*,in_context=False):
        """Register an authenticated canonical reference, in setup or for an offer.

        Setup context is already offered to the model, without another spoken
        return. Reads still revalidate the exact canonical source on each page.
        """
        if (self.closed or not isinstance(source,dict) or set(source)-{'id','revision','kind','label'}
                or not isinstance(source.get('id'),str) or len(source['id'])>256
                or not isinstance(source.get('revision'),str) or not re.fullmatch('[a-f0-9]{64}',source['revision'])
                or source.get('kind') not in ('result','question')
                or 'label' in source and (not isinstance(source['label'],str) or len(source['label'])>200)):
            raise ForegroundUnavailable('Select an owned current integrating source')
        key=(source['id'],source['revision'])
        if key in self._offered or key in self._queued:return False
        if (not in_context and self._returns.full()) or len(self._offered)+len(self._queued)>=128:
            raise ForegroundUnavailable('Integrating offers reached the live bound')
        if in_context:self._offered[key]=dict(source)
        else:
            self._returns.put_nowait(dict(source));self._queued.add(key)
            self.offer_generation+=1
        return True

    @property
    def notice_needed(self):
        return (not self.closed and not self._watching and bool(self._queued)
                and self.offer_generation!=self.noticed_generation)

    async def close(self):
        self.closed=True
        # Wake a pending watch without polling or starting another provider call.
        while not self._returns.empty():
            self._returns.get_nowait()
        self._queued.clear()
        self._returns.put_nowait(None)
        # Retain already captured originals. Closing speech never cancels a
        # native task. No new effects start once the live owner is closed.
        pending=[c.reservation for c in self.captures.values() if c.reservation and not c.reservation.done()]
        if pending:
            with suppress(Exception):
                await asyncio.wait_for(asyncio.gather(*(asyncio.shield(t) for t in pending),return_exceptions=True),5)
        for capture in self.captures.values():
            capture.interpretation_ready.set()
            capture.pcm=b''
