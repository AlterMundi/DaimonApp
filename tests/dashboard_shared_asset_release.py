"""Immutable frontend selection, safe serving and compatibility; zero providers."""
import base64
import gzip
import json
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard import shared_asset_release as r

class Releases(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.vendor=self.root/'vendor';self.vendor.mkdir();self.releases=self.root/'releases'
        self.files={n:b'fixed validator' for n in r.CONTRACT};self.files.update({'experiments/school-avatar-quest/index.html':b'old editor','experiments/school-avatar-quest/archive-assets/nunito.ttf':b'font','LICENSE':b'MIT'})
        for n,v in self.files.items():p=self.vendor/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(v)
        self.source='a'*40;self.metadata={'source':r.SOURCE,'source_revision':self.source,'files':{n:r.digest(v) for n,v in self.files.items()},'receiving_hashes':{n:r.digest(v) for n,v in self.files.items()},'author':'Maintainer','handoff_revision':'original'};self.write_metadata()
    def write_metadata(self):
        self.metadata['receiving_hashes']={n:r.digest((self.vendor/n).read_bytes()) for n in self.files};(self.vendor/'PROVENANCE.json').write_text(json.dumps(self.metadata))
    def transfer(self):return r.package(self.vendor,self.source)
    def test_frozen_module_graph_and_cas_preserve_prior_editor(self):
        a=r.prepare(self.releases,self.transfer(),self.vendor);r.activate(self.releases,a['release'],None,self.vendor)
        old=r.asset(self.releases,a['release'],'experiments/school-avatar-quest/index.html',self.vendor)[0]
        (self.vendor/'experiments/school-avatar-quest/index.html').write_bytes(b'new editor');self.write_metadata();b=r.prepare(self.releases,self.transfer(),self.vendor)
        r.activate(self.releases,b['release'],a['release'],self.vendor)
        self.assertEqual(r.asset(self.releases,a['release'],'experiments/school-avatar-quest/index.html',self.vendor)[0],old)
        self.assertEqual(r.asset(self.releases,b['release'],'experiments/school-avatar-quest/index.html',self.vendor)[0],b'new editor')
        self.assertEqual(r.activate(self.releases,b['release'],None,self.vendor)['state'],'already_selected')
        with self.assertRaises(ValueError):r.activate(self.releases,a['release'],None,self.vendor)
        self.assertEqual(r.current(self.releases)['release'],b['release'])
    def test_changed_validator_and_forged_bytes_refused_before_selection(self):
        raw=self.transfer();(self.vendor/r.CONTRACT[0]).write_bytes(b'new backend')
        with self.assertRaises(ValueError):r.prepare(self.releases,raw,self.vendor)
        self.assertIsNone(r.current(self.releases))
        (self.vendor/r.CONTRACT[0]).write_bytes(b'fixed validator');value=json.loads(gzip.decompress(raw));value['files']['LICENSE']=base64.b64encode(b'changed').decode()
        with self.assertRaises(ValueError):r.prepare(self.releases,gzip.compress(json.dumps(value).encode()),self.vendor)
    def test_source_path_expansion_and_transfer_bounds(self):
        for name in ('../secret','/secret','a/../b','a//b','a\\b'):
            self.assertFalse(r.safe_name(name))
        value=json.loads(gzip.decompress(self.transfer()));value['manifest']['source']='unknown/publisher'
        with self.assertRaises(ValueError):r.prepare(self.releases,gzip.compress(json.dumps(value).encode()),self.vendor)
        with self.assertRaises(ValueError):r.unpack(gzip.compress(b'x'*(6*1024*1024+1)),self.vendor)
    def test_ancestor_symlink_and_public_validator_are_refused(self):
        x=r.prepare(self.releases,self.transfer(),self.vendor);folder=self.releases/x['release']/'experiments';folder.rename(folder.with_name('original'));folder.symlink_to(folder.with_name('original'),target_is_directory=True)
        with self.assertRaises(OSError):r.asset(self.releases,x['release'],'experiments/school-avatar-quest/index.html',self.vendor)
        with self.assertRaises(FileNotFoundError):r.asset(self.releases,x['release'],'validate-design.mjs',self.vendor)
    def test_conflicting_adapter_changes_are_not_guessed(self):
        from scripts.build_workshop_release import merge
        self.assertEqual(merge('abcdef','aXbcdef','abcdeYf'),'aXbcdeYf')
        with self.assertRaises(ValueError):merge('abcdef','abXef','abYef')
        with self.assertRaises(ValueError):merge('abc','abXc','abYc')
        self.assertEqual(merge('abc','local','abc'),'local')
    def test_mounted_api_pins_redirects_fonts_and_prior_graph(self):
        from fastapi import FastAPI,HTTPException
        from fastapi.testclient import TestClient
        from dashboard.avatar_workshop_api import install
        from dashboard.avatar_workshop_provenance import receiving_hashes
        import dashboard.avatar_workshop_api as api
        vendor=Path(api.__file__).parent/'web/avatar-workshop'
        metadata=json.loads((vendor/'PROVENANCE.json').read_text());self.assertEqual(receiving_hashes(vendor),metadata['receiving_hashes'])
        app=FastAPI()
        class Owner:
            def authorized(self,human):return human==100
        async def authorize(request):raise HTTPException(401,'Synthetic actor required')
        state=self.root/'mounted';install(app,{'state_dir':str(state)},Owner(),authorize,['http://testserver'])
        target=state/'shared-app-assets/avatar-workshop';prepared=r.prepare(target,r.package(vendor,metadata['source_revision']),vendor);r.activate(target,prepared['release'],None,vendor)
        with TestClient(app) as client:
            path='/assets/avatar-workshop/experiments/school-avatar-quest/index.html'
            redirect=client.get(path,follow_redirects=False);self.assertEqual(redirect.status_code,307);self.assertIn('releases/'+prepared['release']+'/',redirect.headers['location'])
            from urllib.parse import urljoin
            html=client.get(urljoin('http://testserver'+path,redirect.headers['location']));self.assertEqual(html.status_code,200);self.assertIn('archive.css',html.text);self.assertIn('immutable',html.headers['cache-control'])
            font=client.get('/assets/avatar-workshop/releases/'+prepared['release']+'/experiments/school-avatar-quest/archive-assets/nunito.ttf');self.assertEqual(font.status_code,200);self.assertEqual(font.headers['content-type'],'font/ttf')
            self.assertEqual(client.get('/assets/avatar-workshop/releases/'+prepared['release']+'/validate-design.mjs').status_code,404)
            self.assertEqual(client.get('/api/interaction/avatars').status_code,401)

    def test_fonts_are_versioned_and_immutable(self):
        x=r.prepare(self.releases,self.transfer(),self.vendor);data,sha=r.asset(self.releases,x['release'],'experiments/school-avatar-quest/archive-assets/nunito.ttf',self.vendor);self.assertEqual(data,b'font');self.assertEqual(sha,r.digest(data))
        path=self.releases/x['release']/'experiments/school-avatar-quest/archive-assets/nunito.ttf';path.write_bytes(b'changed')
        with self.assertRaises(ValueError):r.asset(self.releases,x['release'],'experiments/school-avatar-quest/archive-assets/nunito.ttf',self.vendor)

class Distribution(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def test_lost_selection_ack_is_observed_without_second_write(self):
        from unittest.mock import patch
        from scripts.update_shared_workshop import deploy
        current={};writes=[]
        def call(target,action,**args):
            if action=='status':return {'current':{'release':current['release']} if current else None}
            if action=='prepare':return {'release':'a'*64,'current':None}
            writes.append(args);current['release']=args['release'];raise ValueError('Lost exact acknowledgment')
        state={'receipt_path':str(self.root/'receipt.json')};config={'targets':[{'id':'first'}]}
        with patch('scripts.update_shared_workshop.target_call',side_effect=call):
            first=deploy(config,b'frozen transfer',state);self.assertEqual(first['state'],'partial_update_retained');self.assertEqual(len(writes),1)
            first['targets']['first']['uncertain_until']=0
            second=deploy(config,b'frozen transfer',first);self.assertEqual(second['state'],'all_consumers_adopted_verified');self.assertEqual(len(writes),1)
    def test_later_direction_is_preserved_and_new_consumers_join(self):
        from unittest.mock import patch
        from scripts.update_shared_workshop import deploy
        calls=[];current={'first':'later'}
        def call(target,action,**args):
            calls.append((target['id'],action))
            if action=='status':return {'current':{'release':current[target['id']]} if current.get(target['id']) else None}
            if action=='prepare':return {'release':'a'*64,'current':None}
            current[target['id']]=args['release'];return {'release':args['release']}
        state={'receipt_path':str(self.root/'receipt.json'),'targets':{'first':{'phase':'activation_uncertain','uncertain_until':0,'release':'a'*64,'expected':None}}}
        with patch('scripts.update_shared_workshop.target_call',side_effect=call):
            result=deploy({'targets':[{'id':'first'},{'id':'new'}]},b'frozen transfer',state)
        self.assertEqual(result['state'],'partial_update_retained');self.assertEqual(current['first'],'later');self.assertNotIn(('first','activate'),calls);self.assertEqual(result['targets']['new']['phase'],'adopted_verified')
    def test_changed_consumer_binding_cannot_keep_an_old_success_label(self):
        from unittest.mock import patch
        from scripts.update_shared_workshop import deploy
        state={'receipt_path':str(self.root/'receipt.json'),'targets':{'first':{'phase':'adopted_verified','release':'a'*64,'binding_sha256':'old-binding'}}}
        with patch('scripts.update_shared_workshop.target_call') as call:
            result=deploy({'targets':[{'id':'first','config':'later-config'}]},b'frozen transfer',state)
        self.assertEqual(result['state'],'partial_update_retained');self.assertEqual(result['targets']['first']['phase'],'binding_changed');call.assert_not_called()
    def test_real_receiver_installs_code_only_and_resolves_exact_selection(self):
        import os,sys
        from unittest.mock import patch
        from scripts.update_shared_workshop import target_call
        import dashboard.avatar_workshop_api as api
        vendor=Path(api.__file__).parent/'web/avatar-workshop';metadata=json.loads((vendor/'PROVENANCE.json').read_text());raw=r.package(vendor,metadata['source_revision'])
        state=self.root/'state';state.mkdir();actor=state/'avatar-workshop';actor.mkdir();(actor/'original').write_bytes(b'unchanged actor history')
        cfg=self.root/'owner.toml';cfg.write_text('state_dir='+json.dumps(str(state))+'\n');cfg.chmod(0o600)
        tools=self.root/'bin';tools.mkdir();systemctl=tools/'systemctl';systemctl.write_text('#!/bin/sh\necho '+str(os.getpid())+'\n');systemctl.chmod(0o755)
        target={'id':'synthetic','service':'synthetic.service','config':str(cfg),'python':sys.executable}
        with patch.dict(os.environ,{'PATH':str(tools)+':'+os.environ['PATH']}):
            prepared=target_call(target,'prepare',package=base64.b64encode(raw).decode());selected=target_call(target,'activate',release=prepared['release'],expected=None)
            again=target_call(target,'activate',release=prepared['release'],expected=None);observed=target_call(target,'status')
        self.assertEqual(again['state'],'already_selected');self.assertEqual(observed['current']['release'],selected['release']);self.assertFalse(selected['web_restart']);self.assertEqual((actor/'original').read_bytes(),b'unchanged actor history')

if __name__=='__main__':unittest.main()
