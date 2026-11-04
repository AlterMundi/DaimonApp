#!/usr/bin/env python3
"""Opt-in real Core + wrapper heartbeat journey against a local Responses stand-in.
No real account/provider/Telegram. Uses temporary, test-owned native metadata.
"""
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from heartbeat_io import HeartbeatJourney

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.activity_indicator import Native


def file_sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)


def actual_rpc(client, method, params):
    # Test-owned client intentionally admits metadata creation; the production
    # observer method allowlist stays unchanged.
    client.sequence += 1
    ident = client.sequence
    client.send({'id': ident, 'method': method, 'params': params})
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        value = client.messages.get(timeout=1)
        if value.get('id') == ident:
            assert 'error' not in value, value
            return value['result']
    raise AssertionError('Native metadata RPC timed out')


class ActualJourney(HeartbeatJourney):
    def stop(self):
        if self.process:
            self.process.send_signal(signal.SIGINT)
            self.last_stdout, self.last_stderr = self.process.communicate(timeout=10)
            self.process = None


def qualify(binary, native_binary, *, busy=False, native_cli=False, reports=False):
    j = ActualJourney(str(Path(binary).resolve()))
    native = client = None
    native_log = None
    errors, requests = [], []
    original = batch = None
    pause_entered, pause_release = threading.Event(), threading.Event()
    busy_entered, busy_release = threading.Event(), threading.Event()
    def call(ident, operation, arguments):
        return {'type': 'response.output_item.done', 'item': {'type': 'function_call',
                'call_id': ident, 'name': 'interaction_controller',
                'arguments': json.dumps({'operation': operation, 'arguments': arguments})}}
    def message(text):
        return {'type': 'response.output_item.done', 'item': {'type': 'message',
                'id': str(uuid.uuid4()), 'role': 'assistant', 'phase': 'final_answer',
                'content': [{'type': 'output_text', 'text': text}]}}
    def plan(name, selector, scope):
        return {'input_ref': original, 'request_id': name,
                'expires_at': (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),
                'steps': [{'id': name, 'selector': selector, 'after': None,
                           'scope': scope, 'checkpoint': 'Exact native checkpoint', 'milestone': 'Ready'}]}
    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            nonlocal batch
            try:
                size = int(self.headers['content-length'])
                assert size <= 2 * 1024 * 1024 and len(requests) < 24
                value = json.loads(self.rfile.read(size))
                texts = list(strings(value.get('input', [])))
                outputs = {item.get('call_id'): item.get('output') for item in value.get('input', [])
                           if item.get('type') == 'function_call_output'}
                # Canonical internal tool results may carry a JSON text block.
                def output(ident):
                    raw = outputs[ident]
                    if isinstance(raw, list):
                        raw = ''.join(v.get('text', '') for v in raw)
                    return json.loads(raw)
                controller = next((t for t in reversed(texts) if t.startswith('[Interaction controller]')), None)
                packet = None
                for text in reversed(texts):
                    try:
                        candidate = json.loads(text)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(candidate, dict) and candidate.get('schema') == 'daimon.heartbeat-batch/v1':
                        packet = candidate
                        break
                if any(text == 'AFTER_PAUSE_CONTACT' or text.endswith('AFTER_PAUSE_CONTACT') for text in texts):
                    events, stage = [message('Ordinary contact preserved after pause.')], 'human-after-pause'
                elif (packet and batch is not None and packet['return_id'] != batch['return_id']
                      and packet['evidence']['offers'][0]['evidence']['reason'] != 'admission_attention_required'):
                    # Hold a real provider response while the shared owner
                    # control interrupts this exact newly reserved root.
                    stage = 'heartbeat-held-for-pause'
                    requests.append({'stage': stage, 'bytes': size, 'held': True})
                    pause_entered.set()
                    assert pause_release.wait(timeout=25), 'Pause control did not return'
                    events = [message('Late cancelled fixture response.')]
                elif (busy and not controller and not packet
                      and any(text == 'BUSY_NATIVE_WORKER' for text in texts)):
                    stage = 'ordinary-busy-worker'
                    requests.append({'stage': stage, 'bytes': size, 'held': True})
                    busy_entered.set()
                    assert busy_release.wait(timeout=120), 'Busy native worker was not released'
                    events = [message('Ordinary native work finished.')]
                elif (not controller and not packet
                        and not any('QUALIFY_NATIVE_HEARTBEAT' in text for text in texts)
                        and any(text == 'QUALIFY_NATIVE_BOOTSTRAP' for text in texts)):
                    events, stage = [message('Fixture native metadata materialized.')], 'bootstrap'
                elif controller:
                    instruction = re.search(r'^Current instruction: (.+)$', controller, re.M).group(1)
                    addressed = json.loads(re.search(r'^Addressed requests: (.+)$', controller, re.M).group(1))
                    events = [message('Native worker checkpoint.\n<daimon-result>'+json.dumps({
                        'requests': addressed, 'covered': [instruction], 'completed': addressed})+'</daimon-result>')]
                    stage = 'worker'
                elif packet:
                    batch = packet
                    prefix = 'hb-' + packet['return_id'].rsplit(':', 1)[-1]
                    read_id, declare_id, advance_id, reviewed_id = [prefix+'-'+kind for kind in ('read', 'declare', 'advance', 'reviewed')]
                    report = next((offer for offer in packet['evidence']['offers']
                                   if offer['key'].startswith('report:')), None)
                    report_read_id = prefix + '-owned-report'
                    if report and report_read_id not in outputs:
                        reader = report['evidence']['reader']
                        events = [call(report_read_id, reader['operation'], {
                            **reader['arguments'], 'return_id': packet['return_id']})]
                        stage = 'heartbeat-owned-report-read'
                    elif report and 'OWNED_REPORT_DELTA' not in output(report_read_id).get('text', ''):
                        raise AssertionError('Owned report fields were not delivered through exact source reader')
                    elif reviewed_id in outputs:
                        assert output(reviewed_id).get('reviewed') is True, output(reviewed_id)
                        events = [message('Native heartbeat read the checkpoint and selected the verification; retained outcomes remain separate.')]
                        stage = 'heartbeat-final'
                    elif advance_id in outputs:
                        events = [call(reviewed_id, 'heartbeat_reported', {
                            'return_id': packet['return_id'], 'revision': packet['evidence']['revision']})]
                        stage = 'heartbeat-review'
                    elif declare_id in outputs:
                        assert output(read_id)['text'].startswith('Native worker checkpoint.'), output(read_id)
                        selected = output(declare_id)
                        events = [call(advance_id, 'workflow_advance', {
                            'workflow': selected['id'], 'revision': selected['revision']})]
                        stage = 'heartbeat-advance'
                    elif read_id in outputs:
                        selected = output(read_id)
                        assert selected['steps'][0]['phase'] == 'retained_unsent', selected
                        events = [call(advance_id, 'workflow_advance', {
                            'workflow': selected['id'], 'revision': selected['revision']})]
                        stage = 'heartbeat-recover-known-unsent'
                    else:
                        offer = packet['evidence']['offers'][0]['evidence']
                        reader = offer['reader']
                        events = [call(read_id, reader['operation'], reader['arguments'])]
                        if offer['reason'] != 'admission_attention_required':
                            events.append(call(declare_id, 'workflow_declare', plan('verify-native', 't8',
                                'Verify the exact selected native checkpoint.')))
                        stage = 'heartbeat-read-declare'
                elif 'initial-advance' in outputs:
                    events, stage = [message('Native initial workflow selected; awaiting its result.')], 'initial-final'
                elif 'initial-declare' in outputs:
                    selected = output('initial-declare')
                    events = [call('initial-advance', 'workflow_advance', {
                        'workflow': selected['id'], 'revision': selected['revision']})]
                    stage = 'initial-advance'
                else:
                    assert any('QUALIFY_NATIVE_HEARTBEAT' in text for text in texts), 'Unexpected provider context'
                    events = [call('initial-declare', 'workflow_declare', plan('produce-native', 't7',
                        'Produce the selected native checkpoint.'))]
                    stage = 'initial-declare'
                if stage not in ('heartbeat-held-for-pause', 'ordinary-busy-worker'):
                    requests.append({'stage': stage, 'bytes': size, 'sha256': hashlib.sha256(json.dumps(value).encode()).hexdigest(),
                        'tools': len(value.get('tools', [])), 'instructions_hint': str(value.get('instructions', ''))[:100],
                        'last_input_types': [item.get('type', item.get('role')) for item in value.get('input', [])[-4:]],
                        'has_batch_marker': 'daimon.heartbeat-batch/v1' in json.dumps(value),
                        'session_id': self.headers.get('session_id')})
                events = [{'type': 'response.created', 'response': {'id': str(uuid.uuid4())}}] + events + [
                    {'type': 'response.completed', 'response': {'id': str(uuid.uuid4()), 'usage': {
                        'input_tokens': 10, 'output_tokens': 0, 'total_tokens': 10}}}]
                payload = ''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events).encode()
                self.send_response(200); self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Content-Length', str(len(payload))); self.end_headers(); self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                if not pause_entered.is_set():
                    errors.append('Unexpected local provider disconnect')
            except Exception as error:
                errors.append(repr(error)); self.send_error(500, 'Finite local fixture failed')
    provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    try:
        # Existing fixture seeds only synthetic local owners. Replace those
        # test-owned bindings with real fresh native threads before qualification.
        j.start()
        for topic in (7, 8, 1):
            j.admit('Seed fixture metadata', topic=topic)
            j.wait(lambda: j.has('Initial goal turn delivered.', topic)); j.idle()
        j.stop()
        native_home = j.root/'actual-core'; native_home.mkdir()
        (native_home/'config.toml').write_text(f'''model="mock-model"
model_provider="mock_provider"
approval_policy="never"
sandbox_mode="read-only"
[features]
plugins=false
enable_request_compression=false
[model_providers.mock_provider]
name="Local finite fixture"
base_url="http://127.0.0.1:{provider.server_port}/v1"
wire_api="responses"
request_max_retries=0
stream_max_retries=0
requires_openai_auth=false
supports_websockets=false
''')
        with socket.socket() as address:
            address.bind(('127.0.0.1', 0)); port = address.getsockname()[1]
        native_log = (j.root/'actual-native.log').open('w+')
        native_command = [str(Path(native_binary).resolve())]
        if native_cli:
            native_command.append('app-server')
        native = subprocess.Popen([*native_command, '--listen', f'ws://127.0.0.1:{port}'],
            cwd=j.root, env={'PATH': os.environ['PATH'], 'HOME': str(j.root),
                'CODEX_HOME': str(native_home), 'RUST_LOG': 'warn'}, stdout=native_log, stderr=native_log)
        deadline = time.monotonic()+10
        while True:
            assert native.poll() is None, 'Actual native exited during startup'
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.2):
                    break
            except OSError:
                assert time.monotonic() < deadline
                time.sleep(.05)
        proxy = j.root/'codex'
        proxy.write_text(proxy.read_text().replace(str(j.native.server_address[1]), str(port)))
        client = Native(str(proxy))
        with sqlite3.connect(j.root/'state.sqlite') as db:
            # Let the wrapper create its integrating native thread with its
            # real dynamic-tool profile. Only workers use prepared metadata.
            db.execute('UPDATE sessions SET codex_thread_id=NULL,model=?,force_fresh_thread=1 WHERE thread_id=1', ('mock-model',))
            for topic in (7, 8):
                created = actual_rpc(client, 'thread/start', {'cwd': str(j.root),
                    'model': 'mock-model', 'approvalPolicy': 'never', 'sandbox': 'read-only'})
                # Core refuses resume before a first persisted native turn.
                # Materialize this isolated synthetic context through its real API.
                actual_rpc(client, 'turn/start', {'threadId': created['thread']['id'],
                    'input': [{'type': 'text', 'text': 'QUALIFY_NATIVE_BOOTSTRAP'}]})
                deadline = time.monotonic()+15
                while True:
                    observed = client.rpc('thread/read', {'threadId': created['thread']['id'], 'includeTurns': True})
                    turns = observed.get('thread', {}).get('turns', []) if observed else []
                    if turns and turns[-1]['status'] == 'completed':
                        break
                    assert time.monotonic() < deadline, 'Native bootstrap did not terminate'
                    time.sleep(.05)
                db.execute('UPDATE sessions SET codex_thread_id=?,model=?,force_fresh_thread=0 WHERE thread_id=?',
                           (created['thread']['id'], 'mock-model', topic))
        if busy:
            target = j.row('SELECT codex_thread_id FROM sessions WHERE thread_id=8')[0][0]
            actual_rpc(client, 'turn/start', {'threadId': target,
                'input': [{'type':'text','text':'BUSY_NATIVE_WORKER'}]})
            assert busy_entered.wait(timeout=10), 'Busy native task never reached its local provider'
        else:
            client.close(); client = None
        j.config.write_text(j.config.read_text().replace('[telegram]', '[telegram]\nenabled=false')
            .replace('default_model="fixture-model"', 'default_model="mock-model"') + j.target_config)
        j.start(); j.wait_control_socket(j.socket)
        binding = j.read('presentation', 'list', '0', '0')['result']['binding']
        original = str(uuid.uuid4())
        j.submit(binding, 'QUALIFY_NATIVE_HEARTBEAT: Produce a checkpoint and then verify it in the existing second session.', ident=original)
        j.wait(lambda: len(j.row('SELECT id FROM interaction_results')) == 1, seconds=45)
        j.idle()
        assert not errors, errors
        paused = j.read('heartbeat', 'pause')['result']
        expiry = int((datetime.now(timezone.utc)+timedelta(minutes=4)).timestamp()*1000)
        resources = {'contract_id': str(uuid.uuid4()), 'max_provider_attempts': 48 if busy else 24,
            'provider_attempts_per_execution': 6, 'max_request_bytes': 2*1024*1024,
            'execution_seconds': 60, 'expires_at_unix_ms': expiry}
        j.read('heartbeat', 'configure-resources', str(paused['generation']), json.dumps(resources))
        report_sources = []
        if reports:
            report_path = j.root/'learning-report.json'
            report_path.write_text(json.dumps({'clock': 1, 'offers': [{'delta': 'OWNED_REPORT_DELTA'}],
                'excluded': 'PRIVATE_REPORT_FIELD'}))
            report_sources = [{'id': 'learning', 'path': str(report_path), 'pointers': ['/offers']}]
        j.read('heartbeat', 'configure-producer', str(paused['generation']), json.dumps({
            'interval_seconds': 30, 'max_checks': 3, 'expires_at_unix_ms': expiry,
            'matrix_replies': False, 'workflows': True, **({'reports': report_sources} if reports else {})}))
        j.read('heartbeat', 'resume', str(paused['generation']))
        retained_child = None
        if busy:
            j.wait(lambda: j.row("SELECT i.id FROM interaction_instructions i JOIN sessions s ON s.id=i.session_id WHERE s.thread_id=8 AND i.phase='retained_unsent'"), seconds=75)
            retained_child = j.row("SELECT i.id FROM interaction_instructions i JOIN sessions s ON s.id=i.session_id WHERE s.thread_id=8 AND i.phase='retained_unsent'")[0][0]
            assert sum(r['stage']=='worker' for r in requests) == 1, requests
            busy_release.set()
        j.wait(lambda: len(j.row('SELECT id FROM interaction_results')) == 2, seconds=105 if busy else 75)
        if busy:
            assert j.row("SELECT i.id,i.phase FROM interaction_instructions i JOIN sessions s ON s.id=i.session_id WHERE s.thread_id=8") == [(retained_child,'accepted')]
            assert any(r['stage']=='heartbeat-recover-known-unsent' for r in requests)
        j.wait(lambda: any(r['stage']=='heartbeat-final' for r in requests), seconds=30)
        j.idle()
        j.wait(lambda: pause_entered.is_set(), seconds=75)
        status = j.read('heartbeat', 'pause')['result']
        pause_release.set()
        assert not errors, errors
        expected_reserved = 30 if busy else 18
        assert status['resources']['reserved_provider_attempts'] == expected_reserved, status
        assert any(o['state']=='terminal' and o['status']=='interrupted'
                   for o in status['cancellation_observations']), status
        j.idle()
        page = j.read('presentation', 'list', '0', '0')['result']
        assert any(i['preview'].startswith('Native heartbeat read the checkpoint') for i in page['items'])
        j.submit(page['binding'], 'AFTER_PAUSE_CONTACT')
        j.wait(lambda: any(r['stage']=='human-after-pause' for r in requests), seconds=30)
        j.idle()
        final = j.read('heartbeat', 'status')['result']
        assert final['admission_paused'] and final['resources']['reserved_provider_attempts'] == expected_reserved
        assert batch is not None and len(requests) <= 24, requests
        if reports:
            assert any(r['stage'] == 'heartbeat-owned-report-read' for r in requests)
        assert j.row('SELECT count(*) FROM conversation_inputs') == [(2,)]
        print(json.dumps({'result': 'PASS', 'native_sha256': file_sha256(native_binary),
            'native_entrypoint': 'complete-cli' if native_cli else 'standalone-app-server',
            'owned_report_read': reports,
            'requests': requests, 'reserved_attempts': expected_reserved, 'busy_known_unsent_recovered': busy, 'live_provider_calls': 0,
            'pause_observations': status['cancellation_observations'], 'ordinary_contact_after_pause': True,
            'evidence': 'Actual Core, local HTTP stand-in, real wrapper/controller/store, bounded root/child, source read/canonical report, exact active-root pause and subsequent ordinary contact. Not receiving/model/device acceptance.'}))
    finally:
        pause_release.set()
        busy_release.set()
        if client: client.close()
        j.stop()
        if native:
            native.terminate()
            try: native.wait(timeout=10)
            except subprocess.TimeoutExpired: native.kill(); native.wait(timeout=5)
        if sys.exc_info()[0]:
            print('Fixture errors:', errors, 'requests:', requests, file=sys.stderr)
            print('Wrapper tail:', (getattr(j, 'last_stdout', '')+getattr(j, 'last_stderr', ''))[-6000:], file=sys.stderr)
            print('Turn metadata:', j.row('SELECT id,status,substr(assistant_text,1,700) FROM turns ORDER BY id DESC LIMIT 5'), file=sys.stderr)
            print('Instruction phases:', j.row('SELECT phase FROM interaction_instructions'), file=sys.stderr)
            print('Heartbeat metadata:', j.row("SELECT key,json_extract(value,'$.phase'),json_extract(value,'$.terminal_status'),json_extract(value,'$.checks'),json_extract(value,'$.native_returns[0].reported_revision'),json_extract(value,'$.stopped_reason') FROM bot_state WHERE key LIKE 'heartbeat_%'"), file=sys.stderr)
            if native_log:
                native_log.flush(); native_log.seek(0)
                print('Actual native tail:', native_log.read()[-6000:], file=sys.stderr)
        if native_log: native_log.close()
        j.close(); provider.shutdown(); provider.server_close()


if __name__ == '__main__':
    qualify(sys.argv[1], sys.argv[2], busy='--busy' in sys.argv[3:],
        native_cli='--native-cli' in sys.argv[3:], reports='--reports' in sys.argv[3:])
