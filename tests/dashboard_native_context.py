"""Canonical SQLite outbox/restart/uncertain receipts; no audio or model calls."""
import asyncio
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.native_context import NativeContext
from dashboard.native_history import NativeHistory
from dashboard.provider import ProviderUnavailable


class Journal:
    def __init__(self):
        self.producers={};self.calls=[];self.fresh=[];self.lose_next=False

    def conversation_live_context(self,body):
        self.calls.append(body)
        ident=body['dialogue']
        if body['action']=='open':
            p=self.producers.setdefault(ident,{'dialogue':ident,'generation':body['generation'],'closed':False,'sources':{}})
        else:p=self.producers[ident]
        assert p['generation']==body['generation']
        receipts=[]
        guide=p.get('guidance')
        if body['action']=='guidance':
            return {k:p[k] for k in ('dialogue','generation','closed')}|{'guidance':guide if guide and guide['phase']=='pending' else None}
        if body['action']=='guidance_begin':
            assert guide['phase']=='pending' and guide['id']==body['id'];guide['phase']='submitting'
        elif body['action']=='guidance_outcome':
            assert guide['id']==body['id'];guide['phase']='pending' if body['outcome']=='unsent' else body['outcome']
        if body['action']=='sync':
            for source in body['assistant']:
                old=p['sources'].get(source['source'])
                if old is None:
                    assert not p['closed']
                    p['sources'][source['source']]=source;self.fresh.append(source)
                else:assert old==source
                receipts.append({'source':source['source'],'sequence':list(p['sources']).index(source['source'])+1,
                    'revision':hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest(),'fresh':old is None})
            if self.lose_next and receipts:
                self.lose_next=False
                raise ProviderUnavailable('Synthetic lost receipt AFTER native retention')
        elif body['action']=='close':p['closed']=True
        return {k:p[k] for k in ('dialogue','generation','closed')}|{'assistant_receipts':receipts,'guidance':guide}


