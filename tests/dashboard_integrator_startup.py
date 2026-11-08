"""Current native conversation before public voice; no model/provider calls."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.integrator_startup import read, integrating_sources
from dashboard.provider import Provider, ProviderUnavailable


def message(ident,text,role='user',phase=None):
    item={'id':ident,'type':'userMessage' if role=='user' else 'agentMessage'}
    if role=='user':item['content']=[{'type':'text','text':text}]
    else:item.update(text=text,phase=phase)
    return {'turnId':'owned-turn','item':item,'startedAtMs':10,'completedAtMs':20}


class Reader:
    def __init__(self,pages):self.pages=copy.deepcopy(pages);self.calls=[]
    def rpc(self,method,params):
        self.calls.append((method,params));return self.pages.pop(0)


class CurrentIntegrator(unittest.TestCase):
    def test_later_integrator_correction_follows_voice_in_chronological_order(self):
        native=Reader([{'data':[message('answer','Saturday is confirmed.','assistant'),
            message('correction','It is Saturday, not Friday.'),
            message('voice','Earlier voice said Friday.')],'nextCursor':None}])
        result=read(native,'owned')
        self.assertEqual([r['item'] for r in result['messages']],['voice','correction','answer'])
        self.assertEqual(result['messages'][-2]['text'],'It is Saturday, not Friday.')
        self.assertFalse(result['earlier_history_available'])
        self.assertEqual(native.calls[0][1]['threadId'],'owned')
        self.assertEqual([m for m,_ in native.calls],['thread/items/list'])

    def test_tools_and_private_analysis_never_enter_voice_startup(self):
        native=Reader([{'data':[message('a','Useful progress','assistant','commentary'),
            message('private','PRIVATE ANALYSIS','assistant','analysis'),
            {'item':{'type':'commandExecution','id':'tool','output':'PRIVATE TOOL'}}],
            'nextCursor':None}])
        result=read(native,'owned');self.assertEqual(len(result['messages']),1)
        self.assertNotIn('PRIVATE',json.dumps(result))

    def test_exact_text_not_clipped_when_older_history_exceeds_capacity(self):
        latest='Latest complete correction.'
        native=Reader([{'data':[message('new',latest),message('old','old '*10000)],'nextCursor':None}])
        result=read(native,'owned',max_bytes=1024)
        self.assertEqual([r['text'] for r in result['messages']],[latest])
        self.assertTrue(result['earlier_history_available'])
        with self.assertRaisesRegex(ValueError,'semantic preparation'):
            read(Reader([{'data':[message('new','large '*10000)],'nextCursor':None}]),'owned',max_bytes=1024)

    def test_voice_spec_budget_counts_embedding_context_as_json_text(self):
        native=Reader([{'data':[message('new','Latest complete correction.'),
            message('old','"'*180)],'nextCursor':None}])
        result=read(native,'owned',max_bytes=1024)
        embedded=json.dumps(json.dumps(result,ensure_ascii=False,separators=(',',':')),
            ensure_ascii=False).encode()
        self.assertLessEqual(len(embedded),1024)
        self.assertEqual(result['messages'][0]['text'],'Latest complete correction.')
        self.assertTrue(result['earlier_history_available'])

    def test_bounded_paging_and_repeated_cursor_refusal(self):
        native=Reader([{'data':[],'nextCursor':str(i)} for i in range(4)])
        self.assertTrue(read(native,'owned')['earlier_history_available'])
        self.assertEqual(len(native.calls),4)
        with self.assertRaisesRegex(ValueError,'cursor'):
            read(Reader([{'data':[],'nextCursor':'same'},{'data':[],'nextCursor':'same'}]),'owned')

    def test_duplicate_source_and_missing_reader_refuse(self):
        with self.assertRaisesRegex(ValueError,'repeated a source'):
            read(Reader([{'data':[message('same','a'),message('same','b')],'nextCursor':None}]),'owned')
        with self.assertRaisesRegex(ValueError,'unavailable'):read(Reader([None]),'owned')

    def test_expired_owner_read_budget_does_not_schedule_another_native_read(self):
        native=Reader([{'data':[],'nextCursor':'next'}]);calls=[]
        def check():
            calls.append(1)
            if len(calls)>1:raise ProviderUnavailable('Read budget ended')
        with self.assertRaises(ProviderUnavailable):read(native,'owned',check=check)
        self.assertEqual(len(native.calls),1)


class IntegratingLedger(unittest.TestCase):
    def setUp(self):
        self.frozen={'binding':'a'*64,'entry_binding':[100,{'chat_id':100,'thread_id':1},1,'native'],
            'native_thread':'native'}
        self.ident='11111111-1111-4111-8111-111111111111'
        self.p=Provider.__new__(Provider);self.p.receiver={'codex':{'binary':'existing-codex'}}
        self.p.public_live_binding=lambda b:self.frozen
        self.source='delivery:22222222-2222-4222-8222-222222222222'
        self.status={'id':self.ident,'entry_binding':self.frozen['entry_binding'],
            'native_binding_current':True,'text':'Latest human correction after leaving voice.',
            'phase':'accepted','voice':{'transcription':{'actual_transcriber':'synthetic'}}}
        self.input_page={'binding':self.frozen['binding'],'entry_binding':copy.deepcopy(self.frozen['entry_binding']),
            'items':[{'id':self.ident,'capture_order':2,'received_at':'2026-11-07T18:00:00Z'}],'more':False}
        self.output_page={'binding':self.frozen['binding'],'items':[{'id':self.source,
            'revision':'b'*64,'kind':'worker_result','current':True,'correction_pending':False,
            'completed':False,'observed_at':'2026-11-07T18:00:01Z'}],'more':False}
        self.reads=[]
        def presentation(command):
            self.reads.append(command)
            return copy.deepcopy(self.input_page if command=='input list 0 before' else self.status)
        self.p.presentation=presentation
        self.p.presentation_list=lambda *args:copy.deepcopy(self.output_page)
        self.p.presentation_part=lambda source,revision,offset:{'id':source,'revision':revision,
            'entry_binding':self.frozen['entry_binding'][:3]+[self.frozen['binding']],
            'offset':offset,'next_offset':None,'text':'New worker progress, not a completed goal.',
            'kind':'worker_progress','current':True,'native_binding_current':True}

    def test_latest_original_and_worker_progress_do_not_wait_for_native_incorporation(self):
        value=integrating_sources(self.p,self.frozen)
        self.assertEqual([v['kind'] for v in value['sources']],['retained_input','worker_progress'])
        self.assertEqual(value['sources'][0]['capture_order'],2)
        self.assertIn('Machine interpretation',value['sources'][0]['text_meaning'])
        self.assertFalse(value['sources'][1]['completed'])
        self.assertEqual(self.reads,['input list 0 before','input status '+self.ident],
            'Raw read-only readers must not invoke media-retiring status/list conveniences')

    def test_changed_owner_or_source_refuses(self):
        self.input_page['entry_binding'][0]=200
        with self.assertRaisesRegex(ValueError,'owner changed'):integrating_sources(self.p,self.frozen)

    def test_same_general_entry_cannot_silently_become_another_native_thread(self):
        selected=copy.deepcopy(self.frozen)
        observer=Reader([{'data':[message('current','The same general conversation.')],'nextCursor':None}])
        observer.close=lambda:None
        def switched(_):
            # A changed selected entry refuses rather than using the previous
            # voice snapshot or admitting work into a replacement conversation.
            return {**selected,'entry_binding':selected['entry_binding'][:3]+['other-native'],
                'native_thread':'other-native'}
        self.p.public_live_binding=switched
        with patch('dashboard.provider.Native',return_value=observer),self.assertRaises(ProviderUnavailable):
            self.p.public_live_integrator_context(selected)
        self.assertEqual(observer.calls,[],'Refuse before reading any other native conversation')

    def test_source_timestamps_order_windows_instead_of_reader_or_page_order(self):
        self.output_page['items'][0]['observed_at']='2026-11-07T17:59:59Z'
        value=integrating_sources(self.p,self.frozen)
        self.assertEqual([v['kind'] for v in value['sources']],['worker_progress','retained_input'])
        self.input_page['items'][0]['received_at']='2026-11-07T17:59:58Z'
        value=integrating_sources(self.p,self.frozen)
        self.assertEqual([v['kind'] for v in value['sources']],['retained_input','worker_progress'])

    def test_naive_or_missing_timestamp_stays_unknown(self):
        self.input_page['items'][0]['received_at']='2026-11-07T18:00:00'
        value=integrating_sources(self.p,self.frozen)
        original=next(v for v in value['sources'] if v['kind']=='retained_input')
        self.assertTrue(original['ordering_unknown'])

    def test_provider_rechecks_binding_and_closes_only_its_observer(self):
        observer=Reader([{'data':[message('current','Current native context')],'nextCursor':None}])
        observer.closed=False;observer.close=lambda:setattr(observer,'closed',True)
        with patch('dashboard.provider.Native',return_value=observer):
            result=self.p.public_live_integrator_context(self.frozen)
        self.assertTrue(observer.closed)
        self.assertIn('Current native context',result['messages'][0]['text'])
        self.assertEqual(len(result['integrating_sources']['sources']),2)
        calls=[]
        def changed(_):
            calls.append(1);return self.frozen if len(calls)==1 else dict(self.frozen,native_thread='changed')
        self.p.public_live_binding=changed
        observer=Reader([{'data':[],'nextCursor':None}]);observer.close=lambda:None
        with patch('dashboard.provider.Native',return_value=observer),self.assertRaises(ProviderUnavailable):
            self.p.public_live_integrator_context(self.frozen)


if __name__=='__main__':unittest.main()
