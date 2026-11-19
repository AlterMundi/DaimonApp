"""Dispatch claims and native-return lineage use actual SQLite transactions."""
import concurrent.futures
import asyncio
import threading
import json
import sys
from pathlib import Path
import tempfile
import unittest
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dashboard.atelier_workshop import AtelierWorkshop, AtelierConflict
from dashboard_atelier_workshop import fixtures
from dashboard.atelier_workshop_api import install
from dashboard.atelier_native import digest
from dashboard.provider import ProviderUnavailable
from fastapi import FastAPI
import httpx


class DispatchStore(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.f = fixtures()
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = AtelierWorkshop(self.tmp.name); self.ident = self.f['id']
        self.store.save_request(100, self.f['request'])
        self.body = {'id': str(uuid.uuid4()), 'binding': 'b' * 64, 'text': 'Explicit chosen request',
                     'reply': {'source': 'session:selected', 'revision': 'r'}, 'files': []}
    def prepare(self):
        return self.store.prepare_dispatch(100, self.ident, 'c' * 64, 'Chosen session', self.body)
    def test_concurrent_claim_has_one_winner_and_frozen_retry(self):
        first = self.prepare(); before = self.store.snapshot(100)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.store.claim_dispatch(100, self.ident), range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(self.prepare()['body'], first['body'])
        self.assertEqual(self.store.snapshot(100), before)
        with self.assertRaises(AtelierConflict):
            self.store.prepare_dispatch(100, self.ident, 'd' * 64, 'Other', self.body)
        self.assertIsNone(self.store.dispatch(200, self.ident))
    def test_dispatch_quota_failure_does_not_claim_or_change_original(self):
        before = self.store.snapshot(100); original = self.store.get(100, self.ident)
        self.store.max_actor_bytes = 1
        with self.assertRaises(ValueError): self.prepare()
        self.assertIsNone(self.store.dispatch(100, self.ident))
        self.assertEqual(self.store.snapshot(100), before)
        self.assertEqual(self.store.get(100, self.ident), original)
    def test_native_origin_and_proposal_commit_or_refuse_together(self):
        self.prepare(); before = self.store.snapshot(100)
        origin = {'inputId': str(uuid.uuid4()), 'artifactId': str(uuid.uuid4()),
                  'source': 'delivery:' + str(uuid.uuid4()), 'revision': 'a' * 64, 'sha256': 'e' * 64}
        with self.assertRaises(AtelierConflict):
            self.store.save_reply(100, self.ident, self.f['reply'], native_origin=origin)
        self.assertNotIn('reply', self.store.get(100, self.ident))
        self.assertEqual(self.store.snapshot(100), before)
        origin['inputId'] = self.body['id']
        result = self.store.save_reply(100, self.ident, self.f['reply'], native_origin=origin)
        self.assertEqual(result['reply'], self.f['reply'])
        self.assertEqual(self.store.dispatch(100, self.ident)['origin'], origin)
        self.assertEqual(self.store.save_reply(100, self.ident, self.f['reply'], native_origin=origin), result)

    def test_cancelled_caller_finishes_one_claimed_write_and_status_recovers(self):
        entered, release = threading.Event(), threading.Event()
        class Peer:
            calls = 0
            ref = {'source': 'session:synthetic', 'revision': 'a' * 64}
            def authorized(self, human): return human == 100
            def check_reply(self, ref): assert ref == self.ref
            def session_workspace(self): return {'destinations_state': 'available', 'sessions': [{'id': 'a' * 24, 'title': 'Chosen', 'destination': self.ref}]}
            def conversation_inputs(self): return {'binding': 'b' * 64}
            def conversation_file_upload(self, data, ref): return ref
            def conversation_input_submit(self, body):
                self.calls += 1; entered.set(); assert release.wait(5)
                self.receipt = {'id': body['id'], 'phase': 'accepted', 'native_acceptance': 'observed'}
                return self.receipt
            def conversation_input_status(self, ident):
                if not hasattr(self, 'receipt'): raise ProviderUnavailable('Not confirmed yet')
                return self.receipt
        peer = Peer(); app = FastAPI()
        def authorize(request): return {'human': 100, 'scope': 'interaction_only', 'csrf': 'fresh', 'workspace_access': True}
        async def async_authorize(request): return authorize(request)
        store = install(app, {'state_dir': self.tmp.name}, peer, async_authorize, ['https://example.test'], authorize_sync=authorize)
        async def scenario():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://example.test') as client:
                headers = {'origin': 'https://example.test', 'x-dashboard-csrf': 'fresh'}
                body = {'action': 'dispatch', 'requestId': self.ident, 'choice': digest(['a' * 24, peer.ref])}
                task = asyncio.create_task(client.post('/api/interaction/atelier', json=body, headers=headers))
                try:
                    assert await asyncio.to_thread(entered.wait, 5)
                    task.cancel(); release.set()
                    with self.assertRaises(asyncio.CancelledError): await task
                    result = await client.get('/api/interaction/atelier/requests/' + self.ident + '/native')
                    self.assertTrue(result.json()['accepted'])
                    duplicate = await client.post('/api/interaction/atelier', json=body, headers=headers)
                    self.assertEqual(duplicate.status_code, 200)
                    self.assertEqual(peer.calls, 1)
                    self.assertEqual(store.dispatch(100, self.ident)['receipt']['inputId'], result.json()['inputId'])
                finally: release.set()
        asyncio.run(scenario())


if __name__ == '__main__': unittest.main()
