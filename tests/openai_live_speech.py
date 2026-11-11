"""Actual preview event loop + existing durable cache, with synthetic sockets."""
import base64
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import openai_live_speech as live,speech_render as speech


class Clock:
    def __init__(self):self.now=0
    def __call__(self):return self.now


class Socket:
    def __init__(self,clock,voice='cedar',cancel=None):
        self.clock=clock;self.sent=[];self.closed=False;self.cancel=cancel
        audio={'type':'session.output_audio.delta','delta':base64.b64encode(b'\x01\0'*2400).decode()}
        self.events=[{'type':'session.started','event_id':'start','session':{'id':'synthetic-live',
            'model':'gpt-live-1','audio':{'format':{'type':'audio/pcm','rate':24000},'output':{'voice':voice}}}},
            audio,dict(audio),{'type':'session.output_transcript.delta','event_id':'words','delta':'Dale, Compai.'}]
    def settimeout(self,value):assert 0<value<=.02
    def send(self,raw):
        value=json.loads(raw);self.sent.append(value)
        if value['type']=='session.close':self.events.append({'type':'session.closed','event_id':'end',
            'session':{'id':'synthetic-live'},'usage':{'seconds':2},'reason':'close_requested'})
    def recv(self):
        self.clock.now+=.2
        if not self.events:raise TimeoutError()
        value=self.events.pop(0)
        if self.cancel is not None and value['type']=='session.output_audio.delta':self.cancel.set()
        return json.dumps(value,separators=(',',':'))
    def close(self,**kwargs):self.closed=True


