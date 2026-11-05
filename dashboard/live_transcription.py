"""Authenticated voice preparation over one bounded WebSocket; no input dispatch."""
import asyncio
from contextlib import suppress
from collections import deque
import hashlib
import io
import json
import logging
from pathlib import Path
import re
import secrets
import time
import threading
import wave

from fastapi import HTTPException, WebSocket
from starlette.requests import Request
from starlette.websockets import WebSocketDisconnect

from .private_state import private_directory, read_json, write_json
from .transcription import TranscriptionStream, TranscriptionUnavailable
from .turn_detection import Detector, DetectionUnavailable, analyze_capture, command as detection_command
from scripts.speech_render import lock, RenderError


class VoiceInbox:
    """Collect already-arrived frames while fresh authorization is in flight.

    No batching timer, dropped PCM/events, auth cache or persistence. Input is bounded to
    eight seconds pending PCM and 128 messages; output retains at most 128 worker
    events (the worker already bounds each JSON line). Original packet sizes and
    order survive batching. Controls remain separate by default; native PCM may
    opt into ordered control batching and a finite wait for consumer space.
    Disconnect always stays separate.
    """
    space_timeout = 3

    def __init__(self, receive, *, pcm=False, batch_size=10, control_bytes=256, batch_control_frames=False, wait_for_space=False):
        if type(batch_size) is not int or not 1<=batch_size<=50:
            raise ValueError('Invalid bounded voice batch size')
        if type(control_bytes) is not int or not 256<=control_bytes<=8192:
            raise ValueError('Invalid bounded voice control size')
        if type(batch_control_frames) is not bool or batch_control_frames and not pcm:
            raise ValueError('Control batching requires a PCM inbox')
        if type(wait_for_space) is not bool or wait_for_space and not pcm:
            raise ValueError('Backpressure requires a PCM inbox')
        self.wait_for_space=wait_for_space
        self.space=asyncio.Event()
        self.batch_control_frames=batch_control_frames
        self.control_bytes=control_bytes
        self.batch_size=batch_size
        self.receive = receive
        self.pcm = pcm
        self.items = deque()
        self.bytes = 0
        self.received_bytes = self.received_messages = 0
        self.peak_bytes = self.peak_messages = 0
        self.peak_wait_seconds = 0
        self.analyzed_bytes = self.onsets = self.endpoints = 0
        self.changed = asyncio.Event()
        self.error = None
        self.task = asyncio.create_task(self.collect())

    async def collect(self):
        try:
            while True:
                value = await self.receive()
                arrived=asyncio.get_running_loop().time()
                size = 0
                if self.pcm:
                    if value.get('bytes') is not None:
                        size = len(value['bytes'])
                        if not size or size % 2 or size > 32000:
                            raise ValueError('Foreground PCM exceeds frame bounds')
                    elif len(value.get('text', '').encode()) > self.control_bytes:
                        raise ValueError('Foreground control exceeds bound')
                deadline=asyncio.get_running_loop().time()+self.space_timeout
                while len(self.items) >= 128 or self.bytes + size > 256000:
                    if not self.wait_for_space:
                        raise ValueError('Voice processing backlog exceeds bound')
                    # Pause network reads at the existing memory bound, retaining
                    # this one validated frame. A burst is not a stalled consumer.
                    # The fixed deadline cannot be extended by control-only drains.
                    self.space.clear()
                    try:
                        await asyncio.wait_for(self.space.wait(),max(0,deadline-asyncio.get_running_loop().time()))
                    except TimeoutError:
                        raise ValueError('Voice processing backlog exceeds bound') from None
                self.items.append((value, size, arrived))
                self.bytes += size
                self.received_bytes += size
                self.received_messages += 1
                self.peak_bytes = max(self.peak_bytes, self.bytes)
                self.peak_messages = max(self.peak_messages, len(self.items))
                if not self.pcm:
                    count = value.get('audio_bytes')
                    if type(count) is int and 0 <= count <= 300 * 32000:
                        self.analyzed_bytes = max(self.analyzed_bytes, count)
                    self.onsets += isinstance(value.get('onset'), dict)
                    self.endpoints += isinstance(value.get('endpoint'), dict)
                self.changed.set()
                if self.pcm and value['type'] == 'websocket.disconnect':
                    return
        except Exception as error:
            self.error = error
            self.changed.set()

    async def batch(self):
        while not self.items:
            if self.error is not None:
                raise self.error
            self.changed.clear()
            await self.changed.wait()
        if self.error is not None:
            raise self.error
        values, size = [], 0
        while self.items and len(values) < self.batch_size:
            value, count, arrived = self.items[0]
            # Native playback observations may share the next fresh check with
            # queued PCM/control frames, in exact order. Disconnect stays alone.
            terminal=value.get('type')=='websocket.disconnect'
            control_boundary=not count and not self.batch_control_frames
            if self.pcm and (terminal or control_boundary or size + count > 32000):
                if values:
                    break
            self.items.popleft()
            self.peak_wait_seconds=max(self.peak_wait_seconds,asyncio.get_running_loop().time()-arrived)
            self.bytes -= count
            size += count
            values.append(value)
            if self.pcm and (terminal or control_boundary):
                break
        self.space.set()
        return values

    async def close(self):
        self.task.cancel()
        with suppress(asyncio.CancelledError):
            await self.task
        self.items.clear()
        self.bytes = 0


