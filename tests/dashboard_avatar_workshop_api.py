"""Mounted grant/CSRF/isolation and actual Node-backed workshop persistence."""
from pathlib import Path
import sys
from unittest.mock import patch
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from dashboard.avatar_workshop import AvatarWorkshop
from dashboard.avatar_workshop_api import install
from dashboard.companion import permitted
import dashboard_avatar_workshop as fixtures


class Mounted(unittest.TestCase):
    def setUp(self):
        fixtures.Workshop.setUp(self);self.allowed={100,200}
        test=self
        class Owner:
            def authorized(self,human):return human in test.allowed
        async def authorize(request):
            token=request.headers.get('authorization')
            if token not in ('actor100','actor200','monitor'):raise HTTPException(401,'Sign in')
            return {'human':200 if token=='actor200' else 100,'csrf':'fresh',
                    'scope':'monitor_readonly' if token=='monitor' else 'interaction_only'}
        app=FastAPI();install(app,{'state_dir':str(self.root)},Owner(),authorize,['https://example.test'])
        self.client=TestClient(app,base_url='https://example.test');self.addCleanup(self.client.close)
        self.headers={'origin':'https://example.test','authorization':'actor100','x-dashboard-csrf':'fresh'}
        self.body={'action':'save','id':self.ident,'design':self.design,'parentId':None,'generation':0}

    def test_existing_grant_scope_and_csrf_are_required(self):
        path='/api/interaction/avatars'
        self.assertTrue(permitted('GET',path));self.assertTrue(permitted('POST',path))
        self.assertFalse(permitted('GET',path,'monitor_readonly'))
        self.assertFalse(permitted('POST',path,'monitor_readonly'))
        self.assertFalse(permitted('GET',path+'/other-account'))
        self.assertEqual(self.client.get(path).status_code,401)
        self.assertEqual(self.client.post(path,json=self.body,headers={**self.headers,'x-dashboard-csrf':'bad'}).status_code,403)
        self.assertEqual(self.client.get(path,headers={**self.headers,'authorization':'monitor'}).status_code,403)
        self.assertEqual(self.store.snapshot(100)['versions'],[])

    def test_authenticated_save_reload_and_explicit_use(self):
        path='/api/interaction/avatars'
        response=self.client.post(path,json=self.body,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text);self.assertIsNone(response.json()['active'])
        loaded=self.client.get(path+'/'+self.ident,headers=self.headers)
        self.assertEqual(loaded.status_code,200);self.assertEqual(loaded.json()['design']['body'],'modular-bot')
        used=self.client.post(path,json={'action':'activate','id':self.ident,'generation':1},headers=self.headers)
        self.assertEqual(used.status_code,200,used.text);self.assertEqual(used.json()['active'],self.ident)
        stale=self.client.post(path,json={'action':'edit','id':self.ident,'generation':1},headers=self.headers)
        self.assertEqual(stale.status_code,409)

    def test_actor_identity_never_comes_from_an_import_or_foreign_revision(self):
        path='/api/interaction/avatars';self.client.post(path,json=self.body,headers=self.headers)
        foreign={**self.headers,'authorization':'actor200'}
        self.assertEqual(self.client.get(path+'/'+self.ident,headers=foreign).status_code,404)
        self.assertEqual(self.client.post(path,json={'action':'activate','id':self.ident,'generation':0},headers=foreign).status_code,404)
        self.assertEqual(self.client.post(path,json={**self.body,'human':100},headers=foreign).status_code,400)
        self.assertEqual(self.store.snapshot(200)['versions'],[])

    def test_revocation_after_commit_preserves_immutable_save_for_status_readback(self):
        path='/api/interaction/avatars';write=AvatarWorkshop._write;test=self
        def revoked(store,*args):write(store,*args);test.allowed.clear()
        with patch.object(AvatarWorkshop,'_write',revoked):
            self.assertEqual(self.client.post(path,json=self.body,headers=self.headers).status_code,403)
        self.assertEqual(len(self.store.snapshot(100)['versions']),1)
        self.allowed.add(100)
        retry=self.client.post(path,json=self.body,headers=self.headers)
        self.assertEqual(retry.status_code,200,retry.text);self.assertEqual(len(retry.json()['versions']),1)

    def test_oversized_import_refuses_before_validation_or_storage(self):
        response=self.client.post('/api/interaction/avatars',content=b'x'*(1024*1024+1),headers=self.headers)
        self.assertEqual(response.status_code,413)
        self.assertEqual(self.store.snapshot(100)['generation'],0)


if __name__=='__main__':unittest.main()