class Preview(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=Path(self.temp.name);self.key=p/'key';self.key.write_text('sk-synthetic-local-only');self.key.chmod(0o600)
        self.config={'schema':speech.SCHEMA,'provider':'openai-live','cache_root':str(p/'cache'),
            'credential_file':str(self.key),'model':'gpt-live-1','voice':'cedar','language':'es-AR',
            'instruction':'Speak Spanish from Argentina, Río de la Plata.','timeout_seconds':30}
        self.request={'scope':'synthetic-actor-and-preview-identity','text':'Dale, Compai.'}
        self.configured,self.fields,_=speech.render_plan(self.config,self.request)
        self.clock=Clock();self.socket=Socket(self.clock);self.connects=0
    def connect(self,*args):self.connects+=1;return self.socket
    def run_preview(self,**kwargs):return live.render(self.configured,self.fields,'synthetic',speech.MAX_AUDIO,
        connector=self.connect,clock=self.clock,**kwargs)

    def test_reading_uses_selected_identity_without_preview_word_limit(self):
        from dashboard.speech import Speech
        from dashboard.avatar_workshop import AvatarWorkshop
        import uuid
        binding=Path(self.temp.name)/'reader.json'
        base={**self.config,'provider':'openai-realtime','model':'gpt-realtime-2.1-mini','timeout_seconds':60}
        binding.write_text(json.dumps(base));binding.chmod(0o600)
        config={'openai_live':{'enabled':True,'api_key_file':str(self.key),
            'session_options':{'audio':{'output':{'voice':'cedar'}}}},'voice_studio':{'voices':['willow']}}
        store=AvatarWorkshop(Path(self.temp.name)/'state')
        profiles=[{'provider':'openai','api':'gpt-live','model':'gpt-live-1','voice':v} for v in ('cedar','willow')]
        ident=str(uuid.uuid4());store.voice_save(100,ident,profiles[1],'Warm and calm.',None,0)
        store.voice_select(100,ident,1,profiles)
        original=Speech({'binding':str(binding)})
        original.media_retention=object()
        reader=original.selected_voice(config,store.voice_for_conversation(100,profiles))
        self.assertIs(reader.capacity,original.capacity)
        self.assertIs(reader.media_retention,original.media_retention)
        text='palabra '*60
        route,fields,reading_id=speech.render_plan(reader.receiving_route(),{'scope':'reading','text':text})
        self.assertEqual(route['voice'],'willow');self.assertEqual(route['timeout_seconds'],120)
        self.assertIn('Warm and calm.',fields['session']['instructions'])
        self.assertEqual(fields['passage'],text)
        self.assertIsNone(store.voice_for_conversation(200,profiles))
        other=str(uuid.uuid4());store.voice_save(100,other,profiles[0],'',None,2);store.voice_select(100,other,3,profiles)
        self.assertEqual(reader.receiving_route()['voice'],'willow','In-flight reading stays frozen')
        next_reader=original.selected_voice(config,store.voice_for_conversation(100,profiles))
        self.assertEqual(next_reader.receiving_route()['voice'],'cedar')
        self.assertNotEqual(reading_id,speech.render_plan(next_reader.receiving_route(),{'scope':'reading','text':text})[2])
        self.assertEqual(json.loads(binding.read_text()),base)
        with self.assertRaises(speech.RenderError):speech.render_plan(self.config,{'scope':'preview','text':text})

    def test_continuous_zero_pcm_does_not_extend_a_completed_passage(self):
        receive=self.socket.recv
        def continuous():
            if not self.socket.events:
                self.socket.events.append({'type':'session.output_audio.delta',
                    'delta':base64.b64encode(b'\0'*9600).decode()})
            return receive()
        self.socket.recv=continuous
        audio,receipt=self.run_preview()
        self.assertTrue(receipt['finalized']);self.assertTrue(receipt['passage_match'])
        self.assertLess(receipt['generation_millis'],5000,'Continuous silence must not hold completed reading until the generation deadline')
        self.assertLess(receipt['audio_millis'],5000)
        self.assertEqual([e['type'] for e in self.socket.sent].count('session.close'),1)
        self.assertEqual(self.connects,1)

    def test_same_live_api_one_greeting_silence_dedup_and_confirmed_usage(self):
        audio,receipt=self.run_preview()
        self.assertEqual(audio[:4],b'RIFF');self.assertEqual(len(audio),44+9600)
        self.assertTrue(receipt['finalized']);self.assertTrue(receipt['passage_match'])
        self.assertEqual(receipt['usage'],{'seconds':2});self.assertEqual(receipt['hearing'],'not_observed')
        self.assertTrue(self.socket.closed);self.assertEqual(self.connects,1)
        types=[x['type'] for x in self.socket.sent]
        self.assertEqual(types.count('session.start'),1);self.assertEqual(types.count('session.commentary.append'),1)
        self.assertEqual(types.count('session.close'),1);self.assertIn('session.input_audio.append',types)
        start=self.socket.sent[0]['session'];self.assertEqual(start['delegation'],{'type':'client'})
        self.assertFalse(start['store']);self.assertNotIn('tools',start)

    def test_primary_audio_without_identity_preserves_repeated_chunks_in_order(self):
        # Actual documented LiveOutputAudioDelta shape; no invented event_id.
        self.socket.events[2] = {'type':'session.output_audio.delta',
            'delta':base64.b64encode(b'\x02\0'*2400).decode()}
        audio,receipt=self.run_preview()
        self.assertEqual(audio[44:], b'\x01\0'*2400+b'\x02\0'*2400)
        self.assertEqual(receipt['audio_millis'],200)
        self.assertEqual(self.connects,1)

    def test_primary_audio_still_checks_pcm_and_budget(self):
        for delta in ('not base64!', '', base64.b64encode(b'odd').decode()):
            with self.subTest(delta=delta):
                self.clock=Clock();self.socket=Socket(self.clock)
                self.socket.events[1]={'type':'session.output_audio.delta','delta':delta}
                with self.assertRaisesRegex(live.SpeechError,'event-mismatch'):self.run_preview()
        self.clock=Clock();self.socket=Socket(self.clock)
        with self.assertRaisesRegex(live.SpeechError,'event-mismatch'):
            live.render(self.configured,self.fields,'synthetic',100,
                connector=self.connect,clock=self.clock)

    def test_metadata_still_requires_identity_and_conflicting_duplicates_refuse(self):
        for bad in ({'type':'session.output_transcript.delta','delta':'private'},
                {'type':'session.output_transcript.delta','event_id':'start','delta':'private'}):
            with self.subTest(bad=bad):
                self.clock=Clock();self.socket=Socket(self.clock);self.socket.events.insert(1,bad);receipts=[]
                with self.assertRaisesRegex(live.SpeechError,'event-mismatch'):
                    self.run_preview(progress=receipts.append)
                self.assertTrue(receipts[-1]['finalized'])
                self.assertEqual(receipts[-1]['diagnostic']['mismatch_stage'],'event_validation')

    def test_cancel_drains_owned_close_without_another_session(self):
        cancel=threading.Event();self.socket.cancel=cancel;receipts=[]
        with self.assertRaisesRegex(live.SpeechError,'cancelled'):self.run_preview(cancel=cancel,progress=receipts.append)
        self.assertEqual(receipts[-1]['stage'],'session_closed');self.assertTrue(receipts[-1]['finalized'])
        self.assertTrue(self.socket.closed);self.assertEqual(self.connects,1)

    def test_cancel_during_start_never_requests_greeting(self):
        cancel=threading.Event();receive=self.socket.recv
        def cancelled_start():
            raw=receive()
            if json.loads(raw)['type']=='session.started':cancel.set()
            return raw
        self.socket.recv=cancelled_start
        with self.assertRaisesRegex(live.SpeechError,'cancelled'):self.run_preview(cancel=cancel)
        self.assertFalse(any(e['type']=='session.commentary.append' for e in self.socket.sent))
        self.assertEqual(sum(e['type']=='session.close' for e in self.socket.sent),1)

    def test_wrong_voice_is_closed_and_never_used_as_another_identity(self):
        self.socket=Socket(self.clock,voice='other')
        with self.assertRaisesRegex(live.SpeechError,'mismatch'):self.run_preview()
        self.assertTrue(self.socket.closed);self.assertEqual(self.connects,1)
        self.assertEqual(sum(x['type']=='session.close' for x in self.socket.sent),1)

    def test_confirmed_close_keeps_the_failure_that_requested_it(self):
        for kind in ('wrong_voice','provider_error','no_audio'):
            with self.subTest(kind=kind):
                self.clock=Clock();self.socket=Socket(self.clock,voice='other' if kind=='wrong_voice' else 'cedar');receipts=[]
                if kind=='provider_error':self.socket.events.insert(1,{'type':'error','event_id':'bad','error':{'code':'invalid_value','message':'sk-private not for diagnostics'}})
                if kind=='no_audio':self.socket.events=[self.socket.events[0]]
                with self.assertRaises(live.SpeechError):self.run_preview(progress=receipts.append)
                result=receipts[-1];self.assertEqual(result['stage'],'session_closed');self.assertTrue(result['finalized'])
                expected={'wrong_voice':'audition-event-mismatch','provider_error':'audition-provider-error','no_audio':'audition-no-audio'}[kind]
                self.assertEqual(result['diagnostic']['failure_code'],expected)
                self.assertNotIn('sk-private',json.dumps(result))
                if kind=='wrong_voice':self.assertEqual(result['diagnostic']['mismatch_stage'],'startup_voice')
                if kind=='provider_error':self.assertEqual(result['diagnostic']['provider_error_code'],'invalid_value')

    def test_unknown_close_keeps_existing_cache_intent_and_never_reconnects(self):
        def disconnected():raise ConnectionError()
        self.socket.recv=disconnected
        actual=live.render
        with patch.object(live,'render',lambda *a,**kw:actual(*a,**kw,connector=self.connect,clock=self.clock)):
            with self.assertRaisesRegex(speech.RenderError,'unconfirmed'):speech.render(self.config,self.request,allow_regenerate=False)
            with self.assertRaisesRegex(speech.RenderError,'retained-render'):speech.render(self.config,self.request,allow_regenerate=False)
        self.assertEqual(self.connects,1)

    def test_completed_preview_reuses_same_cache_and_expiry_cannot_regenerate(self):
        actual=live.render
        with patch.object(live,'render',lambda *a,**kw:actual(*a,**kw,connector=self.connect,clock=self.clock)):
            first=speech.render(self.config,self.request,allow_regenerate=False)
            self.assertTrue(speech.render(self.config,self.request,allow_regenerate=False)['cache_hit'])
            root=Path(self.config['cache_root']);job=next(p for p in root.iterdir() if p.is_dir())
            state=json.loads((job/'state.json').read_text());state['phase']='audio_expired'
            (job/'state.json').write_text(json.dumps(state))
            with self.assertRaisesRegex(speech.RenderError,'expired-no-automatic'):speech.render(self.config,self.request,allow_regenerate=False)
        self.assertEqual(self.connects,1);self.assertFalse(first['cache_hit'])

    def test_no_audio_is_not_a_successful_preview(self):
        self.socket.events=[self.socket.events[0]]
        with self.assertRaisesRegex(live.SpeechError,'no-audio'):self.run_preview()
        self.assertTrue(self.socket.closed)

    def test_no_start_or_missing_final_usage_keeps_outcome_unconfirmed(self):
        self.socket.events=[]
        with self.assertRaisesRegex(live.SpeechError,'start-unconfirmed'):self.run_preview()
        self.assertFalse(any(x['type']=='session.close' for x in self.socket.sent))
        self.clock=Clock();self.socket=Socket(self.clock)
        send=self.socket.send
        def without_usage(raw):
            send(raw)
            if json.loads(raw)['type']=='session.close':self.socket.events[-1].pop('usage')
        self.socket.send=without_usage
        with self.assertRaisesRegex(live.SpeechError,'finalization-unconfirmed'):self.run_preview()
        self.assertTrue(self.socket.closed)

    def test_failed_start_retains_bounded_reason_without_provider_message(self):
        self.socket.events=[{'type':'error','event_id':'error',
            'error':{'code':'invalid_value','message':'sk-private must never be retained',
                     'param':'private-account-resource'}}]
        receipts=[]
        with self.assertRaisesRegex(live.SpeechError,'start-unconfirmed'):
            self.run_preview(progress=receipts.append)
        final=receipts[-1]
        self.assertFalse(final['finalized'])
        self.assertEqual(final['diagnostic'],{'failure_code':'audition-provider-error',
                                            'provider_error_code':'invalid_value'})
        self.assertNotIn('sk-private',json.dumps(receipts))
        self.assertNotIn('private-account-resource',json.dumps(receipts))
        self.assertTrue(self.socket.closed);self.assertEqual(self.connects,1)

    def test_diagnostics_reject_unknown_codes_and_arbitrary_values(self):
        self.assertEqual(live.diagnostic({'failure_code':'private','provider_error_code':'sk-secret',
                                         'message':'secret'}),{})
        self.assertEqual(live.diagnostic(None),{})
        self.assertEqual(live.diagnostic({'failure_code':{},'provider_error_code':[]}),{})
        self.socket.events=[];receipts=[]
        with self.assertRaisesRegex(live.SpeechError,'start-unconfirmed'):
            self.run_preview(progress=receipts.append)
        self.assertEqual(receipts[-1]['diagnostic'],{'failure_code':'audition-start-unconfirmed'})

    def test_explicit_retirement_reuses_exact_cache_and_preserves_unknown_jobs(self):
        actual=live.render
        with patch.object(live,'render',lambda *a,**kw:actual(*a,**kw,connector=self.connect,clock=self.clock)):
            result=speech.render(self.config,self.request,allow_regenerate=False)
        ident=result['render_id'];job=Path(self.config['cache_root'])/ident
        state_path=job/'state.json';state=json.loads(state_path.read_text())
        outcome={'state':'rendered','receipt':result}
        state['phase']='intent';state_path.write_text(json.dumps(state))
        with self.assertRaises(speech.RenderError):speech.retire_preview_job(self.config,ident,outcome)
        self.assertTrue((job/'audio.wav').exists())
        state['phase']='rendered';state_path.write_text(json.dumps(state))
        self.assertTrue(speech.retire_preview_job(self.config,ident,outcome)['retired'])
        self.assertFalse(job.exists());self.assertTrue(speech.retire_preview_job(self.config,ident,outcome)['already_absent'])
        self.assertEqual(self.connects,1)

    def test_passage_endpoint_deadline_bounds_refuse_without_a_connection(self):
        with self.assertRaises(speech.RenderError):speech.render_plan(self.config,{**self.request,'text':'word '*41})
        for field,value in [('endpoint','wss://unselected.example/v1/live/sessions'),('timeout_seconds',31),('model','other')]:
            with self.assertRaises(speech.RenderError):speech.render_plan({**self.config,field:value},self.request)
        self.assertEqual(self.connects,0)

if __name__=='__main__':unittest.main()
