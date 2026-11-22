"""Finite owner-scoped file-ASR recovery; never human ingress or work admission."""
import asyncio
from contextlib import suppress
import hashlib
import io
import json
import math
import os
import re
import signal
import stat
import struct
import time
import uuid
import wave

from scripts.speech_render import atomic, canonical, lock, private_bytes, sync_directory, RenderError
from .private_state import private_directory, read_json, write_json


class CaptionRecovery:
    max_jobs = 512
    max_cache_bytes = 32 * 1024 * 1024
    max_owned_jobs = 8
    max_audio_bytes = 120 * 48000
    media_seconds = 86400

    @staticmethod
    def configuration(voice):
        if not isinstance(voice, dict): raise ValueError('Select the existing file-ASR configuration')
        command = voice.get('transcription_command')
        completed = voice.get('completed_transcription_command')
        for value in (command, *([completed] if completed is not None else [])):
            if (not isinstance(value, list) or not 1 <= len(value) <= 32
                    or any(not isinstance(v, str) or not v or len(v) > 4096 or '\0' in v for v in value)):
                raise ValueError('Select the existing bounded file-ASR command')
        timeout = voice.get('timeout_seconds', 60)
        if type(timeout) is not int or not 1 <= timeout <= 120:
            raise ValueError('Select the existing file-ASR time bound')
        return command, completed, timeout

    def __init__(self, root, voice, human, scope, binding, authorize, deliver, slots, owned):
        command, completed, timeout = self.configuration(voice)
        self.root = private_directory(root)
        self.command, self.completed_command, self.timeout = command, completed, timeout
        self.options = hashlib.sha256(canonical(voice)).hexdigest()
        self.human, self.scope, self.binding = human, scope, binding
        self.authorize, self.deliver, self.slots, self.owned = authorize, deliver, slots, owned
        self.tasks = set(); self.running = set(); self.seen = set(); self.closing = False
        self.counts = {'submitted': 0, 'delivered': 0, 'uncertain': 0, 'deferred': 0}
        self.disk_slot = asyncio.Semaphore(1)

    async def disk(self, function, *args):
        # Cancellation never releases this slot while its filesystem thread runs.
        await self.disk_slot.acquire()
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        def done(value):
            self.disk_slot.release()
            if not value.cancelled(): value.exception()
        task.add_done_callback(done)
        try: return await asyncio.shield(task)
        except asyncio.CancelledError:
            # The job keeps its global slot and immutable PCM until the disk
            # operation really finishes, including during scoped service close.
            with suppress(Exception): await asyncio.shield(task)
            raise

    def paths(self, source):
        if not isinstance(source, str) or str(uuid.UUID(source)) != source:
            raise ValueError('Select one retained assistant source')
        return self.root / (source + '.json'), self.root / (source + '.wav')

    def inspect(self, source):
        state, _ = self.paths(source)
        value = read_json(state)
        if (value.get('schema') != 'telecodex.assistant-caption-recovery/v1'
                or value.get('source') != source
                or (value.get('human'), value.get('scope'), value.get('binding'))
                    != (self.human, self.scope, self.binding)
                or value.get('options_sha256') != self.options
                or not isinstance(value.get('dialogue'),str)
                or str(uuid.UUID(value['dialogue'])) != value['dialogue']
                or any(not isinstance(value.get(k),str) or not re.fullmatch('[a-f0-9]{64}',value[k])
                    for k in ('pcm_sha256','media_sha256'))
                or type(value.get('generated_bytes')) is not int
                or not 0 < value['generated_bytes'] <= self.max_audio_bytes or value['generated_bytes'] % 2
                or type(value.get('observed_at')) not in (int,float)
                or not math.isfinite(value['observed_at']) or value['observed_at'] <= 0
                or value.get('phase') not in ('prepared', 'running', 'uncertain', 'completed', 'delivered', 'expired')):
            raise ValueError('Caption recovery identity changed')
        return value

    def prepare(self, dialogue, evidence, pcm):
        source = evidence['source']; state, media = self.paths(source)
        if (str(uuid.UUID(dialogue)) != dialogue or evidence.get('state') != 'missing_caption'
                or not isinstance(pcm, (bytes, bytearray)) or not 0 < len(pcm) <= self.max_audio_bytes
                or len(pcm) % 2 or len(pcm) != evidence.get('generated_bytes')
                or hashlib.sha256(pcm).hexdigest() != evidence.get('pcm_sha256')):
            raise ValueError('Select exact bounded generated audio')
        if not any(abs(sample[0]) >= 4 for sample in struct.iter_unpack('<h',pcm)):
            raise ValueError('No audible generated signal; do not ask ASR to invent words')
        with lock(self.root / '.capacity.lock'):
            if state.exists() or state.is_symlink():
                old = self.inspect(source)
                if any(old.get(k) != evidence.get(k) for k in ('pcm_sha256', 'generated_bytes')) or old['dialogue'] != dialogue:
                    raise ValueError('Caption recovery audio changed')
                return old
            files = list(self.root.iterdir()); total = 0; jobs = 0
            for path in files:
                info = path.lstat()
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077):
                    raise ValueError('Unsafe caption recovery cache')
                total += info.st_size; jobs += path.suffix == '.json'
                if path.suffix == '.json' and read_json(path).get('phase') not in ('delivered','expired'):
                    total += max(0,65536-info.st_size)
            if jobs >= self.max_jobs or total + len(pcm) + 65536 > self.max_cache_bytes:
                raise ValueError('Caption recovery cache reached its bound')
            data = io.BytesIO()
            with wave.open(data, 'wb') as output:
                output.setnchannels(1); output.setsampwidth(2); output.setframerate(24000)
                output.writeframes(pcm)
            raw = data.getvalue()
            # A leftover media file is not permission to replace or retranscribe it.
            if media.exists() or media.is_symlink():
                raise ValueError('Inspect orphaned recovery media before reuse')
            atomic(media, raw)
            value = {'schema': 'telecodex.assistant-caption-recovery/v1',
                'source': source, 'dialogue': dialogue, 'human': self.human,
                'scope': self.scope, 'binding': self.binding, 'options_sha256': self.options,
                'pcm_sha256': evidence['pcm_sha256'], 'generated_bytes': len(pcm),
                'media_sha256': hashlib.sha256(raw).hexdigest(), 'observed_at': time.time(), 'phase': 'prepared'}
            write_json(state, value)
            return value

    def retire(self, value):
        _, media = self.paths(value['source'])
        if media.exists() or media.is_symlink():
            try: raw = private_bytes(media, self.max_audio_bytes + 4096)
            except FileNotFoundError: return
            if hashlib.sha256(raw).hexdigest() != value['media_sha256']:
                raise ValueError('Caption recovery media changed before retirement')
            media.unlink(missing_ok=True)
            sync_directory(self.root)

    def pending(self):
        # Only an explicit authorized avatar open invokes this finite sweep.
        values = []
        files = sorted(self.root.glob('*.json'))
        if len(files) > self.max_jobs: raise ValueError('Caption recovery job bound exceeded')
        for path in files:
            try: value = self.inspect(path.stem)
            except (ValueError, OSError): continue  # Another actor/binding is not ours.
            if value['phase'] == 'delivered':
                self.retire(value)  # Complete interrupted cleanup without ASR replay.
                continue
            if value['phase'] == 'expired': continue
            if time.time() - value['observed_at'] > self.media_seconds and value['phase'] != 'completed':
                # Never delete media held by another finite owning operation.
                try:
                    with lock(self.root / (value['source'] + '.lock')):
                        value = self.inspect(value['source'])
                        if value['phase'] == 'completed': values.append(value); continue
                        self.retire(value); value['phase'] = 'expired'; write_json(path, value)
                except RenderError: pass
                continue
            values.append(value)
        return values[:self.max_owned_jobs]

    def submit(self, dialogue, evidence, pcm):
        source = evidence['source']
        if self.closing or source in self.seen or source in self.owned or len(self.owned) >= self.max_owned_jobs or len(self.seen) >= self.max_owned_jobs:
            pcm.clear(); self.counts['deferred'] += 1; return False
        self.seen.add(source)
        captured = bytes(pcm); pcm.clear()
        async def operation():
            try:
                value = await self.disk(self.prepare, dialogue, evidence, captured)
                await self.run(value)
            except Exception: self.counts['deferred'] += 1
        self.launch(source, operation()); self.counts['submitted'] += 1
        return True

    def launch(self, source, operation):
        self.owned.add(source)
        task = asyncio.create_task(operation, name='native-caption-recovery')
        self.tasks.add(task)
        def done(value):
            self.tasks.discard(value); self.owned.discard(source)
            if not value.cancelled(): value.exception()
        task.add_done_callback(done)

    async def recover(self):
        await self.authorize()
        try: values = await self.disk(self.pending)
        except (OSError, ValueError, RenderError):
            self.counts['deferred'] += 1; return
        for value in values:
            if (value['source'] in self.seen or value['source'] in self.owned
                    or len(self.owned) >= self.max_owned_jobs or len(self.seen) >= self.max_owned_jobs): continue
            self.seen.add(value['source']); self.launch(value['source'], self.run(value))

    @staticmethod
    def result(value):
        if (not isinstance(value, dict) or value.get('final') is not True
                or value.get('partial') is True or not isinstance(value.get('text'), str)
                or not value['text'].strip() or len(value['text'].encode()) > 16000 or '\0' in value['text']):
            raise ValueError('No complete bounded ASR draft')
        if 'streaming_model' in value and value['streaming_model'] not in ('gemini-3.8-live','gemini-3.5-transcribe-live','qwen-audio-3.0-realtime-plus'):
            raise ValueError('ASR result provider provenance is unsupported')
        return {k: value[k] for k in ('text', 'final', 'streaming_model') if k in value}

    async def execute(self, command, media):
        return await execute_asr(command,media,self.timeout)

    async def run(self, initial):
        source = initial['source']; state, media = self.paths(source)
        try:
            async with self.slots:
                self.running.add(asyncio.current_task())
                with lock(self.root / (source + '.lock')):
                    value = await self.disk(self.inspect, source)
                    if value['phase'] in ('delivered', 'expired'): return
                    if value['phase'] != 'completed':
                        raw = await self.disk(private_bytes, media, self.max_audio_bytes + 4096)
                        if hashlib.sha256(raw).hexdigest() != value['media_sha256']:
                            raise ValueError('Caption recovery media changed')
                        del raw
                        await self.authorize()
                        if self.closing: return  # Queued jobs stay prepared; no new ASR on close.
                        command = self.command if value['phase'] == 'prepared' else self.completed_command
                        if command is None: return
                        # running after a released lock means an interrupted owner,
                        # not permission to repeat its possible provider operation.
                        value['phase'] = 'uncertain'
                        await self.disk(write_json, state, value)
                        try: result = await self.execute(command, media)
                        except (OSError, ValueError, TimeoutError):
                            self.counts['uncertain'] += 1; return
                        value.update(phase='completed', result=result)
                        await self.disk(write_json, state, value)
                    await self.authorize()
                    await self.deliver(value, self.result(value['result']))
                    value['phase'] = 'delivered'; value.pop('result', None)
                    await self.disk(write_json, state, value)
                    await self.disk(self.retire, value)
                    self.counts['delivered'] += 1
        except Exception: self.counts['deferred'] += 1
        finally: self.running.discard(asyncio.current_task())

    async def close(self):
        self.closing = True
        tasks = tuple(self.tasks)
        if not tasks: return
        for task in tasks:
            if task not in self.running: task.cancel()
        done, pending = await asyncio.wait(tasks, timeout=self.timeout + 25)
        for task in pending: task.cancel()
        if pending: await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            if not task.cancelled(): task.exception()


async def execute_asr(command, media, timeout):
    process = None
    opening = asyncio.create_task(asyncio.create_subprocess_exec(*command, str(media),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, start_new_session=True))
    try:
        async with asyncio.timeout(timeout):
            process = await asyncio.shield(opening)
            raw = bytearray()
            while True:
                chunk = await process.stdout.read(min(4096, 32769 - len(raw)))
                if not chunk: break
                raw.extend(chunk)
                if len(raw) > 32768: raise ValueError('ASR result exceeds its bound')
            if await process.wait() != 0: raise ValueError('ASR outcome unconfirmed')
            return CaptionRecovery.result(json.loads(raw))
    finally:
        # The child group belongs solely to this operation, never native work.
        if process is None:
            with suppress(Exception): process = await asyncio.shield(opening)
        if process is not None and process.returncode is None:
            with suppress(ProcessLookupError): os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
