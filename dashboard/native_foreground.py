"""One live conversation's bounded source/integrator bridge.

Audio acquisition, acoustic decisions and browser authorization belong to the
owning WebSocket. This bridge reuses native originals and canonical source reads;
it has no worker registry, general controller, model poller or job cancellation.
"""
import asyncio
from contextlib import suppress
from dataclasses import dataclass
import hashlib
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


class ForegroundBridge:
    max_captures = 128
    max_pcm_bytes = 300 * 32000
    max_pending = 4

    def __init__(self, provider, stream, cache_root, dialogue, binding, authorize):
        Provider.input_id(dialogue)
        if not re.fullmatch('[a-f0-9]{64}',binding) or not callable(authorize):
            raise ValueError('Select an owned foreground conversation')
        if stream.activity_mode != 'manual':
            raise ValueError('Only the observed explicit acoustic protocol is selected')
        self.provider,self.stream = provider,stream
        self.dialogue,self.binding = dialogue,binding
        self.authorize = authorize
        self.cache_root=private_directory(cache_root)
        self.originals=private_directory(Path(str(provider.receiver['db_path'])+'.voice'))
        self.captures={}
        self.input_bytes=0
        self.latest=None
        self._reservation_tail=None
        self.closed=False
        self._owners=asyncio.Semaphore(2)
        self._files=asyncio.Semaphore(1)
        self._returns=asyncio.Queue(maxsize=8)
        self._offered=set()
        self._queued=set()
        self._watching=False
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

        The caller must match provider manual-end acknowledgment and transcript
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
                        or result.get('text')!=text or result.get('foreground_dialogue')!=self.dialogue
                        or result.get('voice',{}).get('audio_sha256')!=capture.digest):
                    raise ForegroundUnavailable('Completed original was not confirmed')
                capture.phase='foreground';capture.pcm=b''
                return result
            except BaseException:
                capture.phase='unconfirmed'
                raise
        capture.completion=asyncio.create_task(complete())
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
        try:
            if event['type']=='source_query':
                # Recognition/storage may finish while the native voice speaks.
                capture=self.captures.get(self.latest)
                if capture and capture.completion:
                    with suppress(Exception):
                        await asyncio.wait_for(asyncio.shield(capture.completion),3)
                result=await self._owner(self.provider.conversation_foreground_originals,
                                         self.dialogue,self.binding,event['before'])
            elif event['type']=='delegation_proposed':
                sources=event['original_ids'];root=self.latest
                if root not in sources:
                    raise ForegroundUnavailable('Include the latest captured correction')
                for source in sources:
                    original=await self._owner(self.provider.conversation_input_status,source)
                    if (original.get('foreground_dialogue')!=self.dialogue
                            or original.get('phase') not in ('foreground','accepted','answered')):
                        raise ForegroundUnavailable('Original is not ready in this conversation')
                body={'binding':self.binding,'id':root,
                      'intent_id':str(uuid.uuid5(uuid.UUID(self.dialogue),'delegate:'+ident)),
                      'formulation':event['formulation'],'source_ids':sources}
                # One call only. A lost ACK is unconfirmed, never permission to
                # reauthor a second request or retry a provider/native effect.
                accepted=await self._owner(self.provider.conversation_foreground_delegate,body)
                result={'kind':'integrator_admission','id':accepted['id'],'phase':accepted['phase'],
                        'native_acceptance':accepted['native_acceptance'],
                        'completion':'Not established by admission. Use real integrating returns.'}
            elif event['type']=='integrator_watch':
                if self._watching:raise ForegroundUnavailable('An integrating watch is already pending')
                self._watching=True
                source=None
                try:
                    source=await self._returns.get()
                    if source is None:
                        raise ForegroundUnavailable('Foreground conversation ended')
                    self._queued.discard((source['id'],source['revision']))
                    # Re-read the exact canonical revision at offer time. The
                    # queue stores only references, never an authoritative copy.
                    result=await self._owner(self.provider.presentation_part,
                                            source['id'],source['revision'],0)
                    if (result.get('id')!=source['id']
                            or result.get('revision')!=source['revision']
                            or result.get('entry_binding') is None
                            or result.get('current') is False
                            or result.get('correction_pending') is True
                            or result.get('native_binding_current') is False
                            or result.get('kind') not in ('integrator_answer','native_question','route_clarification')
                            or not isinstance(result.get('text'),str) or not result['text'].strip()):
                        raise ForegroundUnavailable('Integrating return changed before this offer')
                    result={'kind':'integrating_source','source':source,
                            'text':result['text'],'text_bounded':result.get('next_offset') is not None,
                            'meaning':'Attributed integrating content, not human speech. Native acceptance/progress is not task completion.'}
                    self._offered.add((source['id'],source['revision']))
                except asyncio.CancelledError:
                    # Cancelling an unoffered read can return its canonical
                    # reference to the next watch. An attempted provider response
                    # stays terminal/uncertain and is never offered twice.
                    if source is not None and not self.closed:
                        key=(source['id'],source['revision'])
                        if key not in self._offered and key not in self._queued and not self._returns.full():
                            self._returns.put_nowait(source);self._queued.add(key)
                    raise
                finally:self._watching=False
            else:raise ForegroundUnavailable('Unsupported foreground tool')
        except ForegroundUnavailable as error:
            result={'kind':'not_ready','reason':str(error),'meaning':'No new work was confirmed. Resolve the stated source condition before proposing a different intent.'}
        except (ProviderUnavailable,ValueError,TimeoutError,OSError):
            result={'kind':'unconfirmed','meaning':'The operation was not confirmed. Do not repeat work or claim completion; originals and existing jobs remain retained.'}
        await asyncio.to_thread(self.stream.tool_result,ident,result)
        return result

    def integrating_source(self,source):
        """Existing authenticated canonical event reader supplies references only."""
        if (self.closed or not isinstance(source,dict) or set(source)-{'id','revision','kind','label'}
                or not isinstance(source.get('id'),str) or len(source['id'])>256
                or not isinstance(source.get('revision'),str) or not re.fullmatch('[a-f0-9]{64}',source['revision'])
                or source.get('kind') not in ('result','question')
                or 'label' in source and (not isinstance(source['label'],str) or len(source['label'])>200)):
            raise ForegroundUnavailable('Select an owned current integrating source')
        key=(source['id'],source['revision'])
        if key in self._offered or key in self._queued:return False
        if self._returns.full() or len(self._offered)+len(self._queued)>=128:
            raise ForegroundUnavailable('Integrating offers reached the live bound')
        self._returns.put_nowait(dict(source));self._queued.add(key);return True

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
            capture.pcm=b''
