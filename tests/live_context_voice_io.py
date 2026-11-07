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
from dashboard.qwen_dialogue import QwenDialogue
from dashboard.native_history import NativeHistory
from dashboard_native_voice import Stream, Detector
from workflow_native_returns_io import Returning
from conversation_routing_io import CanonicalRouting


class VoiceContext(Returning):
    def __init__(self,binary,keep_integrator_active=True):
        self.keep_integrator_active=keep_integrator_active;self.detached_context=None;self.detached_starts=0;self.reattached_tools=0;self.detached_physical=[];self.pending_terminal=None
        self.context_roles=set();self.context_outputs={}
        self.guide_id=None
        self.context_active=False;self.guide_checkpoint=None
        self.missing_audio_observations=[];self.derived_captions=[];self.fixture_errors=[]
        super().__init__(binary)

    def handle_extra_rpc(self,message,send):
        try:return self.context_rpc(message,send)
        except Exception as error:
            self.fixture_errors.append((type(error).__name__,str(error)[:256]));raise

    def context_rpc(self,message,send):
        method=message.get('method');p=message.get('params',{});ident=message.get('id')
        if method=='thread/turns/list' and self.detached_context is not None and p['threadId']==self.web_thread:
            pending=self.detached_context
            send({'id':ident,'result':{'data':[{'id':pending['turn'],'status':'inProgress','items':[]}],'nextCursor':None}})
            if p.get('limit')==1 and not pending['offered']:
                # Core keeps an unanswered tool request. The exact attachment
                # sees it again after metadata confirms the existing writer;
                # this is no new model input or semantic source.
                pending['offered']=True;self.reattached_tools+=1
                self.context_ack(send,pending['call'],pending['output'])
            return True
        if method=='turn/start' and 'toolOutput' in p:
            assert p['input']==[] and p['toolOutput']['name']=='foreground_context'
            output=json.loads(p['toolOutput']['output'])
            self.internal_packets.append(p)
            first=not self.context_active
            self.web_thread=p['threadId']
            if first:self.web_turn='voice-context-native-'+str(len(self.internal_packets))
            self.context_active=True
            if self.pending_terminal is not None:
                # Force terminal-before-ACK delivery of the old writer, after
                # the next internal request has already been written to it.
                self.broadcast(self.web_thread,'turn/completed',{'turn':{'id':self.pending_terminal,'status':'completed'}})
                self.pending_terminal=None
            send({'id':ident,'result':{'turn':{'id':self.web_turn}}})
            if first:self.broadcast(self.web_thread,'turn/started',{'turn':{'id':self.web_turn,'status':'inProgress'}})
            call='route-voice-context-'+str(len(self.internal_packets))
            self.context_outputs[call]=output
            assert output['evidence']['complete'],'This bounded fixture expects complete inline evidence'
            if first and not self.keep_integrator_active and 'additionalContext' not in p:
                self.detached_starts+=1;self.detached_physical.append(self.web_turn)
                self.detached_context={'turn':self.web_turn,'call':call,'output':output,'offered':False}
            else:self.context_ack(send,call,output)
            return True
        if method is None and str(ident).startswith('route-voice-context-'):
            assert message['result']['success'],message
            output=self.context_outputs[ident]
            # This fixture models an integrator still working while the finite
            # ASR draft is pending. Terminal-root/late-ACK ordering has its own
            # native-return regression; this is not evidence of tool servicing
            # on a newly detached physical root.
            if any(e.get('audio_without_transcript') for e in output['evidence']['content']['events']):
                if self.keep_integrator_active:return True
                if not any(e.get('derived_caption') for e in output['evidence']['content']['events']):
                    self.broadcast(self.web_thread,'item/completed',{'turnId':self.web_turn,'item':{
                        'id':'missing-caption-observation','type':'agentMessage','phase':'final_answer',
                        'text':'PRIVATE_NATIVE_CONTEXT_ONLY'}})
                    self.pending_terminal=self.web_turn;self.context_active=False
                    (self.root/'source-parent-incorporated').touch()
                    return True
            if any(e.get('audio_without_transcript') or e.get('derived_caption') for e in output['evidence']['content']['events']):
                self.broadcast(self.web_thread,'item/completed',{'turnId':self.web_turn,'item':{
                    'id':'missing-caption-observation','type':'agentMessage','phase':'final_answer',
                    'text':'PRIVATE_NATIVE_CONTEXT_ONLY'}})
                self.broadcast(self.web_thread,'turn/completed',{'turn':{'id':self.web_turn,'status':'completed'}})
                self.context_active=False
                self.detached_context=None
                return True
            if output.get('checkpoint_request') is not None:
                self.checkpoint_output=output
                send({'id':'route-pressure-read','method':'item/tool/call','params':{
                    'threadId':self.web_thread,'turnId':self.web_turn,'callId':'route-pressure-read',
                    'tool':'interaction_controller','arguments':output['checkpoint_reader']}})
                return True
            if self.context_roles=={'human','assistant'} and output['evidence']['through']%2==0:
                view=json.loads(message['result']['contentItems'][0]['text'])
                if self.guide_id is None:
                    self.guide_checkpoint=view;self.guide_id=str(uuid.uuid4())
                    send({'id':'route-voice-guide','method':'item/tool/call','params':{
                        'threadId':self.web_thread,'turnId':self.web_turn,'callId':'route-voice-guide',
                        'tool':'interaction_controller','arguments':{'operation':'live_context','arguments':{
                            'action':'guide','dialogue':output['dialogue'],'generation':output['generation'],
                            'basis':output['evidence']['through'],'id':self.guide_id,'mode':'context_only',
                            'text':'Use the confirmed shared memory without claiming an unconfirmed saved note.'}}}})
            return True
        if method is None and ident=='route-pressure-read':
            assert message['result']['success'],message
            view=json.loads(message['result']['contentItems'][0]['text'])
            assert view['range']['complete'] and view['range']['full']
            self.context_roles.update(e['role'] for e in view['range']['content']['events'])
            send({'id':'route-pressure-incorporate','method':'item/tool/call','params':{
                'threadId':self.web_thread,'turnId':self.web_turn,'callId':'route-pressure-incorporate',
                'tool':'interaction_controller','arguments':{'operation':'live_context','arguments':{
                    'action':'incorporate','dialogue':view['dialogue'],'revision':view['range']['revision']}}}})
            return True
        if method is None and ident=='route-pressure-incorporate':
            assert message['result']['success'],message
            self.checkpoint(send,json.loads(message['result']['contentItems'][0]['text']))
            return True
        if method is None and ident=='route-voice-guide':
            assert message['result']['success'],message
            receipt=json.loads(message['result']['contentItems'][0]['text'])
            assert receipt['guidance']['phase']=='pending'
            return True
        if method is None and str(ident).startswith('route-voice-checkpoint-'):
            assert message['result']['success'],message
            self.broadcast(self.web_thread,'item/completed',{'turnId':self.web_turn,'item':{
                'id':'private-context-bookkeeping','type':'agentMessage','phase':'final_answer',
                'text':'PRIVATE_NATIVE_CONTEXT_ONLY'}})
            self.broadcast(self.web_thread,'turn/completed',{'turn':{'id':self.web_turn,'status':'completed'}})
            self.context_active=False
            return True
        return CanonicalRouting.handle_extra_rpc(self,message,send)

    def context_ack(self,send,call,output):
        events=output['evidence']['content']['events']
        self.context_roles.update(e['role'] for e in events)
        self.missing_audio_observations.extend(e for e in events if e.get('audio_without_transcript'))
        self.derived_captions.extend(e for e in events if e.get('derived_caption'))
        send({'id':call,'method':'item/tool/call','params':{
            'threadId':self.web_thread,'turnId':self.web_turn,'callId':call,
            'tool':'interaction_controller','arguments':output['after_incorporation']}})

    def checkpoint(self,send,view):
        ident='route-voice-checkpoint-'+str(view['incorporated'])
        send({'id':ident,'method':'item/tool/call','params':{
            'threadId':self.web_thread,'turnId':self.web_turn,'callId':ident,
            'tool':'interaction_controller','arguments':{'operation':'live_context','arguments':{
                'action':'checkpoint','dialogue':view['dialogue'],'revision':view['checkpoint_revision'],
                'through':view['incorporated'],'text':'Keep our conversation purpose, current correction, confirmed memory distinction and unresolved effect references. Do not replay any original or effect.'}}}})


