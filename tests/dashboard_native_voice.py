"""Mounted native voice through authenticated sockets and durable source/text state.

Synthetic provider/detector peers only. No microphone, model, real native work or
receiving configuration is used. Ordinary HTTP qualification remains separate.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from dashboard.app import create_app
from dashboard.provider import Provider
from dashboard.live_transcription import wav_bytes
from dashboard_io import Receiver


class Stream:
    activity_mode='manual';model='gemini-3.8-live';max_tools=32;opened=[]
    def __init__(self,*args,**kwargs):
        self.queue=queue.Queue();self.queue.put([{'type':'ready'}]);self.total=0;self.closed=False;self.closed_event=threading.Event()
        self.tool_results=queue.Queue();self.opened.append(self)
    def receive(self):
        try:return self.queue.get(timeout=.05)
        except queue.Empty:return []
    def activity_start(self):
        self.queue.put([{'type':'voice_activity','activity':'ACTIVITY_START','audio_offset':f'{self.total/32000:g}s','source':'provider_manual_activity_ack'}])
    def append(self,pcm):self.total+=len(pcm)
    def activity_end(self):
        self.queue.put([{'type':'input_transcript','text':'Exact synthetic interpretation'},
            {'type':'voice_activity','activity':'ACTIVITY_END','audio_offset':f'{self.total/32000:g}s','source':'provider_manual_activity_ack'},
            {'type':'audio','pcm':b'\1\0'*320,'sample_rate':24000},
            {'type':'output_transcript','text':'A native foreground response.'},
            {'type':'turn_complete'}])
    def close(self):self.closed=True;self.closed_event.set();self.queue.put([{'type':'closing'}])
    def tool_result(self,*args):self.tool_results.put(args)


class Detector:
    opened=[]
    @classmethod
    async def open(cls,*args,**kwargs):
        value=cls();value.queue=asyncio.Queue();value.total=0;value.closed=False;value.closed_event=threading.Event()
        cls.opened.append(value);return value
    async def feed(self,pcm):
        self.total+=len(pcm);first=self.total==3200
        value={'type':'activity','audio_bytes':self.total,'generation':1,'speaking':first,'speech_seen':True}
        value['onset' if first else 'endpoint']={'generation':1,'audio_bytes':self.total,
                                              **({} if first else {'authority':'analysis_only','probability':.9})}
        await self.queue.put(value)
    async def receive(self):return await self.queue.get()
    async def boundary(self,value):await self.queue.put({'type':'boundary',**value})
    async def close(self):self.closed=True;self.closed_event.set()


class Owner(Receiver):
    def __init__(self,root):
        super().__init__();self.root=root;self.binding='a'*64;self.compatible=True
        self.receiver={'db_path':str(root/'native.sqlite3'),'voice':{'enabled':True}}
        (root/'native.sqlite3').touch();self.inputs={};self.completed=threading.Event();self.delegations=[];self.return_ready=False
        self.input_id=Provider.input_id
    def presentation(self,command):
        if command=='input voice capabilities':return {'binding':self.binding,'foreground_retention':'v1' if self.compatible else None,'foreground_completed_reader':self.compatible}
        if command.startswith('input list '):return {'binding':self.binding}
        raise AssertionError(command)
    def presentation_list(self,*args):
        cursor=args[1] if len(args)>1 else 0
        item={'id':'native:1','revision':'b'*64,'kind':'integrator_answer','current':True,'label':'Integrator'}
        return {'binding':self.binding,'items':[item] if self.return_ready and cursor<1 else [],
                'newest':{'delivery':0,'native':int(self.return_ready)},'cursor':{'delivery':0,'native':int(self.return_ready)},'more':False}
    def presentation_part(self,ident,revision,offset):
        return {'id':ident,'revision':revision,'kind':'integrator_answer','entry_binding':[100],
                'current':True,'text':'Canonical integrating return.','next_offset':None}
    def conversation_foreground_originals(self,dialogue,binding,before):
        return {'sources':[{'id':ident,'phase':value['phase']} for ident,value in self.inputs.items()]}
    def conversation_foreground_delegate(self,body):
        self.delegations.append(body)
        return {'id':body['id'],'phase':'accepted','native_acceptance':'observed'}

    def conversation_voice_submit(self,meta,data,**kwargs):
        value={**meta,'phase':'foreground_captured','foreground_dialogue':kwargs['foreground_dialogue'],
               'voice':{'audio_sha256':hashlib.sha256(data).hexdigest()}}
        self.inputs[meta['id']]=value;return value
    def conversation_foreground_complete(self,ident,binding,dialogue):
        record=json.loads((self.root/'prepared'/f'{ident}.json').read_text())
        value=self.inputs[ident];value.update(phase='foreground',text=record['text']);self.completed.set();return value
    def conversation_input_status(self,ident):return self.inputs[ident]


class Mounted(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.root.chmod(0o700)
        self.owner=Owner(self.root);Stream.opened=[];Detector.opened=[]
        self.config={'state_dir':str(self.root),'origin':'https://example.test','prefix':'/sessions','bot_id':123,
            'streaming_transcription':{'enabled':True,'provider':'gemini','mode':'prepared','native_dialogue':True,
                'endpoint':'wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent',
                'credential_file':str(self.root/'fixture-key'),'cache_root':str(self.root/'prepared'),
                'turn_detection':{'enabled':True,'continuous':True,'command':['/fixture/python','capture-turn']}}}
        self.patches=[patch('dashboard.native_voice.NativeDialogue',Stream),patch('dashboard.native_voice.Detector',Detector)]
        for p in self.patches:p.start()
        self.app=create_app(self.config,self.owner,lambda raw,bot:int(raw))
        self.client=TestClient(self.app,base_url='https://example.test');self.client.__enter__()
        self.client.post('/api/session',json={'init_data':'100'},headers={'origin':'https://example.test'})
        self.client.cookies.set('telecodex_dashboard',self.client.cookies.get('telecodex_dashboard'),path='/')
        self.csrf=self.client.get('/api/state').json()['csrf'];self.ident=str(uuid.uuid4())
    def tearDown(self):
        self.client.__exit__(None,None,None)
        for p in self.patches:p.stop()
        self.tmp.cleanup()
    def meta(self,**kwargs):return {'id':self.ident,'binding':self.owner.binding,'csrf':self.csrf,**kwargs}
    def open(self,origin='https://example.test'):
        return self.client.websocket_connect('/api/interaction/voice/native',headers={'origin':origin})
    def test_exact_original_and_assistant_history_through_the_mounted_route(self):
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            ws.send_bytes(b'\1\0'*1600);ws.send_bytes(b'\0\0'*1600)
            events=[]
            while not any(v['type']=='original_retained' for v in events) or not any(v['type']=='assistant_utterance' and v['utterance']['closed'] for v in events):
                events.append(ws.receive_json())
            self.assertTrue(self.owner.completed.wait(2))
            audio=next(v for v in events if v['type']=='audio')
            ws.send_json({'type':'playback','id':audio['id'],'played_bytes':640})
            ws.send_json({'type':'close'})
        self.assertEqual(len(self.owner.inputs),1)
        original=next(iter(self.owner.inputs.values()))
        self.assertEqual(original['phase'],'foreground');self.assertEqual(original['text'],'Exact synthetic interpretation')
        self.assertEqual(original['voice']['audio_sha256'],hashlib.sha256(wav_bytes(b'\1\0'*1600+b'\0\0'*1600)).hexdigest())
        history=self.client.get('/api/interaction/foreground').json()['items']
        self.assertEqual(history[0]['speaker'],'assistant');self.assertEqual(history[0]['text'],'A native foreground response.')
        self.assertEqual(history[0]['played_bytes'],640);self.assertTrue(history[0]['closed'])
        self.assertEqual(self.owner.calls,[])
        self.assertTrue(Stream.opened[0].closed_event.wait(2),'Wait for actual provider cleanup, not client context exit')
        self.assertTrue(Detector.opened[0].closed_event.wait(2))
    def test_native_voice_continues_while_an_integrating_return_watch_is_pending(self):
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            ws.send_bytes(b'\1\0'*1600);ws.send_bytes(b'\0\0'*1600)
            while ws.receive_json()['type']!='turn_complete':pass
            self.assertTrue(self.owner.completed.wait(2));stream=Stream.opened[0]
            stream.queue.put([{'type':'source_query','call_id':'sources','before':0}])
            call,result=stream.tool_results.get(timeout=2)
            original=result['sources'][0]['id'];self.assertEqual(call,'sources')
            stream.queue.put([{'type':'delegation_proposed','call_id':'work','original_ids':[original],'formulation':'Assistant-refined request.'}])
            call,result=stream.tool_results.get(timeout=2)
            self.assertEqual(result['kind'],'integrator_admission');self.assertIn('Not established',result['completion'])
            self.assertEqual(len(self.owner.delegations),1)
            stream.queue.put([{'type':'integrator_watch','call_id':'watch'},
                              {'type':'audio','pcm':b'\2\0'*320,'sample_rate':24000},
                              {'type':'output_transcript','text':'I can keep talking while work continues.'},
                              {'type':'turn_complete'}])
            while ws.receive_json()['type']!='audio':pass
            self.assertTrue(stream.tool_results.empty(),'Waiting for a result does not block native audio')
            self.owner.return_ready=True
            (self.root/'native.sqlite3').write_bytes(b'synthetic source notification')
            call,result=stream.tool_results.get(timeout=3)
            self.assertEqual(call,'watch');self.assertEqual(result['text'],'Canonical integrating return.')
            self.assertEqual(len(self.owner.delegations),1)
            ws.send_json({'type':'close'})
    def test_provider_cancellation_does_not_end_voice_or_cancel_work(self):
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready');stream=Stream.opened[0]
            stream.queue.put([{'type':'integrator_watch','call_id':'watch'},
                {'type':'proposal_cancelled','call_id':'watch','native_work_cancelled':False},
                {'type':'audio','pcm':b'\1\0'*320,'sample_rate':24000}])
            seen=[]
            while not seen or seen[-1]['type']!='audio':seen.append(ws.receive_json())
            self.assertTrue(any(v['type']=='proposal_cancelled' for v in seen))
            self.assertFalse(stream.closed);self.assertEqual(self.owner.delegations,[])
            ws.send_json({'type':'close'})

    def test_revoked_actor_cannot_receive_generated_audio(self):
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            self.owner.allowed=False
            Stream.opened[0].queue.put([{'type':'audio','pcm':b'\1\0'*320,'sample_rate':24000}])
            self.assertEqual(ws.receive_json()['type'],'review')
        self.assertTrue(Stream.opened[0].closed_event.wait(2))

    def test_old_native_listener_is_refused_before_provider_or_microphone(self):
        self.owner.compatible=False
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'review')
        self.assertEqual(Stream.opened,[]);self.assertEqual(self.owner.inputs,{})
    def test_fresh_action_token_is_required_before_native_open(self):
        with self.open() as ws:
            ws.send_json(self.meta(csrf='invalid'));self.assertEqual(ws.receive_json()['type'],'review')
        self.assertEqual(Stream.opened,[])
    def test_origin_is_checked_and_voice_is_off_by_default(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.open('https://other.test'):pass
        self.assertEqual(Stream.opened,[])
    def test_native_route_requires_an_explicit_enablement(self):
        disabled={**self.config,'streaming_transcription':{**self.config['streaming_transcription'],'native_dialogue':False}}
        app=create_app(disabled,self.owner,lambda raw,bot:int(raw))
        self.assertNotIn('/api/interaction/voice/native',[r.path for r in app.routes])
        self.assertFalse(getattr(app.state,'native_voice_enabled',False))

    def test_only_text_or_turn_changes_notify_history_readers(self):
        history=self.app.state.native_history;ident=str(uuid.uuid4());calls=[]
        close=history.subscribe(lambda:calls.append(True))
        history.retain(100,self.ident,self.owner.binding,ident,'','b'*64,4,closed=False)
        self.assertEqual(calls,[])
        history.retain(100,self.ident,self.owner.binding,ident,'Words','b'*64,4,closed=False)
        history.retain(100,self.ident,self.owner.binding,ident,'Words','c'*64,8,closed=False)
        history.played(100,self.ident,ident,4)
        self.assertEqual(len(calls),1,'PCM/playback writes do not create whole-conversation refresh loops')
        history.retain(100,self.ident,self.owner.binding,ident,'Words','c'*64,8,closed=True)
        self.assertEqual(len(calls),2);close()

    def test_history_does_not_rewrite_a_closed_utterance_or_cross_owner(self):
        history=self.app.state.native_history;ident=str(uuid.uuid4())
        history.retain(100,self.ident,self.owner.binding,ident,'Retained','b'*64,4)
        with self.assertRaises(ValueError):history.retain(100,self.ident,self.owner.binding,ident,'Changed','c'*64,8)
        self.assertEqual(history.page(101)['items'],[])
        with self.assertRaises(ValueError):history.played(101,self.ident,ident,2)
        history.max_rows=1
        with self.assertRaises(ValueError):history.capacity()


if __name__=='__main__':unittest.main()
