#!/usr/bin/env python3
"""Mounted voice → actual provider/control/native Store → synthetic Core context.

Provider audio, detector and Core reasoning are simulated; auth, file/voice
retention, completed interpretation, both SQLite stores, owner socket, native
transport/controller and presentation are real. No models or hardware capture.
"""
import json
import asyncio
from contextlib import contextmanager
import logging
import math
from pathlib import Path
import queue
import sys
import struct
import sqlite3
import time
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from dashboard.app import create_app
from dashboard.provider import Provider
from dashboard.provider import ProviderUnavailable
from dashboard.native_context import NativeContext
from dashboard.native_history import NativeHistory
from dashboard_native_voice import Stream, Detector
from workflow_native_returns_io import Returning
from conversation_routing_io import CanonicalRouting


class VoiceContext(Returning):
    def __init__(self,binary):
        self.context_roles=set();self.context_outputs={}
        self.guide_id=None
        super().__init__(binary)

    def handle_extra_rpc(self,message,send):
        method=message.get('method');p=message.get('params',{});ident=message.get('id')
        if method=='turn/start' and 'toolOutput' in p:
            assert p['input']==[] and p['toolOutput']['name']=='foreground_context'
            output=json.loads(p['toolOutput']['output'])
            self.internal_packets.append(p)
            evidence=output['evidence'];assert evidence['complete']
            self.context_roles.update(e['role'] for e in evidence['content']['events'])
            first=self.web_turn is None
            self.web_thread=p['threadId'];self.web_turn='voice-context-native'
            send({'id':ident,'result':{'turn':{'id':self.web_turn}}})
            if first:self.broadcast(self.web_thread,'turn/started',{'turn':{'id':self.web_turn,'status':'inProgress'}})
            call='route-voice-context-'+str(len(self.internal_packets))
            self.context_outputs[call]=output
            send({'id':call,'method':'item/tool/call','params':{
                'threadId':self.web_thread,'turnId':self.web_turn,'callId':call,
                'tool':'interaction_controller','arguments':output['after_incorporation']}})
            return True
        if method is None and str(ident).startswith('route-voice-context-'):
            assert message['result']['success'],message
            output=self.context_outputs[ident]
            if self.context_roles=={'human','assistant'} and output['evidence']['through']>=2 and self.guide_id is None:
                self.guide_id=str(uuid.uuid4())
                send({'id':'route-voice-guide','method':'item/tool/call','params':{
                    'threadId':self.web_thread,'turnId':self.web_turn,'callId':'route-voice-guide',
                    'tool':'interaction_controller','arguments':{'operation':'live_context','arguments':{
                        'action':'guide','dialogue':output['dialogue'],'generation':output['generation'],
                        'basis':output['evidence']['through'],'id':self.guide_id,'mode':'context_only',
                        'text':'Use the confirmed shared memory without claiming an unconfirmed saved note.'}}}})
            return True
        if method is None and ident=='route-voice-guide':
            assert message['result']['success'],message
            receipt=json.loads(message['result']['contentItems'][0]['text'])
            assert receipt['guidance']['phase']=='pending'
            if self.context_roles=={'human','assistant'}:
                self.broadcast(self.web_thread,'item/completed',{'turnId':self.web_turn,'item':{
                    'id':'private-context-bookkeeping','type':'agentMessage','phase':'final_answer',
                    'text':'PRIVATE_NATIVE_CONTEXT_ONLY'}})
                self.broadcast(self.web_thread,'turn/completed',{'turn':{'id':self.web_turn,'status':'completed'}})
            return True
        return CanonicalRouting.handle_extra_rpc(self,message,send)


