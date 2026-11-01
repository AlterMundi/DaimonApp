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
    end: int | None = None
    sent: int = 0
    stream_start: int | None = None
    stream_end: int | None = None
    start_ack: bool = False
    end_ack: bool = False
    text: str | None = None


class NativeAcousticSession:
    max_bytes=300*32000
    max_backlog=8*32000
    max_spans=128

    def __init__(self,bridge,detector,questions,notify):
        self.bridge,self.stream,self.detector=bridge,bridge.stream,detector
        # An arm-time narrowing scope is safe when the first local acoustic
        # marker cannot be observed before confirmed speech.
        self.questions=dict(questions or {})
        self.notify=notify
        self.pcm=bytearray();self.analyzed=0;self.boundary=0;self.sent=0
        self.spans=[];self.local=None;self.provider=None;self.created=0
        self.closed=False;self.lock=asyncio.Lock()

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
                    self.local=Span(str(uuid.uuid4()),start,generation,end,sent=start)
                    self.spans.append(self.local);self.created+=1
                    await self.notify({'type':'capture_started','id':self.local.ident,'start':start})
                else:self.local.generation=generation
            if self.local:self.local.analyzed=end
            endpoint=value.get('endpoint')
            if endpoint:
                if (self.local is None or endpoint.get('generation')!=self.local.generation
                        or endpoint.get('audio_bytes')!=end or endpoint.get('authority')!='analysis_only'
                        or type(endpoint.get('probability')) not in (int,float)
                        or not .5<=endpoint['probability']<=1 or value.get('speaking') is not False):
                    raise ForegroundUnavailable('Acoustic endpoint changed')
                span=self.local
                if end-span.start>120*32000:
                    raise ForegroundUnavailable('Captured phrase exceeds its live bound')
                span.end=end;self.local=None;self.boundary=end
                self.bridge.capture(span.ident,bytes(self.pcm[span.start:end]),self.questions)
                await self.detector.boundary({'generation':endpoint['generation'],'audio_bytes':end})
                await self.notify({'type':'phrase_end','id':span.ident,'start':span.start,'end':end})
            await self._pump()

    async def _pump(self):
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
        if span.end_ack and span.text is not None:
            # One finalized input transcript plus its exact manual-end ACK.
            # Output completion/generation does not finalize a human original.
            self.bridge.transcript(span.ident,span.text)
            self.spans.pop(0);self.provider=None
            await self.notify({'type':'input_interpreted','id':span.ident,'text':span.text})
            await self._pump()

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
                if target is None or abs(self._offset(event.get('audio_offset'))-target)>2:
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
                if (not span.start_ack or span.text is not None or not isinstance(text,str)
                        or not text.strip() or len(text.encode())>16000):
                    raise ForegroundUnavailable('Input transcript needs source review')
                span.text=text
            await self._pump()

    async def close(self):
        async with self.lock:
            if self.closed:return
            self.closed=True
            # A disconnect does not throw away an unfinished, analyzed original.
            # It remains foreground_captured, never automatically delegated.
            if self.local and len(self.pcm)>self.local.start:
                span=self.local
                self.bridge.capture(span.ident,bytes(self.pcm[span.start:]),self.questions)
            self.pcm.clear();self.local=None;self.spans.clear();self.provider=None
