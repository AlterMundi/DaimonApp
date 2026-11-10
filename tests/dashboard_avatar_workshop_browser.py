#!/usr/bin/env python3
"""Real shipped editor/renderer + mounted authenticated API, synthetic actors.

One temporary state root/server/browser,120s cap, no provider/model/device calls.
Set PLAYWRIGHT_MODULE and CHROMIUM_EXECUTABLE to the existing browser tools.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI,HTTPException
from fastapi.responses import HTMLResponse,FileResponse
import uvicorn
from dashboard.avatar_workshop_api import install


def qualify():
    with tempfile.TemporaryDirectory(prefix='avatar-browser-') as root:
        import dashboard.avatar_workshop_api as mounted_api
        app=FastAPI();public=Path(mounted_api.__file__).resolve().parent/'web'
        workshop_root=Path(os.environ.get('QUALIFICATION_WORKSHOP_ROOT',str(public/'avatar-workshop'))).resolve()
        class Owner:
            human=100
            def authorized(self,human):return human in (100,200)
        async def authorize(request):
            actor=request.headers.get('x-test-actor')
            if actor not in ('100','200'):raise HTTPException(401,'Synthetic test actor required')
            return {'human':int(actor),'scope':'interaction_only','csrf':'test-action'}
        sock=socket.socket();sock.bind(('127.0.0.1',0));origin='http://127.0.0.1:'+str(sock.getsockname()[1])
        config={'state_dir':root,'voice_studio':{'voices':['cedar','marin']},'openai_live':{'enabled':True,'session_options':{'audio':{'output':{'voice':'cedar'}}}}}
        mission_host=None
        if os.environ.get('SCHOOL_SOURCE'):
            import hashlib,shutil
            school=Path(os.environ['SCHOOL_SOURCE']).resolve()
            selected=Path(root)/'selected-school-source';selected.mkdir(mode=0o700);rows=[]
            for directory in ('scripts','curriculum'):
                for original in sorted((school/directory).glob('*')):
                    if original.suffix not in ('.py','.json'):continue
                    relative=original.relative_to(school);target=selected/relative
                    target.parent.mkdir(exist_ok=True,mode=0o700);shutil.copyfile(original,target);target.chmod(0o600)
                    raw=target.read_bytes();rows.append({'archive_path':relative.as_posix(),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
            manifest=json.dumps({'files':rows},sort_keys=True).encode();(selected/'MANIFEST.json').write_bytes(manifest)
            sys.path.insert(0,str(selected/'scripts'))
            from learning_engine import Ledger
            ledger=Ledger(Path(root)/'school')
            fixture=json.loads((school/'docs/examples/ascii-mission3.synthetic.json').read_text())
            context=fixture['request']
            ledger.put_profile({'id':context['learner_id'],'name':'Synthetic browser participant',
                'synthetic':True,'participation_authorized':False,'daimon_status':'created'})
            ledger.close()
            tools=Path(root)/'bindings.json';tools.write_text(json.dumps({'learner_id':context['learner_id'],'companion_ref':context['daimon_ref']}));tools.chmod(0o600)
            descriptor=dict(schema='school-creativity.app-selection/v1',active=True,actor=100,
                human_ref='human:synthetic:own',application_id=context['space_ref'],tool_bindings=str(tools),request=context)
            descriptor_raw=json.dumps(descriptor).encode();entry=Path(root)/'mission.json';entry.write_bytes(descriptor_raw);entry.chmod(0o600)
            config.update(application_id=context['space_ref'],shared_auth={'human_ref':'human:synthetic:own'},
                school_mission={'selection':str(entry),'selection_sha256':hashlib.sha256(descriptor_raw).hexdigest(),
                    'source':{'root':str(selected),'state':str(ledger.state),'manifest_sha256':hashlib.sha256(manifest).hexdigest()}})
            from dashboard.school_mission_host import compose
            mission_host=compose(config,Owner())
        install(app,config,Owner(),authorize,[origin],mission_host=mission_host)
        if workshop_root != (public/'avatar-workshop').resolve():
            from dashboard import shared_asset_release as releases
            from dashboard.avatar_workshop_provenance import receiving_hashes
            metadata=json.loads((workshop_root/'PROVENANCE.json').read_text()); assert receiving_hashes(workshop_root)==metadata['receiving_hashes']
            transfer=releases.package(workshop_root,metadata['source_revision']); target=Path(root)/'shared-app-assets/avatar-workshop'
            staged=releases.prepare(target,transfer,public/'avatar-workshop');releases.activate(target,staged['release'],None,public/'avatar-workshop')
        @app.get('/assets/{name}')
        def asset(name:str):
            if name not in ('avatar-workshop.js','voice-studio.js','voice-mode.js','companion.js','style.css','webrtc-native-audio.js','voice-output-pcm.js'):raise HTTPException(404)
            return FileResponse(public/name)
        @app.get('/')
        def shell():
            return HTMLResponse('''<!doctype html><html><head><link rel="stylesheet" href="assets/style.css"><script src="assets/voice-mode.js"></script><script src="assets/voice-studio.js"></script><script src="assets/avatar-workshop.js"></script><script src="fixture.js" defer></script></head><body style="--dm-background:#101820;--dm-surface:#17212b;--dm-text:#f3f1e6;--dm-accent:#82d5e7"><section id="conversation-companion"><pre>PREVIOUS AVATAR</pre></section><button id="avatar-workshop-open" hidden>Personalize avatar</button><button id="avatar-workshop-pause" hidden>Pause avatar</button><p id="avatar-workshop-status"></p></body></html>''')
        @app.get('/fixture.js')
        def fixture():
            from fastapi.responses import Response
            return Response('''window.testActor='100';window.testAvatar=AvatarWorkshopUI.mount({headers:()=>({'X-Test-Actor':testActor}),api:async(path,body)=>{if(window.testRejectActivation&&body?.action==='activate')throw Error('Synthetic activation refusal');const r=await fetch('/api/'+path,{method:body?'POST':'GET',headers:{'X-Test-Actor':testActor,'X-Dashboard-CSRF':'test-action','Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});const v=await r.json();if(!r.ok)throw Error(v.detail||'Failed');if(path==='interaction/avatars/voice/previews'&&body)window.testPreviewReplies=(window.testPreviewReplies||0)+1;if(path==='interaction/avatars/voice'&&body){window.testVoicePosts=(window.testVoicePosts||0)+1;if(window.testLoseVoiceSaveAck&&body.action==='save'){window.testLoseVoiceSaveAck=false;throw Error('Synthetic lost save acknowledgement');}}return v;}});if(!new URLSearchParams(location.search).has('defer_bind'))testAvatar.bind('actor100');''',media_type='text/javascript')
        server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='off'))
        thread=threading.Thread(target=lambda:asyncio.run(server.serve(sockets=[sock])),daemon=True);thread.start()
        try:
            subprocess.run(['node',str(Path(__file__).with_suffix('.js')),origin],check=True,timeout=120)
            subprocess.run(['node',str(Path(__file__).with_name('dashboard_avatar_import_capabilities_browser.cjs'))],check=True,timeout=120)
            if mission_host:
                from contextlib import closing
                with closing(Ledger(mission_host.state)) as checked:
                    assert checked.events(context['learner_id'])==[]
                    assert checked.profile(context['learner_id'])['participation_authorized'] is False
                    assert checked.report(context['learner_id'])['achieved_count']==0

        finally:
            server.should_exit=True;thread.join(timeout=5);sock.close()
            if thread.is_alive():raise RuntimeError('Workshop browser fixture did not stop')

if __name__=='__main__':qualify()
