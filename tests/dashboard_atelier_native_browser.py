"""Shipped parent/editor -> actual owned native controller, on disposable TLS."""
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
sys.path.insert(0, str(Path(__file__).resolve().parents[1])); sys.path.insert(0, str(Path(__file__).resolve().parent))
from fastapi.responses import HTMLResponse, Response
import uvicorn
from dashboard.app import create_app
from dashboard.provider import Provider
from dashboard.atelier_native import digest
from dashboard_atelier_native_io import NumericalPeer


def qualify(binary):
    j = NumericalPeer(str(Path(binary).resolve())); server = None
    try:
        j.start()
        for topic in (7, 8, 1):
            j.admit('Seed existing owned context', topic=topic)
            j.wait(lambda: j.has('Initial goal turn delivered.', topic)); j.idle()
        j.stop(); retained = j.root / 'retained'; retained.mkdir(mode=0o700)
        j.config.write_text(j.config.read_text() + '\n[interaction.artifact_store]\ndirectory=' + json.dumps(str(retained)) +
                            '\nmax_file_bytes=8388608\nmax_total_bytes=67108864\n' + j.target_config)
        j.start(); j.wait_control_socket(j.socket); j.routing = True; j.messages.clear()
        sock = socket.socket(); sock.bind(('127.0.0.1', 0)); origin = 'https://127.0.0.1:' + str(sock.getsockname()[1])
        cert, key = j.root / 'cert.pem', j.root / 'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-keyout', str(key), '-out', str(cert), '-subj', '/CN=localhost'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        config = {'receiver_config': str(j.config), 'state_dir': str(j.root / 'dashboard'), 'origin': origin, 'prefix': '/sessions', 'bot_id': 123}
        provider = Provider(config); app = create_app(config, provider, lambda raw, bot: int(raw))
        @app.get('/fixture')
        def shell():
            return HTMLResponse('<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/assets/style.css"><script src="/assets/atelier-workshop/host.js" defer></script><script src="/fixture.js" defer></script><button id="atelier-workshop-open" hidden>3D workshop</button><p id="atelier-workshop-status"></p>')
        @app.get('/fixture.js')
        def script():
            return Response("""window.fixture={token:null,csrf:null};fixture.headers=()=>({Authorization:'Bearer '+fixture.token});fixture.api=async(route,body)=>{const r=await fetch('/api/'+route,{method:body?'POST':'GET',headers:{...fixture.headers(),...(body?{'Content-Type':'application/json','X-Dashboard-CSRF':fixture.csrf}:{})},...(body?{body:JSON.stringify(body)}:{})});const v=await r.json();if(!r.ok)throw Error(v.detail||'Unavailable');return v;};fixture.ui=AtelierWorkshopUI.mount({api:fixture.api,headers:fixture.headers});fixture.ready=(async()=>{const r=await fetch('/api/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({init_data:'100'})});fixture.token=(await r.json()).session_token;fixture.csrf=(await fixture.api('state')).csrf;fixture.ui.bind('synthetic-account100');})();""", media_type='text/javascript')
        @app.get('/fixture/target')
        def target():
            row = next(r for r in provider.session_workspace()['sessions'] if r['audio_key'] == '100:7')
            return {'key': digest([row['id'], row['destination']])}
        @app.get('/fixture/complete')
        def complete():
            j.wait(lambda: j.instructions(7) and j.instructions(7)[0][1] == 'accepted')
            j.answer_worker(7, 'A numerical synthetic peer returned an editable proposal.')
            return {'synthetic': True}
        server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off', ssl_keyfile=str(key), ssl_certfile=str(cert)))
        thread = threading.Thread(target=lambda: asyncio.run(server.serve(sockets=[sock])), daemon=True); thread.start()
        try:
            subprocess.run(['node', str(Path(__file__).with_suffix('.mjs')), origin], check=True, timeout=180)
            assert j.row('SELECT count(*) FROM conversation_inputs') == [(1,)]
            assert not j.instructions(8) and not j.messages
        finally:
            server.should_exit = True; thread.join(timeout=5); sock.close()
            assert not thread.is_alive(), 'Disposable server did not stop'
    finally:
        j.close()


if __name__ == '__main__': qualify(sys.argv[1])