class VoiceActor:
    """Join only concurrent fresh checks on one socket; never cache a verdict.

    Input, analysis, output and tools can request the same HTTPS identity check
    simultaneously. They share its in-flight result, not its future authority:
    the next call after completion always revalidates. A cancelled waiter cannot
    cancel another stream consumer's check. No token or identity is logged.
    """
    def __init__(self,authorize,request,human):
        self.authorize,self.request,self.human=authorize,request,human
        self.pending=None;self.calls=self.checks=0;self.seconds=self.peak=0

    async def _check(self):
        self.checks+=1;started=asyncio.get_running_loop().time()
        try:
            current=await self.authorize(self.request)
            if current['human']!=self.human:raise HTTPException(403,'Conversation audience changed')
        finally:
            spent=asyncio.get_running_loop().time()-started
            self.seconds+=spent;self.peak=max(self.peak,spent)

    async def __call__(self):
        self.calls+=1
        if self.pending is None or self.pending.done():
            self.pending=asyncio.create_task(self._check())
            self.pending.add_done_callback(lambda t:None if t.cancelled() else t.exception())
        await asyncio.shield(self.pending)

    def snapshot(self):
        return {'calls':self.calls,'fresh_checks':self.checks,
                'total_ms':round(self.seconds*1000),'peak_ms':round(self.peak*1000)}


def wav_bytes(pcm):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
        audio.writeframes(pcm)
    return output.getvalue()


def save_prepared(root, ident, binding, pcm, result):
    """Only completed server recognition can prepare an exact original WAV."""
    if (str(__import__('uuid').UUID(ident)) != ident
            or not re.fullmatch('[a-f0-9]{64}', binding)
            or not isinstance(pcm, bytes) or not pcm or len(pcm) % 2
            or len(pcm) > TranscriptionStream.max_audio_bytes
            or result.get('final') is not True
            or result.get('pcm_sha256') != hashlib.sha256(pcm).hexdigest()
            or result.get('audio_millis') != len(pcm)*1000//32000
            or not isinstance(result.get('text'), str) or not result['text'].strip()
            or len(result['text'].encode()) > 16000):
        raise ValueError('Completed recognition must match the captured audio')
    root = private_directory(root)
    value = {'schema':'telecodex.streaming-transcript/v1', 'capture_id':ident,
             'binding':binding, 'source_sha256':hashlib.sha256(wav_bytes(pcm)).hexdigest(),
             'created_at':time.time(), **result}
    with lock(root / '.lock'):
        target = root / (ident + '.json')
        if target.exists() or target.is_symlink():
            old = read_json(target)
            if any(old.get(k) != v for k,v in value.items() if k != 'created_at'):
                raise ValueError('Prepared recording identity cannot be replaced')
            return old
        # This cache retains text only. Never evict an uncertain/original input.
        files = list(root.iterdir())
        if len(files) > 32768 or sum(p.lstat().st_size for p in files) + 65536 > 64*1024*1024:
            raise ValueError('Prepared transcription storage is full')
        write_json(target, value)
    return value