class CycleDetector(Detector):
    async def feed(self,pcm):
        self.total+=len(pcm);generation=(self.total+6399)//6400;first=self.total%6400==3200
        await self.queue.put({'type':'activity','audio_bytes':self.total,'generation':generation,
            'speaking':first,'speech_seen':True,
            'onset' if first else 'endpoint':{'generation':generation,'audio_bytes':self.total,
                **({} if first else {'authority':'analysis_only','probability':.9})}})


def qualify(binary,detached_semantic=False):
    j=VoiceContext(binary,keep_integrator_active=not detached_semantic)
    if detached_semantic:(j.root/'detached-test').touch()
    try:
        j.start();j.admit('Seed selected voice context.',topic=1)
        j.wait(lambda:j.has('Initial goal turn delivered.',1));j.idle();j.stop()
        helper=j.root/'completed.py'
        helper.write_text("""import json,pathlib,sys
root=pathlib.Path(sys.argv[1])
if '--completed-only' not in sys.argv:
 source=pathlib.Path(sys.argv[-1])
 if source.parent.name!='native-caption-audio':
  (root/'unexpected-asr').touch();sys.exit(2)
 with (root/'caption-asr-calls').open('a') as f:f.write('read\\n')
 if (root/'detached-test').exists():
  import time
  deadline=time.monotonic()+3
  while not (root/'source-parent-incorporated').exists() and time.monotonic()<deadline:time.sleep(.005)
  assert (root/'source-parent-incorporated').exists()
 print(json.dumps({'text':'Approximate synthetic assistant caption.','final':True}));sys.exit(0)
with (root/'completed-calls').open('a') as f:f.write('read\\n')
print(json.dumps({'text':'Exact synthetic interpretation','final':True,'streaming_model':'gemini-3.8-live'}))
""")
        j.config.write_text(j.config.read_text()+'\n[voice]\ntranscriber_label="synthetic/no-inference"\ntimeout_seconds=20\ntranscription_command='+json.dumps(['/usr/bin/python3',str(helper),str(j.root)])+'\ncompleted_transcription_command='+json.dumps(['/usr/bin/python3',str(helper),str(j.root),'--completed-only'])+'\n')
        # The user's one recognition is already completed by the live stream.
        # Native completion only reads it; the base helper remains for captions
        # of generated assistant audio, never another user recognition.
        live_command=['/usr/bin/python3',str(helper),str(j.root),'--completed-only']
        j.config.write_text(j.config.read_text()+'\n[voice.transcription_profiles.previous-live]\ntranscriber_label="synthetic/same-live-result"\ntranscription_command='+json.dumps(live_command)+'\ncompleted_transcription_command='+json.dumps(live_command)+'\n')
        j.start();j.wait_control_socket(j.socket);j.messages.clear()
        journal=j.row('SELECT count(*) FROM incoming_updates')
        config={'receiver_config':str(j.config),'state_dir':str(j.root/'dashboard'),
            'origin':'https://example.test','bot_id':123,
            'shared_auth':{'enabled':True,'home_origin':'https://example.test'},'streaming_transcription':{
                'enabled':True,'provider':'gemini','mode':'prepared','native_dialogue':True,'native_caption_recovery':True,
                'endpoint':'wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent',
                'credential_file':str(j.root/'synthetic-key'),'cache_root':str(j.root/'prepared'),
                'turn_detection':{'enabled':True,'continuous':True,'command':['/synthetic/python','capture-turn']}}}
        provider=Provider(config);app=create_app(config,provider,lambda raw,bot:int(raw))
        dialogue=str(uuid.uuid4());closed=queue.Queue()
        def log(message,*args,**kwargs):
            if message=='native_voice_closed %s':closed.put(json.loads(args[0]))
        identity={'contract':'dm.home-session/v1','origin':config['origin'],
            'expires':int(time.time())+3600,'actor':{'kind':'human','ref':'human:telegram:100'}}
        Stream.opened.clear()
        with patch('dashboard.home_auth.identity_response',return_value=identity),patch('dashboard.native_voice.NativeDialogue',Stream),patch('dashboard.native_voice.Detector',CycleDetector),patch.object(logging.getLogger('uvicorn.error'),'info',side_effect=log):
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
                    for cycle in range(2):
                        stream=Stream.opened[-1]
                        ws.send_bytes(tone);ws.send_bytes(b'\0\0'*1600)
                        utterance=None;original=None
                        while utterance is None or original is None:
                            event=ws.receive_json();assert event['type']!='review',event
                            if event['type']=='assistant_utterance' and event['utterance']['closed']:utterance=event['utterance']
                            if event['type']=='original_completed':original=event['id']
                        through=2*(cycle+1)
                        j.wait(lambda:j.row("SELECT json_extract(doc,'$.incorporated') FROM live_context WHERE dialogue=?",(dialogue,))==[(through,)])
                        j.wait(lambda:j.row("SELECT json_extract(doc,'$.guidance[0].phase') FROM live_context WHERE dialogue=?",(dialogue,))==[('sent',)])
                        if cycle==0:
                            assert len(stream.guidance)==1 and stream.guidance[0]['id']==j.guide_id
                            assert stream.guidance[0]['dialogue']==dialogue and stream.guidance[0]['mode']=='context_only'
                        stream.rollover_due=True
                        # Exercise the adapter's actual pressure contract against the native Store.
                        qwen=QwenDialogue.__new__(QwenDialogue)
                        qwen.context_estimate=48000;qwen.turns_finished=0
                        qwen.input_bytes=0;qwen.output_bytes=0
                        stream.checkpoint_pressure=qwen.checkpoint_pressure
                        ws.send_json({'type':'playback','id':utterance['id'],'played_bytes':640})
                        j.wait(lambda:stream.closed_event.is_set())
                        assert len(Stream.opened)==cycle+2
                        assert Stream.opened[-1].context['live_checkpoint']['through']==through
                    assert j.context_roles=={'human','assistant'}
                    assert [s.total for s in Stream.opened]==[6400,6400,0]
                    # A later audio-only provider turn is not silently omitted
                    # from Sol context or converted into invented human speech.
                    Stream.opened[-1].queue.put([{'type':'audio','pcm':b'\x10\0'*160,'sample_rate':24000},
                        {'type':'turn_complete'}])
                    while True:
                        event=ws.receive_json();assert event['type']!='review',event
                        if event['type']=='assistant_utterance' and event['utterance']['closed'] and not event['utterance'].get('derived_caption'):
                            assert event['utterance']['text']=='' and event['utterance']['generated_bytes']==320
                            ws.send_json({'type':'playback','id':event['utterance']['id'],'played_bytes':320})
                            break
                    try:j.wait(lambda:j.row("SELECT json_extract(doc,'$.incorporated') FROM live_context WHERE dialogue=?",(dialogue,))==[(6,)])
                    except AssertionError:
                        retained=json.loads(j.row('SELECT doc FROM live_context WHERE dialogue=?',(dialogue,))[0][0])
                        print('Caption native boundary:',{k:retained[k] for k in ('high','incorporated','closed','caption_parents')})
                        print('Caption return phases:',[(r['phase'],r.get('native_turn'),r['envelope'].get('through')) for r in retained['native_returns']])
                        print('Caption packet lengths:',[(len(json.dumps(packet)),list(packet.get('toolOutput',{}))) for packet in j.internal_packets])
                        print('Synthetic peer failures:',j.fixture_errors)
                        last=json.loads(j.internal_packets[-1]['toolOutput']['output'])
                        print('Last context schema/completeness:',last['schema'],last['evidence'].get('complete'))
                        print('Last exact RPC shapes:',[(v.get('method'),list(v.get('params',{})),v.get('error')) for v in j.rpc[-6:]])
                        raise
                    j.wait(lambda:j.row('SELECT busy FROM sessions WHERE thread_id=1')==[(0,)])
                    assert len(j.missing_audio_observations)==1
                    observation=j.missing_audio_observations[0]
                    assert observation['role']=='assistant' and observation['text']==''
                    assert observation['audio_without_transcript']['generated_bytes']==320
                    assert len(j.derived_captions)==1 and j.derived_captions[0]['derived_caption']['parent_source']==observation['source']
                    ws.send_json({'type':'close'})
                    summary=closed.get(timeout=5)
                    assert summary['context_producer']=='closed' and summary['provider_rollovers']==2,summary
        doc=json.loads(j.row('SELECT doc FROM live_context WHERE dialogue=?',(dialogue,))[0][0])
        assert doc['closed'] and doc['incorporated']==doc['high']==6
        if detached_semantic:
            assert j.detached_starts==j.reattached_tools==1
            receipt=next(r for r in doc['native_returns'] if r['envelope']['through']==6)
            assert receipt['collection_local']!=receipt['local'] and receipt['native_turn']==j.detached_physical[0]
            assert j.row('SELECT first_turn FROM native_collections WHERE local_turn=?',(receipt['collection_local'],))==[(receipt['native_turn'],)]
            assert all(r.get('method') not in ('thread/goal/set','thread/goal/clear') for r in j.rpc)
            print('PASS exact detached context attachment: one existing physical root, one pending tool, unchanged goals/originals, six sources incorporated and no input replay')
        assert doc['checkpoint']['through']==4
        assert len(doc['sources'])==6 and len(doc['events'])==2
        assert doc['events'][0]['text']=='' and doc['events'][0]['audio_without_transcript']['generated_bytes']==320
        pressure_packets=[json.loads(p['toolOutput']['output']) for p in j.internal_packets
            if json.loads(p['toolOutput']['output']).get('checkpoint_request') is not None]
        assert len(pressure_packets)==2
        assert all(p['evidence']['from']==p['evidence']['through']+1
            and p['evidence']['content']['events']==[] for p in pressure_packets)
        assert j.row('SELECT phase,local_turn FROM conversation_inputs')==[('foreground',None)]*2
        assert j.row('SELECT count(*) FROM interaction_instructions')==[(0,)]
        assert j.row('SELECT count(*) FROM interaction_workflows')==[(0,)]
        assert j.row('SELECT count(*) FROM incoming_updates')==journal
        assert not (j.root/'unexpected-asr').exists()
        assert (j.root/'completed-calls').read_text().splitlines()==['read','read']
        assert (j.root/'caption-asr-calls').read_text().splitlines()==['read']
        assert list((j.root/'dashboard'/'native-caption-audio').glob('*.wav'))==[]
        assert not j.messages
        assert not any('PRIVATE_NATIVE_CONTEXT_ONLY' in item['preview'] for item in provider.presentation_list(0,0)['items'])
        with app.state.native_history.database() as db:
            assert db.execute("SELECT count(*) FROM foreground_context_outbox WHERE phase='pending'").fetchone()[0]==0
            assert db.execute('SELECT count(*) FROM foreground_utterances').fetchone()[0]==4
        print('PASS two active voice socket handovers through completed-only originals, canonical assistant outbox including a missing-caption observation and one actual synthetic-ASR subprocess with parent-bound approximate recovery, actual owner/controller incorporation/checkpoints and source-bound Sol guidance; no PCM/work/ASR replay or private bookkeeping publication, clean close; synthetic audio/detector/Core/provider peers, zero models')
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


