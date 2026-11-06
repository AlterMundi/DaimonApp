#!/usr/bin/env python3
"""Committed browser audio through actual HTTP/owner/SQLite/decoder/native; no models."""
import asyncio
import hashlib
import io
import json
import math
from pathlib import Path
import sqlite3
import struct
import sys
import uuid
import wave
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from dashboard.app import create_app
from dashboard.provider import Provider
from dashboard.live_transcription import wav_bytes
from conversation_requests_http_io import Requests

def audio(frequency=440,silence=False):
    target=io.BytesIO()
    with wave.open(target,'wb') as wav:
        wav.setparams((1,2,16000,0,'NONE','not compressed'))
        wav.writeframes(b''.join(struct.pack('<h',0 if silence else int(5000*math.sin(2*math.pi*frequency*i/16000))) for i in range(3200)))
    return target.getvalue()

def qualify(binary, stop_reason="duration_limit"):
    j=Requests(str(Path(binary).resolve()));client=None
    try:
        j.start()
        for topic in (7,8,1):
            j.admit('Seed owned native context',topic=topic);j.wait(lambda:j.has('Initial goal turn delivered.',topic));j.idle()
        j.stop()
        transcriber=j.root/'asr.py';transcriber.write_text('''import hashlib,json,pathlib,sys,time
root=pathlib.Path(sys.argv[1]);digest=hashlib.sha256(pathlib.Path(sys.argv[-1]).read_bytes()).hexdigest()
item=json.loads((root/'transcripts.json').read_text())[digest]
if '--completed-only' in sys.argv:
    result=root/('completed-'+digest+'.json')
    if not result.exists():sys.exit(2)
    print(result.read_text());sys.exit(0)
if item.get('fail'):sys.exit(2)
with (root/'asr-calls').open('a') as output:output.write(digest+'\\n')
while item.get('hold') and not (root/('release-'+digest)).exists():time.sleep(.02)
print(json.dumps({'text':item['text'],'final':True}))
''')
        j.config.write_text(j.config.read_text()+j.target_config+'\n[voice]\ntranscriber_label="synthetic/no-inference"\ntimeout_seconds=20\ntranscription_command='+json.dumps(['/usr/bin/python3',str(transcriber),str(j.root)])+'\ncompleted_transcription_command='+json.dumps(['/usr/bin/python3',str(transcriber),str(j.root),'--completed-only'])+'\n')
        j.start();j.wait_control_socket(j.socket);j.routing=True
        binding=j.read('presentation','list','0','0')['result']['binding'];j.messages.clear()
        config={'receiver_config':str(j.config),'state_dir':str(j.root/'dashboard'),'origin':'https://example.test','bot_id':123}
        client=TestClient(create_app(config,Provider(config),lambda raw,bot:int(raw)),base_url=config['origin'])
        headers={'origin':config['origin']}
        token=client.post('/api/session',json={'init_data':'100'},headers=headers).json()['session_token'];headers['authorization']='Bearer '+token
        page=client.get('/api/interaction',headers=headers).json();assert page['can_speak'];headers['x-dashboard-csrf']=page['csrf']
        transcripts={}
        def calls():
            p=j.root/'asr-calls';return p.read_text().splitlines() if p.exists() else []
        def register(data,text,hold=False):
            digest=hashlib.sha256(data).hexdigest();transcripts[digest]={'text':text,'hold':hold};(j.root/'transcripts.json').write_text(json.dumps(transcripts));return digest
        def upload(data,ident=None,selected=None,digest=None,stop=None):
            ident=ident or str(uuid.uuid4());digest=digest or hashlib.sha256(data).hexdigest()
            h={**(headers if selected is None else selected),'content-type':'audio/wav','x-input-binding':binding,'x-input-id':ident,'x-audio-sha256':digest}
            if stop is not None:h['x-recording-stop']=stop
            return ident,client.post('/api/interaction/voice/limited' if stop is not None else '/api/interaction/voice',content=data,headers=h)
        def status(ident):
            result=client.get('/api/interaction/inputs/'+ident,headers=headers);assert result.status_code==200,result.text;return result.json()
        data=audio();digest=register(data,'Earlier spoken requirement13.',True)
        assert upload(data,selected={k:v for k,v in headers.items() if k!='authorization'})[1].status_code==401
        assert upload(data,selected={k:v for k,v in headers.items() if k!='x-dashboard-csrf'})[1].status_code==403
        assert upload(data,digest='0'*64)[1].status_code==400
        assert upload(b'x'*(20*1024*1024+1))[1].status_code==413
        failed_sync=str(uuid.uuid4())
        with patch('dashboard.provider.sync_directory',side_effect=OSError('Synthetic directory-sync failure')):
            assert upload(data,failed_sync)[1].status_code==503
        assert not calls() and j.row('SELECT count(*) FROM conversation_inputs WHERE id=?',(failed_sync,))==[(0,)]
        original,response=upload(data,stop=stop_reason);assert response.status_code==200,response.text
        assert response.json()['phase']=='preparing' and response.json()['text']==''
        j.wait(lambda:digest in calls());assert not j.packets,'Partial ASR admitted work'
        repeated=upload(data,original,stop=stop_reason)[1];assert repeated.status_code==200 and not repeated.json()['new_input']
        assert upload(audio(555),original)[1].status_code==400
        assert calls().count(digest)==1
        # Native immutable-identity refusals use the existing unconfirmed-control
        # HTTP response; inspect the retained original rather than replaying it.
        assert upload(data,original)[1].status_code==503,'A retry cannot drop the duration-limit context'
        assert status(original)['voice']['capture_stop']==stop_reason
        assert calls().count(digest)==1
        later=str(uuid.uuid4());later_response=client.post('/api/interaction/inputs',json={'binding':binding,'id':later,'text':'Later correction: requirement17.'},headers=headers)
        assert later_response.status_code==200,later_response.text
        j.wait(lambda:status(later)['phase']=='accepted');assert len(j.packets)==1
        j.call('route-newer-text','dispatch',{'input_ref':later,'destinations':[{'selector':'Alpha','relation':'new','requests':[]}]})
        j.wait(lambda:j.instructions(7) and j.instructions(7)[0][1]=='accepted')
        (j.root/('release-'+digest)).touch()
        j.wait(lambda:j.row('SELECT phase FROM conversation_inputs WHERE id=?',(original,))==[('accepted',)])
        assert not Path(str(j.root/'state.sqlite')+'.voice').joinpath(original).exists(), 'Committed browser capture remained without another client read'
        retained=status(original);assert retained['text']=='Earlier spoken requirement13.'
        proof=retained['voice']['transcription'];assert proof['capture_id']==original and 'telegram_file_id' not in proof and proof['audio_sha256']==digest
        assert 'not verified written speech' in j.packets[-1][1]['input'][0]['text']
        assert proof['capture_stop']==stop_reason
        assert 'wait for or clarify the continuation' in j.packets[-1][1]['input'][0]['text']
        request=json.loads(j.instructions(7)[0][2])['requests']
        j.call('route-older-voice','dispatch',{'input_ref':original,'destinations':[{'selector':'Alpha','relation':'amends','requests':request}]})
        j.wait(lambda:len(j.instructions(7))==2 and j.instructions(7)[1][1]=='accepted')
        worker_packet=j.worker_packets['native-topic-7'][-1]['input'][0]['text']
        assert '"capture_id":"'+original+'"' in worker_packet and 'Earlier spoken requirement13.' in worker_packet
        orders=j.row("SELECT event_id,id FROM original_ingress_order WHERE channel='conversation' ORDER BY id")
        assert orders[0][0]==original and orders[1][0]==later and orders[0][1]<orders[1][1]
        assert json.loads(worker_packet.split('Transport provenance: ',1)[1].split('\nCurrent instruction:',1)[0])['transcription']['capture_stop']==stop_reason
        assert '"capture_order":'+str(orders[0][1]) in worker_packet
        assert calls().count(digest)==1 and len(j.packets)==2
        assert not Path(str(j.root/'state.sqlite')+'.voice').joinpath(original).exists()
        repeated = upload(data,original,stop=stop_reason)[1]
        assert repeated.status_code==200 and calls().count(digest)==1
        assert not Path(str(j.root/'state.sqlite')+'.voice').joinpath(original).exists()
        # Silence fails before invoking ASR and leaves ordinary text controls usable.
        silent=audio(silence=True);register(silent,'Never use hallucinated silence')
        silent_id,r=upload(silent);assert r.status_code==200
        j.wait(lambda:status(silent_id)['phase']=='preparation_unconfirmed');assert len(calls())==1 and len(j.packets)==2
        # Failed originals recover only already completed text, preserving order/identity.
        recovery_data=audio(610);recovery_digest=register(recovery_data,'Recovered original')
        transcripts[recovery_digest]['fail']=True
        (j.root/'transcripts.json').write_text(json.dumps(transcripts))
        recovery_id,r=upload(recovery_data,stop=stop_reason);assert r.status_code==200
        j.wait(lambda:status(recovery_id)['phase']=='preparation_unconfirmed')
        before_calls=list(calls())
        command={'binding':binding,'id':recovery_id}
        def recover():
            return j.read('input','voice','recover',json.dumps(command))
        recover()
        j.wait(lambda:status(recovery_id)['phase']=='preparation_unconfirmed')
        assert calls()==before_calls and not status(recovery_id)['text']
        (j.root/('completed-'+recovery_digest+'.json')).write_text(json.dumps({'text':'Recovered original','final':True}))
        recover();j.wait(lambda:status(recovery_id)['phase']=='accepted')
        assert calls()==before_calls and status(recovery_id)['text']=='Recovered original'
        saved=status(recovery_id)['voice']['transcription']
        assert saved['capture_id']==recovery_id and saved['audio_sha256']==recovery_digest
        assert saved['capture_stop']==stop_reason,'Completed-transcript recovery retains the same truncation context'
        assert not Path(str(j.root/'state.sqlite')+'.voice').joinpath(recovery_id).exists()
        recover();assert calls()==before_calls
        # The additional accepted original is real fixture work, not another upload.
        assert len(j.packets)==3
        # Restoring a revoked grant cannot revive an in-flight voice capture.
        data2=audio(660);digest2=register(data2,'Must not run after authority retirement',True)
        retired,r=upload(data2);assert r.status_code==200;j.wait(lambda:digest2 in calls())
        with sqlite3.connect(j.root/'state.sqlite') as db:
            db.execute('UPDATE users SET allowed=0 WHERE tg_user_id=100');db.execute('UPDATE users SET allowed=1 WHERE tg_user_id=100')
        (j.root/('release-'+digest2)).touch();j.wait(lambda:status(retired)['phase']=='preparation_unconfirmed')
        assert status(retired)['retired'] and len(j.packets)==3
        # Grant restoration creates a new browser binding. An old tab cannot
        # capture input with its retired generation, even for the same UUID.
        stale=upload(data2,retired)[1];assert stale.status_code==503,stale.text
        assert calls().count(digest2)==1
        current=client.get('/api/interaction/inputs',headers=headers)
        assert current.status_code==200,current.text
        assert current.json()['binding']!=binding
        binding=current.json()['binding']
        repeated=upload(data2,retired)[1];assert repeated.status_code==200,repeated.text
        assert repeated.json()['new_input'] is False and repeated.json()['retired']
        assert calls().count(digest2)==1 and len(j.packets)==3
        # Restart closes only fixture processes, retaining uncertainty without ASR/native replay.
        data3=audio(770);digest3=register(data3,'Never replay after restart',True)
        interrupted,r=upload(data3);assert r.status_code==200;j.wait(lambda:digest3 in calls())
        j.stop();j.start();j.wait_control_socket(j.socket)
        assert status(interrupted)['phase']=='preparation_unconfirmed'
        assert upload(data3,interrupted)[1].json()['new_input'] is False and calls().count(digest3)==1
        assert not j.messages,'Canonical microphone fabricated Telegram publication'
        print('PASS committed browser voice: actual HTTP/owner/SQLite/decoder/native, one retained clip identity, final ASR only, source order before later text, attributed worker routing, silence, duplicate/changed upload, grant ABA and restart without replay; zero models.')
    finally:
        if client:client.close()
        j.close()

