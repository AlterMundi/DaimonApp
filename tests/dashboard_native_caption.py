"""Missing-caption PCM eligibility and cleanup, without providers or devices."""
import hashlib
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.native_caption import CaptionAudio
from dashboard.native_caption_recovery import CaptionRecovery
from dashboard.private_state import write_json


class Audio(unittest.TestCase):
    def begin(self, capture):
        source = str(uuid.uuid4())
        capture.begin(source)
        return source

    def test_missing_caption_preserves_exact_audio_and_parent_not_a_transcript(self):
        capture = CaptionAudio(); source = self.begin(capture)
        chunks = [b'\x01\x00' * 320, b'\x02\x00' * 160]
        for chunk in chunks: capture.append(chunk)
        capture.caption('')  # Empty provider metadata does not confirm language.
        evidence, pcm = capture.finish()
        self.assertEqual(bytes(pcm), b''.join(chunks))
        self.assertEqual(evidence, {'source':source, 'state':'missing_caption',
            'generated_bytes':960, 'pcm_sha256':hashlib.sha256(bytes(pcm)).hexdigest()})
        self.assertEqual(len(capture.audio), 0)
        with self.assertRaises(ValueError): capture.begin(source)
        with self.assertRaises(ValueError): capture.finish()
        pcm.clear()  # The finite recovery caller owns retirement after transfer.

    def test_text_before_or_after_audio_releases_media_but_keeps_exact_digest(self):
        for before in (True, False):
            capture = CaptionAudio(); self.begin(capture)
            if before: capture.caption('Known output')
            capture.append(b'\x03\x00' * 64)
            if not before: capture.caption('Known output')
            self.assertEqual(len(capture.audio), 0)
            capture.append(b'\x04\x00' * 64)
            evidence, pcm = capture.finish()
            self.assertIsNone(pcm)
            self.assertEqual(evidence['state'], 'caption_present')
            self.assertEqual(evidence['generated_bytes'], 256)
            self.assertEqual(evidence['pcm_sha256'], hashlib.sha256(b'\x03\x00'*64+b'\x04\x00'*64).hexdigest())

    def test_overlong_audio_is_unrecoverable_not_a_partial_clip(self):
        capture = CaptionAudio(); capture.max_clip_bytes = 8
        self.begin(capture); capture.append(b'\x00\x00' * 4)
        self.assertEqual(len(capture.audio), 8)
        capture.append(b'\x01\x00')
        evidence, pcm = capture.finish()
        self.assertIsNone(pcm)
        self.assertEqual(evidence['state'], 'audio_exceeds_asr_limit')
        self.assertEqual(evidence['generated_bytes'], 10)

    def test_dialogue_budget_survives_utterance_retirement_and_invalid_input(self):
        capture = CaptionAudio(); capture.max_dialogue_bytes = 8
        self.begin(capture); capture.append(b'\0' * 6); capture.caption('Text'); capture.finish()
        self.begin(capture)
        for invalid in (b'', b'x', bytearray(b'xx'), b'\0' * 4):
            with self.assertRaises(ValueError): capture.append(invalid)
        self.assertEqual(capture.total_bytes, 6)
        capture.append(b'\0\0'); capture.finish()
        self.begin(capture)
        with self.assertRaises(ValueError): capture.append(b'\0\0')

    def test_close_releases_incomplete_audio_and_prevents_reuse(self):
        capture = CaptionAudio(); self.begin(capture); capture.append(b'\0\0')
        capture.close(); capture.close()
        self.assertEqual(len(capture.audio), 0)
        for operation in (lambda: capture.begin(str(uuid.uuid4())),
                          lambda: capture.append(b'\0\0'),
                          lambda: capture.caption('Late text'), capture.finish):
            with self.assertRaises(ValueError): operation()