class ReconnectCheckpointContext(Returning):
    """Read every exact page through native controls before semantic retirement."""
    def __init__(self,binary):
        self.pages=0;self.read_texts=[];self.fixture_errors=[];self.control_serial=0
        super().__init__(binary)

    def call_context(self,send,ident,arguments):
        self.control_serial+=1;ident=f'{ident}-{self.control_serial}'
        send({'id':ident,'method':'item/tool/call','params':{
            'threadId':self.web_thread,'turnId':self.web_turn,'callId':ident,
            'tool':'interaction_controller','arguments':arguments}})

    def finish_context(self):
        self.broadcast(self.web_thread,'turn/completed',{'turn':{'id':self.web_turn,'status':'completed'}})

    def read_context(self,send,view,full):
        self.reading_full=full;self.read_view=view;self.parts=[]
        if view['range'].get('complete'):
            self.accept_content(send,view['range']['content'])
        else:
            self.call_context(send,'route-reconnect-page',{'operation':'live_context','arguments':{
                'action':'part','dialogue':view['dialogue'],'revision':view['range']['revision'],'offset':0}})

    def accept_content(self,send,content):
        self.read_texts.extend(e['text'] for e in content['events'])
        self.call_context(send,'route-reconnect-ack',self.read_view['after_incorporation'])

    def handle_extra_rpc(self,message,send):
        try:return self.context_rpc(message,send)
        except Exception as error:
            self.fixture_errors.append((type(error).__name__,str(error)[:256]));raise

    def context_rpc(self,message,send):
        method=message.get('method');p=message.get('params',{});ident=message.get('id')
        if method=='turn/start' and 'toolOutput' in p:
            output=json.loads(p['toolOutput']['output']);assert p['input']==[]
            self.internal_packets.append(p);self.web_thread=p['threadId']
            self.web_turn='reconnect-native-'+str(len(self.internal_packets));self.pending_context=output
            send({'id':ident,'result':{'turn':{'id':self.web_turn}}})
            self.broadcast(self.web_thread,'turn/started',{'turn':{'id':self.web_turn,'status':'inProgress'}})
            self.read_context(send,{'dialogue':output['dialogue'],'range':output['evidence'],
                'after_incorporation':output['after_incorporation']},False)
            return True
        if method is None and str(ident).startswith('route-reconnect-'):
            ident=ident.rsplit('-',1)[0]
            assert message['result']['success'],message
            view=json.loads(message['result']['contentItems'][0]['text'])
            if ident=='route-reconnect-page':
                self.pages+=1;self.parts.append(view['range']['text']);self.read_view=view
                if view['range']['more']:
                    self.call_context(send,ident,{'operation':'live_context','arguments':{
                        'action':'part','dialogue':view['dialogue'],'revision':view['range']['revision'],
                        'offset':view['range']['next']}})
                else:self.accept_content(send,json.loads(''.join(self.parts)))
            elif ident=='route-reconnect-full':self.read_context(send,view,True)
            elif ident=='route-reconnect-ack':
                if self.reading_full:
                    writer=self.read_view['checkpoint_writer']
                    writer['arguments']['text']='The corrected key is violet, replacing orange. Keep the unresolved bell question and its source references. No work was admitted or replayed.'
                    self.call_context(send,'route-reconnect-checkpoint',writer)
                elif self.pending_context.get('checkpoint_request'):
                    self.call_context(send,'route-reconnect-full',self.pending_context['checkpoint_reader'])
                else:self.finish_context()
            elif ident=='route-reconnect-checkpoint':self.finish_context()
            return True
        return CanonicalRouting.handle_extra_rpc(self,message,send)


