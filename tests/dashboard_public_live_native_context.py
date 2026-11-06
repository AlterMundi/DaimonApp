"""Source journals -> native semantic outbox; no provider, ASR, work or audio."""
import copy
from pathlib import Path
import sys
import unittest
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from dashboard.native_context import NativeContext
from dashboard.openai_live import LiveCall
from dashboard.openai_live_visits import LiveCreations
from dashboard.openai_live_native_context import PublicLiveContextHistory
from dashboard.provider import ProviderUnavailable
import dashboard_native_context as fixtures


class PublicContext(unittest.IsolatedAsyncioTestCase):
    setUp=fixtures.Context.setUp
    tearDown=fixtures.Context.tearDown
    database=fixtures.Context.database
    owner=fixtures.Context.owner

    def prepare(self):
        self.frozen={'binding':self.binding,'native_thread':'native',
            'entry_binding':[100,{'chat_id':100,'thread_id':1},1,'native']}
        self.visits=LiveCreations(Path(self.tmp.name)/'visits')
        self.visits.prepare(self.dialogue,100,self.frozen,backend_mode='native')
        client=type('Client',(),{'create':lambda s,*a:LiveCall('live:synthetic','v=0 answer')})()
        self.visits.create(self.dialogue,100,self.frozen,'v=0 offer',
            {'model':'gpt-live-1','instructions':'Synthetic','delegation':{'type':'client'}},client)
        self.adapter=PublicLiveContextHistory(self.history,self.visits,100,self.frozen)
        self.producer=NativeContext(self.adapter,self.provider,100,self.dialogue,self.binding,self.owner)

    def event(self,text='Friday, not Thursday',speaker='input'):
        value={'type':'session.'+speaker+'_transcript.delta','event_id':str(uuid.uuid4()),
            'delta':text,'start_ms':10.5,'end_ms':20.75}
        self.visits.event(self.dialogue,100,self.frozen,value)
        return value

    async def test_exact_speaker_and_correction_context_uses_constant_cursor_without_canonical_originals(self):
        self.prepare();first=self.event('Thursday');second=self.event('Actually Friday');output=self.event('Friday?',speaker='output')
        await self.producer.open();record=self.producer.record
        pending=self.adapter.context_pending(record)
        self.assertEqual([s['text'] for s in pending],['Thursday','Actually Friday','Friday?'])
        self.assertEqual([s['live_transcript']['speaker'] for s in pending],['input','input','output'])
        self.assertEqual(pending[0]['live_transcript']['start_ms'],10.5)
        self.assertNotIn('native_context_cursor',self.visits.read(self.dialogue,100,self.frozen))
        await self.producer._sync(record)
        self.assertEqual(len(self.provider.fresh),3)
        self.assertTrue(all(s['live_transcript']['authority']=='transcript_context_only' for s in self.provider.fresh))
        self.assertTrue(all('_public_cursor' not in s for s in self.provider.fresh))
        with self.database() as db:self.assertEqual(db.execute('SELECT count(*) FROM foreground_utterances').fetchone()[0],0)
        before=copy.deepcopy(self.visits.read(self.dialogue,100,self.frozen)['native_context_cursor'])
        self.assertEqual(set(before),{'generation','after','revision'})
        await self.producer._sync(record);self.assertEqual(len(self.provider.fresh),3)
        self.assertEqual(self.visits.read(self.dialogue,100,self.frozen)['native_context_cursor'],before)
        await self.producer.close()

    async def test_lost_native_receipt_keeps_source_cursor_and_reconciles_same_sources_after_restart(self):
        self.prepare();self.event();await self.producer.open();self.provider.lose_next=True
        with self.assertRaises(ProviderUnavailable):await self.producer._sync(self.producer.record)
        self.assertEqual(len(self.provider.fresh),1)
        self.assertNotIn('native_context_cursor',self.visits.read(self.dialogue,100,self.frozen))
        restarted=PublicLiveContextHistory(self.history,LiveCreations(self.visits.root),100,self.frozen)
        current=NativeContext(restarted,self.provider,100,self.dialogue,self.binding,self.owner)
        current.record=self.producer.record
        await current._sync(current.record)
        self.assertEqual(len(self.provider.fresh),1,'Native source reconciliation is not a second source/work')
        await current.close()

    async def test_bad_source_hash_other_actor_and_incomplete_append_do_not_advance(self):
        self.prepare();self.event();await self.producer.open();record=self.producer.record
        bad={**record,'human':200}
        with self.assertRaises(ValueError):self.adapter.context_pending(bad)
        path=self.visits.root/(self.dialogue+'.events');before=path.read_bytes()
        path.write_bytes(before.replace(b'Friday, not Thursday',b'Untrusted replacement'))
        with self.assertRaises(ValueError):self.adapter.context_pending(record)
        path.write_bytes(before)
        await self.producer._sync(record)
        with path.open('ab') as f:f.write(b'{"interrupted":')
        with self.assertRaises(ValueError):self.adapter.context_pending(record)
        self.assertEqual(len(self.provider.fresh),1)

    async def test_long_source_pages_and_late_fragments_keep_order_without_nested_history(self):
        self.prepare()
        expected=[]
        for n in range(19):expected.append('Fragment '+str(n));self.event(expected[-1])
        await self.producer.open();await self.producer._sync(self.producer.record)
        self.assertEqual([s['text'] for s in self.provider.fresh],expected)
        self.event('Late correction')
        await self.producer._sync(self.producer.record)
        self.assertEqual(self.provider.fresh[-1]['text'],'Late correction')
        self.assertTrue(all(len(call.get('assistant',[]))<=8 for call in self.provider.calls))
        await self.producer.close()


if __name__=='__main__':unittest.main()
