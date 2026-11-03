"""Source ownership, uncertain admission and close races; no model/network calls."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.native_foreground import ForegroundBridge, ForegroundUnavailable
from dashboard.provider import Provider, ProviderUnavailable
from dashboard.live_transcription import wav_bytes


class Stream:
    max_tools=32
    activity_mode='manual'
    model='gemini-3.8-live'
    def __init__(self):self.results=[];self.continuations=[]
    def tool_result(self,ident,result,*,will_continue=False):
        self.results.append((ident,result));self.continuations.append(will_continue)


class Owner:
    def __init__(self,root):
        self.receiver={'db_path':str(root/'native.sqlite3')}
        self.inputs={};self.delegations=[];self.parts={};self.fail=False
    def conversation_voice_submit(self,meta,data,**kwargs):
        value={**meta,'phase':'foreground_captured','foreground_dialogue':kwargs['foreground_dialogue'],
               'voice':{'audio_sha256':hashlib.sha256(data).hexdigest()}}
        self.inputs[meta['id']]=value
        return value
    def conversation_foreground_complete(self,ident,binding,dialogue):
        value=self.inputs[ident]
        value.update(phase='foreground',text=self.text)
        return value
    def conversation_input_status(self,ident):return self.inputs[ident]
    def conversation_foreground_originals(self,dialogue,binding,before):
        return {'kind':'foreground_originals','sources':[{'id':k} for k,v in self.inputs.items()
                if v['foreground_dialogue']==dialogue]}
    def conversation_foreground_delegate(self,body):
        self.delegations.append(body)
        if self.fail:raise TimeoutError()
        return {'id':body['id'],'phase':'accepted','native_acceptance':'pending'}
    def presentation_part(self,ident,revision,offset):
        value=self.parts[ident];text=value['text'];end=min(offset+1600,len(text))
        return {**value,'text':text[offset:end],'offset':offset,
                'next_offset':end if end<len(text) else None}


class Bridge(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.owner=Owner(self.root);self.stream=Stream();self.auth=0
        async def authorize():self.auth+=1
        self.dialogue=str(uuid.uuid4());self.binding='a'*64
        self.bridge=ForegroundBridge(self.owner,self.stream,self.root/'prepared',self.dialogue,self.binding,authorize)
    async def asyncTearDown(self):
        await self.bridge.close();self.tmp.cleanup()
    async def captured(self,text='Exact human interpretation'):
        ident=str(uuid.uuid4());pcm=b'\1\0'*160
        capture=self.bridge.capture(ident,pcm,{})
        await capture.reservation;self.owner.text=text
        await self.bridge.transcript(ident,text)
        return ident,pcm,capture
    async def test_invalid_proposal_returns_feedback_without_owner_operation(self):
        result=await self.bridge.tool({'type':'tool_rejected','call_id':'invalid'})
        self.assertEqual(result['kind'],'invalid_arguments')
        self.assertFalse(result['operation_started'])
        self.assertEqual(self.owner.delegations,[])
        self.assertEqual(self.owner.inputs,{})
        self.assertEqual(self.stream.results,[('invalid',result)])

    async def test_capture_retirement_keeps_originals_latest_correlation_and_replay_bound(self):
        first,pcm,_=await self.captured('First')
        second,_,_=await self.captured('Second')
        third,_,latest=await self.captured('Third')
        before=self.bridge.input_bytes
        self.bridge.retire_captures([first,second,third])
        self.assertEqual(set(self.bridge.captures),{third})
        self.assertEqual(self.bridge.capture_ids,{first,second,third})
        self.assertEqual(self.bridge.latest,third)
        self.assertEqual(self.bridge.input_bytes,before)
        self.assertEqual(set(self.owner.inputs),{first,second,third})
        self.assertEqual(latest.phase,'foreground')
        with self.assertRaises(ForegroundUnavailable):self.bridge.capture(first,pcm,{})
        self.bridge.max_captures=3
        with self.assertRaises(ForegroundUnavailable):self.bridge.capture(str(uuid.uuid4()),pcm,{})
        result=await self.bridge.tool({'type':'source_query','call_id':'current','before':0})
        self.assertEqual({v['id'] for v in result['sources']},{first,second,third})

    async def test_result_index_reuses_canonical_page_and_revalidates_offered_worker_text(self):
        reads=[];ident='delivery:'+str(uuid.uuid4());revision='c'*64
        self.owner.presentation_list=lambda *args:reads.append(args) or {
            'cursor':{'delivery':14,'native':27},'more':True,'items':[
                {'id':ident,'revision':revision,'kind':'worker_result','current':True,
                 'label':'Print','preview':'Short preview','completed':False,'artifacts':[
                     {'id':str(uuid.uuid4()),'name':'part.stl','available':True,'bytes':40},
                     {'name':'expired.stl','available':False}], 'private':'not forwarded'},
                {'id':'native:124','revision':'a'*64,'kind':'integrator_answer','correction_pending':True},
                {'id':'native:125','revision':'a'*64,'kind':'worker_progress'},
                {'id':'native:126','revision':'a'*64,'kind':'worker_result','native_binding_current':False}]}
        index=await self.bridge.tool({'type':'recent_results_query','call_id':'index','delivery':15,'native':28})
        self.assertEqual(reads,[(15,28,'before')]);self.assertEqual(len(index['items']),1)
        item=index['items'][0];self.assertFalse(item['preview_complete']);self.assertFalse(item['completed'])
        self.assertEqual([f['name'] for f in item['files']],['part.stl']);self.assertNotIn('private',item)
        self.assertEqual(index['omitted'],3);self.assertEqual(index['cursor'],{'delivery':14,'native':27})
        self.owner.parts[ident]={'id':ident,'revision':revision,'kind':'worker_result',
            'entry_binding':[1],'current':True,'text':'Complete source text. '*110}
        event={'type':'integrating_source_query','call_id':'read-result','source':ident,'revision':revision,'offset':0}
        page=await self.bridge.tool(event)
        self.assertEqual(page['kind'],'integrating_source');self.assertEqual(page['text'],self.owner.parts[ident]['text'][:1600])
        self.assertEqual(page['next_offset'],1600)
        self.owner.parts[ident]['correction_pending']=True
        stale=await self.bridge.tool({**event,'call_id':'stale-read'})
        self.assertEqual(stale['kind'],'not_ready')
        self.assertEqual(self.owner.delegations,[]);self.assertEqual(self.owner.inputs,{})

    async def test_result_index_truncation_never_offers_unreturned_source_or_skips_records(self):
        self.owner.presentation_list=lambda *args:{'cursor':{'delivery':8,'native':8},'items':[
            {'id':'native:'+str(n+1),'revision':'c'*64,'kind':'integrator_answer',
             'preview':'x'*256,'label':'y'*12000} for n in range(3)]}
        result=await self.bridge.tool({'type':'recent_results_query','call_id':'large-index','delivery':0,'native':0})
        self.assertTrue(result['truncated']);self.assertIsNone(result['cursor'])
        self.assertLessEqual(len(json.dumps(result).encode()),16384)
        self.assertEqual(len(self.bridge._offered),len(result['items']))

    async def test_pending_ledger_projection_is_read_only_bounded_and_keeps_dates(self):
        self.owner.internal_pending=lambda after:{'cursor':41,'more':True,'items':[
            {'id':'a'*32,'kind':'task','title':'Inspect result','preview':'x'*20000,
             'created_at':'2026-11-02','revision':'b'*64,'can_dismiss':True}]*64}
        result=await self.bridge.tool({'type':'session_pending_query','call_id':'pending','after':0})
        self.assertTrue(result['read_only']);self.assertTrue(result['truncated'])
        self.assertIsNone(result['cursor']);self.assertLessEqual(len(json.dumps(result).encode()),16384)
        self.assertEqual(result['items'][0]['created_at'],'2026-11-02')
        self.assertNotIn('can_dismiss',result['items'][0])
        self.assertEqual(self.owner.delegations,[]);self.assertEqual(self.owner.inputs,{})

    async def test_automatic_source_query_and_delegation_cannot_select_previous_original(self):
        ident,_,_=await self.captured()
        self.bridge.pending_acoustic=str(uuid.uuid4())
        for event in ({'type':'source_query','call_id':'early-query','before':None},
                      {'type':'delegation_proposed','call_id':'early-delegate','original_ids':[ident],'formulation':'Old request'}):
            result=await self.bridge.tool(event)
            self.assertEqual(result['kind'],'not_ready')
        self.assertEqual(self.owner.delegations,[])
        self.assertEqual(self.bridge.latest,ident)

    async def test_automatic_start_during_original_read_returns_not_ready_instead_of_old_page(self):
        ident,_,_=await self.captured()
        entered=threading.Event();release=threading.Event()
        reader=self.owner.conversation_foreground_originals
        def delayed(*args):
            entered.set();release.wait(2);return reader(*args)
        self.owner.conversation_foreground_originals=delayed
        task=asyncio.create_task(self.bridge.tool({'type':'source_query','call_id':'racing-read','before':None}))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait,2))
            self.bridge.pending_acoustic=str(uuid.uuid4())
        finally:release.set()
        result=await task
        self.assertEqual(result['kind'],'not_ready');self.assertNotIn('sources',result)
        self.assertEqual(self.owner.delegations,[])

    async def test_session_status_reuses_observer_and_redacts_stale_state_without_work(self):
        calls=[]
        def observed():
            calls.append(True)
            return {'connected':True,'observed_at':123,'sources':[
                {'label':'Conversation','fresh':True,'observed_at':122,'execution':'running','goal_state':'active','private_field':'not forwarded'},
                {'label':'Beta','fresh':False,'observed_at':1,'execution':'running','goal_state':'complete','pending':True}]}
        self.owner.sonic_activity=observed
        result=await self.bridge.tool({'type':'session_status_query','call_id':'status'})
        self.assertEqual(len(calls),1);self.assertEqual(result['kind'],'session_status')
        self.assertEqual(result['sessions'][0]['execution'],'running');self.assertNotIn('private_field',result['sessions'][0])
        self.assertEqual(result['sessions'][1]['execution'],'unknown');self.assertEqual(result['sessions'][1]['goal_state'],'unknown');self.assertIsNone(result['sessions'][1]['pending'])
        self.assertEqual(self.owner.delegations,[]);self.assertEqual(self.owner.inputs,{})
        self.assertEqual(result['integrator_connection'],'available_through_foreground_tools')
    async def test_disconnected_observer_and_large_status_have_explicit_limits(self):
        self.owner.sonic_activity=lambda:{'connected':False,'sources':[{'label':'Beta','fresh':True,'execution':'running','goal_state':'complete'}]*65}
        result=await self.bridge.tool({'type':'session_status_query','call_id':'disconnected'})
        self.assertTrue(result['truncated']);self.assertLessEqual(len(json.dumps(result).encode()),16384)
        self.assertTrue(all(not v['fresh'] and v['execution']=='unknown' for v in result['sessions']))
        self.assertEqual(self.owner.delegations,[])

    async def test_slow_first_reservation_cannot_be_overtaken(self):
        entered=threading.Event();release=threading.Event();order=[]
        real=self.owner.conversation_voice_submit
        first=str(uuid.uuid4());second=str(uuid.uuid4())
        def delayed(meta,data,**kwargs):
            if meta['id']==first:
                entered.set();release.wait(2)
            order.append(meta['id'])
            return real(meta,data,**kwargs)
        with patch.object(self.owner,'conversation_voice_submit',delayed):
            a=self.bridge.capture(first,b'\1\0'*160,{})
            await asyncio.to_thread(entered.wait,1)
            b=self.bridge.capture(second,b'\2\0'*160,{})
            await asyncio.sleep(.01)
            self.assertEqual(order,[])
            release.set()
            await asyncio.gather(a.reservation,b.reservation)
        self.assertEqual(order,[first,second])

    async def test_exact_audio_is_retained_and_completed_once(self):
        ident,pcm,capture=await self.captured()
        self.assertEqual(capture.phase,'foreground');self.assertEqual(capture.pcm,b'')
        raw=list((self.root/'native.sqlite3.voice').glob('*'))
        self.assertTrue(any(p.is_file() and p.read_bytes()==wav_bytes(pcm) for p in raw))
        receipt=__import__('json').loads((self.root/'prepared'/f'{ident}.json').read_text())
        self.assertEqual(receipt['source_sha256'],hashlib.sha256(wav_bytes(pcm)).hexdigest())
        self.assertIs(self.bridge.transcript(ident,self.owner.text),capture.completion)
        with self.assertRaises(ForegroundUnavailable):self.bridge.transcript(ident,'changed text')
    async def test_playback_context_cannot_overflow_or_replace_original_references(self):
        original=str(uuid.uuid4())
        self.owner.conversation_foreground_originals=lambda *args:{'sources':[{'id':original}],'context':'x'*15700}
        self.bridge.speech_context=lambda:[{'text_excerpt':'y'*600,'played_bytes':0}]
        result=await self.bridge.tool({'type':'source_query','call_id':'bounded','before':0})
        self.assertEqual(result['sources'],[{'id':original}])
        self.assertNotIn('assistant_speech',result,'Optional playback context yields to the existing tool response bound')
        self.assertLessEqual(len(json.dumps(result).encode()),16384)
        self.assertEqual(self.owner.delegations,[])
    async def test_owner_normalizes_outer_whitespace_without_losing_the_original(self):
        complete=self.owner.conversation_foreground_complete
        def normalized(*args):
            result=complete(*args)
            result['text']=result['text'].strip()
            return result
        self.owner.conversation_foreground_complete=normalized
        ident,pcm,capture=await self.captured(' Mientras Alfa trabaja ')
        retained=await capture.completion
        self.assertEqual(retained['text'],'Mientras Alfa trabaja')
        receipt=__import__('json').loads((self.root/'prepared'/f'{ident}.json').read_text())
        self.assertEqual(receipt['text'],' Mientras Alfa trabaja ')
        self.assertEqual(receipt['source_sha256'],hashlib.sha256(wav_bytes(pcm)).hexdigest())
        self.assertEqual(capture.phase,'foreground')

    async def test_read_does_not_admit_work_and_latest_correction_is_required(self):
        first,_,_=await self.captured();last,_,_=await self.captured('Correction')
        result=await self.bridge.tool({'type':'source_query','call_id':'read','before':0})
        self.assertEqual(len(result['sources']),2);self.assertEqual(self.owner.delegations,[])
        result=await self.bridge.tool({'type':'delegation_proposed','call_id':'old',
                                      'original_ids':[first],'formulation':'Derivative'})
        self.assertEqual(result['kind'],'not_ready');self.assertEqual(self.owner.delegations,[])
        task=asyncio.create_task(self.bridge.tool({'type':'delegation_proposed','call_id':'new',
                                      'original_ids':[first,last],'formulation':'Derivative'}))
        await self.results(3)
        self.assertEqual(self.stream.results[-1][1]['kind'],'integrator_admission')
        self.assertEqual(self.owner.delegations[0]['id'],last)
        self.assertEqual(self.owner.inputs[last]['text'],'Correction')
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
    async def test_admission_itself_streams_question_and_answer_return_without_a_model_watch(self):
        ident,_,_=await self.captured()
        task=asyncio.create_task(self.bridge.tool({'type':'delegation_proposed','call_id':'work',
            'original_ids':[ident],'formulation':'Please prepare the proposal.'}))
        await self.results(1)
        self.assertTrue(self.stream.continuations[0]);self.assertFalse(task.done())
        initial=self.stream.results[0][1]
        self.assertEqual(initial['recipient'],'integrating_conversation')
        self.assertEqual(initial['worker_delivery'],'not_established_by_this_receipt')
        self.assertEqual(initial['native_acceptance'],'pending')
        source=self.source();source['kind']='question'
        self.owner.parts[source['id']]={'id':source['id'],'revision':source['revision'],
            'entry_binding':[1,2],'kind':'native_question','text':'Which ordering?','current':True}
        self.assertTrue(self.bridge.integrating_source(source));await self.results(2)
        self.assertEqual(self.stream.results[-1][0],'work')
        self.assertEqual(self.stream.results[-1][1]['text'],'Which ordering?')
        answer,_,_=await self.captured('Preparation time')
        admitted=await self.bridge.tool({'type':'delegation_proposed','call_id':'answer',
            'original_ids':[answer],'formulation':'The human selected preparation time.'})
        self.assertEqual(admitted['kind'],'integrator_admission')
        self.assertEqual(admitted['recipient'],'integrating_conversation')
        self.assertEqual(admitted['worker_delivery'],'not_established_by_this_receipt','A follow-up answer admission is not a worker receipt either')
        self.assertEqual(len(self.owner.delegations),2)
        final={'id':'native:124','revision':'c'*64,'kind':'result'}
        self.owner.parts[final['id']]={'id':final['id'],'revision':final['revision'],
            'entry_binding':[1,2],'kind':'integrator_answer','text':'Preference incorporated.','current':True}
        self.bridge.integrating_source(final);await self.results(4)
        self.assertEqual(self.stream.results[-1][0],'work')
        self.assertEqual(self.stream.continuations,[True,True,False,True])
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
    async def test_lost_admission_is_not_retried(self):
        ident,_,_=await self.captured();self.owner.fail=True
        result=await self.bridge.tool({'type':'delegation_proposed','call_id':'work',
                                      'original_ids':[ident],'formulation':'Derivative'})
        self.assertEqual(result['kind'],'unconfirmed');self.assertEqual(len(self.owner.delegations),1)
        with self.assertRaises(ForegroundUnavailable):
            await self.bridge.tool({'type':'delegation_proposed','call_id':'work',
                                    'original_ids':[ident],'formulation':'Derivative'})
        self.assertEqual(len(self.owner.delegations),1)
        successor=Stream();self.bridge.replace_stream(successor,str(uuid.uuid4()))
        result=await self.bridge.tool({'type':'delegation_proposed','call_id':'work',
            'original_ids':[ident],'formulation':'A replacement model asks again.'})
        self.assertEqual(result['kind'],'unconfirmed')
        self.assertEqual(len(self.owner.delegations),1,'A new provider generation/call ID cannot reauthor an uncertain admission')
    def source(self):return {'id':'native:123','revision':'b'*64,'kind':'result','label':'Integrator'}
    async def results(self,count):
        async def wait():
            while len(self.stream.results)<count:await asyncio.sleep(.001)
        await asyncio.wait_for(wait(),1)
    async def test_return_watch_is_event_driven_and_revalidates_source(self):
        source=self.source();task=asyncio.create_task(self.bridge.tool({'type':'integrator_watch','call_id':'watch'}))
        await asyncio.sleep(0);self.assertFalse(task.done())
        self.owner.parts[source['id']]={**source,'kind':'integrator_answer','entry_binding':[1],
                                      'current':True,'text':'Real return','next_offset':None}
        self.assertTrue(self.bridge.integrating_source(source));self.assertFalse(self.bridge.integrating_source(source))
        await self.results(1);self.assertEqual(self.stream.results[-1][1]['text'],'Real return')
        self.assertFalse(task.done(),'The same subscription remains available for later returns')
        self.assertFalse(self.bridge.integrating_source(source))
        second={**source,'id':'native:124','revision':'c'*64}
        self.owner.parts[second['id']]={**second,'kind':'integrator_progress','native_returns':['result:actual'],
                                       'entry_binding':[1],'current':True,'text':'Later canonical result'}
        self.bridge.integrating_source(second);await self.results(2)
        self.assertEqual(self.stream.results[-1][1]['text'],'Later canonical result')
        self.assertEqual(self.stream.continuations,[True,True])
        self.assertEqual(len(self.bridge._tool_calls),1)
        await self.bridge.close();await task
    async def test_long_offered_return_can_be_read_on_demand_without_new_work(self):
        source=self.source();text='First-page context. '*100+' Último detalle: azafrán.'
        self.owner.parts[source['id']]={**source,'kind':'integrator_answer','entry_binding':[1],
                                      'current':True,'text':text}
        task=asyncio.create_task(self.bridge.tool({'type':'integrator_watch','call_id':'watch'}))
        self.bridge.integrating_source(source);await self.results(1)
        offered=self.stream.results[0][1]
        self.assertEqual(offered['text'],text[:1600]);self.assertEqual(offered['next_offset'],1600)
        page=await self.bridge.tool({'type':'integrating_source_query','call_id':'remainder',
            'source':source['id'],'revision':source['revision'],'offset':offered['next_offset']})
        self.assertEqual(page['kind'],'integrating_source')
        self.assertEqual(offered['text']+page['text'],text)
        self.assertIsNone(page['next_offset']);self.assertFalse(page['text_bounded'])
        self.assertEqual(self.owner.delegations,[])
        # The same offered revision loses eligibility as soon as its source changes.
        for changes in ({'current':False},{'correction_pending':True},
                        {'native_binding_current':False},{'revision':'c'*64},{'kind':'worker_progress'}):
            self.owner.parts[source['id']]={**self.owner.parts[source['id']],**changes}
            result=await self.bridge.tool({'type':'integrating_source_query','call_id':str(uuid.uuid4()),
                'source':source['id'],'revision':source['revision'],'offset':1600})
            self.assertEqual(result['kind'],'not_ready')
            self.assertNotIn('text',result)
            self.owner.parts[source['id']]={**source,'kind':'integrator_answer','entry_binding':[1],
                                          'current':True,'text':text}
        await self.bridge.close();await task

    async def test_setup_context_can_be_read_without_reannouncing_and_still_revalidates(self):
        source=self.source()
        self.owner.parts[source['id']]={**source,'kind':'integrator_answer','entry_binding':[1],
                                      'current':True,'text':'Retained result, not new work.'}
        self.bridge.integrating_source(source,in_context=True)
        self.assertFalse(self.bridge.integrating_source(source),'Do not speak old setup context again as a new return')
        task=asyncio.create_task(self.bridge.tool({'type':'integrator_watch','call_id':'watch'}))
        await asyncio.sleep(0)
        page=await self.bridge.tool({'type':'integrating_source_query','call_id':'read-context',
            'source':source['id'],'revision':source['revision'],'offset':0})
        self.assertEqual(page['text'],'Retained result, not new work.')
        self.assertEqual([call for call,_ in self.stream.results],['read-context'])
        self.owner.parts[source['id']]['current']=False
        rejected=await self.bridge.tool({'type':'integrating_source_query','call_id':'stale-context',
            'source':source['id'],'revision':source['revision'],'offset':0})
        self.assertEqual(rejected['kind'],'not_ready');self.assertNotIn('text',rejected)
        self.assertEqual(self.owner.delegations,[])
        await self.bridge.close();await task

    async def test_integrating_read_cannot_select_an_unoffered_source(self):
        with patch.object(self.owner,'presentation_part',side_effect=AssertionError('Unscoped read')):
            result=await self.bridge.tool({'type':'integrating_source_query','call_id':'outside',
                'source':'native:999','revision':'b'*64,'offset':0})
        self.assertEqual(result['kind'],'not_ready');self.assertEqual(self.owner.delegations,[])

    async def test_changed_or_worker_progress_cannot_be_announced_as_return(self):
        task=asyncio.create_task(self.bridge.tool({'type':'integrator_watch','call_id':'watch'}))
        await asyncio.sleep(0)
        for field,value in (('current',False),('correction_pending',True),('kind','worker_progress'),('revision','c'*64)):
            source=self.source()
            self.owner.parts[source['id']]={**source,'kind':'integrator_answer','entry_binding':[1],
                                          'text':'Obsolete',field:value}
            self.bridge.integrating_source(source)
            while self.bridge._queued:await asyncio.sleep(.001)
            await asyncio.sleep(.001)
            self.assertFalse(task.done())
            self.assertEqual(self.stream.results,[])
        await self.bridge.close();await task
    async def test_close_wakes_pending_source_read_without_another_provider_effect(self):
        capture=self.bridge.capture(str(uuid.uuid4()),b'\1\0'*160,{})
        await capture.reservation
        task=asyncio.create_task(self.bridge.tool({'type':'source_query','call_id':'read','before':0}))
        await asyncio.sleep(0);self.assertFalse(task.done())
        await self.bridge.close()
        result=await asyncio.wait_for(task,1)
        self.assertEqual(result['kind'],'not_ready');self.assertEqual(self.stream.results,[])

    async def test_cancelled_unoffered_read_can_rearm_notice_without_replaying_a_response(self):
        source=self.source()
        self.owner.parts[source['id']]={**source,'kind':'integrator_answer','entry_binding':[1],
                                      'current':True,'text':'The actual retained result.'}
        self.bridge.integrating_source(source);self.bridge.noticed_generation=self.bridge.offer_generation
        entered=asyncio.Event();wait=asyncio.Event();read=self.bridge._integrating_part
        async def delayed(*args):entered.set();await wait.wait();return await read(*args)
        self.bridge._integrating_part=delayed
        task=asyncio.create_task(self.bridge.tool({'type':'integrator_watch','call_id':'interrupted'}))
        await asyncio.wait_for(entered.wait(),1);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(self.stream.results,[],'Nothing was attempted at the provider')
        self.assertTrue(self.bridge.notice_needed,'Known-unoffered requeue is a fresh attention event')
        self.assertEqual(len(self.bridge._queued),1)
        self.bridge._integrating_part=read
        next_watch=asyncio.create_task(self.bridge.tool({'type':'integrator_watch','call_id':'continue'}))
        await self.results(1);self.assertEqual(self.stream.results[0][1]['text'],'The actual retained result.')
        next_watch.cancel()
        with self.assertRaises(asyncio.CancelledError):await next_watch
        self.assertFalse(self.bridge.notice_needed,'An attempted/offered response is never requeued')
        self.assertEqual(self.owner.delegations,[])

    async def test_close_wakes_watch_without_cancelling_native_jobs(self):
        task=asyncio.create_task(self.bridge.tool({'type':'integrator_watch','call_id':'watch'}))
        await asyncio.sleep(0);await self.bridge.close()
        result=await asyncio.wait_for(task,1)
        self.assertEqual(result['kind'],'not_ready');self.assertEqual(self.owner.delegations,[])
    async def test_close_during_receipt_write_preserves_immutable_pcm(self):
        ident=str(uuid.uuid4());pcm=b'\2\0'*160
        capture=self.bridge.capture(ident,pcm,{})
        await capture.reservation;self.owner.text='Retained'
        real_run=self.bridge._run;entered=asyncio.Event();release=asyncio.Event();seen=[]
        async def delayed(limit,function,*args,**kwargs):
            if function.__name__=='save_prepared':
                seen.append(args[3]);entered.set();await release.wait()
            return await real_run(limit,function,*args,**kwargs)
        with patch.object(self.bridge,'_run',delayed):
            task=self.bridge.transcript(ident,'Retained');await entered.wait()
            await self.bridge.close();release.set()
            with self.assertRaises(ForegroundUnavailable):await task
        self.assertEqual(seen,[pcm]);self.assertTrue((self.root/'prepared'/f'{ident}.json').exists())


class OriginalPages(unittest.TestCase):
    def test_original_lookup_preserves_owner_cursor_without_starting_work(self):
        dialogue=str(uuid.uuid4());selected=str(uuid.uuid4());calls=[]
        owner=Provider.__new__(Provider)
        def read(command):
            calls.append(command)
            return {'binding':'a'*64,'cursor':12,'more':True,'items':[
                {'id':selected,'phase':'foreground','foreground_dialogue':dialogue,
                 'capture_order':17,'preview':'original','voice':{}},
                {'id':str(uuid.uuid4()),'phase':'foreground','foreground_dialogue':str(uuid.uuid4()),
                 'preview':'Another dialogue'}]}
        owner.presentation=read
        result=owner.conversation_foreground_originals(dialogue,'a'*64)
        self.assertEqual([r['id'] for r in result['sources']],[selected])
        self.assertEqual(result['before'],12);self.assertTrue(result['more'])
        self.assertEqual(calls,['input list 0 before'])
        with self.assertRaises(ProviderUnavailable):
            owner.conversation_foreground_originals(dialogue,'b'*64)
        with self.assertRaises(ValueError):
            owner.conversation_foreground_originals(dialogue,'a'*64,True)


if __name__=='__main__':unittest.main()
