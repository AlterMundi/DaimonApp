"""Atomic A/B scope, restart uncertainty and finite retirement; no synthesis."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.avatar_workshop import AvatarWorkshop,WorkshopConflict
from dashboard.voice_studio_batches import MAX_BATCHES


class Batches(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=AvatarWorkshop(self.temp.name);self.ident=str(uuid.uuid4());self.plans=0
        self.profile={'provider':'openai','api':'gpt-live','model':'gpt-live-1','voice':'cedar'}
    def planner(self,row):self.plans+=1;return {'A':'a'*64,'B':'b'*64}
    def prepare(self,ident=None,generation=0,voice_generation=0,delivery='Warm.'):
        return self.store.preview_prepare(100,ident or self.ident,self.profile,delivery,voice_generation,generation,self.planner)
    def test_frozen_ab_save_readback_and_actor_isolation_keep_visual_and_voice_pointers(self):
        visual=self.store.snapshot(100);voice=self.store.voice_snapshot(100)
        first=self.prepare();self.assertEqual(first['choices']['A']['delivery'],'')
        self.assertEqual(first['choices']['B']['delivery'],'Warm.')
        self.assertEqual(self.prepare(),first);self.assertEqual(self.plans,1)
        with self.assertRaises(WorkshopConflict):self.prepare(delivery='Changed')
        preset=str(uuid.uuid4());self.store.voice_save(100,preset,self.profile,'Neutral.',None,0)
        self.store.voice_select(100,preset,1,[self.profile])
        self.assertEqual(self.prepare(),first)
        self.assertEqual(self.store.snapshot(100),visual)
        self.assertEqual(self.store.preview_snapshot(200)['batches'],[])
        with self.assertRaises(KeyError):self.store.preview_start(200,self.ident,1,'A')
        self.assertIsNone(voice['active'])

    def test_restart_and_unknown_attempt_only_observe_same_intent(self):
        self.prepare();row,fresh=self.store.preview_start(100,self.ident,1,'A');self.assertTrue(fresh)
        outcome={'state':'unconfirmed','receipt':{'finalized':False}}
        self.store.preview_observe(100,self.ident,1,'A','a'*64,outcome)
        restarted=AvatarWorkshop(self.temp.name);row,fresh=restarted.preview_start(100,self.ident,1,'A')
        self.assertFalse(fresh);self.assertEqual(row['renders']['A']['state'],'unconfirmed')
        retired=[]
        with self.assertRaises(ValueError):restarted.preview_retire(100,self.ident,1,1,retired.append)
        self.assertEqual(retired,[])

    def test_cancel_keeps_started_attempt_and_proves_other_slot_unsent(self):
        self.prepare();self.store.preview_start(100,self.ident,1,'A')
        row=self.store.preview_cancel(100,self.ident,1)
        self.assertEqual(row['renders']['A']['state'],'cancel_requested')
        self.assertEqual(row['renders']['B']['state'],'not_started')
        self.assertFalse(self.store.preview_start(100,self.ident,1,'B')[1])
        self.store.preview_observe(100,self.ident,1,'A','a'*64,{'state':'cancelled_verified','receipt':{'finalized':True}})
        self.assertEqual(self.store.preview_retire(100,self.ident,1,1,lambda row:None)['batches'],[])

    def test_capacity_and_generation_refuse_retired_or_stale_allocation(self):
        for n in range(MAX_BATCHES):self.prepare(ident=self.ident if n==0 else str(uuid.uuid4()),generation=n)
        with self.assertRaises(ValueError):self.prepare(ident=str(uuid.uuid4()),generation=MAX_BATCHES)
        self.assertEqual(self.plans,MAX_BATCHES)
        self.store.preview_retire(100,self.ident,1,MAX_BATCHES,lambda row:None)
        with self.assertRaises(WorkshopConflict):self.prepare()
        self.assertEqual(len(self.store.preview_snapshot(100)['batches']),MAX_BATCHES-1)

    def test_partial_retirement_is_durable_and_continues_only_its_cleanup(self):
        self.prepare();removed=[]
        write=self.store._write;calls=0
        def fail_after_cleanup(*args):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('Synthetic final metadata failure')
            return write(*args)
        with patch.object(self.store,'_write',side_effect=fail_after_cleanup):
            with self.assertRaises(OSError):self.store.preview_retire(100,self.ident,1,1,lambda row:removed.append(row['id']))
        restarted=AvatarWorkshop(self.temp.name)
        self.assertEqual(restarted.preview_snapshot(100)['batches'][0]['phase'],'retiring')
        with self.assertRaises(ValueError):restarted.preview_start(100,self.ident,1,'A')
        self.assertEqual(restarted.preview_retire(100,self.ident,1,1,lambda row:self.assertIn(row['id'],removed))['batches'],[])
        self.assertEqual(removed,[self.ident])

if __name__=='__main__':unittest.main()
