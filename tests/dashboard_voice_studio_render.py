"""Actual isolated CLI/cache hit and owned process cancellation; zero providers."""
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import wave
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.voice_studio_render import PreviewRunner,PreviewUnavailable
from scripts import speech_render as speech


class Runner(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.key=self.root/'key';self.key.write_text('sk-synthetic-not-used');self.key.chmod(0o600)
        self.route={'schema':speech.SCHEMA,'provider':'openai-live','model':'gpt-live-1','voice':'cedar','language':'es-AR',
            'cache_root':str(self.root/'cache'),'credential_file':str(self.key),'timeout_seconds':30}
        self.request={'scope':'synthetic-preview','text':'Dale, Compai.'};self.runner=PreviewRunner(asyncio.Semaphore(1))
    def cache(self):
        config,_,ident=speech.render_plan(self.route,self.request);job=speech.directory(speech.directory(config['cache_root'])/ident)
        buffer=io.BytesIO()
        with wave.open(buffer,'wb') as out:out.setnchannels(1);out.setsampwidth(2);out.setframerate(24000);out.writeframes(b'\0\0'*2400)
        data=buffer.getvalue();speech.atomic(job/'audio.wav',data)
        state={'schema':'telecodex.speech-render/v1','identity_sha256':ident,'phase':'rendered','provider':'openai-live',
            'voice':'cedar','language':'es-AR','text_sha256':speech.sha(self.request['text'].encode()),
            'created_at':__import__('time').time(),'last_used_at':__import__('time').time(),'generation':1,
            'audio_sha256':speech.sha(data),'format':speech.audio_info(data),'audio_bytes':len(data),
            'provider_receipt':{'stage':'session_closed','finalized':True,'usage':{'seconds':2}}}
        speech.atomic(job/'state.json',speech.canonical(state));return data
    async def test_real_cli_reuses_exact_existing_cache_without_provider(self):
        data=self.cache();actual,result=await self.runner.run(self.route,self.request,asyncio.Event())
        self.assertEqual(actual,data);self.assertTrue(result['cache_hit'])
        self.assertEqual(result['audio_sha256'],hashlib.sha256(data).hexdigest())
    async def test_cancel_before_spawn_and_capacity_refusal_have_no_attempt(self):
        stop=asyncio.Event();stop.set()
        with self.assertRaises(PreviewUnavailable) as failure:await self.runner.run(self.route,self.request,stop)
        self.assertFalse(failure.exception.attempted)
        async with self.runner.capacity:
            with self.assertRaises(PreviewUnavailable) as failure:await self.runner.run(self.route,self.request,asyncio.Event())
            self.assertFalse(failure.exception.attempted)
    async def test_cancel_terminates_only_its_actual_process_group(self):
        marker=self.root/'owned.pid';term=self.root/'term';script=self.root/'fixture.py'
        script.write_text('import os,signal,time,pathlib,sys\n'+
            'pathlib.Path('+repr(str(marker))+').write_text(str(os.getpid()))\n'+
            'def done(*args):\n pathlib.Path('+repr(str(term))+').write_text("cancelled")\n sys.exit(1)\n'+
            'signal.signal(signal.SIGTERM,done)\ntime.sleep(20)\n')
        spawn=asyncio.create_subprocess_exec;children=[]
        async def fixture(*args,**kwargs):
            child=await spawn(sys.executable,str(script),**kwargs);children.append(child);return child
        stop=asyncio.Event()
        sentinel=await spawn(sys.executable,'-c','import time;time.sleep(20)',start_new_session=True)
        try:
            with patch('dashboard.voice_studio_render.asyncio.create_subprocess_exec',side_effect=fixture):
                task=asyncio.create_task(self.runner.run(self.route,self.request,stop))
                async with asyncio.timeout(3):
                    while not marker.exists():await asyncio.sleep(.01)
                stop.set()
                with self.assertRaises(PreviewUnavailable):await asyncio.wait_for(task,7)
            self.assertEqual(len(children),1);self.assertIsNotNone(children[0].returncode)
            self.assertEqual(term.read_text(),'cancelled');self.assertIsNone(sentinel.returncode)
            self.assertFalse(self.runner.capacity.locked())
        finally:
            if sentinel.returncode is None:sentinel.kill()
            await sentinel.wait()

if __name__=='__main__':unittest.main()
