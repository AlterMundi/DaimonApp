"""Client delegation source/intent ownership; synthetic native execution only."""
import copy
import hashlib
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dashboard.openai_live_native_work import delegate_native
from dashboard.openai_live import session_spec
from dashboard.openai_live_visits import LiveCreations
from dashboard.provider import ProviderUnavailable
import dashboard_openai_live_native_commit as fixtures


class NativeWork(unittest.TestCase):
    def setUp(self):
        fixtures.NativeCommit.setUp(self)
        self.spec = session_spec('Synthetic client delegation only.', client_delegation=True)
    create = fixtures.NativeCommit.create
    client = fixtures.NativeCommit.client
    success = fixtures.NativeCommit.success
    prepare = fixtures.NativeCommit.prepare
    enroll = fixtures.NativeCommit.enroll
    ready = fixtures.NativeCommit.ready
    recognizer = fixtures.NativeCommit.recognizer
    run_original = fixtures.NativeCommit.run_original
    setup_commit = fixtures.NativeCommit.setup_commit
    commit = fixtures.NativeCommit.commit

    def ready_work(self):
        self.setup_commit(); self.commit()
        self.delegation = 'client-delegation-1'
        self.formulation = 'Apply the correction in the retained original. This is an assistant formulation.'
        self.visits.event(self.ident, 100, self.owner, {
            'type': 'session.delegation.created', 'event_id': 'source-delegation-1',
            'offset_ms': 200, 'delegation': {'id': self.delegation, 'target': 'client'}})
        self.writes = []
        self.provider.presentation_list = lambda *args: {'binding':self.owner['binding'],'newest':{'native':0}}
        def write(body):
            self.writes.append(copy.deepcopy(body))
            native = self.provider.retained[body['id']]
            native.update(phase='queued', foreground_delegation={
                'intent_id': body['intent_id'], 'dialogue_id': self.ident,
                'formulation': body['formulation'], 'sources': [{
                    'id': source, 'capture_order': index + 1,
                    'text': self.provider.retained[source]['text'],
                    'text_sha256': hashlib.sha256(self.provider.retained[source]['text'].encode()).hexdigest(),
                    'voice': copy.deepcopy(self.provider.retained[source]['voice'])}
                    for index, source in enumerate(body['source_ids'])]})
            return copy.deepcopy(native)
        self.provider.conversation_foreground_delegate = write

    def delegate(self, history=None, ordinals=None, formulation=None, delegation=None):
        return delegate_native(history or self.visits, self.ident, 100, self.owner,
            delegation or self.delegation, [0] if ordinals is None else ordinals,
            self.formulation if formulation is None else formulation, self.provider)

    def test_exact_source_formulation_once_and_restart_observation(self):
        self.ready_work(); result = self.delegate()
        self.assertEqual(result['state'], 'observed'); self.assertFalse(result['work_completed'])
        self.assertEqual(self.writes[0]['source_ids'], [self.receipt['id']])
        self.assertEqual(self.writes[0]['binding'], self.owner['binding'])
        self.assertEqual(self.delegate(LiveCreations(self.root)), result)
        self.assertEqual(len(self.writes), 1); self.assertEqual(len(self.sent), 1)
        self.assertNotIn('native_work_reserve', self.visits.read(self.ident,100,self.owner)['delegations'][self.delegation])
        with self.assertRaises(ValueError): self.delegate(formulation='A replacement request')

    def test_lost_ack_reconciles_only_same_original_without_replay(self):
        self.ready_work(); write = self.provider.conversation_foreground_delegate
        def lost(body): write(body); raise ProviderUnavailable()
        self.provider.conversation_foreground_delegate = lost
        self.assertEqual(self.delegate()['state'], 'unconfirmed')
        self.assertEqual(self.delegate(LiveCreations(self.root))['state'], 'observed')
        self.assertEqual(len(self.writes), 1)

    def test_unavailable_status_and_unknown_write_never_repeat(self):
        self.ready_work()
        def unknown(body): self.writes.append(body); raise ProviderUnavailable()
        self.provider.conversation_foreground_delegate = unknown
        self.assertEqual(self.delegate()['state'], 'unconfirmed')
        self.provider.conversation_input_status = lambda ident: (_ for _ in ()).throw(ProviderUnavailable())
        self.assertEqual(self.delegate(LiveCreations(self.root))['state'], 'unconfirmed')
        self.assertEqual(len(self.writes), 1)

    def test_revocation_after_native_write_preserves_ack_not_exposure(self):
        self.ready_work(); write = self.provider.conversation_foreground_delegate
        def revoked(body): result = write(body); self.provider.allowed = False; return result
        self.provider.conversation_foreground_delegate = revoked
        with self.assertRaises(ProviderUnavailable): self.delegate()
        state = self.visits.read(self.ident,100,self.owner)['delegations'][self.delegation]['native_work']
        self.assertEqual(state['state'], 'observed')
        self.provider.allowed = True
        self.assertEqual(self.delegate()['state'], 'observed'); self.assertEqual(len(self.writes),1)

    def test_fragment_uncommitted_source_and_restarted_admission_cannot_start_work(self):
        self.ready_work()
        with self.assertRaises(ValueError): self.delegate(delegation='only-a-transcript-fragment')
        with self.assertRaises(ValueError): self.delegate(ordinals=[True])
        with self.assertRaises(ValueError): self.delegate(ordinals=list(range(9)))
        with self.assertRaises(ValueError): self.delegate(ordinals=[0,0])
        value = self.visits.read(self.ident,100,self.owner)
        value['native_originals']['0']['native_commit']['state'] = 'intent'
        self.visits._write(value)
        with self.assertRaises(ValueError): self.delegate()
        value['native_originals']['0']['native_commit']['state'] = 'observed'
        self.visits._write(value)
        with self.assertRaises(ValueError): self.delegate(LiveCreations(self.root))
        self.assertEqual(self.writes, [])

    def test_receipt_reserve_is_required_before_native_write(self):
        self.ready_work()
        value = self.visits.read(self.ident,100,self.owner)
        import json
        self.visits.max_record_bytes = len(json.dumps(value).encode()) + 100
        with self.assertRaises(ValueError): self.delegate()
        self.assertEqual(self.writes, [])

    def test_changed_native_source_proof_is_not_admission(self):
        self.ready_work(); write = self.provider.conversation_foreground_delegate
        def wrong(body):
            result = write(body)
            result['foreground_delegation']['sources'][0]['text'] = 'Different human instruction'
            return result
        self.provider.conversation_foreground_delegate = wrong
        with self.assertRaises(ValueError): self.delegate()
        self.assertEqual(self.delegate()['state'], 'observed')  # Read retained exact receipt, no repeat.
        self.assertEqual(len(self.writes), 1)

    def test_native_latest_correction_rejection_is_not_bypassed(self):
        self.ready_work()
        def superseded(body): self.writes.append(body); raise ValueError('Later captured correction')
        self.provider.conversation_foreground_delegate = superseded
        self.assertEqual(self.delegate()['state'], 'unconfirmed')
        with self.assertRaises(ValueError): self.delegate()  # No matching native delegation.
        self.assertEqual(len(self.writes), 1)

    def test_another_delegation_cannot_resubmit_the_same_root(self):
        self.ready_work(); self.delegate()
        self.visits.event(self.ident,100,self.owner, {'type':'session.delegation.created',
            'event_id':'source-delegation-2', 'delegation':{'id':'client-delegation-2','target':'client'}})
        with self.assertRaises(ValueError): self.delegate(delegation='client-delegation-2')
        self.assertEqual(len(self.writes), 1)

    def test_capture_seal_must_be_acknowledged_before_native_work(self):
        from dashboard.openai_live_seals import request_seal, accept_seal
        self.ready_work()
        command=request_seal(self.visits,self.ident,100,self.owner,self.delegation,self.provider)
        with self.assertRaises(ValueError):self.delegate()
        self.assertEqual(self.writes,[])
        accept_seal(self.visits,self.ident,100,self.owner,{'type':'source_sealed',
            'request':command['request'],'through_ordinal':1,'capture_bytes':len(self.audio)-44},self.provider)
        self.assertEqual(self.delegate()['state'],'observed')


if __name__ == '__main__': unittest.main()