def foreground_capture(binary):
    j=Requests(str(Path(binary).resolve()))
    try:
        j.start();j.admit('Seed foreground capture integrator',topic=1)
        j.wait(lambda:j.has('Initial goal turn delivered.',1));j.idle();j.stop()
        helper=j.root/'completed-foreground.py'
        helper.write_text("""import json,pathlib,sys
root=pathlib.Path(sys.argv[1])
if '--completed-only' not in sys.argv:
 (root/'unexpected-asr').touch();sys.exit(2)
with (root/'completed-calls').open('a') as out:out.write('read\\n')
print(json.dumps({'text':'Synthetic native foreground interpretation.','final':True,'streaming_model':'gemini-3.8-live'}))
""")
        j.config.write_text(j.config.read_text()+'\n[voice]\ntranscriber_label="synthetic/no-inference"\ntimeout_seconds=20\ntranscription_command='+json.dumps(['/usr/bin/python3',str(helper),str(j.root)])+'\ncompleted_transcription_command='+json.dumps(['/usr/bin/python3',str(helper),str(j.root),'--completed-only'])+'\n')
        j.start();j.wait_control_socket(j.socket)
        config={'receiver_config':str(j.config),'state_dir':str(j.root/'dashboard'),'origin':'https://example.test','bot_id':123}
        provider=Provider(config);binding=j.read('presentation','list','0','0')['result']['binding']
        data=audio();ident=str(uuid.uuid4());dialogue=str(uuid.uuid4())
        body={'binding':binding,'id':ident,'audio_sha256':hashlib.sha256(data).hexdigest(),'mime':'audio/wav','capture_questions':{}}
        result=provider.conversation_voice_submit(body,data,foreground_dialogue=dialogue,defer_foreground=True)
        assert result['phase']=='foreground_captured'
        assert not (j.root/'completed-calls').exists() and not j.packets
        later=str(uuid.uuid4())
        provider.conversation_foreground_retain({'id':later,'binding':binding,'dialogue_id':dialogue,
                                                'text':'Use the later scope correction.'})
        provider.conversation_foreground_complete(ident,binding,dialogue)
        j.wait(lambda:provider.conversation_input_status(ident)['phase']=='foreground')
        saved=provider.conversation_input_status(ident)
        assert saved['voice']['transcription']['actual_transcriber']=='gemini-3.8-live'
        assert saved['voice']['transcription']['audio_sha256']==body['audio_sha256']
        assert saved['voice']['transcription']['capture_id']==ident
        assert saved['native_acceptance']=='not_requested' and not j.packets
        assert not (j.root/'unexpected-asr').exists()
        assert (j.root/'completed-calls').read_text().splitlines()==['read']
        again=provider.conversation_voice_submit(body,data,foreground_dialogue=dialogue)
        assert not again['new_input'] and again['phase']=='foreground'
        assert (j.root/'completed-calls').read_text().splitlines()==['read']
        delegated={'binding':binding,'id':later,'intent_id':str(uuid.uuid4()),
                   'formulation':'Resolve the selected synthetic request with the later correction.','source_ids':[ident,later]}
        provider.conversation_foreground_delegate(delegated)
        j.wait(lambda:provider.conversation_input_status(later)['phase']=='accepted')
        assert len(j.packets)==1
        orders=j.row("SELECT event_id FROM original_ingress_order WHERE channel='conversation' ORDER BY id")
        assert orders==[(ident,),(later,)],'Deferred transcript completion changed original capture order'
        text=j.packets[0][1]['input'][0]['text']
        assert saved['voice']['transcription']['interpretation'] in text and 'gemini-3.8-live' in text
        assert body['audio_sha256'] in text
        assert not provider.conversation_foreground_delegate(delegated)['new_input']
        assert len(j.packets)==1
        # An already captured original must finish its deferred retention even
        # when close happens before its first file/owner await. This uses the
        # actual owner command/SQLite, without interpreting or replaying audio.
        from dashboard.native_foreground import ForegroundBridge
        class ClosedStream:
            activity_mode='automatic';model='gemini-3.8-live'
        with wave.open(io.BytesIO(audio(990)),'rb') as wav:tail=wav.readframes(wav.getnframes())
        recovered=str(uuid.uuid4());recovery_dialogue=str(uuid.uuid4());checks=[]
        async def close_with_capture():
            async def authorize():
                caps=await asyncio.to_thread(provider.presentation,'input voice capabilities')
                assert caps['binding']==binding
                checks.append(True)
            bridge=ForegroundBridge(provider,ClosedStream(),j.root/'close-prepared',recovery_dialogue,binding,authorize)
            capture=bridge.capture(recovered,tail,{})
            await bridge.close()
            return await capture.reservation
        result=asyncio.run(close_with_capture())
        assert checks==[True] and result['phase']=='foreground_captured'
        saved=provider.conversation_input_status(recovered)
        assert saved['foreground_dialogue']==recovery_dialogue and saved['native_acceptance']=='not_requested'
        assert not saved.get('text') and not (j.root/'unexpected-asr').exists()
        assert Path(str(provider.receiver['db_path'])+'.voice',recovered).read_bytes()==wav_bytes(tail)
        assert (j.root/'completed-calls').read_text().splitlines()==['read']
        assert len(j.packets)==1,'Close recovery must not submit another native turn'
        # Public Live uses this SAME native foreground reservation, without
        # inventing transcript text, starting ASR or submitting a model turn.
        from dashboard.openai_live_visits import LiveCreations
        from dashboard.openai_live_originals import enroll_original
        public=LiveCreations(j.root/'public-visits');visit=str(uuid.uuid4())
        owner=provider.public_live_binding(binding);public.prepare(visit,provider.human,owner)
        receipt=public.recording(visit,provider.human,binding,0,audio(880),provider)
        from dashboard.provider import ProviderUnavailable
        native_submit=provider.conversation_voice_submit;native_calls=[]
        def lost_native_ack(*args,**kwargs):
            native_calls.append(True);native_submit(*args,**kwargs)
            raise ProviderUnavailable('Synthetic lost acknowledgement after actual native reservation')
        provider.conversation_voice_submit=lost_native_ack
        assert enroll_original(public,visit,provider.human,owner,0,provider)['state']=='unconfirmed'
        # Restart the App reader, retain the exact native write intent, and read
        # the actual SQLite/owner receipt instead of submitting it again.
        public=LiveCreations(j.root/'public-visits')
        enrolled=enroll_original(public,visit,provider.human,owner,0,provider)
        assert native_calls==[True]
        provider.conversation_voice_submit=native_submit
        assert enrolled['state']=='observed' and enrolled['work_admitted'] is False
        original=provider.conversation_input_status(receipt['id'])
        assert original['phase']=='foreground_captured' and original['foreground_dialogue']==visit
        assert not original.get('text') and original['native_acceptance']=='not_requested'
        assert not original['voice'].get('transcription')
        assert original['voice']['audio_sha256']==receipt['audio_sha256']
        assert enroll_original(public,visit,provider.human,owner,0,provider)==enrolled
        assert (j.root/'completed-calls').read_text().splitlines()==['read']
        assert len(j.packets)==1 and not (j.root/'unexpected-asr').exists()
        correction=str(uuid.uuid4())
        provider.conversation_foreground_retain({'id':correction,'binding':binding,
            'dialogue_id':visit,'text':'Later correction belongs after this public acoustic original.'})
        order=j.row("SELECT event_id FROM original_ingress_order WHERE channel='conversation' ORDER BY id")
        assert order.index((receipt['id'],))<order.index((correction,))
        # A fresh, complete public original uses OpenAI interpretation exactly
        # once, then imports its derivative into the SAME native source row.
        # The recognizer is synthetic; the owner socket/SQLite/WAV proof are real.
        from dashboard.openai_live_transcription import interpret_original, commit_interpretation
        # Separate fixture store: the preceding case intentionally leaves an
        # unconfirmed provider creation. This does not qualify visit renewal.
        active=LiveCreations(j.root/'public-import-visits');active_visit=str(uuid.uuid4())
        active.prepare(active_visit,provider.human,owner)
        sample=audio(990);acoustic=active.recording(active_visit,provider.human,binding,0,sample,provider)
        assert enroll_original(active,active_visit,provider.human,owner,0,provider)['state']=='observed'
        asr_calls=[]
        class SyntheticRecognizer:
            model='gpt-transcribe'
            def transcribe(self,data):
                assert data==sample;asr_calls.append(True)
                return 'Interpretación sintética: el destino corregido es Río Cobre.'
        derivative=interpret_original(active,active_visit,provider.human,owner,0,provider,SyntheticRecognizer())
        assert derivative['state']=='completed' and asr_calls==[True]
        native_interpret=provider.conversation_foreground_interpret;native_imports=[]
        def lost_import_ack(body):
            native_imports.append(dict(body));native_interpret(body)
            raise ProviderUnavailable('Synthetic lost acknowledgement after actual native interpretation import')
        provider.conversation_foreground_interpret=lost_import_ack
        assert commit_interpretation(active,active_visit,provider.human,owner,0,provider)['state']=='unconfirmed'
        restarted=LiveCreations(j.root/'public-import-visits')
        imported=commit_interpretation(restarted,active_visit,provider.human,owner,0,provider)
        assert imported['state']=='observed' and imported['work_admitted'] is False
        assert len(native_imports)==1 and asr_calls==[True]
        provider.conversation_foreground_interpret=native_interpret
        actual=provider.conversation_input_status(acoustic['id'])
        assert actual['text']==derivative['text'] and actual['phase']=='foreground'
        assert actual['voice']['preserve_original'] is True
        assert actual['capture_questions'] == {}
        proof=actual['voice']['transcription']
        assert proof['actual_transcriber']=='gpt-transcribe' and proof['capture_id']==acoustic['id']
        assert proof['audio_sha256']==acoustic['audio_sha256'] and proof['audio_millis']==200
        assert 'not' in proof['interpretation'].lower() and actual['native_acceptance']=='not_requested'
        assert not actual.get('foreground_delegation')
        assert j.row('SELECT count(*) FROM conversation_inputs WHERE id=?',(acoustic['id'],))==[(1,)]
        assert native_interpret(native_imports[0])['new_input'] is False
        assert len(j.packets)==1 and not (j.root/'unexpected-asr').exists()
        assert Path(str(provider.receiver['db_path'])+'.voice',acoustic['id']).read_bytes()==sample
        # A trusted client-delegation event can admit this SAME source into the
        # existing native integrator. Public creation/native inference are fake;
        # owner ingress, source freezing and SQLite admission are actual code.
        from dashboard.openai_live import LiveCall, session_spec
        from dashboard.openai_live_native_work import delegate_native
        class SyntheticCreation:
            def create(self,sdp,spec):
                assert spec['delegation']['type']=='client'
                return LiveCall('synthetic:client-delegation','v=0 synthetic answer')
        active.create(active_visit,provider.human,owner,'v=0 synthetic offer',
            session_spec('Synthetic qualification only.',client_delegation=True),SyntheticCreation())
        active.event(active_visit,provider.human,owner,{'type':'session.delegation.created',
            'event_id':'synthetic-native-work-event','offset_ms':200,
            'delegation':{'id':'synthetic-native-work','target':'client'}})
        native_delegate=provider.conversation_foreground_delegate;native_work_calls=[]
        def lost_work_ack(body):
            native_work_calls.append(dict(body));native_delegate(body)
            raise ProviderUnavailable('Synthetic lost work acknowledgment after actual native admission')
        provider.conversation_foreground_delegate=lost_work_ack
        formulation='Resolve the synthetic request from the retained public acoustic source; incorporate its correction.'
        def work(history):
            return delegate_native(history,active_visit,provider.human,owner,
                'synthetic-native-work',[0],formulation,provider)
        assert work(active)['state']=='unconfirmed'
        assert work(LiveCreations(j.root/'public-import-visits'))['state']=='observed'
        assert len(native_work_calls)==1 and asr_calls==[True]
        provider.conversation_foreground_delegate=native_delegate
        j.wait(lambda:provider.conversation_input_status(acoustic['id'])['phase']=='accepted')
        delegated=provider.conversation_input_status(acoustic['id'])['foreground_delegation']
        assert delegated['formulation']==formulation and delegated['sources'][0]['text']==derivative['text']
        assert delegated['sources'][0]['voice']['audio_sha256']==acoustic['audio_sha256']
        assert len(j.packets)==2
        assert formulation in j.packets[-1][1]['input'][0]['text']
        assert acoustic['audio_sha256'] in j.packets[-1][1]['input'][0]['text']
        assert not work(active)['work_completed'] and len(native_work_calls)==1
        # The fixture's native peer now finishes that exact turn. Read the
        # actual canonical source/revision, return it once over a fake sideband,
        # and retain a context-injection ACK separately from unobserved hearing.
        from dashboard.openai_live_native_results import return_native_part
        native_text='Resultado nativo sintético: el destino corregido es Río Cobre.'
        j.broadcast(j.web_thread,'item/completed',{'turnId':j.web_turn,'item':{
            'id':'synthetic-public-result','type':'agentMessage','phase':'final_answer','text':native_text}})
        j.broadcast(j.web_thread,'turn/completed',{'turn':{'id':j.web_turn,'status':'completed'}})
        local=provider.conversation_input_status(acoustic['id'])['local_turn']
        def returned():
            return [row for row in provider.presentation_list(0,0,'before')['items']
                if row.get('kind')=='integrator_answer' and row.get('local_turn')==local]
        j.wait(lambda:bool(returned()))
        source=returned()[0];updates=[]
        class SyntheticSideband:
            def send(self,command):updates.append(dict(command))
        sideband=SyntheticSideband()
        def send_result(history):
            return return_native_part(history,active_visit,provider.human,owner,
                'synthetic-native-work',source['id'],source['revision'],0,provider,sideband)
        assert send_result(active)['state']=='sent'
        assert native_text in updates[0]['content'] and updates[0]['delegation_id']=='synthetic-native-work'
        active.event(active_visit,provider.human,owner,{'type':'session.commentary.appended',
            'event_id':'synthetic-native-result-ack','client_event_id':updates[0]['event_id']})
        returned_receipt=send_result(LiveCreations(j.root/'public-import-visits'))
        assert returned_receipt['state']=='context_injected' and returned_receipt['hearing']=='not_observed'
        assert len(updates)==1 and len(native_work_calls)==1 and len(j.packets)==2
        later=str(uuid.uuid4());provider.conversation_foreground_retain({'id':later,'binding':binding,
            'dialogue_id':active_visit,'text':'Later human correction is preserved after the acoustic original.'})
        order=j.row("SELECT event_id FROM original_ingress_order WHERE channel='conversation' ORDER BY id")
        assert order.count((acoustic['id'],))==1 and order.index((acoustic['id'],))<order.index((later,))
        print('PASS public gpt-transcribe import, client delegation and exact canonical native result return through actual owner/SQLite/WAV; one synthetic native admission and context append, lost-ACK restart reads, separate injection/hearing; no real inference or paid calls.')
        print('PASS native foreground WAV/proof and immediate-close deferred retention through actual owner/SQLite: actor/binding rechecked, exact unconfirmed WAV retained, no ASR/work/replay on close; one sourced native admission; zero models.')
    finally:j.close()

