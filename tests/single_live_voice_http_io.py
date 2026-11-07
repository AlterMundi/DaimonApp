"""Actual native admission of one live result, with no file recognizer available."""
import hashlib
import json
from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from dashboard.app import create_app
from dashboard.provider import Provider
from dashboard.live_transcription import save_prepared
from conversation_requests_http_io import Requests
from conversation_voice_http_io import audio

def qualify(binary):
    j=Requests(str(Path(binary).resolve()));client=None
    try:
        j.start()
        j.admit('Seed owned native context',topic=1)
        j.wait(lambda:j.has('Initial goal turn delivered.',1));j.idle();j.stop()
        root=j.root;binding_file=root/'live-result.json'
        binding_file.write_text(json.dumps({'schema':'telecodex.interaction-asr/v1',
            'provider':'live-result','models':['gpt-live-transcribe'],
            'cache_root':str(root/'live-cache'),'streaming_cache_root':str(root/'prepared')}))
        binding_file.chmod(0o600)
        command=[sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/interaction_asr.py'),'--binding',str(binding_file)]
        j.config.write_text(j.config.read_text()+j.target_config+'\n[voice]\ntranscriber_label="synthetic/base-must-not-run"\ntranscription_command=["/usr/bin/false"]\ntimeout_seconds=20\n[voice.transcription_profiles.openai-live]\ntranscriber_label="OpenAI gpt-live-transcribe; same live session, no second ASR"\ntranscription_command='+json.dumps(command)+'\ncompleted_transcription_command='+json.dumps(command+['--completed-only'])+'\n')
        j.start();j.wait_control_socket(j.socket);j.routing=True
        config={'receiver_config':str(j.config),'state_dir':str(root/'dashboard'),'origin':'https://example.test','bot_id':123}
        provider=Provider(config);client=TestClient(create_app(config,provider,lambda raw,bot:int(raw)),base_url=config['origin'])
        headers={'origin':config['origin']}
        headers['authorization']='Bearer '+client.post('/api/session',json={'init_data':'100'},headers=headers).json()['session_token']
        page=client.get('/api/interaction',headers=headers).json();headers['x-dashboard-csrf']=page['csrf'];binding=page['binding']
        ident=str(uuid.uuid4());data=audio();pcm=data[44:];text='Use exactly the live words, including this correction.'
        save_prepared(root/'prepared',ident,binding,pcm,{'text':text,'final':True,'model':'gpt-live-transcribe','pcm_sha256':hashlib.sha256(pcm).hexdigest(),'audio_millis':len(pcm)*1000//32000})
        upload={**headers,'content-type':'audio/wav','x-input-binding':binding,'x-input-id':ident,'x-audio-sha256':hashlib.sha256(data).hexdigest()}
        response=client.post('/api/interaction/voice/openai-live',content=data,headers=upload)
        assert response.status_code==200,response.text
        def status():return client.get('/api/interaction/inputs/'+ident,headers=headers).json()
        j.wait(lambda:status().get('phase')=='accepted')
        value=status();assert value['text']==text,value
        assert value['voice']['transcription_profile']=='openai-live'
        assert 'gpt-live-transcribe' in value['voice']['transcription']['configured_transcriber']
        repeated=client.post('/api/interaction/voice/openai-live',content=data,headers=upload)
        assert repeated.status_code==200 and not repeated.json()['new_input'],repeated.text
        assert status()['text']==text
        print('single live result -> actual native original: passed; base file recognizer disabled')
    finally:
        if client:client.close()
        j.close()

if __name__=='__main__':qualify(sys.argv[1])
