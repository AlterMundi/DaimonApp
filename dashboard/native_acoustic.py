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
    ended_at: float | None = None


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
        self.pcm=bytearray();self.pcm_base=0;self.analyzed=0;self.boundary=0;self.sent=0
        self.spans=[];self.local=None;self.provider=None;self.created=0
        self.markers=[]
        self.closed=False;self.lock=asyncio.Lock();self.changed=asyncio.Event()
        self.boundary_mismatch=None
        self.provider_offset_base=0
        self.renewal_hold=False
        self.peak_analysis_bytes=0;self.peak_unsent_span_bytes=0
        self.peak_confirmation_seconds=0

    def _observe_queues(self):
        # Fixed scalar observations only; no frame log, PCM or transcript copy.
        # Audio duration waiting for analysis differs from wall-clock waiting
        # for the provider's final transcript AND matching activity-end ACK.
        self.peak_analysis_bytes=max(self.peak_analysis_bytes,self.captured-self.analyzed)
        unsent=sum(max(0,(s.end if s.end is not None else s.analyzed)-s.sent) for s in self.spans)
        self.peak_unsent_span_bytes=max(self.peak_unsent_span_bytes,unsent)
        span=self.provider
        if span is not None and span.ended_at is not None:
            self.peak_confirmation_seconds=max(self.peak_confirmation_seconds,
                asyncio.get_running_loop().time()-span.ended_at)

    def diagnostics(self):
        if self.stream.activity_mode!='manual':return None
        return {'peak_analysis_audio_ms':self.peak_analysis_bytes*1000//32000,
                'peak_unsent_span_audio_ms':self.peak_unsent_span_bytes*1000//32000,
                'peak_input_confirmation_wait_ms':round(self.peak_confirmation_seconds*1000)}

    @property
    def captured(self):
        return self.pcm_base+len(self.pcm)

    def _slice(self,start,stop=None):
        if stop is None:stop=self.captured
        if not self.pcm_base<=start<=stop<=self.captured:
            raise ForegroundUnavailable('Acoustic source is outside its retained PCM')
        return bytes(self.pcm[start-self.pcm_base:stop-self.pcm_base])

    def _retire_prefix(self):
        if not self.pcm_base<=self.boundary<=self.captured:
            raise ForegroundUnavailable('Acoustic retirement boundary changed')
        del self.pcm[:self.boundary-self.pcm_base]
        self.pcm_base=self.boundary

    async def retire_completed_prefix(self):
        """Release confirmed originals independently of provider replacement.

        Keep the unassigned tail and every logical/provider clock unchanged.
        An unresolved original or active acoustic span prevents retirement.
        """
        async with self.lock:
            if (self.max_bytes<=300*32000 or self.closed or self.local is not None
                    or self.provider is not None or self.spans):return
            if any(c.phase!='foreground' or c.completion is None
                    or not c.completion.done() or c.completion.cancelled()
                    or c.completion.exception() is not None
                    for c in self.bridge.captures.values()):return
            self._retire_prefix()

    def unsent_originals(self):
        """Only local spans whose provider activity was never started."""
        return {s.ident for s in self.spans if s.stream_start is None and s.sent==s.start}

    def handover_ready(self):
        if self.closed or self.provider is not None:return False
        if self.renewal_hold and self.stream.activity_mode=='manual':
            return all(s.stream_start is None and s.sent==s.start for s in self.spans)
        return self.local is None and not self.spans

    def replace_stream(self,stream):
        """Caller holds the idle acoustic lock; logical PCM/detector offsets stay.

        The new provider starts at byte zero. Keep retained source/capture clocks
        monotonic and rebase only its incoming activity offsets.
        """
        if not self.handover_ready():
            raise ForegroundUnavailable('Acoustic handover requires an idle or wholly unsent boundary')
        if stream.activity_mode!=self.stream.activity_mode:
            raise ForegroundUnavailable('Acoustic handover changed activity ownership')
        if self.stream.activity_mode=='automatic' and (self.boundary!=self.sent or self.unassigned):
            raise ForegroundUnavailable('Automatic handover needs its complete acknowledged input boundary')
        # Only the completed original prefix is retired. Unassigned/trailing
        # PCM stays available for its later exact source or close-time recovery.
        # All capture/detector/provider clocks remain logical and monotonic.
        keep=min([self.boundary]+[s.start for s in self.spans])
        if not self.pcm_base<=keep<=self.captured:
            raise ForegroundUnavailable('Acoustic handover PCM boundary changed')
        del self.pcm[:keep-self.pcm_base];self.pcm_base=keep
        self.provider_offset_base=self.sent;self.stream=stream
        self.renewal_hold=False

    async def marker(self,audio_bytes,questions):
        # The client emits this narrowing snapshot before the PCM containing its
        # first conservative local energy marker. It adds no question authority.
        from .provider import Provider
        Provider.check_capture_questions(questions)
        async with self.lock:
            if (self.closed or type(audio_bytes) is not int or audio_bytes%2
                    or not self.captured<audio_bytes<=self.captured+32000
                    or len(self.markers)>=4 or self.markers and audio_bytes<=self.markers[-1][0]):
                raise ForegroundUnavailable('Capture scope marker does not precede its PCM')
            self.markers.append((audio_bytes,dict(questions or {})))

    async def feed(self,pcm):
        async with self.lock:
            if (self.closed or not isinstance(pcm,bytes) or not pcm or len(pcm)%2
                    or len(pcm)>32000 or self.captured+len(pcm)>self.max_bytes
                    or self.local is not None and self.captured+len(pcm)-self.local.start>120*32000
                    or self.captured+len(pcm)-self.analyzed>self.max_backlog):
                raise ForegroundUnavailable('Native acoustic input exceeds its live bounds')
            self.pcm.extend(pcm)
            self._observe_queues()
            if self.max_bytes>300*32000:
                # One maximum1s frame of close reserve inside each hard bound.
                # Stop after owning this frame so cleanup can retain it, even
                # when onset/analysis or provider confirmation is still late.
                unsent=self.captured-self.analyzed+sum(max(0,
                    (s.end if s.end is not None else s.analyzed)-s.sent) for s in self.spans)
                if (len(self.pcm)>=299*32000 or unsent>=7*32000
                        or self.local is not None and self.captured-self.local.start>=119*32000):
                    raise ForegroundUnavailable('Native voice capacity reached; captured audio needs review')
        # Detector writes do not hold the state lock needed by its event reader.
        await self.detector.feed(pcm)

    async def activity(self,value):
        async with self.lock:
            end=value.get('audio_bytes');generation=value.get('generation')
            if (self.closed or value.get('type')!='activity' or type(end) is not int
                    or end%2 or not self.analyzed<=end<=self.captured
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
                self.bridge.capture(span.ident,self._slice(span.start,end),span.questions)
                await self.detector.boundary({'generation':endpoint['generation'],'audio_bytes':end})
                await self.notify({'type':'phrase_end','id':span.ident,'start':span.start,'end':end})
            await self._pump()

    async def _pump(self):
        self.changed.set()
        if self.closed:return
        self._observe_queues()
        if self.provider is None and self.spans:
            if self.renewal_hold:return
            self.provider=self.spans[0];self.provider.stream_start=self.sent
            await asyncio.to_thread(self.stream.activity_start)
        span=self.provider
        if span is None:return
        end=span.end if span.end is not None else span.analyzed
        if end-span.start>120*32000:
            raise ForegroundUnavailable('Captured phrase exceeds its live bound')
        while span.sent<end:
            stop=min(end,span.sent+32000)
            await asyncio.to_thread(self.stream.append,self._slice(span.sent,stop))
            self.sent+=stop-span.sent;span.sent=stop
        if span.end is not None and span.stream_end is None:
            span.stream_end=self.sent
            await asyncio.to_thread(self.stream.activity_end)
            span.ended_at=asyncio.get_running_loop().time()
            span.final_deadline=span.ended_at+self.transcript_timeout
        if span.end_ack and span.text is not None:
            # One finalized input transcript plus its exact manual-end ACK.
            # Output completion/generation does not finalize a human original.
            self.spans.pop(0);self.provider=None
            if span.text.strip():
                self.bridge.transcript(span.ident,span.text)
                await self.notify({'type':'input_interpreted','id':span.ident,'text':span.text})
            else:
                # Qwen can commit a noise/unclear span with no words. Keep
                # that exact original unconfirmed; do not end unrelated speech.
                await self.notify({'type':'input_uninterpreted','id':span.ident,
                    'reason':'empty_final_transcript'})
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
            if kind not in ('voice_activity','input_transcript','input_committed'):return
            if span is None:raise ForegroundUnavailable('Uncorrelated native input event')
            if kind=='input_committed':
                # Qwen acknowledges the explicit buffered input item, not VAD.
                # Compare the locally retained exact range to the adapter's
                # one outstanding commit; never invent provider sample offsets.
                if ((getattr(self.stream,'model',None),event.get('source')) not in (
                            ('qwen-audio-3.0-realtime-plus','provider_qwen_commit'),
                            ('gpt-realtime-2.1','provider_openai_commit'))
                        or span.stream_end is None or span.start_ack or span.end_ack
                        or type(event.get('stream_start')) is not int
                        or type(event.get('stream_end')) is not int
                        or event['stream_start']+self.provider_offset_base!=span.stream_start
                        or event['stream_end']+self.provider_offset_base!=span.stream_end
                        or not isinstance(event.get('item_id'),str) or not event['item_id']):
                    raise ForegroundUnavailable('Provider input commitment does not match the captured phrase')
                span.start_ack=span.end_ack=True
            elif kind=='voice_activity':
                if event.get('source')!='provider_manual_activity_ack':
                    raise ForegroundUnavailable('Native activity is not the selected manual protocol')
                start=event.get('activity')=='ACTIVITY_START'
                target=span.stream_start if start else span.stream_end
                offset=self._offset(event.get('audio_offset'))+self.provider_offset_base
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
                        if not combined.strip() and not (
                                getattr(self.stream,'model',None)=='qwen-audio-3.0-realtime-plus'
                                and span.end_ack and span.stream_end is not None):
                            raise ForegroundUnavailable('Input transcript is empty')
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

    async def close(self,*,recover_unassigned=False):
        if type(recover_unassigned) is not bool:
            raise ValueError('Select explicit unassigned-tail recovery')
        async with self.lock:
            if self.closed:return
            if self.stream.activity_mode=='manual':self._observe_queues()
            self.closed=True;self.changed.set()
            # A disconnect does not throw away an unfinished original.
            # It remains foreground_captured, never automatically delegated.
            if self.local and self.captured>self.local.start:
                span=self.local
                self.bridge.capture(span.ident,self._slice(span.start),span.questions,recovery=True)
            elif recover_unassigned:
                # The detector/provider may not yet have marked speech. Retain
                # only the raw tail after the last captured span, without a
                # transcript, asserted speech boundary or automatic delegation.
                # No onset means the earlier arm-time scope remains frozen.
                for start in range(self.boundary,self.captured,120*32000):
                    stop=min(self.captured,start+120*32000)
                    self.bridge.capture(str(uuid.uuid4()),self._slice(start,stop),
                                        self.questions,recovery=True)
            self.pcm_base=self.captured
            self.pcm.clear();self.local=None;self.spans.clear();self.provider=None


class NativeAutomaticAcousticSession(NativeAcousticSession):
    """Own provider-detected spans on the continuous, uncompressed PCM timeline.

    Automatic boundaries identify originals, never authorize work. An ambiguous
    transcript ends the live attempt with its exact recordings kept for review.
    """
    def __init__(self,bridge,questions,notify):
        if bridge.stream.activity_mode!='automatic':
            raise ValueError('Select automatic native activity')
        super().__init__(bridge,None,questions,notify)
        self.unassigned=False

    async def feed(self,pcm):
        async with self.lock:
            if (self.closed or not isinstance(pcm,bytes) or not pcm or len(pcm)%2
                    or len(pcm)>32000 or self.captured+len(pcm)>self.max_bytes
                    or self.local is not None and self.captured+len(pcm)-self.local.start>120*32000):
                raise ForegroundUnavailable('Native acoustic input exceeds its live bounds')
            self.pcm.extend(pcm)
            # Serialize with provider offsets; a failed write is never replayed.
            await asyncio.to_thread(self.stream.append,pcm)
            self.sent+=len(pcm)

    async def activity(self,value):
        raise ForegroundUnavailable('Automatic activity has no local detector authority')

    async def _pump(self):
        self.changed.set()
        span=self.provider
        if not self.closed and span and span.end_ack and span.text is not None:
            self.bridge.transcript(span.ident,span.text)
            self.spans.remove(span);self.provider=None
            self.bridge.pending_acoustic=None
            await self.notify({'type':'input_interpreted','id':span.ident,'text':span.text})

    async def provider_event(self,event):
        async with self.lock:
            if self.closed:raise ForegroundUnavailable('Native acoustic conversation ended')
            kind=event['type']
            if kind not in ('voice_activity','input_transcript'):return
            span=self.provider
            if kind=='voice_activity':
                if event.get('source')!='provider_automatic_activity':
                    raise ForegroundUnavailable('Native activity is not the selected automatic protocol')
                offset=self._offset(event.get('audio_offset'))+self.provider_offset_base
                if offset!=offset.to_integral_value() or offset%2 or not self.boundary<=offset<=self.sent:
                    raise ForegroundUnavailable('Automatic boundary does not match transmitted PCM')
                offset=int(offset)
                if event.get('activity')=='ACTIVITY_START':
                    if self.local is not None or self.created>=self.max_spans or len(self.spans)>=4:
                        raise ForegroundUnavailable('Automatic start needs source review')
                    start=max(self.boundary,offset-16000)
                    scope=next((q for n,q in self.markers if self.boundary<n<=offset),self.questions)
                    self.markers=[(n,q) for n,q in self.markers if n>offset]
                    new=Span(str(uuid.uuid4()),start,self.created+1,offset,
                             questions=dict(scope),stream_start=offset,start_ack=True)
                    self.local=new;self.spans.append(new);self.created+=1
                    self.bridge.pending_acoustic=new.ident
                    await self.notify({'type':'capture_started','id':new.ident,'start':start})
                    # Retain the new tail on close even if the previous final
                    # text is missing. Never guess which source unmarked text owns.
                    if span is not None:
                        raise ForegroundUnavailable('Previous automatic interpretation needs review')
                    self.provider=new;self.changed.set()
                    return new.ident
                if (event.get('activity')!='ACTIVITY_END' or span is None or self.local is not span
                        or span.end_ack or offset<=span.stream_start or offset<=span.start):
                    raise ForegroundUnavailable('Automatic end needs source review')
                span.end=span.stream_end=offset;span.end_ack=True
                self.local=None;self.boundary=offset
                self.markers=[(n,q) for n,q in self.markers if n>offset]
                self.bridge.capture(span.ident,self._slice(span.start,offset),span.questions)
                await self.notify({'type':'phrase_end','id':span.ident,'start':span.start,'end':offset})
                span.final_deadline=asyncio.get_running_loop().time()+self.transcript_timeout
            else:
                text=event.get('text')
                if span is None:
                    # Speech text without an owned START cannot be bound to a
                    # previous original. Keep its unassigned raw tail on close,
                    # without interpreting or dispatching that fallback audio.
                    self.unassigned=True
                    raise ForegroundUnavailable('Input transcript has no owned automatic start')
                if span.text is not None or not isinstance(text,str):
                    raise ForegroundUnavailable('Input transcript needs source review')
                if 'finished' in event:
                    if type(event['finished']) is not bool:
                        raise ForegroundUnavailable('Input transcript completion is invalid')
                    text=span.transcript_parts+text
                    if len(text.encode())>16000:
                        raise ForegroundUnavailable('Input transcript exceeds its live bound')
                    span.transcript_parts=text;span.fragmented=True
                    if event['finished']:
                        if not text.strip():raise ForegroundUnavailable('Input transcript is empty')
                        span.text=text
                    await self.notify({'type':'input_caption','id':span.ident,'text':text})
                else:
                    if span.fragmented or not text.strip() or len(text.encode())>16000:
                        raise ForegroundUnavailable('Input transcript needs source review')
                    # Observed automatic protocol sends final text just BEFORE
                    # END. Buffer it; only a validated END can close the original.
                    span.text=text
            ident=span.ident
            await self._pump()
            return ident

    async def close(self,*,recover_unassigned=False):
        if type(recover_unassigned) is not bool:
            raise ValueError('Select explicit unassigned-tail recovery')
        await super().close(recover_unassigned=(self.unassigned or recover_unassigned))
