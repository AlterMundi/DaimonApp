"""Mounted native voice endpoints with synthetic owner; zero model/media calls."""
from pathlib import Path
import asyncio
import json
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
from dashboard.codex_voice_api import install
from dashboard.codex_voice_history import CodexVoiceHistory
from dashboard.live_transcription import wav_bytes
from dashboard.provider import Provider


class Owner:
    def __init__(self,root):
        self.receiver={'voice':{},'db_path':str(root/'receiver.sqlite')}
        self.receiver['voice']={'configured':True}
        self.native_home=root/'native';self.media_retention=None
        self.binding='a'*64;self.human=100;self.collected=[];self.held=False;self.current=None
    retain_voice_capture=staticmethod(Provider.retain_voice_capture)
    def authorized(self,human):return human==self.human
    def close(self):pass
    def snapshot(self):return {'sessions':[],'stop':{'state':'no_operation'}}
    def presentation_list(self,*args):return {'binding':self.binding,'items':[]}
    def presentation(self,command):return {'binding':self.binding}
    def codex_voice_binding(self,binding):
        if binding!=self.binding or self.held:raise ValueError('Synthetic held/changed owner')
        return {'binding':binding,'entry_binding':[100,{'chat_id':100,'thread_id':7},1,'native'],
                'native_thread':'native'}
    def codex_voice_transcripts(self,owner,sessions):
        from dashboard.codex_voice_history import IncompleteTranscript
        raise IncompleteTranscript('Synthetic canonical closure unavailable')
    def codex_voice_collect(self,owner,turn):
        self.collected.append(turn);return {'state':'collecting'}
    def codex_voice_memory(self,owner,text,checkpoint=None):
        return {'file':[1,1],'offset':1,'found':hasattr(Native.opened[-1],'memory'),'compacted':False}
    def codex_voice_current(self,owner):return self.current


class Native:
    opened=[];emit_turn=False;bad_generation=False;lose_closure=False;open_delay=0;start_delay=0
    opening_seen=threading.Event();starting_seen=threading.Event()
    def __init__(self,home,thread,*,lease):
        self.session_id=str(uuid.uuid4());self.events=queue.Queue();self.started=False
        self.closure_observed=False;self.stops=0;self.closed=False;self.opened.append(self)
        self.opening_seen.set();time.sleep(self.open_delay)
    def start(self,sdp,**kwargs):
        self.starting_seen.set();time.sleep(self.start_delay)
        self.started=True;self.sdp=sdp;self.context=kwargs['context'];self.continuation=kwargs['continuation']
        values=[{'method':'thread/realtime/started','params':{}},
                {'method':'thread/realtime/sdp','params':{'sdp':'v=0\r\nsynthetic-answer'}}]
        values.append({'method':'thread/realtime/item/completed','params':{'item':{
            'id':'source_1','type':'transcriptSegment','role':'user','text':'A native original',
            'realtimeSessionId':str(uuid.uuid4())if self.bad_generation else self.session_id}}})
        if self.emit_turn:values.append({'method':'turn/started','params':{'turn':{'id':'native-work'}}})
        self.events.put(values)
    def remember(self,memory):self.memory=memory
    def receive(self,timeout):
        try:return self.events.get(timeout=timeout)
        except queue.Empty:return []
    def stop(self):self.stops+=1;self.closure_observed=not self.lose_closure
    def close(self):self.closed=True


