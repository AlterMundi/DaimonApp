"""Source ownership, uncertain admission and close races; no model/network calls."""
import asyncio
import hashlib
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
    def __init__(self):self.results=[]
    def tool_result(self,ident,result):self.results.append((ident,result))


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
    def presentation_part(self,ident,revision,offset):return self.parts[ident]


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
    async def test_read_does_not_admit_work_and_latest_correction_is_required(self):
        first,_,_=await self.captured();last,_,_=await self.captured('Correction')
        result=await self.bridge.tool({'type':'source_query','call_id':'read','before':0})
        self.assertEqual(len(result['sources']),2);self.assertEqual(self.owner.delegations,[])
        result=await self.bridge.tool({'type':'delegation_proposed','call_id':'old',
                                      'original_ids':[first],'formulation':'Derivative'})
        self.assertEqual(result['kind'],'not_ready');self.assertEqual(self.owner.delegations,[])
        result=await self.bridge.tool({'type':'delegation_proposed','call_id':'new',
                                      'original_ids':[first,last],'formulation':'Derivative'})
        self.assertEqual(result['kind'],'integrator_admission')
        self.assertEqual(self.owner.delegations[0]['id'],last)
        self.assertEqual(self.owner.inputs[last]['text'],'Correction')
    async def test_lost_admission_is_not_retried(self):
        ident,_,_=await self.captured();self.owner.fail=True
        result=await self.bridge.tool({'type':'delegation_proposed','call_id':'work',
                                      'original_ids':[ident],'formulation':'Derivative'})
        self.assertEqual(result['kind'],'unconfirmed');self.assertEqual(len(self.owner.delegations),1)
        with self.assertRaises(ForegroundUnavailable):
            await self.bridge.tool({'type':'delegation_proposed','call_id':'work',
                                    'original_ids':[ident],'formulation':'Derivative'})
        self.assertEqual(len(self.owner.delegations),1)
    def source(self):return {'id':'native:123','revision':'b'*64,'kind':'result','label':'Integrator'}
    async def test_return_watch_is_event_driven_and_revalidates_source(self):
        source=self.source();task=asyncio.create_task(self.bridge.tool({'type':'integrator_watch','call_id':'watch'}))
        await asyncio.sleep(0);self.assertFalse(task.done())
        self.owner.parts[source['id']]={**source,'kind':'integrator_answer','entry_binding':[1],
                                      'current':True,'text':'Real return','next_offset':None}
        self.assertTrue(self.bridge.integrating_source(source));self.assertFalse(self.bridge.integrating_source(source))
        result=await task;self.assertEqual(result['text'],'Real return')
        self.assertFalse(self.bridge.integrating_source(source))
    async def test_changed_or_worker_progress_cannot_be_announced_as_return(self):
        for field,value in (('current',False),('correction_pending',True),('kind','worker_progress'),('revision','c'*64)):
            source=self.source()
            self.owner.parts[source['id']]={**source,'kind':'integrator_answer','entry_binding':[1],
                                          'text':'Obsolete',field:value}
            self.bridge.integrating_source(source)
            result=await self.bridge.tool({'type':'integrator_watch','call_id':field})
            self.assertEqual(result['kind'],'not_ready')
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
