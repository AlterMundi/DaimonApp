"""Mounted native voice through authenticated sockets and durable source/text state.

Synthetic provider/detector peers only. No microphone, model, real native work or
receiving configuration is used. Ordinary HTTP qualification remains separate.
"""
import asyncio
import hashlib
import json
import logging
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch
# When imported as a synthetic peer, keep the caller's selected application
# runtime. Replacing its namespace path could qualify checkout scripts instead.
if 'dashboard' not in sys.modules:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from dashboard.app import create_app
from dashboard.provider import Provider, ProviderUnavailable
from dashboard.live_transcription import wav_bytes
from dashboard.native_voice import playback_status, being_identity, ForegroundUnavailable, DialogueUnavailable
from dashboard_io import Receiver


class Stream:
    activity_mode='manual';model='gemini-3.8-live';max_tools=32;opened=[]
    def __init__(self,*args,**kwargs):
        self.context=kwargs.get('context')
        self.voice_name=kwargs.get('voice_name')
        self.queue=queue.Queue();self.queue.put([{'type':'ready'}]);self.total=0;self.closed=False;self.closed_event=threading.Event()
        self.start_sent=threading.Event();self.tool_results=queue.Queue();self.notices=[];self.notice_seen=threading.Event();self.input_active=False;self.response_pending=False;self.opened.append(self)
        self.guidance=[];self.guidance_seen=threading.Event()
        self.rollover_due=False
        self.handover_checks=[]
    def handover_ready(self,watch=None):
        self.handover_checks.append(watch)
        return not self.input_active and not self.response_pending
    def successor(self,basis,*,pending_effects=None,pending_originals=None):
        value=type(self)(context={'live_checkpoint':basis,'pending_integrator_effects':pending_effects,
            'uninterpreted_originals':pending_originals or []})
        value.receive()  # setupComplete belongs to candidate preparation.
        return value
    def receive(self):
        try:return self.queue.get(timeout=.05)
        except queue.Empty:return []
    def activity_start(self):
        self.queue.put([{'type':'voice_activity','activity':'ACTIVITY_START','audio_offset':f'{self.total/32000:g}s','source':'provider_manual_activity_ack'}]);self.start_sent.set()
    def append(self,pcm):self.total+=len(pcm)
    def activity_end(self):
        self.queue.put([{'type':'input_transcript','text':' \nExact synthetic interpretation  '},
            {'type':'voice_activity','activity':'ACTIVITY_END','audio_offset':f'{self.total/32000:g}s','source':'provider_manual_activity_ack'},
            {'type':'audio','pcm':b'\1\0'*320,'sample_rate':24000},
            {'type':'output_transcript','text':'A native foreground response.'},
            {'type':'turn_complete'}])
    def close(self):self.closed=True;self.closed_event.set();self.queue.put([{'type':'closing'}])
    def tool_result(self,*args,**kwargs):self.tool_results.put(args)
    def notify_integrator_update(self):
        if self.input_active or self.response_pending:return False
        self.notices.append('internal_integrator_update_available');self.notice_seen.set();return True
    def guide(self,value):
        if self.input_active or self.response_pending:return False
        self.guidance.append(value);self.guidance_seen.set()
        if value['mode']=='spoken_offer':self.response_pending=True
        return True


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
        (root/'native.sqlite3').touch();self.inputs={};self.completed=threading.Event();self.delegations=[];self.return_ready=False;self.questions=[];self.requests_seen=threading.Event()
        self.return_kind='integrator_answer';self.native_returns=[]
        self.return_current=True;self.return_seen=threading.Event()
        self.input_id=Provider.input_id
        self.contexts={};self.context_calls=[];self.context_retained=threading.Event();self.context_closed=threading.Event();self.guidance_done=threading.Event()
    def presentation(self,command):
        if command=='input voice capabilities':return {'binding':self.binding,'foreground_retention':'v1' if self.compatible else None,'foreground_completed_reader':self.compatible,'foreground_context':'v1','foreground_continuation':'v1','foreground_audio_observations':'v1','foreground_derived_captions':'v1','foreground_guidance':'v1','foreground_rollover':'v1','foreground_resume':'v1'}
        if command.startswith('input list '):return {'binding':self.binding}
        raise AssertionError(command)
    def presentation_list(self,*args):
        cursor=args[1] if len(args)>1 else 0
        item={'id':'native:1','revision':'b'*64,'kind':self.return_kind,'native_returns':self.native_returns,'current':self.return_current,'label':'Integrator'}
        if self.return_ready and cursor<1:self.return_seen.set()
        return {'binding':self.binding,'items':[item] if self.return_ready and cursor<1 else [],
                'newest':{'delivery':0,'native':int(self.return_ready)},'cursor':{'delivery':0,'native':int(self.return_ready)},'more':False}
    def conversation_requests(self,after=0):
        self.requests_seen.set()
        rows=self.questions[after:after+8]
        return {'binding':self.binding,'items':[{k:v for k,v in row.items() if k!='body'} for row in rows],
                'cursor':after+len(rows),'more':after+len(rows)<len(self.questions)}
    def conversation_request_detail(self,ident,offset,revision):
        value=next(v for v in self.questions if v['id']==ident)
        if value['revision']!=revision or value['state']!='pending':raise ProviderUnavailable('Question changed')
        body=value['body'];end=min(offset+4000,len(body))
        return {**value,'body':body[offset:end],'entry_binding':[100],
                'offset':offset,'next_offset':end if end<len(body) else None}
    def presentation_part(self,ident,revision,offset):
        if ident.startswith('request:'):return Provider.presentation_part(self,ident,revision,offset)
        text=getattr(self,'return_text','Canonical integrating return.');end=min(offset+1600,len(text))
        return {'id':ident,'revision':revision,'kind':self.return_kind,'native_returns':self.native_returns,'entry_binding':[100],
                'current':True,'text':text[offset:end],'offset':offset,'next_offset':end if end<len(text) else None}
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
        value=self.inputs[ident];value.update(phase='foreground',text=record['text'].strip());self.completed.set();return value
    def conversation_input_status(self,ident):return self.inputs[ident]

    def conversation_live_context(self,body):
        self.context_calls.append(body)
        dialogue=body['dialogue'];generation=body['generation']
        if body['action']=='open':
            self.assert_context_binding(body['binding'])
            context=self.contexts.setdefault(dialogue,{'dialogue':dialogue,'generation':generation,'closed':False,'sources':{}})
        else:context=self.contexts[dialogue]
        if body['action']=='resume_read':
            assert context['closed']
            content={'dialogue':dialogue,'generation':generation,'checkpoint':{'text':'Prior purpose'},
                'events':list(context['sources'].values())}
            return {k:context[k] for k in ('dialogue','generation','closed')}|{'resume':{
                'revision':'c'*64,'bytes':len(json.dumps(content,separators=(',',':')).encode()),'content':content}}
        if body['action']=='checkpoint_needed':
            return {k:context[k] for k in ('dialogue','generation','closed')}|{
                'checkpoint_request':{'generation':generation,'reason':body['reason']}}
        if body['action']=='rollover_read':
            if not context['sources']:raise ProviderUnavailable('Synthetic checkpoint not yet ready')
            content={'kind':'internal_integrator_checkpoint','checkpoint':{'text':'Keep conversation purpose and pending integrating references.'}}
            revision=hashlib.sha256(json.dumps([context['generation'],context['sources']],sort_keys=True).encode()).hexdigest()
            return {k:context[k] for k in ('dialogue','generation','closed')}|{'rollover_basis':{'revision':revision,'through':len(context['sources']),'content':content}}
        if body['action']=='rollover_commit':
            assert context['generation']==generation
            revision=hashlib.sha256(json.dumps([context['generation'],context['sources']],sort_keys=True).encode()).hexdigest()
            if body['revision']!=revision:raise ProviderUnavailable('Synthetic candidate basis changed')
            context['generation']=body['next_generation']
            context['rollover']={'previous':generation,'next':body['next_generation'],'revision':revision,'committed':True}
            return {k:context[k] for k in ('dialogue','generation','closed','rollover')}
        if body['action']=='rollover_abort':
            committed=context['generation']==body['next_generation']
            return {k:context[k] for k in ('dialogue','generation','closed')}|{'rollover':context.get('rollover'),
                'rollover_committed':committed,'rollover_fenced':not committed}
        assert context['generation']==generation
        receipts=[]
        guide=context.get('guidance')
        if body['action']=='guidance':
            return {k:context[k] for k in ('dialogue','generation','closed')}|{'guidance':guide if guide and guide['phase']=='pending' else None}
        if body['action']=='guidance_begin':
            assert guide['id']==body['id'] and guide['phase']=='pending';guide['phase']='submitting'
        elif body['action']=='guidance_outcome':
            assert guide['id']==body['id'];guide['phase']='pending' if body['outcome']=='unsent' else body['outcome']
            if body['outcome']=='sent':self.guidance_done.set()
        if body['action']=='sync':
            for ident,value in self.inputs.items():
                if value.get('foreground_dialogue')==dialogue and value.get('text'):
                    context['sources'].setdefault(ident,{'role':'human','text':value['text']})
            for source in body.get('assistant',[]):
                ident=source['source'];value={'role':'assistant',**source}
                if ident in context['sources']:assert context['sources'][ident]==value
                else:context['sources'][ident]=value
                receipts.append({'source':ident,'sequence':list(context['sources']).index(ident)+1,
                    'revision':hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest(),'fresh':True})
            if any(s['role']=='human' for s in context['sources'].values()) and any(s['role']=='assistant' for s in context['sources'].values()):
                self.context_retained.set()
        elif body['action']=='close':context['closed']=True;self.context_closed.set()
        return {k:context[k] for k in ('dialogue','generation','closed')}|{'assistant_receipts':receipts,'guidance':guide}

    def assert_context_binding(self,binding):
        assert binding==self.binding


