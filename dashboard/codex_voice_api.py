"""Explicit native WebRTC visits; capture storage never dispatches native input."""
import asyncio
from anyio import CancelScope
from contextlib import suppress
import json
from pathlib import Path
import re
import secrets

from fastapi import HTTPException, Request, WebSocket
from starlette.websockets import WebSocketDisconnect

from .codex_voice import AvatarVoiceLease, CodexVoice, CodexVoiceUnavailable
from .codex_voice_history import CodexVoiceHistory, IncompleteTranscript
from .live_transcription import bind_voice_actor
from .provider import ProviderUnavailable


def install(app,config,provider,authorize,origins):
    selected=config.get('codex_voice',{})
    if selected.get('enabled')is not True:return False
    if (set(selected)-{'enabled','session_seconds','voice','identity_file'}
            or type(selected.get('session_seconds',600))is not int
            or not 300<=selected.get('session_seconds',600)<=600
            or not re.fullmatch('[a-z]{1,32}',selected.get('voice','cove'))
            or not isinstance(selected.get('identity_file'),str)
            or not Path(selected['identity_file']).is_absolute()):
        raise ValueError('Select bounded owner-configured native Codex voice')
    history=CodexVoiceHistory(Path(config['state_dir'])/'codex-voice-visits')
    seconds=selected.get('session_seconds',600)
    uploads=asyncio.Semaphore(2)

    async def frozen(binding):
        return await asyncio.to_thread(provider.codex_voice_binding,binding)

    async def http_owner(request,binding,*,write=False):
        session=await authorize(request)
        if write and (request.headers.get('origin')not in origins
                or not secrets.compare_digest(request.headers.get('x-dashboard-csrf',''),session['csrf'])):
            raise HTTPException(403,'Fresh voice action token required')
        # Reads/uploads can recover originals while native work is held. They
        # validate the current binding but cannot start/attach any native work.
        value=await asyncio.to_thread(provider.presentation,'input list 9223372036854775807 after')
        if not re.fullmatch('[a-f0-9]{64}',binding)or value.get('binding')!=binding:
            raise HTTPException(409,'Voice conversation binding changed')
        return session

    @app.get('/api/interaction/voice/codex/visits/{visit}')
    async def visit_status(visit:str,request:Request):
        binding=request.headers.get('x-voice-binding','')
        session=await http_owner(request,binding)
        try:return {**await asyncio.to_thread(history.read,visit,session['human'],binding),'capture_prefix_retention':'v1'}
        except (OSError,ValueError):raise HTTPException(404,'Voice visit unavailable')from None

    @app.get('/api/interaction/voice/codex/visits')
    async def recent_visits(request:Request,before:str|None=None):
        binding=request.headers.get('x-voice-binding','')
        session=await http_owner(request,binding)
        def read():
            values=history.list(session['human'],binding,before=before,limit=9)
            return {'visits':[history.read(v['id'],session['human'],binding)for v in values[:8]],
                    'more':len(values)>8,'before':values[7]['id']if len(values)>8 else None}
        try:return await asyncio.to_thread(read)
        except ValueError:raise HTTPException(404,'Voice history page unavailable')from None

    @app.post('/api/interaction/voice/codex/visits/{visit}/capture/ended')
    async def end_capture(visit:str,request:Request):
        binding=request.headers.get('x-voice-binding','')
        session=await http_owner(request,binding,write=True)
        try:
            owner=await frozen(binding)
            await asyncio.to_thread(history.end_admission,visit,session['human'],owner)
            return {'visit':visit,'binding':binding,'capture':'ended'}
        except (OSError,ValueError,ProviderUnavailable):
            raise HTTPException(409,'Microphone admission could not be confirmed ended')from None

    @app.post('/api/interaction/voice/codex/visits/{visit}/recordings/{ordinal}')
    async def original(visit:str,ordinal:int,request:Request):
        binding=request.headers.get('x-voice-binding','')
        session=await http_owner(request,binding,write=True)
        capture_stop=request.headers.get('x-voice-capture-stop')
        if capture_stop not in (None,'interrupted_prefix'):
            raise HTTPException(400,'Unknown native recording provenance')
        if not 0<=ordinal<32:raise HTTPException(400,'Recording index exceeds bound')
        if uploads.locked():raise HTTPException(429,'Two voice originals are being retained')
        try:
            async with uploads:
                await asyncio.to_thread(history.read,visit,session['human'],binding)
                data=bytearray()
                async with asyncio.timeout(30):
                    async for part in request.stream():
                        if len(data)+len(part)>120*32000+44:raise HTTPException(413,'Voice original exceeds bound')
                        data.extend(part)
                if (await authorize(request))['human']!=session['human']:
                    raise HTTPException(403,'Voice audience changed')
                receipt=await asyncio.to_thread(history.recording,visit,session['human'],binding,ordinal,bytes(data),provider,capture_stop=capture_stop)
            return {'visit':visit,'binding':binding,'recording':receipt}
        except (OSError,ValueError,ProviderUnavailable):
            raise HTTPException(409,'Original could not be confirmed; keep the same local audio and inspect its receipt')from None

    @app.websocket('/api/interaction/voice/codex')
    async def native_voice(socket:WebSocket):
        if socket.headers.get('origin')not in origins:
            await socket.close(code=1008);return
        await socket.accept()
        lease=voice=opening=remembering=starting=incoming=events=noticing=None
        visit=human=binding=None;closed=False;collectors=set();turns=set();collection_failed=False;transcript_failed=False;retained_visit=False
        logical=False;admission=None;close_reason='review'
        pending=[];anchors={};unpresented=set();failed_notices=set();playback_ready=False
        async def send(value):
            await recheck()
            await asyncio.wait_for(socket.send_json(value),3)
        async def remember_anchor(turn):
            if turn in anchors:return
            try:
                if await frozen(binding)!=owner:return
                anchor=await asyncio.to_thread(voice.work_anchor,turn)
                if anchor is None:return
                await recheck()
                if await frozen(binding)!=owner:return
                await asyncio.to_thread(history.retain_anchor,visit,human,binding,turn,anchor)
                anchors[turn]=anchor
            except (CodexVoiceUnavailable,OSError,ValueError):
                return  # Optional location metadata must not interrupt useful voice.
        async def collect(turn,check=True):
            # Observation only. Never infer that arbitrary concurrent work was
            # caused by a nearby transcript, and never replay its human input.
            for _ in range(20):
                if check:await recheck()
                value=await asyncio.to_thread(provider.codex_voice_collect,owner,turn)
                if value['state']!='pending':
                    await remember_anchor(turn)
                    return
                await asyncio.sleep(.25)
            raise ValueError('Native tools collector did not attach')
        async def offer_pending():
            nonlocal noticing
            if not playback_ready or not pending:return
            async def notice(status):
                try:await asyncio.to_thread(history.notice_status,visit,human,binding,status)
                except (OSError,ValueError):pass  # The same store may be full.
            async def present():
                for turn in list(pending):
                    if turn in failed_notices:continue
                    await recheck()
                    if await frozen(binding)!=owner:raise ValueError('Native result owner changed')
                    try:result=await asyncio.to_thread(voice.completed_result,turn,anchor=anchors.get(turn))
                    except (CodexVoiceUnavailable,OSError,ValueError):
                        failed_notices.add(turn)
                        await notice('source_unavailable')
                        return  # Optional presentation must not end useful voice.
                    if result is None:continue
                    if result.get('status')in ('failed','interrupted'):
                        await asyncio.to_thread(history.finish_work,visit,human,binding,turn,result['status'])
                        pending.remove(turn);continue
                    try:claimed=await asyncio.to_thread(history.claim_result,visit,human,owner,result)
                    except (OSError,ValueError):
                        failed_notices.add(turn)
                        await notice('source_unavailable')
                        return  # Optional provenance capacity must not end voice.
                    pending.remove(turn)
                    if not claimed:continue
                    # This retained source is assistant presentation, not a new
                    # user turn, tool invocation or client-managed delegation.
                    await recheck()
                    try:await asyncio.to_thread(voice.offer_result,result)
                    except (CodexVoiceUnavailable,OSError,ValueError):
                        await notice('submission_unconfirmed')
                        return  # Retained intent prevents an uncertain replay.
                    await asyncio.to_thread(history.confirm_result,visit,human,binding,turn)
                    break  # Let the native utterance finish before another offer.
            noticing=asyncio.create_task(present())
            await asyncio.shield(noticing)
        try:
            async with asyncio.timeout(seconds+60):
                raw=await asyncio.wait_for(socket.receive_text(),5)
                if len(raw.encode())>8192:raise ValueError('Voice metadata exceeds bound')
                meta=json.loads(raw)
                if (not isinstance(meta,dict)or set(meta)-{'id','binding','csrf','authorization','logical_visit','predecessor'}
                        or 'logical_visit'in meta and meta['logical_visit']is not True
                        or 'predecessor'in meta and meta.get('logical_visit')is not True
                        or not all(isinstance(meta.get(k),str)for k in ('id','binding','csrf'))):
                    raise ValueError('Select one native voice visit')
                visit=history.ident(meta['id']);binding=meta['binding']
                session,recheck,actor=await bind_voice_actor(provider,authorize,socket,meta,require_voice=False)
                human=session['human'];owner=await frozen(binding)
                lease=AvatarVoiceLease(app.state.voice_active,human,binding,owner['native_thread'])
                logical=meta.get('logical_visit')is True
                if logical and 'predecessor'in meta:
                    # Reserve before opening any native control/start. A lost
                    # response cannot be retried with another visit UUID.
                    admission=await asyncio.to_thread(history.claim_successor,
                        meta['predecessor'],visit,human,owner)
                # Supported owner-selected developer item; never browser text.
                from .native_voice import being_identity
                identity=being_identity({'native_identity_file':selected['identity_file']})
                context=identity['text']
                try:startup=await asyncio.to_thread(history.continuation,human,owner)
                except IncompleteTranscript:
                    pending=await asyncio.to_thread(history.incomplete,human,owner)
                    sources=await asyncio.to_thread(provider.codex_voice_transcripts,owner,pending)
                    await asyncio.to_thread(history.reconcile,human,owner,sources)
                    startup=await asyncio.to_thread(history.continuation,human,owner)
                memory=await asyncio.to_thread(history.memory_context,human,owner)
                if memory is not None:
                    startup=await asyncio.to_thread(history.continuation,human,owner,reserve=len(memory.encode()))
                opening=asyncio.create_task(asyncio.to_thread(CodexVoice,provider.native_home,
                    owner['native_thread'],lease=lease))
                voice=await asyncio.shield(opening)
                if memory is not None:
                    await recheck()
                    if await frozen(binding)!=owner:raise ValueError('Voice owner changed')
                    remembering=asyncio.create_task(asyncio.to_thread(history.remember,human,owner,memory,voice,provider))
                    await asyncio.shield(remembering)
                await asyncio.to_thread(history.open,visit,human,owner,voice.session_id,seconds,
                    identity_sha256=identity['sha256'],startup=startup,
                    admission_root=None if admission is None else admission['id'])
                retained_visit=True
                pending=await asyncio.to_thread(history.pending_work,human,owner)
                current=await asyncio.to_thread(provider.codex_voice_current,owner)
                if current is not None and current not in pending:pending.append(current)
                await asyncio.to_thread(history.retain_work,visit,human,binding,pending)
                anchors=await asyncio.to_thread(history.work_anchors,human,owner,pending)
                if current is not None:await remember_anchor(current)
                await send({'type':'prepared','id':visit,'session_seconds':seconds,'mode':'codex_webrtc',
                    **({'logical_visit':'v1','admission':admission}if logical else{})})
                if logical and admission is None:
                    # Permission may be granted first, but capture/WebRTC input
                    # must not begin before this one server-owned deadline.
                    raw=await asyncio.wait_for(socket.receive_text(),20)
                    if len(raw)>128 or json.loads(raw)!={'type':'capture'}:
                        raise ValueError('Begin one logical microphone admission')
                    await recheck()
                    if await frozen(binding)!=owner:raise ValueError('Voice owner changed')
                    admission=await asyncio.to_thread(history.begin_admission,visit,human,owner)
                    await send({'type':'capture_ready','id':visit,'admission':admission})
                raw=await asyncio.wait_for(socket.receive_text(),20)
                if len(raw.encode())>70000:raise ValueError('Voice offer exceeds bound')
                offer=json.loads(raw)
                if not isinstance(offer,dict)or set(offer)!={'type','sdp'}or offer['type']!='offer':
                    raise ValueError('Select one WebRTC offer')
                await recheck()
                if await frozen(binding)!=owner:raise ValueError('Voice owner changed')
                if logical:admission=await asyncio.to_thread(history.admission_status,visit,human,owner)
                starting=asyncio.create_task(asyncio.to_thread(voice.start,offer['sdp'],
                    voice=selected.get('voice','cove'),context=context,continuation=startup,memory=memory))
                await asyncio.shield(starting)
                if logical:admission=await asyncio.to_thread(history.admission_status,visit,human,owner)
                incoming=asyncio.create_task(socket.receive_text())
                events=asyncio.create_task(asyncio.to_thread(voice.receive,.25))
                deadline=asyncio.get_running_loop().time()+(seconds if admission is None else admission['remaining_seconds'])
                close_reason='time_limit'
                while asyncio.get_running_loop().time()<deadline:
                    done,_=await asyncio.wait([incoming,events,*collectors],timeout=.5,
                        return_when=asyncio.FIRST_COMPLETED)
                    for task in list(collectors):
                        if task in done:
                            collectors.remove(task)
                            try:task.result()
                            except Exception:collection_failed=True;raise
                    if incoming in done:
                        raw=incoming.result()
                        message=json.loads(raw)if len(raw)<=128 else None
                        if message=={'type':'close'}:close_reason='requested';break
                        if message=={'type':'renew'}and logical:
                            # Owned recovery of failed media, not a new turn,
                            # microphone permission or cancellation of work.
                            await recheck()
                            if await frozen(binding)!=owner:raise ValueError('Voice owner changed')
                            await asyncio.to_thread(history.admission_status,visit,human,owner)
                            close_reason='media_replacement';break
                        if message!={'type':'ready'}:
                            raise ValueError('Native voice accepts media through WebRTC only')
                        playback_ready=True
                        incoming=asyncio.create_task(socket.receive_text())
                        await offer_pending()
                    if events in done:
                        try:batch=events.result()
                        except Exception:transcript_failed=True;raise
                        for event in batch:
                            method=event['method'];p=event['params']
                            if method=='thread/realtime/started':
                                await asyncio.to_thread(history.state,visit,human,binding,'active')
                            elif method=='thread/realtime/sdp':
                                if not isinstance(p.get('sdp'),str)or len(p['sdp'].encode())>65536:
                                    raise ValueError('Native answer exceeds bound')
                                await send({'type':'answer','id':visit,'sdp':p['sdp']})
                            elif method=='thread/realtime/item/completed':
                                item=p.get('item',{})
                                if item.get('type')=='transcriptSegment':
                                    try:saved=await asyncio.to_thread(history.item,visit,human,binding,item)
                                    except (OSError,ValueError):transcript_failed=True;raise
                                    source=next(v for v in saved['items']if v['id']==item['id'])
                                    await send({'type':'transcript','id':visit,
                                        'item':source})
                                    if source['role']=='assistant':await offer_pending()
                            elif method=='turn/started':
                                turn=p.get('turn',{}).get('id')
                                if turn not in turns:
                                    if len(turns)>=32 or len(collectors)>=2:raise ValueError('Native collector bound reached')
                                    turns.add(turn);unpresented.add(turn)
                                    await asyncio.to_thread(history.retain_work,visit,human,binding,
                                        list(dict.fromkeys([*pending,*sorted(unpresented)])))
                                    collectors.add(asyncio.create_task(collect(turn)))
                            elif method=='turn/completed':
                                turn=p.get('turn',{}).get('id')
                                # Completion is not a presentation receipt. Keep
                                # newly observed work eligible after closure.
                                if turn in pending:await offer_pending()
                            elif method=='thread/realtime/closed':
                                closed=True
                                close_reason={'transport_closed':'native_transport_closed',
                                    'requested':'native_requested','error':'native_error'}.get(p.get('reason'),'native_closed')
                                break
                            elif method=='thread/realtime/error':raise ValueError('Native voice failed')
                        if closed:break
                        events=asyncio.create_task(asyncio.to_thread(voice.receive,.25))
                    await actor()
        except (Exception,asyncio.CancelledError)as error:
            close_reason='review'
            # No native/provider payload, identity or credentials in diagnostics.
            with suppress(Exception):await asyncio.wait_for(socket.send_json({'type':'review','id':visit,
                'message':('Previous voice history needs reconciliation before reconnecting. Recordings and accepted work are kept.'
                    if isinstance(error,IncompleteTranscript)else
                    'Voice paused. Original recordings and accepted work remain available.')}),1)
        finally:
            with CancelScope(shield=True):
                for task in (incoming,):
                    if task is not None:task.cancel()
                for task in (incoming,):
                    if task is not None:
                        with suppress(Exception,asyncio.CancelledError):await task
                # A cancelled open/start is awaited once, never retried. Cleanup
                # closes voice only and leaves accepted backend work running.
                if opening is not None and voice is None:
                    with suppress(Exception):voice=await asyncio.shield(opening)
                if remembering is not None:
                    with suppress(Exception):await asyncio.shield(remembering)
                if starting is not None:
                    with suppress(Exception):await asyncio.shield(starting)
                if noticing is not None:
                    with suppress(Exception):await asyncio.shield(noticing)
                control_closed=False
                if voice is not None:
                    try:
                        await asyncio.to_thread(voice.stop)
                        closed=voice.closure_observed
                    except Exception:closed=False
                    # Native observed closure drains parsed handoffs before ending
                    # its fanout. Reconcile the admitted writer after that barrier;
                    # backend tools/results must not depend on an open browser.
                    try:
                        async with asyncio.timeout(10):
                            tail=[]
                            try:
                                if events is not None:tail.extend(await events)
                                tail.extend(await asyncio.to_thread(voice.receive,0))
                            except Exception:collection_failed=True;transcript_failed=True
                            for event in tail:
                                if event.get('method')=='turn/started':
                                    turn=event.get('params',{}).get('turn',{}).get('id')
                                    if isinstance(turn,str):unpresented.add(turn)
                                if event.get('method')=='thread/realtime/item/completed':
                                    item=event.get('params',{}).get('item',{})
                                    if item.get('type')=='transcriptSegment':
                                        try:await asyncio.to_thread(history.item,visit,human,binding,item)
                                        except (OSError,ValueError):collection_failed=True;transcript_failed=True
                            carried=list(dict.fromkeys([*pending,*sorted(unpresented)]))
                            if retained_visit:await asyncio.to_thread(history.retain_work,visit,human,binding,carried)
                            # Persist the previous visit's last completed sources
                            # before admitting a successor startup snapshot.
                            if retained_visit and closed and not transcript_failed:
                                await asyncio.to_thread(history.complete_transcript,visit,human,binding)
                            if collectors:
                                results=await asyncio.gather(*collectors,return_exceptions=True)
                                if any(isinstance(value,BaseException)for value in results):collection_failed=True
                            current=await asyncio.to_thread(provider.codex_voice_current,owner)
                            if current is not None and current not in carried and retained_visit:
                                await asyncio.to_thread(history.retain_work,visit,human,binding,[*carried,current])
                            if current is not None and current not in turns:
                                turns.add(current)
                                # Enrolled owner rechecks remain in the provider.
                                # This is continuation of already accepted work,
                                # independent of expiration of the browser session.
                                await collect(current,check=False)
                    except (Exception,asyncio.CancelledError):collection_failed=True
                    finally:
                        if events is not None and not events.done():events.cancel()
                        if events is not None:
                            with suppress(Exception,asyncio.CancelledError):await events
                        for task in collectors:
                            if not task.done():task.cancel()
                        for task in collectors:
                            with suppress(Exception,asyncio.CancelledError):await task
                    with suppress(Exception):
                        await asyncio.to_thread(voice.close)
                        control_closed=True
                successor_ready=False
                if retained_visit:
                    if starting is None:
                        with suppress(Exception):await asyncio.to_thread(history.abandon_unstarted,visit,human,binding)
                    with suppress(Exception):
                        terminal=await asyncio.to_thread(history.state,visit,human,binding,
                            'closed'if closed and control_closed and not collection_failed and not transcript_failed else'review',
                            successor_ready=closed and control_closed and not collection_failed and not transcript_failed,
                            closure_reason=close_reason)
                        successor_ready=(closed and control_closed and not collection_failed and not transcript_failed
                            and terminal['state']=='closed'and terminal['transcript_complete']is True)
                # A native close notification is not yet a successor barrier:
                # late work references, collectors and terminal metadata still
                # belong to this lease. Publish readiness only after they settle
                # and this exact control connection has been closed. Failure
                # retains review; it must never authorize an automatic restart.
                if lease is not None:lease.release()
                if voice is not None:
                    with suppress(Exception):await asyncio.wait_for(socket.send_json({
                        'type':'closed','id':visit,'confirmed':closed,
                        'successor_ready':successor_ready,'reason':close_reason}),1)
                with suppress(Exception):await asyncio.wait_for(socket.close(),1)
    return True
