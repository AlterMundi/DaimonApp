#!/usr/bin/env python3
"""Real shipped editor/renderer + mounted authenticated API, synthetic actors.

One temporary state root/server/browser,120s cap, no provider/model/device calls.
Set PLAYWRIGHT_MODULE and CHROMIUM_EXECUTABLE to the existing browser tools.
"""
import asyncio
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
        app=FastAPI();public=Path(__file__).resolve().parents[1]/'dashboard/web'
        class Owner:
            def authorized(self,human):return human in (100,200)
        async def authorize(request):
            actor=request.headers.get('x-test-actor')
            if actor not in ('100','200'):raise HTTPException(401,'Synthetic test actor required')
            return {'human':int(actor),'scope':'interaction_only','csrf':'test-action'}
        sock=socket.socket();sock.bind(('127.0.0.1',0));origin='http://127.0.0.1:'+str(sock.getsockname()[1])
        install(app,{'state_dir':root,'voice_studio':{'voices':['cedar','marin']},'openai_live':{'enabled':True,'session_options':{'audio':{'output':{'voice':'cedar'}}}}},Owner(),authorize,[origin])
        @app.get('/assets/{name}')
        def asset(name:str):
            if name not in ('avatar-workshop.js','voice-studio.js','style.css'):raise HTTPException(404)
            return FileResponse(public/name)
        @app.get('/')
        def shell():
            return HTMLResponse('''<!doctype html><html><head><link rel="stylesheet" href="assets/style.css"><script src="assets/voice-studio.js"></script><script src="assets/avatar-workshop.js"></script><script src="fixture.js" defer></script></head><body style="--dm-background:#101820;--dm-surface:#17212b;--dm-text:#f3f1e6;--dm-accent:#82d5e7"><section id="conversation-companion"><pre>PREVIOUS AVATAR</pre></section><button id="avatar-workshop-open" hidden>Personalize avatar</button><button id="avatar-workshop-pause" hidden>Pause avatar</button><p id="avatar-workshop-status"></p></body></html>''')
        @app.get('/fixture.js')
        def fixture():
            from fastapi.responses import Response
            return Response('''window.testActor='100';window.testAvatar=AvatarWorkshopUI.mount({headers:()=>({'X-Test-Actor':testActor}),api:async(path,body)=>{if(window.testRejectActivation&&body?.action==='activate')throw Error('Synthetic activation refusal');const r=await fetch('/api/'+path,{method:body?'POST':'GET',headers:{'X-Test-Actor':testActor,'X-Dashboard-CSRF':'test-action','Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});const v=await r.json();if(!r.ok)throw Error(v.detail||'Failed');if(path==='interaction/avatars/voice/previews'&&body)window.testPreviewReplies=(window.testPreviewReplies||0)+1;if(path==='interaction/avatars/voice'&&body){window.testVoicePosts=(window.testVoicePosts||0)+1;if(window.testLoseVoiceSaveAck&&body.action==='save'){window.testLoseVoiceSaveAck=false;throw Error('Synthetic lost save acknowledgement');}}return v;}});if(!new URLSearchParams(location.search).has('defer_bind'))testAvatar.bind('actor100');''',media_type='text/javascript')
        server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='off'))
        thread=threading.Thread(target=lambda:asyncio.run(server.serve(sockets=[sock])),daemon=True);thread.start()
        try:
            subprocess.run(['node',str(Path(__file__).with_suffix('.js')),origin],check=True,timeout=120)
        finally:
            server.should_exit=True;thread.join(timeout=5);sock.close()
            if thread.is_alive():raise RuntimeError('Workshop browser fixture did not stop')

if __name__=='__main__':qualify()