async def bind_voice_actor(provider, authorize, socket, meta, *, require_voice=True):
    headers = list(socket.scope['headers'])
    if 'authorization' in meta:
        if (not isinstance(meta['authorization'], str) or len(meta['authorization']) > 128
                or socket.headers.getlist('authorization')):
            raise ValueError('One explicit session credential required')
        headers.append((b'authorization', meta['authorization'].encode('ascii')))
    request = Request({**socket.scope, 'type': 'http', 'method': 'POST',
        'scheme': 'https' if socket.url.scheme == 'wss' else 'http', 'headers': headers})
    session = await authorize(request)
    if not secrets.compare_digest(meta['csrf'], session['csrf']):
        raise HTTPException(403, 'Action token missing')
    if require_voice and not getattr(provider, 'receiver', {}).get('voice'):
        raise ValueError('Voice input unavailable')
    actor=VoiceActor(authorize,request,session['human'])
    async def recheck():
        await actor()
        value = await asyncio.to_thread(provider.presentation, f'input list {2**63-1} after')
        if value['binding'] != meta['binding']:
            raise ValueError('Conversation binding changed')
    await recheck()
    return session, recheck, actor



def install(app, config, provider, authorize, origins):
    selected = config.get('streaming_transcription', {})
    if selected.get('enabled') is not True:
        return False
    mode=selected.get('mode','prepared')
    if (mode not in ('prepared','captions')
            or selected.get('provider','qwen') not in ('qwen','gemini')
            or set(selected)-{'enabled','endpoint','credential_file','cache_root','mode','provider','fallback','turn_detection','native_dialogue','native_activity_mode','native_identity_file','native_voice_name','native_caption_recovery','native_session_seconds','native_provider','native_credential_file'}
            or not {'enabled','endpoint','credential_file','cache_root'}<=set(selected)
            or any(not isinstance(selected[k], str) for k in ('endpoint','credential_file','cache_root'))
            or not all(Path(selected[k]).is_absolute() for k in ('credential_file','cache_root'))):
        raise ValueError('Explicit private streaming-transcription binding required')
    native_provider=selected.get('native_provider','gemini')
    if native_provider not in ('gemini','qwen'):
        raise ValueError('Select a supported native conversation provider')
    if native_provider=='qwen' and (selected.get('native_dialogue') is not True
            or selected.get('native_activity_mode','manual')!='manual'
            or not isinstance(selected.get('native_credential_file'),str)
            or not Path(selected['native_credential_file']).is_absolute()):
        raise ValueError('Native provider dialogue needs explicit private credentials and manual activity')
    if 'native_credential_file' in selected and (native_provider!='qwen'
            or not isinstance(selected['native_credential_file'],str)
            or not Path(selected['native_credential_file']).is_absolute()):
        raise ValueError('Select explicit private native provider credentials')
    fallback=selected.get('fallback')
    if fallback is not None and (selected.get('provider')!='gemini'
            or not isinstance(fallback,dict) or set(fallback)!={'provider','endpoint','credential_file'}
            or fallback.get('provider')!='qwen'
            or not isinstance(fallback.get('endpoint'),str)
            or not isinstance(fallback.get('credential_file'),str)
            or not Path(fallback['credential_file']).is_absolute()):
        raise ValueError('Select one explicit Qwen fallback for Gemini streaming')
    if 'native_dialogue' in selected and type(selected['native_dialogue']) is not bool:
        raise ValueError('Select explicit native dialogue enablement')
    if (selected.get('native_activity_mode','manual') not in ('manual','automatic')
            or 'native_activity_mode' in selected and selected.get('native_dialogue') is not True):
        raise ValueError('Select an explicit native activity mode for enabled dialogue')
    if 'native_caption_recovery' in selected and (type(selected['native_caption_recovery']) is not bool
            or selected.get('native_dialogue') is not True):
        raise ValueError('Select explicit native caption recovery for enabled dialogue')
    if 'native_session_seconds' in selected and (type(selected['native_session_seconds']) is not int
            or not 300<=selected['native_session_seconds']<=1800
            or selected.get('native_dialogue') is not True
            or selected.get('native_activity_mode','manual')!='manual'):
        raise ValueError('Select a finite300..1800second manual native session')
    if 'native_identity_file' in selected and (selected.get('native_dialogue') is not True
            or not isinstance(selected['native_identity_file'],str)
            or not Path(selected['native_identity_file']).is_absolute()):
        raise ValueError('Select one explicit native being-identity file')
    if 'native_voice_name' in selected and (selected.get('native_dialogue') is not True
            or not isinstance(selected['native_voice_name'],str)
            or not re.fullmatch('[A-Za-z][A-Za-z0-9]{0,63}',selected['native_voice_name'])):
        raise ValueError('Select one explicit prebuilt native voice name')
    candidates=[selected]+([fallback] if fallback is not None else [])
    detector_command = detection_command(selected)
    root = private_directory(selected['cache_root'])
    active = set()
    if not hasattr(app.state,'voice_active'):app.state.voice_active=set()
    analysis_active = app.state.voice_active
    prepared_writes = asyncio.Semaphore(1)

    async def persist_prepared(*args):
        # A client cancellation cannot release this writer while its filesystem
        # thread is still running. No accumulating blocked writes under I/O load.
        await asyncio.wait_for(prepared_writes.acquire(), 2)
        job = asyncio.create_task(asyncio.to_thread(save_prepared, *args))
        def done(task):
            prepared_writes.release()
            if not task.cancelled():
                task.exception()
        job.add_done_callback(done)
        return await asyncio.wait_for(asyncio.shield(job), 3)

    async def bind_voice(socket, meta):
        return await bind_voice_actor(provider,authorize,socket,meta)


    @app.websocket('/api/interaction/voice/live')
    async def voice_live(socket: WebSocket):
        diagnostic = {'stage':'metadata', 'audio_bytes':0, 'finish_received':False, 'prepared_saved':False}
        preparation_started = {}
        preparation_timing = {}
        def elapsed(stage):
            started = preparation_started.get(stage)
            if started is not None:
                preparation_timing[stage + '_ms'] = round((time.monotonic() - started) * 1000, 2)
        stream = None
        reader = None
        owner = None
        incoming = None
        detector_reader = None
        sending = asyncio.Lock()
        async def send(value):
            async with sending:
                await socket.send_json(value)
        opening_lock, abandoned, opened = threading.Lock(), threading.Event(), []
        if socket.headers.get('origin') not in origins:
            await socket.close(code=1008); return
        await socket.accept()
        try:
            async with asyncio.timeout(140):
                raw = await asyncio.wait_for(socket.receive_text(), timeout=5)
                if len(raw.encode()) > 8192:
                    raise ValueError('Streaming capture metadata exceeds bound')
                meta = json.loads(raw)
                if (not isinstance(meta, dict) or set(meta)-{'id','binding','csrf','authorization','mode','turn_detection'}
                        or not all(isinstance(meta.get(k),str) for k in ('id','binding','csrf'))
                        or not re.fullmatch('[a-f0-9-]{36}',meta['id'])
                        or not re.fullmatch('[a-f0-9]{64}',meta['binding'])):
                    raise ValueError('One exact capture binding required')
                if meta.get('mode','prepared')!=mode:
                    raise ValueError('Capture transcription mode changed')
                if 'turn_detection' in meta and (meta['turn_detection'] is not True or not detector_command):
                    raise ValueError('Conversational analysis unavailable')
                provider.input_id(meta['id'])
                diagnostic['capture_id'] = meta['id']
                session, recheck, _actor = await bind_voice(socket, meta)
                owner = (session['human'], meta['id'])
                if owner in active or len(active) >= 2:
                    owner = None
                    raise ValueError('Voice preparation capacity occupied')
                active.add(owner)
                pcm = bytearray()
                analysis_changed = asyncio.Event()
                if meta.get('turn_detection'):
                    async def receive_detection():
                        async def activity(event):
                            await recheck()
                            await send({'type':'turn_activity','id':meta['id'], 'activity':event})
                        try:
                            await analyze_capture(lambda: Detector.open(detector_command), pcm, analysis_changed, activity)
                        except (OSError, DetectionUnavailable, TimeoutError):
                            await send({'type':'turn_detection_unavailable'})
                    detector_reader = asyncio.create_task(receive_detection())
                candidate_index=0
                def open_provider(start=0):
                    nonlocal candidate_index
                    for index in range(start,len(candidates)):
                        if abandoned.is_set():raise TranscriptionUnavailable('Capture closed during connection setup')
                        choice=candidates[index]
                        try:
                            value=TranscriptionStream(choice['endpoint'],Path(choice['credential_file']),
                                                      provider=choice.get('provider','qwen'))
                        except (OSError,ValueError,TranscriptionUnavailable):
                            if index+1==len(candidates):raise
                            continue
                        with opening_lock:
                            if not abandoned.is_set():
                                candidate_index=index;opened.append(value)
                                return value
                        value.close()
                        raise TranscriptionUnavailable('Capture closed during connection setup')
                    raise TranscriptionUnavailable('No configured streaming provider')
                diagnostic['stage'] = 'provider_open'
                stream = await asyncio.to_thread(open_provider)
                ready, finished = asyncio.Event(), asyncio.Event()
                async def receive_provider():
                    nonlocal stream
                    opening_deadline=time.monotonic()+8
                    while True:
                        try:
                            if not ready.is_set() and time.monotonic()>=opening_deadline:
                                raise TranscriptionUnavailable('Streaming readiness unavailable')
                            event = await asyncio.to_thread(stream.receive)
                        except (OSError,ValueError,TranscriptionUnavailable):
                            # No PCM can be accepted before ready. Once advertised,
                            # never replay this capture into another paid stream.
                            if ready.is_set() or candidate_index+1>=len(candidates):raise
                            await recheck()
                            old=stream
                            await asyncio.to_thread(old.close)
                            with opening_lock:
                                if old in opened:opened.remove(old)
                            stream=await asyncio.to_thread(open_provider,candidate_index+1)
                            opening_deadline=time.monotonic()+8
                            continue
                        if event['type']=='ready': ready.set()
                        if event['type'] in ('ready','partial'):
                            await recheck()
                            await send(event)
                        elif event['type']=='final':
                            if mode=='captions':
                                raise ValueError('Live captions are not a confirmed transcript')
                            elapsed('provider_final')
                            diagnostic['stage'] = 'final_authorization'
                            preparation_started['final_authorization'] = time.monotonic()
                            await recheck()
                            elapsed('final_authorization')
                            diagnostic['stage'] = 'save_prepared'
                            preparation_started['receipt_write'] = time.monotonic()
                            value = await persist_prepared(root,meta['id'],meta['binding'],bytes(pcm),stream.result())
                            elapsed('receipt_write')
                            elapsed('finish_to_prepared')
                            diagnostic['prepared_saved'] = True
                            # Ephemeral durations only: not speech endpoint/acoustic
                            # latency, and not part of the durable exact-WAV receipt.
                            await send({'type':'prepared','id':meta['id'],
                                'source_sha256':value['source_sha256'],'text':value['text'],
                                'timing':preparation_timing})
                            finished.set(); return
                reader = asyncio.create_task(receive_provider())
                checked = time.monotonic()
                while not finished.is_set():
                    incoming = asyncio.create_task(socket.receive())
                    waiting=[incoming,reader]
                    if detector_reader is not None:
                        if detector_reader.done():
                            await detector_reader
                            detector_reader = None
                        else: waiting.append(detector_reader)
                    done,_ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
                    if detector_reader in done:
                        await detector_reader
                        detector_reader = None
                        if incoming not in done and reader not in done:
                            incoming.cancel()
                            with suppress(asyncio.CancelledError): await incoming
                            continue
                    if reader in done:
                        incoming.cancel()
                        with suppress(asyncio.CancelledError): await incoming
                        await reader
                        break
                    message = await incoming
                    if message['type']=='websocket.disconnect':
                        break  # No finish or original admission on disconnect.
                    if time.monotonic()-checked >= 15:
                        await recheck();checked = time.monotonic()
                    if 'bytes' in message and message['bytes'] is not None:
                        if not ready.is_set():raise ValueError('Wait for recognition readiness')
                        data = message['bytes']
                        await asyncio.to_thread(stream.append,data)
                        diagnostic['audio_bytes'] += len(data)
                        diagnostic['stage'] = 'receiving_audio'
                        if mode=='prepared':
                            pcm.extend(data)
                            analysis_changed.set()
                    else:
                        control = message.get('text','')
                        if len(control.encode())>256:raise ValueError('Control exceeds bound')
                        command = json.loads(control)
                        if command == {'type':'discard'}:
                            diagnostic['discarded'] = True
                            break
                        if command != {'type':'finish'}:raise ValueError('Unknown capture control')
                        diagnostic['finish_received'] = True
                        preparation_started['finish_to_prepared'] = time.monotonic()
                        if mode=='captions':raise ValueError('Live captions cannot finalize the original')
                        diagnostic['stage'] = 'finish_authorization'
                        preparation_started['finish_authorization'] = time.monotonic()
                        await recheck()
                        elapsed('finish_authorization')
                        diagnostic['stage'] = 'provider_finalize'
                        preparation_started['provider_final'] = time.monotonic()
                        await asyncio.to_thread(stream.finish)
                        await reader
                        break
        except (HTTPException, ValueError, OSError, UnicodeError, TranscriptionUnavailable,
                WebSocketDisconnect, TimeoutError, RenderError) as error:
            diagnostic['error_type'] = type(error).__name__
            with suppress(Exception):
                await send({'type':'unavailable','message':'Live transcription unavailable. Your recording has not been submitted.'})
        finally:
            # One metadata-only line under the existing bounded system journal.
            # Never include provider events, exception messages, speech or keys.
            if (mode == 'prepared' and diagnostic['audio_bytes']
                    and not diagnostic['prepared_saved'] and not diagnostic.get('discarded')):
                logging.getLogger(__name__).warning('voice_preparation_closed %s',
                    json.dumps(diagnostic, sort_keys=True))
            try:
                # Cancel before any cleanup await: WebView teardown can cancel this
                # handler again while close() unblocks the provider's reader.
                if reader is not None:
                    reader.cancel()
                    if reader.done():
                        with suppress(asyncio.CancelledError,Exception):reader.result()
                if incoming is not None:
                    incoming.cancel()
                if detector_reader is not None:
                    detector_reader.cancel()
                if detector_reader is not None:
                    with suppress(asyncio.CancelledError,Exception):
                        await asyncio.shield(detector_reader)
                # A canceled async wait cannot cancel the blocking dial. Its owning
                # thread closes a late socket instead of orphaning it after timeout.
                with opening_lock:
                    abandoned.set()
                    closing = opened.pop() if opened else None
                if closing is not None:
                    closing_task = asyncio.create_task(asyncio.to_thread(closing.close))
                    # Retrieve completion even if the WebView cancels our wait.
                    closing_task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
                    await asyncio.shield(closing_task)
                if incoming is not None:
                    with suppress(asyncio.CancelledError,Exception):await incoming
                if reader is not None:
                    reader.cancel()
                    with suppress(asyncio.CancelledError,Exception): await reader
                with suppress(Exception):await socket.close()
            finally:
                if owner is not None:active.discard(owner)
    @app.websocket('/api/interaction/voice/activity')
    async def foreground_activity(socket: WebSocket):
        """One explicit warm foreground analyzer; no ASR, originals or work."""
        worker = reader = incoming = inbox = output_inbox = None
        diagnostic = {'outcome': 'cancelled', 'fed_pcm_bytes': 0, 'delivered_pcm_bytes': 0}
        started = time.monotonic()
        intervals = {}
        async def measured(stage, operation, *args):
            before = time.monotonic()
            try:
                return await operation(*args)
            except Exception:
                diagnostic.setdefault('failure_stage', stage)
                raise
            finally:
                elapsed = (time.monotonic() - before) * 1000
                item = intervals.setdefault(stage, {'count': 0, 'total_ms': 0, 'max_ms': 0})
                item['count'] += 1
                item['total_ms'] += elapsed
                item['max_ms'] = max(item['max_ms'], elapsed)
        owner = None
        sending = asyncio.Lock()
        async def send(value):
            async with sending:
                await socket.send_json(value)
        if socket.headers.get('origin') not in origins:
            await socket.close(code=1008)
            return
        await socket.accept()
        try:
            async with asyncio.timeout(305):
                raw = await asyncio.wait_for(socket.receive_text(), 5)
                if len(raw.encode()) > 8192:
                    raise ValueError('Foreground metadata exceeds bound')
                meta = json.loads(raw)
                if (not detector_command or mode != 'prepared' or not isinstance(meta, dict)
                        or set(meta) - {'id', 'binding', 'csrf', 'authorization'}
                        or not all(isinstance(meta.get(k), str) for k in ('id', 'binding', 'csrf'))
                        or not re.fullmatch('[a-f0-9]{64}', meta['binding'])):
                    raise ValueError('One explicit foreground voice binding required')
                provider.input_id(meta['id'])
                session, recheck, actor = await bind_voice(socket, meta)
                owner = session['human']
                if owner in analysis_active or len(analysis_active) >= 2:
                    owner = None
                    raise ValueError('Foreground analysis capacity occupied')
                analysis_active.add(owner)
                diagnostic['session_id'] = meta['id']
                async def open_worker():
                    return await Detector.open(detector_command, continuous=True)
                worker = await measured('worker_open', open_worker)
                await recheck()
                await send({'type': 'ready', 'id': meta['id'], 'analysis_only': True})
                async def receive():
                    nonlocal output_inbox
                    events = output_inbox = VoiceInbox(worker.receive)
                    try:
                        while True:
                            batch = await events.batch()
                            if any(value.get('type') not in ('activity', 'boundary') for value in batch):
                                raise DetectionUnavailable('Unexpected foreground analysis response')
                            await measured('output_authorization', actor)
                            for value in batch:
                                await measured('output_send', send, {'type': 'turn_activity' if value['type'] == 'activity' else 'boundary',
                                            'id': meta['id'], 'activity': value})
                                count = value.get('audio_bytes')
                                if type(count) is int and 0 <= count <= 300 * 32000:
                                    diagnostic['delivered_pcm_bytes'] = max(diagnostic['delivered_pcm_bytes'], count)
                    finally:
                        await events.close()
                reader = asyncio.create_task(receive())
                inbox = VoiceInbox(socket.receive, pcm=True)
                checked = time.monotonic()
                total = 0
                while True:
                    incoming = asyncio.create_task(inbox.batch())
                    done, _ = await asyncio.wait((incoming, reader), return_when=asyncio.FIRST_COMPLETED)
                    if reader in done:
                        incoming.cancel()
                        await reader
                    batch = await incoming
                    if batch[0]['type'] == 'websocket.disconnect':
                        diagnostic['outcome'] = 'client_disconnect'
                        break
                    await measured('input_authorization', actor)
                    if time.monotonic() - checked >= 15:
                        await measured('periodic_binding_recheck', recheck)
                        checked = time.monotonic()
                    closing = False
                    for message in batch:
                        if message.get('bytes') is not None:
                            pcm = message['bytes']
                            if total + len(pcm) > 300 * 32000:
                                raise ValueError('Foreground PCM exceeds session bounds')
                            total += len(pcm)
                            await measured('worker_feed', worker.feed, pcm)
                            diagnostic['fed_pcm_bytes'] = total
                        else:
                            value = json.loads(message.get('text', ''))
                            if value == {'type': 'close'}:
                                diagnostic['outcome'] = 'client_close'
                                closing = True
                                break
                            if not isinstance(value, dict) or set(value) != {'boundary'}:
                                raise ValueError('Unknown foreground control')
                            await worker.boundary(value['boundary'])
                    if closing:
                        break

        except (HTTPException, ValueError, OSError, UnicodeError, DetectionUnavailable,
                WebSocketDisconnect, TimeoutError) as error:
            diagnostic.update(outcome='unavailable', error_type=type(error).__name__)
            with suppress(Exception):
                await send({'type': 'unavailable', 'message': 'Voice activity unavailable. No recording was submitted.'})
        finally:
            try:
                for task in (reader, incoming):
                    if task is not None:
                        task.cancel()
                if inbox is not None:
                    await inbox.close()
                if worker is not None:
                    closing = asyncio.create_task(worker.close())
                    closing.add_done_callback(lambda task: None if task.cancelled() else task.exception())
                    await asyncio.shield(closing)
                for task in (reader, incoming):
                    if task is not None:
                        with suppress(asyncio.CancelledError, Exception):
                            await task
                with suppress(Exception):
                    await socket.close()
            finally:
                if owner is not None:
                    analysis_active.discard(owner)
                if 'session_id' in diagnostic:
                    diagnostic['elapsed_ms'] = round((time.monotonic() - started) * 1000, 2)
                    diagnostic['timing'] = {name: {key: round(value, 2) for key, value in item.items()}
                                            for name, item in intervals.items()}
                    if inbox is not None:
                        diagnostic.update(received_pcm_bytes=inbox.received_bytes,
                            input_messages=inbox.received_messages, input_peak_bytes=inbox.peak_bytes,
                            input_peak_messages=inbox.peak_messages)
                    if output_inbox is not None:
                        diagnostic.update(analyzed_pcm_bytes=output_inbox.analyzed_bytes,
                            worker_events=output_inbox.received_messages,
                            output_peak_messages=output_inbox.peak_messages,
                            onsets_observed=output_inbox.onsets, endpoints_observed=output_inbox.endpoints)
                    # One bounded metadata-only line under the existing web-unit
                    # journal. Never include PCM, text, request/identity headers,
                    # provider payloads, exception details or new persistence.
                    logging.getLogger('uvicorn.error').info('voice_activity_closed %s',
                        json.dumps(diagnostic, sort_keys=True))
    if selected.get('native_dialogue') is True:
        if (selected.get('provider')!='gemini' or mode!='prepared'
                or selected.get('native_activity_mode','manual')=='manual' and not detector_command):
            raise ValueError('Native dialogue requires prepared transcription and the selected acoustic detector')
        from .native_voice import install as install_native_voice
        install_native_voice(app,config,provider,origins,bind_voice,detector_command,analysis_active)
    return True
