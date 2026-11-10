"""Mounted grant/CSRF/isolation and actual Node-backed workshop persistence."""
from pathlib import Path
import hashlib
import sys
from unittest.mock import patch
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from dashboard.avatar_workshop import AvatarWorkshop,validate_design
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
        self.config={'state_dir':str(self.root)}
        app=FastAPI();install(app,self.config,Owner(),authorize,['https://example.test'])
        self.client=TestClient(app,base_url='https://example.test');self.addCleanup(self.client.close)
        self.headers={'origin':'https://example.test','authorization':'actor100','x-dashboard-csrf':'fresh'}
        self.body={'action':'save','id':self.ident,'design':self.design,'parentId':None,'generation':0}

    def test_voice_account_csrf_save_and_explicit_next_conversation_selection(self):
        path='/api/interaction/avatars/voice'
        self.config['openai_live']={'enabled':True,'session_options':{'audio':{'output':{'voice':'cedar'}}}}
        self.assertTrue(permitted('GET',path));self.assertTrue(permitted('POST',path))
        self.assertFalse(permitted('POST',path,'monitor_readonly'))
        state=self.client.get(path,headers=self.headers).json();profile=state['profiles'][0]
        body={'action':'save','id':self.ident,'profile':profile,'delivery':'Warm.', 'parentId':None,'generation':0}
        self.assertEqual(self.client.post(path,json=body,headers={'authorization':'actor100'}).status_code,403)
        saved=self.client.post(path,json=body,headers=self.headers)
        self.assertEqual(saved.status_code,200,saved.text);self.assertIsNone(saved.json()['active'])
        self.assertEqual(self.client.post(path,json=body,headers=self.headers).json(),saved.json())
        used=self.client.post(path,json={'action':'use','id':self.ident,'generation':1},headers=self.headers)
        self.assertEqual(used.status_code,200,used.text);self.assertEqual(used.json()['active'],self.ident)
        foreign=self.client.get(path,headers={'authorization':'actor200'}).json()
        self.assertEqual(foreign['versions'],[])
        self.assertEqual(self.store.snapshot(100)['active'],None)
        body['id']=str(__import__('uuid').uuid4());body['profile']={**profile,'voice':'unknown'}
        self.assertEqual(self.client.post(path,json=body,headers=self.headers).status_code,400)

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

    def test_mission_routes_keep_auth_and_refuse_an_unconnected_host(self):
        path='/api/interaction/avatars/missions/'+self.ident
        self.assertTrue(permitted('GET',path));self.assertTrue(permitted('POST',path))
        self.assertFalse(permitted('GET',path,'monitor_readonly'))
        self.assertFalse(permitted('GET',path+'/extra'))
        self.assertEqual(self.client.get(path).status_code,401)
        self.assertEqual(self.client.get(path,headers=self.headers).status_code,503)
        self.assertEqual(self.client.post(path,headers={**self.headers,'x-dashboard-csrf':'bad'},json={'revision_id':self.ident}).status_code,403)
        self.assertEqual(self.client.post(path,headers=self.headers,json={'revision_id':self.ident,'learner_id':'spoof'}).status_code,400)
        self.assertEqual(self.client.post(path,headers=self.headers,json={'revision_id':self.ident}).status_code,503)

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

    def test_canonical_export_is_exact_immutable_validator_bytes_without_use(self):
        self.design['name']='Lámpara 🧭'
        canonical,digest=validate_design(self.design)
        path='/api/interaction/avatars/'+self.ident
        saved=self.client.post('/api/interaction/avatars',json=self.body,headers=self.headers)
        self.assertEqual(saved.status_code,200,saved.text)
        before=self.store._path(100).read_bytes()
        response=self.client.get(path+'?format=canonical',headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.content,canonical.encode('utf-8'))
        self.assertEqual(hashlib.sha256(response.content).hexdigest(),digest)
        self.assertEqual(response.headers['etag'],'"sha256-'+digest+'"')
        self.assertEqual(response.headers['cache-control'],'private, no-store')
        self.assertEqual(response.headers['x-content-type-options'],'nosniff')
        self.assertEqual(response.headers['content-disposition'],
                         'attachment; filename="'+self.ident+'.avatar.json"')
        self.assertEqual(AvatarWorkshop(self.root).get(100,self.ident,True),canonical)
        record=self.client.get(path,headers=self.headers).json()
        self.assertNotIn('canonical',record)
        self.assertEqual(record['sha256'],digest)
        repeated=self.client.get(path+'?format=canonical',headers={**self.headers,'if-none-match':response.headers['etag']})
        self.assertEqual(repeated.status_code,200)
        self.assertEqual(repeated.content,response.content)
        self.assertEqual(self.store._path(100).read_bytes(),before)
        self.assertIsNone(self.store.snapshot(100)['active'])

    def test_canonical_export_uses_existing_actor_and_current_access_checks(self):
        self.client.post('/api/interaction/avatars',json=self.body,headers=self.headers)
        path='/api/interaction/avatars/'+self.ident+'?format=canonical'
        for token,status in ((None,401),('actor200',404),('monitor',403)):
            headers={'authorization':token} if token else {}
            self.assertEqual(self.client.get(path,headers=headers).status_code,status)
        self.assertEqual(self.client.get(path.replace('canonical','unknown'),headers=self.headers).status_code,400)
        read=AvatarWorkshop.get;test=self
        def revoke(store,*args):
            value=read(store,*args);test.allowed.clear();return value
        with patch.object(AvatarWorkshop,'get',revoke):
            response=self.client.get(path,headers=self.headers)
        self.assertEqual(response.status_code,403)
        self.assertNotIn('etag',response.headers)

    def test_canonical_export_refuses_changed_stored_bytes(self):
        self.client.post('/api/interaction/avatars',json=self.body,headers=self.headers)
        value=self.store._read(100)
        value['versions'][0]['canonical']+=' '
        self.store._write(100,value)
        before=self.store._path(100).read_bytes()
        response=self.client.get('/api/interaction/avatars/'+self.ident+'?format=canonical',headers=self.headers)
        self.assertEqual(response.status_code,400)
        self.assertNotIn('etag',response.headers)
        self.assertEqual(self.store._path(100).read_bytes(),before)

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

    def test_only_shipped_editor_assets_are_public(self):
        path='/assets/avatar-workshop/'
        response=self.client.get(path+'experiments/school-avatar-quest/index.html')
        self.assertEqual(response.status_code,200)
        self.assertIn('Usar este avatar',response.text)
        module=self.client.get(path+'renderer.mjs')
        self.assertEqual(module.status_code,200)
        self.assertIn('javascript',module.headers['content-type'])
        for name in ('PROVENANCE.json','validate-design.mjs','100.json','../../avatar-workshop/100.json'):
            self.assertEqual(self.client.get(path+name).status_code,404,name)

    def test_selected_archive_fonts_only_are_public_assets(self):
        base='/assets/avatar-workshop/experiments/school-avatar-quest/'
        for name in ('pixelifysans.ttf','nunito.ttf'):
            reply=self.client.get(base+'archive-assets/'+name)
            self.assertEqual(reply.status_code,200)
            self.assertTrue(reply.headers['content-type'].startswith('font/ttf'))
            self.assertGreater(len(reply.content),1000)
        for name in ('private.ttf','nunito-OFL.txt','../../PROVENANCE.json'):
            self.assertEqual(self.client.get(base+'archive-assets/'+name).status_code,404)


if __name__=='__main__':
    from dashboard_school_mission_host import Selection
    unittest.main()