def qualify_reconnect_compaction(binary,active=False):
    j=ReconnectCheckpointContext(binary)
    try:
        j.start();j.admit('Seed synthetic closed reconnect continuity.',topic=1)
        j.wait(lambda:j.has('Initial goal turn delivered.',1));j.idle();j.messages.clear()
        provider=Provider({'receiver_config':str(j.config),'state_dir':str(j.root/'reconnect-dashboard'),'bot_id':123})
        @contextmanager
        def database():
            db=sqlite3.connect(j.root/'context.sqlite3',timeout=3);db.row_factory=sqlite3.Row
            try:
                with db:yield db
            finally:db.close()
        history=NativeHistory(database,'reconnect-scope')
        binding=provider.presentation_list(0,0)['binding'];dialogue=str(uuid.uuid4())
        async def owner(function,*args):
            if not active and args and args[0].get('action')=='sync':
                # Simulate an older producer that does not select active preparation.
                args=({**args[0],'prepare_continuation':False},*args[1:])
            return await asyncio.to_thread(function,*args)
        async def scenario():
            old=NativeContext(history,provider,100,dialogue,binding,owner);await old.open()
            originals=['The key is orange. '+('Original attributed context. '*500),
                'Correction: the key is violet. Unresolved: where is the bell? '+('Retain original uncertainty. '*500)]
            for cycle in range(2 if active else 1):
                for text in originals:
                    history.retain(100,dialogue,binding,str(uuid.uuid4()),text,'d'*64,0,closed=True)
                await old._sync(old.record)
                field='checkpoint.through' if active else 'incorporated'
                await asyncio.to_thread(j.wait,lambda:j.row(
                    "SELECT json_extract(doc,?) FROM live_context WHERE dialogue=?",
                    ('$.'+field,dialogue))==[(2*(cycle+1),)])
                await asyncio.to_thread(j.idle)
            if active:
                doc=json.loads(j.row('SELECT doc FROM live_context WHERE dialogue=?',(dialogue,))[0][0])
                assert doc['generation']==old.record['generation'] and doc['rollover'] is None
                assert doc['continuation']['requests']==2 and doc['checkpoint_request']['committed']
            await old.close()
            needed=await old._call(old.record,'resume_read')
            if active:assert needed['resume']['bytes']<=24576
            else:assert needed['resume_requirement']['bytes']>24576
            fresh=NativeContext(history,provider,100,str(uuid.uuid4()),binding,owner)
            preparing=[]
            async def progress():preparing.append(True)
            seed=await fresh.resume_context(dialogue,on_preparing=progress)
            assert preparing==([] if active else [True]) and seed['bytes']<=24576
            assert 'violet' in seed['content']['checkpoint']['text']
            assert fresh.record is None,'Preparation must not open a new producer'
            assert j.pages>=4 and all(text in j.read_texts for text in originals)
            assert not j.fixture_errors,j.fixture_errors
            await fresh.open()
            doc=json.loads(j.row('SELECT doc FROM live_context WHERE dialogue=?',(fresh.dialogue,))[0][0])
            assert doc['resume_source']==fresh.resume_source
            # This fixture has semantically incorporated its complete tail.
            # Reconnect must copy that exact language once, not reserialize the
            # prior transport envelope into a progressively escaped JSON string.
            assert seed['content']['events']==[] and seed['content']['guidance']==[]
            assert doc['checkpoint']['text']==seed['content']['checkpoint']['text']
            assert doc['checkpoint']['text'].count('violet')==seed['content']['checkpoint']['text'].count('violet')
            await fresh.close()
        asyncio.run(scenario())
        assert j.row('SELECT count(*) FROM interaction_instructions')==[(0,)]
        assert j.row('SELECT count(*) FROM conversation_inputs')==[(0,)]
        assert not j.messages
        print('PASS '+('two active semantic checkpoints without provider renewal, ready reconnect' if active else 'closed oversized reconnect')+' through exact paginated native incorporation, full semantic checkpoint and source-bound successor opening; original correction retained, no human/work replay; synthetic reasoning, zero providers or models')
    finally:
        if sys.exc_info()[0]:print('Reconnect fixture errors:',j.fixture_errors,file=sys.stderr)
        j.close()


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
            parent=str(uuid.uuid4())
            history.retain(100,dialogue,binding,parent,'','c'*64,640,closed=True)
            await p._sync(p.record)
            await asyncio.to_thread(j.wait,lambda:j.row("SELECT json_extract(doc,'$.checkpoint.through') FROM live_context WHERE dialogue=?",(dialogue,))==[(3,)])
            await asyncio.to_thread(j.wait,lambda:j.row('SELECT busy FROM sessions WHERE thread_id=1')==[(0,)])
            await p.close()
            before=next(v for v in history.page(100)['items'] if v['id']==parent)
            draft=history.retain_caption(100,dialogue,binding,parent,'c'*64,640,
                {'text':'Synthetic approximate assistant caption after voice close.','final':True})
            actual=provider.conversation_live_context
            def lose_caption_receipt(body):
                result=actual(body)
                if body['action']=='sync' and any(s.get('derived_caption') for s in body.get('assistant',[])):
                    raise ProviderUnavailable('Synthetic lost derived-caption retention ACK')
                return result
            with patch.object(provider,'conversation_live_context',side_effect=lose_caption_receipt):
                try:await p._sync(p.record)
                except ProviderUnavailable:pass
                else:raise AssertionError('Fixture must lose the actual source receipt')
            await p._finish(p.record)
            await asyncio.to_thread(j.wait,lambda:j.row("SELECT json_extract(doc,'$.checkpoint.through') FROM live_context WHERE dialogue=?",(dialogue,))==[(4,)])
            await asyncio.to_thread(j.wait,lambda:j.row('SELECT busy FROM sessions WHERE thread_id=1')==[(0,)])
            doc=json.loads(j.row('SELECT doc FROM live_context WHERE dialogue=?',(dialogue,))[0][0])
            assert doc['closed'] and doc['high']==4 and doc['incorporated']==4
            assert len(doc['sources'])==4 and doc['caption_parents'][parent]['derived_source']==draft['id']
            assert before==next(v for v in history.page(100)['items'] if v['id']==parent)
            assert history.retain_caption(100,dialogue,binding,parent,'c'*64,640,
                {'text':'Synthetic approximate assistant caption after voice close.','final':True})==draft
            events=[e for packet in j.internal_packets for e in json.loads(packet['toolOutput']['output'])['evidence']['content']['events']]
            derived=[e for e in events if e.get('derived_caption')]
            assert len(derived)==1 and derived[0]['derived_caption']['parent_source']==parent

        asyncio.run(scenario())
        with database() as db:
            assert db.execute("SELECT count(*) FROM foreground_context_outbox WHERE phase='retained'").fetchone()[0]==4
            assert tuple(db.execute('SELECT phase,rollover FROM foreground_context_producers WHERE dialogue=?',(dialogue,)).fetchone())==('closed',None)
        assert j.row('SELECT count(*) FROM interaction_instructions')==[(0,)]
        assert j.row('SELECT count(*) FROM conversation_inputs')==[(0,)]
        assert not j.messages
        print('PASS two actual native checkpoint/generation cycles plus a late parent-bound ASR draft after checkpoint and voice close; lost actual source ACK reconciled once, original unchanged, closed producer retained, zero human originals/models/work replay; ASR/provider generation remains simulated')
    finally:j.close()