class Context(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'state.sqlite3'
        self.history=NativeHistory(self.database,'selected-scope');self.provider=Journal()
        self.dialogue=str(uuid.uuid4());self.binding='a'*64

    def tearDown(self):self.tmp.cleanup()

    @contextmanager
    def database(self):
        db=sqlite3.connect(self.path,timeout=3);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()

    async def owner(self,function,*args):return function(*args)

    def producer(self,dialogue=None):
        return NativeContext(self.history,self.provider,100,dialogue or self.dialogue,self.binding,self.owner)

    def retain(self,text='Terminal language α.',*,closed=True,source=None):
        return self.history.retain(100,self.dialogue,self.binding,source or str(uuid.uuid4()),text,'b'*64,640,closed=closed)

    async def test_terminal_transaction_and_playback_use_one_semantic_source(self):
        p=self.producer();await p.open()
        source=self.retain();record=p.record
        pending=self.history.context_pending(record);self.assertEqual(len(pending),1)
        semantic=pending[0]['semantic_revision']
        await p._sync(record)
        self.assertEqual(self.history.context_pending(record),[])
        with self.database() as db:
            retained=db.execute('SELECT native_sequence,native_revision FROM foreground_context_outbox WHERE source=?',(source['id'],)).fetchone()
        receipt={'source':source['id'],'sequence':retained['native_sequence'],'revision':retained['native_revision']}
        self.history.context_retained(record,pending,[receipt])
        with self.assertRaises(ValueError):self.history.context_retained(record,pending,[{**receipt,'sequence':receipt['sequence']+1}])
        self.history.played(100,self.dialogue,source['id'],640)
        self.assertNotEqual(source['revision'],self.history.page(100)['items'][0]['revision'])
        self.assertEqual(self.history.context_pending(record),[])
        with self.database() as db:
            self.assertEqual(db.execute('SELECT revision FROM foreground_context_outbox WHERE source=?',(source['id'],)).fetchone()[0],semantic)
        await p._sync(record)
        self.assertEqual(len(self.provider.fresh),1,'Playback and catch-up must not resend already retained language')
        await p.close()

    async def test_lost_retention_receipt_stays_pending_and_recovers_same_identity(self):
        p=self.producer();await p.open();source=self.retain()
        generation=p.record['generation'];self.provider.lose_next=True
        task=asyncio.create_task(p.run())
        with self.assertRaises(ProviderUnavailable):await task
        calls=len(self.provider.calls)
        await p.close()
        self.assertEqual(len(self.provider.calls),calls,'Cleanup must not retry an unknown boundary')
        self.assertEqual(p.status,'needs_review')
        self.assertEqual(len(self.history.context_pending(p.record)),1)
        # A fresh explicit avatar open reconciles retained source IDs. It does
        # not regenerate audio, invent an original or reauthor the native return.
        self.history=NativeHistory(self.database,'selected-scope')
        next_producer=self.producer(str(uuid.uuid4()));await next_producer.open()
        self.assertEqual(len(self.provider.fresh),1)
        self.assertIn(source['id'],self.provider.producers[self.dialogue]['sources'])
        self.assertEqual(self.provider.producers[self.dialogue]['generation'],generation)
        self.assertEqual(self.history.context_pending(p.record),[])
        with self.database() as db:
            self.assertEqual(db.execute('SELECT phase FROM foreground_context_producers WHERE dialogue=?',(self.dialogue,)).fetchone()[0],'closed')
        await next_producer.close()

    async def test_abandoned_partial_text_and_slow_closure_are_caught_up(self):
        p=self.producer();await p.open()
        # A later row can close before an earlier row; a high row cursor alone
        # would lose the earlier source when it eventually becomes terminal.
        earlier=self.retain('Earlier partial',closed=False)
        later=self.retain('Later terminal')
        await p._sync(p.record)
        self.assertEqual([s['source'] for s in self.provider.fresh],[later['id']])
        self.history=NativeHistory(self.database,'selected-scope')
        next_producer=self.producer(str(uuid.uuid4()));await next_producer.open()
        self.assertEqual(len(self.provider.fresh),2)
        recovered=self.provider.producers[self.dialogue]['sources'][earlier['id']]
        self.assertEqual(recovered['text'],'Earlier partial');self.assertTrue(recovered['interrupted'])
        self.assertEqual(self.history.page(100,dialogue=self.dialogue)['items'][1]['played_bytes'],0)
        await next_producer.close()

    async def test_batch_byte_bound_drains_every_pending_source_and_preserves_owner(self):
        p=self.producer();await p.open()
        for _ in range(9):self.retain('á'*8000)
        await p._sync(p.record)
        self.assertEqual(len(self.provider.fresh),9)
        self.assertEqual(self.history.context_pending(p.record),[])
        batches=[b['assistant'] for b in self.provider.calls if b['action']=='sync']
        self.assertTrue(all(len(b)<=8 and sum(len(s['text'].encode()) for s in b)<=65536 for b in batches))
        with self.assertRaises(ValueError):self.history.context_pending({**p.record,'human':101})
        with patch.object(NativeContext,'max_producers',1):
            with self.assertRaises(ValueError):self.history.context_register(100,str(uuid.uuid4()),self.binding)
        self.assertEqual(len(self.provider.fresh),9)
        await p.close()

    async def test_guidance_known_unsent_can_wait_but_unknown_send_never_replays(self):
        p=self.producer();await p.open()
        def guide():
            value={'id':str(uuid.uuid4()),'generation':p.record['generation'],'basis':0,
                'mode':'context_only','text':'Confirmed internal fact.','phase':'pending'}
            self.provider.producers[self.dialogue]['guidance']=value;return value
        value=guide();calls=[]
        async def busy(frame):return False
        self.assertFalse(await p.offer_guidance(busy));self.assertEqual(value['phase'],'pending')
        async def send(frame):calls.append(frame);return True
        self.assertTrue(await p.offer_guidance(send));self.assertEqual(value['phase'],'sent')
        self.assertFalse(await p.offer_guidance(send));self.assertEqual(len(calls),1)
        unknown=guide()
        async def lost(frame):calls.append(frame);raise OSError('Unknown provider socket write')
        with self.assertRaises(OSError):await p.offer_guidance(lost)
        self.assertEqual(unknown['phase'],'uncertain')
        self.assertFalse(await p.offer_guidance(send));self.assertEqual(len(calls),2)
        await p.close()


if __name__=='__main__':unittest.main()
