"""Finite source→interpretation→native→result orchestration; no real providers."""
import copy
import hashlib
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from dashboard.openai_live_native_backend import prepare_native, return_one_native_part
from dashboard.openai_live_seals import request_seal, accept_seal
from dashboard.openai_live_window import freeze_input_window
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
        self.provider.presentation=lambda command:{'binding':self.owner['binding'],'foreground_interpretation':'gpt-transcribe/v1','foreground_live_window':'journal-input/v1','voice_available':True,'foreground_completed_reader':True}
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
            self.assertIn('live_window',body)
            window=self.visits.read(self.ident,100,self.owner)['delegations'][self.delegation]['live_window']
            native['text']=window['text']
            native.update(phase='accepted',local_turn=42,native_acceptance='observed',foreground_delegation={
                'intent_id':body['intent_id'],'dialogue_id':self.ident,'formulation':body['formulation'],'live_window':body['live_window']['proof'],
                'sources':[{'id':source,'capture_order':index+1,'text':self.provider.retained[source]['text'],
                    'text_sha256':hashlib.sha256(self.provider.retained[source]['text'].encode()).hexdigest(),
                    'voice':copy.deepcopy(self.provider.retained[source]['voice'])} for index,source in enumerate(body['source_ids'])]})
            return copy.deepcopy(native)
        self.provider.conversation_foreground_interpret=interpret
        self.provider.conversation_foreground_delegate=delegate
        self.provider.conversation_input_trace=lambda root:{'id':root,
            'entry_binding':self.owner['entry_binding'],'routes':[]}
        self.provider.presentation_part=lambda source,revision,offset:{'id':source,'revision':revision,
            'offset':offset,'next_offset':None,'text':'Respuesta nativa verificada.',
            'entry_binding':self.owner['entry_binding'][:3]+[self.owner['binding']],
            'kind':'integrator_answer','local_turn':42,'native_binding_current':True}
        self.visits.event(self.ident,100,self.owner,{'type':'session.input_transcript.delta','event_id':'live-input','delta':'Usá el nombre corregido: Río Cobre.','start_ms':0,'end_ms':50})
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
        self.assertEqual(self.provider.submissions,1);self.assertEqual(len(self.asr),0)
        self.assertEqual(len(self.imports),0);self.assertEqual(len(self.writes),1)
        self.assertEqual(self.run_pipeline(LiveCreations(self.root)),result)
        self.assertEqual(len(self.writes),1);self.assertEqual(len(self.asr),0)
        test=self
        class Sideband:
            def send(self,command):test.updates.append(command)
        channel=Sideband()
        returned=return_one_native_part(self.visits,self.ident,100,self.owner,self.delegation,self.provider,channel)
        self.assertEqual(returned['state'],'sent');self.assertIn('Respuesta nativa',self.updates[0]['content'])
        self.assertIsNone(return_one_native_part(self.visits,self.ident,100,self.owner,self.delegation,self.provider,channel))
        self.assertEqual(len(self.updates),1)

    def test_close_after_window_freeze_preserves_sources_without_dispatch(self):
        self.ready()
        def close(*args):
            result=freeze_input_window(*args)
            self.visits.end_capture(self.ident,100,self.owner['binding'])
            return result
        with patch('dashboard.openai_live_native_backend.freeze_input_window',close):
            with self.assertRaises(ValueError):self.run_pipeline()
        value=self.visits.read(self.ident,100,self.owner)
        self.assertNotIn('interpretation',value['native_originals']['0'])
        self.assertIn('live_window',value['delegations'][self.delegation])
        self.assertEqual(value['delegations'][self.delegation]['native_pipeline']['state'],'held')
        self.assertEqual(self.writes,[]);self.assertEqual(self.imports,[]);self.assertEqual(self.asr,[])
        self.assertEqual(self.run_pipeline()['state'],'held')

    def test_unknown_native_admission_is_retained_not_retried_by_pipeline(self):
        self.ready();delegate=self.provider.conversation_foreground_delegate
        def lost(body):delegate(body);raise OSError('Synthetic lost native reply')
        self.provider.conversation_foreground_delegate=lost
        self.assertEqual(self.run_pipeline()['state'],'unconfirmed')
        self.assertEqual(self.run_pipeline(LiveCreations(self.root))['state'],'unconfirmed')
        self.assertEqual(len(self.writes),1);self.assertEqual(len(self.asr),0)

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

    def test_in_process_cancellation_after_window_freeze_never_submits(self):
        self.ready();stopped=threading.Event()
        def stop(*args):
            result=freeze_input_window(*args);stopped.set();return result
        with patch('dashboard.openai_live_native_backend.freeze_input_window',stop):
            with self.assertRaises(ValueError):
                prepare_native(self.visits,self.ident,100,self.owner,self.delegation,
                    self.provider,self.key,self.recognizer,stopped=stopped)
        value=self.visits.read(self.ident,100,self.owner)
        self.assertFalse(value['admission']['ended'])
        self.assertNotIn('interpretation',value['native_originals']['0'])
        self.assertEqual(self.imports,[]);self.assertEqual(self.writes,[]);self.assertEqual(self.asr,[])
        receipt=prepare_native(self.visits,self.ident,100,self.owner,self.delegation,
            self.provider,self.key,self.recognizer,stopped=stopped)
        self.assertEqual(receipt['state'],'held')

    def test_result_scan_continues_after_bounded_unrelated_pages(self):
        self.ready();self.run_pipeline();test=self
        def page(delivery,native,direction):
            rows=[{'id':'native:'+str(n),'revision':'d'*64,'kind':'integrator_answer',
                'local_turn':42 if n==65 else 99} for n in range(native+1,min(native+8,65)+1)]
            return {'binding':self.owner['binding'],'items':rows,
                'cursor':{'delivery':0,'native':min(native+8,65)},'more':native+8<65}
        self.provider.presentation_list=page
        class Sideband:
            def send(self,command):test.updates.append(command)
        channel=Sideband()
        self.assertIsNone(return_one_native_part(self.visits,self.ident,100,self.owner,self.delegation,self.provider,channel))
        value=self.visits.read(self.ident,100,self.owner)
        self.assertEqual(value['delegations'][self.delegation]['native_pipeline']['return_after'],64)
        result=return_one_native_part(self.visits,self.ident,100,self.owner,self.delegation,self.provider,channel)
        self.assertEqual(result['state'],'sent');self.assertEqual(result['source'],'native:65')
        self.assertEqual(len(self.writes),1);self.assertEqual(len(self.updates),1)

    def test_stop_before_worker_starts_does_not_leave_a_pending_voice_close(self):
        self.ready();stopped=threading.Event();stopped.set()
        result=prepare_native(self.visits,self.ident,100,self.owner,self.delegation,
            self.provider,self.key,self.recognizer,stopped=stopped)
        self.assertEqual(result['state'],'held');self.assertEqual(self.asr,[])
        self.assertEqual(self.provider.submissions,0)
        self.assertEqual(self.visits.close_intent(self.ident,100,self.owner)['type'],'session.close')

    def worker_result(self):
        self.ready();self.run_pipeline()
        source='delivery:00000000-0000-4000-8000-000000000001'
        result={'source':source,'revision':'b'*64,'instruction_covered':True,
                'current':True,'correction_pending':False}
        route={'target_available':True,'results':[result]}
        self.provider.conversation_input_trace=lambda root:{'id':root,
            'entry_binding':self.owner['entry_binding'],'routes':[route]}
        part=self.provider.presentation_part
        self.provider.presentation_part=lambda source,revision,offset:{
            **part(source,revision,offset),'kind':'worker_result','current':True}
        test=self
        class Sideband:
            def send(self,command):test.updates.append(command)
        return route,result,Sideband()

    def test_late_worker_uses_exact_trace_without_scanning_unrelated_history(self):
        route,result,channel=self.worker_result()
        self.provider.presentation_list=lambda *args:self.fail('Exact trace must locate an older worker result')
        returned=return_one_native_part(self.visits,self.ident,100,self.owner,self.delegation,self.provider,channel)
        self.assertEqual(returned['source'],result['source']);self.assertEqual(returned['revision'],result['revision'])
        self.assertEqual(len(self.writes),1);self.assertEqual(len(self.asr),0)
        self.assertIsNone(return_one_native_part(self.visits,self.ident,100,self.owner,self.delegation,self.provider,channel))
        self.assertEqual(len(self.updates),1,'An unknown injection cannot be retried or skipped')

    def test_unavailable_or_uncovered_worker_can_be_observed_later_without_new_work(self):
        route,result,channel=self.worker_result()
        self.provider.presentation_list=lambda *args:{'binding':self.owner['binding'],
            'items':[],'cursor':{'native':0,'delivery':1000},'more':False}
        route['target_available']=False
        self.assertIsNone(return_one_native_part(self.visits,self.ident,100,self.owner,self.delegation,self.provider,channel))
        route['target_available']=True
        for field,value in [('instruction_covered',False),('current',False),('correction_pending',True),('revision',None)]:
            before=result[field];result[field]=value
            self.assertIsNone(return_one_native_part(self.visits,self.ident,100,self.owner,self.delegation,self.provider,channel))
            result[field]=before
        returned=return_one_native_part(self.visits,self.ident,100,self.owner,self.delegation,self.provider,channel)
        self.assertEqual(returned['source'],result['source']);self.assertEqual(len(self.writes),1)

    def test_worker_association_is_rechecked_before_context_write(self):
        route,result,channel=self.worker_result();reads=[]
        def trace(root):
            reads.append(root)
            return {'id':root,'entry_binding':self.owner['entry_binding'],
                'routes':[route] if len(reads)==1 else []}
        self.provider.conversation_input_trace=trace
        with self.assertRaises(ValueError):
            return_one_native_part(self.visits,self.ident,100,self.owner,self.delegation,self.provider,channel)
        self.assertEqual(self.updates,[]);self.assertEqual(len(self.writes),1)

    def test_foreign_trace_cannot_select_a_worker_result(self):
        route,result,channel=self.worker_result()
        self.provider.conversation_input_trace=lambda root:{'id':root,'entry_binding':[1,2,3,4],'routes':[route]}
        from dashboard.provider import ProviderUnavailable
        with self.assertRaises(ProviderUnavailable):
            return_one_native_part(self.visits,self.ident,100,self.owner,self.delegation,self.provider,channel)
        self.assertEqual(self.updates,[])


if __name__=='__main__':unittest.main()
