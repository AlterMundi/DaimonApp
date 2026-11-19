"""Actual Node validation and SQLite restart, quota, collision and isolation."""
from pathlib import Path
import concurrent.futures
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.atelier_workshop import AtelierWorkshop,AtelierConflict,FILE_BYTES


def fixtures():
    root=Path(__file__).resolve().parents[1]/'dashboard/web/atelier-workshop'
    code='''import {webcrypto} from 'node:crypto';if(!globalThis.crypto)globalThis.crypto=webcrypto;
import {makeRevision,uuid} from './project.js';import {makeRequest,stretchProposal} from './corner-contract.js';
const p={schema:'sculpt.project/v1',id:uuid(),name:'Lámpara 🍋',units:'mm',camera:null,objects:[{id:uuid(),name:'Forma',color:'#81948b',visible:true,position:[0,0,0],scale:1,positions:[0,0,0,10,0,0,0,10,0],indices:[0,1,2]}]},r=await makeRevision(p),request=JSON.stringify(await makeRequest(r,'Estirá esta pieza',[p.objects[0].id])),reply=JSON.stringify(await stretchProposal(request,{axis:'y',factor:1.2}));console.log(JSON.stringify({request,reply,id:JSON.parse(JSON.parse(request).document).id}));'''
    return json.loads(subprocess.check_output(['node','--input-type=module','-e',code],cwd=root))


class Store(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from scripts.verify_atelier_workshop import verify
        verify()
        cls.fixture=fixtures()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.store=AtelierWorkshop(self.root);self.raw=self.fixture['request'];self.reply=self.fixture['reply'];self.ident=self.fixture['id']
    def test_exact_source_reply_restart_and_readback_without_new_validator(self):
        first=self.store.save_request(100,self.raw);self.assertEqual(first['request'],self.raw)
        returned=self.store.save_reply(100,self.ident,self.reply);self.assertEqual(returned['reply'],self.reply);self.assertEqual(first['receiptId'],returned['receiptId'])
        before=self.store.snapshot(100)
        with patch('dashboard.atelier_workshop.validate_transfer',side_effect=ValueError('Future validator unavailable')):
            fresh=AtelierWorkshop(self.root);self.assertEqual(fresh.get(100,self.ident),returned)
            self.assertEqual(fresh.save_request(100,self.raw),returned);self.assertEqual(fresh.save_reply(100,self.ident,self.reply),returned)
        self.assertEqual(fresh.snapshot(100),before);self.assertEqual(before['generation'],2)
        self.assertEqual(hashlib.sha256(returned['request'].encode()).hexdigest(),hashlib.sha256(self.raw.encode()).hexdigest())
    def test_actor_isolation_and_same_id_is_not_cross_account_authority(self):
        self.store.save_request(100,self.raw)
        self.assertEqual(self.store.snapshot(200)['requests'],[])
        with self.assertRaises(KeyError):self.store.get(200,self.ident)
        self.assertNotEqual(self.store.snapshot(100)['storageScope'],self.store.snapshot(200)['storageScope'])
        self.store.save_request(200,self.raw);self.store.save_reply(200,self.ident,self.reply)
        self.assertNotIn('reply',self.store.get(100,self.ident));self.assertIn('reply',self.store.get(200,self.ident))
    def test_immutable_conflicts_corrupt_hash_and_foreign_return_preserve_source(self):
        saved=self.store.save_request(100,self.raw)
        with self.assertRaises(AtelierConflict):self.store.save_request(100,self.raw+' ')
        bad=json.loads(self.reply);bad['document']=bad['document'].replace('Estiré','Rompí')
        with self.assertRaises(ValueError):self.store.save_reply(100,self.ident,json.dumps(bad))
        other=fixtures();self.store.save_request(100,other['request'])
        with self.assertRaises(ValueError):self.store.save_reply(100,self.ident,other['reply'])
        self.assertEqual(self.store.get(100,self.ident),saved)
    def test_quota_refusal_is_atomic_and_existing_records_stay_readable(self):
        saved=self.store.save_request(100,self.raw);before=self.store.snapshot(100)
        self.store.max_actor_bytes=1
        with self.assertRaises(ValueError):self.store.save_reply(100,self.ident,self.reply)
        self.assertEqual(self.store.get(100,self.ident),saved);self.assertEqual(self.store.snapshot(100),before)
        self.store.max_actor_bytes=64*1024*1024;self.store.max_requests=1
        with self.assertRaises(ValueError):self.store.save_request(100,fixtures()['request'])
        self.assertEqual(self.store.get(100,self.ident),saved)
        with self.assertRaises(ValueError):self.store.save_request(100,'x'*(FILE_BYTES+1))
    def test_concurrent_duplicate_commits_have_one_receipt_and_one_generation(self):
        # Avoid the intentional single validation slot by racing exact retries
        # after one retained save. Both use the actual SQLite transaction reader.
        saved=self.store.save_request(100,self.raw)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            rows=list(pool.map(lambda _:AtelierWorkshop(self.root).save_request(100,self.raw),range(2)))
        self.assertEqual(rows,[saved,saved]);self.assertEqual(self.store.snapshot(100)['generation'],1)
    def test_tampered_canonical_bytes_and_unsafe_database_refuse_without_reset(self):
        self.store.save_request(100,self.raw)
        with sqlite3.connect(self.store.path) as db:db.execute('UPDATE exchanges SET request=?',(b'changed',))
        with self.assertRaises(ValueError):self.store.get(100,self.ident)
        with tempfile.TemporaryDirectory() as other:
            target=Path(other)/'original';target.write_bytes(b'untouched')
            self.store.path.unlink();self.store.path.symlink_to(target)
            with self.assertRaises(ValueError):self.store.snapshot(100)
            self.assertEqual(target.read_bytes(),b'untouched')

if __name__=='__main__':unittest.main()
