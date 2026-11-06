"""Optional public GPT-Live WebRTC admission and trusted sideband.

Public project access is independent of Codex login/voice entitlement. Browser
messages never authorize tools or supply trusted transcripts, instructions or
provider commands. The current native/provider modes and their work stay intact.
"""
import asyncio
from anyio import CancelScope
from contextlib import suppress
import json
from pathlib import Path
import re
import secrets
import threading

from fastapi import HTTPException, Request, WebSocket
from starlette.websockets import WebSocketDisconnect

from .codex_voice import AvatarVoiceLease, CodexVoiceUnavailable
from .live_transcription import bind_voice_actor
from .openai_live import OpenAILive, LiveUnavailable, session_spec
from .openai_live_visits import LiveCreations
from .openai_live_context import TOOL, NAME, serve_context
from .openai_live_originals import enroll_original
from .openai_live_seals import request_seal, accept_seal
from .openai_live_native_backend import prepare_native, return_one_native_part
from .provider import ProviderUnavailable
from scripts.speech_render import private_bytes, RenderError


def install(app, config, provider, authorize, origins):
    selected = config.get('openai_live', {})
    if selected.get('enabled') is not True:return False
    backend_mode=selected.get('backend_mode','responses')
    if backend_mode not in ('responses','native'):raise ValueError('Select an explicit public Live backend')
    native_backend=backend_mode=='native'
    if (set(selected)-{'enabled','api_key_file','identity_file','backend_instructions_file',
            'backend_model','backend_tools','session_options','backend_options',
            'delegation_options','session_seconds','resume_mode','conversation_context','native_originals','source_seals','backend_mode'}
            or any(not isinstance(selected.get(key),str) or not Path(selected[key]).is_absolute()
                   for key in (('api_key_file','identity_file') if native_backend else ('api_key_file','identity_file','backend_instructions_file')))
            or type(selected.get('session_seconds',600)) is not int
            or not 300 <= selected.get('session_seconds',600) <= 600):
        raise ValueError('Select owner-configured public GPT-Live and bounded capture')
    instructions=private_bytes(selected['identity_file'],8192).decode()
    backend=None if native_backend else private_bytes(selected['backend_instructions_file'],8192).decode()
    context=selected.get('conversation_context',False)
    if type(context) is not bool:raise ValueError('Select owner conversation-context access')
    native_originals=selected.get('native_originals',False)
    if type(native_originals) is not bool:raise ValueError('Select explicit native original retention')
    source_seals=selected.get('source_seals',native_backend)
    if type(source_seals) is not bool or source_seals and native_originals:
        raise ValueError('Select explicit source sealing before native enrollment, never both upload paths')
    tools=[] if native_backend else list(selected.get('backend_tools',()))
    if any(isinstance(tool,dict) and tool.get('name')==NAME for tool in tools):
        raise ValueError('Conversation reader name belongs to the owning adapter')
    if native_backend and (context or not source_seals):
        raise ValueError('Native backend requires source seals and uses native context, not Responses tools')
    if context:tools.append(TOOL)
    options={'session_options':selected.get('session_options'),'delegation_options':selected.get('delegation_options')}
    spec=(session_spec(instructions,client_delegation=True,**options) if native_backend else
        session_spec(instructions, backend_model=selected.get('backend_model'),
            backend_instructions=backend, backend_tools=tools,backend_options=selected.get('backend_options'),**options))
    if 'format' in spec.get('audio',{}):raise ValueError('WebRTC negotiates its audio format')
    resume=selected.get('resume_mode','fresh')
    if resume not in ('fresh','stored_fork') or resume=='stored_fork' and spec.get('store') is not True:
        raise ValueError('Stored continuation requires explicit storage configuration')
    if native_backend and resume!='fresh':
        raise ValueError('Native client renewal needs its sourced continuation integration; no silent mode fallback')
    seconds=selected.get('session_seconds',600)
    history=LiveCreations(Path(config['state_dir'])/'public-live-visits')
    uploads=asyncio.Semaphore(2)

    async def http_owner(request, *, write=False):
        session=await authorize(request)
        if dict(session).get('scope')=='monitor_readonly':raise HTTPException(403,'Voice interaction access required')
        if write and (request.headers.get('origin') not in origins or not secrets.compare_digest(
                request.headers.get('x-dashboard-csrf',''),session['csrf'])):
            raise HTTPException(403,'Fresh voice action token required')
        binding=request.headers.get('x-voice-binding','')
        value=await asyncio.to_thread(provider.presentation,'input list 9223372036854775807 after')
        if not re.fullmatch('[a-f0-9]{64}',binding) or value.get('binding')!=binding:
            raise HTTPException(409,'Voice conversation binding changed')
        return session,binding

    @app.get('/api/interaction/voice/gpt-live/visits')
    async def visits(request:Request,before:str|None=None):
        session,binding=await http_owner(request)
        try:return await asyncio.to_thread(history.visits,session['human'],binding,before=before)
        except (OSError,ValueError,RenderError):raise HTTPException(409,'Voice history page unavailable') from None

    @app.get('/api/interaction/voice/gpt-live/visits/{visit}')
    async def status(visit:str,request:Request):
        session,binding=await http_owner(request)
        try:
            value=await asyncio.to_thread(history.owned,visit,session['human'],binding)
            # SDP/owner internals are unnecessary for a recovery/status read.
            return {key:value[key] for key in ('id','state','recordings','delegations','finalization','latest_usage') if key in value}
        except (OSError,ValueError,RenderError):raise HTTPException(404,'Voice visit unavailable') from None

    @app.get('/api/interaction/voice/gpt-live/visits/{visit}/events')
    async def sources(visit:str,request:Request,after:int=0,revision:str|None=None):
        session,binding=await http_owner(request)
        try:return await asyncio.to_thread(history.source_page,visit,session['human'],binding,after=after,revision=revision)
        except (OSError,ValueError,RenderError):raise HTTPException(409,'Voice source page unavailable') from None

    @app.post('/api/interaction/voice/gpt-live/visits/{visit}/recordings/{ordinal}')
    async def original(visit:str,ordinal:int,request:Request):
        session,binding=await http_owner(request,write=True)
        capture_stop=request.headers.get('x-voice-capture-stop')
        if capture_stop not in (None,'interrupted_prefix'):raise HTTPException(400,'Unknown recording provenance')
        if not 0<=ordinal<32:raise HTTPException(400,'Recording index exceeds bound')
        if uploads.locked():raise HTTPException(429,'Two voice originals are being retained')
        try:
            async with uploads:
                await asyncio.to_thread(history.owned,visit,session['human'],binding)
                data=bytearray()
                async with asyncio.timeout(30):
                    async for part in request.stream():
                        if len(data)+len(part)>120*32000+44:raise HTTPException(413,'Voice original exceeds bound')
                        data.extend(part)
                fresh,current=await http_owner(request,write=True)
                if fresh['human']!=session['human'] or current!=binding:raise HTTPException(403,'Voice audience changed')
                receipt=await asyncio.to_thread(history.recording,visit,session['human'],binding,ordinal,bytes(data),provider,capture_stop=capture_stop)
                result={'visit':visit,'binding':binding,'recording':receipt}
                if native_originals:
                    owner=await asyncio.to_thread(provider.public_live_binding,binding)
                    result['native_original']=await asyncio.to_thread(enroll_original,history,visit,session['human'],owner,ordinal,provider)
                return result
        except (OSError,ValueError,RenderError,ProviderUnavailable):
            raise HTTPException(409,'Original not confirmed; keep the same local audio') from None

    @app.websocket('/api/interaction/voice/gpt-live')
    async def live(socket:WebSocket):
        if socket.headers.get('origin') not in origins:
            await socket.close(code=1008);return
        await socket.accept()
        lease=sideband=creating=read_browser=read_provider=preparing=returning=None
        result_index=0
        preparation_stopped=threading.Event()
        visit=human=binding=None;admitted=False;closing=False;close_deadline=None;native_failure=False
        async def message(limit):
            raw=await socket.receive_text()
            if len(raw.encode())>limit:raise ValueError('Public voice control exceeds bound')
            value=json.loads(raw)
            if not isinstance(value,dict):raise ValueError('Select one public voice action')
            return value
        async def send(value):
            await recheck()
            await asyncio.wait_for(socket.send_json(value),3)
        async def current_owner():
            if await asyncio.to_thread(provider.public_live_binding,binding)!=owner:
                raise ValueError('Public voice owner changed')
        async def begin_close():
            nonlocal closing,close_deadline
            if closing:return
            preparation_stopped.set()
            closing=True;close_deadline=asyncio.get_running_loop().time()+30
            await asyncio.to_thread(history.end_capture,visit,human,binding)
            await send({'type':'finishing','id':visit,**({'message':
                'Finishing voice; this native request needs review. Originals are kept.'} if native_failure else {})})
        try:
            async with asyncio.timeout(seconds+60):
                meta=await asyncio.wait_for(message(8192),5)
                if set(meta)-{'id','binding','csrf','authorization'} or not all(isinstance(meta.get(k),str) for k in ('id','binding','csrf')):
                    raise ValueError('Select one public voice admission')
                visit=history._ident(meta['id']);binding=meta['binding']
                session,recheck,actor=await bind_voice_actor(provider,authorize,socket,meta,require_voice=False)
                if dict(session).get('scope')=='monitor_readonly':raise HTTPException(403,'Voice interaction access required')
                human=session['human'];owner=await asyncio.to_thread(provider.public_live_binding,binding)
                if native_backend:
                    caps=await asyncio.to_thread(provider.presentation,'input voice capabilities')
                    if caps.get('binding')!=binding or caps.get('foreground_interpretation')!='gpt-transcribe/v1':
                        raise LiveUnavailable('native_reader_unavailable')
                lease=AvatarVoiceLease(app.state.voice_active,human,binding,owner['native_thread'])
                client=OpenAILive(selected['api_key_file'])
                # Validate this explicitly configured project file before mic
                # permission; never discover or reinterpret Codex credentials.
                await asyncio.to_thread(client._project_key)
                admission=await asyncio.to_thread(history.prepare,visit,human,owner,seconds,resume_spec=spec if resume=='stored_fork' else None)
                admitted=True
                await send({'type':'prepared','id':visit,'binding':binding,'admission':admission,
                    'mode':'public_live_native_comparison' if native_backend else 'public_live_responses_comparison',
                    'source_coverage':'sideband_before_media_answer'})
                offer=await asyncio.wait_for(message(66000),min(seconds,300))
                if set(offer)!={'type','sdp'} or offer['type']!='offer':raise ValueError('Select one WebRTC offer')
                await recheck();await current_owner()
                creating=asyncio.create_task(asyncio.to_thread(history.create,visit,human,owner,offer['sdp'],spec,client))
                call=await asyncio.shield(creating)
                await recheck();await current_owner()
                sideband=await asyncio.to_thread(client.attach,call)
                # Install trusted receive before the browser can apply the SDP
                # answer and enable media. Sideband still has no pre-attach replay.
                read_provider=asyncio.create_task(asyncio.to_thread(sideband.receive))
                await send({'type':'answer','id':visit,'session':call.session_id,'sdp':call.sdp})
                read_browser=asyncio.create_task(message(1024))
                while True:
                    done,_=await asyncio.wait((read_provider,read_browser),timeout=.5,return_when=asyncio.FIRST_COMPLETED)
                    await recheck();await current_owner()
                    # Consume source events first when a close races a queued
                    # delegation. A browser assertion cannot complete backend work.
                    if read_provider in done:
                        event=read_provider.result()
                        if event is not None:
                            if event['type']=='session.closed':
                                result=await asyncio.to_thread(history.observe_closed,visit,human,owner,event)
                                await send({'type':'closed','id':visit,'finalization':result['finalization'],
                                    **({'message':'Voice ended. This native request needs review; originals and work receipts are kept.'}
                                       if native_failure else {})})
                                break
                            if await asyncio.to_thread(history.event,visit,human,owner,event):
                                await send({'type':'provider_event','event':event})
                            if (context and event['type']=='response.event'
                                    and event.get('event',{}).get('type')=='response.completed'):
                                # Only completed trusted function items can select a
                                # read. Provider data never grants work execution.
                                await asyncio.to_thread(serve_context,history,visit,human,
                                    owner,provider,sideband,event.get('delegation_id'))
                        read_provider=asyncio.create_task(asyncio.to_thread(sideband.receive))
                    if read_browser in done:
                        action=read_browser.result()
                        if source_seals and action.get('type')=='source_sealed' and not closing:
                            receipt=await asyncio.to_thread(accept_seal,history,visit,human,owner,action,provider)
                            await send({'type':'source_seal_recorded','visit':visit,'seal':receipt})
                        else:
                            if action!={'type':'close'}:raise ValueError('Select a matching source acknowledgment or an explicit close')
                            await begin_close()  # A duplicate close observes the same intent.
                        read_browser=asyncio.create_task(message(1024))
                    if returning is not None and returning.done():
                        completed=returning;returning=None
                        try:completed.result()
                        except (OSError,ValueError,RenderError,ProviderUnavailable,LiveUnavailable):
                            if not closing:native_failure=True;await begin_close()
                    if preparing is not None and preparing.done():
                        completed=preparing;preparing=None
                        try:outcome=completed.result()
                        except (OSError,ValueError,RenderError,ProviderUnavailable,LiveUnavailable):
                            if not closing:native_failure=True;await begin_close()
                        else:
                            if outcome['state']!='admitted' and not closing:
                                native_failure=True;await begin_close()
                    if not closing:
                        value=await asyncio.to_thread(history.read,visit,human,owner)
                        try:history.check_capture(value)
                        except ValueError:
                            await begin_close()
                        else:
                            if source_seals and not any(row.get('source_seal',{}).get('state')=='requested'
                                    for row in value['delegations'].values()):
                                pending=next((key for key,row in value['delegations'].items()
                                    if row.get('target')=='client' and 'source_seal' not in row),None)
                                if pending is not None:
                                    command=await asyncio.to_thread(request_seal,history,visit,human,owner,pending,provider)
                                    if command is not None:await send(command)
                            if native_backend and preparing is None:
                                pending=next((key for key,row in value['delegations'].items()
                                    if row.get('source_seal',{}).get('state') in ('sealed','empty') and 'native_pipeline' not in row),None)
                                if pending is not None:
                                    preparing=asyncio.create_task(asyncio.to_thread(prepare_native,
                                        history,visit,human,owner,pending,provider,selected['api_key_file'],
                                        stopped=preparation_stopped))
                            if native_backend and returning is None:
                                ready=[key for key,row in value['delegations'].items()
                                    if row.get('native_work',{}).get('state')=='observed']
                                if ready:
                                    result_index%=len(ready)
                                    returning=asyncio.create_task(asyncio.to_thread(return_one_native_part,history,visit,human,owner,
                                        ready[result_index],provider,sideband,stopped=preparation_stopped))
                                    result_index+=1
                    if closing:
                        command=await asyncio.to_thread(history.close_intent,visit,human,owner)
                        if command is not None:await asyncio.to_thread(sideband.send,command)
                        if asyncio.get_running_loop().time()>=close_deadline:
                            await send({'type':'finalization_unconfirmed','id':visit,'message':'Voice paused; pending work and final usage need review.'})
                            break
        except (OSError,ValueError,RenderError,LiveUnavailable,CodexVoiceUnavailable,
                ProviderUnavailable,HTTPException,TimeoutError,WebSocketDisconnect) as error:
            messages={
                'stored_continuation_needs_review':'The previous conversation needs review before continuing. No new voice call was created.',
                'prior_creation_needs_review':'The previous voice connection is not confirmed closed. Your recordings and work are kept for review.',
                'creation_storage_full':'Voice history storage is full. Your recordings and work are kept; review storage before starting another call.',
                'native_reader_unavailable':'This native voice comparison needs its prepared server update. No voice call was opened.',
                'project_key_unavailable':'This voice comparison needs its configured OpenAI project access. Your recordings and work are unchanged.'}
            message=messages.get(error.outcome) if isinstance(error,LiveUnavailable) else None
            with suppress(Exception):
                await asyncio.wait_for(socket.send_json({'type':'unconfirmed','id':visit,
                    'message':message or 'Voice paused. Keep your original audio; the connection and pending work need review.'}),2)
        finally:
            with CancelScope(shield=True):
                try:
                    preparation_stopped.set()
                    if admitted:
                        with suppress(Exception):await asyncio.to_thread(history.end_capture,visit,human,binding)
                    for task in (read_browser,read_provider):
                        if task is not None:
                            task.cancel()
                            with suppress(BaseException):await task
                    # Retain one in-flight POST's actual outcome. Never reissue a lost
                    # request or send session.close as disconnected-client cleanup.
                    if creating is not None:
                        with suppress(BaseException):await asyncio.wait_for(asyncio.shield(creating),50)
                    if preparing is not None:
                        with suppress(BaseException):await asyncio.wait_for(asyncio.shield(preparing),50)
                    if returning is not None:
                        with suppress(BaseException):await asyncio.wait_for(asyncio.shield(returning),50)
                    if sideband is not None:
                        with suppress(Exception):await asyncio.to_thread(sideband.detach)
                    if admitted:
                        with suppress(Exception):await asyncio.to_thread(history.end_capture,visit,human,binding)
                    if visit:history.release_sources(visit)
                    with suppress(Exception):await asyncio.wait_for(socket.close(),1)
                finally:
                    if lease is not None:lease.release()
    return True
