"""Mounted public Live auth, source/creation loss and original recovery; zero models."""
import asyncio
import json
from pathlib import Path
import queue
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from dashboard.companion import permitted
from dashboard.live_transcription import wav_bytes
from dashboard.openai_live import LiveCall, LiveUnavailable, session_spec
from dashboard.openai_live_api import install
from dashboard.openai_live_visits import LiveCreations
from dashboard.provider import Provider, ProviderUnavailable


class Owner:
    human=100
    binding_bytes=b'public-live-synthetic-receiver'
    retain_voice_capture=staticmethod(Provider.retain_voice_capture)
    def __init__(self,root):
        self.receiver={'db_path':str(root/'receiver.sqlite')}
        self.media_retention=None;self.binding='a'*64;self.held=False
    def presentation(self,command):return {'binding':self.binding}
    def presentation_list(self,*args):return {'binding':self.binding,'items':[]}
    def authorized(self,human):return human==100
    def assert_binding(self):pass
    def close(self):pass
    def public_live_binding(self,binding):
        if binding!=self.binding or self.held:raise ProviderUnavailable('Changed synthetic owner')
        return {'binding':binding,'entry_binding':[100,{'chat_id':100,'thread_id':7},1,'thread'],
                'native_thread':'thread'}


class Client:
    instances=[];failure=None
    def __init__(self,key):
        self.events=queue.Queue();self.sent=[];self.creations=0;self.detached=False;self.forks=[]
        self.instances.append(self)
    def _project_key(self):return 'test-only-project-key'
    def create(self,sdp,spec):
        self.creations+=1;self.spec=spec
        if self.failure:raise LiveUnavailable(self.failure)
        return LiveCall('live_opaque:provider/42','v=0 answer')
    def fork(self,source,sdp):
        self.forks.append((source,sdp))
        if self.failure:raise LiveUnavailable(self.failure)
        return LiveCall('live_opaque:provider/fork-'+str(len(Client.instances)),'v=0 fork answer')
    def attach(self,call):
        self.session_id=call.session_id
        self.events.put({'type':'session.started','event_id':'start','session':{'id':call.session_id}})
        return self
    def receive(self):
        try:return self.events.get(timeout=.02)
        except queue.Empty:return None
    def send(self,event):
        self.sent.append(event)
        if event['type']=='session.close':
            self.events.put({'type':'session.closed','event_id':'closed','reason':'close_requested',
                'session':{'id':self.session_id},'usage':{'seconds':12}})
    def detach(self):self.detached=True


