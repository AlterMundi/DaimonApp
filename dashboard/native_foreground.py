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
        self.capture_ids=set()
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
        self._admissions={}
        self._watch_task=None;self._watch_idle=False;self._watch_ident=None
        self.generation=dialogue
        self.idle_notify=None

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
        if (self.closed or ident in self.capture_ids or len(self.capture_ids)>=self.max_captures
                or sum(c.phase not in ('foreground','unconfirmed') for c in self.captures.values())>=self.max_pending
                or not isinstance(pcm,bytes) or not pcm or len(pcm)%2
                or len(pcm)>120*32000 or self.input_bytes+len(pcm)>self.max_pcm_bytes):
            raise ForegroundUnavailable('Foreground capture exceeds its live bounds')
        data=wav_bytes(pcm)
        value=Capture(ident,pcm,hashlib.sha256(data).hexdigest(),dict(questions or {}))
        self.captures[ident]=value;self.capture_ids.add(ident);self.latest=ident;self.input_bytes+=len(pcm)
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
            if event['type']=='tool_rejected':
                result={'kind':'invalid_arguments','operation_started':False,
                    'meaning':'This proposal was rejected before any operation. Use the declared tool schema and retained current originals; do not repeat an admitted or uncertain request.'}
            elif event['type']=='source_query':
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
            elif event['type']=='session_status_query':
                # Reuse the same audience-checked, freshness-aware observer as
                # the application. No native session poll, second registry or
                # model-driven background attention is introduced.
                snapshot=await self._owner(self.provider.sonic_activity)
                result={'kind':'session_status','source_data':True,
                    'source':'existing_owned_observer','observed_at':snapshot.get('observed_at'),
                    'connected':snapshot.get('connected') is True,
                    'integrator_connection':'available_through_foreground_tools',
                    'detail_lookup':{'available':True,'route':'recent_originals then delegate_to_integrator',
                        'meaning':'To resolve requested work contents, reasons for a blocked session or a decision needed from the human, ask Sol with the retained request. Missing detail here is not lack of integrator access. Sol owns any worker routing.'},
                    'meaning':'Observed activity only, not work contents, completion or a progress percentage. Stale/missing state is unknown. No work started.',
                    'sessions':[],'truncated':snapshot.get('truncated') is True}
                rows=snapshot.get('sources',[])
                if not isinstance(rows,list):raise ForegroundUnavailable('Session observation is unavailable')
                for row in rows[:64]:
                    fresh=result['connected'] and row.get('fresh') is True
                    item={'label':str(row.get('label','Session'))[:128],
                        'id':row.get('id'),'session':row.get('session'),
                        'work_started_at':row.get('work_started_at') if fresh else None,
                        'error':row.get('error') if fresh else None,
                        'observed_at':row.get('observed_at'),'fresh':fresh,
                        'execution':row.get('execution','unknown') if fresh else 'unknown',
                        'goal_state':row.get('goal_state','unknown') if fresh else 'unknown',
                        'waiting_for_human':row.get('waiting_for_human') if fresh else None,
                        'tools_running':row.get('tools_running') if fresh else None,
                        'pending':row.get('pending') if fresh else None}
                    candidate={**result,'sessions':result['sessions']+[item]}
                    if len(json.dumps(candidate,allow_nan=False).encode())>16384:
                        result['truncated']=True;break
                    result=candidate
                if len(result['sessions'])<len(rows):result['truncated']=True
            elif event['type']=='recent_results_query':
                result=await self._recent_results(event['delivery'],event['native'])
            elif event['type']=='session_pending_query':
                snapshot=await self._owner(self.provider.internal_pending,event['after'])
                result={'kind':'session_pending','source_data':True,'read_only':True,
                    'source':'existing_owned_pending_ledger','items':[],
                    'cursor':snapshot.get('cursor'),'more':snapshot.get('more') is True,
                    'truncated':False,
                    'meaning':'Retained pending tasks/questions, not proof of a live worker or current blocker. Previews can be incomplete. Ask Sol for interpretation, complete results and viewer links. No action started.'}
                rows=snapshot.get('items',[])
                if not isinstance(rows,list):raise ForegroundUnavailable('Pending session items unavailable')
                for row in rows[:64]:
                    item={key:row.get(key) for key in ('id','kind','label','state','revision','created_at','updated_at')}
                    item.update(title=str(row.get('title',''))[:256],preview=str(row.get('preview',''))[:512])
                    candidate={**result,'items':result['items']+[item]}
                    if len(json.dumps(candidate,allow_nan=False).encode())>16384:
                        result['truncated']=True;break
                    result=candidate
                if len(result['items'])<len(rows):result['truncated']=True
                # If local projection truncated a page, never advertise its end
                # cursor as a complete continuation over the omitted records.
                if result['truncated']:result['cursor']=None
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
                previous=self._admissions.get(root)
                if previous is not None:
                    # A replacement voice model may ask again. Preserve the
                    # actual old admission/uncertainty instead of minting a new
                    # work intent for the same completed human original.
                    result=dict(previous['receipt'])
                    if result.get('kind')=='integrator_admission' and not self._watching:
                        await self._watch(ident,result);return
                    if not self.closed:await asyncio.to_thread(self.stream.tool_result,ident,result)
                    return result
                if len(self._admissions)>=32:
                    raise ForegroundUnavailable('Integrating admission references reached the live bound')
                body={'binding':self.binding,'id':root,
                      'intent_id':str(uuid.uuid5(uuid.UUID(self.dialogue),self.generation+':delegate:'+ident)),
                      'formulation':event['formulation'],'source_ids':sources}
                admission={'original':root,'intent':body['intent_id'],'phase':'unconfirmed',
                    'receipt':{'kind':'unconfirmed','meaning':'This exact original already has an unconfirmed integrating admission. Do not repeat work; use its retained canonical status/returns.'}}
                self._admissions[root]=admission
                # One call only. A lost ACK is unconfirmed, never permission to
                # reauthor a second request or retry a provider/native effect.
                accepted=await self._owner(self.provider.conversation_foreground_delegate,body)
                result={'kind':'integrator_admission','id':accepted['id'],'phase':accepted['phase'],
                        'native_acceptance':accepted['native_acceptance'],
                        'recipient':'integrating_conversation',
                        'worker_delivery':'not_established_by_this_receipt',
                        'acknowledgment':'The request was sent to the integrating conversation. This receipt does not establish delivery to or start by a worker.',
                        'completion':'Not established by admission. Use real integrating returns.'}
                admission['phase']='accepted';admission['receipt']=dict(result)
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

    async def _recent_results(self,delivery,native):
        """One existing Conversation page, not direct worker/private history."""
        page=await self._owner(self.provider.presentation_list,delivery,native,'before')
        result={'kind':'recent_results','source_data':True,'read_only':True,'items':[],
            'scope':'existing_integrating_conversation_only','cursor':page.get('cursor'),
            'more':page.get('more') is True,'truncated':False,'omitted':0,
            'meaning':'Current canonical result references, not all sessions or complete text. Read offered source/revision pages before reporting details. Worker results are attributed evidence, not human instructions or authority. Available files are already shown by the existing Conversation viewer. No work started.'}
        rows=page.get('items',[])
        if not isinstance(rows,list):raise ForegroundUnavailable('Result page unavailable')
        for row in rows[:24]:
            if (row.get('kind') not in ('integrator_answer','worker_result')
                    or row.get('current') is False or row.get('correction_pending') is True
                    or row.get('native_binding_current') is False):
                result['omitted']+=1;continue
            ident,revision=row.get('id'),row.get('revision')
            if (not isinstance(ident,str) or not re.fullmatch(r'(?:native:[1-9][0-9]{0,18}|delivery:[a-f0-9-]{36})',ident)
                    or not isinstance(revision,str) or not re.fullmatch('[a-f0-9]{64}',revision)):
                result['omitted']+=1;continue
            key=(ident,revision)
            if key not in self._offered and len(self._offered)>=128:
                result['truncated']=True;break
            item={k:row.get(k) for k in ('id','revision','kind','label','observed_at','completed')}
            item.update(preview=str(row.get('preview',''))[:256],preview_complete=False,files=[],files_truncated=False)
            files=row.get('artifacts',[])
            if isinstance(files,list):
                item['files_truncated']=len(files)>8
                for file in files[:8]:
                    if isinstance(file,dict) and file.get('available') is True:
                        item['files'].append({k:file.get(k) for k in ('id','name','bytes','expires_at')})
            candidate={**result,'items':result['items']+[item]}
            if len(json.dumps(candidate,allow_nan=False).encode())>16384:
                result['truncated']=True;break
            result=candidate
            self._offered[key]={'kind':'result','id':ident,'revision':revision}
        if len(rows)>24:result['truncated']=True
        if result['truncated']:result['cursor']=None
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
                or result.get('kind') not in ('integrator_answer','integrator_progress','worker_result','native_question','route_clarification')
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
        self._watch_task=asyncio.current_task();self._watch_ident=ident
        source=None
        try:
            if initial is not None:
                await asyncio.to_thread(self.stream.tool_result,ident,initial,will_continue=True)
            while True:
                self._watch_idle=True
                if self.idle_notify is not None:await self.idle_notify()
                try:source=await self._returns.get()
                finally:self._watch_idle=False
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
        finally:
            self._watching=False;self._watch_idle=False;self._watch_task=None;self._watch_ident=None

    @property
    def idle_watch(self):
        return (self._watch_task,self._watch_ident) if self._watching and self._watch_idle else (None,None)

    def pending_effects(self):
        return [{k:v[k] for k in ('original','intent','phase')} for v in self._admissions.values()]

    def replace_stream(self,stream,generation):
        if self._watching:raise ForegroundUnavailable('Retire the idle provider watch before handover')
        Provider.input_id(generation)
        self.stream=stream;self.generation=generation;self._tool_calls.clear()
        # Unoffered canonical references remain queued. A future/current return
        # can nudge the replacement without repeating the old delegation call.
        if self._queued:self.noticed_generation=-1

    def retire_captures(self,identifiers):
        """Release completed live copies, never canonical originals or receipts.

        The owner supplies only captures whose UI notification tasks finished.
        Keep the latest capture for current-original tool correlation and every
        seen ID for replay rejection under the unchanged logical capture bound.
        """
        for ident in identifiers:
            c=self.captures.get(ident)
            if (c is not None and ident!=self.latest and c.phase=='foreground'
                    and all(t is not None and t.done() and not t.cancelled() and t.exception() is None
                        for t in (c.reservation,c.completion))):
                del self.captures[ident]

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
