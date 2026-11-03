"""Explicit authenticated native-audio foreground; existing owners retain work."""
import asyncio
import base64
from collections import deque
from contextlib import suppress
import hashlib
import json
import logging
from pathlib import Path
import re
import time
import uuid

from fastapi import HTTPException, WebSocket
from starlette.websockets import WebSocketDisconnect

from scripts.speech_render import private_bytes, RenderError

from .live import changes
from .live_transcription import VoiceInbox
from .native_acoustic import NativeAcousticSession, NativeAutomaticAcousticSession
from .native_dialogue import NativeDialogue, DialogueUnavailable
from .native_foreground import ForegroundBridge, ForegroundUnavailable
from .native_context import NativeContext
from .provider import Provider, ProviderUnavailable
from .turn_detection import Detector, DetectionUnavailable


def failure_site(error):
    """Source location only: never exception text, locals or absolute paths."""
    site=None;trace=error.__traceback__
    modules={'dashboard.native_voice','dashboard.native_acoustic','dashboard.native_foreground','dashboard.native_dialogue','dashboard.live_transcription','dashboard.native_context'}
    while trace is not None:
        module=trace.tb_frame.f_globals.get('__name__')
        if module in modules:
            site=f"{module.rsplit('.',1)[-1]}.{trace.tb_frame.f_code.co_name}:{trace.tb_lineno}"
        trace=trace.tb_next
    return site


def playback_status(value):
    """Untrusted client observations: fixed scalars only, never audio authority."""
    counts={'handled','scheduled','ended','skipped_floor','skipped_muted','skipped_retired'}
    flags={'audible','user_paused','floor','blocked'}
    if (not isinstance(value,dict) or set(value)!={'type','context',*counts,*flags}
            or value.get('type')!='playback_status'
            or value.get('context') not in ('running','suspended','interrupted','closed','native','unavailable')
            or any(type(value[k]) is not int or not 0<=value[k]<=16384 for k in counts)
            or any(type(value[k]) is not bool for k in flags)):
        raise ValueError('Invalid native playback observation')
    return {k:value[k] for k in sorted(counts|flags|{'context'})}


def being_identity(selected):
    """Explicit owner-selected SOUL context, not memory/authority or a browser upload."""
    path=selected.get('native_identity_file')
    if path is None:return None
    try:
        raw=private_bytes(path,8192)
        text=raw.decode('utf-8').strip()
        if not text or '\0' in text:raise ValueError('Empty or invalid identity')
    except (OSError,ValueError,UnicodeError,RenderError):
        raise ForegroundUnavailable('Selected voice identity is unavailable') from None
    return {'source':'owner_selected_being_identity','text':text,
            'sha256':hashlib.sha256(raw).hexdigest(),
            'meaning':'Same-being identity and selected SOUL context; not new human speech, work authority or a complete memory corpus.'}