def qualify(binary):
    j=VoiceContext(binary)
    try:
        j.start();j.admit('Seed selected voice context.',topic=1)
        j.wait(lambda:j.has('Initial goal turn delivered.',1));j.idle();j.stop()
        helper=j.root/'completed.py'
        helper.write_text("""import json,pathlib,sys
root=pathlib.Path(sys.argv[1])
if '--completed-only' not in sys.argv:
 (root/'unexpected-asr').touch();sys.exit(2)
with (root/'completed-calls').open('a') as f:f.write('read\\n')
print(json.dumps({'text':'Exact synthetic interpretation','final':True,'streaming_model':'gemini-3.8-live'}))
""")
        j.config.write_text(j.config.read_text()+'\n[voice]\ntranscriber_label="synthetic/no-inference"\ntimeout_seconds=20\ntranscription_command='+json.dumps(['/usr/bin/python3',str(helper),str(j.root)])+'\ncompleted_transcription_command='+json.dumps(['/usr/bin/python3',str(helper),str(j.root),'--completed-only'])+'\n')
        j.start();j.wait_control_socket(j.socket);j.messages.clear()
        journal=j.row('SELECT count(*) FROM incoming_updates')
        config={'receiver_config':str(j.config),'state_dir':str(j.root/'dashboard'),
            'origin':'https://example.test','bot_id':123,
            'shared_auth':{'enabled':True,'home_origin':'https://example.test'},'streaming_transcription':{
                'enabled':True,'provider':'gemini','mode':'prepared','native_dialogue':True,
                'endpoint':'wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent',
                'credential_file':str(j.root/'synthetic-key'),'cache_root':str(j.root/'prepared'),
                'turn_detection':{'enabled':True,'continuous':True,'command':['/synthetic/python','capture-turn']}}}
        provider=Provider(config);app=create_app(config,provider,lambda raw,bot:int(raw))
        dialogue=str(uuid.uuid4());closed=queue.Queue()
        def log(message,*args,**kwargs):
            if message=='native_voice_closed %s':closed.put(json.loads(args[0]))
        identity={'contract':'dm.home-session/v1','origin':config['origin'],
            'expires':int(time.time())+3600,'actor':{'kind':'human','ref':'human:telegram:100'}}
        with patch('dashboard.home_auth.identity_response',return_value=identity),patch('dashboard.native_voice.NativeDialogue',Stream),patch('dashboard.native_voice.Detector',Detector),patch.object(logging.getLogger('uvicorn.error'),'info',side_effect=log):
            with TestClient(app,base_url=config['origin']) as client:
                client.cookies.set('__Host-home','h'*43,path='/')
                access=client.get('/api/interaction/access')
                assert access.status_code==200,access.text
                csrf=access.json()['csrf']
                binding=provider.presentation_list(0,0)['binding']
                with client.websocket_connect('wss://example.test/api/interaction/voice/native',headers={'origin':config['origin']}) as ws:
                    ws.send_json({'id':dialogue,'binding':binding,'csrf':csrf})
                    ready=ws.receive_json()
                    assert ready['type']=='ready',ready
                    # The actual decoder rejects inaudible amplitude-one PCM;
                    # use a bounded synthetic tone, never a hardware microphone.
                    tone=b''.join(struct.pack('<h',int(5000*math.sin(2*math.pi*440*i/16000))) for i in range(1600))
                    ws.send_bytes(tone);ws.send_bytes(b'\0\0'*1600)
                    j.wait(lambda:j.row("SELECT json_extract(doc,'$.incorporated') FROM live_context WHERE dialogue=?",(dialogue,))==[(2,)])
                    assert j.context_roles=={'human','assistant'}
                    j.wait(lambda:j.row("SELECT json_extract(doc,'$.guidance[0].phase') FROM live_context WHERE dialogue=?",(dialogue,))==[('sent',)])
                    stream=Stream.opened[0]
                    assert len(stream.guidance)==1 and stream.guidance[0]['id']==j.guide_id
                    assert stream.guidance[0]['dialogue']==dialogue and stream.guidance[0]['mode']=='context_only'
                    ws.send_json({'type':'close'})
                    summary=closed.get(timeout=5)
                    assert summary['context_producer']=='closed',summary
        doc=json.loads(j.row('SELECT doc FROM live_context WHERE dialogue=?',(dialogue,))[0][0])
        assert doc['closed'] and doc['incorporated']==doc['high']==2
        assert {e['role'] for e in doc['events']}=={'human','assistant'}
        assert j.row('SELECT phase,local_turn FROM conversation_inputs')==[('foreground',None)]
        assert j.row('SELECT count(*) FROM interaction_instructions')==[(0,)]
        assert j.row('SELECT count(*) FROM interaction_workflows')==[(0,)]
        assert j.row('SELECT count(*) FROM incoming_updates')==journal
        assert not (j.root/'unexpected-asr').exists()
        assert (j.root/'completed-calls').read_text().splitlines()==['read']
        assert not j.messages
        assert not any('PRIVATE_NATIVE_CONTEXT_ONLY' in item['preview'] for item in provider.presentation_list(0,0)['items'])
        with app.state.native_history.database() as db:
            assert db.execute("SELECT count(*) FROM foreground_context_outbox WHERE phase='pending'").fetchone()[0]==0
            assert db.execute('SELECT count(*) FROM foreground_utterances').fetchone()[0]==1
        print('PASS mounted voice + completed-only original + assistant outbox → actual owner/native-controller context incorporation → source-bound Sol guidance to the same Live; sent is not applied/heard, clean close, no work/ASR/audio replay or private bookkeeping publication; synthetic audio/detector/Core, zero models')
    finally:j.close()


