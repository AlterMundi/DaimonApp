"""Finite source→interpretation→native→result orchestration; no real providers."""
import copy
import hashlib
from pathlib import Path
import sys
import threading
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from dashboard.openai_live_native_backend import prepare_native, return_one_native_part
from dashboard.openai_live_seals import request_seal, accept_seal
from dashboard.openai_live_visits import LiveCreations
import dashboard_openai_live_native_work as fixtures


class Backend(unittest.TestCase):
    setUp=fixtures.NativeWork.setUp
    create=fixtures.NativeWork.create
    client=fixtures.NativeWork.client
    success=fixtures.NativeWork.success
    prepare=fixtures.NativeWork.prepare

    def ready(self):
        self.prepare();self.delegation='native-task';self.asr=[];self.imports=[];self.writes=[];self.updates=[]
        self.provider.presentation=lambda command:{'binding':self.owner['binding'],'foreground_interpretation':'gpt-transcribe/v1'}
        self.provider.presentation_list=lambda *args:{'binding':self.owner['binding'],
            'newest':{'native':1 if self.writes else 0},'items':([{
                'id':'native:1','revision':'d'*64,'kind':'integrator_answer','local_turn':42}] if self.writes else []),
            'cursor':{'native':1,'delivery':0},'more':False}
        def interpret(body):
            self.imports.append(copy.deepcopy(body));native=self.provider.retained[body['id']]
            native.update(phase='foreground',text=body['text'])
            native['voice'].update(preserve_original=True,transcription={
                'actual_transcriber':body['model'],'capture_id':body['id'],
                'audio_sha256':body['audio_sha256'],'audio_millis':body['audio_millis'],
                'transcription_millis':body['transcription_millis']})
            return copy.deepcopy(native)
        def delegate(body):
            self.writes.append(copy.deepcopy(body));native=self.provider.retained[body['id']]
            native.update(phase='accepted',local_turn=42,native_acceptance='observed',foreground_delegation={
                'intent_id':body['intent_id'],'dialogue_id':self.ident,'formulation':body['formulation'],
                'sources':[{'id':source,'capture_order':index+1,'text':self.provider.retained[source]['text'],
                    'text_sha256':hashlib.sha256(self.provider.retained[source]['text'].encode()).hexdigest(),
                    'voice':copy.deepcopy(self.provider.retained[source]['voice'])} for index,source in enumerate(body['source_ids'])]})
            return copy.deepcopy(native)
        self.provider.conversation_foreground_interpret=interpret
        self.provider.conversation_foreground_delegate=delegate
        self.provider.presentation_part=lambda source,revision,offset:{'id':source,'revision':revision,
            'offset':offset,'next_offset':None,'text':'Respuesta nativa verificada.',
            'entry_binding':self.owner['entry_binding'][:3]+[self.owner['binding']],
            'kind':'integrator_answer','local_turn':42,'native_binding_current':True}
        self.visits.event(self.ident,100,self.owner,{'type':'session.delegation.created',
            'event_id':'native-request','delegation':{'id':self.delegation,'target':'client'}})
        request=request_seal(self.visits,self.ident,100,self.owner,self.delegation,self.provider)
        accept_seal(self.visits,self.ident,100,self.owner,{'type':'source_sealed','request':request['request'],
            'through_ordinal':1,'capture_bytes':len(self.audio)-44},self.provider)

    def recognizer(self, key):
        test=self
        class Recognizer:
            model='gpt-transcribe'
            def transcribe(self,data):
                test.asr.append(data);test.assertEqual(data,test.audio)
                return 'Recordá el nombre corregido: Río Cobre.'
        return Recognizer()

    def run_pipeline(self, history=None, factory=None):
        return prepare_native(history or self.visits,self.ident,100,self.owner,
            self.delegation,self.provider,self.key,factory or self.recognizer)

    def test_whole_source_to_native_and_current_result_once(self):
        self.ready();result=self.run_pipeline()
        self.assertEqual(result['state'],'admitted');self.assertFalse(result['work_completed'])
        self.assertEqual(self.provider.submissions,1);self.assertEqual(len(self.asr),1)
        self.assertEqual(len(self.imports),1);self.assertEqual(len(self.writes),1)
        self.assertEqual(self.run_pipeline(LiveCreations(self.root)),result)
        self.assertEqual(len(self.writes),1);self.assertEqual(len(self.asr),1)
        test=self
        class Sideband:
            def send(self,command):test.updates.append(command)
        channel=Sideband()
        returned=return_one_native_part(self.visits,self.ident,100,self.owner,self.delegation,self.provider,channel)
        self.assertEqual(returned['state'],'sent');self.assertIn('Respuesta nativa',self.updates[0]['content'])
        self.assertIsNone(return_one_native_part(self.visits,self.ident,100,self.owner,self.delegation,self.provider,channel))
        self.assertEqual(len(self.updates),1)

    def test_close_during_interpretation_preserves_paid_result_but_never_dispatches(self):
        self.ready();normal=self.recognizer
        def factory(key):
            recognizer=normal(key);transcribe=recognizer.transcribe
            def close(data):
                result=transcribe(data);self.visits.end_capture(self.ident,100,self.owner['binding']);return result
            recognizer.transcribe=close;return recognizer
        with self.assertRaises(ValueError):self.run_pipeline(factory=factory)
        value=self.visits.read(self.ident,100,self.owner)
        self.assertEqual(value['native_originals']['0']['interpretation']['state'],'completed')
        self.assertEqual(value['delegations'][self.delegation]['native_pipeline']['state'],'held')
        self.assertEqual(self.writes,[]);self.assertEqual(self.imports,[])
        self.assertEqual(self.run_pipeline()['state'],'held');self.assertEqual(len(self.asr),1)

    def test_unknown_native_admission_is_retained_not_retried_by_pipeline(self):
        self.ready();delegate=self.provider.conversation_foreground_delegate
        def lost(body):delegate(body);raise OSError('Synthetic lost native reply')
        self.provider.conversation_foreground_delegate=lost
        self.assertEqual(self.run_pipeline()['state'],'unconfirmed')
        self.assertEqual(self.run_pipeline(LiveCreations(self.root))['state'],'unconfirmed')
        self.assertEqual(len(self.writes),1);self.assertEqual(len(self.asr),1)

    def test_restart_cannot_start_unattempted_paid_preparation(self):
        self.ready()
        with self.assertRaises(ValueError):self.run_pipeline(LiveCreations(self.root))
        self.assertEqual(self.provider.submissions,0);self.assertEqual(self.asr,[])

    def test_empty_confirmed_window_is_held_without_inference(self):
        self.ready();empty='empty-task'
        self.visits.event(self.ident,100,self.owner,{'type':'session.delegation.created',
            'event_id':'empty-native-request','delegation':{'id':empty,'target':'client'}})
        request=request_seal(self.visits,self.ident,100,self.owner,empty,self.provider)
        accept_seal(self.visits,self.ident,100,self.owner,{'type':'source_sealed','request':request['request'],
            'through_ordinal':1,'capture_bytes':len(self.audio)-44},self.provider)
        result=prepare_native(self.visits,self.ident,100,self.owner,empty,self.provider,self.key,self.recognizer)
        self.assertEqual(result['state'],'held');self.assertEqual(self.asr,[]);self.assertEqual(self.writes,[])

    def test_owned_stop_fences_dispatch_even_before_capture_end_is_persisted(self):
        self.ready();stopped=threading.Event();normal=self.recognizer
        def factory(key):
            recognizer=normal(key);transcribe=recognizer.transcribe
            def stop(data):result=transcribe(data);stopped.set();return result
            recognizer.transcribe=stop;return recognizer
        with self.assertRaises(ValueError):
            prepare_native(self.visits,self.ident,100,self.owner,self.delegation,
                self.provider,self.key,factory,stopped=stopped)
        value=self.visits.read(self.ident,100,self.owner)
        self.assertFalse(value['admission']['ended'],'This exercises the in-process fence, not a durable close marker')
        self.assertEqual(value['native_originals']['0']['interpretation']['state'],'completed')
        self.assertEqual(self.imports,[]);self.assertEqual(self.writes,[]);self.assertEqual(len(self.asr),1)


if __name__=='__main__':unittest.main()
