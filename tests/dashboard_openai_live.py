"""Public GPT-Live creation boundaries, synthetic HTTP only; no provider calls."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.openai_live import LiveUnavailable, OpenAILive, LiveSideband, session_spec
from dashboard.openai_live_visits import LiveCreations


class Creation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.key = Path(self.tmp.name) / 'project-key'
        self.key.write_text('sk-synthetic-not-a-provider-secret')
        self.key.chmod(0o600)
        self.calls = []
        self.spec = session_spec('You are CompAII. Speak briefly.',
            backend_model='explicit-owner-backend', backend_instructions='Use verified results.',
            backend_tools=[{'type': 'web_search'}])

    def client(self, reply):
        def handle(request):
            self.calls.append(request)
            return reply(request) if callable(reply) else reply
        return OpenAILive(self.key, transport=httpx.MockTransport(handle))

    def success(self):
        return httpx.Response(201, json={'session': {'id': 'opaque:live/example'},
            'transport': {'type': 'webrtc', 'sdp': 'v=0\r\nanswer'}})

    def test_documented_live_json_preserves_owner_and_opaque_session(self):
        call = self.client(self.success()).create('v=0\r\noffer', self.spec)
        request = self.calls[0]
        self.assertEqual(str(request.url), 'https://api.openai.com/v1/live/sessions')
        value = json.loads(request.content)
        self.assertEqual(value['session']['model'], 'gpt-live-1')
        self.assertEqual(value['session']['instructions'], self.spec['instructions'])
        self.assertEqual(value['session']['delegation']['type'], 'responses')
        self.assertEqual(value['session']['delegation']['responses']['tools'], [{'type': 'web_search'}])
        self.assertEqual(value['transport'], {'type': 'webrtc', 'sdp': 'v=0\r\noffer'})
        self.assertNotIn('audio', value['session'])  # Negotiated media, no PCM adapter.
        self.assertEqual(call.session_id, 'opaque:live/example')
        self.assertNotIn('answer', repr(call))

    def test_client_delegation_keeps_existing_backend_outside_voice_session(self):
        spec = session_spec('Owner voice context', client_delegation=True)
        self.client(self.success()).create('v=0 offer', spec)
        self.assertEqual(json.loads(self.calls[0].content)['session']['delegation'], {'type': 'client'})
        with self.assertRaises(ValueError):
            session_spec('Owner voice context', client_delegation=True, backend_model='other')

    def test_invalid_offer_model_and_tools_never_submit(self):
        client = self.client(self.success())
        for offer, spec in [('not SDP', self.spec), ('v=0 offer', {**self.spec, 'model': 'gpt-realtime-2.1'})]:
            with self.assertRaises(ValueError):
                client.create(offer, spec)
        for tools in [[{'type': 'web_search'}] * 129, [{'type': 'function', 'value': float('nan')}]]:
            with self.assertRaises(ValueError):
                session_spec('Owner', backend_model='explicit-backend', backend_instructions='Owner', backend_tools=tools)
        self.assertEqual(self.calls, [])

    def test_owner_input_is_frozen_and_bounded(self):
        tools = [{'type': 'web_search'}]
        spec = session_spec('Owner', backend_model='explicit-backend', backend_instructions='Owner', backend_tools=tools)
        tools[0]['type'] = 'changed'
        self.assertEqual(spec['delegation']['responses']['tools'][0]['type'], 'web_search')
        with self.assertRaises(ValueError):
            session_spec('x' * 8193, client_delegation=True)

    def test_provider_voice_context_permissions_and_backend_options_are_preserved(self):
        options = {'audio': {'output': {'voice': {'id': 'owner-custom-voice'}}},
            'input': [{'role': 'developer', 'content': [{'type': 'input_text', 'text': 'Owner startup context'}]}],
            'client': {'data_channel': {'allowed_client_events': ['session.close']}}}
        backend = {'reasoning': {'effort': 'low'}, 'max_output_tokens': 128,
                   'parallel_tool_calls': False}
        spec = session_spec('Owner', backend_model='explicit-backend', backend_instructions='Owner',
                            session_options=options, backend_options=backend,
                            delegation_options={'acknowledgement_delay_ms': 400})
        options['audio']['output']['voice']['id'] = 'changed'
        self.client(self.success()).create('v=0 offer', spec)
        sent = json.loads(self.calls[0].content)['session']
        self.assertEqual(sent['audio']['output']['voice']['id'], 'owner-custom-voice')
        self.assertEqual(sent['input'][0]['content'][0]['text'], 'Owner startup context')
        self.assertEqual(sent['client']['data_channel']['allowed_client_events'], ['session.close'])
        self.assertEqual(sent['delegation']['responses']['reasoning'], {'effort': 'low'})
        self.assertEqual(sent['delegation']['acknowledgement_delay_ms'], 400)
        for field in ['model', 'instructions', 'delegation']:
            with self.assertRaises(ValueError):
                session_spec('Owner', client_delegation=True, session_options={field: 'override'})

    def test_no_codex_json_or_login_token_is_used_as_api_key(self):
        for value in ['{"tokens":{"access_token":"synthetic"}}', 'ey-synthetic-login-token']:
            self.key.write_text(value)
            with self.assertRaises(LiveUnavailable) as failure:
                self.client(self.success()).create('v=0 offer', self.spec)
            self.assertEqual(failure.exception.outcome, 'project_key_unavailable')
        self.assertEqual(self.calls, [])

    def test_timeout_is_uncertain_and_is_never_retried(self):
        def timeout(request):
            raise httpx.ReadTimeout('sensitive provider details', request=request)
        client = self.client(timeout)
        with self.assertRaises(LiveUnavailable) as failure:
            client.create('v=0 offer', self.spec)
        self.assertEqual(str(failure.exception), 'creation_unconfirmed')
        with self.assertRaises(LiveUnavailable) as repeated:
            client.create('v=0 offer', self.spec)
        self.assertEqual(repeated.exception.outcome, 'creation_already_attempted')
        self.assertEqual(len(self.calls), 1)

    def test_rejection_server_error_and_redirect_keep_distinct_outcomes(self):
        for status, outcome in [(401, 'creation_rejected'), (429, 'creation_rejected'),
                                (408, 'creation_unconfirmed'), (503, 'creation_unconfirmed'),
                                (307, 'creation_unconfirmed')]:
            with self.subTest(status=status):
                with self.assertRaises(LiveUnavailable) as failure:
                    self.client(httpx.Response(status, text='private provider payload',
                        headers={'location': 'https://unselected.test/'})).create('v=0 offer', self.spec)
                self.assertEqual(failure.exception.outcome, outcome)
                self.assertEqual(failure.exception.status, status)
                self.assertNotIn('private', str(failure.exception))
        self.assertEqual(len(self.calls), 5)  # No redirected request.

    def test_malformed_or_oversized_success_is_uncertain_without_another_call(self):
        for body in [b'not JSON', b'{}', b'[]', b'x' * 131073]:
            client = self.client(httpx.Response(201, content=body))
            with self.assertRaises(LiveUnavailable) as failure:
                client.create('v=0 offer', self.spec)
            self.assertEqual(failure.exception.outcome, 'creation_unconfirmed')
            with self.assertRaises(LiveUnavailable):
                client.create('v=0 offer', self.spec)
        self.assertEqual(len(self.calls), 4)


class DurableCreation(unittest.TestCase):
    client = Creation.client
    success = Creation.success

    def setUp(self):
        Creation.setUp(self)
        self.root = Path(self.tmp.name) / 'visits'
        self.visits = LiveCreations(self.root)
        self.ident = str(uuid.uuid4())
        self.owner = {'binding': 'a' * 64,
            'entry_binding': [100, {'chat_id': 100, 'thread_id': 7}, 1, 'existing-thread'],
            'native_thread': 'existing-thread'}

    def create(self, client=None, ident=None, human=100, owner=None):
        return self.visits.create(ident or self.ident, human, owner or self.owner,
                                 'v=0 offer', self.spec, client or self.client(self.success()))

    def closed(self, ident=None, usage=None):
        event = {'type': 'session.closed', 'session': {'id': 'opaque:live/example'},
                 'reason': 'connection_lost', 'event_id': 'provider-closed-1'}
        if usage is not None:
            event['usage'] = {'seconds': usage}
        return self.visits.observe_closed(ident or self.ident, 100, self.owner, event)

    def test_exact_offer_retry_in_a_new_process_only_reads_the_receipt(self):
        first = self.create()
        reordered = {key: self.spec[key] for key in reversed(self.spec)}
        self.assertEqual(self.visits.create(self.ident, 100, self.owner, 'v=0 offer',
            reordered, self.client(self.success())), first)
        program = '''import json,sys
sys.path.insert(0,sys.argv[1])
from dashboard.openai_live_visits import LiveCreations
class Unexpected:
 def create(self,*a):raise AssertionError('A restart repeated the provider POST')
p=json.loads(sys.argv[2]);v=LiveCreations(p['root']).create(p['id'],100,p['owner'],'v=0 offer',p['spec'],Unexpected())
print(json.dumps({'id':v.session_id,'sdp':v.sdp}))
'''
        value = {'root': str(self.root), 'id': self.ident, 'owner': self.owner, 'spec': self.spec}
        raw = subprocess.check_output([sys.executable, '-B', '-c', program,
            str(Path(__file__).resolve().parents[1]), json.dumps(value)], timeout=10, text=True)
        self.assertEqual(json.loads(raw), {'id': first.session_id, 'sdp': first.sdp})
        self.assertEqual(len(self.calls), 1)

    def test_changed_owner_offer_or_spec_never_reuses_an_existing_creation(self):
        self.create()
        changed = {**self.owner, 'binding': 'b' * 64}
        for human, owner, offer, spec in [(200, self.owner, 'v=0 offer', self.spec),
            (100, changed, 'v=0 offer', self.spec),
            (100, self.owner, 'v=0 different', self.spec),
            (100, self.owner, 'v=0 offer', {**self.spec, 'instructions': 'changed'})]:
            with self.assertRaises(ValueError):
                self.visits.create(self.ident, human, owner, offer, spec, self.client(self.success()))
        with self.assertRaises(ValueError):
            self.visits.read(self.ident, 200, self.owner)
        self.assertEqual(len(self.calls), 1)

    def test_crash_after_durable_intent_is_not_permission_to_post_after_restart(self):
        class Interrupted:
            def create(self, *_):
                raise SystemExit('Synthetic process loss before observable POST')
        with self.assertRaises(SystemExit):
            self.create(Interrupted())
        self.visits = LiveCreations(self.root)
        self.assertEqual(self.visits.read(self.ident, 100, self.owner)['state'], 'creating')
        with self.assertRaises(LiveUnavailable) as failure:
            self.create()
        self.assertEqual(failure.exception.outcome, 'creation_unconfirmed')
        with self.assertRaises(LiveUnavailable) as next_id:
            self.create(ident=str(uuid.uuid4()))
        self.assertEqual(next_id.exception.outcome, 'prior_creation_needs_review')
        self.assertEqual(self.calls, [])

    def test_lost_response_remains_uncertain_without_another_call_or_id(self):
        def timeout(request):
            raise httpx.ReadTimeout('private response detail', request=request)
        with self.assertRaises(LiveUnavailable):
            self.create(self.client(timeout))
        self.visits = LiveCreations(self.root)
        for ident in [self.ident, str(uuid.uuid4())]:
            with self.assertRaises(LiveUnavailable):
                self.create(ident=ident)
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn('private response detail', self.visits._path(self.ident).read_text())

    def test_receipt_write_failure_after_http_success_keeps_original_uncertainty(self):
        write = self.visits._write
        def fail_receipt(value):
            if value['state'] == 'created':
                raise OSError('sensitive filesystem details')
            write(value)
        with patch.object(self.visits, '_write', fail_receipt):
            with self.assertRaises(LiveUnavailable) as failure:
                self.create()
        self.assertEqual(str(failure.exception), 'creation_unconfirmed')
        self.visits = LiveCreations(self.root)
        with self.assertRaises(LiveUnavailable):
            self.create()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.visits.read(self.ident, 100, self.owner)['state'], 'creating')

    def test_competing_writers_do_not_hold_the_filesystem_lock_across_http(self):
        entered, release = threading.Event(), threading.Event()
        def held(_):
            entered.set()
            self.assertTrue(release.wait(3))
            return self.success()
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(self.create, self.client(held))
            self.assertTrue(entered.wait(3))
            try:
                other = LiveCreations(self.root)
                with self.assertRaises(LiveUnavailable) as failure:
                    other.create(self.ident, 100, self.owner, 'v=0 offer', self.spec,
                                 self.client(self.success()))
                self.assertEqual(failure.exception.outcome, 'creation_unconfirmed')
            finally:
                release.set()
            self.assertEqual(pending.result(timeout=3).session_id, 'opaque:live/example')
        self.assertEqual(len(self.calls), 1)

    def test_wrong_terminal_session_is_refused_and_closed_call_cannot_restart(self):
        self.create()
        wrong = {'type': 'session.closed', 'session': {'id': 'other'}, 'reason': 'expired',
                 'event_id': 'provider-other-1'}
        with self.assertRaises(ValueError):
            self.visits.observe_closed(self.ident, 100, self.owner, wrong)
        with self.assertRaises(LiveUnavailable):
            self.create(ident=str(uuid.uuid4()))
        value = self.closed(usage=12.5)
        self.assertEqual(value['state'], 'closed')
        self.assertEqual(value['finalization']['usage_seconds'], 12.5)
        self.assertEqual(self.closed(usage=12.5), value)
        with self.assertRaises(ValueError):
            self.closed(usage=13)
        with self.assertRaises(LiveUnavailable) as failure:
            self.create()
        self.assertEqual(failure.exception.outcome, 'session_closed')
        self.create(ident=str(uuid.uuid4()))  # New provider creation, not a microphone admission.
        self.assertEqual(len(self.calls), 2)

    def test_confirmed_closure_and_missing_voice_usage_are_separate(self):
        self.create()
        value = self.closed()
        self.assertEqual(value['state'], 'closed')
        self.assertFalse(value['finalization']['voice_usage_confirmed'])
        self.assertIsNone(value['finalization']['usage_seconds'])
        self.assertNotIn('work_completed', value)
        reconciled = self.closed(usage=17)
        self.assertTrue(reconciled['finalization']['voice_usage_confirmed'])
        self.assertEqual(reconciled['finalization']['provider_event_id'], 'provider-closed-1')
        self.assertEqual(reconciled['finalization']['usage_event_id'], 'provider-closed-1')
        self.assertEqual(self.closed(), reconciled)  # A partial duplicate never downgrades known usage.
        self.assertEqual(len(self.calls), 1)

    def test_capacity_is_reserved_before_post_and_does_not_evict_receipts(self):
        self.visits.max_total_bytes = 2 * self.visits.max_record_bytes - 1
        with self.assertRaises(LiveUnavailable) as failure:
            self.create()
        self.assertEqual(failure.exception.outcome, 'creation_storage_full')
        self.assertEqual(self.calls, [])
        self.visits.max_total_bytes = LiveCreations.max_total_bytes
        self.visits.max_records = 1
        self.create()
        before = self.visits._path(self.ident).read_bytes()
        self.closed()
        retained = self.visits._path(self.ident).read_bytes()
        self.assertNotEqual(before, retained)
        with self.assertRaises(LiveUnavailable) as full:
            self.create(ident=str(uuid.uuid4()))
        self.assertEqual(full.exception.outcome, 'creation_storage_full')
        self.assertEqual(self.visits._path(self.ident).read_bytes(), retained)
        self.assertEqual(len(self.calls), 1)

    def test_active_capacity_is_shared_across_distinct_human_owners(self):
        self.create()
        other = {**self.owner, 'entry_binding': [200, {'chat_id': 200}, 2, 'existing-thread']}
        self.create(ident=str(uuid.uuid4()), human=200, owner=other)
        third = {**self.owner, 'entry_binding': [300, {'chat_id': 300}, 3, 'existing-thread']}
        with self.assertRaises(LiveUnavailable) as full:
            self.create(ident=str(uuid.uuid4()), human=300, owner=third)
        self.assertEqual(full.exception.outcome, 'public_voice_capacity')
        self.assertEqual(len(self.calls), 2)

    def test_trusted_sideband_attaches_to_retained_owner_and_commits_final_usage(self):
        self.create()
        frames = [json.dumps({'type': 'session.closed', 'session': {'id': 'opaque:live/example'},
                             'reason': 'expired', 'event_id': 'provider-expired-1',
                             'usage': {'seconds': 19}})]
        socket = SidebandSocket(frames)
        attached = []
        def connect(url, **kwargs):
            attached.append((url, kwargs))
            return socket
        sideband = self.visits.attach(self.ident, 100, self.owner,
            self.client(self.success()), connect=connect)
        self.assertEqual(attached[0][0],
            'wss://api.openai.com/v1/live/sessions/opaque%3Alive%2Fexample/attach')
        self.assertEqual(sideband.session_id, 'opaque:live/example')
        self.assertEqual(socket.sent, [])  # No second session.start or POST.
        value = self.visits.observe_closed(self.ident, 100, self.owner, sideband.receive())
        self.assertTrue(value['finalization']['voice_usage_confirmed'])
        self.assertEqual(value['finalization']['usage_seconds'], 19)
        sideband.detach()
        self.assertTrue(socket.closed)
        self.assertEqual(socket.sent, [])  # Detach never sends session.close.
        with self.assertRaises(LiveUnavailable):
            self.visits.attach(self.ident, 100, self.owner, self.client(self.success()), connect=connect)
        self.assertEqual(len(attached), 1)
        self.assertEqual(len(self.calls), 1)

    def test_missing_provider_event_id_is_not_terminal_evidence(self):
        self.create()
        event = {'type': 'session.closed', 'session': {'id': 'opaque:live/example'},
                 'reason': 'expired', 'usage': {'seconds': 3}}
        with self.assertRaises(ValueError):
            self.visits.observe_closed(self.ident, 100, self.owner, event)
        self.assertEqual(self.visits.read(self.ident, 100, self.owner)['state'], 'created')

    def test_receipt_growth_includes_temporary_bytes_and_preserves_previous_receipt(self):
        self.create()
        self.closed()
        path = self.visits._path(self.ident)
        before = path.read_bytes()
        self.visits.max_total_bytes = len(before) + 1
        with self.assertRaises(ValueError):
            self.closed(usage=17)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.visits.read(self.ident, 100, self.owner)['finalization']['voice_usage_confirmed'])
        self.assertEqual(len(self.calls), 1)


class SidebandSocket:
    def __init__(self, frames=()):
        self.frames = list(frames)
        self.sent = []
        self.closed = False
        self.write_error = False
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)

    def recv(self):
        if not self.frames:
            raise TimeoutError()
        return self.frames.pop(0)

    def send(self, raw):
        self.sent.append(json.loads(raw))
        if self.write_error:
            raise OSError('private transport details')

    def close(self):
        self.closed = True


class Sideband(unittest.TestCase):
    def test_timeout_detach_and_frame_bounds_do_not_finalize_or_dispatch_work(self):
        socket = SidebandSocket()
        channel = LiveSideband('opaque', socket)
        self.assertIsNone(channel.receive())
        for raw, outcome in [('[]', 'sideband_event_invalid'),
                             ('not JSON', 'sideband_event_invalid'),
                             ('x' * (channel.max_event_bytes + 1), 'sideband_event_exceeds_bound'),
                             ('', 'sideband_closed')]:
            socket.frames.append(raw)
            with self.assertRaises(LiveUnavailable) as failure:
                channel.receive()
            self.assertEqual(failure.exception.outcome, outcome)
        channel.detach()
        channel.detach()
        self.assertEqual(socket.sent, [])
        with self.assertRaises(LiveUnavailable):
            channel.receive()

    def test_command_failure_is_uncertain_and_never_retried_or_auto_closed(self):
        socket = SidebandSocket([json.dumps({'type': 'session.instructions.appended',
                                           'client_event_id': 'one'})])
        channel = LiveSideband('opaque', socket)
        with self.assertRaises(ValueError):
            channel.send({'type': 'session.start'})
        socket.write_error = True
        command = {'type': 'session.instructions.append', 'event_id': 'one',
                   'delegation_id': None, 'content': 'Owner context'}
        with self.assertRaises(LiveUnavailable) as failure:
            channel.send(command)
        self.assertEqual(str(failure.exception), 'command_unconfirmed')
        with self.assertRaises(LiveUnavailable):
            channel.send(command)
        self.assertEqual(socket.sent, [command])
        self.assertEqual(channel.receive()['client_event_id'], 'one')
        channel.detach()
        self.assertEqual(socket.sent, [command])


if __name__ == '__main__':
    unittest.main()
