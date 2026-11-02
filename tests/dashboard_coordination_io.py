"""Actual HTTP/process boundary; synthetic public authority/financial reports."""
import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from dashboard.app import create_app
from dashboard.companion import Grants
from dashboard.coordination import canonical


class Receiver:
    human = 100
    allowed = True
    binding_bytes = b'fixture'
    calls = 0
    def authorized(self, human): return self.allowed and human == self.human
    def assert_binding(self): pass
    def presentation_list(self, *args): return {'binding': 'fixture', 'items': []}
    def close(self): pass


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.receiver = Receiver()
        self.instruction = {'store_id': 'e4718c54-2248-48ac-9b37-8d560d204630',
                            'principal': 'human:test',
                            'task_sha256': hashlib.sha256(b'Selected objective').hexdigest()}
        self.instruction_file = self.root / 'instruction.json'
        self.instruction_file.write_text(json.dumps(self.instruction))
        self.instruction_file.chmod(0o600)
        sha = hashlib.sha256(canonical(self.instruction)).hexdigest()
        accounts = [dict(account_id=kind, kind=kind, unit='synthetic-charge',
                         max_calls=3, calls=1, available_calls=2,
                         max_charge=100, spent=10, reserved=20, available_charge=70,
                         active=0, uncertain=0, paused=False)
                    for kind in ('tribe', 'being', 'episode')]
        self.report = {'schema': 'execution/episode-report/v1', 'reporting_enabled': True,
                       'notice': None, 'snapshot': {**self.instruction,
                       'account_id': 'episode', 'instructions': [{'instruction_sha256': sha}],
                       'participants': ['being:test'], 'accounts': accounts,
                       'work': {'queued': 1}, 'start': 100, 'end': 200,
                       'observed_at': 150, 'funding_constraints': []}}
        self.report_file = self.root / 'report.json'
        self.report_file.write_text(json.dumps(self.report))
        self.marker = self.root / 'calls.jsonl'
        command = self.root / 'budget_reader_fixture.py'
        command.write_text('import json,sys\nfrom pathlib import Path\n'
                           f'p=Path({str(self.marker)!r})\n'
                           'with p.open("a") as f:f.write(json.dumps(sys.argv[1:])+"\\n")\n'
                           f'print(Path({str(self.report_file)!r}).read_text())\n')
        self.config = {'state_dir': str(self.root / 'state'), 'origin': 'https://example.test',
                       'prefix': '/interaction', 'bot_id': 123,
                       'companion': {'enabled': True, 'grants_dir': str(self.root / 'grants')},
                       'coordination': {'enabled': True, 'command': [sys.executable, str(command)],
                        'store_id': self.instruction['store_id'], 'principal': 'human:test',
                        'episodes': [{'account_id': 'episode', 'instruction_file': str(self.instruction_file),
                                      'task': 'Selected objective'}]}}

    def client(self, control=None):
        return TestClient(create_app(self.config, self.receiver, lambda raw, bot: int(raw), coordination_control=control),
                          base_url='https://example.test')

    def auth(self, client):
        response = client.post('/api/session', json={'init_data': '100'},
                               headers={'origin': 'https://example.test'})
        self.assertEqual(response.status_code, 200)
        return {'authorization': 'Bearer ' + response.json()['session_token']}

    def test_owner_read_uses_only_configured_operator_and_keeps_conversation_separate(self):
        with self.client() as client:
            self.assertEqual(client.get('/api/interaction/coordination').status_code, 401)
            self.assertFalse(self.marker.exists())
            response = client.get('/api/interaction/coordination', headers=self.auth(client))
            self.assertEqual(response.status_code, 200, response.text)
            value = response.json()
            self.assertTrue(value['read_only'])
            self.assertEqual(value['episodes'][0]['objective'], 'Selected objective')
            self.assertEqual(value['episodes'][0]['accounts'][0]['available_charge'], 70)
            self.assertEqual(json.loads(self.marker.read_text()), ['episode-report', '--', 'episode'])
            self.assertEqual(self.receiver.calls, 0)

    def test_bad_report_and_changed_instruction_never_return_partial_private_data(self):
        with self.client() as client:
            headers = self.auth(client)
            self.report['snapshot']['accounts'][0]['available_charge'] = 71
            self.report_file.write_text(json.dumps(self.report))
            response = client.get('/api/interaction/coordination', headers=headers)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('Selected objective', response.text)
            count = len(self.marker.read_text().splitlines())
            self.instruction_file.write_text('{}')
            response = client.get('/api/interaction/coordination', headers=headers)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(len(self.marker.read_text().splitlines()), count)

    def test_existing_companion_requires_explicit_budget_grant_without_reenrollment(self):
        credential = self.root / 'device.json'
        grants = Grants(self.config, self.receiver)
        grants.enroll('Selected device', credential, 3600)
        device = json.loads(credential.read_text())
        headers = {'authorization': device['authorization']}
        with self.client() as client:
            self.assertEqual(client.get('/api/interaction/coordination', headers=headers).status_code, 403)
            self.assertFalse(self.marker.exists())
            grants.coordination(device['grant_id'], True)
            self.assertEqual(client.get('/api/interaction/coordination', headers=headers).status_code, 200)
            self.assertEqual(json.loads(credential.read_text()), device)
            grants.coordination(device['grant_id'], False)
            self.assertEqual(client.get('/api/interaction/coordination', headers=headers).status_code, 403)

    def test_shared_login_budget_permission_defaults_off(self):
        self.config['shared_auth'] = {'enabled': True, 'home_origin': 'https://example.test'}
        identity = {'contract': 'dm.home-session/v1', 'origin': 'https://example.test',
                    'actor': {'kind': 'human', 'ref': 'human:telegram:100'}, 'expires': 2**40}
        with patch('dashboard.home_auth.identity_response', return_value=identity):
            with self.client() as client:
                client.cookies.set('__Host-home', 'A' * 43)
                self.assertEqual(client.get('/api/interaction/coordination').status_code, 403)
                self.assertFalse(self.marker.exists())
            self.config['shared_auth']['coordination_access'] = True
            with self.client() as client:
                client.cookies.set('__Host-home', 'A' * 43)
                self.assertEqual(client.get('/api/interaction/coordination').status_code, 200)

    def test_objective_mismatch_refuses_reader_configuration(self):
        self.config['coordination']['episodes'][0]['task'] = 'Unapproved objective'
        with self.assertRaises(ValueError):
            create_app(self.config, self.receiver)
        self.assertFalse(self.marker.exists())

    def control_headers(self, client, headers):
        import sqlite3
        with closing(sqlite3.connect(self.root / 'state/dashboard.sqlite3')) as db:
            csrf = db.execute('SELECT csrf FROM sessions WHERE human=100').fetchone()[0]
        return {**headers, 'origin': 'https://example.test', 'x-dashboard-csrf': csrf}

    def test_human_control_requires_authority_csrf_and_retains_exact_duplicate(self):
        from types import SimpleNamespace
        calls = []
        def apply(human, selected, body, **kwargs):
            calls.append(body)
            return {'state': 'confirmed', 'control_revision': body['expected_revision']+1,
                    'paused': body['paused'], 'execution_started': False}
        control = SimpleNamespace(permits=lambda human, selected: human == 100, apply=apply)
        body = {'nonce': 'native-pause-request-0001', 'account_id': 'episode', 'expected_revision': 0, 'paused': True}
        with self.client(control) as client:
            self.assertEqual(client.post('/api/interaction/coordination/control', json=body).status_code, 403)
            headers = self.auth(client)
            self.assertEqual(client.post('/api/interaction/coordination/control', json=body,
                headers={**headers,'origin':'https://example.test'}).status_code, 403)
            headers = self.control_headers(client, headers)
            first = client.post('/api/interaction/coordination/control', json=body, headers=headers)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(client.post('/api/interaction/coordination/control', json=body, headers=headers).json(), first.json())
            self.assertEqual(len(calls), 1)
            changed = client.post('/api/interaction/coordination/control', json=body | {'paused': False}, headers=headers)
            self.assertEqual(changed.status_code, 409)
            self.assertEqual(len(calls), 1)
            self.assertEqual(client.post('/api/interaction/coordination/control', json=body | {'account_id': 'not-selected'}, headers=headers).status_code, 400)

    def test_uncertain_control_is_never_replayed_or_replaced(self):
        from types import SimpleNamespace
        import sqlite3
        calls = []
        def apply(*args, **kwargs):
            calls.append(1)
            raise TimeoutError('Synthetic lost commit return')
        control = SimpleNamespace(permits=lambda human, selected: True, apply=apply)
        body = {'nonce': 'native-uncertain-request-1', 'account_id': 'episode', 'expected_revision': 0, 'paused': True}
        with self.client(control) as client:
            headers = self.control_headers(client, self.auth(client))
            for value in (body, body, body | {'nonce': 'native-uncertain-request-2', 'paused': False}):
                result = client.post('/api/interaction/coordination/control', json=value, headers=headers)
                self.assertEqual(result.status_code, 202, result.text)
                self.assertEqual(result.json()['state'], 'unconfirmed')
            self.assertEqual(calls, [1])
        with closing(sqlite3.connect(self.root / 'state/dashboard.sqlite3')) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM actions WHERE nonce LIKE 'coordination:%'").fetchone()[0], 1)

    def test_budget_read_grant_does_not_authorize_control(self):
        from types import SimpleNamespace
        calls = []
        control = SimpleNamespace(permits=lambda human, selected: True,
            apply=lambda *args, **kwargs: calls.append(1) or {'state': 'confirmed'})
        credential = self.root / 'control-device.json'
        grants = Grants(self.config, self.receiver)
        grants.enroll('Selected device', credential, 3600)
        device = json.loads(credential.read_text())
        headers = {'authorization': device['authorization'], 'origin': 'https://example.test', 'x-dashboard-csrf': device['csrf']}
        body = {'nonce': 'native-device-request-0001', 'account_id': 'episode', 'expected_revision': 0, 'paused': True}
        grants.coordination(device['grant_id'], True)
        with self.client(control) as client:
            self.assertFalse(client.get('/api/interaction/coordination', headers=headers).json()['can_control'])
            self.assertEqual(client.post('/api/interaction/coordination/control', json=body, headers=headers).status_code, 403)
            self.assertEqual(calls, [])
            grants.coordination(device['grant_id'], True, control=True)
            self.assertTrue(client.get('/api/interaction/coordination', headers=headers).json()['can_control'])
            self.assertEqual(client.post('/api/interaction/coordination/control', json=body, headers=headers).status_code, 200)
            self.assertEqual(calls, [1])
            grants.coordination(device['grant_id'], False)
            self.assertEqual(client.post('/api/interaction/coordination/control', json=body, headers=headers).status_code, 403)
        self.assertEqual(json.loads(credential.read_text()), device)

    def test_shared_login_control_is_distinct_from_budget_reading(self):
        from types import SimpleNamespace
        calls = []
        control=SimpleNamespace(permits=lambda human,selected:True,
            apply=lambda *args,**kwargs:calls.append(1) or {'state':'confirmed'})
        self.config['shared_auth']={'enabled':True,'home_origin':'https://example.test','coordination_access':True}
        identity={'contract':'dm.home-session/v1','origin':'https://example.test',
            'actor':{'kind':'human','ref':'human:telegram:100'},'expires':2**40}
        body={'nonce':'shared-control-request-001','account_id':'episode','expected_revision':0,'paused':True}
        with patch('dashboard.home_auth.identity_response',return_value=identity):
            with self.client(control) as client:
                client.cookies.set('__Host-home','A'*43)
                csrf=client.get('/api/interaction/access').json()['csrf']
                headers={'origin':'https://example.test','x-dashboard-csrf':csrf}
                self.assertEqual(client.post('/api/interaction/coordination/control',json=body,headers=headers).status_code,403)
            self.config['shared_auth']['coordination_control_access']=True
            with self.client(control) as client:
                client.cookies.set('__Host-home','A'*43)
                csrf=client.get('/api/interaction/access').json()['csrf']
                response=client.post('/api/interaction/coordination/control',json=body,
                    headers={'origin':'https://example.test','x-dashboard-csrf':csrf})
                self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(calls,[1])

    def test_protected_unknown_slots_bound_admission_without_deleting_evidence(self):
        from types import SimpleNamespace
        import sqlite3
        calls=[]
        control=SimpleNamespace(permits=lambda human,selected:True,
            apply=lambda *args,**kwargs:calls.append(1))
        with self.client(control) as client:
            headers=self.control_headers(client,self.auth(client))
            with closing(sqlite3.connect(self.root/'state/dashboard.sqlite3')) as db:
                for n in range(8):
                    db.execute('INSERT INTO actions VALUES(?,?,?,?)',(100,'coordination:'+str(n),
                        'unconfirmed',json.dumps({'request':{'nonce':str(n)},'outcome':{'state':'unconfirmed'}})))
                db.commit()
            body={'nonce':'bounded-control-request-001','account_id':'episode','expected_revision':0,'paused':True}
            self.assertEqual(client.post('/api/interaction/coordination/control',json=body,headers=headers).status_code,409)
            self.assertEqual(calls,[])
        with closing(sqlite3.connect(self.root/'state/dashboard.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM actions').fetchone()[0],8)

    @unittest.skipUnless(os.environ.get('MATRIX_COORDINATION_TEST_ROOT'),
                         'Actual Matrix human funding operator source is optional')
    def test_actual_human_frontend_pause_through_authenticated_http(self):
        import importlib.util
        import time
        import uuid
        from types import SimpleNamespace
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from dashboard.coordination import HumanControl
        matrix = Path(os.environ['MATRIX_COORDINATION_TEST_ROOT']).resolve()
        sys.path.insert(0, str(matrix / 'src'))
        self.addCleanup(lambda: sys.path.remove(str(matrix / 'src')))
        from daimon_matrix.execution_instruction import Instruction
        from daimon_matrix.execution_store import ExecutionStore
        from daimon_matrix.operator_execution import HumanExecutionOperator
        from daimon_matrix.codex_review import CodexReviewRunner
        from daimon_matrix.hermes_review import HermesReviewRunner
        from daimon_matrix.review_runner import ReviewController
        spec = importlib.util.spec_from_file_location('matrix_control_fixture', matrix/'tests/test_execution_instruction.py')
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        key = Ed25519PrivateKey.generate()
        store = ExecutionStore.create(self.root/'human-control.sqlite', fixture.verifier(key))
        store.enable_episode_reporting()
        now = int(time.time())
        def signed(value, event): return fixture.proof(key, 'approve', value, event)
        for kind in ('tribe', 'being', 'episode'):
            account = dict(schema='execution/funding-account/v1', store_id=store.store_id,
                principal='human:test',account_id=kind,kind=kind,
                subject='being:test' if kind=='being' else kind,start=now-5,end=now+600,
                unit='synthetic',max_calls=3,max_charge=100,max_active=1,max_bindings=3)
            store.grant_budget(account,signed(account,'grant-'+kind))
        payload = fixture.request(store_id=store.store_id,start=now-1,end=now+300,
            task_sha256=hashlib.sha256(b'Selected objective').hexdigest())
        instruction = Instruction.from_dict(payload)
        store.approve(instruction,signed(payload,'instruction'))
        funding = dict(schema='execution/instruction-funding/v1',store_id=store.store_id,
            principal='human:test',instruction_sha256=instruction.sha256,
            accounts=['tribe','being','episode'],route='isolated-test',max_charge=30)
        store.fund_instruction(instruction,funding,signed(funding,'funding'))
        policy = dict(schema='execution/episode-policy/v1',store_id=store.store_id,
            principal='human:test',account_id='episode',participants=['being:peer'],
            instructions=[instruction.sha256],threads=['selected-thread'],
            max_requests=2,max_pending=1,max_input_bytes=4096)
        store.configure_episode(policy,signed(policy,'policy'))
        self.instruction_file.write_text(json.dumps(payload))
        self.config['coordination']['store_id'] = store.store_id
        self.report_file.write_text(json.dumps(store.episode_report('episode')))
        bindings = {}
        for kind, cls in (('codex',CodexReviewRunner),('hermes',HermesReviewRunner)):
            runner = object.__new__(cls)
            runner.registration = SimpleNamespace(binding=instruction.binding,principal='human:test')
            bindings[kind]=(store,ReviewController(store,runner,None))
        factory_calls = []
        def factory(authenticate):
            factory_calls.append(1)
            return HumanExecutionOperator(challenge_path=self.root/'human-challenges.sqlite',
                bindings=bindings,authenticate=authenticate,
                signer=lambda principal,data:key.sign(data),challenge_id=lambda:uuid.uuid4().hex)
        control = HumanControl(factory,human=100,principal='human:test',store_id=store.store_id,runner_type='codex')
        body={'nonce':'actual-human-control-0001','account_id':'episode','expected_revision':0,'paused':True}
        with self.client(control) as client:
            headers=self.control_headers(client,self.auth(client))
            result=client.post('/api/interaction/coordination/control',json=body,headers=headers)
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['applied_revision'],1)
            self.assertTrue(store.funding_status('episode')['paused'])
            self.assertEqual(client.post('/api/interaction/coordination/control',json=body,headers=headers).json(),result.json())
            self.assertEqual(factory_calls,[1])
            stale=body|{'nonce':'actual-stale-resume-0001','paused':False}
            self.assertEqual(client.post('/api/interaction/coordination/control',json=stale,headers=headers).json()['state'],'rejected')
            self.assertTrue(store.funding_status('episode')['paused'])
            resume=body|{'nonce':'actual-resume-control-001','expected_revision':1,'paused':False}
            result=client.post('/api/interaction/coordination/control',json=resume,headers=headers)
            self.assertEqual(result.json()['applied_revision'],2,result.text)
            reopened=ExecutionStore(store.path,store.verifier)
            self.assertFalse(reopened.funding_status('episode')['paused'])
            self.assertEqual(reopened.funding_status('episode')['calls'],0)
        import sqlite3
        with closing(sqlite3.connect(store.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM cycles').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM coordination_work').fetchone()[0],0)
        self.assertEqual(self.receiver.calls,0)

    @unittest.skipUnless(os.environ.get('MATRIX_COORDINATION_TEST_ROOT'),
                         'Actual selected Matrix operator source is optional')
    def test_actual_matrix_signed_journal_through_authenticated_http(self):
        matrix = Path(os.environ['MATRIX_COORDINATION_TEST_ROOT']).resolve()
        python = os.environ.get('MATRIX_COORDINATION_TEST_PYTHON', sys.executable)
        setup = '''import json,sys,time,hashlib
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from daimon_matrix.execution_instruction import Instruction
from daimon_matrix.execution_store import ExecutionStore
from tests.test_execution_instruction import proof,request,verifier
root=Path(sys.argv[1]);key=Ed25519PrivateKey.generate();now=int(time.time());serial=0
def signed(value):
 global serial
 serial+=1
 return proof(key,'approve',value,event='interop-'+str(serial))
store=ExecutionStore.create(root/'signed.sqlite',verifier(key))
store.enable_episode_reporting()
for kind in ['tribe','being','episode']:
 value=dict(schema='execution/funding-account/v1',store_id=store.store_id,principal='human:test',account_id=kind,kind=kind,subject='being:test' if kind=='being' else kind,start=now-5,end=now+600,unit='synthetic-charge',max_calls=3,max_charge=100,max_active=1,max_bindings=3)
 store.grant_budget(value,signed(value))
value=request(store_id=store.store_id,start=now-1,end=now+300,task_sha256=hashlib.sha256(b'Selected objective').hexdigest())
instruction=Instruction.from_dict(value);store.approve(instruction,signed(value))
funding=dict(schema='execution/instruction-funding/v1',store_id=store.store_id,principal='human:test',instruction_sha256=instruction.sha256,accounts=['tribe','being','episode'],route='isolated-test',max_charge=30)
store.fund_instruction(instruction,funding,signed(funding))
policy=dict(schema='execution/episode-policy/v1',store_id=store.store_id,principal='human:test',account_id='episode',participants=['being:peer'],instructions=[instruction.sha256],threads=['selected-thread'],max_requests=2,max_pending=1,max_input_bytes=4096)
store.configure_episode(policy,signed(policy))
(root/'actual-instruction.json').write_text(json.dumps(value));(root/'actual-instruction.json').chmod(0o600)
(root/'public-trust.json').write_text(json.dumps({'human:test':key.public_key().public_bytes_raw().hex()}));(root/'public-trust.json').chmod(0o600)
print(json.dumps({'store_id':store.store_id}))
'''
        environment = {**os.environ, 'PYTHONPATH': os.pathsep.join((str(matrix / 'src'), str(matrix)))}
        result = subprocess.run([python, '-c', setup, str(self.root)], env=environment,
                                capture_output=True, text=True, check=True, timeout=20)
        store = json.loads(result.stdout)['store_id']
        entry = (f'import sys;sys.path[:0]={[str(matrix / "src")]!r};'
                 'from daimon_matrix.operator_execution import main;sys.exit(main())')
        self.config['coordination'].update(store_id=store, command=[python, '-c', entry,
            '--store', str(self.root / 'signed.sqlite'), '--trust', str(self.root / 'public-trust.json')])
        self.config['coordination']['episodes'][0]['instruction_file'] = str(self.root / 'actual-instruction.json')
        with self.client() as client:
            response = client.get('/api/interaction/coordination', headers=self.auth(client))
            self.assertEqual(response.status_code, 200, response.text)
            account = response.json()['episodes'][0]['accounts'][0]
            self.assertEqual(account['available_calls'], 3)
            self.assertEqual(account['available_charge'], 100)
        import sqlite3
        with closing(sqlite3.connect(self.root / 'signed.sqlite')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM cycles').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM coordination_work').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