class Mounted(unittest.TestCase):
    def test_qwen_selection_preserves_prepared_asr_and_delivers_committed_audio(self):
        class QwenStream(Stream):
            model='qwen-audio-3.0-realtime-plus'
            def activity_start(self):self.started=self.total;self.start_sent.set()
            def activity_end(self):
                self.queue.put([{'type':'input_committed','source':'provider_qwen_commit','item_id':'qwen-item',
                    'stream_start':self.started,'stream_end':self.total},
                    {'type':'input_transcript','text':'Exact Qwen interpretation.','finished':True},
                    {'type':'audio','pcm':b'\1\0'*320,'sample_rate':24000},
                    {'type':'output_transcript','text':'Qwen native speech.'},{'type':'turn_complete'}])
        self.client.__exit__(None,None,None)
        self.config['streaming_transcription'].update(native_provider='qwen',
            native_credential_file=str(self.root/'qwen-key'),native_voice_name='longanqian')
        qwen_patch=patch('dashboard.qwen_dialogue.QwenDialogue',QwenStream)
        self.patches.append(qwen_patch);qwen_patch.start()
        self.app=create_app(self.config,self.owner,lambda raw,bot:int(raw))
        self.client=TestClient(self.app,base_url='https://example.test');self.client.__enter__()
        self.client.post('/api/session',json={'init_data':'100'},headers={'origin':'https://example.test'})
        self.client.cookies.set('telecodex_dashboard',self.client.cookies.get('telecodex_dashboard'),path='/')
        self.csrf=self.client.get('/api/state').json()['csrf']
        with self.open() as ws:
            ws.send_json(self.meta());ready=ws.receive_json();self.assertEqual(ready['model'],QwenStream.model)
            ws.send_bytes(b'\1\0'*1600);ws.send_bytes(b'\0\0'*1600)
            kinds=[]
            for _ in range(20):
                v=ws.receive_json();kinds.append(v['type'])
                if v['type']=='original_completed':break
            self.assertIn('audio',kinds);self.assertIn('original_completed',kinds)
            self.assertNotIn('input_committed',kinds)
            ws.send_json({'type':'close'})
        self.assertEqual(self.app.state.native_history.page(100)['items'][0]['model'],QwenStream.model)
        self.assertEqual(self.config['streaming_transcription']['provider'],'gemini')
        for updates in ({'native_provider':'other'},{'native_activity_mode':'automatic'},
                        {'native_credential_file':'relative'}):
            invalid={**self.config,'streaming_transcription':{**self.config['streaming_transcription'],**updates}}
            with self.assertRaises(ValueError):create_app(invalid,self.owner,lambda raw,bot:int(raw))

    def test_real_qwen_adapter_keeps_pending_admission_and_late_return_across_renewal(self):
        # Compose the actual Qwen wire adapter with the mounted owner. Existing
        # generic Stream fixtures alone do not cover deferred Qwen responses.
        import base64
        from dashboard.qwen_dialogue import QwenDialogue as RealQwen
        opened=[]
        class Wire:
            def __init__(self):
                self.sent=[];self.queue=queue.Queue();self.closed=threading.Event();self.sequence=0
            def send(self,raw):
                value=json.loads(raw);self.sent.append(value);kind=value['type']
                if kind=='session.update':self.push({'type':'session.updated'})
                elif kind=='input_audio_buffer.commit':
                    self.push({'type':'input_audio_buffer.committed','item_id':'input-1'})
                    self.push({'type':'conversation.item.input_audio_transcription.completed','item_id':'input-1','transcript':'Keep one task pending.'})
                elif kind=='response.create':
                    self.sequence+=1
                    self.push({'type':'response.created','response':{'id':f'response-{self.sequence}'}})
                    self.push({'type':'response.audio.delta','delta':base64.b64encode(b'\1\0'*320).decode()})
                    text='Canonical integrating return.' if any('Canonical integrating return.' in json.dumps(v) for v in self.sent) else 'Synthetic acknowledgement.'
                    self.push({'type':'response.audio_transcript.delta','delta':text})
                    self.push({'type':'response.done','response':{'status':'completed'}})
            def push(self,value):self.queue.put(json.dumps(value))
            def recv(self):
                try:return self.queue.get(timeout=.03)
                except queue.Empty:raise TimeoutError()
            def settimeout(self,value):pass
            def close(self):self.closed.set()
        class ActualQwen(RealQwen):
            def __init__(self,*args,**kwargs):
                kwargs.setdefault('connect',lambda *a,**k:Wire())
                super().__init__(*args,**kwargs);opened.append(self)
        self.client.__exit__(None,None,None)
        key=self.root/'qwen-key';key.write_text('synthetic');key.chmod(0o600)
        self.config['streaming_transcription'].update(native_provider='qwen',native_credential_file=str(key),native_voice_name='longanlufeng')
        selected=patch('dashboard.qwen_dialogue.QwenDialogue',ActualQwen);self.patches.append(selected);selected.start()
        self.app=create_app(self.config,self.owner,lambda raw,bot:int(raw))
        self.client=TestClient(self.app,base_url='https://example.test');self.client.__enter__()
        self.client.post('/api/session',json={'init_data':'100'},headers={'origin':'https://example.test'})
        self.client.cookies.set('telecodex_dashboard',self.client.cookies.get('telecodex_dashboard'),path='/')
        self.csrf=self.client.get('/api/state').json()['csrf']
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            old=opened[0];ws.send_bytes(b'\1\0'*1600);ws.send_bytes(b'\0\0'*1600)
            utterance=original=None
            while utterance is None or original is None:
                value=ws.receive_json();self.assertNotEqual(value['type'],'review',value)
                if value['type']=='assistant_utterance' and value['utterance']['closed']:utterance=value['utterance']
                if value['type']=='original_completed':original=value['id']
            wire=old._qsocket
            wire.push({'type':'response.created','response':{'id':'delegate'}})
            wire.push({'type':'response.function_call_arguments.done','call_id':'admit-once','name':'delegate_to_integrator',
                'arguments':json.dumps({'original_ids':[original],'request':'Preserve one pending task across renewal.'})})
            wire.push({'type':'response.done','response':{'status':'completed'}})
            # The tool's required acknowledgement completes on the old socket.
            while True:
                value=ws.receive_json();self.assertNotEqual(value['type'],'review',value)
                if value['type']=='assistant_utterance' and value['utterance']['closed'] and value['utterance']['id']!=utterance['id']:
                    utterance=value['utterance'];break
            self.assertEqual(len(self.owner.delegations),1)
            old.context_estimate=55940
            ws.send_json({'type':'playback','id':utterance['id'],'played_bytes':640})
            self.assertTrue(wire.closed.wait(3),'Settled Qwen output must reach a physical successor')
            self.assertEqual(len(opened),2)
            successor=opened[-1]
            self.assertIn(original,successor._qbase,'Successor setup keeps the existing pending original reference')
            self.assertIn(self.owner.delegations[0]['id'],successor._qbase,'Successor setup keeps the admitted intent, not another work request')
            self.owner.return_ready=True;(self.root/'native.sqlite3').write_bytes(b'late canonical return')
            successor._qsocket.push({'type':'response.created','response':{'id':'return-watch'}})
            successor._qsocket.push({'type':'response.function_call_arguments.done','call_id':'late-watch','name':'await_integrator_update','arguments':'{}'})
            successor._qsocket.push({'type':'response.done','response':{'status':'completed'}})
            while True:
                value=ws.receive_json();self.assertNotEqual(value['type'],'review',value)
                if value['type']=='assistant_utterance' and value['utterance']['closed'] and value['utterance']['text']=='Canonical integrating return.':break
            self.assertEqual(len(self.owner.inputs),1)
            self.assertEqual(len(self.owner.delegations),1,'Renewal and return cannot repeat work admission')
            self.assertEqual(sum(v['type']=='input_audio_buffer.commit' for stream in opened for v in stream._qsocket.sent),1,'No old captured PCM is replayed')
            outputs=[v['item'] for v in wire.sent if v.get('item',{}).get('type')=='function_call_output']
            self.assertEqual([v['call_id'] for v in outputs],['admit-once'])
            self.assertIn('Canonical integrating return.',json.dumps(successor._qsocket.sent))
            ws.send_json({'type':'close'});self.assertTrue(self.owner.context_closed.wait(2))

    def test_reconnect_metadata_is_bounded_and_correlates_the_owned_close(self):
        import dashboard.native_voice as voice
        snapshot={'previous_dialogue':self.ident,'cause':'server_review','playback_context':'running',
            'audio_bytes':3200,'retained_originals':1,'pending_events':0,'queued_audio_bytes':0,
            'generated_audio_bytes':4800,'played_audio_bytes':2400,'floor':False,'blocked':True,'user_paused':False}
        self.assertEqual(voice.reconnect_snapshot(snapshot),snapshot)
        self.assertEqual(voice.reconnect_snapshot({**snapshot,'generated_audio_bytes':86400000})['generated_audio_bytes'],86400000)
        for value in ({**snapshot,'text':'Private words'},{**snapshot,'audio_bytes':True},
                {**snapshot,'queued_audio_bytes':86400001},{**snapshot,'cause':'arbitrary details'}):
            with self.assertRaises(ValueError):voice.reconnect_snapshot(value)
        with self.assertLogs('uvicorn.error',level='INFO') as logs:
            with self.open() as ws:
                ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
                ws.send_json({'type':'close'})
            deadline=time.monotonic()+3
            while not any('native_voice_closed ' in v for v in logs.output) and time.monotonic()<deadline:time.sleep(.005)
            self.assertTrue(any('native_voice_closed ' in v for v in logs.output))
            self.ident=str(uuid.uuid4())
            with self.open() as ws:
                ws.send_json(self.meta(reconnect=snapshot))
                self.assertEqual(ws.receive_json()['type'],'reconnect_recorded')
                outcome=ws.receive_json();self.assertEqual(outcome['type'],'ready',outcome)
                ws.send_json({'type':'close'})
        report=json.loads(next(v.split('native_voice_reconnect ',1)[1] for v in logs.output if 'native_voice_reconnect ' in v))
        self.assertEqual(Stream.opened[-1].context['prior_conversation']['content']['dialogue'],snapshot['previous_dialogue'])
        self.assertEqual(report['client_observation'],snapshot)
        self.assertTrue(report['previous_close_available'])
        self.assertEqual(report['previous_server_close']['id'],snapshot['previous_dialogue'])
        self.assertEqual(self.owner.delegations,[])

    def test_owner_selected_voice_reaches_provider_and_invalid_selection_is_refused(self):
        self.config['streaming_transcription']['native_voice_name']='Charon'
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            self.assertEqual(Stream.opened[0].voice_name,'Charon')
            ws.send_json({'type':'close'})
        for value in ('',1,'Charon\n'):
            invalid={**self.config,'streaming_transcription':{**self.config['streaming_transcription'],'native_voice_name':value}}
            with self.assertRaises(ValueError):create_app(invalid,self.owner,lambda raw,bot:int(raw))

    def test_failed_candidate_setup_keeps_current_voice_available(self):
        attempted=threading.Event();released=threading.Event()
        class Holding(Stream):
            def hold_for_renewal(self,enabled=True):
                self.holding=enabled
                if not enabled:released.set()
        def fail(*args,**kwargs):
            attempted.set();raise DialogueUnavailable('Synthetic candidate setup unavailable')
        with patch('dashboard.native_voice.NativeDialogue',Holding),patch.object(Stream,'successor',side_effect=fail),self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            old=Stream.opened[0];old.rollover_due=True
            old.queue.put([{'type':'output_transcript','text':'Current purpose.'},{'type':'turn_complete'}])
            self.assertTrue(attempted.wait(2))
            self.assertTrue(released.wait(2),'A failed candidate must release the same provider, not strand queued speech')
            old.queue.put([{'type':'audio','pcm':b'\1\0'*320,'sample_rate':24000}])
            while True:
                value=ws.receive_json();self.assertNotEqual(value['type'],'review',value)
                if value['type']=='audio':break
            self.assertFalse(old.closed);self.assertEqual(len(Stream.opened),1)
            ws.send_json({'type':'close'})
            closed=self.owner.context_closed.wait(2)
            with self.app.state.native_history.database() as db:
                record=dict(db.execute('SELECT * FROM foreground_context_producers WHERE dialogue=?',(self.ident,)).fetchone())
            self.assertTrue(closed,f'actions={[c["action"] for c in self.owner.context_calls]}, local={record}')

    def test_renewal_installs_successor_before_transmitting_queued_new_phrase(self):
        held=threading.Event();release=threading.Event()
        class Yielding(Stream):
            def hold_for_renewal(self,enabled=True):self.holding=enabled
            def successor(stream,basis,**kwargs):
                held.set()
                if not release.wait(3):raise TimeoutError('Synthetic successor setup')
                return super(Yielding,stream).successor(basis,**kwargs)
        class Repeated(Detector):
            async def feed(self,pcm):
                self.total+=len(pcm);generation=(self.total+6399)//6400;first=self.total%6400==3200
                await self.queue.put({'type':'activity','audio_bytes':self.total,'generation':generation,
                    'speaking':first,'speech_seen':True,
                    'onset' if first else 'endpoint':{'generation':generation,'audio_bytes':self.total,
                        **({} if first else {'authority':'analysis_only','probability':.9})}})
        with patch('dashboard.native_voice.NativeDialogue',Yielding),patch('dashboard.native_voice.Detector',Repeated),self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            old=Stream.opened[0]
            ws.send_bytes(b'\1\0'*1600);ws.send_bytes(b'\0\0'*1600)
            utterance=original=None
            while utterance is None or original is None:
                event=ws.receive_json();self.assertNotEqual(event['type'],'review',event)
                if event['type']=='original_completed':original=event['id']
                if event['type']=='assistant_utterance' and event['utterance']['closed']:utterance=event['utterance']
            old.rollover_due=True
            ws.send_json({'type':'playback','id':utterance['id'],'played_bytes':640})
            try:
                self.assertTrue(held.wait(2));self.assertTrue(old.holding)
                ws.send_bytes(b'\2\0'*1600);ws.send_bytes(b'\0\0'*1600)
                queued=None
                while queued is None:
                    event=ws.receive_json();self.assertNotEqual(event['type'],'review',event)
                    if event['type']=='original_retained':queued=event['id']
                self.assertNotEqual(queued,original)
                self.assertEqual(old.total,6400,'New phrase stays local while candidate prepares')
                release.set()
                while True:
                    event=ws.receive_json();self.assertNotEqual(event['type'],'review',event)
                    if event['type']=='original_completed' and event['id']==queued:break
                self.assertTrue(old.closed_event.wait(2))
                self.assertEqual(len(Stream.opened),2)
                self.assertEqual(Stream.opened[1].total,6400)
                self.assertEqual(len(self.owner.inputs),2,'No replacement original or work admission')
                self.assertEqual(self.owner.delegations,[])
            finally:
                release.set();ws.send_json({'type':'close'})

    def test_preparing_a_successor_keeps_old_audio_and_defers_changed_floor(self):
        held=threading.Event();release=threading.Event();created=threading.Event();successor=Stream.successor
        def prepare(stream,basis,**kwargs):
            held.set()
            if not release.wait(2):raise TimeoutError('Synthetic held candidate setup')
            result=successor(stream,basis,**kwargs);created.set();return result
        with patch.object(Stream,'successor',prepare),self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            old=Stream.opened[0];old.rollover_due=True
            old.queue.put([{'type':'output_transcript','text':'Earlier purpose.'},{'type':'turn_complete'}])
            try:
                self.assertTrue(held.wait(2))
                old.queue.put([{'type':'audio','pcm':b'\1\0'*320,'sample_rate':24000},
                    {'type':'output_transcript','text':'Still available during candidate setup.'}])
                while ws.receive_json()['type']!='audio':pass
                self.assertEqual(len(Stream.opened),1,'Candidate preparation must not stop old audio reception')
                release.set()
                self.assertTrue(created.wait(2))
                self.assertEqual(len(Stream.opened),2)
                self.assertTrue(Stream.opened[1].closed_event.wait(2))
                self.assertFalse(old.closed)
                self.assertFalse(any(c['action']=='rollover_commit' for c in self.owner.context_calls))
            finally:release.set()
            ws.send_json({'type':'close'});self.assertTrue(self.owner.context_closed.wait(2))

    def test_two_active_socket_rollovers_keep_speech_and_pending_work_once_only(self):
        class Repeated(Detector):
            async def feed(self,pcm):
                self.total+=len(pcm);generation=(self.total+6399)//6400;first=self.total%6400==3200
                await self.queue.put({'type':'activity','audio_bytes':self.total,'generation':generation,
                    'speaking':first,'speech_seen':True,
                    'onset' if first else 'endpoint':{'generation':generation,'audio_bytes':self.total,
                        **({} if first else {'authority':'analysis_only','probability':.9})}})
        with patch('dashboard.native_voice.Detector',Repeated),self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            for cycle in range(2):
                old=Stream.opened[-1]
                ws.send_bytes(b'\1\0'*1600);ws.send_bytes(b'\0\0'*1600)
                utterance=None;original=None
                while utterance is None or original is None:
                    value=ws.receive_json()
                    self.assertNotEqual(value['type'],'review',value)
                    if value['type']=='assistant_utterance' and value['utterance']['closed']:utterance=value['utterance']
                    if value['type']=='original_completed':original=value['id']
                if cycle==0:
                    old.queue.put([{'type':'delegation_proposed','call_id':'admit-work',
                        'original_ids':[original],'formulation':'A synthetic long task stays with Sol.'}])
                    _,receipt=old.tool_results.get(timeout=2)
                    self.assertEqual(receipt['kind'],'integrator_admission')
                old.rollover_due=True
                ws.send_json({'type':'playback','id':utterance['id'],'played_bytes':640})
                self.assertTrue(old.closed_event.wait(3),f'Cycle {cycle}: active socket must actually be replaced after playback: opened={len(Stream.opened)}, actions={[c["action"] for c in self.owner.context_calls]}')
                self.assertEqual(old.handover_checks,['admit-work' if cycle==0 else None])
                self.assertEqual(len(Stream.opened),cycle+2)
                successor=Stream.opened[-1]
                self.assertFalse(successor.closed)
                self.assertEqual(successor.context['live_checkpoint']['through'],2*(cycle+1))
                self.assertEqual(successor.context['pending_integrator_effects'][0]['original'],next(iter(self.owner.inputs)))
                self.assertEqual(len(self.owner.delegations),1,'Rollover must not resubmit the pending task')
            self.assertEqual([s.total for s in Stream.opened],[6400,6400,0],'No old captured PCM is replayed')
            self.owner.return_ready=True
            (self.root/'native.sqlite3').write_bytes(b'late canonical result after two generations')
            self.assertTrue(successor.notice_seen.wait(2))
            successor.queue.put([{'type':'integrator_watch','call_id':'admit-work'}])
            _,result=successor.tool_results.get(timeout=2)
            self.assertEqual(result['text'],'Canonical integrating return.')
            self.assertEqual(len(self.owner.inputs),2);self.assertEqual(len(self.owner.delegations),1)
            ws.send_json({'type':'close'});self.assertTrue(self.owner.context_closed.wait(2))

    def test_retained_empty_final_does_not_prevent_two_provider_successors(self):
        class Repeated(Detector):
            async def feed(self,pcm):
                self.total+=len(pcm);generation=(self.total+6399)//6400;first=self.total%6400==3200
                await self.queue.put({'type':'activity','audio_bytes':self.total,'generation':generation,
                    'speaking':first,'speech_seen':True,
                    'onset' if first else 'endpoint':{'generation':generation,'audio_bytes':self.total,
                        **({} if first else {'authority':'analysis_only','probability':.9})}})
        ends=[]
        class QwenEmpty(Stream):
            model='qwen-audio-3.0-realtime-plus'
            def activity_start(self):self.started=self.total;self.start_sent.set()
            def activity_end(self):
                first=not ends;ends.append(True)
                self.queue.put([{'type':'input_committed','source':'provider_qwen_commit','item_id':str(len(ends)),
                    'stream_start':self.started,'stream_end':self.total},
                    {'type':'input_transcript','text':'' if first else 'Exact later human words.','finished':True},
                    *([] if first else [{'type':'audio','pcm':b'\1\0'*320,'sample_rate':24000},
                        {'type':'output_transcript','text':'Useful later spoken answer.'}]),{'type':'turn_complete'}])
        self.client.__exit__(None,None,None)
        self.config['streaming_transcription'].update(native_provider='qwen',
            native_credential_file=str(self.root/'qwen-key'),native_voice_name='longanqian')
        qwen_patch=patch('dashboard.qwen_dialogue.QwenDialogue',QwenEmpty)
        self.patches.append(qwen_patch);qwen_patch.start()
        self.app=create_app(self.config,self.owner,lambda raw,bot:int(raw))
        self.client=TestClient(self.app,base_url='https://example.test');self.client.__enter__()
        self.client.post('/api/session',json={'init_data':'100'},headers={'origin':'https://example.test'})
        self.client.cookies.set('telecodex_dashboard',self.client.cookies.get('telecodex_dashboard'),path='/')
        self.csrf=self.client.get('/api/state').json()['csrf']
        with patch('dashboard.native_voice.Detector',Repeated),self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            ws.send_bytes(b'\1\0'*1600);ws.send_bytes(b'\0\0'*1600)
            raw=None;retained=None
            while raw is None or retained is None:
                event=ws.receive_json();self.assertNotEqual(event['type'],'review',event)
                if event['type']=='input_uninterpreted':raw=event['id']
                if event['type']=='original_retained':retained=event
            self.assertEqual(raw,retained['id'])
            for cycle in range(2):
                old=Stream.opened[-1]
                ws.send_bytes(b'\1\0'*1600);ws.send_bytes(b'\0\0'*1600)
                utterance=completed=None
                while utterance is None or completed is None:
                    event=ws.receive_json();self.assertNotEqual(event['type'],'review',event)
                    if event['type']=='original_completed':completed=event['id']
                    if event['type']=='assistant_utterance' and event['utterance']['closed']:utterance=event['utterance']
                old.rollover_due=True
                ws.send_json({'type':'playback','id':utterance['id'],'played_bytes':640})
                self.assertTrue(old.closed_event.wait(3),'Durably retained empty final must not permanently block renewal')
                self.assertEqual(len(Stream.opened),cycle+2)
                self.assertEqual(Stream.opened[-1].context['uninterpreted_originals'],
                    [{'original':raw,'sha256':retained['sha256']}])
                self.assertEqual(self.owner.inputs[raw]['phase'],'foreground_captured')
                self.assertNotIn('text',self.owner.inputs[raw])
            self.assertEqual([s.total for s in Stream.opened],[12800,6400,0],'Old PCM must never be replayed')
            self.assertEqual(self.owner.delegations,[])
            ws.send_json({'type':'close'});self.assertTrue(self.owner.context_closed.wait(2))

    def test_new_speech_during_successor_setup_preserves_pending_work_and_late_return(self):
        class Repeated(Detector):
            async def feed(self,pcm):
                self.total+=len(pcm);generation=(self.total+6399)//6400;first=self.total%6400==3200
                await self.queue.put({'type':'activity','audio_bytes':self.total,'generation':generation,
                    'speaking':first,'speech_seen':True,
                    'onset' if first else 'endpoint':{'generation':generation,'audio_bytes':self.total,
                        **({} if first else {'authority':'analysis_only','probability':.9})}})
        held=threading.Event();release=threading.Event();created=threading.Event();successor=Stream.successor
        def prepare(stream,basis,**kwargs):
            held.set()
            if not release.wait(3):raise TimeoutError('Synthetic held successor setup')
            result=successor(stream,basis,**kwargs);created.set();return result
        with patch('dashboard.native_voice.Detector',Repeated),patch.object(Stream,'successor',prepare),self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            old=Stream.opened[0]
            def phrase():
                ws.send_bytes(b'\1\0'*1600);ws.send_bytes(b'\0\0'*1600)
                utterance=original=None
                while utterance is None or original is None:
                    value=ws.receive_json();self.assertNotEqual(value['type'],'review',value)
                    if value['type']=='assistant_utterance' and value['utterance']['closed']:utterance=value['utterance']
                    if value['type']=='original_completed':original=value['id']
                return utterance,original
            utterance,original=phrase()
            old.queue.put([{'type':'delegation_proposed','call_id':'admit-work',
                'original_ids':[original],'formulation':'Preserve one pending synthetic task through new speech.'}])
            _,receipt=old.tool_results.get(timeout=2);self.assertEqual(receipt['kind'],'integrator_admission')
            old.rollover_due=True
            ws.send_json({'type':'playback','id':utterance['id'],'played_bytes':640})
            try:
                self.assertTrue(held.wait(2))
                second,second_original=phrase()
                self.assertNotEqual(second_original,original)
                self.assertEqual(old.total,12800,'New speech must stay on the existing socket during setup')
                release.set();self.assertTrue(created.wait(2))
                self.assertTrue(Stream.opened[1].closed_event.wait(2),'Changed speech/playback floor must discard the stale candidate')
                self.assertFalse(old.closed)
                self.assertFalse(any(c['action']=='rollover_commit' for c in self.owner.context_calls))
                self.assertEqual(len(self.owner.inputs),2);self.assertEqual(len(self.owner.delegations),1)
                old.rollover_due=False  # Isolate return on the preserved socket; two successful successors have separate coverage.
                self.owner.return_ready=True
                (self.root/'native.sqlite3').write_bytes(b'late return while new speech is awaiting playback')
                # Continue the existing admission watch, never open another
                # watch or manufacture another delegation to repair the test.
                ws.send_json({'type':'playback','id':second['id'],'played_bytes':640})
                _,result=old.tool_results.get(timeout=2)
                self.assertEqual(result['text'],'Canonical integrating return.')
                self.assertEqual(len(self.owner.delegations),1)
            finally:release.set()
            ws.send_json({'type':'close'});self.assertTrue(self.owner.context_closed.wait(2))

    def test_slow_guidance_control_does_not_block_provider_audio(self):
        held=threading.Event();release=threading.Event();finished=threading.Event()
        original=self.owner.conversation_live_context
        def delayed(body):
            if body['action']=='guidance':
                held.set()
                if not release.wait(5):raise TimeoutError('Synthetic held control')
                finished.set()
            return original(body)
        with patch.object(self.owner,'conversation_live_context',side_effect=delayed),self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            try:
                (self.root/'native.sqlite3').write_bytes(b'control notification')
                self.assertTrue(held.wait(2))
                Stream.opened[0].queue.put([{'type':'audio','pcm':b'\1\0'*320,'sample_rate':24000}])
                while ws.receive_json()['type']!='audio':pass
                self.assertFalse(finished.is_set(),'Provider audio must arrive while the owner control read is still held')
            finally:release.set()
            ws.send_json({'type':'close'});self.assertTrue(self.owner.context_closed.wait(2))

    def queue_guidance(self,mode='context_only'):
        context=self.owner.contexts[self.ident]
        value={'id':str(uuid.uuid4()),'generation':context['generation'],'basis':0,
            'mode':mode,'text':'Use the confirmed memory and keep current human corrections.','phase':'pending'}
        context['guidance']=value
        (self.root/'native.sqlite3').write_bytes(b'new source-bound guidance')
        return value

    def test_guidance_targets_same_live_and_waits_for_generation(self):
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            stream=Stream.opened[0];stream.response_pending=True
            guide=self.queue_guidance()
            self.assertFalse(stream.guidance_seen.wait(.05))
            self.assertEqual(guide['phase'],'pending')
            stream.response_pending=False;stream.queue.put([{'type':'turn_complete'}])
            self.assertTrue(self.owner.guidance_done.wait(2))
            self.assertEqual(len(stream.guidance),1);self.assertEqual(stream.guidance[0]['dialogue'],self.ident)
            self.assertEqual(stream.guidance[0]['id'],guide['id']);self.assertEqual(guide['phase'],'sent')
            self.assertEqual(self.owner.inputs,{});self.assertEqual(self.owner.delegations,[])
            ws.send_json({'type':'close'});self.assertTrue(self.owner.context_closed.wait(2))

    def test_spoken_guidance_waits_for_playback_without_claim_write_loop(self):
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            stream=Stream.opened[0]
            stream.queue.put([{'type':'audio','pcm':b'\1\0'*320,'sample_rate':24000},
                {'type':'output_transcript','text':'Earlier serialized reply.'},{'type':'turn_complete'}])
            while True:
                value=ws.receive_json()
                if value['type']=='assistant_utterance' and value['utterance']['closed']:
                    utterance=value['utterance'];break
            guide=self.queue_guidance('spoken_offer')
            self.assertFalse(stream.guidance_seen.wait(.1))
            self.assertEqual(guide['phase'],'pending')
            self.assertFalse(any(c['action']=='guidance_begin' for c in self.owner.context_calls),'Known pending playback must not cause a claim/defer DB-write wakeup loop')
            ws.send_json({'type':'playback','id':utterance['id'],'played_bytes':640})
            self.assertTrue(self.owner.guidance_done.wait(2));self.assertEqual(len(stream.guidance),1)
            ws.send_json({'type':'close'});self.assertTrue(self.owner.context_closed.wait(2))

    def test_context_incompatible_listener_is_refused_before_provider_opening(self):
        presentation=self.owner.presentation
        for capability in ('foreground_context','foreground_continuation'):
            def without_context(command):
                value=presentation(command)
                if command=='input voice capabilities':value.pop(capability)
                return value
            with self.subTest(capability=capability),patch.object(self.owner,'presentation',side_effect=without_context),self.open() as ws:
                ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'review')
            self.assertEqual(Stream.opened,[]);self.assertEqual(self.owner.contexts,{})

    def test_missing_caption_incompatible_listener_is_refused_before_provider_opening(self):
        presentation=self.owner.presentation
        def without_observations(command):
            value=presentation(command)
            if command=='input voice capabilities':value.pop('foreground_audio_observations')
            return value
        with patch.object(self.owner,'presentation',side_effect=without_observations),self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'review')
        self.assertEqual(Stream.opened,[]);self.assertEqual(self.owner.contexts,{})
    def enable_caption_recovery(self,wait=False):
        self.config['streaming_transcription']['native_caption_recovery']=True
        script=self.root/'caption-helper.py'
        script.write_text("""import json,sys,time
from pathlib import Path
Path(sys.argv[1]).write_text('started')
if sys.argv[2]=='wait':
    while not Path(sys.argv[3]).exists():time.sleep(.01)
print(json.dumps({'text':'Approximate recovered response.','final':True}))
""")
        self.owner.receiver['voice']={'transcription_command':[sys.executable,str(script),
            str(self.root/'caption-called'),'wait' if wait else 'now',str(self.root/'caption-release')],
            'timeout_seconds':3,'transcriber_label':'Synthetic caption helper'}

    def test_recovery_incompatible_listener_is_refused_before_provider_opening(self):
        self.enable_caption_recovery();presentation=self.owner.presentation
        def without_recovery(command):
            value=presentation(command)
            if command=='input voice capabilities':value.pop('foreground_derived_captions')
            return value
        with patch.object(self.owner,'presentation',side_effect=without_recovery),self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'review')
        self.assertEqual(Stream.opened,[]);self.assertFalse((self.root/'caption-called').exists())

    def test_missing_output_runs_finite_asr_and_retains_one_approximate_caption(self):
        self.enable_caption_recovery()
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            Stream.opened[0].queue.put([{'type':'audio','pcm':b'\x10\0'*320},{'type':'turn_complete'}])
            while True:
                event=ws.receive_json()
                if event['type']=='assistant_utterance' and event['utterance'].get('derived_caption'):
                    draft=event['utterance'];break
            self.assertEqual(draft['text'],'Approximate recovered response.')
            items={item['id']:item for item in self.app.state.native_history.page(100)['items']}
            parent=items[draft['derived_caption']['parent_source']]
            self.assertEqual((parent['text'],parent['generated_bytes']),('',640))
            self.assertEqual(len(items),2);self.assertEqual(self.owner.inputs,{})
            self.assertEqual(self.owner.delegations,[])
            ws.send_json({'type':'close'})
            self.assertTrue(self.owner.context_closed.wait(2),'Observe actual context close before shutting down fixture')
            deadline=time.monotonic()+2
            while list((self.root/'native-caption-audio').glob('*.wav')) and time.monotonic()<deadline:time.sleep(.005)
            self.assertEqual(list((self.root/'native-caption-audio').glob('*.wav')),[])
        self.assertTrue(self.owner.contexts[self.ident]['closed'])
        self.assertEqual(len(self.owner.contexts[self.ident]['sources']),2)

    def test_late_caption_after_voice_close_does_not_block_or_release_successor_voice(self):
        self.enable_caption_recovery(wait=True)
        with self.open() as first:
            first.send_json(self.meta());self.assertEqual(first.receive_json()['type'],'ready')
            Stream.opened[0].queue.put([{'type':'audio','pcm':b'\x10\0'*320},{'type':'turn_complete'}])
            deadline=time.monotonic()+2
            while not (self.root/'caption-called').exists() and time.monotonic()<deadline:time.sleep(.005)
            self.assertTrue((self.root/'caption-called').exists())
            first.send_json({'type':'close'})
            self.assertTrue(self.owner.context_closed.wait(2))
            successor={**self.meta(),'id':str(uuid.uuid4())}
            with self.open() as second:
                second.send_json(successor);self.assertEqual(second.receive_json()['type'],'ready')
                (self.root/'caption-release').touch()
                deadline=time.monotonic()+2
                while time.monotonic()<deadline:
                    if any(item.get('derived_caption') for item in self.app.state.native_history.page(100)['items']):break
                    time.sleep(.005)
                self.assertTrue(any(item.get('derived_caption') for item in self.app.state.native_history.page(100)['items']))
                with self.open() as third:
                    third.send_json({**self.meta(),'id':str(uuid.uuid4())})
                    self.assertEqual(third.receive_json()['type'],'review','Old cleanup cannot clear successor ownership')
                self.assertEqual(len(Stream.opened),2)
                second.send_json({'type':'close'})
        self.assertTrue(self.owner.contexts[self.ident]['closed'])
        self.assertEqual(len(self.owner.contexts[self.ident]['sources']),2)
        self.assertEqual(self.owner.inputs,{})

    def test_voice_semantic_outbox_reaches_context_without_becoming_work(self):
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            ws.send_bytes(b'\1\0'*1600);ws.send_bytes(b'\0\0'*1600)
            self.assertTrue(self.owner.context_retained.wait(2),'Both canonical human and terminal assistant context must arrive without Send')
            context=self.owner.contexts[self.ident]
            sources=list(context['sources'].values())
            self.assertTrue(any(s['role']=='human' and s['text']=='Exact synthetic interpretation' for s in sources))
            self.assertTrue(any(s['role']=='assistant' and s['text']=='A native foreground response.' for s in sources))
            self.assertEqual(self.owner.delegations,[])
            ws.send_json({'type':'close'})
            self.assertTrue(self.owner.context_closed.wait(2),'Observe the actual owner close before tearing down its websocket fixture')
        self.assertEqual(len(self.owner.inputs),1)
        self.assertTrue(self.owner.contexts[self.ident]['closed'])
        with self.app.state.native_history.database() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM foreground_context_outbox WHERE phase='pending'").fetchone()[0],0)

    def test_owner_selected_identity_reaches_native_connector_and_refreshes_on_read(self):
        selected=self.root/'selected-identity.txt'
        text='Oliva: a distinct being. The avatar and integrator share this identity.'
        selected.write_text(text);selected.chmod(0o600)
        self.config['daimon_name']='Oliva'
        self.config['streaming_transcription']['native_identity_file']=str(selected)
        self.select_automatic()
        contexts=[]
        def connector(*args,**kwargs):
            contexts.append(kwargs['context'])
            raise ForegroundUnavailable('Synthetic provider unavailable before readiness')
        # Inspect the authenticated connector boundary without starting unrelated
        # output/return watchers. Existing tests qualify their socket lifecycle.
        with patch('dashboard.native_voice.NativeDialogue',side_effect=connector):
            with self.open() as ws:
                ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'review')
        self.assertEqual(len(contexts),1)
        context=contexts[0]
        self.assertEqual(context['display_name'],'Oliva')
        self.assertEqual(context['being_identity']['text'],text)
        self.assertEqual(context['being_identity']['sha256'],hashlib.sha256(selected.read_bytes()).hexdigest())
        self.assertNotIn(str(selected),json.dumps(context),'Private source path is not provider context')
        selected.write_text('Oliva: updated owner-selected relationship and values.')
        self.assertEqual(being_identity(self.config['streaming_transcription'])['text'],selected.read_text())
        self.assertEqual(context['being_identity']['text'],text,'An existing context keeps its identity snapshot')
        self.assertEqual(self.owner.inputs,{})
        self.assertEqual(self.owner.delegations,[])
        self.assertEqual(Stream.opened,[])
        self.assertEqual(Detector.opened,[])

    def test_identity_failure_prevents_provider_and_microphone_readiness(self):
        selected=self.root/'selected-identity.txt'
        self.config['streaming_transcription']['native_identity_file']=str(selected)
        self.select_automatic()
        # One mounted rejection verifies the preflight boundary. The remaining
        # file cases exercise that reader directly, without repeated socket teardown.
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'review')
        self.assertEqual(Stream.opened,[],'Missing identity must not open the provider')
        self.assertEqual(Detector.opened,[])
        self.assertEqual(self.owner.inputs,{})
        for case in ('missing','oversized','empty','nul','invalid-utf8','readable-by-others','symlink'):
            with self.subTest(case=case):
                if selected.exists() or selected.is_symlink():selected.unlink()
                if case!='missing':
                    selected.write_bytes({'oversized':b'x'*8193,'empty':b'','nul':b'bad\0identity','invalid-utf8':b'\xff'}.get(case,b'Synthetic owner identity'))
                    selected.chmod(0o644 if case=='readable-by-others' else 0o600)
                    if case=='symlink':
                        target=self.root/'identity-target';selected.rename(target);selected.symlink_to(target)
                with self.assertRaises(ForegroundUnavailable):being_identity(self.config['streaming_transcription'])
        self.assertIsNone(being_identity({}),'Identity-free clients retain the existing context path')

    def test_native_identity_binding_requires_explicit_absolute_file_and_dialogue(self):
        for value in (False,{},'relative-identity.txt'):
            with self.subTest(value=value):
                config={**self.config,'streaming_transcription':{**self.config['streaming_transcription'],'native_identity_file':value}}
                with self.assertRaises(ValueError):create_app(config,self.owner,lambda raw,bot:int(raw))
        config={**self.config,'streaming_transcription':{**self.config['streaming_transcription'],'native_dialogue':False,'native_identity_file':str(self.root/'identity')}}
        with self.assertRaises(ValueError):create_app(config,self.owner,lambda raw,bot:int(raw))

    def test_playback_observations_are_fixed_bounded_untrusted_scalars(self):
        value={'type':'playback_status','handled':1,'scheduled':1,'ended':0,
               'skipped_floor':0,'skipped_muted':0,'skipped_retired':0,
               'context':'suspended','audible':True,'user_paused':True,'floor':False,'blocked':False}
        self.assertEqual(playback_status(value),{k:v for k,v in value.items() if k!='type'})
        for invalid in ({**value,'text':'Not allowed'}, {**value,'context':'arbitrary provider text'},
                        {**value,'handled':True},{**value,'ended':16385},{**value,'audible':1}):
            with self.assertRaises(ValueError):playback_status(invalid)

    def test_mounted_playback_observations_reach_existing_close_summary_only(self):
        summaries=queue.Queue()
        def log(message,*args,**kwargs):
            if message=='native_voice_closed %s':summaries.put(json.loads(args[0]))
        value={'type':'playback_status','handled':1,'scheduled':0,'ended':0,
               'skipped_floor':1,'skipped_muted':0,'skipped_retired':0,
               'context':'suspended','audible':True,'user_paused':False,'floor':True,'blocked':True}
        with patch.object(logging.getLogger('uvicorn.error'),'info',side_effect=log):
            with self.open() as ws:
                ws.send_json(self.meta());ready=ws.receive_json();self.assertTrue(ready['playback_status'])
                for _ in range(40):ws.send_json(value)
                ws.send_json({'type':'close'})
            observed=summaries.get(timeout=2)['client_playback']
        self.assertEqual(observed,{'source':'untrusted_client_observation','count':32,
                                  'first':playback_status(value),'last':playback_status(value)})
        self.assertEqual(self.app.state.native_history.page(100)['items'],[],'Observation cannot create output or prove hearing')
        self.assertEqual(self.owner.inputs,{})

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
    def select_automatic(self):
        self.client.__exit__(None,None,None)
        self.config['streaming_transcription']['native_activity_mode']='automatic'
        self.app=create_app(self.config,self.owner,lambda raw,bot:int(raw))
        self.client=TestClient(self.app,base_url='https://example.test');self.client.__enter__()
        self.client.post('/api/session',json={'init_data':'100'},headers={'origin':'https://example.test'})
        self.client.cookies.set('telecodex_dashboard',self.client.cookies.get('telecodex_dashboard'),path='/')
        self.csrf=self.client.get('/api/state').json()['csrf']

    def configure_duration(self,seconds):
        self.client.__exit__(None,None,None)
        self.config['streaming_transcription']['native_session_seconds']=seconds
        self.app=create_app(self.config,self.owner,lambda raw,bot:int(raw))
        self.client=TestClient(self.app,base_url='https://example.test');self.client.__enter__()
        self.client.post('/api/session',json={'init_data':'100'},headers={'origin':'https://example.test'})
        self.client.cookies.set('telecodex_dashboard',self.client.cookies.get('telecodex_dashboard'),path='/')
        self.csrf=self.client.get('/api/state').json()['csrf']

    def test_duration_is_strict_operator_selection_and_client_can_only_narrow(self):
        for invalid in (True,299,1801,600.0):
            self.config['streaming_transcription']['native_session_seconds']=invalid
            with self.assertRaises(ValueError):create_app(self.config,self.owner,lambda raw,bot:int(raw))
        self.configure_duration(600)
        calls=[]
        class Budget(Detector):
            @classmethod
            async def open(cls,*args,**kwargs):
                calls.append(kwargs)
                return await super().open(*args,**kwargs)
        with patch('dashboard.native_voice.Detector',Budget):
            for requested,effective in ((None,300),(300,300),(1800,600)):
                self.ident=str(uuid.uuid4());self.owner.context_closed.clear()
                with self.open() as ws:
                    ws.send_json(self.meta(**({} if requested is None else {'session_seconds':requested})))
                    ready=ws.receive_json();self.assertEqual(ready['type'],'ready')
                    self.assertEqual(ready['session_seconds'],effective)
                    self.assertEqual(calls[-1].get('session_seconds',300),effective)
                    ws.send_json({'type':'close'});self.assertTrue(self.owner.context_closed.wait(2))
                    self.assertTrue(Budget.opened[-1].closed_event.wait(2))
        self.assertEqual(self.owner.inputs,{})

    def test_invalid_client_duration_and_automatic_extension_do_not_open_providers(self):
        for invalid in (True,299,1801,'600'):
            with self.open() as ws:
                ws.send_json(self.meta(session_seconds=invalid))
                self.assertEqual(ws.receive_json()['type'],'review')
        self.assertEqual(Stream.opened,[]);self.assertEqual(Detector.opened,[])
        self.config['streaming_transcription'].update(native_activity_mode='automatic',native_session_seconds=600)
        with self.assertRaises(ValueError):create_app(self.config,self.owner,lambda raw,bot:int(raw))

    def test_explicit_capacity_close_keeps_manual_audio_without_an_onset(self):
        class Quiet(Detector):
            async def feed(self,pcm):
                self.total+=len(pcm)
                await self.queue.put({'type':'activity','audio_bytes':self.total,'generation':0,'speaking':False})
        with patch('dashboard.native_voice.Detector',Quiet),self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            pcm=b'\3\0'*1600;ws.send_bytes(pcm)
            while ws.receive_json()['type']!='turn_activity':pass
            ws.send_json({'type':'close','recover_unassigned':True})
            self.assertTrue(self.owner.context_closed.wait(2))
            self.assertTrue(Quiet.opened[-1].closed_event.wait(2))
        ident,original=next(iter(self.owner.inputs.items()))
        self.assertEqual(original['phase'],'foreground_captured')
        self.assertEqual((self.root/'native.sqlite3.voice'/ident).read_bytes(),wav_bytes(pcm))
        self.assertNotIn('text',original);self.assertEqual(self.owner.delegations,[])

    def test_confirmed_original_releases_resident_pcm_before_next_provider_rollover(self):
        self.configure_duration(600)
        class LongDetector(Detector):
            async def feed(self,pcm):
                previous=self.total;self.total+=len(pcm)
                generation=getattr(self,'generation',0);speaking=getattr(self,'speaking',False)
                value={'type':'activity','audio_bytes':self.total,'generation':generation,'speaking':False}
                if pcm[0]==1:
                    self.generation=generation+1;self.speaking=True
                    value.update(generation=self.generation,speaking=True,
                        onset={'audio_bytes':previous+3072,'generation':self.generation})
                elif speaking:
                    self.speaking=False
                    value['endpoint']={'audio_bytes':self.total,'generation':generation,'authority':'analysis_only','probability':.9}
                await self.queue.put(value)
        with patch('dashboard.native_voice.Detector',LongDetector),self.open() as ws:
            ws.send_json(self.meta(session_seconds=600));self.assertEqual(ws.receive_json()['session_seconds'],600)
            stream=Stream.opened[-1]
            for cycle in range(2):
                for _ in range(198):
                    ws.send_bytes(bytes(32000))
                    while True:
                        value=ws.receive_json();self.assertNotEqual(value['type'],'review',value)
                        if value['type']=='turn_activity':break
                ws.send_bytes(b'\1\0'*16000);ws.send_bytes(bytes(32000))
                original=utterance=None
                while original is None or utterance is None:
                    value=ws.receive_json();self.assertNotEqual(value['type'],'review',value)
                    if value['type']=='original_completed':original=value['id']
                    if value['type']=='assistant_utterance' and value['utterance']['closed']:utterance=value['utterance']
                ws.send_json({'type':'playback','id':utterance['id'],'played_bytes':640})
            self.assertEqual(LongDetector.opened[-1].total,400*32000)
            self.assertEqual(len(self.owner.inputs),2)
            self.assertEqual(Stream.opened,[stream],'Retirement does not replace the provider')
            self.assertEqual(self.owner.delegations,[])
            ws.send_json({'type':'close'});self.assertTrue(self.owner.context_closed.wait(2))
            self.assertTrue(LongDetector.opened[-1].closed_event.wait(2))

    def test_six_hundred_second_pcm_through_two_successors_keeps_one_work_and_return(self):
        self.configure_duration(600)
        class LongDetector(Detector):
            async def feed(self,pcm):
                previous=self.total;self.total+=len(pcm)
                generation=getattr(self,'generation',0);speaking=getattr(self,'speaking',False)
                value={'type':'activity','audio_bytes':self.total,'generation':generation,'speaking':False}
                if pcm[0]==1:
                    self.generation=generation+1;self.speaking=True
                    value.update(generation=self.generation,speaking=True,
                        onset={'audio_bytes':previous+3072,'generation':self.generation})
                elif speaking:
                    self.speaking=False
                    value['endpoint']={'audio_bytes':self.total,'generation':generation,'authority':'analysis_only','probability':.9}
                await self.queue.put(value)
        with patch('dashboard.native_voice.Detector',LongDetector),self.open() as ws:
            ws.send_json(self.meta(session_seconds=600));ready=ws.receive_json()
            self.assertEqual(ready['session_seconds'],600)
            for cycle in range(3):
                old=Stream.opened[-1]
                for _ in range(198):
                    ws.send_bytes(bytes(32000))
                    while True:
                        value=ws.receive_json();self.assertNotEqual(value['type'],'review',value)
                        if value['type']=='turn_activity':break
                ws.send_bytes(b'\1\0'*16000);ws.send_bytes(bytes(32000))
                utterance=original=None
                while utterance is None or original is None:
                    value=ws.receive_json();self.assertNotEqual(value['type'],'review',value)
                    if value['type']=='original_completed':original=value['id']
                    if value['type']=='assistant_utterance' and value['utterance']['closed']:utterance=value['utterance']
                if cycle==0:
                    old.queue.put([{'type':'delegation_proposed','call_id':'admit-work',
                        'original_ids':[original],'formulation':'A synthetic long task stays with Sol.'}])
                    self.assertEqual(old.tool_results.get(timeout=2)[1]['kind'],'integrator_admission')
                if cycle<2:
                    old.rollover_due=True
                    ws.send_json({'type':'playback','id':utterance['id'],'played_bytes':640})
                    self.assertTrue(old.closed_event.wait(3))
                    self.assertEqual(len(Stream.opened),cycle+2)
                else:
                    ws.send_json({'type':'playback','id':utterance['id'],'played_bytes':640})
            self.assertEqual(LongDetector.opened[-1].total,600*32000)
            self.assertEqual(len(self.owner.inputs),3);self.assertEqual(len(self.owner.delegations),1)
            successor=Stream.opened[-1];self.owner.return_ready=True
            (self.root/'native.sqlite3').write_bytes(b'late canonical result after600seconds of PCM')
            self.assertTrue(successor.notice_seen.wait(2))
            successor.queue.put([{'type':'integrator_watch','call_id':'admit-work'}])
            self.assertEqual(successor.tool_results.get(timeout=2)[1]['text'],'Canonical integrating return.')
            self.assertTrue(all(s.total<3*32000 for s in Stream.opened),'Only current phrase PCM, no quiet prefix or old replay')
            ws.send_json({'type':'close'});self.assertTrue(self.owner.context_closed.wait(2))
            self.assertTrue(LongDetector.opened[-1].closed_event.wait(2))

    def test_automatic_speech_keeps_pending_work_returns_and_late_questions_separate_from_correction(self):
        class AutomaticStream(Stream):
            activity_mode='automatic'
            def append(self,pcm):
                super().append(pcm)
                if self.total in (3200,6400):
                    offset='0s' if self.total==3200 else '0.15s'
                    self.queue.put([activity('ACTIVITY_START',offset)])
            def receive(self):
                events=super().receive()
                for event in events:
                    if event['type']=='voice_activity':
                        self.input_active=event['activity']=='ACTIVITY_START'
                        if not self.input_active:self.response_pending=True
                    elif event['type']=='turn_complete':self.response_pending=False
                return events
        def activity(kind,offset):
            return {'type':'voice_activity','activity':kind,'audio_offset':offset,'source':'provider_automatic_activity'}
        def received(ws,kind):
            while True:
                event=ws.receive_json()
                if event['type']==kind:return event
        with patch('dashboard.native_voice.NativeDialogue',AutomaticStream), patch.object(Detector,'open',side_effect=AssertionError('No CPU detector in automatic mode')):
            self.select_automatic()
            with self.open() as ws:
                ws.send_json(self.meta());self.assertEqual(received(ws,'ready')['activity_mode'],'automatic')
                stream=Stream.opened[0]
                ws.send_bytes(b'\1\0'*1600)
                # Provider events are injected, no real inference/native job.
                first=received(ws,'capture_started')['id']
                stream.queue.put([{'type':'input_transcript','text':'First work request.'},activity('ACTIVITY_END','0.1s'),{'type':'turn_complete'}])
                self.assertEqual(received(ws,'original_completed')['id'],first)
                stream.queue.put([{'type':'delegation_proposed','call_id':'work','original_ids':[first],'formulation':'First refined request.'}])
                call,result=stream.tool_results.get(timeout=2)
                self.assertEqual((call,result['kind']),('work','integrator_admission'))
                self.assertEqual(len(self.owner.delegations),1)
                ws.send_bytes(b'\2\0'*1600)
                second=received(ws,'capture_started')['id']
                stream.queue.put([{'type':'source_query','call_id':'old-source','before':0}])
                call,result=stream.tool_results.get(timeout=2)
                self.assertEqual((call,result['kind']),('old-source','not_ready'))
                self.owner.return_ready=True
                (self.root/'native.sqlite3').write_bytes(b'actual fixture return while second speech is active')
                call,result=stream.tool_results.get(timeout=3)
                self.assertEqual(call,'work');self.assertEqual(result['text'],'Canonical integrating return.')
                self.assertTrue(stream.input_active);self.assertEqual(stream.notices,[])
                self.owner.questions=[{'id':'c'*32,'revision':'d'*64,'capture_version':'e'*64,
                    'kind':'question','state':'pending','actionable':True,'label':'#Beta','body':'Breve or detallada?'}]
                (self.root/'native.sqlite3').write_bytes(b'late fixture question during second speech')
                call,result=stream.tool_results.get(timeout=3)
                self.assertEqual(call,'work');self.assertEqual(result['source']['id'],'request:'+'c'*32)
                self.assertIn('Breve or detallada?',result['text'])
                self.assertTrue(stream.input_active);self.assertEqual(stream.notices,[])
                stream.queue.put([activity('ACTIVITY_END','0.2s'),{'type':'input_transcript','text':'A later correction.'},{'type':'turn_complete'}])
                self.assertEqual(received(ws,'original_completed')['id'],second)
                self.assertEqual(self.owner.inputs[second]['text'],'A later correction.')
                self.assertEqual(self.owner.inputs[second]['capture_questions'],{},'The newly offered question cannot widen the active original')
                stream.queue.put([{'type':'source_query','call_id':'current-source','before':0}])
                call,result=stream.tool_results.get(timeout=2)
                self.assertEqual(call,'current-source');self.assertEqual({v['id'] for v in result['sources']},{first,second})
                self.assertEqual(len(self.owner.delegations),1,'Returns, question offers and later speech do not create another work request')
                self.assertEqual(len(self.owner.inputs),2)
                ws.send_json({'type':'close'})
        self.assertEqual(Detector.opened,[])

    def test_automatic_provider_route_retains_exact_source_and_never_opens_cpu_detector(self):
        class AutomaticStream(Stream):
            activity_mode='automatic'
            def append(self,pcm):
                self.total+=len(pcm)
                if self.total==3200:
                    self.queue.put([{'type':'voice_activity','activity':'ACTIVITY_START',
                        'audio_offset':'0.05s','source':'provider_automatic_activity'}])
                elif self.total==6400:
                    self.queue.put([{'type':'input_transcript','text':'Automatic exact interpretation'},
                        {'type':'voice_activity','activity':'ACTIVITY_END','audio_offset':'0.2s','source':'provider_automatic_activity'},
                        {'type':'audio','pcm':b'\1\0'*320,'sample_rate':24000},
                        {'type':'output_transcript','text':'Automatic response.'},{'type':'turn_complete'}])
        with patch('dashboard.native_voice.NativeDialogue',AutomaticStream), patch.object(Detector,'open',side_effect=AssertionError('Automatic mode opened CPU detector')):
            self.select_automatic()
            with self.open() as ws:
                ws.send_json(self.meta());self.assertEqual(ws.receive_json()['activity_mode'],'automatic')
                pcm=b'\1\0'*1600+b'\0\0'*1600
                ws.send_bytes(pcm[:3200]);ws.send_bytes(pcm[3200:])
                events=[]
                while not any(v['type']=='original_completed' for v in events):events.append(ws.receive_json())
                source=next(v['id'] for v in events if v['type']=='capture_started')
                self.assertEqual(next(v['id'] for v in events if v['type']=='voice_activity' and v['activity']=='ACTIVITY_END'),source)
                self.assertEqual(self.owner.inputs[source]['text'],'Automatic exact interpretation')
                self.assertEqual(self.owner.inputs[source]['voice']['audio_sha256'],hashlib.sha256(wav_bytes(pcm)).hexdigest())
                self.assertEqual(self.owner.delegations,[])
                order=[v['type'] for v in events]
                self.assertLess(order.index('phrase_end'),order.index('input_interpreted'))
                self.assertLess(order.index('original_retained'),order.index('original_completed'))
                ws.send_json({'type':'close'})
        self.assertEqual(Detector.opened,[])

    def test_exact_original_and_assistant_history_through_the_mounted_route(self):
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            ws.send_bytes(b'\1\0'*1600);ws.send_bytes(b'\0\0'*1600)
            events=[]
            while not any(v['type']=='original_completed' for v in events) or not any(v['type']=='assistant_utterance' and v['utterance']['closed'] for v in events):
                events.append(ws.receive_json())
            self.assertTrue(self.owner.completed.wait(2))
            audio=next(v for v in events if v['type']=='audio')
            # Sending a control is not its durable receipt. TestClient socket
            # teardown may cancel the route before the asynchronous write runs.
            persisted=threading.Event();played=self.app.state.native_history.played
            def observe_playback(*args):
                result=played(*args);persisted.set();return result
            with patch.object(self.app.state.native_history,'played',observe_playback):
                ws.send_json({'type':'playback','id':audio['id'],'played_bytes':640})
                self.assertTrue(persisted.wait(2),'Wait for the actual playback commit before closing the fixture')
                ws.send_json({'type':'close'})
        self.assertEqual(len(self.owner.inputs),1)
        original=next(iter(self.owner.inputs.values()))
        self.assertEqual(original['phase'],'foreground');self.assertEqual(original['text'],'Exact synthetic interpretation')
        prepared=json.loads((self.root/'prepared'/f"{original['id']}.json").read_text())
        self.assertEqual(prepared['text'],' \nExact synthetic interpretation  ','The prepared source remains exact while the owner normalizes its retained interpretation')
        self.assertEqual(original['voice']['audio_sha256'],hashlib.sha256(wav_bytes(b'\1\0'*1600+b'\0\0'*1600)).hexdigest())
        history=self.client.get('/api/interaction/foreground').json()['items']
        self.assertEqual(history[0]['speaker'],'assistant');self.assertEqual(history[0]['text'],'A native foreground response.')
        self.assertEqual(history[0]['played_bytes'],640);self.assertTrue(history[0]['closed'])
        self.assertEqual(self.owner.calls,[])
        self.assertTrue(Stream.opened[0].closed_event.wait(2),'Wait for actual provider cleanup, not client context exit')
        self.assertTrue(Detector.opened[0].closed_event.wait(2))
    def test_close_journal_records_task_and_error_without_private_content(self):
        observed=queue.Queue()
        def log(message,*args,**kwargs):
            if message=='native_voice_closed %s':observed.put(json.loads(args[0]))
        with patch.object(logging.getLogger('uvicorn.error'),'info',side_effect=log):
            with self.open() as ws:
                ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
                Stream.opened[0].queue.put([{'type':'voice_activity','activity':'ACTIVITY_END',
                    'audio_offset':'0s','source':'provider_manual_activity_ack'}])
                event=ws.receive_json()
                while event['type']!='review':event=ws.receive_json()
                # Observe actual cleanup/journal while the fixture is alive;
                # context teardown can cancel the route before its callback.
                result=observed.get(timeout=2)
        self.assertEqual(result['id'],self.ident)
        self.assertEqual(result['stage'],'native-output')
        self.assertEqual(result['error_type'],'ForegroundUnavailable')
        self.assertEqual(result['cleanup'],'completed')
        self.assertRegex(result['failure_site'],r'^native_acoustic\.provider_event:[0-9]+$')
        self.assertIsNone(result['first_send_failure'])
        self.assertIsNone(result['boundary_mismatch'])
        self.assertEqual(set(result),{'id','stage','error_type','failure_site','first_send_failure','provider_failure_code','owner_operation','provider_controls','boundary_mismatch','elapsed_ms','received_pcm_bytes','received_messages','peak_pending_messages','peak_pending_pcm_bytes','peak_input_queue_wait_ms','actor_checks','acoustic_queues','caption_recovery','generated_pcm_bytes','cleanup','client_playback','context_producer','provider_rollovers','provider_renewal','candidate_setup_failures','provider_context'})
        self.assertGreater(result['actor_checks']['fresh_checks'],0)
        self.assertEqual(result['acoustic_queues'],{'peak_analysis_audio_ms':0,
            'peak_unsent_span_audio_ms':0,'peak_input_confirmation_wait_ms':0})
        self.assertEqual(result['provider_rollovers'],0)
        self.assertEqual(result['provider_renewal'],{'phase':'not_requested','blocked':None,'uninterpreted_originals':0})
        self.assertIn(result['context_producer'],('not_started','active','needs_review','closed'))
        self.assertEqual(self.owner.delegations,[])

    def test_mismatched_boundary_close_retains_only_validated_scalar_timing(self):
        observed=queue.Queue()
        def log(message,*args,**kwargs):
            if message=='native_voice_closed %s':observed.put(json.loads(args[0]))
        with patch.object(logging.getLogger('uvicorn.error'),'info',side_effect=log):
            with self.open() as ws:
                ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
                ws.send_bytes(b'\1\0'*1600)
                event=ws.receive_json()
                while event['type']!='capture_started':event=ws.receive_json()
                self.assertTrue(Stream.opened[0].start_sent.wait(2),'Queue the actual start observation before injecting a later mismatch')
                Stream.opened[0].queue.put([{'type':'voice_activity','activity':'ACTIVITY_START',
                    'audio_offset':'3.000000001s','source':'provider_manual_activity_ack','private_text':'must not reach journal'}])
                event=ws.receive_json()
                while event['type']!='review':event=ws.receive_json()
                # Observe actual cleanup/journal while the fixture is alive;
                # context teardown can cancel the route before its callback.
                # Partial capture retention has its own bounded file/native
                # cleanup. This is a scalar/privacy check, not a 2s close SLA.
                result=observed.get(timeout=30)
        self.assertEqual(result['boundary_mismatch'],{'activity':'start','expected_pcm_bytes':0,
            'reported_offset_nanoseconds':3000000001,'sent_pcm_bytes':3200,'provider_input_bytes':None,
            'span_start':0,'span_end':None,'start_observed':True,'end_observed':False})
        self.assertNotIn('private_text',json.dumps(result));self.assertNotIn('must not reach journal',json.dumps(result))
        self.assertEqual(self.owner.delegations,[])

    def test_first_network_send_failure_survives_later_closed_send(self):
        from starlette.websockets import WebSocket,WebSocketState
        observed=queue.Queue();original=WebSocket.send_json
        def log(message,*args,**kwargs):
            if message=='native_voice_closed %s':observed.put(json.loads(args[0]))
        async def send(socket,value,*args,**kwargs):
            if value.get('type')=='audio':
                socket.application_state=WebSocketState.DISCONNECTED
                raise WebSocketDisconnect(1006,'PRIVATE_NETWORK_DETAIL')
            return await original(socket,value,*args,**kwargs)
        with patch.object(logging.getLogger('uvicorn.error'),'info',side_effect=log),patch.object(WebSocket,'send_json',send):
            with self.open() as ws:
                ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
                Stream.opened[0].queue.put([{'type':'audio','pcm':b'\1\0'*320,'sample_rate':24000}])
                self.assertTrue(Stream.opened[0].closed_event.wait(2),'Observe the actual send failure before closing the client')
            result=observed.get(timeout=2)
        self.assertEqual(result['first_send_failure']['error_type'],'WebSocketDisconnect')
        self.assertEqual(result['first_send_failure']['stage'],'native-output')
        self.assertNotIn('PRIVATE_NETWORK_DETAIL',json.dumps(result))
        self.assertNotIn(str(self.root),json.dumps(result))
        self.assertTrue(Stream.opened[0].closed_event.wait(2))

    def test_missing_provider_final_closes_to_review_and_preserves_exact_original(self):
        def no_transcript(stream):
            stream.queue.put([{'type':'voice_activity','activity':'ACTIVITY_END',
                'audio_offset':f'{stream.total/32000:g}s','source':'provider_manual_activity_ack'},
                {'type':'turn_complete'}])
        with patch.object(Stream,'activity_end',no_transcript),patch('dashboard.native_acoustic.NativeAcousticSession.transcript_timeout',.05),self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            ws.send_bytes(b'\1\0'*1600);ws.send_bytes(b'\0\0'*1600)
            events=[]
            while not events or events[-1]['type']!='review':events.append(ws.receive_json())
            self.assertIn('not confirmed in time',events[-1]['message'])
            self.assertFalse(any(e['type']=='original_completed' for e in events))
        self.assertTrue(Stream.opened[0].closed_event.wait(2))
        self.assertTrue(Detector.opened[0].closed_event.wait(2))
        original=next(iter(self.owner.inputs.values()))
        self.assertEqual(original['phase'],'foreground_captured')
        self.assertEqual(original['voice']['audio_sha256'],hashlib.sha256(wav_bytes(b'\1\0'*1600+b'\0\0'*1600)).hexdigest())
        self.assertEqual(self.owner.delegations,[])
        self.assertFalse(self.owner.completed.is_set())

    def test_manual_detector_failure_before_onset_keeps_unconfirmed_exact_tail(self):
        class FailedBeforeOnset(Detector):
            async def feed(self,pcm):
                self.total+=len(pcm)
                raise DialogueUnavailable('Synthetic detector failure before onset')
        pcm=b'\3\0'*1600
        with patch('dashboard.native_voice.Detector',FailedBeforeOnset):
            with self.open() as ws:
                ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
                ws.send_bytes(pcm)
                while ws.receive_json()['type']!='review':pass
                self.assertTrue(self.owner.context_closed.wait(30),'Wait for actual retained cleanup')
                self.assertTrue(FailedBeforeOnset.opened[-1].closed_event.wait(2),
                                'Context close precedes detector shutdown; observe both before teardown')
        self.assertEqual(len(self.owner.inputs),1)
        ident,original=next(iter(self.owner.inputs.items()))
        self.assertEqual(original['phase'],'foreground_captured')
        self.assertNotIn('text',original)
        self.assertEqual((self.root/'native.sqlite3.voice'/ident).read_bytes(),wav_bytes(pcm))
        self.assertEqual(self.owner.delegations,[])
        self.assertFalse(self.owner.completed.is_set())
        self.assertEqual(Stream.opened[-1].total,0,'No onset can acquire the provider floor')

    def test_automatic_send_failure_before_onset_keeps_unconfirmed_exact_tail(self):
        class FailedBeforeOnset(Stream):
            activity_mode='automatic'
            def append(self,pcm):
                super().append(pcm)
                raise DialogueUnavailable('Synthetic provider send outcome is unknown')
        self.select_automatic()
        pcm=b'\3\0'*1600
        with patch('dashboard.native_voice.NativeDialogue',FailedBeforeOnset):
            with self.open() as ws:
                ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
                ws.send_bytes(pcm)
                event=ws.receive_json()
                while event['type']!='review':event=ws.receive_json()
                self.assertTrue(self.owner.context_closed.wait(2),'Observe completed owned cleanup, not a deferred logging callback')
        self.assertEqual(len(self.owner.inputs),1)
        ident,original=next(iter(self.owner.inputs.items()))
        self.assertEqual(original['phase'],'foreground_captured')
        self.assertNotIn('text',original)
        self.assertEqual((self.root/'native.sqlite3.voice'/ident).read_bytes(),wav_bytes(pcm))
        self.assertEqual(self.owner.delegations,[])
        self.assertFalse(self.owner.completed.is_set())
        self.assertEqual(FailedBeforeOnset.opened[-1].total,len(pcm),'Unknown provider audio is never resent')

    def test_reopened_voice_context_uses_current_binding_without_removing_history(self):
        history=self.app.state.native_history
        current=str(uuid.uuid4());earlier=str(uuid.uuid4())
        history.retain(100,self.ident,self.owner.binding,current,'Current conversation','b'*64,4)
        history.retain(100,self.ident,'c'*64,earlier,'Earlier binding','d'*64,4)
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            sources=Stream.opened[0].context['sources']
            selected=[item['id'] for item in sources if item['speaker']=='assistant_foreground']
            self.assertEqual(selected,[current])
            ws.send_json({'type':'close'})
        self.assertEqual({item['id'] for item in history.page(100)['items']},{current,earlier})
        with self.assertRaises(ValueError):history.page(100,binding='invalid')
    def test_reopened_voice_can_read_complete_retained_return_without_replaying_it(self):
        self.owner.return_ready=True
        self.owner.return_text='Contexto anterior: á. '*100+' Último detalle: azafrán.'
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            stream=Stream.opened[0]
            source=next(v for v in stream.context['sources'] if v['speaker']=='integrator')
            self.assertTrue(source['can_read']);self.assertEqual(source['next_offset'],len(source['text_excerpt']))
            self.assertLessEqual(len(source['text_excerpt'].encode()),1200)
            # The opening excerpt is already offered context; no new work or
            # historical spoken offer is needed to ask for its missing detail.
            stream.queue.put([{'type':'integrating_source_query','call_id':'retained-detail',
                'source':source['id'],'revision':source['revision'],
                'offset':source['next_offset']}])
            call,page=stream.tool_results.get(timeout=2)
            self.assertEqual(call,'retained-detail');self.assertEqual(page['kind'],'integrating_source')
            self.assertEqual(source['text_excerpt']+page['text'],self.owner.return_text)
            self.assertEqual(self.owner.delegations,[])
            ws.send_json({'type':'close'})

    def test_explicit_transcript_fragments_commit_one_complete_original_after_end_marker(self):
        def incomplete_end(stream):
            stream.queue.put([{'type':'voice_activity','activity':'ACTIVITY_END',
                'audio_offset':f'{stream.total/32000:g}s','source':'provider_manual_activity_ack'},
                {'type':'input_transcript','text':'Primera parte ','finished':False}])
        with patch.object(Stream,'activity_end',incomplete_end),self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            ws.send_bytes(b'\1\0'*1600);ws.send_bytes(b'\0\0'*1600)
            seen=[]
            while not any(e['type']=='input_caption' for e in seen):seen.append(ws.receive_json())
            self.assertFalse(self.owner.completed.is_set())
            stream=Stream.opened[0];stream.queue.put([{'type':'turn_complete'}])
            while ws.receive_json()['type']!='turn_complete':pass
            self.assertFalse(self.owner.completed.is_set(),'Model completion is not human transcript completion')
            stream.queue.put([{'type':'input_transcript','text':'y final.','finished':False},
                              {'type':'input_transcript','text':'','finished':True}])
            while not any(e['type']=='original_completed' for e in seen):seen.append(ws.receive_json())
            captions=[e['text'] for e in seen if e['type']=='input_caption']
            self.assertEqual(captions[-1],'Primera parte y final.')
            self.assertFalse(any(e['type']=='input_transcript' for e in seen),'Raw fragments and empty end markers must not overwrite accumulated captions')
            ws.send_json({'type':'close'})
        self.assertEqual(len(self.owner.inputs),1)
        self.assertEqual(next(iter(self.owner.inputs.values()))['text'],'Primera parte y final.')
        self.assertEqual(self.owner.delegations,[])
    def test_native_voice_continues_while_an_integrating_return_watch_is_pending(self):
        self.owner.return_kind='integrator_progress'
        self.owner.native_returns=['result:retained-worker-return']
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
            stream.queue.put([{'type':'audio','pcm':b'\2\0'*320,'sample_rate':24000},
                              {'type':'output_transcript','text':'I can keep talking while work continues.'},
                              {'type':'turn_complete'}])
            while ws.receive_json()['type']!='audio':pass
            self.assertTrue(stream.tool_results.empty(),'Waiting for a result does not block native audio')
            self.owner.return_ready=True
            (self.root/'native.sqlite3').write_bytes(b'synthetic source notification')
            call,result=stream.tool_results.get(timeout=3)
            self.assertEqual(call,'work');self.assertEqual(result['text'],'Canonical integrating return.')
            self.assertEqual(stream.notices,[],'A continued delegation needs no additional control turn')
            self.assertEqual(len(self.owner.delegations),1)
            ws.send_json({'type':'close'})
    def test_canonical_pending_questions_offer_complete_choices_without_waiting_for_sol_summary(self):
        self.owner.questions=[{'id':f'{i:032x}','revision':'d'*64,'kind':'question','state':'pending',
            'actionable':True,'capture_version':'e'*64,'label':'#Beta','body':f'Question {i}: breve or detallada?'} for i in range(1,11)]
        self.owner.questions[0]['kind']='approval'
        self.owner.questions[1]['state']='answered'
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            stream=Stream.opened[0];stream.queue.put([{'type':'integrator_watch','call_id':'questions'}])
            offered=[stream.tool_results.get(timeout=3)[1] for _ in range(8)]
            events=[]
            while not events or events[-1]['type']!='question_scope':events.append(ws.receive_json())
            self.assertEqual(events[-1]['capture_questions'],{f'{i:032x}':'e'*64 for i in range(3,11)})
            self.assertEqual({r['source']['id'] for r in offered},{'request:'+f'{i:032x}' for i in range(3,11)})
            self.assertTrue(all(r['source']['kind']=='question' and 'breve or detallada?' in r['text'] for r in offered))
            self.assertTrue(all(r['text'].startswith('#Beta. ') for r in offered))
            self.assertFalse(self.owner.return_ready,'A question needs no lossy Sol summary to become canonical')
            self.assertEqual(self.owner.delegations,[],'Reading a native question is not answering or dispatching')
            ws.send_json({'type':'close'})

    def test_question_capture_scope_precedes_immediate_question_audio(self):
        self.owner.questions=[{'id':'c'*32,'revision':'d'*64,'capture_version':'e'*64,
            'kind':'question','state':'pending','actionable':True,'label':'#Beta','body':'Breve or detallada?'}]
        original=Stream.tool_result
        def respond(stream,ident,result,**kwargs):
            original(stream,ident,result,**kwargs)
            if result.get('kind')=='integrating_source':
                stream.queue.put([{'type':'audio','pcm':b'\1\0'*320,'sample_rate':24000},
                                  {'type':'output_transcript','text':'Breve or detallada?'},{'type':'turn_complete'}])
        with patch.object(Stream,'tool_result',respond),self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            Stream.opened[0].queue.put([{'type':'integrator_watch','call_id':'questions'}])
            events=[]
            while not any(e['type']=='audio' for e in events):events.append(ws.receive_json())
            scope=next(e for e in events if e['type']=='question_scope')
            self.assertEqual(scope['capture_questions'],{'c'*32:'e'*64})
            self.assertLess(next(i for i,e in enumerate(events) if e['type']=='question_scope'),next(i for i,e in enumerate(events) if e['type']=='audio'))
            self.assertEqual(self.owner.inputs,{})
            self.assertEqual(self.owner.delegations,[])
            ws.send_json({'type':'close'})

    def test_answered_question_is_not_re_read_and_next_revision_keeps_the_same_watch(self):
        question={'id':'c'*32,'revision':'d'*64,'kind':'question','state':'pending',
                  'actionable':True,'capture_version':'e'*64,'label':'#Beta','body':'Choose breve or detallada.'}
        self.owner.questions=[question]
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            stream=Stream.opened[0];stream.queue.put([{'type':'integrator_watch','call_id':'questions'}])
            call,offered=stream.tool_results.get(timeout=3)
            self.assertEqual(call,'questions')
            question['state']='answered'
            stream.queue.put([{'type':'integrating_source_query','call_id':'stale',
                'source':offered['source']['id'],'revision':offered['source']['revision'],'offset':0}])
            call,rejected=stream.tool_results.get(timeout=2)
            self.assertEqual(call,'stale');self.assertEqual(rejected['kind'],'not_ready')
            question.update(state='pending',revision='e'*64,capture_version='f'*64,body='The next actual question.')
            (self.root/'native.sqlite3').write_bytes(b'next canonical question revision')
            call,current=stream.tool_results.get(timeout=3)
            self.assertEqual(call,'questions','A stale page must not end the existing return watch')
            self.assertEqual(current['source']['revision'],'e'*64)
            self.assertIn('The next actual question.',current['text'])
            self.assertEqual(self.owner.delegations,[])
            ws.send_json({'type':'close'})

    def test_native_voice_can_read_the_remainder_of_an_offered_long_return(self):
        self.owner.return_text='Contexto inicial. '*100+' Último detalle: azafrán.'
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            stream=Stream.opened[0]
            stream.queue.put([{'type':'integrator_watch','call_id':'watch'}])
            self.owner.return_ready=True
            (self.root/'native.sqlite3').write_bytes(b'synthetic source notification')
            call,result=stream.tool_results.get(timeout=3)
            self.assertEqual(call,'watch');self.assertEqual(result['next_offset'],1600)
            stream.queue.put([{'type':'integrating_source_query','call_id':'remainder',
                'source':result['source']['id'],'revision':result['source']['revision'],'offset':result['next_offset']}])
            call,page=stream.tool_results.get(timeout=2)
            self.assertEqual(call,'remainder');self.assertEqual(page['kind'],'integrating_source')
            self.assertEqual(result['text']+page['text'],self.owner.return_text)
            self.assertIsNone(page['next_offset']);self.assertEqual(self.owner.delegations,[])
            ws.send_json({'type':'close'})

    def test_source_tool_reads_current_playback_without_claiming_hearing(self):
        history=self.app.state.native_history
        ident=str(uuid.uuid4());other=str(uuid.uuid4())
        history.retain(100,self.ident,self.owner.binding,ident,'Interrupted generated words','b'*64,640,interrupted=True)
        history.played(100,self.ident,ident,160)
        history.retain(100,str(uuid.uuid4()),self.owner.binding,other,'Another voice session','c'*64,640)
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            stream=Stream.opened[0]
            stream.queue.put([{'type':'source_query','call_id':'playback-before','before':0}])
            _,result=stream.tool_results.get(timeout=2)
            observed=result['assistant_speech']
            self.assertEqual([item['id'] for item in observed],[ident])
            self.assertEqual(observed[0]['played_bytes'],160)
            self.assertEqual(observed[0]['generated_bytes'],640)
            self.assertTrue(observed[0]['interrupted'])
            self.assertIn('not a contiguous heard range',observed[0]['meaning'])
            history.played(100,self.ident,ident,320)
            stream.queue.put([{'type':'source_query','call_id':'playback-after','before':0}])
            _,result=stream.tool_results.get(timeout=2)
            self.assertEqual(result['assistant_speech'][0]['played_bytes'],320,'Read current observations rather than opening-time context')
            self.assertEqual(self.owner.delegations,[])
            ws.send_json({'type':'close'})
    def test_recovered_caption_keeps_approximate_provenance_in_setup_and_source_tool(self):
        history=self.app.state.native_history;parent=str(uuid.uuid4())
        history.retain(100,self.ident,self.owner.binding,parent,'','b'*64,640)
        draft=history.retain_caption(100,self.ident,self.owner.binding,parent,'b'*64,640,
            {'text':'Approximate recovered assistant words.','final':True})
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            stream=Stream.opened[0]
            retained=next(s for s in stream.context['sources'] if s['id']==draft['id'])
            self.assertEqual(retained['derived_caption'],draft['derived_caption'])
            stream.queue.put([{'type':'source_query','call_id':'draft','before':0}])
            _,result=stream.tool_results.get(timeout=2)
            observed=next(s for s in result['assistant_speech'] if s['id']==draft['id'])
            self.assertEqual(observed['derived_caption'],draft['derived_caption'])
            self.assertEqual(observed['generated_bytes'],0)
            self.assertEqual(self.owner.delegations,[])
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
            # A later receive, not another event in the cancellation batch,
            # must still reach the same live socket.
            stream.queue.put([{'type':'output_transcript','text':'After cancellation.'},
                              {'type':'turn_complete'}])
            later=[]
            while not later or later[-1]['type']!='turn_complete':later.append(ws.receive_json())
            self.assertTrue(any(v['type']=='assistant_utterance' and v['utterance']['text']=='After cancellation.' for v in later))
            self.assertFalse(stream.closed);self.assertEqual(self.owner.delegations,[])
            ws.send_json({'type':'close'})

    def test_existing_source_metadata_can_become_a_current_return(self):
        self.owner.return_kind='integrator_progress'
        self.owner.return_current=False
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            stream=Stream.opened[0]
            stream.queue.put([{'type':'integrator_watch','call_id':'watch'}])
            self.owner.return_ready=True
            (self.root/'native.sqlite3').write_bytes(b'progress first visible')
            self.assertTrue(self.owner.return_seen.wait(2))
            self.assertTrue(stream.tool_results.empty())
            # Same ID, revision and row cursor; canonical metadata changes.
            self.owner.native_returns=['result:retained-worker-result']
            self.owner.return_current=True
            (self.root/'native.sqlite3').write_bytes(b'current source-linked return')
            call,result=stream.tool_results.get(timeout=2)
            self.assertEqual(call,'watch');self.assertEqual(result['text'],'Canonical integrating return.')
            ws.send_json({'type':'close'})

    def test_new_return_without_speech_or_model_watch_gets_one_internal_notice(self):
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            stream=Stream.opened[0]
            self.owner.return_ready=True
            (self.root/'native.sqlite3').write_bytes(b'new result before human speech')
            self.assertTrue(self.owner.return_seen.wait(2))
            self.assertTrue(stream.notice_seen.wait(2),'A queued return must not depend on another human phrase')
            self.assertEqual(len(stream.notices),1)
            self.assertEqual(self.owner.inputs,{});self.assertEqual(self.owner.delegations,[])
            ws.send_json({'type':'close'})

    def test_idle_return_notice_waits_for_existing_audio_playback(self):
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            stream=Stream.opened[0]
            stream.queue.put([{'type':'audio','pcm':b'\1\0'*320,'sample_rate':24000},
                              {'type':'output_transcript','text':'Existing speech.'},{'type':'turn_complete'}])
            while True:
                value=ws.receive_json()
                if value['type']=='assistant_utterance' and value['utterance']['closed']:
                    utterance=value['utterance'];break
            self.owner.return_ready=True
            (self.root/'native.sqlite3').write_bytes(b'new result while output is queued')
            self.assertTrue(self.owner.return_seen.wait(2))
            self.assertFalse(stream.notice_seen.wait(.05),'Queued or paused speech must keep the floor')
            ws.send_json({'type':'playback','id':utterance['id'],'played_bytes':640})
            self.assertTrue(stream.notice_seen.wait(2))
            self.assertEqual(len(stream.notices),1);self.assertEqual(self.owner.delegations,[])
            ws.send_json({'type':'close'})

    def test_shared_home_input_burst_waits_at_the_same_memory_bound(self):
        from dashboard.live_transcription import VoiceInbox
        self.client.__exit__(None,None,None);home='https://home.example.test'
        self.config.update(origin=home,shared_auth={'enabled':True,'home_origin':home})
        self.app=create_app(self.config,self.owner,lambda raw,bot:int(raw))
        self.client=TestClient(self.app,base_url=home);self.client.__enter__()
        self.client.cookies.set('__Host-home','h'*43,path='/')
        held=threading.Event();release=threading.Event();full=threading.Event();fed=threading.Event();inboxes=[]
        class ObservedInbox(VoiceInbox):
            def __init__(self,receive,**kwargs):
                async def observed():
                    value=await receive()
                    if self.pcm and self.bytes>=252800:full.set()
                    return value
                super().__init__(observed,**kwargs)
                if self.pcm:inboxes.append(self)
        class Quiet(Detector):
            async def feed(self,pcm):
                self.total+=len(pcm)
                if self.total==320000:fed.set()
                await self.queue.put({'type':'activity','audio_bytes':self.total,'generation':0,'speaking':False})
        def identity(origin,token):
            if held.is_set() and not release.wait(2):raise OSError('Synthetic blocked identity')
            return {'contract':'dm.home-session/v1','origin':origin,'expires':int(time.time())+3600,
                    'actor':{'kind':'human','ref':'human:telegram:100'}}
        with patch('dashboard.home_auth.identity_response',side_effect=identity),patch('dashboard.native_voice.VoiceInbox',ObservedInbox),patch('dashboard.native_voice.Detector',Quiet):
            self.csrf=self.client.get('/api/interaction/access').json()['csrf']
            with self.client.websocket_connect('wss://home.example.test/api/interaction/voice/native',headers={'origin':home}) as ws:
                ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
                held.set()
                try:
                    for _ in range(100):ws.send_bytes(b'\0'*3200)
                    self.assertTrue(full.wait(1),'The burst must actually fill the retained native input queue')
                    self.assertIsNone(inboxes[0].error)
                    release.set()
                    self.assertTrue(fed.wait(2),'All captured bytes must reach the detector after fresh authorization returns')
                    self.assertEqual(inboxes[0].received_bytes,320000)
                    self.assertLessEqual(inboxes[0].peak_bytes,256000)
                    self.assertEqual(self.owner.inputs,{})
                    ws.send_json({'type':'close'})
                finally:release.set()

    def test_shared_home_playback_progress_does_not_starve_captured_pcm(self):
        # Small PCM buffers can finish faster than a fresh home-identity lookup.
        # Exercise the actual cookie-auth path, not the fast Telegram fixture.
        self.client.__exit__(None,None,None);home='https://home.example.test'
        self.config.update(origin=home,shared_auth={'enabled':True,'home_origin':home})
        self.app=create_app(self.config,self.owner,lambda raw,bot:int(raw))
        self.client=TestClient(self.app,base_url=home);self.client.__enter__()
        self.client.cookies.set('__Host-home','h'*43,path='/');checks=[]
        class Quiet(Detector):
            async def feed(self,pcm):
                self.total+=len(pcm)
                await self.queue.put({'type':'activity','audio_bytes':self.total,'generation':0,'speaking':False})
        def identity(origin,token):
            checks.append(time.monotonic());time.sleep(.03)
            return {'contract':'dm.home-session/v1','origin':origin,'expires':int(time.time())+3600,
                    'actor':{'kind':'human','ref':'human:telegram:100'}}
        completed=threading.Event();failures=[];positions=[];closes=[];played=self.app.state.native_history.played
        def observe(*args):
            value=played(*args);positions.append(args[-1])
            if args[-1]==360:completed.set()
            return value
        def log(message,*args,**kwargs):
            if message=='native_voice_closed %s':closes.append(json.loads(args[0]))
        with patch.object(logging.getLogger('uvicorn.error'),'info',side_effect=log),patch('dashboard.home_auth.identity_response',side_effect=identity),patch('dashboard.native_voice.Detector',Quiet),patch.object(self.app.state.native_history,'played',observe):
            self.csrf=self.client.get('/api/interaction/access').json()['csrf']
            with self.client.websocket_connect('wss://home.example.test/api/interaction/voice/native',headers={'origin':home}) as ws:
                ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
                Stream.opened[0].queue.put([{'type':'audio','pcm':b'\1\0'*16000,'sample_rate':24000}])
                value=ws.receive_json()
                while value['type']!='audio':value=ws.receive_json()
                utterance=value['id'];before=len(checks)
                def send():
                    try:
                        for n in range(1,181):
                            ws.send_json({'type':'playback','id':utterance,'played_bytes':n*2})
                            if n%12==0:ws.send_bytes(b'\0\0'*1600)
                            time.sleep(.008)
                    except Exception as error:failures.append(type(error).__name__)
                producer=threading.Thread(target=send);producer.start()
                try:self.assertTrue(completed.wait(4),'Playback controls must not fill the input queue while microphone PCM waits for authorization: '+json.dumps(closes))
                finally:producer.join(timeout=3)
                self.assertFalse(producer.is_alive());self.assertEqual(failures,[])
                self.assertEqual(positions,list(range(2,361,2)))
                self.assertLess(len(checks)-before,120,'Already queued native controls share a fresh batch check, without an auth cache')
                ws.send_json({'type':'close'})
                self.assertTrue(self.owner.context_closed.wait(2),'Observe normal close before fixture teardown')
                self.assertTrue(Quiet.opened[-1].closed_event.wait(2))
        self.assertTrue(Stream.opened[0].closed_event.wait(2))
        self.assertEqual(Quiet.opened[-1].total,48000,'All microphone frames are processed in order without loss')
        self.assertEqual(self.owner.inputs,{});self.assertEqual(self.owner.delegations,[])

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
    def test_unavailable_acoustics_are_refused_before_provider_opening(self):
        from dashboard.turn_detection import DetectionUnavailable
        with patch.object(Detector,'open',side_effect=DetectionUnavailable('synthetic unavailable')):
            with self.open() as ws:
                ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'review')
        self.assertEqual(Stream.opened,[])
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

    def test_observer_status_is_available_in_native_voice_without_delegating_work(self):
        reads=[]
        def status():
            reads.append(True)
            return {'connected':True,'observed_at':123,'sources':[{'label':'Conversation','fresh':True,'observed_at':122,'execution':'running','goal_state':'active'}]}
        self.owner.sonic_activity=status
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            stream=Stream.opened[0];stream.queue.put([{'type':'session_status_query','call_id':'observer'}])
            call,result=stream.tool_results.get(timeout=2)
            self.assertEqual(call,'observer');self.assertEqual(result['sessions'][0]['label'],'Conversation')
            self.assertEqual(len(reads),1);self.assertEqual(self.owner.delegations,[]);self.assertEqual(self.owner.inputs,{})
            ws.send_json({'type':'close'})

    def test_mounted_recent_results_query_reuses_existing_presentation_reader(self):
        reads=[]
        original=self.owner.presentation_list;enabled=[]
        def listed(*args):
            if not enabled or len(args)<3 or args[2]!='before':return original(*args)
            reads.append(args)
            return {'items':[{'id':'native:123','revision':'c'*64,'kind':'integrator_answer','preview':'Useful result'}]}
        self.owner.presentation_list=listed
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            stream=Stream.opened[0]
            enabled.append(True)
            stream.queue.put([{'type':'recent_results_query','call_id':'results','delivery':0,'native':0}])
            call,result=stream.tool_results.get(timeout=2)
            self.assertEqual(call,'results');self.assertEqual(result['items'][0]['id'],'native:123')
            self.assertEqual(reads,[(0,0,'before')]);self.assertEqual(self.owner.delegations,[])
            ws.send_json({'type':'close'})

    def test_rejected_tool_keeps_mounted_voice_open_for_next_read(self):
        self.owner.sonic_activity=lambda:{'connected':True,'sources':[]}
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            stream=Stream.opened[0]
            stream.queue.put([{'type':'tool_rejected','call_id':'bad-arguments'}])
            call,result=stream.tool_results.get(timeout=2)
            self.assertEqual(call,'bad-arguments');self.assertFalse(result['operation_started'])
            stream.queue.put([{'type':'session_status_query','call_id':'valid-read'}])
            call,result=stream.tool_results.get(timeout=2)
            self.assertEqual(call,'valid-read');self.assertEqual(result['kind'],'session_status')
            self.assertEqual(self.owner.delegations,[]);self.assertEqual(self.owner.inputs,{})
            ws.send_json({'type':'close'})

    def test_idle_notice_does_not_interrupt_active_human_capture(self):
        with self.open() as ws:
            ws.send_json(self.meta());self.assertEqual(ws.receive_json()['type'],'ready')
            stream=Stream.opened[0];ws.send_bytes(b'\1\0'*1600)
            while ws.receive_json()['type']!='capture_started':pass
            self.owner.return_ready=True
            (self.root/'native.sqlite3').write_bytes(b'new result while human is speaking')
            self.assertTrue(self.owner.return_seen.wait(2));self.assertFalse(stream.notice_seen.wait(.05))
            ws.send_bytes(b'\0\0'*1600)
            while True:
                value=ws.receive_json()
                if value['type']=='assistant_utterance' and value['utterance']['closed']:
                    utterance=value['utterance'];break
            self.assertFalse(stream.notice_seen.is_set())
            ws.send_json({'type':'playback','id':utterance['id'],'played_bytes':640})
            self.assertTrue(stream.notice_seen.wait(2));self.assertEqual(self.owner.delegations,[])
            ws.send_json({'type':'close'})

    def test_notice_floor_uses_latest_serialized_audio_without_rewriting_old_gaps(self):
        history=self.app.state.native_history;old=str(uuid.uuid4());fresh=str(uuid.uuid4())
        history.retain(100,self.ident,self.owner.binding,old,'Interrupted earlier speech','b'*64,8)
        history.played(100,self.ident,old,2)
        self.assertTrue(history.pending_audio(100,self.ident))
        history.retain(100,self.ident,self.owner.binding,fresh,'Fresh speech','c'*64,4)
        self.assertTrue(history.pending_audio(100,self.ident))
        history.played(100,self.ident,fresh,4)
        self.assertFalse(history.pending_audio(100,self.ident))
        previous=next(v for v in history.page(100)['items'] if v['id']==old)
        self.assertEqual(previous['played_bytes'],2,'Later playback is not a contiguous hearing receipt')
        self.assertFalse(history.pending_audio(101,self.ident))

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

    def test_pcm_updates_stay_bounded_with_a_full_populated_text_history(self):
        from contextlib import contextmanager
        history=self.app.state.native_history;ident=str(uuid.uuid4())
        history.retain(100,self.ident,self.owner.binding,ident,'Words','b'*64,0,closed=False)
        original_database=history.database
        with original_database() as db:
            # Global bounds include other actors; no original needs to be deleted
            # merely to continue an already-admitted assistant utterance.
            db.executemany("""INSERT INTO foreground_utterances
                (id,human,scope,dialogue,binding,observed_at,text,model,audio_sha256,
                 generated_bytes,interrupted,closed) VALUES(?,?,?,?,?,0,?,'fixture',?,0,0,1)""",
                [(str(uuid.uuid4()),101,history.scope,self.ident,self.owner.binding,'x'*256,'b'*64)
                 for _ in range(4096)])
        history.max_rows=4097;history.max_bytes=4096*256+len('Words')
        @contextmanager
        def bounded_database():
            with original_database() as db:
                # A deterministic SQLite work budget, independent of wall-clock
                # speed: indexed single-utterance updates fit; a whole-history
                # aggregate for each PCM fragment does not.
                db.set_progress_handler(lambda:1,10000)
                yield db
        history.database=bounded_database
        try:
            for end in range(640,640*17,640):
                history.retain(100,self.ident,self.owner.binding,ident,'Words','c'*64,end,closed=False)
            history.played(100,self.ident,ident,640*16)
        finally:history.database=original_database
        item=history.page(100)['items'][0]
        self.assertEqual((item['text'],item['generated_bytes'],item['played_bytes'],item['closed']),
                         ('Words',640*16,640*16,False))
        with self.assertRaises(ValueError):
            history.retain(100,self.ident,self.owner.binding,str(uuid.uuid4()),'New','d'*64,2)
        # The admitted open utterance still cannot grow text beyond the bound.
        with self.assertRaises(ValueError):
            history.retain(100,self.ident,self.owner.binding,ident,'Words!','d'*64,640*16)
        self.assertEqual(history.page(100)['items'][0]['text'],'Words')
        history.database=bounded_database
        try:history.retain(100,self.ident,self.owner.binding,ident,'Words','c'*64,640*16,closed=True)
        finally:history.database=original_database
        self.assertTrue(history.page(100)['items'][0]['closed'])

    def test_history_does_not_rewrite_a_closed_utterance_or_cross_owner(self):
        history=self.app.state.native_history;ident=str(uuid.uuid4())
        history.retain(100,self.ident,self.owner.binding,ident,'Retained','b'*64,4)
        with self.assertRaises(ValueError):history.retain(100,self.ident,self.owner.binding,ident,'Changed','c'*64,8)
        self.assertEqual(history.page(101)['items'],[])
        with self.assertRaises(ValueError):history.played(101,self.ident,ident,2)
        history.max_rows=1
        with self.assertRaises(ValueError):history.capacity()


if __name__=='__main__':
    # A stalled synthetic close previously consumed the entire CI job without
    # naming the test. Bound this four-second suite and retain thread evidence.
    import faulthandler
    faulthandler.dump_traceback_later(30,exit=True)
    try:unittest.main(verbosity=2)
    finally:faulthandler.cancel_dump_traceback_later()