class CheckpointContext(Returning):
    """Actual native incorporation/checkpoint controls; synthetic reasoning."""
    def handle_extra_rpc(self,message,send):
        method=message.get('method');p=message.get('params',{});ident=message.get('id')
        if method=='turn/start' and 'toolOutput' in p:
            output=json.loads(p['toolOutput']['output']);assert p['input']==[]
            self.internal_packets.append(p);self.web_thread=p['threadId']
            self.web_turn='checkpoint-native-'+str(len(self.internal_packets))
            self.pending_context=output
            send({'id':ident,'result':{'turn':{'id':self.web_turn}}})
            self.broadcast(self.web_thread,'turn/started',{'turn':{'id':self.web_turn,'status':'inProgress'}})
            send({'id':'route-incorporate','method':'item/tool/call','params':{
                'threadId':self.web_thread,'turnId':self.web_turn,'callId':'route-incorporate',
                'tool':'interaction_controller','arguments':output['after_incorporation']}})
            return True
        if method is None and ident=='route-incorporate':
            assert message['result']['success'],message
            view=json.loads(message['result']['contentItems'][0]['text'])
            send({'id':'route-checkpoint','method':'item/tool/call','params':{
                'threadId':self.web_thread,'turnId':self.web_turn,'callId':'route-checkpoint',
                'tool':'interaction_controller','arguments':{'operation':'live_context','arguments':{
                    'action':'checkpoint','dialogue':view['dialogue'],'revision':view['checkpoint_revision'],
                    'through':view['incorporated'],'text':'Keep our current conversation purpose, the human correction and unresolved effect references. No effects are replayed from this semantic checkpoint.'}}}})
            return True
        if method is None and ident=='route-checkpoint':
            assert message['result']['success'],message
            self.broadcast(self.web_thread,'item/completed',{'turnId':self.web_turn,'item':{
                'id':'internal-checkpoint','type':'agentMessage','phase':'final_answer','text':'PRIVATE_CHECKPOINT_BOOKKEEPING'}})
            self.broadcast(self.web_thread,'turn/completed',{'turn':{'id':self.web_turn,'status':'completed'}})
            return True
        return CanonicalRouting.handle_extra_rpc(self,message,send)


def qualify_rollover(binary):
    j=CheckpointContext(binary)
    try:
        j.start();j.admit('Seed synthetic checkpoint continuity.',topic=1)
        j.wait(lambda:j.has('Initial goal turn delivered.',1));j.idle();j.messages.clear()
        config={'receiver_config':str(j.config),'state_dir':str(j.root/'checkpoint-dashboard'),'bot_id':123}
        provider=Provider(config)
        @contextmanager
        def database():
            db=sqlite3.connect(j.root/'context.sqlite3',timeout=3);db.row_factory=sqlite3.Row
            try:
                with db:yield db
            finally:db.close()
        history=NativeHistory(database,'checkpoint-scope')
        binding=provider.presentation_list(0,0)['binding'];dialogue=str(uuid.uuid4())
        async def owner(function,*args):return await asyncio.to_thread(function,*args)
        async def scenario():
            p=NativeContext(history,provider,100,dialogue,binding,owner);await p.open()
            first_generation=p.record['generation']
            for cycle in range(2):
                source=str(uuid.uuid4())
                history.retain(100,dialogue,binding,source,f'Exact language for cycle {cycle}.','b'*64,0,closed=True)
                await p._sync(p.record)
                await asyncio.to_thread(j.wait,lambda:j.row("SELECT json_extract(doc,'$.checkpoint.through') FROM live_context WHERE dialogue=?",(dialogue,))==[(cycle+1,)])
                await asyncio.to_thread(j.wait,lambda:j.row('SELECT busy FROM sessions WHERE thread_id=1')==[(0,)])
                basis=await p.prepare_rollover();assert basis is not None
                intent=await p.begin_rollover(basis,str(uuid.uuid4()));assert intent is not None
                actual=provider.conversation_live_context
                if cycle==0:
                    def queued_commit(body):
                        if body['action']=='rollover_commit':raise ProviderUnavailable('Synthetic still-queued commit')
                        return actual(body)
                    with patch.object(provider,'conversation_live_context',side_effect=queued_commit):
                        assert not await p.commit_rollover(intent)
                    try:
                        actual({'action':'rollover_commit','dialogue':dialogue,'generation':intent['previous'],
                            'next_generation':intent['next'],'revision':intent['revision']})
                    except ProviderUnavailable:pass
                    else:raise AssertionError('An actual delayed commit must be fenced after abort')
                    intent=await p.begin_rollover(basis,str(uuid.uuid4()));assert intent is not None
                def lose_commit(body):
                    result=actual(body)
                    if body['action']=='rollover_commit':raise ProviderUnavailable('Synthetic lost ACK after ACTUAL native commit')
                    return result
                with patch.object(provider,'conversation_live_context',side_effect=lose_commit):
                    assert await p.commit_rollover(intent)
                assert p.record['generation']==intent['next'] and p.record['rollover'] is None
            assert p.record['generation']!=first_generation
            await p.close()
        asyncio.run(scenario())
        with database() as db:
            assert db.execute("SELECT count(*) FROM foreground_context_outbox WHERE phase='retained'").fetchone()[0]==2
            assert tuple(db.execute('SELECT phase,rollover FROM foreground_context_producers WHERE dialogue=?',(dialogue,)).fetchone())==('closed',None)
        assert j.row('SELECT count(*) FROM interaction_instructions')==[(0,)]
        assert j.row('SELECT count(*) FROM conversation_inputs')==[(0,)]
        assert not j.messages
        print('PASS two actual native incorporation/checkpoint/generation cycles with local SQLite CAS and deliberately lost commit ACK, fenced outcome recovery, once-only sources and no models/socket/work replay; provider rollover remains separate')
    finally:j.close()


if __name__=='__main__':
    binary=str(Path(sys.argv[1]).resolve());qualify(binary);qualify_rollover(binary)
