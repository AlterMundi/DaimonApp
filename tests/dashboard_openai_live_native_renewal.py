"""Old native work, fresh voice context, flat receipts; zero providers/models."""
import copy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from dashboard.openai_live_native_results import return_native_part
from dashboard.openai_live_native_backend import return_next_native_part,return_one_native_part
from dashboard.openai_live_visits import LiveCreations
from dashboard.provider import ProviderUnavailable
import dashboard_openai_live_native_results as fixtures


class Renewal(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.NativeResults('test_verified_source_once_then_context_ack_is_not_hearing')
        self.f.setUp();self.addCleanup(self.f.doCleanups);self.f.ready_result()
        self.origin=self.current=self.f.ident

    def replacement(self):
        f=self.f
        f.visits.observe_closed(self.current,100,f.owner,{'type':'session.closed',
            'event_id':str(uuid.uuid4()),'session':{'id':'opaque:live/example'},'reason':'close_requested'})
        self.current=str(uuid.uuid4())
        f.visits.prepare(self.current,100,f.owner,backend_mode='native');f.create(ident=self.current)
        return self.current

    def emit(self,offset=0):
        f=self.f
        return return_native_part(f.visits,self.current,100,f.owner,f.delegation,
            f.source,f.revision,offset,f.provider,f.channel,source_visit=self.origin)

    def ack(self):
        f=self.f;command=f.updates[-1]
        f.visits.event(self.current,100,f.owner,{'type':command['type']+'ed',
            'event_id':str(uuid.uuid4()),'client_event_id':command['event_id']})

    def test_late_result_uses_original_work_proof_and_no_foreign_delegation_id(self):
        target=self.replacement();result=self.emit()
        self.assertEqual(result['state'],'sent');self.assertEqual(len(self.f.updates),1)
        self.assertIsNone(self.f.updates[0]['delegation_id'])
        self.assertIn('Río Cobre',self.f.updates[0]['content'])
        original=self.f.visits.read(self.origin,100,self.f.owner)
        day=datetime.fromtimestamp(original['created_at'],timezone.utc).date().isoformat()
        self.assertIn('from earlier voice connection (opened '+day+' UTC)',self.f.updates[0]['content'])
        self.assertEqual(len(self.f.writes),1,'Renewal must not dispatch work again')
        self.ack();self.replacement();seen=self.emit()
        self.assertEqual(seen['state'],'already_forwarded');self.assertEqual(seen['forwarded_visit'],target)
        self.assertEqual(len(self.f.updates),1,'A third connection must not replay the second connection append')

    def test_explicit_disconnected_replacement_keeps_late_work_without_claiming_finalization(self):
        f=self.f
        value=f.visits.read(self.current,100,f.owner);value['backend_mode']='native';f.visits._write(value)
        f.visits.end_capture(self.current,100,f.owner['binding'])
        offer=f.visits.replacement_offer(100,f.owner)
        self.current=str(uuid.uuid4())
        f.visits.prepare(self.current,100,f.owner,backend_mode='native',replacement=offer)
        f.create(ident=self.current)
        self.assertEqual(f.visits.native_return_origin(self.current,100,f.owner),
            {'visit':self.origin,'delegation':f.delegation})
        self.assertEqual(self.emit()['state'],'sent');self.ack()
        self.replacement()
        self.assertEqual(self.emit()['state'],'already_forwarded')
        self.assertEqual(len(f.writes),1);self.assertEqual(len(f.updates),1)
        old=f.visits.read(self.origin,100,f.owner)
        self.assertEqual(old['state'],'created');self.assertNotIn('finalization',old)

    def test_long_result_continues_exact_cursor_across_repeated_replacements(self):
        f=self.f;f.text='Río Cobre es el resultado; seguimos por el siguiente tramo. '*35
        first=f.emit();f.acknowledge();self.replacement()
        second=self.emit(first['next_offset']);self.ack();self.replacement()
        third=self.emit(second['next_offset'])
        self.assertEqual(third['state'],'sent')
        self.assertEqual(len(f.updates),3);self.assertEqual(len(f.writes),1)
        recovered=''.join(row['content'].split('\n',1)[1] for row in f.updates)
        self.assertEqual(recovered,f.text[:third['next_offset']])
        self.assertTrue(all(len(row['content'].encode())<=500 for row in f.updates))
        self.assertEqual([u['delegation_id'] for u in f.updates],[f.delegation,None,None])
        origin=f.visits.read(self.origin,100,f.owner)
        self.assertEqual(len(origin['native_return_claims']),2)
        self.assertTrue(all(set(v)=={'target','key','delegation','source','revision','offset'}
                            for v in origin['native_return_claims'].values()),'Flat references do not copy old transcripts')

    def test_unknown_append_in_old_or_replacement_visit_never_replays(self):
        self.replacement();send=self.f.channel.send
        def lost(command):send(command);raise OSError('Synthetic lost context acknowledgment')
        self.f.channel.send=lost;self.assertEqual(self.emit()['state'],'unconfirmed')
        self.f.channel.send=send;self.replacement();result=self.emit()
        self.assertEqual(result['state'],'held');self.assertEqual(len(self.f.updates),1)
        self.assertEqual(len(self.f.writes),1)

    def test_claim_without_destination_intent_is_held_after_partial_commit(self):
        self.replacement();f=self.f;write=f.visits._write
        def interrupted(value):
            if value['id']==self.current and value.get('native_result_updates'):
                raise OSError('Synthetic destination storage failure')
            return write(value)
        with patch.object(f.visits,'_write',interrupted):
            with self.assertRaises(OSError):self.emit()
        self.assertEqual(f.updates,[])
        self.assertEqual(len(f.visits.read(self.origin,100,f.owner)['native_return_claims']),1)
        with self.assertRaises(ValueError):self.emit()
        self.assertEqual(f.updates,[],'Missing destination is not permission for another append')

    def test_foreign_actor_and_stale_native_source_refuse_before_claim(self):
        self.replacement();f=self.f
        foreign=copy.deepcopy(f.owner);foreign['entry_binding'][0]=200
        with self.assertRaises(ProviderUnavailable):
            return_native_part(f.visits,self.current,200,foreign,f.delegation,f.source,
                f.revision,0,f.provider,f.channel,source_visit=self.origin)
        f.source_fields['native_binding_current']=False
        with self.assertRaises(ValueError):self.emit()
        self.assertNotIn('native_return_claims',f.visits.read(self.origin,100,f.owner))
        self.assertEqual(f.updates,[])

    def test_flat_scan_cursor_survives_another_replacement_and_reader_restart(self):
        self.replacement();f=self.f
        cursor=f.visits.native_return_origin(self.current,100,f.owner)
        self.assertEqual(cursor,{'visit':self.origin,'delegation':f.delegation})
        # A fresh reader cannot reuse an old admission epoch. A new, explicitly
        # created voice after trusted closure gets its own current admission.
        f.visits=LiveCreations(f.root)
        self.replacement()
        value=f.visits.read(self.current,100,f.owner)
        self.assertEqual(value['native_return_scan'],cursor)
        self.assertEqual(f.visits.native_return_origin(self.current,100,f.owner),cursor)
        self.assertEqual(set(cursor),{'visit','delegation'})
        stopped=__import__('threading').Event();stopped.set()
        self.assertIsNone(return_next_native_part(f.visits,self.current,100,f.owner,1,
            f.provider,f.channel,stopped=stopped))
        self.assertEqual(f.updates,[]);self.assertEqual(len(f.writes),1)

    def test_historical_clock_order_is_not_native_work_authority(self):
        f=self.f;self.replacement()
        origin=f.visits.read(self.origin,100,f.owner)
        origin['created_at']=f.visits.read(self.current,100,f.owner)['created_at']+3600
        f.visits._write(origin)
        self.assertEqual(f.visits.native_return_origin(self.current,100,f.owner),
                         {'visit':self.origin,'delegation':f.delegation})

    def test_prior_day_first_person_result_keeps_exact_text_and_prior_date(self):
        f=self.f;f.text='Hoy lo guardé. Ya cambié la voz.'
        original=f.visits.read(self.origin,100,f.owner)
        original['created_at']=datetime(2026,11,6,tzinfo=timezone.utc).timestamp()
        f.visits._write(original);self.replacement()
        result=self.emit();self.ack()
        self.assertIsNone(result['next_offset'])
        self.assertIn('(opened 2026-11-06 UTC)',f.updates[-1]['content'])
        self.assertEqual(f.updates[-1]['content'].split('\n',1)[1],f.text)
        self.assertEqual(len(f.writes),1)
        self.replacement();self.assertEqual(self.emit()['state'],'already_forwarded')
        self.assertEqual(len(f.updates),1)

    def test_replacement_and_fresh_reader_accept_correction_after_old_partial(self):
        f=self.f;old='delivery:00000000-0000-4000-8000-000000000001'
        new='delivery:00000000-0000-4000-8000-000000000003'
        f.source=old;f.text='Previous long result. '*60;f.source_fields.update(kind='worker_result',current=True)
        prior={'source':old,'revision':f.revision,'instruction_covered':True,'current':True,'correction_pending':False}
        corrected={'source':new,'revision':'e'*64,'instruction_covered':True,'current':True,'correction_pending':False}
        f.provider.conversation_input_trace=lambda root:{'id':root,'entry_binding':f.owner['entry_binding'],
            'routes':[{'target_available':True,'results':[prior,corrected]}]}
        f.provider.presentation_list=lambda *args:{'binding':f.owner['binding'],'items':[],
            'cursor':{'native':77,'delivery':0},'more':False}
        first=self.emit();self.ack();self.replacement()
        f.visits=LiveCreations(f.root);self.replacement()
        prior.update(current=False,revision='c'*64)
        f.source=new;f.revision=corrected['revision'];f.text='The corrected result is Río Cobre.'
        returned=return_one_native_part(f.visits,self.current,100,f.owner,f.delegation,
            f.provider,f.channel,source_visit=self.origin)
        self.assertEqual(returned['source'],new);self.assertIn(f.text,f.updates[-1]['content'])
        self.assertEqual(len(f.updates),2);self.assertEqual(len(f.writes),1)
        origin=f.visits.read(self.origin,100,f.owner)
        kept=next(r for r in origin['native_result_updates'].values() if r['source']==old)
        self.assertEqual(kept['state'],'context_injected');self.assertEqual(kept['next_offset'],first['next_offset'])


if __name__=='__main__':unittest.main()
