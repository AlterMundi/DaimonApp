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

from .codex_voice import AvatarVoiceLease, CodexVoice
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
        try:return await asyncio.to_thread(history.read,visit,session['human'],binding)
        except (OSError,ValueError):raise HTTPException(404,'Voice visit unavailable')from None

    @app.get('/api/interaction/voice/codex/visits')
    async def recent_visits(request:Request):
        binding=request.headers.get('x-voice-binding','')
        session=await http_owner(request,binding)
        def read():
            values=history.list(session['human'],binding)
            return {'visits':[history.read(v['id'],session['human'],binding)for v in values[:8]],
                    'more':len(values)>8}
        return await asyncio.to_thread(read)

    @app.post('/api/interaction/voice/codex/visits/{visit}/recordings/{ordinal}')
    async def original(visit:str,ordinal:int,request:Request):
        binding=request.headers.get('x-voice-binding','')
        session=await http_owner(request,binding,write=True)
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
                receipt=await asyncio.to_thread(history.recording,visit,session['human'],binding,ordinal,bytes(data),provider)
            return {'visit':visit,'binding':binding,'recording':receipt}
        except (OSError,ValueError,ProviderUnavailable):
            raise HTTPException(409,'Original could not be confirmed; keep the same local audio and inspect its receipt')from None

    @app.websocket('/api/interaction/voice/codex')
    async def native_voice(socket:WebSocket):
        if socket.headers.get('origin')not in origins:
            await socket.close(code=1008);return
        await socket.accept()
        lease=voice=opening=starting=incoming=events=None
        visit=human=binding=None;closed=False;collectors=set();turns=set();collection_failed=False;transcript_failed=False;retained_visit=False
        async def send(value):
            await recheck()
            await asyncio.wait_for(socket.send_json(value),3)
        async def collect(turn,check=True):
            # Observation only. Never infer that arbitrary concurrent work was
            # caused by a nearby transcript, and never replay its human input.
            for _ in range(20):
                if check:await recheck()
                value=await asyncio.to_thread(provider.codex_voice_collect,owner,turn)
                if value['state']!='pending':return
                await asyncio.sleep(.25)
            raise ValueError('Native tools collector did not attach')
        try:
            async with asyncio.timeout(seconds+60):
                raw=await asyncio.wait_for(socket.receive_text(),5)
                if len(raw.encode())>8192:raise ValueError('Voice metadata exceeds bound')
                meta=json.loads(raw)
                if (not isinstance(meta,dict)or set(meta)-{'id','binding','csrf','authorization'}
                        or not all(isinstance(meta.get(k),str)for k in ('id','binding','csrf'))):
                    raise ValueError('Select one native voice visit')
                visit=history.ident(meta['id']);binding=meta['binding']
                session,recheck,actor=await bind_voice_actor(provider,authorize,socket,meta,require_voice=False)
                human=session['human'];owner=await frozen(binding)
                lease=AvatarVoiceLease(app.state.voice_active,human,binding,owner['native_thread'])
                # Supported owner-selected developer item; never browser text.
                from .native_voice import being_identity
                identity=being_identity({'native_identity_file':selected['identity_file']})
                context=identity['text']
                startup=await asyncio.to_thread(history.continuation,human,owner)
                opening=asyncio.create_task(asyncio.to_thread(CodexVoice,provider.native_home,
                    owner['native_thread'],lease=lease))
                voice=await asyncio.shield(opening)
                await asyncio.to_thread(history.open,visit,human,owner,voice.session_id,seconds,
                    identity_sha256=identity['sha256'],startup=startup)
                retained_visit=True
                await send({'type':'prepared','id':visit,'session_seconds':seconds,'mode':'codex_webrtc'})
                raw=await asyncio.wait_for(socket.receive_text(),20)
                if len(raw.encode())>70000:raise ValueError('Voice offer exceeds bound')
                offer=json.loads(raw)
                if not isinstance(offer,dict)or set(offer)!={'type','sdp'}or offer['type']!='offer':
                    raise ValueError('Select one WebRTC offer')
                await recheck()
                if await frozen(binding)!=owner:raise ValueError('Voice owner changed')
                starting=asyncio.create_task(asyncio.to_thread(voice.start,offer['sdp'],
                    voice=selected.get('voice','cove'),context=context,continuation=startup))
                await asyncio.shield(starting)
                incoming=asyncio.create_task(socket.receive_text())
                events=asyncio.create_task(asyncio.to_thread(voice.receive,.25))
                deadline=asyncio.get_running_loop().time()+seconds
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
                        if len(raw)>128 or json.loads(raw)!={'type':'close'}:
                            raise ValueError('Native voice accepts media through WebRTC only')
                        break
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
                            elif method=='turn/started':
                                turn=p.get('turn',{}).get('id')
                                if turn not in turns:
                                    if len(turns)>=32 or len(collectors)>=2:raise ValueError('Native collector bound reached')
                                    turns.add(turn);collectors.add(asyncio.create_task(collect(turn)))
                            elif method=='thread/realtime/closed':closed=True;break
                            elif method=='thread/realtime/error':raise ValueError('Native voice failed')
                        if closed:break
                        events=asyncio.create_task(asyncio.to_thread(voice.receive,.25))
                    await actor()
        except (Exception,asyncio.CancelledError)as error:
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
                if starting is not None:
                    with suppress(Exception):await asyncio.shield(starting)
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
                                if event.get('method')=='thread/realtime/item/completed':
                                    item=event.get('params',{}).get('item',{})
                                    if item.get('type')=='transcriptSegment':
                                        try:await asyncio.to_thread(history.item,visit,human,binding,item)
                                        except (OSError,ValueError):collection_failed=True;transcript_failed=True
                            # Persist the previous visit's last completed sources
                            # before admitting a successor startup snapshot.
                            if retained_visit and closed and not transcript_failed:
                                await asyncio.to_thread(history.complete_transcript,visit,human,binding)
                            if lease is not None and closed:lease.release()
                            with suppress(Exception):await asyncio.wait_for(socket.send_json({
                                'type':'closed','id':visit,'confirmed':closed}),1)
                            if collectors:
                                results=await asyncio.gather(*collectors,return_exceptions=True)
                                if any(isinstance(value,BaseException)for value in results):collection_failed=True
                            current=await asyncio.to_thread(provider.codex_voice_current,owner)
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
                    with suppress(Exception):await asyncio.to_thread(voice.close)
                if retained_visit:
                    if starting is None:
                        with suppress(Exception):await asyncio.to_thread(history.abandon_unstarted,visit,human,binding)
                    with suppress(Exception):await asyncio.to_thread(history.state,visit,human,binding,'closed'if closed and not collection_failed else'review')
                if lease is not None:lease.release()
                with suppress(Exception):await asyncio.wait_for(socket.close(),1)
    return True
