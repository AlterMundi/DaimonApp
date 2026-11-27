"""Real published Alerts HTTP/SQLite boundaries; Telegram receipt is fictional."""
from contextlib import closing
import concurrent.futures
import hashlib
import http.server
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dashboard.alerts import Client, Receiver, Sender, AlertsUnavailable
from dashboard.alerts_contract import validate
from dashboard.app import create_app
from dashboard.provider import ProviderUnavailable
from fastapi.testclient import TestClient

CORE = Path(os.environ.get('ALERTS_CORE_SOURCE', ROOT.parent / 'daimon-alerts')).resolve()


class NativeProvider:
    human = 100
    binding_bytes = b'fictional receiving authority'
    allowed = True
    def assert_binding(self): pass
    def authorized(self, human): return self.allowed and human == self.human
    def snapshot(self): raise ProviderUnavailable('Native state unavailable')
    def close(self): pass


class NoticeSender:
    token = 'fictional-bot-binding'
    def __init__(self):
        self.calls = []
        self.outcome = {'outcome': 'delivered', 'message_ref': 'message-17', 'destination_ref': 'human-100'}
    def verify(self): pass
    def assert_binding(self): pass
    def send(self, projection):
        self.calls.append(projection)
        return dict(self.outcome)


class Receiving(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (CORE / 'target/debug/daimon-alerts').is_file():
            raise RuntimeError('Build the published pinned Daimon Alerts runtime before these tests')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='telecodex-alerts-')
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        with socket.socket() as stream:
            stream.bind(('127.0.0.1', 0))
            port = stream.getsockname()[1]
        self.base = f'http://127.0.0.1:{port}'
        self.token = self.root / 'token'
        value = secrets.token_urlsafe(32)
        self.token.write_text(value)
        self.token.chmod(0o600)
        actor = dict(actor_id='fixture-receiver', token_sha256=hashlib.sha256(value.encode()).hexdigest(),
            producers=['fixture'], scopes=['human', 'other'], adapters=['telegram'],
            grants=['publish', 'read', 'status', 'acknowledge', 'deliver', *getattr(self, 'extra_grants', [])])
        config = dict(database=str(self.root / 'core.sqlite'), listen=f'127.0.0.1:{port}',
            freshness_seconds=60, max_incidents=1000, retention_seconds=600, actors=[actor],
            routes=[dict(receiving_scope='human', adapter_id='telegram'),
                    dict(receiving_scope='other', adapter_id='telegram')])
        core_config = self.root / 'core.json'
        core_config.write_text(json.dumps(config))
        core_config.chmod(0o600)
        self.process = subprocess.Popen([str(CORE / 'target/debug/daimon-alerts'), 'serve', str(core_config)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.config = dict(state_dir=str(self.root / 'receiving'), origin='https://example.test',
            prefix='/sessions', bot_id=123, alerts=dict(enabled=True, base_url=self.base,
                token_file=str(self.token), receiving_scope='human', adapter_id='telegram', deliver=True))
        self.provider = NativeProvider()
        self.sender = NoticeSender()
        self.client = Client(self.config['alerts'])
        for _ in range(100):
            try:
                self.client.call('GET', '/v1/status', 'Status')
                break
            except AlertsUnavailable:
                if self.process.poll() is not None:
                    self.fail('Published runtime failed to start')
                time.sleep(.03)
        else:
            self.fail('Published runtime was not ready')
        self.receiver = self.make_receiver()
        self.projection = dict(schema='daimon-alerts/v1', producer_id='fixture', incident_id='credit-1',
            operation_id='batch-1', revision=1, receiving_scope='human', phase='index', resource_ref='worker',
            severity='error', problem_code='payment_required', summary='Fictional credit failure.',
            action='Restore credit, then explicitly resume.', source_at=int(time.time()),
            updated_at=int(time.time()), processing_state='open', work_preserved=True)
        self.publish()

    def tearDown(self):
        self.process.terminate()
        self.process.wait(timeout=5)
        self.tmp.cleanup()

    def make_receiver(self):
        return Receiver(self.config, self.provider, client=self.client, sender=self.sender)

    def publish(self, projection=None):
        value = projection or self.projection
        return self.client.call('PUT', f"/v1/incidents/{value['producer_id']}/{value['incident_id']}", 'Acceptance', value)

    def incident(self):
        return self.client.call('GET', '/v1/incidents/fixture/credit-1', 'Incident')

    def test_launcher_attention_is_signed_read_only_and_origin_scoped(self):
        config = {**self.config, 'bot_username':'TestBot', 'miniapp_short_name':'sessions',
                  'launcher_url':'https://pair.example.test/apps/',
                  'alerts':{**self.config['alerts'], 'launcher_origins':['https://apps.example.test']}}
        app = create_app(config, self.provider, lambda raw, bot: int(raw), alerts=self.receiver)
        client = TestClient(app, base_url='https://example.test')
        self.addCleanup(client.close)
        self.receiver.tick()
        endpoint = '/api/alerts/attention'
        headers = {'origin':'https://apps.example.test'}
        self.assertEqual(client.get(endpoint).status_code, 405)
        self.assertEqual(client.post(endpoint, json={'init_data':'100'}).status_code, 403)
        self.assertEqual(client.post(endpoint, headers=headers, json={'init_data':'bad'}).status_code, 401)
        self.assertEqual(client.post(endpoint, headers=headers, json={'init_data':'101'}).status_code, 403)
        response = client.post(endpoint, headers=headers, json={'init_data':'100'})
        self.assertEqual(response.status_code, 200)
        value = response.json()
        self.assertEqual(value['symbol'], '🔴')
        self.assertEqual(value['count'], 1)
        self.assertEqual(value['app_url'], 'https://t.me/TestBot/sessions?mode=compact')
        self.assertEqual(value['bot_username'], 'TestBot')
        self.assertNotIn('session_token', value)
        self.assertNotIn('csrf', value)
        self.assertNotIn('set-cookie', response.headers)
        self.assertEqual(set(value['summaries'][0]), {'symbol','summary'})
        # Launcher origins are not accepted on the session/control surfaces.
        self.assertEqual(client.post('/api/session', headers=headers, json={'init_data':'100'}).status_code, 403)
        self.provider.allowed = False
        self.assertEqual(client.post(endpoint, headers=headers, json={'init_data':'100'}).status_code, 403)

    def test_storage_pressure_contract_and_receiving_projection(self):
        value = dict(self.projection, incident_id='storage-1', phase='storage', problem_code='storage_pressure',
                     resource_ref='fictional-host', severity='critical',
                     summary='Root storage critical: 95% used; 4 GiB available.')
        self.publish(value)
        self.receiver.tick()
        snapshot = self.receiver.snapshot()
        item = next(row for row in snapshot['incidents'] if row['projection']['incident_id'] == value['incident_id'])
        self.assertEqual(item['projection']['severity'], 'critical')
        self.assertEqual(item['projection']['problem_code'], 'storage_pressure')
        self.assertEqual(self.sender.calls[-1]['summary'], value['summary'])

    def test_closed_contract_and_credential_boundaries(self):
        for changed in [dict(self.projection, revision=True), dict(self.projection, summary='private\nraw'),
                        dict(self.projection, raw_provider_error='secret'), dict(self.projection, schema='other/v1')]:
            with self.assertRaises(ValueError): validate(changed, 'IncidentInput')
        self.token.chmod(0o644)
        with self.assertRaises(AlertsUnavailable): Client(self.config['alerts'])
        self.token.chmod(0o600)
        link = self.root / 'symlink'
        link.symlink_to(self.token)
        with self.assertRaises(OSError): Client({**self.config['alerts'], 'token_file': str(link)})
        for base in ['https://example.test', 'http://localhost:8791', self.base + '/private', self.base + '?token=x']:
            with self.assertRaises(ValueError): Client({**self.config['alerts'], 'base_url': base})
        self.assertEqual(self.receiver.db_path.stat().st_mode & 0o077, 0)

    def test_scope_claim_receipt_resolution_and_restart(self):
        self.publish(dict(self.projection, incident_id='foreign', receiving_scope='other'))
        self.receiver.tick()
        self.assertEqual(self.receiver.snapshot()['state'], 'available')
        self.assertEqual(self.receiver.snapshot()['observer_state'], 'unobserved')
        self.assertEqual(len(self.receiver.snapshot()['incidents']), 1)
        self.assertEqual(len(self.sender.calls), 1)
        self.assertEqual(self.incident()['deliveries'][0]['state'], 'delivered')
        self.receiver = self.make_receiver()
        self.receiver.tick()
        self.assertEqual(len(self.sender.calls), 1)
        self.receiver.acknowledge('fixture', 'credit-1', 'same-request')
        self.receiver.acknowledge('fixture', 'credit-1', 'same-request')
        self.assertEqual(len(self.incident()['acknowledgments']), 1)
        with self.assertRaises(AlertsUnavailable): self.receiver.acknowledge('fixture', 'foreign', 'no')
        self.publish(dict(self.projection, revision=2, processing_state='resolved'))
        self.receiver.tick()
        self.assertEqual(len(self.sender.calls), 2)
        self.assertEqual(self.sender.calls[-1]['processing_state'], 'resolved')
        self.assertEqual(self.receiver.snapshot()['incidents'], [])
        self.assertEqual(self.incident()['projection']['processing_state'], 'resolved')

    def test_parallel_receivers_and_ambiguous_send_do_not_repeat(self):
        other = self.make_receiver()
        self.sender.outcome = {'outcome': 'uncertain'}
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda receiver: receiver.tick(), [self.receiver, other]))
        self.assertEqual(len(self.sender.calls), 1)
        self.assertEqual(self.incident()['deliveries'][0]['state'], 'uncertain')
        self.receiver = self.make_receiver()
        self.receiver.tick()
        self.assertEqual(len(self.sender.calls), 1)
        self.assertEqual(self.receiver.snapshot()['local_deliveries'][0]['outcome'], 'uncertain')

    def test_lost_claim_reply_and_revocation_before_send(self):
        original = self.client.call
        def lost(method, path, shape, value=None):
            result = original(method, path, shape, value)
            if path.endswith('/claim'): raise AlertsUnavailable('operation_unconfirmed')
            return result
        self.client.call = lost
        self.receiver.tick()
        self.assertEqual(self.sender.calls, [])
        self.assertEqual(self.incident()['deliveries'][0]['state'], 'uncertain')
        self.client.call = original
        self.make_receiver().tick()
        self.assertEqual(self.sender.calls, [])
        # A new recurrence receives a new incident, preserving the operation.
        self.publish(dict(self.projection, incident_id='credit-2'))
        def revoke(method, path, shape, value=None):
            result = original(method, path, shape, value)
            if path.endswith('/claim'): self.provider.allowed = False
            return result
        self.client.call = revoke
        self.receiver.tick()
        self.assertEqual(self.sender.calls, [])
        self.assertEqual(self.receiver.snapshot()['state'], 'unavailable')

    def test_lost_receipt_reply_reconciles_without_telegram_replay(self):
        original = self.client.call
        def lost(method, path, shape, value=None):
            if path.endswith('/receipt'): raise AlertsUnavailable('service_unavailable')
            return original(method, path, shape, value)
        self.client.call = lost
        self.receiver.tick()
        self.assertEqual(len(self.sender.calls), 1)
        self.assertEqual(self.incident()['deliveries'][0]['state'], 'uncertain')
        self.client.call = original
        self.make_receiver().tick()
        self.assertEqual(len(self.sender.calls), 1)
        self.assertEqual(self.incident()['deliveries'][0]['state'], 'delivered')

    def test_pagination_is_bounded_and_does_not_hide_active_work_as_idle(self):
        for i in range(201): self.publish(dict(self.projection, incident_id=f'incident-{i}'))
        self.receiver.deliver = False
        self.receiver.tick()
        self.assertEqual(len(self.receiver.snapshot()['incidents']), 200)
        self.assertTrue(self.receiver.snapshot()['truncated'])
        with self.receiver.lock: self.receiver.view['observed_at'] = time.time() - 120
        self.assertEqual(self.receiver.snapshot()['state'], 'stale')

    def test_dashboard_alerts_survive_native_failure_and_keep_receiving_auth(self):
        self.receiver.deliver = False
        self.receiver.tick()
        app = create_app(self.config, self.provider, lambda raw, bot: int(raw), alerts=self.receiver)
        client = TestClient(app, base_url='https://example.test')
        self.addCleanup(client.close)
        self.assertEqual(client.get('/api/alerts').status_code, 401)
        headers = {'origin': 'https://example.test'}
        session = client.post('/api/session', json={'init_data': '100'}, headers=headers).json()
        headers['authorization'] = 'Bearer ' + session['session_token']
        self.assertEqual(client.get('/api/state', headers=headers).status_code, 503)
        response = client.get('/api/alerts', headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['incidents'][0]['projection']['problem_code'], 'payment_required')
        self.assertNotIn(self.token.read_text(), response.text)
        body = dict(producer_id='fixture', incident_id='credit-1', request_id='ack-from-phone')
        self.assertEqual(client.post('/api/alerts/acknowledge', json=body, headers=headers).status_code, 403)
        headers['x-dashboard-csrf'] = response.json()['csrf']
        self.assertEqual(client.post('/api/alerts/acknowledge', json=body, headers=headers).status_code, 200)
        bad_origin = {**headers, 'origin': 'https://foreign.test'}
        self.assertEqual(client.post('/api/alerts/acknowledge', json=body, headers=bad_origin).status_code, 403)
        for invalid in [list(body), {**body, 'incident_id': '../foreign'}, {**body, 'token': 'no'}]:
            self.assertEqual(client.post('/api/alerts/acknowledge', json=invalid, headers=headers).status_code, 400)
        self.provider.allowed = False
        self.assertEqual(client.get('/api/alerts', headers=headers).status_code, 401)
        self.assertEqual(client.post('/api/alerts/acknowledge', json=body, headers=headers).status_code, 401)

    def test_telegram_split_preserves_sessions_without_adapter_or_bot_token(self):
        from dashboard.companion import Grants, authority
        from dashboard.private_state import write_json
        from dashboard.provider import Provider
        from dashboard.telegram_split import prepare
        from dashboard.traffic import Traffic
        from scripts.bot_traffic import Journal, private_token

        root = self.root / 'split'
        root.mkdir(mode=0o700)

        def profile(name, content):
            path = root / name
            path.write_text(content)
            path.chmod(0o600)
            return path

        token = profile('bot-key', '123:' + 'synthetic_only_' * 4)
        socket_path = root / 'absent-owner.sock'
        db_path = root / 'gateway.sqlite'
        with closing(sqlite3.connect(db_path)) as db, db:
            db.executescript('CREATE TABLE users(tg_user_id int, allowed int); INSERT INTO users VALUES(100,1);')
        owner = f'[session_control]\nsocket_path="{socket_path}"\nhuman_id=100\n'
        state = f'db_path="{db_path}"\n'
        before_config = f'[telegram]\napi_base="http://127.0.0.1:8081"\nbot_token_file="{token}"\n'
        old_profile = profile('embedded.toml', state + owner + before_config)
        gateway_profile = profile('gateway.toml', state + owner + '[telegram]\nexternal_polling=true\n')
        adapter_profile = profile('adapter.toml', owner + before_config + 'external_polling=true\n')
        meter = profile('meter.toml', f'port=8081\ntoken_file="{token}"\nstate_dir="{root}/meter"\n')
        journal = Journal(root / 'meter')
        self.addCleanup(journal.close)
        journal.bind_bot(private_token(token).hex())
        grants = root / 'grants'
        config = {**self.config, 'bot_username': 'FixtureBot', 'receiver_config': str(old_profile),
                  'state_dir': str(root / 'sessions'), 'traffic': {'enabled': True, 'meter_config': str(meter)},
                  'companion': {'enabled': True, 'grants_dir': str(grants)}}
        legacy = Provider(config)
        device_token = secrets.token_urlsafe(32)
        write_json(grants / (hashlib.sha256(device_token.encode()).hexdigest() + '.json'),
                   {'schema':'telecodex.companion-grant/v1', 'scope':'interaction_only',
                    'authority':authority(config, legacy), 'human':100, 'expires':int(time.time())+3600,
                    'csrf':secrets.token_urlsafe(32)})
        receiver = Receiver(config, legacy)
        with receiver.database() as db:
            db.execute("INSERT INTO attempts VALUES('held','request-held','sending',NULL,1)")
        traffic = Traffic(config, legacy, health=lambda:{'ok':True,'dropped_records':0})
        old_app = create_app(config, legacy, lambda raw, bot: int(raw), alerts=receiver, traffic=traffic)
        old_browser = TestClient(old_app, base_url='https://example.test')
        self.addCleanup(old_browser.close)
        origin = {'origin':'https://example.test'}
        token_result = old_browser.post('/api/session', json={'init_data':'100'}, headers=origin)
        old_session = token_result.json()['session_token']
        migration = root / 'split.json'
        prepare(config, gateway_profile, adapter_profile, migration)
        new_config = {**config, 'receiver_config':str(gateway_profile), 'telegram_split_binding':str(migration)}
        token.unlink()  # The migrated web process can no longer open the Telegram credential.
        candidate = Provider(new_config)
        self.assertEqual(authority(config, legacy), authority(new_config, candidate))
        self.assertEqual(Grants(new_config, candidate).authenticate(device_token)['human'], 100)
        new_alerts = Receiver(new_config, candidate)
        with new_alerts.database() as db:
            self.assertEqual(tuple(db.execute("SELECT request_id,state FROM attempts WHERE delivery_id='held'").fetchone()),
                             ('request-held','sending'))
        self.assertIsNone(new_alerts.sender.call('getMe', {}))
        self.assertEqual(new_alerts.sender.send(self.projection), {'outcome':'failed'})
        new_alerts.sender.next_send = 0
        from unittest.mock import patch
        online = True
        sends = []

        def owner_request(path, *, envelope):
            self.assertEqual(path, str(socket_path))
            if not online:
                raise FileNotFoundError('Adapter is stopped')
            request = envelope['sessions_telegram']
            fingerprint = candidate.telegram_split['credential_fingerprint']
            if request['operation'] == 'status':
                return {'id':123, 'username':'FixtureBot', 'credential_fingerprint':fingerprint}
            self.assertEqual(request['operation'], 'alert')
            self.assertEqual(request['credential_fingerprint'], fingerprint)
            sends.append(request)
            return {'ok':True, 'result':{'message_id':17, 'chat':{'id':100}}}

        with patch('dashboard.alerts.control', side_effect=owner_request):
            new_alerts.sender.verify()
            online = False
            new_alerts.tick()
            self.assertEqual(self.incident()['deliveries'][0]['state'], 'pending')
            self.assertEqual(sends, [])
            online = True
            new_alerts.tick()
            new_alerts.tick()
            self.assertEqual(self.incident()['deliveries'][0]['state'], 'delivered')
            self.assertEqual(len(sends), 1)
        with patch('dashboard.alerts.control', side_effect=ConnectionResetError('Lost response')):
            new_alerts.sender.next_send = 0
            self.assertEqual(new_alerts.sender.send(self.projection), {'outcome':'uncertain'})
        new_traffic = Traffic(new_config, candidate, health=lambda:{'ok':True,'dropped_records':0})
        self.assertEqual(traffic.state['binding'], new_traffic.state['binding'])
        new_app = create_app(new_config, candidate, alerts=new_alerts, traffic=new_traffic)
        new_browser = TestClient(new_app, base_url='https://example.test')
        self.addCleanup(new_browser.close)
        headers = {**origin, 'authorization':'Bearer ' + old_session}
        self.assertEqual(new_browser.get('/api/alerts', headers=headers).status_code, 200)
        self.assertEqual(new_browser.get('/api/alerts', headers=origin).status_code, 401)
        record = json.loads(migration.read_text())
        write_json(migration, {**record, 'human':999})
        self.assertEqual(new_browser.get('/api/alerts', headers=headers).status_code, 503)

    def test_journal_binding_and_live_credential_changes_fail_closed(self):
        original = self.config['alerts']['receiving_scope']
        self.config['alerts']['receiving_scope'] = 'other'
        with self.assertRaises(ValueError): self.make_receiver()
        self.config['alerts']['receiving_scope'] = original
        self.token.write_text(secrets.token_urlsafe(32))
        self.receiver.tick()
        self.assertEqual(self.receiver.snapshot()['error'], 'credential_binding_changed')

    def test_real_bot_http_binding_plain_text_and_malformed_receipts(self):
        calls = []
        reply = {'ok': True, 'result': {'id': 123, 'username': 'TestBot'}}
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(handler):
                calls.append((handler.path.rsplit('/', 1)[-1], json.loads(handler.rfile.read(int(handler.headers['Content-Length'])))))
                raw = json.dumps(reply).encode()
                handler.send_response(200)
                handler.send_header('Content-Type', 'application/json')
                handler.send_header('Content-Length', str(len(raw)))
                handler.end_headers()
                handler.wfile.write(raw)
            def log_message(handler, *args): pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.provider.receiver = {'telegram': {'bot_token_file': str(self.token),
            'api_base': f'http://127.0.0.1:{server.server_port}'}}
        config = {**self.config, 'bot_username': 'TestBot'}
        sender = Sender(self.provider, config)
        sender.verify()
        reply = {'ok': True, 'result': {'chat': {'id': 100}, 'message_id': 17}}
        self.assertEqual(sender.send(self.projection)['outcome'], 'delivered')
        self.assertEqual(calls[-1][1]['chat_id'], 100)
        self.assertNotIn('parse_mode', calls[-1][1])
        self.assertNotIn('message_thread_id', calls[-1][1])
        reply = {'ok': True, 'result': {'chat': 'malformed', 'message_id': 17}}
        sender.next_send = 0
        self.assertEqual(sender.send(self.projection)['outcome'], 'uncertain')
        reply = {'ok': False, 'error_code': 400, 'description': self.token.read_text()}
        sender.next_send = 0
        self.assertEqual(sender.send(self.projection), {'outcome': 'failed'})
        reply = []
        with self.assertRaises(AlertsUnavailable): Sender(self.provider, config).verify()
        # Permission can be revoked during the cadence wait; no external send.
        count = len(calls)
        sender.next_send = time.monotonic() + .1
        timer = threading.Timer(.02, lambda: setattr(self.provider, 'allowed', False))
        timer.start()
        with self.assertRaises(AlertsUnavailable): sender.send(self.projection)
        timer.join()
        self.assertEqual(len(calls), count)

    def test_bot_rotation_denies_cached_browser_view(self):
        bot_token = self.root / 'bot-token'
        bot_token.write_text('fictional-original-bot-token')
        bot_token.chmod(0o600)
        self.provider.receiver = {'telegram': {'bot_token_file': str(bot_token)}}
        config = {**self.config, 'bot_username': 'TestBot'}
        self.receiver.sender = Sender(self.provider, config)
        self.receiver.deliver = False
        self.receiver.tick()
        app = create_app(config, self.provider, lambda raw, bot: int(raw), alerts=self.receiver)
        client = TestClient(app, base_url='https://example.test')
        self.addCleanup(client.close)
        headers = {'origin': 'https://example.test'}
        session = client.post('/api/session', json={'init_data': '100'}, headers=headers).json()
        headers['authorization'] = 'Bearer ' + session['session_token']
        self.assertEqual(client.get('/api/alerts', headers=headers).status_code, 200)
        bot_token.write_text('fictional-replacement-bot-token')
        self.assertEqual(client.get('/api/alerts', headers=headers).status_code, 503)


if __name__ == '__main__': unittest.main(verbosity=2)