class Mounted(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.identity=self.root/'identity.txt'
        self.identity.write_text('You are CompAII. Speak briefly and naturally.')
        self.identity.chmod(0o600)
        self.owner=Owner(self.root);self.app=FastAPI();self.app.state.voice_active=set()
        self.allowed=True;self.checks=0;self.csrf='fresh-action'
        async def authorize(request):
            self.checks+=1
            if not self.allowed:raise HTTPException(401,'Synthetic expired access')
            return {'human':100,'csrf':self.csrf}
        self.config={'state_dir':str(self.root/'dashboard'),'codex_voice':{
            'enabled':True,'identity_file':str(self.identity),'session_seconds':300}}
        # Match create_app's private state prerequisite independently of umask.
        Path(self.config['state_dir']).mkdir(mode=0o700)
        install(self.app,self.config,self.owner,authorize,['https://example.test'])
        self.client=TestClient(self.app,base_url='https://example.test')
        self.addCleanup(self.client.close)
        self.patch=patch('dashboard.codex_voice_api.CodexVoice',Native);self.patch.start();self.addCleanup(self.patch.stop)
        Native.opened=[];Native.emit_turn=Native.bad_generation=Native.lose_closure=False
        Native.open_delay=Native.start_delay=0;Native.opening_seen.clear();Native.starting_seen.clear()
        self.visit=str(uuid.uuid4());self.meta={'id':self.visit,'binding':'a'*64,'csrf':self.csrf}
        self.headers={'origin':'https://example.test','x-dashboard-csrf':self.csrf,'x-voice-binding':'a'*64}
    def socket(self):
        return self.client.websocket_connect('/api/interaction/voice/codex',headers={'origin':'https://example.test'})
    def start(self,socket):
        socket.send_json(self.meta);self.assertEqual(socket.receive_json()['type'],'prepared')
        socket.send_json({'type':'offer','sdp':'v=0\r\nsynthetic-offer'})
        self.assertEqual(socket.receive_json()['type'],'answer')
        self.assertEqual(socket.receive_json()['type'],'transcript')
    def close(self,socket):
        socket.send_json({'type':'close'})
        self.assertEqual(socket.receive_json()['type'],'closed')
        with self.assertRaises(WebSocketDisconnect):socket.receive_json()
    def test_history_pages_survive_new_visits_and_refuse_foreign_cursors_without_work(self):
        history=CodexVoiceHistory(self.root/'dashboard'/'codex-voice-visits')
        owner=self.owner.codex_voice_binding('a'*64);ids=[]
        with patch('dashboard.codex_voice_history.time.time',return_value=10):
            for _ in range(23):
                ident=str(uuid.uuid4());ids.append(ident)
                history.open(ident,100,owner,str(uuid.uuid4()))
            foreign=str(uuid.uuid4())
            history.open(foreign,200,owner,str(uuid.uuid4()))
        route='/api/interaction/voice/codex/visits'
        first=self.client.get(route,headers=self.headers);self.assertEqual(first.status_code,200)
        value=first.json();seen=[v['id']for v in value['visits']]
        self.assertEqual(seen,list(reversed(ids[-8:])))
        self.assertTrue(value['more'])
        history.open(str(uuid.uuid4()),100,owner,str(uuid.uuid4()))
        while value['more']:
            response=self.client.get(route,params={'before':value['before']},headers=self.headers)
            self.assertEqual(response.status_code,200);value=response.json()
            self.assertLessEqual(len(value['visits']),8)
            seen.extend(v['id']for v in value['visits'])
        self.assertEqual(seen,list(reversed(ids)))
        self.assertIsNone(value['before'])
        for cursor in (foreign,str(uuid.uuid4()),'not-a-visit'):
            self.assertEqual(self.client.get(route,params={'before':cursor},headers=self.headers).status_code,404)
        self.allowed=False
        self.assertEqual(self.client.get(route,headers=self.headers).status_code,401)
        self.assertEqual(Native.opened,[]);self.assertEqual(self.owner.collected,[])

    def test_failed_final_correction_write_blocks_successor_before_start(self):
        original_stop=Native.stop
        original_item=CodexVoiceHistory.item
        def stop(native):
            native.events.put([{'method':'thread/realtime/item/completed','params':{'item':{
                'id':'final_correction','type':'transcriptSegment','role':'user',
                'text':'The corrected value','realtimeSessionId':native.session_id}}}])
            original_stop(native)
        def item(history,ident,human,binding,value):
            if value['id']=='final_correction':raise OSError('Synthetic full store')
            return original_item(history,ident,human,binding,value)
        with patch.object(Native,'stop',stop),patch.object(CodexVoiceHistory,'item',item):
            with self.socket()as socket:
                self.start(socket);self.close(socket)
        history=CodexVoiceHistory(self.root/'dashboard'/'codex-voice-visits')
        retained=history.read(self.visit,100,'a'*64)
        self.assertFalse(retained['transcript_complete'])
        self.assertEqual(retained['state'],'review')
        with self.socket()as socket:
            socket.send_json({**self.meta,'id':str(uuid.uuid4())})
            review=socket.receive_json()
            self.assertEqual(review['type'],'review')
            self.assertIn('needs reconciliation',review['message'])
            # No SDP negotiation, new voice input or native start was admitted.
        self.assertEqual(len(Native.opened),1)
        self.assertEqual(self.app.state.voice_active,set())

    def test_cancel_before_offer_does_not_block_successor(self):
        with self.socket()as socket:
            socket.send_json(self.meta)
            self.assertEqual(socket.receive_json()['type'],'prepared')
        deadline=time.monotonic()+2
        while not Native.opened[0].closed and time.monotonic()<deadline:time.sleep(.01)
        history=CodexVoiceHistory(self.root/'dashboard'/'codex-voice-visits')
        first=history.read(self.visit,100,'a'*64)
        self.assertTrue(first['transcript_complete'])
        self.assertEqual(first['native_start'],'not_attempted')
        self.assertFalse(Native.opened[0].started)
        self.visit=str(uuid.uuid4());self.meta['id']=self.visit
        with self.socket()as socket:
            self.start(socket);self.close(socket)
        self.assertEqual(sum(native.started for native in Native.opened),1)

    def test_unconfirmed_memory_hint_preserves_sources_without_starting_visit(self):
        with self.socket()as socket:self.start(socket);self.close(socket)
        history=CodexVoiceHistory(self.root/'dashboard'/'codex-voice-visits')
        retained=history.read(self.visit,100,'a'*64)
        next_visit=str(uuid.uuid4())
        with patch.object(Native,'remember',side_effect=ValueError('Unconfirmed memory context'))as remember:
            with self.socket()as socket:
                socket.send_json({**self.meta,'id':next_visit})
                self.assertEqual(socket.receive_json()['type'],'review')
                self.assertEqual(socket.receive_json()['type'],'closed')
                with self.assertRaises(WebSocketDisconnect):socket.receive_json()
        self.assertEqual(remember.call_count,1)
        self.assertEqual(history.read(self.visit,100,'a'*64),retained)
        self.assertFalse((history.root/(next_visit+'.json')).exists())
        self.assertFalse(Native.opened[-1].started)
        self.assertTrue(Native.opened[-1].closed)
        self.assertEqual(self.app.state.voice_active,set())

    def test_disconnected_browser_waits_for_memory_writer_before_releasing_lease(self):
        with self.socket()as socket:self.start(socket);self.close(socket)
        entered=threading.Event();finished=threading.Event();release=threading.Event()
        def remember(native,memory):
            entered.set();release.wait(2)
            self.assertFalse(native.closed)
            self.assertEqual(self.app.state.voice_active,{100})
            native.memory=memory;finished.set()
        with patch.object(Native,'remember',remember):
            with self.socket()as socket:
                socket.send_json({**self.meta,'id':str(uuid.uuid4())})
                self.assertTrue(entered.wait(1))
                self.assertEqual(self.app.state.voice_active,{100})
                self.assertFalse(Native.opened[-1].closed)
                # Closing the browser cannot cancel/retry the native context
                # writer. Release its controlled completion from another thread.
                timer=threading.Timer(.05,release.set);timer.start()
            timer.join()
        self.assertTrue(finished.is_set())
        deadline=time.monotonic()+2
        while not Native.opened[-1].closed and time.monotonic()<deadline:time.sleep(.01)
        self.assertTrue(Native.opened[-1].closed)
        self.assertEqual(self.app.state.voice_active,set())

    def test_refused_same_id_does_not_rewrite_prior_incomplete_visit(self):
        history=CodexVoiceHistory(self.root/'dashboard'/'codex-voice-visits')
        prior=history.open(self.visit,100,self.owner.codex_voice_binding('a'*64),str(uuid.uuid4()))
        with self.socket()as socket:
            socket.send_json(self.meta)
            self.assertEqual(socket.receive_json()['type'],'review')
        self.assertEqual(history.read(self.visit,100,'a'*64),prior)
        self.assertEqual(Native.opened,[])

    def test_reconnect_reconciles_canonical_correction_without_new_work(self):
        history=CodexVoiceHistory(self.root/'dashboard'/'codex-voice-visits')
        generation=str(uuid.uuid4());owner=self.owner.codex_voice_binding('a'*64)
        prior=history.open(str(uuid.uuid4()),100,owner,generation)
        source={'items':[{'id':'correction','role':'user','text':'Use the corrected value'}],
            'source_sha256':'c'*64}
        with patch.object(self.owner,'codex_voice_transcripts',return_value={generation:source})as read:
            with self.socket()as socket:self.start(socket);self.close(socket)
        read.assert_called_once_with(owner,[generation])
        self.assertEqual(Native.opened[0].continuation['items'],[{'role':'user','text':'Use the corrected value'}])
        self.assertTrue(history.read(prior['id'],100,'a'*64)['transcript_complete'])
        self.assertEqual(self.owner.collected,[])

    def test_default_configuration_has_no_native_openai_endpoint(self):
        other=FastAPI()
        self.assertFalse(install(other,{},self.owner,None,[]))
        self.assertFalse(other.routes[-1].path.startswith('/api/interaction'))
    def test_completed_visit_retains_original_without_asr_or_new_native_work(self):
        with self.socket()as socket:
            self.start(socket);self.close(socket)
        history=CodexVoiceHistory(self.root/'dashboard'/'codex-voice-visits')
        self.assertEqual(history.read(self.visit,100,'a'*64)['state'],'closed')
        self.assertEqual(Native.opened[0].context,self.identity.read_text())
        self.assertEqual(Native.opened[0].stops,1)
        self.assertTrue(Native.opened[0].closed);self.assertEqual(self.app.state.voice_active,set())
        route=f'/api/interaction/voice/codex/visits/{self.visit}/recordings/0'
        audio=wav_bytes(b'\x01\x00'*16000)
        first=self.client.post(route,content=audio,headers=self.headers)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(self.client.post(route,content=audio,headers=self.headers).json(),first.json())
        self.assertEqual(self.owner.collected,[])
        self.assertEqual(self.client.post(route,content=wav_bytes(b'\x02\x00'*16000),headers=self.headers).status_code,409)
        status=self.client.get(route.rsplit('/recordings',1)[0],headers=self.headers).json()
        self.assertEqual(len(status['recordings']),1);self.assertEqual(len(status['items']),1)
    def test_bad_binding_or_shared_capacity_refuses_before_native_open(self):
        for occupied,meta in ((False,{**self.meta,'binding':'b'*64}),(True,self.meta)):
            if occupied:self.app.state.voice_active.add(100)
            with self.socket()as socket:
                socket.send_json(meta);self.assertEqual(socket.receive_json()['type'],'review')
            self.assertEqual(Native.opened,[])
    def test_stale_csrf_and_changed_owner_refuse_before_native_open(self):
        for meta in ({**self.meta,'csrf':'stale'},self.meta):
            self.owner.held=meta is self.meta
            with self.socket()as socket:
                socket.send_json(meta);self.assertEqual(socket.receive_json()['type'],'review')
            self.assertEqual(Native.opened,[])
    def test_wrong_transcript_generation_never_enters_history(self):
        Native.bad_generation=True
        with self.socket()as socket:
            socket.send_json(self.meta);socket.receive_json()
            socket.send_json({'type':'offer','sdp':'v=0\r\nsynthetic-offer'})
            self.assertEqual(socket.receive_json()['type'],'answer')
            self.assertEqual(socket.receive_json()['type'],'review')
        value=CodexVoiceHistory(self.root/'dashboard'/'codex-voice-visits').read(self.visit,100,'a'*64)
        self.assertEqual(value['items'],[])
    def test_missing_close_observation_stays_review_not_closed(self):
        Native.lose_closure=True
        with self.socket()as socket:self.start(socket);self.close(socket)
        value=CodexVoiceHistory(self.root/'dashboard'/'codex-voice-visits').read(self.visit,100,'a'*64)
        self.assertEqual(value['state'],'review')
    def test_native_turn_admitted_during_stop_gets_existing_collector(self):
        self.owner.current='late-native-work'
        with self.socket()as socket:self.start(socket);self.close(socket)
        self.assertEqual(self.owner.collected,['late-native-work'])
        self.assertEqual(Native.opened[0].stops,1)
    def test_observed_native_turn_is_not_attached_twice_at_close(self):
        Native.emit_turn=True;self.owner.current='native-work'
        with self.socket()as socket:self.start(socket);self.close(socket)
        self.assertEqual(self.owner.collected,['native-work'])
    def test_failed_collector_retains_review_without_restarting_input(self):
        self.owner.current='failed-attachment'
        with patch.object(self.owner,'codex_voice_collect',side_effect=ValueError('Synthetic held owner'))as collect:
            with self.socket()as socket:self.start(socket);self.close(socket)
        self.assertEqual(collect.call_count,1)
        value=CodexVoiceHistory(self.root/'dashboard'/'codex-voice-visits').read(self.visit,100,'a'*64)
        self.assertEqual(value['state'],'review')
        self.assertTrue(Native.opened[0].closed)
    def test_stalled_review_send_still_closes_native_voice_and_releases_capacity(self):
        from starlette.websockets import WebSocket
        original=WebSocket.send_json
        async def stalled(socket,value,*args,**kwargs):
            if value.get('type')=='review':await asyncio.sleep(10)
            else:await original(socket,value,*args,**kwargs)
        with patch.object(WebSocket,'send_json',stalled):
            with self.socket()as socket:
                self.start(socket);socket.send_json({'type':'not-a-close'})
                self.assertEqual(socket.receive_json()['type'],'closed')
                with self.assertRaises(WebSocketDisconnect):socket.receive_json()
        self.assertEqual(Native.opened[0].stops,1)
        self.assertTrue(Native.opened[0].closed);self.assertEqual(self.app.state.voice_active,set())
    def test_cancelled_open_or_start_waits_single_attempt_then_cleans_up(self):
        for stage in ('open','start'):
            self.visit=str(uuid.uuid4());self.meta['id']=self.visit
            Native.open_delay=.1 if stage=='open'else 0
            Native.start_delay=.1 if stage=='start'else 0
            Native.opening_seen.clear();Native.starting_seen.clear()
            with self.socket()as socket:
                socket.send_json(self.meta)
                if stage=='start':
                    self.assertEqual(socket.receive_json()['type'],'prepared')
                    socket.send_json({'type':'offer','sdp':'v=0\r\nsynthetic-offer'})
                self.assertTrue((Native.opening_seen if stage=='open'else Native.starting_seen).wait(1))
            deadline=time.monotonic()+2
            while not Native.opened[-1].closed and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(Native.opened[-1].closed)
            self.assertEqual(Native.opened[-1].stops,1)
            self.assertEqual(self.app.state.voice_active,set())
        self.assertEqual(len(Native.opened),2)
    def test_network_disconnect_and_reconnect_preserve_each_terminal_metadata(self):
        import socket as sockets
        import uvicorn
        import websocket
        entered=threading.Event();release=threading.Event();reads=[]
        def current(owner):
            reads.append(owner)
            if len(reads)==1:
                entered.set()
                if not release.wait(5):raise TimeoutError('Synthetic reconciliation was not released')
            return None
        self.owner.codex_voice_current=current
        listener=sockets.socket();listener.bind(('127.0.0.1',0));listener.listen(5)
        server=uvicorn.Server(uvicorn.Config(self.app,log_level='error',access_log=False))
        thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True)
        thread.start()
        try:
            deadline=time.monotonic()+3
            while not server.started and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(server.started)
            socket=websocket.create_connection('ws://127.0.0.1:'+str(listener.getsockname()[1])+
                '/api/interaction/voice/codex',origin='https://example.test',timeout=3)
            try:
                socket.send(json.dumps(self.meta));self.assertEqual(json.loads(socket.recv())['type'],'prepared')
                socket.send(json.dumps({'type':'offer','sdp':'v=0\r\nsynthetic-offer'}))
                self.assertEqual(json.loads(socket.recv())['type'],'answer')
                self.assertEqual(json.loads(socket.recv())['type'],'transcript')
                socket.send(json.dumps({'type':'close'}))
                self.assertTrue(json.loads(socket.recv())['confirmed'])
            finally:socket.close()
            self.assertTrue(entered.wait(2))
            successor=str(uuid.uuid4())
            socket=websocket.create_connection('ws://127.0.0.1:'+str(listener.getsockname()[1])+
                '/api/interaction/voice/codex',origin='https://example.test',timeout=3)
            try:
                socket.send(json.dumps({**self.meta,'id':successor}))
                self.assertEqual(json.loads(socket.recv())['type'],'prepared')
                socket.send(json.dumps({'type':'offer','sdp':'v=0\r\nsynthetic-successor'}))
                self.assertEqual(json.loads(socket.recv())['type'],'answer')
                self.assertEqual(json.loads(socket.recv())['type'],'transcript')
                self.assertEqual(Native.opened[-1].continuation['sources'][0]['visit'],self.visit)
                self.assertEqual(Native.opened[-1].continuation['items'][0]['text'],'A native original')
                release.set()
                history=CodexVoiceHistory(self.root/'dashboard'/'codex-voice-visits')
                deadline=time.monotonic()+3
                while history.read(self.visit,100,'a'*64)['state']=='active'and time.monotonic()<deadline:time.sleep(.01)
                self.assertEqual(history.read(self.visit,100,'a'*64)['state'],'closed')
                self.assertEqual(self.app.state.voice_active,{100},'Old cleanup released its successor')
                socket.send(json.dumps({'type':'close'}))
                self.assertTrue(json.loads(socket.recv())['confirmed'])
            finally:socket.close()
            deadline=time.monotonic()+3
            while history.read(successor,100,'a'*64)['state']=='active'and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(history.read(successor,100,'a'*64)['state'],'closed')
            self.assertTrue(all(native.closed for native in Native.opened))
        finally:
            release.set();server.should_exit=True;thread.join(timeout=5);listener.close()
        self.assertFalse(thread.is_alive())

    def test_complete_app_auth_capability_assets_and_upload_middleware(self):
        from dashboard.app import create_app
        from dashboard.companion import permitted
        self.owner.receiver.pop('voice')  # Native mode does not depend on file ASR.
        config={**self.config,'origin':'https://example.test','bot_id':123}
        app=create_app(config,self.owner,lambda raw,bot:int(raw))
        with TestClient(app,base_url=config['origin'])as client:
            headers={'origin':config['origin']}
            session=client.post('/api/session',json={'init_data':'100'},headers=headers).json()
            headers['authorization']='Bearer '+session['session_token']
            page=client.get('/api/interaction',headers=headers)
            self.assertEqual(page.status_code,200,page.text)
            self.assertTrue(page.json()['can_converse_codex'])
            self.assertFalse(page.json()['can_converse_native'])
            headers['x-dashboard-csrf']=page.json()['csrf'];headers['x-voice-binding']='a'*64
            visit=str(uuid.uuid4())
            with client.websocket_connect('/api/interaction/voice/codex',headers={'origin':config['origin']})as socket:
                socket.send_json({'id':visit,'binding':'a'*64,'csrf':headers['x-dashboard-csrf'],
                    'authorization':headers['authorization']})
                self.assertEqual(socket.receive_json()['type'],'prepared')
                socket.send_json({'type':'offer','sdp':'v=0\r\nsynthetic-offer'})
                self.assertEqual(socket.receive_json()['type'],'answer');socket.receive_json();self.close(socket)
            route=f'/api/interaction/voice/codex/visits/{visit}/recordings/0'
            audio=wav_bytes(b'\x01\x00'*16000)
            result=client.post(route,content=audio,headers=headers)
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['recording']['audio_bytes'],len(audio))
            self.assertEqual(client.post(route,content=audio,headers={**headers,'x-dashboard-csrf':'stale'}).status_code,403)
            for path in ('/api/interaction/voice/codex',route):
                self.assertTrue(permitted('POST',path,'interaction_only'))
                self.assertFalse(permitted('POST',path,'monitor_readonly'))
            self.assertFalse(permitted('POST',route+'/retry','interaction_only'))
            self.assertIn('codex-conversation.js?v=',client.get('/').text)


if __name__=='__main__':unittest.main()