def qualify_public_context(binary):
    """Actual native reader and startup seeds; public transport/Core are simulated."""
    from dashboard.openai_live import LiveCall
    from dashboard.openai_live_visits import LiveCreations
    from dashboard.openai_live_native_session import PublicLiveSessionContext
    j=ReconnectCheckpointContext(binary)
    try:
        j.start();j.admit('Seed synthetic public voice continuity.',topic=1)
        j.wait(lambda:j.has('Initial goal turn delivered.',1));j.idle();j.messages.clear()
        provider=Provider({'receiver_config':str(j.config),'state_dir':str(j.root/'public-dashboard'),'bot_id':123})
        @contextmanager
        def database():
            db=sqlite3.connect(j.root/'public-context.sqlite3',timeout=3);db.row_factory=sqlite3.Row
            try:
                with db:yield db
            finally:db.close()
        history=NativeHistory(database,'public-native-context')
        binding=provider.presentation_list(0,0)['binding'];frozen=provider.public_live_binding(binding)
        caps=provider.presentation('input voice capabilities')
        assert caps['binding']==binding and caps['foreground_interpretation']=='gpt-transcribe/v1'
        assert all(caps.get(k)=='v1' for k in ('foreground_context','foreground_resume','foreground_public_live_transcripts'))
        visits=LiveCreations(j.root/'public-visits')
        baseline=j.row('SELECT count(*) FROM conversation_inputs')
        async def owner(function,*args):return await asyncio.to_thread(function,*args)
        async def scenario():
            previous=None
            # A complete provider fragment near12KiB still fits native typed
            # language16KiB; evidence metadata must not close an otherwise valid visit.
            large='The key is orange. '+('á'*5990)
            assert 11900<len(large.encode())<=12000
            texts=[large, 'Correction: the key is violet. The bell remains unresolved.']
            for cycle in range(3):
                ident=str(uuid.uuid4());visits.prepare(ident,100,frozen,backend_mode='native')
                context=PublicLiveSessionContext(history,visits,provider,100,ident,frozen,owner)
                spec=await context.prepare({'model':'gpt-live-1','instructions':'Synthetic identity',
                    'delegation':{'type':'client'},'store':False,'audio':{'output':{'voice':'cedar'}}})
                assert spec['audio']['output']['voice']=='cedar'
                assert visits.read(ident,100,frozen)['state']=='prepared'
                if previous is not None:
                    startup=spec['input'][-1]
                    assert startup['role']=='developer'
                    assert all(text in startup['content'][0]['text'] for text in texts[:cycle])
                    doc=json.loads(j.row('SELECT doc FROM live_context WHERE dialogue=?',(ident,))[0][0])
                    assert doc['resume_source']['dialogue']==previous
                client=type('PublicTransport',(),{'create':lambda self,*args:LiveCall('live:synthetic/'+ident,'v=0 answer')})()
                visits.create(ident,100,frozen,'v=0 synthetic offer',spec,client)
                if cycle<len(texts):
                    visits.event(ident,100,frozen,{'type':'session.input_transcript.delta',
                        'event_id':'source-'+str(cycle),'delta':texts[cycle],'start_ms':.5,'end_ms':20.25})
                    reference=await context.sync()
                    assert reference['dialogue']==ident
                    await asyncio.to_thread(j.wait,lambda:j.row(
                        "SELECT json_extract(doc,'$.incorporated')=json_extract(doc,'$.high') FROM live_context WHERE dialogue=?",(ident,))==[(1,)])
                    await asyncio.to_thread(j.idle)
                visits.observe_closed(ident,100,frozen,{'type':'session.closed','event_id':'closed-'+str(cycle),
                    'reason':'close_requested','session':{'id':'live:synthetic/'+ident}})
                await context.close();previous=ident
            assert not j.fixture_errors,j.fixture_errors
        asyncio.run(scenario())
        assert j.row('SELECT count(*) FROM conversation_inputs')==baseline
        assert j.row("SELECT count(*) FROM live_context WHERE json_extract(doc,'$.closed')=1")==[(3,)]
        assert len(j.read_texts)>=2 and not j.messages
        assert any(('á'*5990) in text for text in j.read_texts),'Native reader must receive the complete large Unicode fragment'
        print('PASS three public visits through actual native source retention, incorporation and complete startup seeds; corrections retained, Cedar preserved, zero new human originals/ASR/work/provider calls; speech and Core reasoning simulated')
    finally:j.close()


