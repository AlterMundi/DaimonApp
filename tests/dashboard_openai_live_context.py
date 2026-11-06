"""Managed tool return, current-owner context and uncertainty; no provider calls."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dashboard_openai_live as fixtures
from dashboard.openai_live_context import NAME, read_context, serve_context
from dashboard.openai_live_visits import LiveCreations
from dashboard.provider import ProviderUnavailable


class Context(unittest.TestCase):
    setUp = fixtures.DurableCreation.setUp
    create = fixtures.DurableCreation.create
    client = fixtures.DurableCreation.client
    success = fixtures.DurableCreation.success

    def args(self, **change):
        return dict(operation='page', delivery=0, native=0, matrix=0,
                    source='', revision='', offset=0) | change

    def provider(self):
        test = self
        class Owner:
            def authorized(self, human): return human == 100
            def public_live_binding(self, binding): return dict(test.owner)
            def presentation_list(self, delivery, native, direction, matrix):
                return {'binding': test.owner['binding'], 'items': [{'id': 'native:42',
                    'revision': 'c'*64, 'preview': 'Corrected project is Copper River.',
                    'label': 'CompAII', 'kind': 'assistant', 'completed': True}],
                    'cursor': {'delivery': 4, 'native': 42, 'matrix': 0}, 'more': True}
            def presentation_part(self, source, revision, offset):
                return {'id': source, 'revision': revision, 'offset': offset,
                        'text': 'Corrected project is Copper River.', 'next_offset': None}
        return Owner()

    def observe(self, nested, source):
        return self.visits.event(self.ident, 100, self.owner, {'type': 'response.event',
            'event_id': source, 'delegation_id': 'work', 'event': nested})

    def task(self):
        self.visits.prepare(self.ident, 100, self.owner)
        self.create()
        self.visits.event(self.ident, 100, self.owner, {'type': 'session.delegation.created',
            'event_id': 'work', 'delegation': {'id': 'work', 'target': 'responses', 'response_id': 'r1'}})

    def call(self, ident='call', **change):
        item = {'type': 'function_call', 'call_id': ident, 'name': NAME,
                'arguments': json.dumps(self.args())} | change
        self.observe({'type': 'response.output_item.done', 'item': item}, ident)

    def complete(self, response='r1', source='done'):
        self.observe({'type': 'response.completed', 'response': {'id': response}}, source)

    def test_exact_context_pages_parts_and_changed_audience(self):
        provider = self.provider()
        page = json.loads(read_context(provider, self.owner, self.args()))
        self.assertTrue(page['more']); self.assertEqual(page['cursor']['native'], 42)
        source = page['items'][0]
        part = json.loads(read_context(provider, self.owner, self.args(operation='part',
            source=source['id'], revision=source['revision'])))
        self.assertIn('Copper River', part['text']); self.assertTrue(part['source_data'])
        provider.authorized = lambda _: False
        with self.assertRaises(ProviderUnavailable): read_context(provider, self.owner, self.args())

    def test_two_results_then_one_continuation_and_trusted_completion(self):
        self.task(); self.call('a'); self.call('b'); self.complete()
        sent = []
        class Sideband:
            def send(self, command): sent.append(command)
        serve_context(self.visits, self.ident, 100, self.owner, self.provider(), Sideband(), 'work')
        self.assertEqual([c['type'] for c in sent], ['response.item.create']*2 + ['response.create'])
        self.assertEqual([c['item']['call_id'] for c in sent[:2]], ['a', 'b'])
        self.assertIsNone(self.visits.close_intent(self.ident, 100, self.owner))
        # A restarted reader or duplicate completion cannot repeat a command.
        restarted = LiveCreations(self.root)
        serve_context(restarted, self.ident, 100, self.owner, self.provider(), Sideband(), 'work')
        self.assertEqual(len(sent), 3)
        self.observe({'type': 'response.created', 'response': {'id': 'r2'}}, 'new-response')
        with self.assertRaises(ValueError): self.complete('r1', 'late-old-completion')
        self.assertIsNone(self.visits.close_intent(self.ident, 100, self.owner))
        self.complete('r2', 'new-completion')
        self.assertEqual(self.visits.close_intent(self.ident, 100, self.owner)['type'], 'session.close')

    def test_lost_result_write_is_preserved_without_retry_or_close(self):
        self.task(); self.call(); self.complete(); sent = []
        class Sideband:
            def send(self, command):
                sent.append(command); raise OSError('synthetic lost write')
        with self.assertRaises(OSError):
            serve_context(self.visits, self.ident, 100, self.owner, self.provider(), Sideband(), 'work')
        serve_context(LiveCreations(self.root), self.ident, 100, self.owner, self.provider(), Sideband(), 'work')
        self.assertEqual(len(sent), 1)
        value = self.visits.read(self.ident, 100, self.owner)
        self.assertEqual(value['client_calls']['call']['state'], 'result_intent')
        self.assertIsNone(self.visits.close_intent(self.ident, 100, self.owner))

    def test_unknown_tools_arguments_only_and_call_mutation_never_execute(self):
        self.task(); sent = []
        class Sideband:
            def send(self, command): sent.append(command)
        self.observe({'type': 'response.function_call_arguments.done', 'name': NAME,
            'arguments': json.dumps(self.args())}, 'arguments-only')
        self.complete()
        serve_context(self.visits, self.ident, 100, self.owner, self.provider(), Sideband(), 'work')
        self.assertEqual(sent, [])
        self.call(name='unconfigured_shell')
        serve_context(self.visits, self.ident, 100, self.owner, self.provider(), Sideband(), 'work')
        self.assertEqual(sent, [])
        with self.assertRaises(ValueError): self.call(arguments='{"changed":true}')
        self.assertIsNone(self.visits.close_intent(self.ident, 100, self.owner))

    def test_limits_and_exact_part_selection(self):
        self.task()
        for index in range(16): self.call(str(index))
        with self.assertRaises(ValueError): self.call('overflow')
        provider = self.provider()
        provider.presentation_part = lambda *_: {'id': 'native:OTHER', 'revision': 'c'*64, 'offset': 0}
        with self.assertRaises(ProviderUnavailable):
            read_context(provider, self.owner, self.args(operation='part', source='native:42', revision='c'*64))
        with self.assertRaises(ValueError): read_context(provider, self.owner, self.args(native=True))


if __name__ == '__main__': unittest.main()
