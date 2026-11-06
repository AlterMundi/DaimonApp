"""Public GPT-Live creation boundaries, synthetic HTTP only; no provider calls."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.openai_live import LiveUnavailable, OpenAILive, session_spec


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


if __name__ == '__main__':
    unittest.main()
