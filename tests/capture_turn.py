"""Speech-gated, bounded turn analysis; no models, provider or native input."""
import sys
import asyncio
from pathlib import Path
import tempfile
import unittest
import io
import json
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.capture_turn import Activity, TurnEndUnavailable, analysis_budget, main, SCHEMA, VAD_SHA256, MODEL_SHA256
from dashboard.turn_detection import analyze_capture, DetectionUnavailable, Detector


class CaptureTurn(unittest.TestCase):
    def test_default_and_extended_analysis_budgets_are_finite_and_strict(self):
        self.assertEqual(analysis_budget(),(120,30,60,145))
        self.assertEqual(analysis_budget(continuous=True),(300,90,150,305))
        self.assertEqual(analysis_budget(continuous=True,session_seconds=300),(300,90,150,305))
        self.assertEqual(analysis_budget(continuous=True,session_seconds=600),(600,180,300,650))
        self.assertEqual(analysis_budget(continuous=True,session_seconds=1800),(1800,540,900,1850))
        for seconds in (True,300.0,'600',299,1801):
            with self.subTest(seconds=seconds),self.assertRaises(ValueError):
                Activity('/missing-vad','/missing-turn',continuous=True,session_seconds=seconds)
        with self.assertRaises(ValueError):analysis_budget(session_seconds=600)

    def test_cli_acknowledges_extended_budget_and_preserves_default_ready(self):
        for seconds in (None,300,600,1800):
            argv=['capture_turn','--vad-model','unused','--turn-model','unused','--continuous']
            if seconds is not None:argv+=['--session-seconds',str(seconds)]
            output=io.StringIO()
            with patch('sys.argv',argv),patch('scripts.capture_turn.Activity') as activity,\
                    patch('scripts.capture_turn.resource.setrlimit') as cpu,\
                    patch('scripts.capture_turn.signal.alarm') as alarm,\
                    patch('sys.stdin',type('Input',(),{'buffer':io.BytesIO()})()),patch('sys.stdout',output):
                self.assertEqual(main(),0)
            expected={'schema':SCHEMA,'type':'ready','vad_sha256':VAD_SHA256,
                      'turn_sha256':MODEL_SHA256,'continuous':True}
            if seconds and seconds>300:expected['session_seconds']=seconds
            self.assertEqual(json.loads(output.getvalue()),expected)
            budget=analysis_budget(continuous=True,session_seconds=seconds)
            cpu.assert_called_once_with(__import__('resource').RLIMIT_CPU,(budget[2],budget[2]+5))
            alarm.assert_called_once_with(budget[3])
            self.assertEqual(activity.call_args.kwargs['session_seconds'],seconds)

    def test_six_hundred_seconds_keeps_only_eight_second_tail_and_stops_at_bound(self):
        value=self.analyzer()
        seconds,value.max_analyses,_,_=analysis_budget(continuous=True,session_seconds=600)
        value.max_bytes=seconds*32000
        for _ in range(seconds):
            value.feed(bytes(32000))
            self.assertLessEqual(len(value.tail),256000)
            self.assertLess(len(value.pending),1024)
        self.assertEqual(value.bytes,600*32000)
        with self.assertRaises(ValueError):value.feed(b'\0\0')
        self.assertEqual(self.scored,[],'Quiet capture cannot consume semantic analyses')
        value.bytes=0;value.speech_seen=True
        value.generation=value.confirmed_generation=1;value.analyses=180
        with self.assertRaises(TurnEndUnavailable):value.feed(bytes(1024))

    def analyzer(self):
        value = object.__new__(Activity)
        value.pending = bytearray(); value.tail = bytearray()
        value.bytes = value.frames = value.generation = value.positive = value.quiet = value.analyses = 0
        value.speaking = value.speech_seen = False; value.scored_generation = value.confirmed_generation = 0
        value.pending_onset = False
        value.max_bytes=120*32000;value.max_analyses=30;value.endpoints=[]
        value.silence_end_millis=0;value.endpoint_generation=0
        self.probability = 0
        value._probability = lambda _: self.probability
        self.scored = []
        class Turn:
            def predict(_, pcm, *, speech_present):
                self.assertTrue(speech_present);self.scored.append(pcm)
                return {'candidate_complete': True, 'probability': .9}
        value.turn = Turn()
        return value

    def test_silence_never_scores_and_pending_frames_are_carried(self):
        value = self.analyzer()
        for _ in range(10): result = value.feed(b'\0'*3200)
        self.assertFalse(result['speech_seen']);self.assertNotIn('endpoint',result)
        self.assertEqual(value.frames,31);self.assertEqual(len(value.pending),256)
        self.assertEqual(self.scored,[])

    def test_speech_then_quiet_scores_once_per_generation(self):
        value = self.analyzer();self.probability=.8
        self.assertTrue(value.feed(b'\1\0'*1536)['speech_seen'])
        self.probability=0
        self.assertNotIn('endpoint', value.feed(b'\0'*6144))
        result=value.feed(b'\0'*1024)
        self.assertEqual(result['endpoint']['generation'],1)
        self.assertEqual(result['endpoint']['audio_bytes'],10240)
        self.assertEqual(result['endpoint']['authority'],'analysis_only')
        self.assertNotIn('endpoint',value.feed(b'\0'*8192));self.assertEqual(len(self.scored),1)
        self.probability=.8;value.feed(b'\0'*3072);self.probability=0
        self.assertEqual(value.feed(b'\0'*7168)['endpoint']['generation'],2)

    def test_native_silence_closes_a_phrase_rejected_by_the_semantic_score(self):
        value=self.analyzer();value.silence_end_millis=1600
        value.turn.predict=lambda *a,**k:{'candidate_complete':False,'probability':.1}
        self.probability=.8;value.feed(b'\0'*3072);self.probability=0
        self.assertNotIn('endpoint',value.feed(b'\0'*32000))
        self.assertNotIn('endpoint',value.feed(b'\0'*16000))
        result=value.feed(b'\0'*4096)
        self.assertEqual(result['endpoint']['authority'],'acoustic_silence')
        self.assertEqual(result['endpoint']['silence_millis'],1600)
        self.assertNotIn('probability',result['endpoint'],'Acoustic silence is not a semantic probability')
        self.assertNotIn('endpoint',value.feed(b'\0'*32000))
        self.assertEqual(value.boundary(1,result['audio_bytes'])['type'],'boundary')
        legacy=self.analyzer();legacy.turn=value.turn;self.probability=.8
        legacy.feed(b'\0'*3072);self.probability=0
        for _ in range(4):self.assertNotIn('endpoint',legacy.feed(b'\0'*32000))

    def test_short_noise_never_establishes_speech_and_bounds_are_enforced(self):
        value=self.analyzer();self.probability=.9;value.feed(b'\0'*2048)
        self.probability=0;self.assertNotIn('endpoint',value.feed(b'\0'*8192))
        self.assertEqual(self.scored,[])
        for data in [b'',b'\0',b'\0'*32002,'not PCM']:
            with self.assertRaises(ValueError):value.feed(data)
        value.bytes=120*32000
        with self.assertRaises(ValueError):value.feed(b'\0'*1024)
        value.bytes=0;value.speech_seen=True;value.generation=value.confirmed_generation=100;value.analyses=30
        with self.assertRaises(TurnEndUnavailable):value.feed(b'\0'*1024)

    def test_unconfirmed_noise_cannot_orphan_an_open_confirmed_phrase(self):
        for spike_frames in (1,2):
            with self.subTest(spike_frames=spike_frames):
                value=self.analyzer();value.silence_end_millis=1600
                value.turn.predict=lambda *a,**k:{'candidate_complete':False,'probability':.1}
                self.probability=.9
                onset=value.feed(b'\0'*(3*1024))['onset']
                self.probability=0
                self.assertNotIn('endpoint',value.feed(b'\0'*(7*1024)))
                self.probability=.9
                self.assertNotIn('onset',value.feed(b'\0'*(spike_frames*1024)))
                self.probability=0
                self.assertNotIn('endpoint',value.feed(b'\0'*(25*1024)))
                result=value.feed(b'\0'*(25*1024))
                self.assertIn('endpoint',result,'Short unconfirmed noise must not prevent the open phrase ending')
                self.assertEqual(result['endpoint']['generation'],onset['generation'])
                self.assertEqual(result['endpoint']['authority'],'acoustic_silence')
                self.assertGreaterEqual(result['endpoint']['silence_millis'],1600)
                value.boundary(onset['generation'],result['audio_bytes'])
                self.assertNotIn('endpoint',value.feed(b'\0'*(25*1024)))
                self.probability=.9
                next_onset=value.feed(b'\0'*(3*1024))['onset']
                self.assertEqual(next_onset['generation'],onset['generation']+1)

    def test_confirmed_voice_after_a_noise_candidate_still_reopens_the_generation(self):
        value=self.analyzer();value.silence_end_millis=1600
        def incomplete(pcm,**kwargs):
            self.scored.append(pcm)
            return {'candidate_complete':False,'probability':.1}
        value.turn.predict=incomplete
        def frames(probability,count):
            self.probability=probability
            # Preserve the candidate across incomplete512-sample frame reads.
            results=[]
            for _ in range(count*2):results.append(value.feed(b'\0'*512))
            return results
        first=next(r['onset'] for r in frames(.9,3) if 'onset' in r)
        frames(0,7);frames(.9,1);frames(0,3)
        second=next(r['onset'] for r in frames(.9,3) if 'onset' in r)
        self.assertEqual(second['generation'],first['generation']+1)
        endpoints=[r['endpoint'] for r in frames(0,50) if 'endpoint' in r]
        self.assertEqual(len(endpoints),1)
        self.assertEqual(endpoints[0]['generation'],second['generation'])
        self.assertEqual(len(self.scored),2,'Actual resumed voice receives its own completion decision')
        value.boundary(second['generation'],endpoints[0]['audio_bytes'])
        self.assertFalse(any('onset' in r or 'endpoint' in r for r in frames(.9,2)+frames(0,50)))

    def test_repeated_unconfirmed_blips_do_not_hold_the_speech_floor(self):
        for spike_frames,quiet_frames in ((1,2),(2,5)):
            with self.subTest(spike_frames=spike_frames,quiet_frames=quiet_frames):
                value=self.analyzer();value.silence_end_millis=1600
                value.turn.predict=lambda *a,**k:{'candidate_complete':False,'probability':.1}
                self.probability=.9;onset=value.feed(b'\0'*3072)['onset']
                self.probability=0;value.feed(b'\0'*(7*1024))
                events=[]
                # No later run reaches the same three-frame speech requirement.
                for _ in range(20):
                    self.probability=0;events.append(value.feed(b'\0'*(quiet_frames*1024)))
                    self.probability=.9;events.append(value.feed(b'\0'*(spike_frames*1024)))
                self.assertFalse(any('onset' in event for event in events))
                endpoints=[event['endpoint'] for event in events if 'endpoint' in event]
                self.assertEqual(len(endpoints),1,'Unconfirmed blips must not indefinitely own the speech floor')
                self.assertEqual(endpoints[0]['generation'],onset['generation'])
                self.assertEqual(endpoints[0]['authority'],'acoustic_silence')
                self.assertLessEqual(endpoints[0]['silence_millis'],1600+quiet_frames*32)

    def test_unvoiced_frames_within_confirmed_speech_keep_the_existing_continuation(self):
        value=self.analyzer();value.silence_end_millis=1600
        value.turn.predict=lambda *a,**k:{'candidate_complete':False,'probability':.1}
        self.probability=.9;value.feed(b'\0'*3072)
        for _ in range(30):
            self.probability=0;quiet=value.feed(b'\0'*1024)
            self.probability=.9;voiced=value.feed(b'\0'*2048)
            self.assertNotIn('endpoint',quiet)
            self.assertNotIn('endpoint',voiced)
            self.assertTrue(voiced['speaking'],'Debouncing a new onset must not cut continuing voice')

    def test_phrase_end_waits_for_a_provisional_voice_candidate_at_the_deadline(self):
        value=self.analyzer();value.silence_end_millis=1600
        value.turn.predict=lambda *a,**k:{'candidate_complete':False,'probability':.1}
        self.probability=.9;value.feed(b'\0'*3072)
        self.probability=0
        value.feed(b'\0'*(24*1024));value.feed(b'\0'*(25*1024))
        self.probability=.9
        self.assertNotIn('endpoint',value.feed(b'\0'*(2*1024)))
        resumed=value.feed(b'\0'*1024)
        self.assertEqual(resumed['onset']['generation'],2)
        self.assertNotIn('endpoint',resumed,'Do not split actual resumed speech at the inactivity deadline')
        self.probability=0
        value.feed(b'\0'*(25*1024));ended=value.feed(b'\0'*(25*1024))
        self.assertEqual(ended['endpoint']['generation'],2)

    def test_startup_backfill_defers_scoring_until_the_current_tail(self):
        value=self.analyzer();self.probability=.8;value.feed(b'\0'*3072,analyze=False)
        self.probability=0
        self.assertNotIn('endpoint',value.feed(b'\0'*8192,analyze=False))
        self.assertEqual(self.scored,[])
        result=value.feed(b'\0'*1024)
        self.assertEqual(result['endpoint']['audio_bytes'],12288)
        self.assertEqual(len(self.scored),1)
        with self.assertRaises(ValueError):value.feed(b'\0'*1024,analyze='yes')

    def test_new_voice_generation_needs_its_own_speech_confirmation(self):
        value=self.analyzer();self.probability=.8
        onset=value.feed(b'\0'*3072)['onset']
        self.assertEqual(onset,{'generation':1,'audio_bytes':3072})
        self.probability=0;value.feed(b'\0'*8192)
        self.probability=.8
        short=value.feed(b'\0'*1024)
        self.assertNotIn('onset',short)
        self.probability=0
        self.assertNotIn('endpoint',value.feed(b'\0'*8192))
        self.assertEqual(len(self.scored),1,'A prior real voice cannot authorize scoring later short noise')

    def test_foreground_boundary_keeps_later_audio_and_warm_state(self):
        value=self.analyzer();self.probability=.8;value.feed(b'\0'*3072)
        self.probability=0;endpoint=value.feed(b'\0'*8192)['endpoint']
        value.feed(b'\1\0'*512)
        state=(value.frames,value.bytes,value.generation,value.speech_seen)
        before=bytes(value.tail)
        self.assertEqual(value.boundary(endpoint['generation'],endpoint['audio_bytes'])['type'],'boundary')
        self.assertEqual(bytes(value.tail),b'\1\0'*512)
        self.assertEqual((value.frames,value.bytes,value.generation,value.speech_seen),state)
        self.assertNotEqual(bytes(value.tail),before)
        with self.assertRaises(ValueError):value.boundary(endpoint['generation'],endpoint['audio_bytes'])
        with self.assertRaises(ValueError):value.boundary(True,endpoint['audio_bytes'])
        self.assertEqual(len(value.tail),1024)

    def test_two_pending_boundaries_retire_only_the_acknowledged_prefix(self):
        value=self.analyzer();self.probability=.8;value.feed(b'\0'*3072)
        self.probability=0;first=value.feed(b'\0'*8192)['endpoint']
        self.probability=.8;value.feed(b'\1\0'*1536)
        self.probability=0;second=value.feed(b'\0'*8192)['endpoint']
        before=bytes(value.tail);offset=first['audio_bytes']
        value.boundary(first['generation'],offset)
        self.assertEqual(bytes(value.tail),before[offset:])
        value.boundary(second['generation'],second['audio_bytes'])
        self.assertEqual(bytes(value.tail),b'');self.assertEqual(value.endpoints,[])

    def test_wrong_model_is_rejected_before_optional_imports(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'wrong.onnx';path.write_bytes(b'wrong')
            with self.assertRaises(ValueError):Activity(path,path)

class CaptureAnalysisLifecycle(unittest.IsolatedAsyncioTestCase):
    def worker(self):
        class Worker:
            def __init__(self):self.feeds=[];self.closed=False;self.queue=asyncio.Queue()
            async def feed(self,pcm,*,defer=False):
                self.feeds.append((len(pcm),defer));await self.queue.put({'type':'activity','audio_bytes':sum(n for n,_ in self.feeds)})
            async def receive(self):return await self.queue.get()
            async def close(self):self.closed=True
        return Worker()
    async def test_late_open_backfills_once_without_obsolete_endpoint_scores(self):
        worker=self.worker();pcm=bytearray(b'\0'*64000);changed=asyncio.Event();observed=[];complete=asyncio.Event()
        async def open_worker():return worker
        async def observe(value):
            observed.append(value)
            if value['audio_bytes']==64000:complete.set()
        task=asyncio.create_task(analyze_capture(open_worker,pcm,changed,observe))
        await asyncio.wait_for(complete.wait(),1)
        self.assertEqual(worker.feeds,[(32000,True),(32000,False)])
        pcm.extend(b'\0'*1024);changed.set();await asyncio.sleep(.01)
        self.assertEqual(worker.feeds[-1],(1024,False))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(worker.closed)
    async def test_late_first_join_keeps_current_tail_and_absolute_endpoint_offsets(self):
        worker=self.worker();pcm=bytearray(b'\0'*320000);changed=asyncio.Event();observed=[];complete=asyncio.Event()
        async def open_worker():return worker
        async def observe(value):
            observed.append(value)
            if value['audio_bytes']==len(pcm):complete.set()
        task=asyncio.create_task(analyze_capture(open_worker,pcm,changed,observe))
        await asyncio.wait_for(complete.wait(),1)
        self.assertEqual(sum(n for n,_ in worker.feeds),256000)
        self.assertEqual(bytes(pcm),b'\0'*320000)
        await worker.queue.put({'type':'activity','audio_bytes':256000,
            'endpoint':{'audio_bytes':256000,'generation':1}})
        await asyncio.sleep(.01)
        self.assertEqual(observed[-1]['endpoint']['audio_bytes'],320000)
        pcm.extend(b'\0'*1024);changed.set();await asyncio.sleep(.01)
        self.assertEqual(observed[-1]['audio_bytes'],321024)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(worker.closed)
    async def test_steady_state_lag_failure_closes_only_the_analysis_worker(self):
        worker=self.worker()
        async def open_worker():return worker
        current=asyncio.Event()
        async def observe(_):current.set()
        pcm=bytearray(b'\0'*1024);changed=asyncio.Event()
        task=asyncio.create_task(analyze_capture(open_worker,pcm,changed,observe))
        await asyncio.wait_for(current.wait(),1)
        pcm.extend(b'\0'*256002);changed.set()
        with self.assertRaisesRegex(DetectionUnavailable,'fell behind'):
            await task
        self.assertTrue(worker.closed);self.assertEqual(worker.feeds,[(1024,False)])

class DetectorBudget(unittest.IsolatedAsyncioTestCase):
    async def worker(self,seconds,*,acknowledge=True):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name);script=root/'worker.py';args=root/'args.json'
        ready={'schema':SCHEMA,'type':'ready','vad_sha256':VAD_SHA256,
               'turn_sha256':MODEL_SHA256,'continuous':True}
        if acknowledge and seconds and seconds>300:ready['session_seconds']=seconds
        script.write_text('import json,sys\nfrom pathlib import Path\n'
                          f'Path({str(args)!r}).write_text(json.dumps(sys.argv[1:]))\n'
                          f'print({json.dumps(ready)!r},flush=True)\n'
                          'sys.stdin.buffer.read()\n')
        return [sys.executable,str(script)],args

    async def test_selected_extended_worker_acknowledges_budget_and_reaps(self):
        argv,args=await self.worker(600)
        value=await Detector.open(argv,continuous=True,session_seconds=600)
        self.assertEqual(json.loads(args.read_text()),['--continuous','--session-seconds','600'])
        await value.close();self.assertEqual(value.process.returncode,0)

    async def test_legacy_worker_keeps_default_wire_and_cannot_accept_extension(self):
        argv,args=await self.worker(None)
        value=await Detector.open(argv,continuous=True)
        self.assertEqual(json.loads(args.read_text()),['--continuous'])
        await value.close()
        ended=[];close=Detector.close
        async def observed(value):
            await close(value);ended.append(value.process.returncode)
        with patch.object(Detector,'close',observed):
            with self.assertRaisesRegex(DetectionUnavailable,'Unexpected analysis worker'):
                await Detector.open(argv,continuous=True,session_seconds=600)
        self.assertEqual(ended,[0],'Incompatible worker exits before any PCM or provider is opened')

    async def test_invalid_duration_rejected_before_spawning(self):
        for seconds in (True,299,1801):
            with self.assertRaises(ValueError):
                await Detector.open(['/does-not-exist'],continuous=True,session_seconds=seconds)


if __name__ == '__main__':unittest.main()