def install(app,config,provider,origins,bind_voice,detector_command,active):
    selected=config['streaming_transcription']
    activity_mode=selected.get('native_activity_mode','manual')
    app.state.native_voice_enabled=True

    @app.websocket('/api/interaction/voice/native')
    async def native_voice(socket:WebSocket):
        if socket.headers.get('origin') not in origins:
            await socket.close(code=1008);return
        await socket.accept()
        owner=None;bridge=acoustic=worker=stream=inbox=opening=incoming=None
        context_producer=None
        control_task=None;control_dirty=False
        tasks=set();tool_tasks=set();proposals={};cancelled_proposals=set();raw_notifications={};sending=asyncio.Lock();stopping=False
        utterance=None;output_text='';output_bytes=0;output_hash=hashlib.sha256()
        started=time.monotonic();close_stage='preflight';close_error=None;close_site=None;first_send_failure=None
        first_playback_status=last_playback_status=None;playback_status_count=0
        async def send(value):
            nonlocal first_send_failure
            async with sending:
                try:await asyncio.wait_for(socket.send_json(value),3)
                except Exception as error:
                    if first_send_failure is None:
                        task=asyncio.current_task();name=task.get_name() if task else None
                        first_send_failure={'error_type':type(error).__name__,
                            'stage':name if name in {'native-output','native-analysis','native-returns','native-transcripts','native-tool'} else 'native-input',
                            'elapsed_ms':round((time.monotonic()-started)*1000)}
                    raise
        async def flush_output(*,interrupted=False,closed=False,emit=True):
            nonlocal utterance,output_text,output_bytes,output_hash
            if utterance is None:return
            record=await asyncio.to_thread(app.state.native_history.retain,owner,meta['id'],meta['binding'],
                utterance,output_text,output_hash.hexdigest(),output_bytes,interrupted=interrupted,closed=closed)
            if not stopping and emit:await send({'type':'assistant_utterance','utterance':record})
            if closed:
                if context_producer is not None:context_producer.notify()
                utterance=None;output_text='';output_bytes=0;output_hash=hashlib.sha256()
        async def acoustic_event(value):
            await send(value)
            if value['type']=='phrase_end':
                capture=bridge.captures[value['id']]
                async def retained():
                    await asyncio.shield(capture.reservation)
                    await actor()
                    await send({'type':'original_retained','id':capture.ident,'sha256':capture.digest})
                raw_notifications[capture.ident]=launch(retained())
            elif value['type']=='input_interpreted':
                capture=bridge.captures[value['id']]
                async def completed():
                    await asyncio.shield(capture.completion)
                    await asyncio.shield(raw_notifications[capture.ident])
                    await actor()
                    await send({'type':'original_completed','id':capture.ident,'sha256':capture.digest,'phase':'foreground'})
                    if context_producer is not None:context_producer.notify()
                launch(completed())
        def launch(operation):
            task=asyncio.create_task(operation,name='native-tool');tool_tasks.add(task)
            return task
        def guidance_floor():
            return (acoustic is not None and not stopping and not acoustic.closed
                and acoustic.local is None and acoustic.provider is None and not acoustic.spans
                and not stream.input_active and not stream.response_pending)
        async def guide_if_idle():
            if context_producer is None or not guidance_floor():return
            async def ready(frame):
                if not guidance_floor():return False
                if frame['mode']=='spoken_offer' and await asyncio.to_thread(app.state.native_history.pending_audio,owner,meta['id']):return False
                return guidance_floor()
            async def deliver(frame):
                await actor()
                if not await ready(frame):return False
                # The control claim happens outside this floor lock. Only the
                # final send is serialized with captured PCM/provider offsets.
                async with acoustic.lock:
                    if not guidance_floor():return False
                    return await asyncio.to_thread(stream.guide,frame)
            await context_producer.offer_guidance(deliver,ready)
        async def control_if_idle():
            await guide_if_idle()
            # Existing pending tools already stream returns. A new session or
            # cancelled watch needs one event-driven, attributed control notice.
            def available():
                return (bridge is not None and bridge.notice_needed and acoustic is not None
                        and acoustic.local is None and acoustic.provider is None and not acoustic.spans
                        and not stream.input_active and not stream.response_pending)
            if not available():return
            await actor()
            if await asyncio.to_thread(app.state.native_history.pending_audio,owner,meta['id']):return
            if not available():return
            generation=bridge.offer_generation
            if await asyncio.to_thread(stream.notify_integrator_update):
                bridge.noticed_generation=generation
        async def notice_if_idle():
            # Native control can wait on its owner socket. It must never hold
            # the provider receive loop or prevent an arriving speech boundary.
            # Coalesce changes while preserving a notice arriving during send.
            nonlocal control_task,control_dirty
            if stopping:return
            control_dirty=True
            if control_task is not None and not control_task.done():return
            async def controls():
                nonlocal control_dirty
                while control_dirty and not stopping:
                    control_dirty=False
                    await control_if_idle()
            control_task=launch(controls())

        async def outputs():
            nonlocal utterance,output_text,output_bytes,output_hash
            pending=deque()
            async def next_event():
                while not pending:pending.extend(await asyncio.to_thread(stream.receive))
                return pending.popleft()
            queued=VoiceInbox(next_event,batch_size=50)
            try:
                while True:
                    events=await queued.batch()
                    await actor()
                    for event in events:
                        kind=event['type']
                        if kind in ('tool_rejected','recent_results_query','session_pending_query','source_query','session_status_query','integrating_source_query','delegation_proposed','integrator_watch'):
                            proposals[event['call_id']]=launch(bridge.tool(event));continue
                        if kind=='proposal_cancelled':
                            proposal=proposals.pop(event['call_id'],None)
                            if proposal is not None:
                                cancelled_proposals.add(proposal);proposal.cancel()
                                await asyncio.gather(proposal,return_exceptions=True)
                            await send(event);continue
                        if kind in ('voice_activity','input_transcript'):
                            original=acoustic.provider.ident if acoustic.provider else None
                            owned=await acoustic.provider_event(event)
                            if owned is not None:original=owned
                            event={**event,'id':original}
                            # Explicit transcription fragments are rendered as
                            # the acoustic owner's accumulated caption; an empty
                            # final marker must not erase that complete text.
                            if kind=='input_transcript' and 'finished' in event:continue
                        if kind in ('audio','output_transcript'):
                            if utterance is None:utterance=str(uuid.uuid4())
                            if kind=='audio':
                                output_bytes+=len(event['pcm']);output_hash.update(event['pcm'])
                                await flush_output(emit=False)
                                await send({'type':'audio','id':utterance,'end':output_bytes,
                                    'pcm':base64.b64encode(event['pcm']).decode(),'sample_rate':24000})
                                continue
                            output_text+=event['text']
                            if len(output_text.encode())>16384:raise ForegroundUnavailable('Assistant utterance exceeds its live bound')
                            # Update the same app-owned assistant record, not human or native input.
                            await flush_output()
                        elif kind=='interrupted':
                            await send(event);await flush_output(interrupted=True,closed=True)
                        elif kind=='turn_complete':
                            await flush_output(closed=True);await send(event)
                        elif kind=='closing':
                            await send(event);return
                        elif kind!='ready':await send(event)
                    await notice_if_idle()
            finally:await queued.close()
        async def analysis():
            queued=VoiceInbox(worker.receive,batch_size=50)
            try:
                while True:
                    events=await queued.batch()
                    await actor()
                    for event in events:
                        if event['type']=='activity':
                            await acoustic.activity(event)
                            await send({'type':'turn_activity','activity':event})
                        elif event['type']!='boundary':raise DetectionUnavailable('Unexpected acoustic event')
            finally:await queued.close()
        async def returns(cursor):
            # Watch first, then catch up from the pre-open cursor. Never replay
            # historical speech or submit work to recover an observation.
            start=dict(cursor);last_question_scope=None
            async for changed in changes([Path(provider.receiver['db_path'])]):
                await actor()
                if not changed:continue
                await notice_if_idle()
                # A source can acquire currentness/publication metadata without
                # a new row ID. Re-read this session's bounded window instead
                # of advancing permanently past an as-yet-unoffered source.
                # The bridge deduplicates exact offered/queued revisions.
                # The canonical For you reader already excludes unrelated
                # direct-session questions. Offer its full current question,
                # not just a later integrating summary saying a choice is due.
                question_cursor=0;question_scope={};question_sources=[]
                for _ in range(8):
                    page=await bridge._owner(provider.conversation_requests,question_cursor)
                    if page['binding']!=meta['binding']:raise ForegroundUnavailable('Integrating conversation changed')
                    for item in page['items']:
                        if (item.get('kind')=='question' and item.get('state')=='pending' and item.get('actionable') is True
                                and len(question_scope)<32):
                            question_scope[item['id']]=item['capture_version']
                            question_sources.append({'id':'request:'+item['id'],'revision':item['revision'],
                                'kind':'question','label':str(item.get('label') or 'Conversation')[:200]})
                    if not page['more']:break
                    question_cursor=page['cursor']
                else:raise ForegroundUnavailable('Canonical questions exceed the live catch-up bound')
                Provider.check_capture_questions(question_scope)
                if question_scope!=last_question_scope:
                    # Availability reaches the capture client before model
                    # speech. It is not a hearing receipt or answer authority.
                    await send({'type':'question_scope','binding':meta['binding'],'capture_questions':question_scope})
                    last_question_scope=dict(question_scope)
                for source in question_sources:bridge.integrating_source(source)
                cursor=dict(start)
                for _ in range(8):
                    value=await bridge._owner(provider.presentation_list,cursor['delivery'],cursor['native'],'after')
                    if value['binding']!=meta['binding']:raise ForegroundUnavailable('Integrating conversation changed')
                    for item in value['items']:
                        # Reported worker results/questions can be presented as
                        # integrating commentary with an empty final answer.
                        # Ordinary progress is not an integrating return.
                        returning=(item.get('kind')=='integrator_answer' or
                            item.get('kind')=='integrator_progress' and bool(item.get('native_returns')))
                        if (returning and item.get('current') is not False
                                and item.get('correction_pending') is not True and item.get('native_binding_current') is not False):
                            bridge.integrating_source({'id':item['id'],'revision':item['revision'],
                                'kind':'question' if any(x.startswith('question:') for x in item.get('native_returns',[])) else 'result',
                                'label':str(item.get('label') or 'Integrator')[:200]})
                    cursor=value['cursor']
                    if not value['more']:break
                else:raise ForegroundUnavailable('Integrating returns exceed the live catch-up bound')
                await notice_if_idle()
        try:
            async with asyncio.timeout(305):
                raw=await asyncio.wait_for(socket.receive_text(),5)
                if len(raw.encode())>8192:raise ValueError('Native voice metadata exceeds bound')
                meta=json.loads(raw)
                if (not isinstance(meta,dict) or set(meta)-{'id','binding','csrf','authorization','capture_questions'}
                        or not all(isinstance(meta.get(k),str) for k in ('id','binding','csrf'))
                        or not re.fullmatch('[a-f0-9]{64}',meta['binding'])):
                    raise ValueError('Select one owned native voice conversation')
                provider.input_id(meta['id']);Provider.check_capture_questions(meta.get('capture_questions'))
                session,recheck,actor=await bind_voice(socket,meta)
                human=session['human']
                if human in active or len(active)>=2:raise ForegroundUnavailable('Native voice capacity occupied')
                owner=human;active.add(owner)
                # All preflight happens before provider opening and browser microphone acquisition.
                capabilities=await asyncio.to_thread(provider.presentation,'input voice capabilities')
                if (capabilities.get('binding')!=meta['binding'] or capabilities.get('foreground_retention')!='v1'
                        or capabilities.get('foreground_completed_reader') is not True
                        or capabilities.get('foreground_context')!='v1'
                        or capabilities.get('foreground_guidance')!='v1'):
                    raise ForegroundUnavailable('Selected listener does not support native foreground originals')
                await asyncio.to_thread(app.state.native_history.capacity)
                initial=await asyncio.to_thread(provider.presentation_list,0,0,'before')
                if initial['binding']!=meta['binding']:raise ForegroundUnavailable('Integrating conversation changed')
                cursor=initial['newest']
                # Reuse owned conversation sources for continuity, never as a
                # fabricated human turn or authorization to replay prior work.
                sources=[]
                def excerpt(text):return str(text).encode()[:1200].decode('utf-8','ignore')
                for item in initial['items']:
                    if item.get('kind') not in ('integrator_answer','integrator_progress') or item.get('current') is False:continue
                    try:
                        part=await asyncio.to_thread(provider.presentation_part,item['id'],item['revision'],0)
                    except (ProviderUnavailable,ValueError):continue
                    if (part.get('current') is False or part.get('correction_pending') is True
                            or part.get('native_binding_current') is False):continue
                    text=excerpt(part['text'])
                    readable=(part.get('kind')=='integrator_answer' or
                        part.get('kind')=='integrator_progress' and bool(part.get('native_returns')))
                    sources.append({'id':item['id'],'revision':item['revision'],'speaker':'integrator',
                        'text_excerpt':text,'kind':item['kind'],'observed_at':item.get('observed_at'),'current':part.get('current'),
                        'correction_pending':part.get('correction_pending'),'bounded':True,'can_delegate':False,
                        'can_read':readable,'offset':0,
                        'next_offset':len(text) if readable and (len(text)<len(part['text']) or part.get('next_offset') is not None) else None})
                originals=await asyncio.to_thread(provider.presentation,'input list 0 before')
                if originals['binding']!=meta['binding']:raise ForegroundUnavailable('Original context binding changed')
                for item in originals.get('items',[]):
                    sources.append({'id':item['id'],'speaker':'retained_original','origin_kind':item.get('origin_kind'),'source_data':True,'phase':item['phase'],'capture_order':item.get('capture_order'),'received_at':item.get('received_at'),
                        'text_excerpt':excerpt(item.get('preview','')),'bounded':True,'can_delegate':False})
                history=await asyncio.to_thread(app.state.native_history.page,owner,binding=meta['binding'])
                for item in history['items'][:4]:
                    sources.append({'id':item['id'],'speaker':'assistant_foreground','observed_at':item['observed_at'],
                        'text_excerpt':excerpt(item['text']),'interrupted':item['interrupted'],
                        'played_bytes':item['played_bytes'],'generated_bytes':item['generated_bytes'],'playback_meaning':item['playback_meaning'],
                        'bounded':True,'can_delegate':False})
                context={'display_name':config.get('daimon_name','Daimon'),'sources':sources,'source_data':True}
                identity=await asyncio.to_thread(being_identity,selected)
                if identity is not None:context['being_identity']=identity
                while len(json.dumps(context,ensure_ascii=False).encode())>32768:sources.pop()
                await recheck()
                if activity_mode=='manual':
                    worker=await Detector.open(detector_command,continuous=True,silence_end_millis=1600)
                await recheck()
                opening=asyncio.create_task(asyncio.to_thread(NativeDialogue,selected['credential_file'],activity_mode=activity_mode,context=context))
                stream=await asyncio.shield(opening)
                # Provider readiness is actual setupComplete, not successful connect().
                while True:
                    events=await asyncio.to_thread(stream.receive)
                    if any(e['type']=='ready' for e in events):break
                    if time.monotonic()-started>15:raise ForegroundUnavailable('Native speech readiness timed out')
                await recheck()
                def speech_context():
                    history=app.state.native_history.page(owner,binding=meta['binding'],dialogue=meta['id'])
                    return [{'id':item['id'],'speaker':'assistant_foreground',
                        'text_excerpt':item['text'][:200],'text_bounded':len(item['text'])>200,
                        'interrupted':item['interrupted'],'closed':item['closed'],
                        'played_bytes':item['played_bytes'],'generated_bytes':item['generated_bytes'],
                        'meaning':item['playback_meaning']} for item in history['items'][:4]]
                bridge=ForegroundBridge(provider,stream,selected['cache_root'],meta['id'],meta['binding'],recheck,
                    speech_context=speech_context)
                async def context_owner(function,*args):
                    # The same bounded owner slots remain held until actual
                    # control completion, including final cleanup after audio
                    # ownership has closed. No extra unbounded thread pool.
                    await actor()
                    return await bridge._run(bridge._owners,function,*args)
                context_producer=NativeContext(app.state.native_history,provider,owner,meta['id'],meta['binding'],context_owner)
                await context_producer.open()
                # Only references actually retained in the bounded setup are
                # offered. No replay, unsolicited speech or wider source lookup.
                for item in sources:
                    if item.get('speaker')=='integrator' and item.get('can_read') is True:
                        bridge.integrating_source({'id':item['id'],'revision':item['revision'],
                            'kind':'result','label':'Integrator'},in_context=True)
                acoustic=(NativeAcousticSession(bridge,worker,meta.get('capture_questions'),acoustic_event)
                    if activity_mode=='manual' else NativeAutomaticAcousticSession(bridge,meta.get('capture_questions'),acoustic_event))
                await send({'type':'ready','id':meta['id'],'model':stream.model,'activity_mode':activity_mode,'playback_status':True})
                tasks={asyncio.create_task(outputs(),name='native-output'),asyncio.create_task(returns(cursor),name='native-returns'),asyncio.create_task(acoustic.watch_transcripts(),name='native-transcripts')}
                context_task=asyncio.create_task(context_producer.run(),name='native-context')
                context_task.add_done_callback(ForegroundBridge._observe)
                tasks.add(context_task)
                if worker:tasks.add(asyncio.create_task(analysis(),name='native-analysis'))
                inbox=VoiceInbox(socket.receive,pcm=True,batch_size=50,control_bytes=8192,batch_control_frames=True,wait_for_space=True)
                checked=time.monotonic()
                while True:
                    if incoming is None:incoming=asyncio.create_task(inbox.batch())
                    done,_=await asyncio.wait({incoming,*tasks,*tool_tasks},return_when=asyncio.FIRST_COMPLETED)
                    for task in done-{incoming}:
                        if task in cancelled_proposals:
                            cancelled_proposals.discard(task);tool_tasks.discard(task);continue
                        close_stage=task.get_name();task.result()
                        if task in tasks:
                            close_stage+='-ended';return
                        tool_tasks.remove(task)
                        proposals={key:value for key,value in proposals.items() if value is not task}
                    if incoming not in done:continue
                    close_stage='client-input';batch=await incoming;incoming=None
                    if batch[0]['type']=='websocket.disconnect':
                        close_stage='client-disconnect';break
                    await actor()
                    if time.monotonic()-checked>=15:
                        await recheck();checked=time.monotonic()
                    for message in batch:
                        if message.get('bytes') is not None:await acoustic.feed(message['bytes'])
                        else:
                            value=json.loads(message.get('text',''))
                            if value=={'type':'close'}:
                                close_stage='client-close';return
                            if isinstance(value,dict) and value.get('type')=='playback_status':
                                observed=playback_status(value)
                                if playback_status_count<32:
                                    playback_status_count+=1
                                    if first_playback_status is None and observed['handled']:first_playback_status=observed
                                    last_playback_status=observed
                                continue
                            if isinstance(value,dict) and set(value)=={'type','audio_bytes','capture_questions'} and value['type']=='capture_scope':
                                await acoustic.marker(value['audio_bytes'],value['capture_questions']);continue
                            if (not isinstance(value,dict) or set(value)!={'type','id','played_bytes'}
                                    or value['type']!='playback'):raise ValueError('Unsupported native voice control')
                            await asyncio.to_thread(app.state.native_history.played,owner,meta['id'],value['id'],value['played_bytes'])
                            await notice_if_idle()
        except (HTTPException,ValueError,TimeoutError,OSError,ProviderUnavailable,ForegroundUnavailable,DialogueUnavailable,DetectionUnavailable,WebSocketDisconnect) as error:
            close_error=type(error).__name__;close_site=failure_site(error)
            with suppress(Exception):await send({'type':'review','message':'Voice ended. Your retained recordings and integrating work remain available; review before sending anything again.'})
        except BaseException as error:
            close_error=type(error).__name__;close_site=failure_site(error);raise
        finally:
            stopping=True
            if stream:
                with suppress(Exception):stream.close()
            async def cleanup():
                if incoming is not None:
                    incoming.cancel()
                    with suppress(asyncio.CancelledError,Exception):await incoming
                if inbox:await inbox.close()
                audio_tasks={task for task in tasks if task.get_name()!='native-context'}
                for task in audio_tasks:task.cancel()
                for task in audio_tasks:
                    with suppress(asyncio.CancelledError,Exception):await task
                if acoustic:
                    with suppress(Exception):await acoustic.close()
                if bridge:
                    with suppress(Exception):await bridge.close()
                for task in list(tool_tasks):task.cancel()
                for task in list(tool_tasks):
                    with suppress(asyncio.CancelledError,Exception):await task
                with suppress(Exception):await flush_output(interrupted=True,closed=True)
                if context_producer is not None:
                    with suppress(Exception):await context_producer.close()
                if worker:await worker.close()
                if stream is None and opening:
                    def late(task):
                        if not task.cancelled():
                            with suppress(Exception):task.result().close()
                        if owner is not None:active.discard(owner)
                    opening.add_done_callback(late)
                if owner is not None and (opening is None or opening.done()):active.discard(owner)
                with suppress(Exception):await socket.close()
            def observe_close(task):
                if owner is None:return
                # Existing bounded service journal only. No exception detail,
                # transcript, provider payload, identity/header or raw audio.
                summary={'id':meta['id'],'stage':close_stage,'error_type':close_error,'failure_site':close_site,
                    'provider_failure_code':getattr(stream,'failure_code',None),
                    'first_send_failure':first_send_failure,
                    'client_playback':{'source':'untrusted_client_observation','count':playback_status_count,
                        'first':first_playback_status,'last':last_playback_status},
                    'boundary_mismatch':acoustic.boundary_mismatch if acoustic else None,
                    'context_producer':context_producer.status if context_producer is not None else 'not_started',
                    'elapsed_ms':round((time.monotonic()-started)*1000),
                    'received_pcm_bytes':inbox.received_bytes if inbox else 0,
                    'received_messages':inbox.received_messages if inbox else 0,
                    'peak_pending_messages':inbox.peak_messages if inbox else 0,
                    'peak_pending_pcm_bytes':inbox.peak_bytes if inbox else 0,
                    'generated_pcm_bytes':getattr(stream,'output_bytes',0) if stream else 0,
                    'cleanup':'cancelled' if task.cancelled() else 'failed' if task.exception() is not None else 'completed'}
                logging.getLogger('uvicorn.error').info('native_voice_closed %s',json.dumps(summary,separators=(',',':')))
            cleanup_task=asyncio.create_task(cleanup())
            cleanup_task.add_done_callback(ForegroundBridge._observe)
            cleanup_task.add_done_callback(observe_close)
            await asyncio.shield(cleanup_task)
