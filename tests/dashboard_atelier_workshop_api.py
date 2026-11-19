"""Mounted exact actor/CSRF boundaries and the real shared Home authorizer."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from dashboard.atelier_workshop_api import install,BODY_BYTES
from dashboard.atelier_workshop import AtelierWorkshop
from dashboard.companion import permitted
from dashboard.app import create_app
from dashboard_atelier_workshop import fixtures
from dashboard_io import Receiver


class Mounted(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.fixture=fixtures()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.allowed={100,200};test=self
        class Owner:
            def authorized(self,human):return human in test.allowed
        async def authorize(request):
            actor=request.headers.get('authorization')
            if actor not in ('actor100','actor200','monitor'):raise HTTPException(401,'Sign in')
            if not permitted(request.method,request.url.path,'monitor_readonly' if actor=='monitor' else 'interaction_only'):raise HTTPException(403,'Scope')
            return {'human':200 if actor=='actor200' else 100,'scope':'monitor_readonly' if actor=='monitor' else 'interaction_only','csrf':'fresh'}
        self.app=FastAPI();self.store=install(self.app,{'state_dir':self.tmp.name},Owner(),authorize,['https://example.test']);self.client=TestClient(self.app,base_url='https://example.test');self.addCleanup(self.client.close)
        self.h={'authorization':'actor100','origin':'https://example.test','x-dashboard-csrf':'fresh'};self.path='/api/interaction/atelier';self.body={'action':'save-request','request':self.fixture['request']}
    def test_save_exact_readback_account_isolation_reply_and_canonical_export(self):
        response=self.client.post(self.path,json=self.body,headers=self.h);self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['request'],self.fixture['request']);ident=self.fixture['id'];path=self.path+'/requests/'+ident
        foreign={**self.h,'authorization':'actor200'};self.assertEqual(self.client.get(path,headers=foreign).status_code,404)
        self.assertEqual(self.client.get(self.path,headers=foreign).json()['requests'],[])
        body={'action':'save-reply','requestId':ident,'reply':self.fixture['reply']};reply=self.client.post(self.path,json=body,headers=self.h);self.assertEqual(reply.status_code,200,reply.text)
        for kind in ('request','reply'):
            raw=self.fixture[kind].encode();read=self.client.get(path+'?format='+kind,headers=self.h);self.assertEqual(read.content,raw);self.assertEqual(read.headers['etag'],'"sha256-'+hashlib.sha256(raw).hexdigest()+'"');self.assertEqual(read.headers['cache-control'],'private, no-store')
        self.assertEqual(self.client.post(self.path,json=self.body,headers=self.h).json(),reply.json())
    def test_anonymous_monitor_forged_actor_origin_and_csrf_refuse(self):
        self.assertEqual(self.client.get(self.path).status_code,401)
        for headers in ({**self.h,'authorization':'monitor'},{**self.h,'origin':'https://foreign.test'},{**self.h,'x-dashboard-csrf':'wrong'}):self.assertEqual(self.client.post(self.path,json=self.body,headers=headers).status_code,403)
        self.assertEqual(self.client.post(self.path,json={**self.body,'human':100},headers=self.h).status_code,400)
        self.assertEqual(self.store.snapshot(100)['requests'],[])
        for path in (self.path+'/other',self.path+'/requests/../other',self.path+'/requests/'+self.fixture['id']+'/extra'):self.assertFalse(permitted('GET',path))
        self.assertFalse(permitted('POST',self.path,'monitor_readonly'));self.assertFalse(permitted('DELETE',self.path))
    def test_revocation_after_commit_keeps_original_for_exact_status_recovery(self):
        write=AtelierWorkshop.save_request;test=self
        def revoked(store,*args):value=write(store,*args);test.allowed.clear();return value
        with patch.object(AtelierWorkshop,'save_request',revoked):
            response=self.client.post(self.path,json=self.body,headers=self.h)
        self.assertEqual(response.status_code,403);self.allowed.add(100)
        retained=self.client.get(self.path+'/requests/'+self.fixture['id'],headers=self.h)
        self.assertEqual(retained.status_code,200);self.assertEqual(retained.json()['request'],self.fixture['request']);self.assertEqual(self.store.snapshot(100)['generation'],1)
    def test_large_unknown_and_validator_files_are_unavailable(self):
        self.assertEqual(self.client.post(self.path,content=b'x'*(BODY_BYTES+1),headers=self.h).status_code,413)
        self.assertEqual(self.client.post(self.path,content='['*2000+'0'+']'*2000,headers=self.h).status_code,400)
        for asset in ('validate.mjs','project.js','PROVENANCE.json','package.json'):
            self.assertEqual(self.client.get('/assets/atelier-workshop/'+asset).status_code,404)


class SharedHome(unittest.TestCase):
    def test_actual_bearer_session_row_uses_the_same_write_middleware(self):
        with tempfile.TemporaryDirectory() as root:
            provider=Receiver();app=create_app({'state_dir':root,'origin':'https://example.test','prefix':'/sessions','bot_id':123},provider,lambda raw,bot:int(raw))
            with TestClient(app,base_url='https://example.test') as client:
                token=client.post('/api/session',json={'init_data':'100'},headers={'origin':'https://example.test'}).json()['session_token']
                headers={'authorization':'Bearer '+token,'origin':'https://example.test'}
                headers['x-dashboard-csrf']=client.get('/api/state',headers=headers).json()['csrf']
                f=fixtures();response=client.post('/api/interaction/atelier',json={'action':'save-request','request':f['request']},headers=headers)
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.json()['request'],f['request'])
                self.assertEqual(provider.calls,[])

    def test_actual_home_writer_permitted_csrf_chunked_bound_and_private_scope(self):
        with tempfile.TemporaryDirectory() as root:
            provider=Receiver();config={'state_dir':root,'origin':'https://example.test','prefix':'/sessions','bot_id':123,'shared_auth':{'enabled':True,'home_origin':'https://example.test','human_ref':'human:synthetic:100'}}
            app=create_app(config,provider,lambda raw,bot:int(raw));identity={'contract':'dm.home-session/v1','origin':'https://example.test','expires':int(time.time())+60,'actor':{'kind':'human','ref':'human:synthetic:100'}}
            with TestClient(app,base_url='https://example.test') as client,patch('dashboard.home_auth.identity_response',return_value=identity):
                client.cookies.set('__Host-home','a'*43,path='/');access=client.get('/api/interaction/access');self.assertEqual(access.status_code,200,access.text);csrf=access.json()['csrf'];h={'origin':'https://example.test','x-dashboard-csrf':csrf};f=fixtures();path='/api/interaction/atelier'
                response=client.post(path,json={'action':'save-request','request':f['request']},headers=h);self.assertEqual(response.status_code,200,response.text)
                # A body exceeding the ordinary16KiB middleware bound remains
                # allowed only for the explicitly authenticated sculpture path.
                whitespace=f['request']+' '*20000
                self.assertEqual(client.post(path,json={'action':'save-request','request':whitespace},headers=h).status_code,409)
                self.assertEqual(client.post(path,json={'action':'save-request','request':f['request']},headers={**h,'x-dashboard-csrf':'wrong'}).status_code,403)
                identity['actor']['ref']='human:synthetic:200';self.assertEqual(client.get(path).status_code,403)
                self.assertEqual(app.state.atelier_workshop.snapshot(200)['requests'],[])
                self.assertEqual(provider.calls,[])

if __name__=='__main__':unittest.main()
