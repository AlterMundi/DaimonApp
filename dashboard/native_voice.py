"""Explicit authenticated native-audio foreground; existing owners retain work."""
import asyncio
import base64
from collections import deque
from contextlib import suppress
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

from fastapi import HTTPException, WebSocket
from starlette.websockets import WebSocketDisconnect

from .live import changes
from .live_transcription import VoiceInbox
from .native_acoustic import NativeAcousticSession
from .native_dialogue import NativeDialogue, DialogueUnavailable
from .native_foreground import ForegroundBridge, ForegroundUnavailable
from .provider import Provider, ProviderUnavailable
from .turn_detection import Detector, DetectionUnavailable


def install(app,config,provider,origins,bind_voice,detector_command,active):
    selected=config['streaming_transcription']
    app.state.native_voice_enabled=True

    @app.websocket('/api/interaction/voice/native')
    async def native_voice(socket:WebSocket):
        if socket.headers.get('origin') not in origins:
            await socket.close(code=1008);return
        await socket.accept()
        owner=None;bridge=acoustic=worker=stream=inbox=opening=incoming=None
        tasks=set();tool_tasks=set();proposals={};cancelled_proposals=set();raw_notifications={};sending=asyncio.Lock();stopping=False
        utterance=None;output_text='';output_bytes=0;output_hash=hashlib.sha256()
        started=time.monotonic()
        async def send(value):
            async with sending:
                await asyncio.wait_for(socket.send_json(value),3)
        async def flush_output(*,interrupted=False,closed=False,emit=True):
            nonlocal utterance,output_text,output_bytes,output_hash
            if utterance is None:return
            record=await asyncio.to_thread(app.state.native_history.retain,owner,meta['id'],meta['binding'],
                utterance,output_text,output_hash.hexdigest(),output_bytes,interrupted=interrupted,closed=closed)
            if not stopping and emit:await send({'type':'assistant_utterance','utterance':record})
            if closed:
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
                launch(completed())
        def launch(operation):
            task=asyncio.create_task(operation);tool_tasks.add(task)
            return task
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
                        if kind in ('source_query','integrating_source_query','delegation_proposed','integrator_watch'):
                            proposals[event['call_id']]=launch(bridge.tool(event));continue
                        if kind=='proposal_cancelled':
                            pending=proposals.pop(event['call_id'],None)
                            if pending is not None:
                                cancelled_proposals.add(pending);pending.cancel()
                                await asyncio.gather(pending,return_exceptions=True)
                            await send(event);continue
                        if kind in ('voice_activity','input_transcript'):
                            original=acoustic.provider.ident if acoustic.provider else None
                            await acoustic.provider_event(event)
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
            start=dict(cursor)
            async for changed in changes([Path(provider.receiver['db_path'])]):
                await actor()
                if not changed:continue
                # A source can acquire currentness/publication metadata without
                # a new row ID. Re-read this session's bounded window instead
                # of advancing permanently past an as-yet-unoffered source.
                # The bridge deduplicates exact offered/queued revisions.
                # The canonical For you reader already excludes unrelated
                # direct-session questions. Offer its full current question,
                # not just a later integrating summary saying a choice is due.
                question_cursor=0
                for _ in range(8):
                    page=await bridge._owner(provider.conversation_requests,question_cursor)
                    if page['binding']!=meta['binding']:raise ForegroundUnavailable('Integrating conversation changed')
                    for item in page['items']:
                        if item.get('kind')=='question' and item.get('state')=='pending' and item.get('actionable') is True:
                            bridge.integrating_source({'id':'request:'+item['id'],'revision':item['revision'],
                                'kind':'question','label':str(item.get('label') or 'Conversation')[:200]})
                    if not page['more']:break
                    question_cursor=page['cursor']
                else:raise ForegroundUnavailable('Canonical questions exceed the live catch-up bound')
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
                        or capabilities.get('foreground_completed_reader') is not True):
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
                    sources.append({'id':item['id'],'revision':item['revision'],'speaker':'integrator',
                        'text_excerpt':excerpt(part['text']),'kind':item['kind'],'observed_at':item.get('observed_at'),'current':part.get('current'),
                        'correction_pending':part.get('correction_pending'),'bounded':True,'can_delegate':False})
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
                while len(json.dumps(context,ensure_ascii=False).encode())>32768:sources.pop()
                await recheck()
                worker=await Detector.open(detector_command,continuous=True,silence_end_millis=1600)
                await recheck()
                opening=asyncio.create_task(asyncio.to_thread(NativeDialogue,selected['credential_file'],activity_mode='manual',context=context))
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
                acoustic=NativeAcousticSession(bridge,worker,meta.get('capture_questions'),acoustic_event)
                await send({'type':'ready','id':meta['id'],'model':stream.model,'activity_mode':'manual'})
                tasks={asyncio.create_task(outputs()),asyncio.create_task(analysis()),asyncio.create_task(returns(cursor)),asyncio.create_task(acoustic.watch_transcripts())}
                inbox=VoiceInbox(socket.receive,pcm=True,batch_size=50,control_bytes=8192)
                checked=time.monotonic()
                while True:
                    if incoming is None:incoming=asyncio.create_task(inbox.batch())
                    done,_=await asyncio.wait({incoming,*tasks,*tool_tasks},return_when=asyncio.FIRST_COMPLETED)
                    for task in done-{incoming}:
                        if task in cancelled_proposals:
                            cancelled_proposals.discard(task);tool_tasks.discard(task);continue
                        task.result()
                        if task in tasks:return
                        tool_tasks.remove(task)
                        proposals={key:value for key,value in proposals.items() if value is not task}
                    if incoming not in done:continue
                    batch=await incoming;incoming=None
                    if batch[0]['type']=='websocket.disconnect':break
                    await actor()
                    if time.monotonic()-checked>=15:
                        await recheck();checked=time.monotonic()
                    for message in batch:
                        if message.get('bytes') is not None:await acoustic.feed(message['bytes'])
                        else:
                            value=json.loads(message.get('text',''))
                            if value=={'type':'close'}:return
                            if isinstance(value,dict) and set(value)=={'type','audio_bytes','capture_questions'} and value['type']=='capture_scope':
                                await acoustic.marker(value['audio_bytes'],value['capture_questions']);continue
                            if (not isinstance(value,dict) or set(value)!={'type','id','played_bytes'}
                                    or value['type']!='playback'):raise ValueError('Unsupported native voice control')
                            await asyncio.to_thread(app.state.native_history.played,owner,meta['id'],value['id'],value['played_bytes'])
        except (HTTPException,ValueError,TimeoutError,OSError,ProviderUnavailable,ForegroundUnavailable,DialogueUnavailable,DetectionUnavailable,WebSocketDisconnect):
            with suppress(Exception):await send({'type':'review','message':'Voice ended. Your retained recordings and integrating work remain available; review before sending anything again.'})
        finally:
            stopping=True
            if stream:
                with suppress(Exception):stream.close()
            async def cleanup():
                if incoming is not None:
                    incoming.cancel()
                    with suppress(asyncio.CancelledError,Exception):await incoming
                if inbox:await inbox.close()
                for task in tasks:task.cancel()
                for task in tasks:
                    with suppress(asyncio.CancelledError,Exception):await task
                if acoustic:
                    with suppress(Exception):await acoustic.close()
                if bridge:
                    with suppress(Exception):await bridge.close()
                for task in list(tool_tasks):task.cancel()
                for task in list(tool_tasks):
                    with suppress(asyncio.CancelledError,Exception):await task
                with suppress(Exception):await flush_output(interrupted=True,closed=True)
                if worker:await worker.close()
                if stream is None and opening:
                    def late(task):
                        if not task.cancelled():
                            with suppress(Exception):task.result().close()
                        if owner is not None:active.discard(owner)
                    opening.add_done_callback(late)
                if owner is not None and (opening is None or opening.done()):active.discard(owner)
                with suppress(Exception):await socket.close()
            cleanup_task=asyncio.create_task(cleanup())
            cleanup_task.add_done_callback(ForegroundBridge._observe)
            await asyncio.shield(cleanup_task)
