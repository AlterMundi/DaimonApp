"""Source journals -> native semantic outbox; no provider, ASR, work or audio."""
import copy
import json
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
from dashboard.openai_live_native_session import PublicLiveSessionContext
from dashboard.provider import ProviderUnavailable
import dashboard_native_context as fixtures


class PublicContext(unittest.IsolatedAsyncioTestCase):
    setUp=fixtures.Context.setUp
    tearDown=fixtures.Context.tearDown
    database=fixtures.Context.database
    owner=fixtures.Context.owner

    def prepare(self):
        self.provider.public_live_integrator_context=lambda frozen,budget: {
            'kind':'current_integrator_conversation','thread':frozen['native_thread'],
            'messages':[{'role':'user','text':'Latest integrator correction: Saturday.'}],
            'earlier_history_available':True}
        self.frozen={'binding':self.binding,'native_thread':'native',
            'entry_binding':[100,{'chat_id':100,'thread_id':1},1,'native']}
        self.visits=LiveCreations(Path(self.tmp.name)/'visits')
        self.visits.prepare(self.dialogue,100,self.frozen,backend_mode='native')
        client=type('Client',(),{'create':lambda s,*a:LiveCall('live:synthetic','v=0 answer')})()
        self.visits.create(self.dialogue,100,self.frozen,'v=0 offer',
            {'model':'gpt-live-1','instructions':'Synthetic','delegation':{'type':'client'}},client)
        self.adapter=PublicLiveContextHistory(self.history,self.visits,100,self.frozen)
        self.producer=NativeContext(self.adapter,self.provider,100,self.dialogue,self.binding,self.owner)

    def event(self,text='Friday, not Thursday',speaker='input',start=10.5,end=20.75):
        value={'type':'session.'+speaker+'_transcript.delta','event_id':str(uuid.uuid4()),
            'delta':text,'start_ms':start,'end_ms':end}
        self.visits.event(self.dialogue,100,self.frozen,value)
        return value

    async def test_exact_speaker_and_correction_context_uses_constant_cursor_without_canonical_originals(self):
        self.prepare();first=self.event('Thursday');second=self.event('Actually Friday');output=self.event('Friday?',speaker='output')
        await self.producer.open();record=self.producer.record
        pending=self.adapter.context_pending(record)
        self.assertEqual([s['text'] for s in pending],['ThursdayActually FridayFriday?'])
        self.assertEqual([span[0] for span in pending[0]['live_transcript']['spans']],['input','input','output'])
        self.assertEqual(pending[0]['live_transcript']['spans'][0][1],10.5)
        self.assertNotIn('native_context_cursor',self.visits.read(self.dialogue,100,self.frozen))
        await self.producer._sync(record)
        self.assertEqual(len(self.provider.fresh),1)
        self.assertTrue(all(s['live_transcript']['authority']=='transcript_context_only' for s in self.provider.fresh))
        self.assertTrue(all('_public_cursor' not in s for s in self.provider.fresh))
        with self.database() as db:self.assertEqual(db.execute('SELECT count(*) FROM foreground_utterances').fetchone()[0],0)
        before=copy.deepcopy(self.visits.read(self.dialogue,100,self.frozen)['native_context_cursor'])
        self.assertEqual(set(before),{'generation','after','revision'})
        await self.producer._sync(record);self.assertEqual(len(self.provider.fresh),1)
        self.assertEqual(self.visits.read(self.dialogue,100,self.frozen)['native_context_cursor'],before)
        await self.producer.close()

    async def test_valid_large_provider_delta_reaches_native_context_without_closing_voice(self):
        self.prepare()
        text='á'*6000  # One valid12KiB UTF-8 provider fragment, no second ASR.
        event=self.event(text)
        await self.producer.open()
        await self.producer._sync(self.producer.record)
        self.assertEqual([source['text'] for source in self.provider.fresh],[text])
        source=self.provider.fresh[0]
        self.assertEqual(source['live_transcript']['spans'][0][3],12000)
        self.assertLessEqual(len(json.dumps(source,ensure_ascii=False).encode())+1024,16384)
        self.assertEqual(self.adapter.context_pending(self.producer.record),[])
        self.assertFalse(self.provider.producers[self.dialogue]['closed'])
        await self.producer.close()

    async def test_complete_escaped_delta_over_native_typed_bound_remains_retained_without_advancing(self):
        self.prepare()
        self.event('"'*12000)
        await self.producer.open()
        with self.assertRaisesRegex(ValueError,'bounded source read'):
            await self.producer._sync(self.producer.record)
        self.assertEqual(self.provider.fresh,[])
        retained=self.visits.read(self.dialogue,100,self.frozen)
        self.assertNotIn('native_context_cursor',retained)
        self.assertNotIn('native_context_batch',retained)
        self.assertEqual(self.visits.source_page(self.dialogue,100,self.binding)['items'][0]['event']['delta'],'"'*12000)

    async def test_lost_native_receipt_keeps_source_cursor_and_reconciles_same_sources_after_restart(self):
        self.prepare();self.event();await self.producer.open();self.provider.lose_next=True
        with self.assertRaises(ProviderUnavailable):await self.producer._sync(self.producer.record)
        self.assertEqual(len(self.provider.fresh),1)
        self.assertNotIn('native_context_cursor',self.visits.read(self.dialogue,100,self.frozen))
        self.event('A new fragment after the lost receipt')
        restarted=PublicLiveContextHistory(self.history,LiveCreations(self.visits.root),100,self.frozen)
        current=NativeContext(restarted,self.provider,100,self.dialogue,self.binding,self.owner)
        current.record=self.producer.record
        await current._sync(current.record)
        self.assertEqual(len(self.provider.fresh),2,'Frozen old block reconciles once; new language gets a distinct block')
        self.assertEqual([s['text'] for s in self.provider.fresh],['Friday, not Thursday','A new fragment after the lost receipt'])
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
        self.assertEqual(''.join(s['text'] for s in self.provider.fresh),''.join(expected))
        self.event('Late correction')
        await self.producer._sync(self.producer.record)
        self.assertEqual(self.provider.fresh[-1]['text'],'Late correction')
        self.assertTrue(all(len(call.get('assistant',[]))<=8 for call in self.provider.calls))
        await self.producer.close()

    async def test_many_small_deltas_keep_compact_context_and_one_frozen_source_range_per_page(self):
        self.prepare()
        for n in range(146):self.event('x' if n==0 else ('áhi ' if n%2 else 'hello '),
            speaker='input' if n%3 else 'output',start=n*400+.25,end=n*400+25.75)
        await self.producer.open();await self.producer._sync(self.producer.record)
        self.assertEqual(sum(len(s['live_transcript']['spans']) for s in self.provider.fresh),146)
        self.assertEqual(len(self.provider.fresh),3)
        self.assertEqual(sum(len(s['text'].encode()) for s in self.provider.fresh),798)
        total=sum(len(json.dumps(s,ensure_ascii=False).encode()) for s in self.provider.fresh)
        self.assertLess(total,16384,'Subword provider deltas must not force semantic compaction from repeated envelopes')
        for source in self.provider.fresh:
            meta=source['live_transcript'];self.assertEqual(meta['spans'][-1][3],len(source['text'].encode()))
            self.assertTrue(meta['journal_from']<meta['journal_after'])
        self.assertNotIn('native_context_batch',self.visits.read(self.dialogue,100,self.frozen))
        await self.producer.close()

    async def test_legacy_visit_bootstrap_seeds_startup_before_new_provider_creation(self):
        self.prepare();old=self.dialogue;self.event('Actually Friday')
        self.visits.observe_closed(old,100,self.frozen,{'type':'session.closed','event_id':'closed',
            'reason':'close_requested','session':{'id':'live:synthetic'}})
        current=str(uuid.uuid4());self.visits.prepare(current,100,self.frozen,backend_mode='native')
        context=PublicLiveSessionContext(self.history,self.visits,self.provider,100,current,self.frozen,self.owner)
        original={'model':'gpt-live-1','instructions':'Synthetic owner identity','delegation':{'type':'client'},
            'audio':{'output':{'voice':'cedar'}},'store':False}
        seeded=await context.prepare(original)
        self.assertEqual(seeded['audio'],original['audio']);self.assertEqual(seeded['instructions'],original['instructions'])
        self.assertNotIn('input',original)
        self.assertIn('Actually Friday',seeded['input'][-2]['content'][0]['text'])
        self.assertIn('Latest integrator correction: Saturday.',seeded['input'][-1]['content'][0]['text'])
        self.assertEqual(seeded['input'][-1]['role'],'developer')
        self.assertEqual(self.visits.read(current,100,self.frozen)['state'],'prepared')
        self.assertNotIn('call',self.visits.read(current,100,self.frozen))
        opens=[c for c in self.provider.calls if c['action']=='open' and c['dialogue']==current]
        self.assertEqual(opens[0]['resume']['dialogue'],old)
        self.assertEqual(self.visits.read(current,100,self.frozen)['native_context_seed']['resume'],opens[0]['resume'])
        await context.close()

    async def test_inflight_interpretation_keeps_projection_open_for_the_next_explicit_owner(self):
        self.prepare();self.event()
        context=PublicLiveSessionContext(self.history,self.visits,self.provider,100,self.dialogue,self.frozen,self.owner)
        await context.prepare({'model':'gpt-live-1','instructions':'Synthetic','delegation':{'type':'client'}})
        await context.close(settled=False)
        record=self.history.context_resume_record(100,self.binding,self.dialogue)
        self.assertEqual(record['phase'],'closing');self.assertFalse(self.provider.producers[self.dialogue]['closed'])
        await context.close(settled=True)
        self.assertTrue(self.provider.producers[self.dialogue]['closed'])


    async def active_context(self):
        self.prepare()
        context=PublicLiveSessionContext(self.history,self.visits,self.provider,100,self.dialogue,self.frozen,self.owner)
        await context.prepare({'model':'gpt-live-1','instructions':'Synthetic','delegation':{'type':'client'}})
        clock=[0.];context.clock=lambda:clock[0];context.last_sync=0.
        return context,clock

    async def test_active_context_coalesces_trusted_deltas_before_close(self):
        context,clock=await self.active_context()
        for n in range(128):
            event=self.event('Viernes ' if n%2 else 'Friday? ',speaker='input' if n%2 else 'output')
            context.observe(event)
        clock[0]=9.;self.assertFalse(context.sync_due())
        clock[0]=10.;self.assertTrue(context.sync_due())
        await context.sync();self.assertFalse(context.sync_due())
        calls=[c for c in self.provider.calls if c['action']=='sync']
        self.assertTrue(calls and all(c['prepare_continuation'] for c in calls))
        self.assertEqual(sum(len(s['live_transcript']['spans']) for s in self.provider.fresh),128)
        self.assertEqual(context.synced_events,128)
        with self.database() as db:self.assertEqual(db.execute('SELECT count(*) FROM foreground_utterances').fetchone()[0],0)
        context.observe({'type':'session.usage.updated'});self.assertEqual(context.observed_events,128)
        await context.close()

    async def test_active_context_byte_threshold_and_stop_keep_exact_final_tail(self):
        context,clock=await self.active_context();event=self.event('v'*4096);context.observe(event)
        clock[0]=10.;self.assertTrue(context.sync_due());await context.sync()
        context.stop_updates();late=self.event('Corrección tardía: el viernes.');context.observe(late)
        clock[0]=30.;self.assertFalse(context.sync_due())
        await context.close()
        self.assertEqual(''.join(s['text'] for s in self.provider.fresh),'v'*4096+'Corrección tardía: el viernes.')

    async def test_active_context_late_delta_is_not_marked_synced_by_an_earlier_snapshot(self):
        context,clock=await self.active_context();context.observe(self.event('v'*4096));clock[0]=10.
        sync=context.producer._sync
        async def arriving(record):
            context.observe(self.event('Nueva corrección'))
            return await sync(record)
        context.producer._sync=arriving
        await context.sync()
        self.assertEqual(context.observed_events,2);self.assertEqual(context.synced_events,1)
        self.assertIn('Nueva corrección',''.join(s['text'] for s in self.provider.fresh))
        context.producer._sync=sync;await context.close()

    async def test_active_context_lost_receipt_stops_without_close_retry(self):
        context,clock=await self.active_context();context.observe(self.event('v'*4096));clock[0]=10.
        self.provider.lose_next=True
        with self.assertRaises(ProviderUnavailable):await context.sync()
        self.assertFalse(context.sync_due());self.assertTrue(context.sync_failed)
        self.assertEqual(context.producer.status,'needs_review')
        calls=len([c for c in self.provider.calls if c['action']=='sync'])
        await context.close()
        self.assertEqual(len([c for c in self.provider.calls if c['action']=='sync']),calls)
        self.assertEqual(self.history.context_resume_record(100,self.binding,self.dialogue)['phase'],'closing')
        self.assertNotIn('native_context_cursor',self.visits.read(self.dialogue,100,self.frozen))

if __name__=='__main__':unittest.main()