class Recovery(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.calls=self.root/'calls';self.reads=self.root/'reads'
        self.outputs=[];self.owned=set();self.slots=asyncio.Semaphore(2)
        self.dialogue=str(uuid.uuid4())
        code=('import json,sys,wave;'
            'open(sys.argv[1],"a").write("called\\n");'
            'audio=wave.open(sys.argv[-1],"rb");'
            'assert (audio.getframerate(),audio.getnchannels(),audio.getsampwidth())==(24000,1,2);'
            'print(json.dumps({"text":"Approximate assistant words.","final":True}))')
        self.voice={'transcription_command':[sys.executable,'-c',code,str(self.calls)],
            'completed_transcription_command':[sys.executable,'-c',code,str(self.reads)],
            'transcriber_label':'Synthetic fixture ASR','timeout_seconds':2}

    def tearDown(self):self.tmp.cleanup()

    async def authorize(self):pass

    async def deliver(self,value,result):self.outputs.append((value['source'],result))

    def recovery(self,**kwargs):
        return CaptionRecovery(self.root/'cache',self.voice,100,'scope','b'*64,
            kwargs.get('authorize',self.authorize),kwargs.get('deliver',self.deliver),self.slots,self.owned)

    def audio(self):
        source=str(uuid.uuid4());pcm=bytearray(b'\x10\x00'*160)
        return {'source':source,'state':'missing_caption','pcm_sha256':hashlib.sha256(pcm).hexdigest(),
            'generated_bytes':len(pcm)},pcm

    async def drain(self,recovery):
        if recovery.tasks:await asyncio.wait_for(asyncio.gather(*tuple(recovery.tasks)),5)

    async def test_actual_helper_subprocess_once_and_exact_completed_cleanup(self):
        r=self.recovery();evidence,pcm=self.audio()
        self.assertTrue(r.submit(self.dialogue,evidence,pcm));self.assertEqual(pcm,bytearray())
        await self.drain(r)
        self.assertEqual(self.calls.read_text(),'called\n');self.assertFalse(self.reads.exists())
        self.assertEqual(self.outputs,[(evidence['source'],{'text':'Approximate assistant words.','final':True})])
        state,media=r.paths(evidence['source']);self.assertFalse(media.exists())
        self.assertEqual(r.inspect(evidence['source'])['phase'],'delivered')
        self.assertNotIn('result',json.loads(state.read_text()),'Delivered receipts do not duplicate durable transcript text')
        again=self.recovery();await again.recover();await self.drain(again)
        self.assertEqual(self.calls.read_text(),'called\n');self.assertEqual(len(self.outputs),1)
        await r.close();await again.close();self.assertEqual(self.owned,set())

    async def test_uncertain_asr_uses_completed_reader_never_repeats_original(self):
        self.voice['transcription_command'][2]+=';sys.exit(1)'
        r=self.recovery();evidence,pcm=self.audio();r.submit(self.dialogue,evidence,pcm)
        await self.drain(r);self.assertEqual(r.inspect(evidence['source'])['phase'],'uncertain')
        self.assertEqual(self.outputs,[])
        again=self.recovery();await again.recover();await self.drain(again)
        self.assertEqual(self.calls.read_text(),'called\n');self.assertEqual(self.reads.read_text(),'called\n')
        self.assertEqual(len(self.outputs),1);self.assertEqual(again.inspect(evidence['source'])['phase'],'delivered')
        await r.close();await again.close()

    async def test_completed_result_survives_revocation_without_another_asr(self):
        checks=0
        async def revoke_after_provider():
            nonlocal checks
            checks+=1
            if checks>1:raise PermissionError('Synthetic revocation')
        r=self.recovery(authorize=revoke_after_provider);evidence,pcm=self.audio()
        r.submit(self.dialogue,evidence,pcm);await self.drain(r)
        self.assertEqual(r.inspect(evidence['source'])['phase'],'completed');self.assertEqual(self.outputs,[])
        again=self.recovery();await again.recover();await self.drain(again)
        self.assertEqual(len(self.outputs),1);self.assertEqual(self.calls.read_text(),'called\n')
        self.assertFalse(self.reads.exists(),'A retained completed interpretation needs no provider or reader process')
        await r.close();await again.close()

    async def test_queued_close_defers_prepared_job_and_releases_global_slots(self):
        self.slots=asyncio.Semaphore(0);r=self.recovery();evidence,pcm=self.audio()
        r.submit(self.dialogue,evidence,pcm)
        async with asyncio.timeout(2):
            while not r.paths(evidence['source'])[0].exists():await asyncio.sleep(.005)
        await asyncio.wait_for(r.close(),2)
        self.assertEqual(r.inspect(evidence['source'])['phase'],'prepared')
        self.assertFalse(self.calls.exists());self.assertEqual(self.owned,set())

    async def test_cancelled_disk_write_keeps_its_global_slot_until_actual_completion(self):
        r=self.recovery();started=threading.Event();release=threading.Event();actual=r.prepare
        def slow(*args):
            started.set()
            if not release.wait(3):raise ValueError('Synthetic disk writer was not released')
            return actual(*args)
        r.prepare=slow;evidence,pcm=self.audio();r.submit(self.dialogue,evidence,pcm)
        self.assertTrue(await asyncio.to_thread(started.wait,1))
        closing=asyncio.create_task(r.close())
        try:
            await asyncio.sleep(.02)
            self.assertIn(evidence['source'],self.owned)
            self.assertFalse(closing.done(),'Cancellation cannot hide a still-running disk operation')
        finally:release.set()
        await asyncio.wait_for(closing,2)
        self.assertEqual(self.owned,set());self.assertFalse(self.calls.exists())
        self.assertEqual(r.inspect(evidence['source'])['phase'],'prepared')

    async def test_explicit_open_expires_only_own_unfinished_generated_media(self):
        r=self.recovery();evidence,pcm=self.audio();value=r.prepare(self.dialogue,evidence,pcm)
        value['observed_at']=time.time()-2*r.media_seconds
        write_json(r.paths(evidence['source'])[0],value)
        await r.recover();await self.drain(r)
        self.assertEqual(r.inspect(evidence['source'])['phase'],'expired')
        self.assertFalse(r.paths(evidence['source'])[1].exists());self.assertFalse(self.calls.exists())
        await r.close()

    async def test_media_budget_and_global_task_bound_preserve_unknown_without_asr(self):
        r=self.recovery();r.max_cache_bytes=1024;evidence,pcm=self.audio()
        r.submit(self.dialogue,evidence,pcm);await self.drain(r)
        self.assertFalse(self.calls.exists());self.assertFalse(r.paths(evidence['source'])[1].exists())
        self.owned.update(str(uuid.uuid4()) for _ in range(r.max_owned_jobs))
        evidence,pcm=self.audio();self.assertFalse(r.submit(self.dialogue,evidence,pcm))
        self.assertEqual(pcm,bytearray());self.assertEqual(len(r.tasks),0)
        self.owned.clear();await r.close()

    async def test_digital_silence_never_initiates_asr_or_claims_words(self):
        r=self.recovery();source=str(uuid.uuid4());pcm=bytearray(320)
        evidence={'source':source,'state':'missing_caption','pcm_sha256':hashlib.sha256(pcm).hexdigest(),'generated_bytes':320}
        r.submit(self.dialogue,evidence,pcm);await self.drain(r)
        self.assertFalse(self.calls.exists());self.assertEqual(self.outputs,[])
        self.assertFalse(r.paths(source)[0].exists());await r.close()

    async def test_timeout_reaps_only_own_helper_group_and_retains_uncertainty(self):
        self.voice['transcription_command']=[sys.executable,'-c',
            'import sys,time,subprocess;child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]);'
            'open(sys.argv[1],"w").write(str(child.pid));time.sleep(30)',str(self.calls)]
        self.voice['timeout_seconds']=1
        r=self.recovery();evidence,pcm=self.audio();r.submit(self.dialogue,evidence,pcm)
        await self.drain(r)
        self.assertEqual(r.inspect(evidence['source'])['phase'],'uncertain')
        child=int(self.calls.read_text());status=Path('/proc')/str(child)/'stat'
        self.assertTrue(not status.exists() or status.read_text().split()[2]=='Z','Owned helper descendant must not keep running')
        self.assertEqual(self.outputs,[]);await r.close()


if __name__ == '__main__': unittest.main()