class Mounted(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.owner=Owner(self.root)
        self.state=self.root/'state';self.state.mkdir(mode=0o700)
        for name in ('identity','backend','key'):
            p=self.root/name;p.write_text('You are CompAII. Be brief.');p.chmod(0o600)
        self.config={'state_dir':str(self.state),'openai_live':{'enabled':True,
            'identity_file':str(self.root/'identity'),'backend_instructions_file':str(self.root/'backend'),
            'api_key_file':str(self.root/'key'),'backend_model':'explicit-backend','session_seconds':300}}
        self.allowed=True;self.scope=None;self.app=FastAPI();self.app.state.voice_active=set()
        async def authorize(request):
            if not self.allowed:raise HTTPException(401,'Expired synthetic access')
            return {'human':100,'csrf':'fresh','scope':self.scope}
        self.assertTrue(install(self.app,self.config,self.owner,authorize,['https://example.test']))
        self.client=TestClient(self.app,base_url='https://example.test');self.addCleanup(self.client.close)
        self.replacement=patch('dashboard.openai_live_api.OpenAILive',Client);self.replacement.start();self.addCleanup(self.replacement.stop)
        Client.instances=[];Client.failure=None
        self.ident=str(uuid.uuid4());self.meta={'id':self.ident,'binding':'a'*64,'csrf':'fresh'}
        self.headers={'origin':'https://example.test','x-dashboard-csrf':'fresh','x-voice-binding':'a'*64}
    def socket(self):return self.client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'})
    def read(self):return json.loads((self.state/'public-live-visits'/(self.ident+'.json')).read_text())
    def start(self,socket):
        socket.send_json(self.meta);ready=socket.receive_json();self.assertEqual(ready['type'],'prepared')
        self.assertEqual(Client.instances[-1].creations,0,'Admission precedes billable creation')
        socket.send_json({'type':'offer','sdp':'v=0 offer'})
        answer=socket.receive_json();self.assertEqual(answer['type'],'answer');self.assertEqual(answer['session'],'live_opaque:provider/42')
        self.assertEqual(socket.receive_json()['event']['type'],'session.started')
        return Client.instances[-1]
    def close(self,socket):
        socket.send_json({'type':'close'});self.assertEqual(socket.receive_json()['type'],'finishing')
        result=socket.receive_json();self.assertEqual(result['type'],'closed');return result
    def test_native_original_opt_in_uses_exact_owner_and_never_repeats_lost_ack(self):
        app=FastAPI();app.state.voice_active=set()
        async def authorize(request):return {'human':100,'csrf':'fresh'}
        config={**self.config,'openai_live':{**self.config['openai_live'],'native_originals':True}}
        install(app,config,self.owner,authorize,['https://example.test'])
        calls=[];saved={}
        def submit(metadata,data,**options):
            calls.append((metadata,options))
            assert 'text' not in metadata and options=={'foreground_dialogue':self.ident,'defer_foreground':True}
            saved.update(id=metadata['id'],entry_binding=self.owner.public_live_binding('a'*64)['entry_binding'],
                foreground_dialogue=self.ident,voice={'audio_sha256':metadata['audio_sha256']},
                phase='foreground_captured',native_acceptance='not_requested')
            raise ProviderUnavailable('Synthetic ACK lost after native retention')
        self.owner.conversation_voice_submit=submit
        self.owner.conversation_input_status=lambda ident:dict(saved)
        with TestClient(app,base_url='https://example.test') as client:
            with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as socket:
                socket.send_json(self.meta);self.assertEqual(socket.receive_json()['type'],'prepared')
                path='/api/interaction/voice/gpt-live/visits/'+self.ident+'/recordings/0'
                audio=wav_bytes(b'\0\0'*800)
                self.assertEqual(client.post(path,headers={**self.headers,'x-dashboard-csrf':'stale'},content=audio).status_code,403)
                first=client.post(path,headers=self.headers,content=audio)
                self.assertEqual(first.status_code,200,first.text)
                self.assertEqual(first.json()['native_original']['state'],'unconfirmed')
                again=client.post(path,headers=self.headers,content=audio)
                self.assertEqual(again.json()['native_original']['state'],'observed')
                self.assertEqual(len(calls),1);self.assertFalse(again.json()['native_original']['work_admitted'])
                self.assertEqual(Client.instances[-1].creations,0)

    def test_owner_opt_in_context_tool_returns_result_then_resumes_managed_backend(self):
        from dashboard.openai_live_context import NAME
        app=FastAPI();app.state.voice_active=set()
        async def authorize(request):return {'human':100,'csrf':'fresh'}
        config={**self.config,'openai_live':{**self.config['openai_live'],'conversation_context':True}}
        install(app,config,self.owner,authorize,['https://example.test'])
        self.owner.presentation_list=lambda *a,**k:{'binding':'a'*64,'items':[],
            'cursor':{'delivery':0,'native':0,'matrix':0},'more':False}
        with TestClient(app,base_url='https://example.test') as client:
            with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as socket:
                native=self.start(socket)
                self.assertEqual(native.spec['delegation']['responses']['tools'][0]['name'],NAME)
                for event in [
                    {'type':'session.delegation.created','event_id':'work','delegation':{
                        'id':'work','target':'responses','response_id':'r1'}},
                    {'type':'response.event','event_id':'call','delegation_id':'work','event':{
                        'type':'response.output_item.done','item':{'type':'function_call','call_id':'call',
                        'name':NAME,'arguments':json.dumps({'operation':'page','delivery':0,'native':0,
                            'matrix':0,'source':'','revision':'','offset':0})}}},
                    {'type':'response.event','event_id':'done','delegation_id':'work','event':{
                        'type':'response.completed','response':{'id':'r1'}}}]:
                    native.events.put(event);self.assertEqual(socket.receive_json()['event'],event)
                deadline=time.monotonic()+2
                while len(native.sent)<2 and time.monotonic()<deadline:time.sleep(.01)
                self.assertEqual([v['type'] for v in native.sent],['response.item.create','response.create'])
                self.assertTrue(json.loads(native.sent[0]['item']['output'])['source_data'])
                for n,kind in enumerate(['response.created','response.completed']):
                    native.events.put({'type':'response.event','event_id':'next'+str(n),'delegation_id':'work',
                        'event':{'type':kind,'response':{'id':'r2'}}})
                    socket.receive_json()
                self.close(socket)
    def test_actual_mounted_lifecycle_keeps_opaque_id_and_source_before_forward(self):
        with self.socket() as socket:
            native=self.start(socket)
            source={'type':'session.input_transcript.delta','event_id':'speech-1','delta':'  Mi corrección',
                    'start_ms':5,'end_ms':40}
            native.events.put(source);self.assertEqual(socket.receive_json()['event'],source)
            page=self.client.get('/api/interaction/voice/gpt-live/visits/'+self.ident+'/events',headers=self.headers).json()
            self.assertEqual(page['items'][-1]['event'],source)
            result=self.close(socket);self.assertEqual(result['finalization']['usage_seconds'],12)
        self.assertEqual(self.read()['state'],'closed');self.assertTrue(native.detached)
        self.assertEqual([v['type']for v in native.sent],['session.close'])
    def test_mounted_stored_reconnect_inherits_one_closed_call_without_resubmission(self):
        config={**self.config,'openai_live':{**self.config['openai_live'],
            'resume_mode':'stored_fork','session_options':{'store':True}}}
        app=FastAPI();app.state.voice_active=set()
        async def authorize(request):return {'human':100,'csrf':'fresh'}
        install(app,config,self.owner,authorize,['https://example.test'])
        with TestClient(app,base_url='https://example.test') as client:
            for n in range(2):
                with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as socket:
                    ident=str(uuid.uuid4());socket.send_json({**self.meta,'id':ident})
                    admission=socket.receive_json();self.assertEqual(admission['type'],'prepared')
                    self.assertEqual(admission['admission']['continued'],n==1)
                    socket.send_json({'type':'offer','sdp':'v=0 offer'})
                    answer=socket.receive_json();self.assertEqual(answer['type'],'answer')
                    self.assertEqual(answer['session'],'live_opaque:provider/42') if n==0 else self.assertTrue(answer['session'].startswith('live_opaque:provider/fork-'))
                    self.assertEqual(socket.receive_json()['event']['type'],'session.started')
                    socket.send_json({'type':'close'});self.assertEqual(socket.receive_json()['type'],'finishing')
                    self.assertEqual(socket.receive_json()['type'],'closed')
        self.assertEqual(sum(v.creations for v in Client.instances),1)
        self.assertEqual([fork for v in Client.instances for fork in v.forks],[('live_opaque:provider/42','v=0 offer')])
        self.assertEqual(app.state.voice_active,set())
        invalid=FastAPI();invalid.state.voice_active=set()
        with self.assertRaises(ValueError):install(invalid,{**config,'openai_live':{**config['openai_live'],'session_options':{'store':False}}},self.owner,authorize,['https://example.test'])
    def test_history_listing_is_authenticated_read_only_and_uses_current_binding(self):
        path='/api/interaction/voice/gpt-live/visits'
        with self.socket() as socket:
            native=self.start(socket)
            page=self.client.get(path,headers=self.headers)
            self.assertEqual(page.status_code,200,page.text)
            self.assertEqual(page.json()['visits'][0]['id'],self.ident)
            self.assertEqual(set(page.json()['visits'][0]),{'id','created_at','state'})
            self.assertFalse(page.json()['more']);self.assertEqual(native.creations,1)
            self.assertEqual(native.sent,[])
            self.owner.binding='b'*64
            self.assertEqual(self.client.get(path,headers=self.headers).status_code,409)
            self.assertEqual(self.client.get(path,headers={**self.headers,'x-voice-binding':'b'*64}).json()['visits'],[])
            self.owner.binding='a'*64
            self.close(socket)
        self.allowed=False;self.assertEqual(self.client.get(path,headers=self.headers).status_code,401)
    def test_known_pending_responses_drain_before_close_without_work_replay(self):
        with self.socket() as socket:
            native=self.start(socket)
            native.events.put({'type':'session.delegation.created','event_id':'work','delegation':{
                'id':'delegation-1','target':'responses','response_id':'response-1'}})
            self.assertEqual(socket.receive_json()['event']['event_id'],'work')
            socket.send_json({'type':'close'});self.assertEqual(socket.receive_json()['type'],'finishing')
            self.assertEqual(native.sent,[])
            native.events.put({'type':'response.event','event_id':'result','delegation_id':'delegation-1',
                'event':{'type':'response.completed','response':{'id':'response-1','output':[]}}})
            self.assertEqual(socket.receive_json()['event']['event_id'],'result')
            self.assertEqual(socket.receive_json()['type'],'closed')
        self.assertEqual(self.read()['delegations']['delegation-1']['state'],'response.completed')
    def test_auth_binding_origin_and_monitor_refuse_before_creation(self):
        for field,value in (('csrf','wrong'),('binding','b'*64)):
            with self.socket() as socket:
                socket.send_json({**self.meta,field:value});self.assertEqual(socket.receive_json()['type'],'unconfirmed')
        self.scope='monitor_readonly'
        with self.socket() as socket:
            socket.send_json(self.meta);self.assertEqual(socket.receive_json()['type'],'unconfirmed')
        self.assertEqual(Client.instances,[])
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://wrong.test'}):pass
    def test_existing_other_voice_lease_prevents_public_creation(self):
        self.app.state.voice_active.add(100)
        with self.socket() as socket:
            socket.send_json(self.meta);self.assertEqual(socket.receive_json()['type'],'unconfirmed')
        self.assertEqual(Client.instances,[])
    def test_disconnect_and_lost_post_remain_uncertain_without_close_or_new_uuid(self):
        Client.failure='creation_unconfirmed'
        with self.socket() as socket:
            socket.send_json(self.meta);self.assertEqual(socket.receive_json()['type'],'prepared')
            socket.send_json({'type':'offer','sdp':'v=0 offer'});self.assertEqual(socket.receive_json()['type'],'unconfirmed')
        self.assertEqual(self.read()['state'],'creation_unconfirmed')
        with self.socket() as socket:
            socket.send_json({**self.meta,'id':str(uuid.uuid4())});self.assertEqual(socket.receive_json()['type'],'unconfirmed')
        self.assertEqual(sum(v.creations for v in Client.instances),1)
        self.assertFalse(any(v.sent for v in Client.instances))
    def test_permission_abort_is_unbilled_and_original_retry_recovers_while_held(self):
        with self.socket() as socket:
            socket.send_json(self.meta);self.assertEqual(socket.receive_json()['type'],'prepared')
        self.assertEqual(self.read()['state'],'not_created')
        self.owner.held=True
        audio=wav_bytes(b'\0\0'*800)
        path='/api/interaction/voice/gpt-live/visits/'+self.ident+'/recordings/0'
        first=self.client.post(path,headers=self.headers,content=audio)
        self.assertEqual(first.status_code,200,first.text)
        same=self.client.post(path,headers=self.headers,content=audio);self.assertEqual(first.json(),same.json())
        changed=self.client.post(path,headers=self.headers,content=wav_bytes(b'\1\0'*800))
        self.assertEqual(changed.status_code,409)
        self.assertEqual(Client.instances[0].creations,0)
        self.assertEqual(self.client.post(path,headers={**self.headers,'x-dashboard-csrf':'stale'},content=audio).status_code,403)
    def test_mid_visit_revocation_releases_media_lease_but_never_cancels_backend(self):
        with self.socket() as socket:
            native=self.start(socket);self.allowed=False
            self.assertEqual(socket.receive_json()['type'],'unconfirmed')
        self.assertEqual(native.sent,[]);self.assertEqual(self.read()['state'],'created')
        self.assertTrue(self.read()['admission']['ended'])
        self.assertEqual(self.app.state.voice_active,set())

    def test_real_app_companion_streaming_upload_and_revocation(self):
        from dashboard.app import create_app
        from dashboard.companion import Grants
        config={**self.config,'origin':'https://example.test','bot_id':123,
            'companion':{'enabled':True,'grants_dir':str(self.root/'grants')}}
        grants=Grants(config,self.owner);output=self.root/'device.json'
        enrolled=grants.enroll('Synthetic public voice device',output,3600)
        device=json.loads(output.read_text())
        headers={**self.headers,'authorization':device['authorization'],'x-dashboard-csrf':device['csrf']}
        with TestClient(create_app(config,self.owner),base_url=config['origin']) as client:
            with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':config['origin']}) as socket:
                socket.send_json({**self.meta,'csrf':device['csrf'],'authorization':device['authorization']})
                self.assertEqual(socket.receive_json()['type'],'prepared')
                # Exceeds general JSON middleware's16KiB, while remaining inside
                # the freshly authorized capture-only streaming route's bound.
                audio=wav_bytes(b'\0\0'*32000)
                path='/api/interaction/voice/gpt-live/visits/'+self.ident+'/recordings/0'
                result=client.post(path,headers=headers,content=audio)
                self.assertEqual(result.status_code,200,result.text)
                self.assertEqual(result.json()['recording']['audio_bytes'],len(audio))
                socket.send_json({'type':'offer','sdp':'v=0 offer'})
                self.assertEqual(socket.receive_json()['type'],'answer')
                self.assertEqual(socket.receive_json()['type'],'provider_event')
                grants.revoke(enrolled['grant_id'])
                self.assertEqual(socket.receive_json()['type'],'unconfirmed')
            self.assertEqual(client.get('/api/interaction/voice/gpt-live/visits/'+self.ident,headers=headers).status_code,401)
            self.assertEqual(client.app.state.voice_active,set())
        self.assertEqual(Client.instances[-1].sent,[])


class Journal(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.root.chmod(0o700)
        self.history=LiveCreations(self.root);self.owner=Owner(self.root)
        self.frozen=self.owner.public_live_binding('a'*64);self.ident=str(uuid.uuid4())
        self.history.prepare(self.ident,100,self.frozen,300)
        self.spec=session_spec('CompAII',backend_model='backend',backend_instructions='Be brief')
        self.client=Client('test');self.history.create(self.ident,100,self.frozen,'v=0 offer',self.spec,self.client)
    def test_full_record_count_keeps_existing_sources_and_finalization_writable(self):
        self.history.max_records=1
        event={'type':'session.delegation.created','event_id':'work','delegation':{'id':'task','target':'responses'}}
        self.history.event(self.ident,100,self.frozen,event)
        self.history.end_capture(self.ident,100,'a'*64)
        self.assertIsNone(self.history.close_intent(self.ident,100,self.frozen))
        self.history.observe_closed(self.ident,100,self.frozen,{'type':'session.closed','event_id':'closed',
            'reason':'expired','session':{'id':'live_opaque:provider/42'}})
        self.assertEqual(self.history.read(self.ident,100,self.frozen)['state'],'closed')
        with self.assertRaises(LiveUnavailable):self.history.prepare(str(uuid.uuid4()),100,self.frozen,300)
        self.assertEqual(len(self.history.source_page(self.ident,100,'a'*64)['items']),1)
    def test_history_cursor_pages_exact_owner_visits_without_exposing_other_owners(self):
        self.history.observe_closed(self.ident,100,self.frozen,{'type':'session.closed','event_id':'closed',
            'reason':'expired','session':{'id':'live_opaque:provider/42'}})
        first=self.history.read(self.ident,100,self.frozen);first['created_at']=1;self.history._write(first)
        second=str(uuid.uuid4());self.history.prepare(second,100,self.frozen,300)
        self.history.create(second,100,self.frozen,'v=0 second',self.spec,Client('test'))
        page=self.history.visits(100,'a'*64);self.assertEqual(page['visits'][0]['id'],second)
        self.assertTrue(page['more']);self.assertEqual(page['before'],second)
        older=self.history.visits(100,'a'*64,before=second)
        self.assertEqual(older['visits'][0]['id'],self.ident);self.assertFalse(older['more'])
        self.assertEqual(self.history.visits(101,'a'*64)['visits'],[])
        with self.assertRaises(ValueError):self.history.visits(101,'a'*64,before=second)
        with self.assertRaises(ValueError):self.history.visits(100,'b'*64,before=second)
    def test_stored_continuation_keeps_flat_references_and_exact_call_outcomes(self):
        # Start an isolated explicit-storage chain, not the legacy nonstored visit.
        history=LiveCreations(self.root/'stored')
        spec={**self.spec,'store':True};parent=None;provider_ids=set()
        for n in range(3):
            ident=str(uuid.uuid4());client=Client('test')
            admission=history.prepare(ident,100,self.frozen,300,resume_spec=spec)
            self.assertEqual(admission['continued'],parent is not None)
            call=history.create(ident,100,self.frozen,'v=0 offer',spec,client)
            self.assertNotIn(call.session_id,provider_ids);provider_ids.add(call.session_id)
            record=history.read(ident,100,self.frozen)
            self.assertEqual(record.get('continuation_from'),parent)
            self.assertEqual(history.create(ident,100,self.frozen,'v=0 offer',spec,Client('test')),call)
            self.assertEqual(client.creations,1 if parent is None else 0)
            self.assertEqual(len(client.forks),0 if parent is None else 1)
            self.assertNotIn('input',record);self.assertNotIn('instructions',record)
            # Wall-clock order is not the continuation chain's authority.
            record['created_at']=10-n;history._write(record)
            history.observe_closed(ident,100,self.frozen,{'type':'session.closed','event_id':'closed-'+str(n),
                'reason':'close_requested','session':{'id':call.session_id},'usage':{'seconds':1}})
            parent=ident
        with self.assertRaises(LiveUnavailable):history.prepare(str(uuid.uuid4()),100,self.frozen,300,resume_spec={**spec,'instructions':'changed'})
    def test_lost_fork_and_restart_never_create_fresh_fallback_or_repeat_fork(self):
        history=LiveCreations(self.root/'lost-fork');spec={**self.spec,'store':True}
        parent=str(uuid.uuid4());history.prepare(parent,100,self.frozen,300,resume_spec=spec)
        call=history.create(parent,100,self.frozen,'v=0 parent',spec,Client('test'))
        history.observe_closed(parent,100,self.frozen,{'type':'session.closed','event_id':'closed-parent',
            'reason':'close_requested','session':{'id':call.session_id}})
        child=str(uuid.uuid4());history.prepare(child,100,self.frozen,300,resume_spec=spec)
        failed=Client('test');failed.failure='creation_unconfirmed'
        with self.assertRaises(LiveUnavailable):history.create(child,100,self.frozen,'v=0 child',spec,failed)
        self.assertEqual(failed.creations,0);self.assertEqual(failed.forks,[(call.session_id,'v=0 child')])
        restarted=LiveCreations(history.root);unused=Client('test')
        with self.assertRaises(LiveUnavailable):restarted.create(child,100,self.frozen,'v=0 child',spec,unused)
        with self.assertRaises(LiveUnavailable):restarted.prepare(str(uuid.uuid4()),100,self.frozen,300,resume_spec=spec)
        self.assertEqual(unused.creations,0);self.assertEqual(unused.forks,[])
        self.assertEqual(restarted.read(child,100,self.frozen)['state'],'creation_unconfirmed')
    def test_known_child_retry_reads_its_receipt_even_if_closed_parent_is_unavailable(self):
        history=LiveCreations(self.root/'known-child');spec={**self.spec,'store':True}
        parent=str(uuid.uuid4());history.prepare(parent,100,self.frozen,300,resume_spec=spec)
        source=history.create(parent,100,self.frozen,'v=0 parent',spec,Client('test'))
        history.observe_closed(parent,100,self.frozen,{'type':'session.closed','event_id':'closed-parent',
            'reason':'close_requested','session':{'id':source.session_id}})
        child=str(uuid.uuid4());history.prepare(child,100,self.frozen,300,resume_spec=spec)
        result=history.create(child,100,self.frozen,'v=0 child',spec,Client('test'))
        history._path(parent).unlink() # Synthetic retirement; not a live-store cleanup.
        unused=Client('test')
        self.assertEqual(LiveCreations(history.root).create(child,100,self.frozen,'v=0 child',spec,unused),result)
        self.assertEqual(unused.creations,0);self.assertEqual(unused.forks,[])
    def test_published_fresh_receipt_digest_remains_readable_without_new_fields(self):
        import hashlib
        request={'session':self.spec,'transport':{'type':'webrtc','sdp':'v=0 offer'}}
        old=self.history.read(self.ident,100,self.frozen)
        old.pop('configuration_sha256');old.pop('store_requested')
        old['request_sha256']=hashlib.sha256(json.dumps(request,sort_keys=True,allow_nan=False,
            ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        self.history._write(old);unused=Client('test')
        self.assertEqual(LiveCreations(self.root).create(self.ident,100,self.frozen,'v=0 offer',self.spec,unused).session_id,'live_opaque:provider/42')
        self.assertEqual(unused.creations,0);self.assertEqual(unused.forks,[])
    def test_stored_continuation_refuses_nonstored_or_unsettled_backend(self):
        with self.assertRaises(ValueError):self.history.prepare(str(uuid.uuid4()),100,self.frozen,300,resume_spec=self.spec)
        self.history.observe_closed(self.ident,100,self.frozen,{'type':'session.closed','event_id':'closed',
            'reason':'expired','session':{'id':'live_opaque:provider/42'}})
        with self.assertRaises(LiveUnavailable):self.history.prepare(str(uuid.uuid4()),100,self.frozen,300,resume_spec={**self.spec,'store':True})
        value=self.history.read(self.ident,100,self.frozen)
        value.update(store_requested=True,configuration_sha256=self.history._configuration({**self.spec,'store':True}),
            delegations={'work':{'state':'pending'}});self.history._write(value)
        with self.assertRaises(LiveUnavailable):self.history.prepare(str(uuid.uuid4()),100,self.frozen,300,resume_spec={**self.spec,'store':True})
        self.assertEqual(len(self.history._records()[0]),1,'Refusals occur before microphone admission or provider creation')
    def test_prepared_capture_is_not_restarted_by_a_new_process(self):
        other=LiveCreations(self.root)
        with self.assertRaises(ValueError):other.prepare(self.ident,100,self.frozen,300)
        self.assertEqual(self.client.creations,1)
    def test_ordered_deltas_dedupe_and_failed_projection_commit_recover(self):
        event={'type':'session.delegation.created','event_id':'work','delegation':{'id':'task','target':'responses'}}
        with patch.object(self.history,'_write',side_effect=OSError('synthetic receipt failure')):
            with self.assertRaises(OSError):self.history.event(self.ident,100,self.frozen,event)
        other=LiveCreations(self.root)
        self.assertFalse(other.event(self.ident,100,self.frozen,event))
        self.assertIn('task',other.read(self.ident,100,self.frozen)['delegations'])
        self.assertFalse(other.event(self.ident,100,self.frozen,event))
        with self.assertRaises(ValueError):other.event(self.ident,100,self.frozen,{**event,'delegation':{'id':'changed'}})
        page=other.source_page(self.ident,100,'a'*64)
        self.assertEqual(len(page['items']),1)
        with self.assertRaises(ValueError):other.source_page(self.ident,100,'a'*64,after=1,revision=page['revision'])
    def test_original_orphans_count_toward_the_same_capture_limit(self):
        record=self.history.read(self.ident,100,self.frozen);record['max_input_pcm_bytes']=300
        self.history._write(record);audio=wav_bytes(b'\0\0'*100)
        with patch.object(self.history,'_write',side_effect=OSError('synthetic receipt failure')):
            with self.assertRaises(OSError):self.history.recording(self.ident,100,'a'*64,0,audio,self.owner)
        with self.assertRaises(ValueError):self.history.recording(self.ident,100,'a'*64,1,audio,self.owner)
        self.assertEqual(len([p for p in Path(str(self.owner.receiver['db_path'])+'.voice').glob('*') if p.name!='admission.lock']),1)
    def test_waiting_function_result_prevents_close_even_after_response_completed(self):
        for event in (
            {'type':'session.delegation.created','event_id':'work','delegation':{'id':'task','target':'responses'}},
            {'type':'response.event','event_id':'function','delegation_id':'task','event':{'type':'response.output_item.done','item':{'type':'function_call','call_id':'call'}}},
            {'type':'response.event','event_id':'completion','delegation_id':'task','event':{'type':'response.completed','response':{'output':[]}}}):
            self.history.event(self.ident,100,self.frozen,event)
        self.assertIsNone(self.history.close_intent(self.ident,100,self.frozen))
    def test_companion_routes_are_exact_and_do_not_grant_native_or_monitor_access(self):
        root='/api/interaction/voice/gpt-live';ident=self.ident
        for method,path in (('GET',root+'/visits'),('POST',root),('POST',root+'/visits/'+ident+'/recordings/0'),('GET',root+'/visits/'+ident+'/events')):
            self.assertTrue(permitted(method,path));self.assertFalse(permitted(method,path,scope='monitor_readonly'))
        self.assertFalse(permitted('POST',root+'/visits/'+ident+'/tools'))
        self.assertFalse(permitted('POST',root+'/visits/'+ident+'/recordings/32'))
    def test_public_binding_does_not_require_native_codex_voice_entitlement(self):
        owner=Provider.__new__(Provider);owner.human=100
        owner.presentation=lambda _:{'binding':'a'*64,'native_codex_voice':None,
            'entry_binding':self.frozen['entry_binding']}
        self.assertEqual(owner.public_live_binding('a'*64),self.frozen)
        with self.assertRaises(ProviderUnavailable):owner.codex_voice_binding('a'*64)


if __name__=='__main__':unittest.main()
