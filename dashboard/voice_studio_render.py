"""One owned preview process using the existing speech CLI/cache and capacity."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
from anyio import CancelScope
from scripts import speech_render


class PreviewUnavailable(Exception):
    def __init__(self,message,*,attempted=True):
        super().__init__(message);self.attempted=attempted


class PreviewRunner:
    def __init__(self,capacity):
        self.capacity=capacity

    async def run(self,route,request,stop):
        config,_,ident=speech_render.render_plan(route,request)
        if config['provider']!='openai-live':raise PreviewUnavailable('Select the configured Live preview service',attempted=False)
        if stop.is_set():raise PreviewUnavailable('Preview cancelled before generation',attempted=False)
        if self.capacity.locked():raise PreviewUnavailable('Speech preparation is occupied',attempted=False)
        body=json.dumps({'route':config,'request':request},ensure_ascii=False).encode()
        if len(body)>speech_render.MAX_INPUT:raise PreviewUnavailable('Preview input exceeds its bound',attempted=False)
        async with self.capacity:
            if stop.is_set():raise PreviewUnavailable('Preview cancelled before generation',attempted=False)
            child=await asyncio.create_subprocess_exec(sys.executable,str(Path(speech_render.__file__).resolve()),'--preview-route',
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,start_new_session=True)
            completion=watcher=None;terminated=False
            def terminate():
                nonlocal terminated
                if terminated:return
                terminated=True
                try:os.killpg(child.pid,signal.SIGTERM)
                except ProcessLookupError:pass
            async def collect():
                child.stdin.write(body);await child.stdin.drain();child.stdin.close()
                output=bytearray()
                while part:=await child.stdout.read(4096):
                    output.extend(part)
                    if len(output)>65536:raise PreviewUnavailable('Preview process output exceeds its bound')
                code=await child.wait()
                if code:raise PreviewUnavailable('Preview outcome needs review; no automatic retry')
                return bytes(output)
            try:
                completion=asyncio.create_task(collect());watcher=asyncio.create_task(stop.wait())
                done,_=await asyncio.wait({completion,watcher},timeout=35,return_when=asyncio.FIRST_COMPLETED)
                if completion not in done:
                    terminate()
                    try:output=await asyncio.wait_for(asyncio.shield(completion),5)
                    except asyncio.TimeoutError:raise PreviewUnavailable('Preview cancellation or deadline needs review') from None
                else:output=await completion
            finally:
                # Cancellation releases only the task-owned process group. A
                # retained cache intent cannot become permission to regenerate.
                with CancelScope(shield=True):
                    terminate()
                    if child.returncode is None:
                        try:await asyncio.wait_for(child.wait(),5)
                        except asyncio.TimeoutError:pass
                    # A child can exit while a descendant still owns a socket.
                    # Its isolated group remains ours, never a native worker's.
                    try:os.killpg(child.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    await child.wait()
                    for task in (watcher,completion):
                        if task is not None:
                            if not task.done():task.cancel()
                            try:await task
                            except BaseException:pass
            result=json.loads(output)
            expected=Path(config['cache_root'])/ident/'audio.wav'
            if (not isinstance(result,dict) or result.get('schema')!='telecodex.speech-audio/v1'
                    or result.get('render_id')!=ident or result.get('audio_path')!=str(expected)
                    or result.get('voice')!=config['voice'] or result.get('language')!=config['language']
                    or result.get('text_sha256')!=hashlib.sha256(request['text'].encode()).hexdigest()):
                raise PreviewUnavailable('Preview receipt does not match its frozen source')
            data=speech_render.private_bytes(expected,speech_render.MAX_AUDIO)
            if (hashlib.sha256(data).hexdigest()!=result.get('audio_sha256')
                    or speech_render.audio_info(data)!=result.get('format') or result['format']['audio_millis']>30000):
                raise PreviewUnavailable('Preview audio does not match its receipt')
            return data,result
