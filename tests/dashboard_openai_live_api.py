"""Mounted public Live auth, source/creation loss and original recovery; zero models."""
import asyncio
import copy
from contextlib import contextmanager
import sqlite3
import hashlib
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
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
from dashboard.native_history import NativeHistory
sys.path.insert(0,str(Path(__file__).resolve().parent))
import dashboard_native_context as context_fixtures

NATIVE_CAPS={"foreground_interpretation":"gpt-transcribe/v1","foreground_live_window":"journal-input/v1","voice_available":True,"foreground_completed_reader":True,
    "foreground_context":"v1","foreground_resume":"v1","foreground_public_live_transcripts":"v1"}


class Owner:
    human=100
    binding_bytes=b'public-live-synthetic-receiver'
    retain_voice_capture=staticmethod(Provider.retain_voice_capture)
    def __init__(self,root):
        self.receiver={'db_path':str(root/'receiver.sqlite')}
        self.journal=context_fixtures.Journal()
        self.media_retention=None;self.binding='a'*64;self.held=False
    def conversation_live_context(self,body):return self.journal.conversation_live_context(body)
    def public_live_integrator_context(self,frozen,max_bytes):
        return {'kind':'current_integrator_conversation','thread':frozen['native_thread'],
            'messages':[],'earlier_history_available':False}
    def presentation(self,command):return {'binding':self.binding}
    def presentation_list(self,*args):return {'binding':self.binding,'items':[]}
    def authorized(self,human):return human==100
    def assert_binding(self):pass
    def close(self):pass
    def conversation_foreground_delegate(self,body):
        raise AssertionError('This fixture did not select a delegation writer')
    def conversation_foreground_interpret(self,body):
        raise AssertionError('This fixture did not select an interpretation writer')
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
        self.allowed=True;self.scope=None;self.app=self.app_with_history()
        async def authorize(request):
            if not self.allowed:raise HTTPException(401,'Expired synthetic access')
            return {'human':100,'csrf':'fresh','scope':self.scope}
        self.assertTrue(install(self.app,self.config,self.owner,authorize,['https://example.test']))
        self.client=TestClient(self.app,base_url='https://example.test');self.addCleanup(self.client.close)
        self.replacement=patch('dashboard.openai_live_api.OpenAILive',Client);self.replacement.start();self.addCleanup(self.replacement.stop)
        Client.instances=[];Client.failure=None
        self.ident=str(uuid.uuid4());self.meta={'id':self.ident,'binding':'a'*64,'csrf':'fresh'}
        self.headers={'origin':'https://example.test','x-dashboard-csrf':'fresh','x-voice-binding':'a'*64}
    @contextmanager
    def database(self):
        db=sqlite3.connect(self.root/'native-context.sqlite',timeout=3);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()
    def app_with_history(self):
        app=FastAPI();app.state.voice_active=set()
        app.state.native_history=NativeHistory(self.database,'mounted-public-context')
        return app
    def prepared(self,socket):
        value=socket.receive_json()
        while value['type']=='context_preparing':value=socket.receive_json()
        self.assertEqual(value['type'],'prepared')
        self.assertEqual(value['admission']['source_close_reasons'],sorted(LiveCreations.source_close_reasons))
        return value
    def socket(self):return self.client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'})
    def read(self):return json.loads((self.state/'public-live-visits'/(self.ident+'.json')).read_text())
    def start(self,socket):
        socket.send_json(self.meta);ready=self.prepared(socket)
        self.assertEqual(Client.instances[-1].creations,0,'Admission precedes billable creation')
        socket.send_json({'type':'offer','sdp':'v=0 offer'})
        answer=socket.receive_json();self.assertEqual(answer['type'],'answer');self.assertEqual(answer['session'],'live_opaque:provider/42')
        self.assertEqual(socket.receive_json()['event']['type'],'session.started')
        return Client.instances[-1]
    def close(self,socket):
        socket.send_json({'type':'close'});self.assertEqual(socket.receive_json()['type'],'finishing')
        result=socket.receive_json();self.assertEqual(result['type'],'closed');return result

    def renewal_app(self):
        app=self.app_with_history()
        self.owner.presentation=lambda command:{'binding':self.owner.binding,**NATIVE_CAPS}
        async def authorize(request):return {'human':100,'csrf':'fresh'}
        config={**self.config,'openai_live':{**self.config['openai_live'],
            'backend_mode':'native','continuous_renewal':True}}
        install(app,config,self.owner,authorize,['https://example.test'])
        return app

    def test_native_avatar_default_is_admitted_by_actual_config_without_a_provider_session(self):
        app=self.app_with_history()
        async def authorize(request):return {'human':100,'csrf':'fresh'}
        config={**self.config,'openai_live':{**self.config['openai_live'],
            'backend_mode':'native','default_native':True}}
        self.assertTrue(install(app,config,self.owner,authorize,['https://example.test']))
        self.assertEqual(Client.instances,[])
        self.assertEqual(list((self.state/'public-live-visits').glob('*.json')),[])

    def test_renewal_ready_follows_native_close_and_releases_owner_before_successor(self):
        app=self.renewal_app()
        with TestClient(app,base_url='https://example.test') as client:
            with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as socket:
                native=self.start(socket)
                socket.send_json({'type':'close','reason':'transport_renewal'})
                self.assertEqual(socket.receive_json()['type'],'finishing')
                final=socket.receive_json();self.assertEqual(final['type'],'closed')
                self.assertTrue(final['renewal_pending'])
                ready=socket.receive_json();self.assertEqual(ready['type'],'successor_ready')
                self.assertTrue(native.detached)
                self.assertEqual(app.state.voice_active,set())
                prior=self.ident
                self.ident=str(uuid.uuid4())
                self.meta={**self.meta,'id':self.ident,'voice_continuation':prior,'renewal':ready['renewal']}
            with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as successor:
                self.start(successor);self.close(successor)
        old=json.loads((self.state/'public-live-visits'/(prior+'.json')).read_text())
        new=self.read()
        self.assertEqual(old['renewal_target'],self.ident)
        self.assertEqual(new['renewal_from'],prior)
        self.assertEqual(new['native_continuation_from'],prior)
        self.assertEqual(len(Client.instances),2)

    def test_confirmed_provider_expiry_uses_same_native_barriers_without_reclosing_provider(self):
        app=self.renewal_app()
        with TestClient(app,base_url='https://example.test') as client:
            with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as socket:
                native=self.start(socket)
                native.events.put({'type':'session.closed','event_id':'expiry',
                    'reason':'expired','usage':{'seconds':15},'session':{'id':'live_opaque:provider/42'}})
                final=socket.receive_json();self.assertEqual(final['type'],'closed')
                self.assertTrue(final['renewal_pending'])
                ready=socket.receive_json();self.assertEqual(ready['type'],'successor_ready')
                self.assertTrue(native.detached)
                self.assertEqual(app.state.voice_active,set())
                self.assertFalse(any(event['type']=='session.close' for event in native.sent))
                prior=self.ident;self.ident=str(uuid.uuid4())
                self.meta={**self.meta,'id':self.ident,'voice_continuation':prior,'renewal':ready['renewal']}
            with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as successor:
                self.start(successor);self.close(successor)
        self.assertEqual(len(Client.instances),2)
        self.assertEqual(self.read()['renewal_from'],prior)

    def test_unsettled_native_context_never_publishes_successor_ready(self):
        app=self.renewal_app()
        async def failed_close(*args,**kwargs):raise ProviderUnavailable('Synthetic context remains uncertain')
        with patch('dashboard.openai_live_api.PublicLiveSessionContext.close',failed_close):
            with TestClient(app,base_url='https://example.test') as client:
                with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as socket:
                    self.start(socket)
                    socket.send_json({'type':'close','reason':'transport_renewal'})
                    self.assertEqual(socket.receive_json()['type'],'finishing')
                    self.assertEqual(socket.receive_json()['type'],'closed')
                    with self.assertRaises(WebSocketDisconnect):socket.receive_json()
        self.assertNotIn('renewal_ready',self.read())
        self.assertEqual(len(Client.instances),1)

    def test_failed_optional_result_reader_keeps_live_speech_until_explicit_stop(self):
        app=self.app_with_history()
        self.owner.presentation=lambda command:{'binding':self.owner.binding,**NATIVE_CAPS}
        async def authorize(request):return {'human':100,'csrf':'fresh'}
        config={**self.config,'openai_live':{**self.config['openai_live'],'backend_mode':'native'}}
        install(app,config,self.owner,authorize,['https://example.test'])
        calls=[]
        def unavailable(*args,**kwargs):
            calls.append(1)
            raise ProviderUnavailable('Synthetic historical result read unavailable')
        with patch('dashboard.openai_live_api.return_next_native_part',unavailable):
            with TestClient(app,base_url='https://example.test') as client:
                with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as socket:
                    native=self.start(socket)
                    notice=socket.receive_json()
                    self.assertEqual(notice,{'type':'notice','code':'native_results_unavailable'})
                    for index in range(3):
                        event={'type':'session.output_transcript.delta','event_id':'continuing-'+str(index),'delta':'Still speaking.'}
                        native.events.put(event)
                        self.assertEqual(socket.receive_json(),{'type':'provider_event','event':event})
                    self.assertFalse(native.detached)
                    self.assertEqual(native.sent,[],'An optional read must not close the paid voice session')
                    self.assertEqual(calls,[1],'An uncertain result failure is not automatically replayed')
                    self.close(socket)
        self.assertEqual([v['type'] for v in native.sent],['session.close'])
        self.assertTrue(self.read()['finalization']['voice_usage_confirmed'])

    def test_optional_close_diagnostic_write_failure_cannot_block_stop(self):
        with patch.object(LiveCreations,'record_close_reason',side_effect=OSError('Synthetic diagnostic write failure')):
            with self.socket() as socket:
                native=self.start(socket)
                socket.send_json({'type':'close','reason':'explicit_stop'})
                self.assertEqual(socket.receive_json()['type'],'finishing')
                self.assertEqual(socket.receive_json()['type'],'closed')
        self.assertEqual([v['type'] for v in native.sent],['session.close'])
        self.assertTrue(self.read()['finalization']['voice_usage_confirmed'])

    def test_client_close_reason_is_bounded_and_preserves_explicit_stop(self):
        with self.socket() as socket:
            native=self.start(socket)
            socket.send_json({'type':'close','reason':'source_unconfirmed'})
            self.assertEqual(socket.receive_json()['type'],'finishing')
            self.assertEqual(socket.receive_json()['type'],'closed')
        value=self.read()
        self.assertEqual(value['client_close_reason'],'source_unconfirmed')
        self.assertTrue(value['finalization']['voice_usage_confirmed'])
        self.assertEqual([v['type'] for v in native.sent],['session.close'])
        history=LiveCreations(self.state/'public-live-visits')
        for invalid in ('raw private error',{},None,42):
            with self.assertRaises(ValueError):history.record_close_reason(self.ident,100,self.owner.public_live_binding('a'*64),invalid)
        self.assertEqual(self.read(),value)

    def test_fixed_source_close_observation_preserves_finalization_and_first_receipt(self):
        with self.socket() as socket:
            native=self.start(socket)
            socket.send_json({'type':'close','reason':'source_boundary_timeout'})
            self.assertEqual(socket.receive_json()['type'],'finishing')
            self.assertEqual(socket.receive_json()['type'],'closed')
        value=self.read()
        self.assertEqual(value['client_close_reason'],'source_boundary_timeout')
        self.assertTrue(value['finalization']['voice_usage_confirmed'])
        self.assertEqual([v['type'] for v in native.sent],['session.close'])
        history=LiveCreations(self.state/'public-live-visits')
        history.record_close_reason(self.ident,100,self.owner.public_live_binding('a'*64),'source_owner_changed')
        self.assertEqual(self.read(),value,'A later diagnostic cannot replace the original observation')

    def test_studio_choice_reaches_provider_and_reconnect_keeps_frozen_delivery(self):
        from dashboard.avatar_workshop import AvatarWorkshop
        store=AvatarWorkshop(self.state)
        profile={'provider':'openai','api':'gpt-live','model':'gpt-live-1','voice':'cedar'}
        a=str(uuid.uuid4());b=str(uuid.uuid4())
        store.voice_save(100,a,profile,'Warm.',None,0);store.voice_select(100,a,1,[profile])
        app=self.app_with_history();app.state.avatar_workshop=store
        async def authorize(request):return {'human':100,'csrf':'fresh'}
        config={**self.config,'openai_live':{**self.config['openai_live'],'session_options':{'audio':{'output':{'voice':'cedar'}}}}}
        install(app,config,self.owner,authorize,['https://example.test'])
        with TestClient(app,base_url='https://example.test') as client,patch.object(self,'client',client):
            self.meta['voice_start']='new'
            with self.socket() as socket:
                first=self.start(socket);self.assertTrue(first.spec['instructions'].endswith('Warm.'))
                store.voice_save(100,b,profile,'Neutral.',a,2);store.voice_select(100,b,3,[profile])
                self.assertTrue(first.spec['instructions'].endswith('Warm.'))
                self.close(socket)
            previous=self.ident
            self.ident=str(uuid.uuid4());self.meta={'id':self.ident,'binding':'a'*64,'csrf':'fresh','voice_continuation':previous}
            with self.socket() as socket:
                reconnect=self.start(socket);self.assertTrue(reconnect.spec['instructions'].endswith('Warm.'));self.close(socket)
            self.ident=str(uuid.uuid4());self.meta={'id':self.ident,'binding':'a'*64,'csrf':'fresh','voice_start':'new'}
            with self.socket() as socket:
                fresh=self.start(socket);self.assertTrue(fresh.spec['instructions'].endswith('Neutral.'));self.close(socket)
            self.ident=str(uuid.uuid4());self.meta={'id':self.ident,'binding':'a'*64,'csrf':'fresh'}
            with self.socket() as socket:
                legacy=self.start(socket)
                self.assertFalse(legacy.spec['instructions'].endswith('Neutral.'))
                self.close(socket)

    def test_maintenance_refuses_before_provider_or_original_admission(self):
        from dashboard.voice_admission import VoiceAdmission, VoiceAdmissionMiddleware, maintenance_guard
        admission=VoiceAdmission(self.state)
        self.app.add_middleware(VoiceAdmissionMiddleware,admission=admission)
        with maintenance_guard(self.state):
            with self.socket() as socket:
                socket.send_json(self.meta)
                value=socket.receive_json()
                self.assertEqual(value['type'],'unconfirmed')
                self.assertIn('server update',value['message'])
        self.assertEqual(Client.instances,[])
        self.assertFalse((self.state/'public-live-visits'/(self.ident+'.json')).exists())
        with self.socket() as socket:
            self.start(socket);self.close(socket)

    def test_unenabled_native_choice_is_refused_before_paid_creation(self):
        with self.socket() as socket:
            socket.send_json({**self.meta,'backend':'native'})
            self.assertEqual(socket.receive_json()['type'],'unconfirmed')
        self.assertEqual(Client.instances,[])

    def choice_client(self):
        app=self.app_with_history()
        async def authorize(request):return {'human':100,'csrf':'fresh'}
        config={**self.config,'openai_live':{**self.config['openai_live'],
            'native_backend_enabled':True,'conversation_context':True}}
        install(app,config,self.owner,authorize,['https://example.test'])
        return TestClient(app,base_url='https://example.test')

    def test_disconnected_native_visit_requires_review_then_fresh_authenticated_action_before_mic(self):
        self.owner.presentation=lambda command:{'binding':self.owner.binding,**NATIVE_CAPS}
        history=LiveCreations(self.state/'public-live-visits');owner=self.owner.public_live_binding('a'*64)
        old=str(uuid.uuid4());history.prepare(old,100,owner,backend_mode='native')
        history.create(old,100,owner,'v=0 offer',session_spec('Synthetic owner',client_delegation=True),Client('synthetic'))
        history.end_capture(old,100,owner['binding'])
        with self.choice_client() as client:
            def socket():return client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'})
            self.meta['backend']='native'
            with socket() as ws:
                ws.send_json(self.meta);review=ws.receive_json()
                self.assertEqual(review['type'],'unconfirmed');self.assertIn('Reconnect voice',review['message'])
                self.assertEqual(review['replacement']['id'],old)
            self.assertFalse((history.root/(self.ident+'.json')).exists())
            self.assertEqual(sum(c.creations for c in Client.instances),1)
            self.meta={**self.meta,'id':str(uuid.uuid4()),'replacement':review['replacement']};self.ident=self.meta['id']
            with socket() as ws:
                ws.send_json(self.meta);ready=self.prepared(ws)
                self.assertEqual(sum(c.creations for c in Client.instances),1,'Review never performs a billable POST')
                ws.send_json({'type':'offer','sdp':'v=0 new offer'})
                self.assertEqual(ws.receive_json()['type'],'answer');self.assertEqual(ws.receive_json()['event']['type'],'session.started')
                self.close(ws)
            before=history.read(old,100,owner)
            self.assertEqual(before['state'],'created');self.assertNotIn('finalization',before)
            self.assertEqual(before['replacement_review']['target'],self.ident)
            self.assertEqual(sum(c.creations for c in Client.instances),2)

    def test_explicit_native_choice_does_not_replace_the_existing_responses_mode(self):
        self.owner.presentation=lambda command:{'binding':self.owner.binding,**NATIVE_CAPS}
        with self.choice_client() as client:
            for choice,expected in (('native','client'),(None,'responses')):
                self.ident=str(uuid.uuid4());self.meta={**self.meta,'id':self.ident}
                self.meta.pop('backend',None)
                if choice:self.meta['backend']=choice
                with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as socket:
                    native=self.start(socket)
                    self.assertEqual(native.spec['delegation']['type'],expected)
                    if choice:self.assertNotIn('responses',native.spec['delegation'])
                    self.close(socket)
                self.assertEqual(self.read()['backend_mode'],'native' if choice else 'responses')

    def test_native_choice_still_requires_reader_before_microphone_or_billing(self):
        with self.choice_client() as client:
            with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as socket:
                socket.send_json({**self.meta,'backend':'native'})
                value=socket.receive_json();self.assertEqual(value['type'],'unconfirmed')
                self.assertIn('server update',value['message'])
        self.assertEqual(Client.instances,[])

    def _active_context_flow(self,*,slow=False,fail=False,late=False):
        from dashboard.openai_live_native_session import PublicLiveSessionContext
        app=self.app_with_history();entered=threading.Event();release=threading.Event();self.addCleanup(release.set)
        self.owner.presentation=lambda command:{'binding':self.owner.binding,**NATIVE_CAPS}
        async def authorize(request):return {'human':100,'csrf':'fresh'}
        config={**self.config,'openai_live':{**self.config['openai_live'],'backend_mode':'native'}}
        install(app,config,self.owner,authorize,['https://example.test'])
        original=PublicLiveSessionContext.sync
        async def syncing(context):
            if not context.updates_stopped:
                entered.set()
                if slow:await asyncio.to_thread(release.wait,3)
                if fail:raise RuntimeError('Synthetic context adapter failure')
            return await original(context)
        with patch.object(PublicLiveSessionContext,'sync_interval',0.),patch.object(PublicLiveSessionContext,'sync_bytes',1),patch.object(PublicLiveSessionContext,'sync',syncing),patch('dashboard.openai_live_api.NATIVE_CONTEXT_DRAIN_SECONDS',.02 if late else 50):
            with TestClient(app,base_url='https://example.test') as client:
                with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as socket:
                    native=self.start(socket)
                    native.events.put({'type':'session.input_transcript.delta','event_id':'active-context-input',
                        'delta':'La corrección es viernes.','start_ms':0,'end_ms':100})
                    self.assertEqual(socket.receive_json()['event']['type'],'session.input_transcript.delta')
                    self.assertTrue(entered.wait(1),'No active context synchronization before work/Close')
                    if fail:
                        self.assertEqual(socket.receive_json()['type'],'finishing')
                        self.assertEqual(socket.receive_json()['type'],'closed')
                    elif slow:
                        socket.send_json({'type':'close'})
                        self.assertEqual(socket.receive_json()['type'],'finishing')
                        self.assertFalse(release.is_set())
                        self.assertEqual(socket.receive_json()['type'],'closed')
                        self.assertIn(100,app.state.voice_active,'In-flight context still owns the actor')
                        if late:
                            self.assertEqual(socket.receive()['type'],'websocket.close')
                            with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as another:
                                another.send_json({**self.meta,'id':str(uuid.uuid4())})
                                self.assertEqual(another.receive_json()['type'],'unconfirmed')
                            self.assertEqual(len(Client.instances),1,'Unsettled context must not admit another provider')
                        release.set()
                    else:
                        deadline=time.monotonic()+2
                        while not self.owner.journal.fresh and time.monotonic()<deadline:time.sleep(.01)
                        self.assertTrue(self.owner.journal.fresh,'Trusted context was not retained before Close')
                        self.close(socket)
                deadline=time.monotonic()+2
                while app.state.voice_active and time.monotonic()<deadline:time.sleep(.01)
                self.assertFalse(app.state.voice_active)
        self.assertEqual([v['type'] for v in native.sent],['session.close'])
        self.assertTrue(self.read()['finalization']['voice_usage_confirmed'])
        self.assertEqual(self.read()['delegations'],{})
        self.assertEqual(len(self.owner.journal.fresh),0 if fail else 1)
        if not fail:self.assertIn('viernes',self.owner.journal.fresh[0]['text'])

    def test_active_context_is_retained_before_work_or_close(self):self._active_context_flow()
    def test_slow_active_context_keeps_close_and_provider_finalization_responsive(self):self._active_context_flow(slow=True)
    def test_unsettled_context_retains_actor_after_handler_cleanup_deadline(self):self._active_context_flow(slow=True,late=True)
    def test_active_context_adapter_failure_uses_owned_close_protocol(self):self._active_context_flow(fail=True)

    def test_native_context_contract_is_required_before_project_access_or_creation(self):
        for missing in ('foreground_context','foreground_resume','foreground_public_live_transcripts','method','history'):
            with self.subTest(missing=missing):
                caps={'binding':self.owner.binding,**NATIVE_CAPS};caps.pop(missing,None)
                self.owner.presentation=lambda command:dict(caps)
                app=self.app_with_history()
                if missing=='history':del app.state.native_history
                original=self.owner.conversation_live_context
                if missing=='method':self.owner.conversation_live_context=None
                async def authorize(request):return {'human':100,'csrf':'fresh'}
                config={**self.config,'openai_live':{**self.config['openai_live'],'backend_mode':'native'}}
                try:
                    install(app,config,self.owner,authorize,['https://example.test'])
                    with TestClient(app,base_url='https://example.test') as client:
                        with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as socket:
                            socket.send_json(self.meta)
                            self.assertEqual(socket.receive_json()['type'],'unconfirmed')
                finally:self.owner.conversation_live_context=original
                self.assertEqual(Client.instances,[])
                self.assertFalse((self.state/'public-live-visits'/(self.ident+'.json')).exists())

    def test_native_choice_has_its_own_frozen_capability_brief(self):
        brief=self.root/'native-identity';brief.write_text('Native session owns identity, memory and work.');brief.chmod(0o600)
        app=self.app_with_history()
        async def authorize(request):return {'human':100,'csrf':'fresh'}
        config={**self.config,'openai_live':{**self.config['openai_live'],
            'native_backend_enabled':True,'native_identity_file':str(brief)}}
        install(app,config,self.owner,authorize,['https://example.test'])
        self.owner.presentation=lambda command:{'binding':self.owner.binding,**NATIVE_CAPS}
        # A file edit cannot alter a live/prepared process's selected brief.
        brief.write_text('A later profile, not selected by this application.');brief.chmod(0o600)
        with TestClient(app,base_url='https://example.test') as client:
            for native in (False,True):
                self.ident=str(uuid.uuid4());self.meta={**self.meta,'id':self.ident};self.meta.pop('backend',None)
                if native:self.meta['backend']='native'
                with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as socket:
                    call=self.start(socket)
                    self.assertEqual(call.spec['instructions'],'Native session owns identity, memory and work.' if native else 'You are CompAII. Be brief.')
                    self.assertEqual(call.spec['delegation']['type'],'client' if native else 'responses')
                    self.close(socket)

    def test_explicit_native_brief_failure_never_falls_back_to_managed_instructions(self):
        from scripts.speech_render import RenderError
        async def authorize(request):return {'human':100,'csrf':'fresh'}
        for path in ('relative-native-brief',str(self.root/'missing-native-brief')):
            app=self.app_with_history()
            config={**self.config,'openai_live':{**self.config['openai_live'],
                'native_backend_enabled':True,'native_identity_file':path}}
            with self.assertRaises((ValueError,RenderError,OSError)):
                install(app,config,self.owner,authorize,['https://example.test'])
        self.assertEqual(Client.instances,[])
    def test_optional_source_seals_use_trusted_delegations_and_confirmed_uploads_only(self):
        app=self.app_with_history()
        async def authorize(request):return {'human':100,'csrf':'fresh'}
        config={**self.config,'openai_live':{**self.config['openai_live'],'source_seals':True}}
        install(app,config,self.owner,authorize,['https://example.test'])
        with TestClient(app,base_url='https://example.test') as client:
            with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as socket:
                native=self.start(socket)
                self.assertEqual(native.spec['delegation']['type'],'responses','Source control does not switch backend mode')
                audio=wav_bytes(b'\1\0'*800)
                path='/api/interaction/voice/gpt-live/visits/'+self.ident+'/recordings/0'
                self.assertEqual(client.post(path,headers=self.headers,content=audio).status_code,200)
                def delegate(ident):
                    native.events.put({'type':'session.delegation.created','event_id':'source-'+ident,
                        'delegation':{'id':ident,'target':'client'},'offset_ms':50})
                    self.assertEqual(socket.receive_json()['event']['type'],'session.delegation.created')
                delegate('first');request=socket.receive_json()
                self.assertEqual(request['type'],'source_seal_requested')
                delegate('second')
                self.assertNotIn('source_seal',self.read()['delegations']['second'])
                socket.send_json({'type':'source_sealed','request':request['request'],
                    'through_ordinal':1,'capture_bytes':len(audio)-44})
                recorded=socket.receive_json()
                self.assertEqual(recorded['type'],'source_seal_recorded')
                self.assertEqual(recorded['seal']['state'],'sealed');self.assertFalse(recorded['seal']['work_admitted'])
                self.assertEqual(recorded['seal']['recordings'][0]['ordinal'],0)
                second=socket.receive_json();self.assertEqual(second['type'],'source_seal_requested')
                socket.send_json({'type':'source_sealed','request':second['request'],
                    'through_ordinal':1,'capture_bytes':len(audio)-44})
                self.assertEqual(socket.receive_json()['seal']['state'],'empty')
                native.events.put({'type':'session.closed','event_id':'expired','reason':'expired',
                    'session':{'id':native.session_id},'usage':{'seconds':1}})
                self.assertEqual(socket.receive_json()['type'],'closed')
        self.assertNotIn('native_originals',self.read());self.assertEqual(native.sent,[])
        self.assertEqual(self.read()['delegations']['first']['state'],'pending','Capture is not task completion')

    def test_source_seals_cannot_mix_upload_time_native_enrollment(self):
        for flags in ({'source_seals':'yes'},{'source_seals':True,'native_originals':True}):
            app=self.app_with_history()
            config={**self.config,'openai_live':{**self.config['openai_live'],**flags}}
            with self.assertRaises(ValueError):install(app,config,self.owner,lambda _:None,['https://example.test'])
    def test_native_backend_checks_reader_before_microphone_or_paid_creation(self):
        app=self.app_with_history()
        async def authorize(request):return {'human':100,'csrf':'fresh'}
        config={**self.config,'openai_live':{**self.config['openai_live'],'backend_mode':'native'}}
        install(app,config,self.owner,authorize,['https://example.test'])
        with TestClient(app,base_url='https://example.test') as client:
            with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as socket:
                socket.send_json(self.meta);self.assertEqual(socket.receive_json()['type'],'unconfirmed')
        self.assertEqual(Client.instances,[]);self.assertFalse((self.state/'public-live-visits'/(self.ident+'.json')).exists())

    def test_native_choice_refuses_missing_python_adapter_even_with_current_native_capabilities(self):
        self.owner.presentation=lambda command:{'binding':self.owner.binding,**NATIVE_CAPS}
        self.owner.conversation_foreground_delegate=None
        with self.choice_client() as client:
            with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as socket:
                socket.send_json({**self.meta,'backend':'native'})
                value=socket.receive_json();self.assertEqual(value['type'],'unconfirmed')
                self.assertIn('server update',value['message'])
        self.assertEqual(Client.instances,[])
        self.assertFalse((self.state/'public-live-visits'/(self.ident+'.json')).exists())

    def test_native_choice_refuses_unconfigured_raw_voice_before_paid_creation(self):
        self.owner.presentation=lambda command:{'binding':self.owner.binding,**NATIVE_CAPS,'voice_available':False}
        with self.choice_client() as client:
            with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as socket:
                socket.send_json({**self.meta,'backend':'native'})
                self.assertEqual(socket.receive_json()['type'],'unconfirmed')
        self.assertEqual(Client.instances,[])
        self.assertFalse((self.state/'public-live-visits'/(self.ident+'.json')).exists())

    def _native_backend_flow(self,slow_result=False,renew=False):
        app=self.app_with_history();saved={};calls={'asr':0,'work':0}
        entered=threading.Event();release=threading.Event();self.addCleanup(release.set)
        owner=self.owner;frozen=owner.public_live_binding('a'*64)
        def trace(root):
            if slow_result:
                entered.set();self.assertTrue(release.wait(3),'Native result read blocked voice Close')
            return {'id':root,'entry_binding':frozen['entry_binding'],'routes':[]}
        owner.conversation_input_trace=trace
        owner.presentation=lambda command:{'binding':owner.binding,**NATIVE_CAPS}
        def capture(metadata,data,**options):
            saved[metadata['id']]={'id':metadata['id'],'entry_binding':frozen['entry_binding'],
                'foreground_dialogue':options['foreground_dialogue'],'phase':'foreground_captured',
                'voice':{'audio_sha256':metadata['audio_sha256']},'native_acceptance':'not_requested'}
            return copy.deepcopy(saved[metadata['id']])
        def interpret(body):
            row=saved[body['id']];row.update(text=body['text'],phase='foreground')
            row['voice']['transcription']={'actual_transcriber':body['model'],'capture_id':body['id'],
                'audio_sha256':body['audio_sha256'],'audio_millis':body['audio_millis']}
            return copy.deepcopy(row)
        def delegate(body):
            calls['work']+=1;row=saved[body['id']]
            row['text']=self.read()['delegations']['native-task']['live_window']['text']
            self.assertIn('native semantic producer',body['formulation'])
            self.assertIn(self.ident,body['formulation'])
            self.assertIn(self.ident,owner.journal.producers,'Context must be retained before native work')
            row.update(phase='accepted',native_acceptance='observed',local_turn=42,foreground_delegation={
                'intent_id':body['intent_id'],'dialogue_id':self.ident,'formulation':body['formulation'],'live_window':body['live_window']['proof'],
                'sources':[{'id':ident,'capture_order':index+1,'text':saved[ident]['text'],
                    'text_sha256':hashlib.sha256(saved[ident]['text'].encode()).hexdigest(),
                    'voice':copy.deepcopy(saved[ident]['voice'])} for index,ident in enumerate(body['source_ids'])]})
            return copy.deepcopy(row)
        owner.conversation_voice_submit=capture;owner.conversation_foreground_interpret=interpret
        owner.conversation_foreground_delegate=delegate;owner.conversation_input_status=lambda ident:copy.deepcopy(saved[ident])
        owner.presentation_list=lambda delivery,native,direction:{'binding':owner.binding,
            'newest':{'native':77 if calls['work'] else 0},'items':[{'id':'native:77',
                'revision':'d'*64,'kind':'integrator_answer','local_turn':42}] if calls['work'] and native<77 else [],
            'more':False,'cursor':{'delivery':0,'native':77}}
        owner.presentation_part=lambda source,revision,offset:{'id':source,'revision':revision,'offset':offset,
            'next_offset':None,'text':'Soy CompAII. Este resultado viene del integrador nativo.',
            'entry_binding':frozen['entry_binding'][:3]+[owner.binding],
            'kind':'integrator_answer','local_turn':42,'native_binding_current':True}
        class Recognizer:
            model='gpt-transcribe'
            def transcribe(self,data):calls['asr']+=1;return '¿Quién sos y qué recordás?'
        send=Client.send
        def acknowledge(client,event):
            send(client,event)
            if event['type']=='session.commentary.append':
                client.events.put({'type':'session.commentary.appended','event_id':'native-context-ack',
                    'client_event_id':event['event_id']})
        async def authorize(request):return {'human':100,'csrf':'fresh'}
        config={**self.config,'openai_live':{**self.config['openai_live'],'backend_mode':'native'}}
        install(app,config,owner,authorize,['https://example.test'])
        with patch.object(Client,'send',acknowledge):
            with TestClient(app,base_url='https://example.test') as client:
                with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as socket:
                    native=self.start(socket);self.assertEqual(native.spec['delegation']['type'],'client')
                    self.assertNotIn('responses',native.spec['delegation'])
                    native.events.put({'type':'session.input_transcript.delta','event_id':'context-source',
                        'delta':'Correction: Friday, not Thursday.','start_ms':0,'end_ms':50})
                    self.assertEqual(socket.receive_json()['event']['type'],'session.input_transcript.delta')
                    audio=wav_bytes(b'\1\0'*800)
                    self.assertEqual(client.post('/api/interaction/voice/gpt-live/visits/'+self.ident+'/recordings/0',
                        headers=self.headers,content=audio).status_code,200)
                    native.events.put({'type':'session.delegation.created','event_id':'native-request',
                        'delegation':{'id':'native-task','target':'client'}})
                    self.assertEqual(socket.receive_json()['type'],'provider_event')
                    request=socket.receive_json();self.assertEqual(request['type'],'source_seal_requested')
                    socket.send_json({'type':'source_sealed','request':request['request'],
                        'through_ordinal':1,'capture_bytes':len(audio)-44})
                    self.assertEqual(socket.receive_json()['type'],'source_seal_recorded')
                    if slow_result:
                        self.assertTrue(entered.wait(1));socket.send_json({'type':'close'})
                        self.assertEqual(socket.receive_json()['type'],'finishing')
                        self.assertFalse(release.is_set());release.set()
                        self.assertEqual(socket.receive_json()['type'],'closed')
                    else:
                        self.assertEqual(socket.receive_json()['event']['type'],'session.commentary.appended')
                        self.assertIn('Soy CompAII',next(row['content'] for row in native.sent if row['type']=='session.commentary.append'))
                        self.close(socket)
                    self.assertEqual(calls,{'asr':0,'work':1})
                first_value=self.read()
                if renew:
                    original=self.ident;self.ident=str(uuid.uuid4());self.meta={**self.meta,'id':self.ident}
                    source='delivery:11111111-1111-4111-8111-111111111111'
                    owner.conversation_input_trace=lambda root:{'id':root,'entry_binding':frozen['entry_binding'],
                        'routes':[{'target_available':True,'results':[{'source':source,'revision':'c'*64,
                            'instruction_covered':True,'current':True,'correction_pending':False}]}]}
                    owner.presentation_part=lambda selected,revision,offset:{'id':selected,'revision':revision,
                        'offset':offset,'next_offset':None,'text':'Resultado tardío del trabajo original.',
                        'entry_binding':frozen['entry_binding'][:3]+[owner.binding],
                        'kind':'worker_result','current':True,'correction_pending':False,'native_binding_current':True}
                    with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as second:
                        continued=self.start(second)
                        seed=continued.spec['input'][-2]
                        self.assertEqual(seed['role'],'developer')
                        self.assertIn('Friday, not Thursday',seed['content'][0]['text'])
                        self.assertEqual(second.receive_json()['event']['type'],'session.commentary.appended')
                        delivered=next(row for row in continued.sent if row['type']=='session.commentary.append')
                        self.assertIsNone(delivered['delegation_id'])
                        self.assertIn('Resultado tardío',delivered['content'])
                        self.close(second)
                    renewed=self.read()
                    self.assertEqual(renewed['native_continuation_from'],original)
                    self.assertEqual(renewed['delegations'],{},'No new provider delegation or original was needed')
                    self.assertEqual(calls,{'asr':0,'work':1},'Renewal never interprets or dispatches the old work again')
                    self.assertEqual(next(iter(renewed['native_result_updates'].values()))['origin_visit'],original)
        self.assertEqual(first_value['state'],'closed')
        self.assertEqual(first_value['delegations']['native-task']['native_pipeline']['state'],'admitted')
        updates=list(first_value.get('native_result_updates',{}).values())
        self.assertEqual(len(updates),0 if slow_result else 1)
        if not slow_result:
            self.assertEqual(updates[0]['state'],'context_injected');self.assertNotIn('heard',updates[0])
        else:self.assertEqual([row['type'] for row in native.sent],['session.close'])
        self.assertFalse(first_value['delegations']['native-task']['native_pipeline']['work_completed'])

    def test_native_backend_whole_mounted_source_work_and_result_flow(self):
        self._native_backend_flow()

    def test_closed_native_work_returns_to_fresh_voice_without_new_original_or_dispatch(self):
        self._native_backend_flow(renew=True)

    def test_slow_native_result_read_keeps_close_responsive_without_canceling_work(self):
        self._native_backend_flow(slow_result=True)

    def test_native_backend_rejects_unqualified_continuation_or_mixed_context(self):
        for settings in ({'conversation_context':True},{'source_seals':False},
                         {'resume_mode':'stored_fork','session_options':{'store':True}}):
            app=self.app_with_history()
            config={**self.config,'openai_live':{**self.config['openai_live'],'backend_mode':'native',**settings}}
            with self.assertRaises(ValueError):install(app,config,self.owner,lambda _:None,['https://example.test'])

    def test_native_window_failure_finalizes_voice_once_without_work_or_retry(self):
        self._failed_native_preparation(ValueError('Synthetic source window unavailable'),'unconfirmed')

    def test_unexpected_preparation_error_keeps_sideband_until_confirmed_close_without_replay(self):
        with self.assertLogs('dashboard.openai_live_api',level='WARNING') as logs:
            self._failed_native_preparation(AttributeError('sensitive internal provider detail'),'intent')
        self.assertTrue(any('AttributeError' in line for line in logs.output))
        self.assertFalse(any('sensitive internal' in line for line in logs.output))

    def _failed_native_preparation(self,error,interpretation_state):
        app=self.app_with_history();saved={};attempts=[]
        owner=self.owner;frozen=owner.public_live_binding('a'*64)
        owner.presentation=lambda command:{'binding':owner.binding,**NATIVE_CAPS}
        def capture(metadata,data,**options):
            saved[metadata['id']]={'id':metadata['id'],'entry_binding':frozen['entry_binding'],
                'foreground_dialogue':options['foreground_dialogue'],'phase':'foreground_captured',
                'voice':{'audio_sha256':metadata['audio_sha256']},'native_acceptance':'not_requested'}
            return copy.deepcopy(saved[metadata['id']])
        owner.conversation_voice_submit=capture;owner.conversation_input_status=lambda ident:copy.deepcopy(saved[ident])
        class Recognizer:
            model='gpt-transcribe'
            def transcribe(self,data):attempts.append(data);raise error
        def fail_window(*args):attempts.append('source-window');raise error
        async def authorize(request):return {'human':100,'csrf':'fresh'}
        config={**self.config,'openai_live':{**self.config['openai_live'],'backend_mode':'native'}}
        install(app,config,owner,authorize,['https://example.test'])
        with patch('dashboard.openai_live_native_backend.freeze_input_window',fail_window):
            with TestClient(app,base_url='https://example.test') as client:
                with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as socket:
                    native=self.start(socket);audio=wav_bytes(b'\1\0'*800)
                    self.assertEqual(client.post('/api/interaction/voice/gpt-live/visits/'+self.ident+'/recordings/0',
                        headers=self.headers,content=audio).status_code,200)
                    native.events.put({'type':'session.delegation.created','event_id':'failed-native-request',
                        'delegation':{'id':'failed-task','target':'client'}})
                    self.assertEqual(socket.receive_json()['type'],'provider_event');request=socket.receive_json()
                    socket.send_json({'type':'source_sealed','request':request['request'],
                        'through_ordinal':1,'capture_bytes':len(audio)-44})
                    self.assertEqual(socket.receive_json()['type'],'source_seal_recorded')
                    self.assertEqual(socket.receive_json()['type'],'finishing')
                    socket.send_json({'type':'close'})  # Browser hold duplicates the same close intent.
                    final=socket.receive_json();self.assertEqual(final['type'],'closed')
                    self.assertIn('needs review',final['message'])
        self.assertEqual(len(attempts),1);self.assertEqual([v['type'] for v in native.sent],['session.close'])
        value=self.read();self.assertEqual(value['state'],'closed')
        self.assertTrue(value['finalization']['voice_usage_confirmed'])
        self.assertEqual(value['delegations']['failed-task']['native_pipeline']['state'],'held')
        self.assertNotIn('interpretation',value['native_originals']['0'])
        self.assertNotIn('native_work',value['delegations']['failed-task'])

    def test_slow_native_window_read_keeps_close_responsive_without_asr(self):
        app=self.app_with_history();saved={};entered=threading.Event();release=threading.Event()
        self.addCleanup(release.set);owner=self.owner;frozen=owner.public_live_binding('a'*64)
        owner.presentation=lambda command:{'binding':owner.binding,**NATIVE_CAPS}
        def capture(metadata,data,**options):
            saved[metadata['id']]={'id':metadata['id'],'entry_binding':frozen['entry_binding'],
                'foreground_dialogue':options['foreground_dialogue'],'phase':'foreground_captured',
                'voice':{'audio_sha256':metadata['audio_sha256']},'native_acceptance':'not_requested'}
            return copy.deepcopy(saved[metadata['id']])
        owner.conversation_voice_submit=capture;owner.conversation_input_status=lambda ident:copy.deepcopy(saved[ident])
        test=self
        class Recognizer:
            model='gpt-transcribe'
            def transcribe(self,data):
                entered.set();test.assertTrue(release.wait(3),'Preparation blocked voice control instead of running in its owned task')
                return 'Interpretación que termina después del cierre.'
        async def authorize(request):return {'human':100,'csrf':'fresh'}
        config={**self.config,'openai_live':{**self.config['openai_live'],'backend_mode':'native'}}
        install(app,config,owner,authorize,['https://example.test'])
        def slow_window(*args):
            from dashboard.openai_live_window import freeze_input_window
            entered.set();test.assertTrue(release.wait(3),'Source read blocked voice Close')
            return freeze_input_window(*args)
        with patch('dashboard.openai_live_native_backend.freeze_input_window',slow_window):
            with TestClient(app,base_url='https://example.test') as client:
                with client.websocket_connect('/api/interaction/voice/gpt-live',headers={'origin':'https://example.test'}) as socket:
                    native=self.start(socket);audio=wav_bytes(b'\1\0'*800)
                    self.assertEqual(client.post('/api/interaction/voice/gpt-live/visits/'+self.ident+'/recordings/0',
                        headers=self.headers,content=audio).status_code,200)
                    native.events.put({'type':'session.delegation.created','event_id':'slow-native-request',
                        'delegation':{'id':'slow-task','target':'client'}})
                    socket.receive_json();request=socket.receive_json()
                    socket.send_json({'type':'source_sealed','request':request['request'],
                        'through_ordinal':1,'capture_bytes':len(audio)-44})
                    self.assertEqual(socket.receive_json()['type'],'source_seal_recorded')
                    self.assertTrue(entered.wait(1));socket.send_json({'type':'close'})
                    self.assertEqual(socket.receive_json()['type'],'finishing')
                    self.assertFalse(release.is_set());release.set()
                    self.assertEqual(socket.receive_json()['type'],'closed')
        value=self.read()
        self.assertNotIn('interpretation',value['native_originals']['0'])
        self.assertEqual(value['delegations']['slow-task']['native_pipeline']['state'],'held')
        self.assertNotIn('native_work',value['delegations']['slow-task'])
        self.assertEqual([row['type'] for row in native.sent],['session.close'])
    def test_native_original_opt_in_uses_exact_owner_and_never_repeats_lost_ack(self):
        app=self.app_with_history()
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
        app=self.app_with_history()
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
        app=self.app_with_history()
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
            self.close(socket)
            # Read-only history binding checks run after voice closes. Changing
            # the live owner correctly revokes an active socket's admission.
            self.owner.binding='b'*64
            self.assertEqual(self.client.get(path,headers=self.headers).status_code,409)
            self.assertEqual(self.client.get(path,headers={**self.headers,'x-voice-binding':'b'*64}).json()['visits'],[])
            self.owner.binding='a'*64
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

    def test_original_body_outlives_application_clock_without_replay_or_larger_bounds(self):
        import httpx
        with self.socket() as socket:
            socket.send_json(self.meta);self.assertEqual(socket.receive_json()['type'],'prepared')
        audio=wav_bytes(b'\0\0'*800);clock=asyncio.timeout;scheduled=[]
        def expiry(seconds):
            scheduled.append(seconds)
            return clock(.001 if seconds==30 else seconds)
        async def body():
            yield audio[:44]
            await asyncio.sleep(.02)
            yield audio[44:]
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='https://example.test') as client:
                return await client.post('/api/interaction/voice/gpt-live/visits/'+self.ident+'/recordings/0',headers=self.headers,content=body())
        with patch('dashboard.openai_live_api.asyncio.timeout',side_effect=expiry):
            result=asyncio.run(send())
        self.assertEqual(result.status_code,200,result.text)
        self.assertNotIn(30,scheduled,'Transport body reads have no application lifetime cutoff')
        self.assertEqual(result.json()['recording']['audio_bytes'],len(audio))
        self.assertEqual(Client.instances[0].creations,0)
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
    def test_expiry_requires_explicit_server_readiness_complete_usage_and_no_stop_or_source_gap(self):
        value=self.history.read(self.ident,100,self.frozen)
        value['backend_mode']='native';self.history._write(value)
        self.history.end_capture(self.ident,100,self.frozen['binding'])
        self.history.observe_closed(self.ident,100,self.frozen,{'type':'session.closed','event_id':'expired',
            'reason':'expired','session':{'id':'live_opaque:provider/42'},'usage':{'seconds':15}})
        with self.assertRaises(ValueError):self.history.ready_for_renewal(self.ident,100,self.frozen)
        original=self.history.read(self.ident,100,self.frozen)
        for mutation in ('stop','usage','source'):
            value=copy.deepcopy(original)
            if mutation=='stop':value['client_close_reason']='user_hold'
            elif mutation=='usage':value['finalization']['voice_usage_confirmed']=False
            else:value['delegations']['pending']={'target':'client'}
            self.history._write(value)
            with self.assertRaises(ValueError):self.history.ready_for_renewal(self.ident,100,self.frozen,allow_expired=True)
        self.history._write(original)
        ready=self.history.ready_for_renewal(self.ident,100,self.frozen,allow_expired=True)
        child=str(uuid.uuid4())
        self.history.prepare(child,100,self.frozen,backend_mode='native',voice_continuation=self.ident,renewal=ready)
        self.assertEqual(self.history.read(child,100,self.frozen)['renewal_from'],self.ident)

    def renewal_ready(self):
        value=self.history.read(self.ident,100,self.frozen)
        value['backend_mode']='native';self.history._write(value)
        self.history.record_close_reason(self.ident,100,self.frozen,'transport_renewal')
        self.history.end_capture(self.ident,100,self.frozen['binding'])
        self.history.observe_closed(self.ident,100,self.frozen,{'type':'session.closed','event_id':'closed',
            'reason':'close_requested','session':{'id':'live_opaque:provider/42'}})
        return self.history.ready_for_renewal(self.ident,100,self.frozen)

    def test_renewal_claim_survives_partial_write_and_refuses_second_successor(self):
        ready=self.renewal_ready();child=str(uuid.uuid4());write=self.history._write
        def fail_destination(value):
            if value['id']==child:raise OSError('Synthetic destination write failure')
            write(value)
        with patch.object(self.history,'_write',side_effect=fail_destination):
            with self.assertRaises(OSError):self.history.prepare(child,100,self.frozen,backend_mode='native',
                voice_continuation=self.ident,renewal=ready)
        self.assertEqual(self.history.read(self.ident,100,self.frozen)['renewal_target'],child)
        with self.assertRaises(ValueError):self.history.prepare(str(uuid.uuid4()),100,self.frozen,backend_mode='native')
        with self.assertRaises(ValueError):self.history.prepare(str(uuid.uuid4()),100,self.frozen,
            backend_mode='native',voice_continuation=self.ident,renewal=ready)

    def test_renewal_requires_same_service_epoch_owner_token_and_confirmed_reason(self):
        ready=self.renewal_ready()
        for renewal,history in (({**ready,'token':str(uuid.uuid4())},self.history),
                                (ready,LiveCreations(self.root))):
            with self.assertRaises(ValueError):history.prepare(str(uuid.uuid4()),100,self.frozen,
                backend_mode='native',voice_continuation=self.ident,renewal=renewal)
        value=self.history.read(self.ident,100,self.frozen)
        value['finalization']['reason']='content';self.history._write(value)
        with self.assertRaises(ValueError):self.history.prepare(str(uuid.uuid4()),100,self.frozen,
            backend_mode='native',voice_continuation=self.ident,renewal=ready)

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
