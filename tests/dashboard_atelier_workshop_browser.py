"""Real App sessions, middleware, SQLite and shipped 3D editor, on loopback TLS.

Disposable synthetic human sessions; no native/model/provider calls or real
Home credentials. TLS bypass applies only to the isolated browser context.
"""
import asyncio
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
from fastapi.responses import HTMLResponse,Response
import uvicorn
from dashboard.app import create_app
from dashboard_io import Receiver


def qualify():
    with tempfile.TemporaryDirectory(prefix='atelier-account-browser-') as root:
        root=Path(root);sock=socket.socket();sock.bind(('127.0.0.1',0));origin='https://127.0.0.1:'+str(sock.getsockname()[1]);cert=root/'cert.pem';key=root/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',str(key),'-out',str(cert),'-subj','/CN=localhost'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        class Owner(Receiver):
            def authorized(self,human):return self.allowed and human in (100,200)
        owner=Owner();state=root/'state';state.mkdir(mode=0o700);app=create_app({'state_dir':str(state),'origin':origin,'prefix':'/sessions','bot_id':123},owner,lambda raw,bot:int(raw))
        @app.get('/fixture')
        def shell():
            return HTMLResponse('''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/assets/style.css"><script src="/assets/atelier-workshop/host.js" defer></script><script src="/fixture.js" defer></script><button id="atelier-workshop-open" hidden>3D workshop</button><p id="atelier-workshop-status"></p>''')
        @app.get('/fixture.js')
        def script():
            return Response('''window.fixture={token:null,csrf:null,posts:0,loseAck:false};fixture.headers=()=>({Authorization:'Bearer '+fixture.token});fixture.api=async(route,body)=>{const r=await fetch('/api/'+route,{method:body?'POST':'GET',headers:{...fixture.headers(),...(body?{'Content-Type':'application/json','X-Dashboard-CSRF':fixture.csrf}:{})},...(body?{body:JSON.stringify(body)}:{})});const v=await r.json();if(!r.ok)throw Error(v.detail||'Unavailable');if(body?.action==='save-request'){fixture.posts++;if(fixture.loseAck){fixture.loseAck=false;throw Error('Confirmation unavailable; check the saved request');}}return v;};fixture.ui=AtelierWorkshopUI.mount({api:fixture.api,headers:fixture.headers});fixture.login=async human=>{fixture.ui.reset();const r=await fetch('/api/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({init_data:String(human)})});const v=await r.json();fixture.token=v.session_token;fixture.csrf=(await fixture.api('state')).csrf;fixture.ui.bind('synthetic-account-'+human);};''',media_type='text/javascript')
        @app.get('/fixture/revoke')
        def revoke():owner.allowed=False;return {'revoked':True}
        server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='off',ssl_keyfile=str(key),ssl_certfile=str(cert)))
        thread=threading.Thread(target=lambda:asyncio.run(server.serve(sockets=[sock])),daemon=True);thread.start()
        try:
            subprocess.run(['node',str(Path(__file__).with_suffix('.mjs')),origin],check=True,timeout=180)
            assert owner.calls==[]
        finally:
            server.should_exit=True;thread.join(timeout=5);sock.close()
            if thread.is_alive():raise RuntimeError('Atelier browser fixture did not stop')

if __name__=='__main__':qualify()
