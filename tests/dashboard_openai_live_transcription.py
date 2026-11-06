"""Bounded OpenAI file interpretation, exact acoustic source and no paid retries."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from dashboard.openai_live_transcription import OriginalTranscription, InterpretationUnavailable, interpret_original
from dashboard.openai_live_visits import LiveCreations
from dashboard.provider import ProviderUnavailable
import dashboard_openai_live_originals as fixtures


class Interpretation(unittest.TestCase):
    setUp=fixtures.Originals.setUp
    create=fixtures.Originals.create
    client=fixtures.Originals.client
    success=fixtures.Originals.success
    prepare=fixtures.Originals.prepare
    enroll=fixtures.Originals.enroll

    def ready(self):
        self.prepare();self.enroll()
        self.provider.retained[self.receipt['id']]['voice']['transcription']=None
        self.sent=[]
        self.provider.presentation=lambda command:{'binding':self.owner['binding'],'foreground_interpretation':'gpt-transcribe/v1'}

    def recognizer(self,reply=None):
        def handle(request):
            self.sent.append(request)
            return reply(request) if callable(reply) else reply or httpx.Response(200,json={'text':'Usá el nombre corregido: Río Cobre.'})
        return OriginalTranscription(self.key,transport=httpx.MockTransport(handle))

    def run_original(self,recognizer=None,history=None):
        return interpret_original(history or self.visits,self.ident,100,self.owner,0,self.provider,recognizer or self.recognizer())

    def test_one_actual_http_shape_exact_bytes_and_retained_result(self):
        self.ready();result=self.run_original()
        self.assertEqual(result['state'],'completed');self.assertIn('Río Cobre',result['text'])
        self.assertEqual(result['audio_sha256'],self.receipt['audio_sha256']);self.assertFalse(result['work_admitted'])
        request=self.sent[0];self.assertEqual(str(request.url),'https://api.openai.com/v1/audio/transcriptions')
        self.assertIn(b'gpt-transcribe',request.content);self.assertIn(self.audio,request.content)
        self.assertIn('multipart/form-data',request.headers['content-type'])
        self.assertEqual(self.run_original(history=LiveCreations(self.root)),result)
        self.assertEqual(interpret_original(LiveCreations(self.root),self.ident,100,self.owner,0,self.provider),result)
        self.assertEqual(len(self.sent),1)
        self.assertNotIn('interpretation_reserve',self.visits.read(self.ident,100,self.owner)['native_originals']['0'])
        self.assertNotIn('interpretation',self.enroll())

    def test_timeout_and_rejection_never_resubmit_even_after_restart(self):
        self.ready()
        def lost(request):raise httpx.ReadTimeout('synthetic ACK lost')
        self.assertEqual(self.run_original(self.recognizer(lost))['state'],'unconfirmed')
        self.assertEqual(self.run_original(history=LiveCreations(self.root))['state'],'unconfirmed')
        self.assertEqual(len(self.sent),1)
        # A separate original is a separate request, not a retry of that loss.
        from dashboard.live_transcription import wav_bytes
        self.visits.recording(self.ident,100,self.owner['binding'],1,wav_bytes(b'\1\0'*3200),self.provider)
        from dashboard.openai_live_originals import enroll_original
        enroll_original(self.visits,self.ident,100,self.owner,1,self.provider)
        r=interpret_original(self.visits,self.ident,100,self.owner,1,self.provider,self.recognizer(httpx.Response(403,json={'error':'synthetic'})))
        self.assertEqual(r['state'],'rejected');self.assertEqual(r['status'],403)

    def test_revoked_viewer_cannot_get_result_but_paid_result_is_preserved(self):
        self.ready()
        def revoke(request):self.provider.allowed=False;return httpx.Response(200,json={'text':'Respuesta retenida.'})
        with self.assertRaises(ProviderUnavailable):self.run_original(self.recognizer(revoke))
        slot=self.visits.read(self.ident,100,self.owner)['native_originals']['0']
        self.assertEqual(slot['interpretation']['text'],'Respuesta retenida.')
        self.provider.allowed=True
        self.assertEqual(self.run_original()['state'],'completed');self.assertEqual(len(self.sent),1)

    def test_abrupt_exit_preserves_intent_and_budget_without_repeat(self):
        self.ready()
        class ExitDuringRequest(BaseException):pass
        def interrupted(request):raise ExitDuringRequest()
        with self.assertRaises(ExitDuringRequest):self.run_original(self.recognizer(interrupted))
        slot=self.visits.read(self.ident,100,self.owner)['native_originals']['0']
        self.assertEqual(len(slot['interpretation_reserve']),20000)
        result=interpret_original(LiveCreations(self.root),self.ident,100,self.owner,0,self.provider)
        self.assertEqual(result['state'],'intent');self.assertNotIn('text',result)
        self.assertIn('unconfirmed',result['meaning']);self.assertEqual(len(self.sent),1)

    def test_reserved_result_storage_fails_before_paid_call(self):
        self.ready()
        self.visits.max_record_bytes=10000
        with self.assertRaises(ValueError):self.run_original()
        self.assertEqual(self.sent,[])
        self.assertNotIn('interpretation',self.visits.read(self.ident,100,self.owner)['native_originals']['0'])

    def test_existing_canonical_interpretation_and_restart_do_not_start_asr(self):
        self.ready();self.provider.retained[self.receipt['id']]['phase']='foreground'
        with self.assertRaises(ValueError):self.run_original()
        self.assertEqual(self.sent,[])
        with self.assertRaises(ValueError):self.run_original(history=LiveCreations(self.root))

    def test_older_native_reader_refuses_before_billable_intent(self):
        self.ready();self.provider.presentation=lambda command:{'binding':self.owner['binding']}
        with self.assertRaises(ValueError):self.run_original()
        self.assertEqual(self.sent,[])
        self.assertNotIn('interpretation',self.visits.read(self.ident,100,self.owner)['native_originals']['0'])

    def test_response_and_client_are_bounded_and_once_only(self):
        self.ready();client=self.recognizer(httpx.Response(200,content=b'x'*65537))
        with self.assertRaises(InterpretationUnavailable):client.transcribe(self.audio)
        with self.assertRaises(InterpretationUnavailable):client.transcribe(self.audio)
        self.assertEqual(len(self.sent),1)
        with self.assertRaises(ValueError):self.recognizer().transcribe(b'not canonical WAV')


if __name__=='__main__':unittest.main()