def qualify_public_live_window(binary):
    """Actual native journal reader + canonical ingress, with no file ASR."""
    from dashboard.live_transcription import wav_bytes
    from dashboard.openai_live import LiveCall
    from dashboard.openai_live_visits import LiveCreations
    from dashboard.openai_live_native_backend import prepare_native
    from dashboard.openai_live_seals import request_seal,accept_seal
    j=ReconnectCheckpointContext(binary)
    try:
        assert '[voice]' not in j.config.read_text()
        j.config.write_text(j.config.read_text()+'\n[voice]\ntranscription_command=["/bin/false"]\ntranscriber_label="Forbidden second ASR in Live-window qualification"\n')
        j.start();j.admit('Seed synthetic public window handoff.',topic=1)
        j.wait(lambda:j.has('Initial goal turn delivered.',1));j.idle();j.messages.clear()
        provider=Provider({'receiver_config':str(j.config),'state_dir':str(j.root/'window-dashboard'),'bot_id':123})
        binding=provider.presentation_list(0,0)['binding'];owner=provider.public_live_binding(binding)
        assert provider.presentation('input voice capabilities')['foreground_live_window']=='journal-input/v1'
        visits=LiveCreations(j.root/'window-visits');ident=str(uuid.uuid4())
        visits.prepare(ident,100,owner,backend_mode='native')
        transport=type('Transport',(),{'create':lambda self,*args:LiveCall('live:window-synthetic','v=0 answer')})()
        visits.create(ident,100,owner,'v=0 synthetic offer',{'model':'gpt-live-1','instructions':'Synthetic only','delegation':{'type':'client'},'store':False},transport)
        tone=b''.join(struct.pack('<h',int(5000*math.sin(2*math.pi*440*n/16000))) for n in range(1600))
        for ordinal in range(32):visits.recording(ident,100,binding,ordinal,wav_bytes(tone),provider)
        text='Use only this Live input transcript. Keep the later correction.'
        visits.event(ident,100,owner,{'type':'session.input_transcript.delta','event_id':'input','delta':text,'start_ms':0,'end_ms':100})
        visits.event(ident,100,owner,{'type':'session.output_transcript.delta','event_id':'output','delta':'Never promote assistant output.','start_ms':0,'end_ms':100})
        visits.event(ident,100,owner,{'type':'session.delegation.created','event_id':'task','delegation':{'id':'window-task','target':'client'}})
        seal=request_seal(visits,ident,100,owner,'window-task',provider)
        accept_seal(visits,ident,100,owner,{'type':'source_sealed','request':seal['request'],'through_ordinal':32,'capture_bytes':32*len(tone)},provider)
        capture_errors=[];capture=provider.conversation_voice_submit
        def observed_capture(*args,**kwargs):
            try:return capture(*args,**kwargs)
            except Exception as error:
                capture_errors.append((type(error).__name__,str(error)[:300]));raise
        provider.conversation_voice_submit=observed_capture
        def forbidden(*args):raise AssertionError('Second ASR must never start')
        result=prepare_native(visits,ident,100,owner,'window-task',provider,'/no-key-required',forbidden)
        assert result['state']=='admitted',(result,capture_errors)
        value=visits.read(ident,100,owner);root=value['delegations']['window-task']['native_work']['root']
        j.wait(lambda:provider.conversation_input_status(root).get('native_acceptance')=='observed')
        original=provider.conversation_input_status(root);proof=original['foreground_delegation']
        assert original['text']==text and original['voice'].get('transcription') is None
        assert proof['live_window']['input_events']==1 and len(proof['sources'])==32
        assert all(source['voice'].get('transcription') is None for source in proof['sources'])
        assert 'Never promote assistant output.' not in original['text']
        assert all('interpretation' not in slot for slot in value['native_originals'].values())
        assert prepare_native(visits,ident,100,owner,'window-task',provider,'/no-key-required',forbidden)==result
        print('public Live window: exact journal input + 32 raw originals + native canonical handoff, zero ASR; synthetic Core only, no real provider/model calls')
        provider.close()
    finally:j.close()


if __name__=='__main__':
    binary=str(Path(sys.argv[1]).resolve())
    if '--public-window' in sys.argv[2:]:qualify_public_live_window(binary)
    elif '--public-context' in sys.argv[2:]:qualify_public_context(binary)
    elif '--active-compaction' in sys.argv[2:]:qualify_reconnect_compaction(binary,active=True)
    elif '--reconnect-compaction' in sys.argv[2:]:qualify_reconnect_compaction(binary)
    elif '--detached-semantic' in sys.argv[2:]:qualify(binary,detached_semantic=True)
    else:qualify(binary);qualify(binary,detached_semantic=True);qualify_rollover(binary);qualify_reconnect_compaction(binary);qualify_reconnect_compaction(binary,active=True)