def archive_hold(binary, legacy=False):
    """Actual native ASR must retain a selected original across archive failure."""
    from dashboard.media_retention import MediaRetention
    j=Requests(str(Path(binary).resolve()));client=None
    try:
        j.start();j.admit('Seed protected archive entry',topic=1)
        j.wait(lambda:j.has('Initial goal turn delivered.',1));j.idle();j.stop()
        # The archive contract uses a real-form native UUID; this synthetic
        # peer normally seeds presentation-only names such as native-topic-7.
        with sqlite3.connect(j.root/'state.sqlite') as db:
            db.execute('UPDATE sessions SET codex_thread_id=? WHERE chat_id=100 AND thread_id=1',(str(uuid.uuid4()),))
        helper=j.root/'archive-asr.py'
        helper.write_text("""import hashlib,json,pathlib,sys,time
p=pathlib.Path(sys.argv[1]);digest=hashlib.sha256(pathlib.Path(sys.argv[-1]).read_bytes()).hexdigest()
p.open('a').write('asr\\n')
while (p.parent/('hold-'+digest)).exists():time.sleep(.02)
print(json.dumps({'text':'Keep this exact protected requirement.','final':True}))
""")
        j.config.write_text(j.config.read_text()+j.target_config+'\n[voice]\ntranscriber_label="synthetic/no-inference"\ntimeout_seconds=20\ntranscription_command='+json.dumps([sys.executable,str(helper),str(j.root/'archive-asr-calls')])+'\n')
        j.start();j.wait_control_socket(j.socket);j.routing=True
        page=j.read('input','list','0','before')['result'];binding=page['binding'];entry=page['entry_binding'];j.messages.clear()  # Exclude the earlier seed's Telegram reply.
        retention={'directory':str(j.root/'archive'),'human_id':100,'chat_id':entry[1]['chat_id'],
            'topic_id':entry[1]['thread_id'],'native_thread':entry[3],
            'since':'2026-01-01T00:00:00+00:00','max_bytes':1048576}
        original=audio(220);older=MediaRetention(retention).retain({'id':str(uuid.uuid4()),'entry_binding':entry},'human','audio/wav',original)
        config={'receiver_config':str(j.config),'state_dir':str(j.root/'dashboard'),'origin':'https://example.test','bot_id':123,
            'media_retention':{**retention,'max_bytes':1}}
        provider=Provider(config);client=TestClient(create_app(config,provider,lambda raw,bot:int(raw)),base_url=config['origin'])
        headers={'origin':config['origin']}
        token=client.post('/api/session',json={'init_data':'100'},headers=headers).json()['session_token'];headers['authorization']='Bearer '+token
        page=client.get('/api/interaction',headers=headers).json();headers['x-dashboard-csrf']=page['csrf']
        if not legacy:
            # Select archive protection while an earlier unheld ASR is running.
            # Capability must not be mistaken for that original's saved policy.
            prior_data=audio(770);prior_id=str(uuid.uuid4());prior_digest=hashlib.sha256(prior_data).hexdigest()
            gate=j.root/('hold-'+prior_digest);gate.touch()
            prior_meta={'binding':binding,'id':prior_id,'audio_sha256':prior_digest,'mime':'audio/wav'}
            selection=provider.media_retention;provider.media_retention=None
            admitted=provider.conversation_voice_submit(prior_meta,prior_data)
            provider.media_retention=selection
            j.wait(lambda:(j.root/'archive-asr-calls').exists())
            assert admitted['voice'].get('preserve_original') is not True
            # Also cover the transaction race beyond the adapter's preflight.
            refused=j.read('input','voice','submit',json.dumps({**prior_meta,'preserve_original':True}),ok=False)
            assert not refused.get('ok',False),refused
            from dashboard.media_retention import RetentionUnavailable
            try:provider.conversation_voice_submit(prior_meta,prior_data)
            except RetentionUnavailable:pass
            else:raise AssertionError('An existing unheld ASR was falsely upgraded')
            prior_path=Path(str(provider.receiver['db_path'])+'.voice')/prior_id
            assert prior_path.read_bytes()==prior_data
            assert len(j.row('SELECT id FROM conversation_inputs WHERE id=?',(prior_id,)))==1
            gate.unlink()
            j.wait(lambda:provider.presentation('input status '+prior_id)['phase']=='accepted')
            j.wait(lambda:not prior_path.exists())  # Original unselected cleanup contract.
            # This synthetic UUID peer intentionally leaves its turn unresolved.
            # Retain that uncertainty across restart; do not fabricate a reply.
            j.stop();j.start();j.wait_control_socket(j.socket)
            j.packets.clear();(j.root/'archive-asr-calls').unlink()
        data=audio(550);ident=str(uuid.uuid4());digest=hashlib.sha256(data).hexdigest()
        voice_headers={**headers,'content-type':'audio/wav','x-input-binding':binding,'x-input-id':ident,'x-audio-sha256':digest}
        def upload():return client.post('/api/interaction/voice',content=data,headers=voice_headers)
        def status():
            r=client.get('/api/interaction/inputs/'+ident,headers=headers);assert r.status_code==200,r.text;return r.json()
        response=upload();path=Path(str(provider.receiver['db_path'])+'.voice')/ident
        assert path.read_bytes()==data
        if legacy:
            assert response.status_code==507,response.text
            assert j.row('SELECT count(*) FROM conversation_inputs WHERE id=?',(ident,))==[(0,)]
            assert not (j.root/'archive-asr-calls').exists()
            print('PASS older writer refuses archive deferral before native input/ASR; exact original remains protected')
            return
        assert response.status_code==200,response.text
        assert response.json()['voice']['preserve_original'] is True
        assert response.json()['media_retention']['original_retained'] is True
        j.wait(lambda:status()['phase']=='accepted')
        assert status()['media_retention']['state']=='pending' and path.read_bytes()==data
        assert upload().json()['new_input'] is False
        fillers=[]
        for n in range(128):
            filler=path.parent/('synthetic-held-'+str(n));filler.write_bytes(b'held');filler.chmod(0o600);fillers.append(filler)
        refused=str(uuid.uuid4())
        full=client.post('/api/interaction/voice',content=data,
            headers={**voice_headers,'x-input-id':refused})
        assert full.status_code==503,full.text
        assert j.row('SELECT count(*) FROM conversation_inputs WHERE id=?',(refused,))==[(0,)]
        assert not (path.parent/refused).exists() and path.read_bytes()==data
        for filler in fillers:filler.unlink()  # Only these test-owned placeholders.
        j.stop();j.start();j.wait_control_socket(j.socket)
        assert status()['voice']['preserve_original'] is True and path.read_bytes()==data
        # Even a closed/changed archive selection cannot downgrade a saved hold.
        selected=provider.media_retention;provider.media_retention=None
        assert status()['media_retention']['original_retained'] is True and path.read_bytes()==data
        provider.media_retention=selected;selected.config['max_bytes']=retention['max_bytes']
        assert status()['phase']=='accepted' and not path.exists()
        assert (selected.root/digest).read_bytes()==data
        assert (selected.root/older['audio_sha256']).read_bytes()==original
        assert (j.root/'archive-asr-calls').read_text().splitlines()==['asr']
        assert len(j.packets)==1 and not j.messages,(len(j.packets),j.messages)
        print('PASS archive-full HTTP/native ASR, matching transcript and restart keep original until exact handoff; same-ID retry, unchanged old original, one ASR/native admission; zero models')
    finally:
        if client:client.close()
        j.close()

if __name__=='__main__':
    if '--archive-hold' in sys.argv[2:]:archive_hold(sys.argv[1])
    elif '--archive-legacy' in sys.argv[2:]:archive_hold(sys.argv[1],legacy=True)
    else:
        foreground_capture(sys.argv[1])
        for reason in ('duration_limit','audio_flush_unconfirmed'):qualify(sys.argv[1],reason)
        archive_hold(sys.argv[1])
