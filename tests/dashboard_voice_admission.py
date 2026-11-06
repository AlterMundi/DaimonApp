"""Real OS process exclusion and ASGI voice startup/cleanup; no model calls."""
import asyncio
import fcntl
import multiprocessing
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from dashboard.voice_admission import (HEADER, SCOPE_KEY, VoiceAdmission,
    VoiceAdmissionMiddleware, hold_voice_task, maintenance_guard, retained_voice, admit_voice, admission_failure)


def own_voice(root, pipe):
    claim=VoiceAdmission(root).claim()
    try:
        pipe.send('held')
        pipe.poll(8) and pipe.recv()
    finally:
        claim.release();pipe.close()


class Admission(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.admission=VoiceAdmission(self.root)

    def process(self):
        context=multiprocessing.get_context('spawn');parent,child=context.Pipe()
        process=context.Process(target=own_voice,args=(str(self.root),child));process.start();child.close()
        def stop():
            if process.is_alive():process.kill()
            process.join(8)
        self.addCleanup(stop)
        self.addCleanup(parent.close)
        self.assertTrue(parent.poll(8));self.assertEqual(parent.recv(),'held')
        return process,parent

    def test_capture_in_another_process_defers_maintenance_then_releases(self):
        process,pipe=self.process()
        with self.assertRaises(BlockingIOError):
            with maintenance_guard(self.root):pass
        pipe.send('close');process.join(8);self.assertEqual(process.exitcode,0)
        with maintenance_guard(self.root) as header:self.assertEqual(header.header,self.admission.header)

    def test_process_death_releases_without_stale_lease_file_reset(self):
        process,pipe=self.process();process.terminate();process.join(8)
        with maintenance_guard(self.root):pass
        self.assertEqual(VoiceAdmission(self.root).header,self.admission.header)

    def test_wrong_state_domain_and_replaced_inode_cannot_claim_the_running_header(self):
        other=VoiceAdmission(self.root/'other')
        with maintenance_guard(self.root/'other') as header:self.assertNotEqual(header.header,self.admission.header)
        lock=self.root/'voice-admission/.lock';lock.rename(lock.with_name('old'))
        VoiceAdmission(self.root)
        with self.assertRaisesRegex(ValueError,'lock changed'):self.admission.claim()

    def test_unsafe_or_missing_state_is_not_created_by_maintenance(self):
        with self.assertRaises(FileNotFoundError):
            with maintenance_guard(self.root/'absent'):pass
        self.assertFalse((self.root/'absent').exists())
        lock=self.root/'voice-admission/.lock';lock.write_text('not a lock')
        with self.assertRaises(ValueError):self.admission.claim()
        self.assertEqual(lock.read_text(),'not a lock')

    def test_all_voice_transports_refuse_without_entering_handler_and_text_still_works(self):
        app=FastAPI();entered=[]
        async def voice(socket:WebSocket):
            await socket.accept();await socket.receive_text()
            try:admit_voice(socket.scope)
            except ValueError as error:
                await socket.send_json({'message':admission_failure(error)});await socket.close();return
            entered.append(socket.url.path);await socket.send_json({'type':'ready'})
            await socket.receive_text();await socket.close()
        for mode in ('native','codex','gpt-live','live','activity'):
            app.add_api_websocket_route('/api/interaction/voice/'+mode,voice)
        @app.get('/text')
        def text():return {'ok':True}
        app.add_middleware(VoiceAdmissionMiddleware,admission=self.admission)
        with TestClient(app) as client:
            with maintenance_guard(self.root):
                self.assertEqual(client.get('/text').json(),{'ok':True})
                for mode in ('native','codex','gpt-live','live','activity'):
                    with client.websocket_connect('/api/interaction/voice/'+mode) as socket:
                        socket.send_text('authorized')
                        self.assertIn('server update',socket.receive_json()['message'])
                self.assertEqual(entered,[])
            with client.websocket_connect('/api/interaction/voice/native') as socket:
                socket.send_text('authorized')
                self.assertEqual(socket.receive_json()['type'],'ready')
                with self.assertRaises(BlockingIOError):
                    with maintenance_guard(self.root):pass
                socket.send_text('close')
        with maintenance_guard(self.root):pass

    def test_unadmitted_transport_cannot_hold_the_update_fence(self):
        app=FastAPI()
        @app.websocket('/api/interaction/voice/native')
        async def pending(socket:WebSocket):
            await socket.accept();await socket.send_json({'type':'metadata_required'})
            await socket.receive_text();await socket.close()
        app.add_middleware(VoiceAdmissionMiddleware,admission=self.admission)
        with TestClient(app) as client:
            with client.websocket_connect('/api/interaction/voice/native') as socket:
                self.assertEqual(socket.receive_json()['type'],'metadata_required')
                with maintenance_guard(self.root):pass
                socket.send_text('close without admission')

    def test_canceled_handler_keeps_admission_until_owned_late_cleanup_and_callbacks(self):
        async def scenario():
            claim=self.admission.claim();scope={SCOPE_KEY:claim}
            finished=asyncio.Event();closed=[]
            task=asyncio.create_task(finished.wait());hold_voice_task(scope,task)
            task.add_done_callback(lambda _:closed.append('resource_closed'))
            claim.release()  # ASGI handler exits while its shielded owner is alive.
            with self.assertRaises(BlockingIOError):
                with maintenance_guard(self.root):pass
            finished.set();await task;await asyncio.sleep(0)
            self.assertEqual(closed,['resource_closed'])
            with maintenance_guard(self.root):pass
        asyncio.run(scenario())

    def test_actual_transport_exit_waits_for_its_registered_late_resource_close(self):
        app=FastAPI();finish=threading.Event();closed=threading.Event()
        @app.websocket('/api/interaction/voice/native')
        async def owned(socket:WebSocket):
            await socket.accept();admit_voice(socket.scope)
            opening=asyncio.create_task(asyncio.to_thread(finish.wait,8))
            hold_voice_task(socket.scope,opening)
            opening.add_done_callback(lambda _:closed.set())
            await socket.send_json({'type':'ready'})
            await socket.receive_text();await socket.close()
        @app.get('/tick')
        async def tick():await asyncio.sleep(0);return {'ok':True}
        app.add_middleware(VoiceAdmissionMiddleware,admission=self.admission)
        try:
            with TestClient(app) as client:
                with client.websocket_connect('/api/interaction/voice/native') as socket:
                    self.assertEqual(socket.receive_json()['type'],'ready');socket.send_text('end transport')
                with self.assertRaises(BlockingIOError):
                    with maintenance_guard(self.root):pass
                finish.set();self.assertTrue(closed.wait(8));client.get('/tick')
                with maintenance_guard(self.root):pass
        finally:finish.set()

    def test_owned_blocking_setup_retains_guard_after_handler_cancellation(self):
        claim=self.admission.claim();scope={SCOPE_KEY:claim}
        with retained_voice(scope):
            claim.release()
            with self.assertRaises(BlockingIOError):
                with maintenance_guard(self.root):pass
        with maintenance_guard(self.root):pass
        with self.assertRaises(ValueError):
            with retained_voice(scope):pass
    def server(self, header):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(inner):
                inner.send_response(200)
                if header:inner.send_header(HEADER,header)
                inner.end_headers();inner.wfile.write(b'{"ok":true}')
            def log_message(*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def close():server.shutdown();server.server_close();thread.join(5)
        self.addCleanup(close)
        return 'http://127.0.0.1:'+str(server.server_port)+'/health'

    def command(self, url, code, seconds=5):
        config=self.root/'config.toml';config.write_text('state_dir = '+json.dumps(str(self.root))+'\n');config.chmod(0o600)
        script=Path(__file__).resolve().parents[1]/'scripts/interaction_web_maintenance.py'
        return subprocess.run([sys.executable,str(script),'--config',str(config),
            '--health-url',url,'--seconds',str(seconds),'--',sys.executable,'-c',code],
            capture_output=True,text=True,timeout=10)

    def test_actual_operator_exec_inherits_exclusion_and_releases_on_success(self):
        code="from dashboard.voice_admission import VoiceAdmission\n"+"try: VoiceAdmission("+repr(str(self.root))+").claim()\nexcept BlockingIOError: print('fenced')\nelse: raise AssertionError('operator lost fence')"
        result=self.command(self.server(self.admission.header),code)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),'fenced')
        with maintenance_guard(self.root):pass

    def test_operator_refuses_active_voice_and_old_or_wrong_reader_without_effect(self):
        target=self.root/'should-not-exist';code='from pathlib import Path;Path('+repr(str(target))+').write_text("effect")'
        claim=self.admission.claim()
        try:self.assertEqual(self.command(self.server(self.admission.header),code).returncode,75)
        finally:claim.release()
        for header in (None,VoiceAdmission(self.root/'other').header):
            result=self.command(self.server(header),code)
            self.assertEqual(result.returncode,78,result.stderr)
        self.assertFalse(target.exists())

    def test_operator_deadline_retains_unknown_receipt_and_does_not_retry(self):
        target=self.root/'owned-intent'
        code='from pathlib import Path;import time;Path('+repr(str(target))+').write_text("intent");time.sleep(10)'
        result=self.command(self.server(self.admission.header),code,seconds=1)
        self.assertEqual(result.returncode,124,result.stderr);self.assertEqual(target.read_text(),'intent')
        with maintenance_guard(self.root):pass


if __name__=='__main__':unittest.main()
