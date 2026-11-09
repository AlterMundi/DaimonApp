#!/usr/bin/env python3
"""Recover an actual retained final's PNG through owner/native/HTTP, no model replay."""
import sys,json,hashlib
from pathlib import Path
from artifact_return_io import ArtifactRouting,Provider,create_app,TestClient


def run(binary):
    j=ArtifactRouting(str(Path(binary).resolve()));client=None
    try:
        j.config.write_text(j.config.read_text()+j.target_config)
        j.start();j.wait_control_socket(j.socket);j.routing=True
        binding=j.read('input','list','0','before')['result']['binding']
        j.submit(binding,'Synthetic image request; no actual model')
        j.wait(lambda:bool(j.web_turn))
        j.broadcast(j.web_thread,'item/completed',{'turnId':j.web_turn,'item':{'id':'image-final','type':'agentMessage','phase':'final_answer','text':'Generated image in this execution output.'}})
        j.broadcast(j.web_thread,'turn/completed',{'turn':{'id':j.web_turn,'status':'completed'}});j.idle()
        assert j.row('SELECT count(*) FROM interaction_artifact_jobs')==[(0,)]
        before_turns=j.row('SELECT count(*) FROM turns')
        output=j.row("SELECT local_turn,native_thread,native_turn,item_id FROM interaction_native_messages WHERE item_id='image-final'")[0]
        j.stop();retained=j.root/'retained';retained.mkdir(mode=0o700)
        j.config.write_text(j.config.read_text()+f'\n[interaction.artifact_store]\ndirectory={json.dumps(str(retained))}\nmax_file_bytes=2048\nmax_total_bytes=8192\n')
        j.start();j.wait_control_socket(j.socket)
        binding=j.read('input','list','0','before')['result']['binding'];png=j.expected['image.png']
        body={'binding':binding,'local_turn':output[0],'directory':str(j.artifact_out),'output':dict(zip(('native','turn','item'),output[1:])), 'files':{'image.png':hashlib.sha256(png).hexdigest()}}
        def recover(value,ok=True):return j.read('input','artifacts','recover',json.dumps(value),ok=ok)
        recover({**body,'binding':'f'*64},False)
        recover({**body,'files':{'escape.txt':hashlib.sha256(b'PRIVATE UNRELATED BYTES').hexdigest()}},False)
        recover({**body,'files':{'image.png':'0'*64}},False)
        assert j.row('SELECT count(*) FROM interaction_artifact_jobs')==[(0,)]
        assert recover(body)['result']['state']=='copy_recovery_registered'
        j.wait(lambda:any(x['available'] for x in j.read('presentation','artifacts','list')['result']['items']))
        recover(body)
        assert j.row('SELECT count(*) FROM interaction_artifact_jobs')==[(1,)]
        assert j.row('SELECT count(*) FROM turns')==before_turns
        files=j.read('presentation','artifacts','list')['result']['items'];assert len(files)==1 and files[0]['name']=='image.png',files
        config={'receiver_config':str(j.config),'state_dir':str(j.root/'dashboard'),'origin':'https://example.test','bot_id':123}
        provider=Provider(config);client=TestClient(create_app(config,provider,lambda raw,bot:int(raw)),base_url=config['origin'])
        token=client.post('/api/session',json={'init_data':'100'},headers={'origin':config['origin']}).json()['session_token']
        path='/api/interaction/artifacts/'+files[0]['id']
        response=client.get(path,headers={'authorization':'Bearer '+token});assert response.status_code==200,response.text
        assert response.content==png and response.headers['x-artifact-sha256']==body['files']['image.png']
        assert client.get(path).status_code in (401,403)
        assert j.row('SELECT count(*) FROM turns')==before_turns
        print('PASS explicit retained PNG recovery: real native owner + completed final, hash/path/symlink refusals, one durable copy job across duplicate request, exact authenticated HTTP image, no native replay or provider call.')
    finally:
        if client:client.close()
        j.close()

if __name__=='__main__':run(sys.argv[1])
