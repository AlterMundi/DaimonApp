"""OpenAI-only source reading: completion, exact cache, bounds and no replay."""
import base64
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import speech_render as speech
from scripts import openai_speech as realtime


class Socket:
    def __init__(self,fields,config):
        self.sent=[];self.closed=False;self.failure=None;self.close_error=False
        self.pcm=struct.pack('<h',3200)*240
        self.events=[{'type':'session.updated','session':{'model':config['model'],
            'audio':{'output':fields['session']['audio']['output']}}}]
        self.fields=fields
    def send(self,raw):
        value=json.loads(raw);self.sent.append(value)
        if value['type']=='response.create':
            self.events.extend([
                {'type':'response.created','response':{'id':'response-one','metadata':self.fields['response']['metadata']}},
                {'type':'response.output_audio.delta','response_id':'response-one','event_id':'audio-one',
                    'item_id':'item-one','delta':base64.b64encode(self.pcm).decode()},
                {'type':'response.output_audio.delta','response_id':'response-one','event_id':'audio-one',
                    'item_id':'item-one','delta':base64.b64encode(self.pcm).decode()},
                {'type':'response.done','response':{'id':'response-one','status':'completed',
                    'usage':{'input_tokens':48,'output_tokens':25,'total_tokens':73}}}])
            if self.failure:self.events[-1]=self.failure
    def recv(self):return json.dumps(self.events.pop(0))
    def settimeout(self,value):self.timeout=value
    def close(self,**kwargs):
        self.closed=True
        if self.close_error:raise OSError('Synthetic close failure after response completion')


class Reading(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);key=root/'key';key.write_text('synthetic-project-key');key.chmod(0o600)
        self.binding=root/'route';self.config={'schema':speech.SCHEMA,'provider':'openai-realtime',
            'model':'gpt-realtime-2.1-mini','voice':'cedar','language':'es-AR',
            'credential_file':str(key),'cache_root':str(root/'cache'),
            'instruction':'Use Argentine Spanish from Río de la Plata.'}
        self.write();self.request={'scope':'synthetic-source-revision-offset','text':'Dale, CompAII. La clave es violeta.'}
        self.cfg,self.fields,self.ident=speech.render_plan(self.binding,self.request)
        self.socket=Socket(self.fields,self.cfg);self.connections=[]
    def write(self):
        self.binding.write_text(json.dumps(self.config));self.binding.chmod(0o600)
    def connect(self,*args):self.connections.append(args);return self.socket

    def test_complete_audio_deduplicates_frames_retains_usage_and_never_uses_other_vendors(self):
        self.socket.close_error=True
        with patch.object(realtime,'connect',self.connect),patch.object(speech,'fetch',side_effect=AssertionError('Other vendor called')):
            first=speech.render(self.binding,self.request);second=speech.render(self.binding,self.request)
        self.assertEqual(len(self.connections),1);self.assertFalse(first['cache_hit']);self.assertTrue(second['cache_hit'])
        self.assertEqual(first['audio_sha256'],second['audio_sha256']);self.assertTrue(self.socket.closed)
        data=Path(first['audio_path']).read_bytes()
        with wave.open(io.BytesIO(data),'rb') as audio:
            self.assertEqual(audio.getframerate(),24000);self.assertEqual(audio.readframes(10000),self.socket.pcm)
        state=json.loads((Path(self.cfg['cache_root'])/self.ident/'state.json').read_text())
        receipt=state['provider_receipt'];self.assertEqual(receipt['usage']['total_tokens'],73)
        self.assertEqual(receipt['response_id'],'response-one');self.assertEqual(receipt['hearing'],'not_observed')
        self.assertIsNone(self.fields['session']['audio']['input']['turn_detection'])
        self.assertEqual(self.fields['session']['tools'],[]);self.assertEqual(self.fields['response']['conversation'],'none')
        self.assertEqual(self.fields['response']['input'][0]['content'][0]['text'],self.request['text'])

    def test_incomplete_generation_preserves_exact_response_and_refuses_replay(self):
        self.socket.failure={'type':'response.done','response':{'id':'response-one','status':'incomplete'}}
        with patch.object(realtime,'connect',self.connect),patch.object(speech,'fetch',side_effect=AssertionError('Fallback called')):
            for _ in range(2):
                with self.assertRaises(speech.RenderError):speech.render(self.binding,self.request)
        self.assertEqual(len(self.connections),1)
        state=json.loads((Path(self.cfg['cache_root'])/self.ident/'state.json').read_text())
        self.assertEqual(state['phase'],'unconfirmed');self.assertEqual(state['provider_receipt']['response_id'],'response-one')
        self.assertFalse((Path(self.cfg['cache_root'])/self.ident/'audio.wav').exists())

    def test_changed_voice_refuses_before_audio_request(self):
        self.socket.events[0]['session']['audio']['output']={**self.fields['session']['audio']['output'],'voice':'marin'}
        with self.assertRaises(realtime.SpeechError):
            realtime.render(self.cfg,self.fields,'synthetic',speech.MAX_AUDIO,connector=self.connect)
        self.assertEqual([v['type'] for v in self.socket.sent],['session.update'])

    def test_wrong_response_and_audio_capacity_are_refused(self):
        for failure in ({'type':'response.output_audio.delta','response_id':'another','event_id':'wrong',
                'item_id':'item-one','delta':base64.b64encode(self.socket.pcm).decode()},
                {'type':'response.done','response':{'id':'another','status':'completed','usage':{}}}):
            with self.subTest(failure=failure['type']):
                self.socket=Socket(self.fields,self.cfg);self.socket.failure=failure
                with self.assertRaises(realtime.SpeechError):
                    realtime.render(self.cfg,self.fields,'synthetic',speech.MAX_AUDIO,connector=self.connect)
        self.socket=Socket(self.fields,self.cfg)
        with self.assertRaises(realtime.SpeechError):realtime.render(self.cfg,self.fields,'synthetic',45,connector=self.connect)

    def test_model_and_endpoint_are_explicit_and_do_not_accept_retired_tts_workflows(self):
        for updates in ({'model':'gpt-4o-mini-tts'},{'endpoint':'wss://example.test/v1/realtime'},
                {'endpoint':'wss://api.openai.com/v1/realtime?token=secret'},{'voice':'unknown'}):
            with self.subTest(updates=updates):
                before=dict(self.config);self.config.update(updates);self.write()
                with self.assertRaises(speech.RenderError):speech.route(self.binding)
                self.config=before


if __name__=='__main__':unittest.main()
