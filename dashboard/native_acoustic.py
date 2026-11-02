"""Map owned acoustic boundaries to one native-audio stream and exact originals.

Detector events are server observations, never client/provider tool authority.
Native speech does not await a Sol turn, separate ASR or separate speech renderer.
At most one provider activity awaits its input transcript; later local spans are
bounded and retained in acoustic order rather than misattributed to that activity.
"""
import asyncio
from dataclasses import dataclass
from decimal import Decimal
import re
import uuid

from .native_foreground import ForegroundUnavailable


@dataclass
class Span:
    ident: str
    start: int
    generation: int
    analyzed: int
    questions: dict | None = None
    end: int | None = None
    sent: int = 0
    stream_start: int | None = None
    stream_end: int | None = None
    start_ack: bool = False
    end_ack: bool = False
    text: str | None = None
    transcript_parts: str = ''
    fragmented: bool = False
    final_deadline: float | None = None


class NativeAcousticSession:
    max_bytes=300*32000
    max_backlog=8*32000
    max_spans=128
    transcript_timeout=15

    def __init__(self,bridge,detector,questions,notify):
        self.bridge,self.stream,self.detector=bridge,bridge.stream,detector
        # An arm-time narrowing scope is safe when the first local acoustic
        # marker cannot be observed before confirmed speech.
        self.questions=dict(questions or {})
        self.notify=notify
        self.pcm=bytearray();self.analyzed=0;self.boundary=0;self.sent=0
        self.spans=[];self.local=None;self.provider=None;self.created=0
        self.markers=[]
        self.closed=False;self.lock=asyncio.Lock();self.changed=asyncio.Event()
        self.boundary_mismatch=None

    async def marker(self,audio_bytes,questions):
        # The client emits this narrowing snapshot before the PCM containing its
        # first conservative local energy marker. It adds no question authority.
        from .provider import Provider
        Provider.check_capture_questions(questions)
        async with self.lock:
            if (self.closed or type(audio_bytes) is not int or audio_bytes%2
                    or not len(self.pcm)<audio_bytes<=len(self.pcm)+32000
                    or len(self.markers)>=4 or self.markers and audio_bytes<=self.markers[-1][0]):
                raise ForegroundUnavailable('Capture scope marker does not precede its PCM')
            self.markers.append((audio_bytes,dict(questions or {})))

    async def feed(self,pcm):
        async with self.lock:
            if (self.closed or not isinstance(pcm,bytes) or not pcm or len(pcm)%2
                    or len(pcm)>32000 or len(self.pcm)+len(pcm)>self.max_bytes
                    or self.local is not None and len(self.pcm)+len(pcm)-self.local.start>120*32000
                    or len(self.pcm)+len(pcm)-self.analyzed>self.max_backlog):
                raise ForegroundUnavailable('Native acoustic input exceeds its live bounds')
            self.pcm.extend(pcm)
        # Detector writes do not hold the state lock needed by its event reader.
        await self.detector.feed(pcm)

    async def activity(self,value):
        async with self.lock:
            end=value.get('audio_bytes');generation=value.get('generation')
            if (self.closed or value.get('type')!='activity' or type(end) is not int
                    or end%2 or not self.analyzed<=end<=len(self.pcm)
                    or type(generation) is not int or generation<0):
                raise ForegroundUnavailable('Acoustic activity does not match captured PCM')
            self.analyzed=end
            onset=value.get('onset')
            if onset:
                if (type(onset.get('audio_bytes')) is not int or not self.boundary<onset['audio_bytes']<=end
                        or onset.get('generation')!=generation):
                    raise ForegroundUnavailable('Acoustic onset changed')
                if self.local is None:
                    if len(self.spans)>=4 or self.created>=self.max_spans:
                        raise ForegroundUnavailable('Captured phrases need review before more voice')
                    start=max(self.boundary,onset['audio_bytes']-16000)
                    scope=next((q for n,q in self.markers if self.boundary<n<=onset['audio_bytes']),self.questions)
                    self.markers=[(n,q) for n,q in self.markers if n>onset['audio_bytes']]
                    self.local=Span(str(uuid.uuid4()),start,generation,end,questions=dict(scope),sent=start)
                    self.spans.append(self.local);self.created+=1
                    await self.notify({'type':'capture_started','id':self.local.ident,'start':start})
                else:self.local.generation=generation
            if self.local:self.local.analyzed=end
            endpoint=value.get('endpoint')
            if endpoint:
                semantic=(endpoint.get('authority')=='analysis_only'
                          and type(endpoint.get('probability')) in (int,float)
                          and .5<=endpoint['probability']<=1)
                acoustic=(endpoint.get('authority')=='acoustic_silence'
                          and type(endpoint.get('silence_millis')) is int
                          and endpoint['silence_millis']>=1600)
                if (self.local is None or endpoint.get('generation')!=self.local.generation
                        or endpoint.get('audio_bytes')!=end or not (semantic or acoustic)
                        or value.get('speaking') is not False):
                    raise ForegroundUnavailable('Acoustic endpoint changed')
                span=self.local
                if end-span.start>120*32000:
                    raise ForegroundUnavailable('Captured phrase exceeds its live bound')
                span.end=end;self.local=None;self.boundary=end
                self.markers=[(n,q) for n,q in self.markers if n>end]
                self.bridge.capture(span.ident,bytes(self.pcm[span.start:end]),span.questions)
                await self.detector.boundary({'generation':endpoint['generation'],'audio_bytes':end})
                await self.notify({'type':'phrase_end','id':span.ident,'start':span.start,'end':end})
            await self._pump()

    async def _pump(self):
        self.changed.set()
        if self.closed:return
        if self.provider is None and self.spans:
            self.provider=self.spans[0];self.provider.stream_start=self.sent
            await asyncio.to_thread(self.stream.activity_start)
        span=self.provider
        if span is None:return
        end=span.end if span.end is not None else span.analyzed
        if end-span.start>120*32000:
            raise ForegroundUnavailable('Captured phrase exceeds its live bound')
        while span.sent<end:
            stop=min(end,span.sent+32000)
            await asyncio.to_thread(self.stream.append,bytes(self.pcm[span.sent:stop]))
            self.sent+=stop-span.sent;span.sent=stop
        if span.end is not None and span.stream_end is None:
            span.stream_end=self.sent
            await asyncio.to_thread(self.stream.activity_end)
            span.final_deadline=asyncio.get_running_loop().time()+self.transcript_timeout
        if span.end_ack and span.text is not None:
            # One finalized input transcript plus its exact manual-end ACK.
            # Output completion/generation does not finalize a human original.
            self.bridge.transcript(span.ident,span.text)
            self.spans.pop(0);self.provider=None
            await self.notify({'type':'input_interpreted','id':span.ident,'text':span.text})
            await self._pump()

    async def watch_transcripts(self):
        """Bound a missing final transcript/ACK, independently of model tool calls."""
        loop=asyncio.get_running_loop()
        while True:
            async with self.lock:
                if self.closed:return
                span=self.provider
                deadline=span.final_deadline if span else None
                self.changed.clear()
            try:
                if deadline is None:await self.changed.wait()
                else:await asyncio.wait_for(self.changed.wait(),max(0,deadline-loop.time()))
            except TimeoutError:
                async with self.lock:
                    expired=(not self.closed and self.provider is span
                             and span.final_deadline==deadline and loop.time()>=deadline)
                if expired:
                    await self.notify({'type':'review','id':span.ident,
                        'message':'The final voice transcript was not confirmed in time. Your recording is kept for review; integrating work continues.'})
                    return

    @staticmethod
    def _offset(value):
        if not isinstance(value,str) or not re.fullmatch(r'[0-9]{1,3}(?:\.[0-9]{1,9})?s',value):
            raise ForegroundUnavailable('Provider activity offset unavailable')
        return Decimal(value[:-1])*32000

    async def provider_event(self,event):
        async with self.lock:
            if self.closed:raise ForegroundUnavailable('Native acoustic conversation ended')
            kind=event['type'];span=self.provider
            if kind not in ('voice_activity','input_transcript'):return
            if span is None:raise ForegroundUnavailable('Uncorrelated native input event')
            if kind=='voice_activity':
                if event.get('source')!='provider_manual_activity_ack':
                    raise ForegroundUnavailable('Native activity is not the selected manual protocol')
                start=event.get('activity')=='ACTIVITY_START'
                target=span.stream_start if start else span.stream_end
                offset=self._offset(event.get('audio_offset'))
                if target is None or abs(offset-target)>2:
                    # Fixed scalar timing evidence only; never provider text,
                    # PCM, exception contents or an unvalidated event payload.
                    self.boundary_mismatch={'activity':'start' if start else 'end',
                        'expected_pcm_bytes':target,'reported_offset_nanoseconds':int(offset*31250),
                        'sent_pcm_bytes':self.sent,'provider_input_bytes':getattr(self.stream,'input_bytes',None),
                        'span_start':span.start,'span_end':span.end,
                        'start_observed':span.start_ack,'end_observed':span.end_ack}
                    raise ForegroundUnavailable('Provider activity does not match captured audio')
                if start:
                    if span.start_ack:raise ForegroundUnavailable('Repeated native activity start')
                    span.start_ack=True
                else:
                    if not span.start_ack or span.end_ack:
                        raise ForegroundUnavailable('Unexpected native activity end')
                    span.end_ack=True
            else:
                text=event.get('text')
                if not span.start_ack or span.text is not None or not isinstance(text,str):
                    raise ForegroundUnavailable('Input transcript needs source review')
                if 'finished' in event:
                    if type(event['finished']) is not bool:
                        raise ForegroundUnavailable('Input transcript completion is invalid')
                    combined=span.transcript_parts+text
                    if len(combined.encode())>16000:
                        raise ForegroundUnavailable('Input transcript exceeds its live bound')
                    span.transcript_parts=combined;span.fragmented=True
                    if event['finished']:
                        if not combined.strip():raise ForegroundUnavailable('Input transcript is empty')
                        span.text=combined
                    await self.notify({'type':'input_caption','id':span.ident,'text':combined})
                else:
                    # Preserve the observed single-transcript protocol. Once
                    # fragmentation is explicit, absence of a marker cannot
                    # silently finish it or substitute model turn completion.
                    if (span.fragmented or span.end is None or span.stream_end is None
                            or not text.strip() or len(text.encode())>16000):
                        raise ForegroundUnavailable('Input transcript needs source review')
                    span.text=text
            await self._pump()

    async def close(self):
        async with self.lock:
            if self.closed:return
            self.closed=True;self.changed.set()
            # A disconnect does not throw away an unfinished, analyzed original.
            # It remains foreground_captured, never automatically delegated.
            if self.local and len(self.pcm)>self.local.start:
                span=self.local
                self.bridge.capture(span.ident,bytes(self.pcm[span.start:]),span.questions)
            self.pcm.clear();self.local=None;self.spans.clear();self.provider=None
