"""Native result source association, pagination and context ACKs; no models."""
import copy
from pathlib import Path
import sys
import threading
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dashboard.openai_live_native_results import return_native_part
from dashboard.openai_live_visits import LiveCreations
from dashboard.provider import ProviderUnavailable
import dashboard_openai_live_native_work as fixtures


class NativeResults(unittest.TestCase):
    setUp = fixtures.NativeWork.setUp
    create = fixtures.NativeWork.create
    client = fixtures.NativeWork.client
    success = fixtures.NativeWork.success
    prepare = fixtures.NativeWork.prepare
    enroll = fixtures.NativeWork.enroll
    ready = fixtures.NativeWork.ready
    recognizer = fixtures.NativeWork.recognizer
    run_original = fixtures.NativeWork.run_original
    setup_commit = fixtures.NativeWork.setup_commit
    commit = fixtures.NativeWork.commit
    ready_work = fixtures.NativeWork.ready_work
    delegate = fixtures.NativeWork.delegate

    def ready_result(self, text='El resultado verificado es Río Cobre.'):
        self.ready_work(); self.delegate()
        self.provider.retained[self.receipt['id']]['local_turn'] = 42
        self.source = 'native:77'; self.revision = 'd' * 64; self.text = text
        self.source_fields = {'kind':'integrator_answer','local_turn':42,
            'entry_binding':self.owner['entry_binding'][:3]+[self.owner['binding']],
            'native_binding_current':True,'current':None,'correction_pending':None}
        def part(source, revision, offset):
            assert source == self.source and revision == self.revision
            return dict(self.source_fields, id=source, revision=revision, offset=offset,
                text=self.text[offset:offset+1600],
                next_offset=offset+1600 if offset+1600 < len(self.text) else None)
        self.provider.presentation_part = part
        self.updates = []
        test = self
        class Sideband:
            def send(self, command): test.updates.append(copy.deepcopy(command))
        self.channel = Sideband()

    def emit(self, offset=0, history=None, **options):
        return return_native_part(history or self.visits,self.ident,100,self.owner,
            self.delegation,self.source,self.revision,offset,self.provider,self.channel,**options)

    def acknowledge(self, index=-1, **changes):
        command = self.updates[index]
        self.ack_count = getattr(self, 'ack_count', 0) + 1
        return self.visits.event(self.ident,100,self.owner,dict({
            'type':command['type']+'ed','event_id':'ack-'+str(self.ack_count),
            'client_event_id':command['event_id']}, **changes))

    def test_verified_source_once_then_context_ack_is_not_hearing(self):
        self.ready_result(); result = self.emit()
        self.assertEqual(result['state'],'sent'); self.assertEqual(result['hearing'],'not_observed')
        self.assertFalse(result['work_completed'])
        self.assertEqual(self.updates[0]['type'],'session.commentary.append')
        self.assertEqual(self.updates[0]['delegation_id'],self.delegation)
        self.assertIn(self.text,self.updates[0]['content'])
        self.assertEqual(self.emit(),result)
        self.acknowledge()
        result = self.emit(history=LiveCreations(self.root))
        self.assertEqual(result['state'],'context_injected'); self.assertEqual(result['hearing'],'not_observed')
        self.assertEqual(len(self.updates),1); self.assertEqual(len(self.writes),1)

    def test_unicode_long_source_exact_cursors_no_skip_and_bounded_appends(self):
        self.ready_result('Río 🌊: ' * 180)
        result = self.emit(); self.assertGreater(result['next_offset'],0)
        self.assertLessEqual(len(self.updates[0]['content'].encode()),500)
        self.assertIn('(partial; more remains)',self.updates[0]['content'])
        with self.assertRaises(ValueError): self.emit(result['next_offset'])
        offset = 0; recovered = ''
        while True:
            result = self.emit(offset)
            recovered += self.updates[-1]['content'].split('\n',1)[1]
            self.acknowledge()
            if result['next_offset'] is None: break
            offset = result['next_offset']
        self.assertEqual(recovered,self.text)
        self.assertTrue(all(len(row['content'].encode())<=500 for row in self.updates))
        with self.assertRaises(ValueError): self.emit(1234)

    def test_lost_socket_send_never_resends_after_restart_or_later_source(self):
        self.ready_result('a' * 600)
        def lost(command): self.updates.append(command); raise OSError('Synthetic lost send')
        self.channel.send = lost
        self.assertEqual(self.emit()['state'],'unconfirmed')
        self.assertEqual(self.emit(history=LiveCreations(self.root))['state'],'intent')
        self.assertEqual(len(self.updates),1)
        with self.assertRaises(ValueError): self.emit(384)

    def test_foreign_stale_prior_turn_or_unbound_worker_never_sends(self):
        self.ready_result()
        for changes in ({'entry_binding':[1,2,3,4]}, {'local_turn':41},
                {'current':False}, {'correction_pending':True}, {'native_binding_current':False}):
            fields = dict(self.source_fields); self.source_fields.update(changes)
            with self.assertRaises(ValueError): self.emit()
            self.source_fields = fields
        self.source='delivery:00000000-0000-4000-8000-000000000001'
        self.source_fields.update(kind='worker_result',current=True)
        self.provider.conversation_input_trace=lambda root:{'id':root,'entry_binding':self.owner['entry_binding'],'routes':[]}
        with self.assertRaises(ValueError): self.emit()
        self.assertEqual(self.updates,[])

    def test_worker_result_requires_current_covered_original_request(self):
        self.ready_result(); self.source='delivery:00000000-0000-4000-8000-000000000001'
        self.source_fields.update(kind='worker_result',current=True)
        result={'source':self.source,'instruction_covered':False,'current':True,'correction_pending':False}
        self.provider.conversation_input_trace=lambda root:{'id':root,'entry_binding':self.owner['entry_binding'],
            'routes':[{'target_available':True,'results':[result]}]}
        with self.assertRaises(ValueError): self.emit()
        result['instruction_covered']=True
        self.assertEqual(self.emit()['state'],'sent')
        self.assertEqual(len(self.writes),1)

    def test_preexisting_native_answer_in_the_same_turn_is_not_a_new_result(self):
        self.ready_result()
        value = self.visits.read(self.ident,100,self.owner)
        value['delegations'][self.delegation]['native_work']['native_source_floor'] = 77
        self.visits._write(value)
        with self.assertRaises(ValueError): self.emit()
        self.assertEqual(self.updates,[])

    def test_bounded_spoken_fragment_does_not_split_an_ordinary_word(self):
        self.ready_result('dato '*75+'corrección nueva. '+'resultado '*30)
        receipt=self.emit();fragment=self.updates[0]['content'].split('\n',1)[1]
        self.assertEqual(fragment,self.text[:receipt['next_offset']])
        self.assertTrue(fragment[-1].isspace())
        self.assertTrue(self.text[receipt['next_offset']:].startswith('corrección nueva.'))

    def test_progress_is_quiet_and_unmatched_ack_cannot_advance_cursor(self):
        self.ready_result('b' * 600); self.source_fields['kind']='integrator_progress'
        result = self.emit()
        self.assertEqual(self.updates[0]['type'],'session.thinking.append')
        self.acknowledge(client_event_id='unrelated')
        with self.assertRaises(ValueError): self.emit(result['next_offset'])
        self.acknowledge(type='session.commentary.appended')
        with self.assertRaises(ValueError): self.emit(result['next_offset'])
        self.acknowledge()
        self.assertEqual(self.emit(result['next_offset'])['state'],'sent')

    def test_revocation_after_send_does_not_expose_or_repeat_receipt(self):
        self.ready_result(); send = self.channel.send
        def revoked(command): send(command); self.provider.allowed=False
        self.channel.send = revoked
        with self.assertRaises(ProviderUnavailable): self.emit()
        self.provider.allowed=True
        self.assertEqual(self.emit()['state'],'sent'); self.assertEqual(len(self.updates),1)

    def test_injection_ack_racing_socket_send_receipt_cannot_be_downgraded(self):
        self.ready_result(); send = self.channel.send
        def acknowledged(command): send(command); self.acknowledge()
        self.channel.send = acknowledged
        self.assertEqual(self.emit()['state'],'context_injected')
        self.assertEqual(self.emit()['state'],'context_injected'); self.assertEqual(len(self.updates),1)

    def test_result_capacity_and_restart_refuse_before_a_new_send(self):
        self.ready_result()
        with self.assertRaises(ValueError): self.emit(history=LiveCreations(self.root))
        value=self.visits.read(self.ident,100,self.owner)
        value['native_result_updates']={str(n):{} for n in range(128)}
        self.visits._write(value)
        with self.assertRaises(ValueError): self.emit()
        self.assertEqual(self.updates,[])

    def test_close_during_canonical_read_refuses_a_new_append_intent(self):
        self.ready_result();stopped=threading.Event();part=self.provider.presentation_part
        def close(*args):
            value=part(*args);stopped.set();return value
        self.provider.presentation_part=close
        with self.assertRaises(ValueError):self.emit(stopped=stopped)
        self.assertEqual(self.updates,[])
        self.assertEqual(self.visits.read(self.ident,100,self.owner).get('native_result_updates',{}),{})

    def test_close_after_intent_records_known_unsent_without_retry(self):
        self.ready_result();stopped=threading.Event();write=self.visits._write
        def stop(value):
            write(value)
            if value.get('native_result_updates'):stopped.set()
        self.visits._write=stop
        self.assertEqual(self.emit(stopped=stopped)['state'],'not_sent')
        self.assertEqual(self.updates,[])
        stopped.clear()
        self.assertEqual(self.emit()['state'],'not_sent')
        self.assertEqual(self.updates,[],'A known unsent close outcome is not a new append permission')


if __name__ == '__main__': unittest.main()
