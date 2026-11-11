"""Explicit device grants through actual private files, HTTP and speech cache."""
import copy
import asyncio
import threading
import httpx
import hashlib
import os
import tempfile
import uuid
import concurrent.futures
import json
import sqlite3
from pathlib import Path
import sys
import time
import tomllib
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from dashboard.speech import speech_part, speech_request
from dashboard.app import create_app
from dashboard.companion import Grants, authority
from dashboard.provider import Provider, ProviderUnavailable, receiving_authority
from dashboard.private_state import read_json, write_json
from presentation_io import Receiver
import speech_render as speech_fixture
from scripts import speech_render as renderer


class Owner(Receiver):
    human = 100
    binding_bytes = b'fictional-native-owner-entry-and-target-profile'
    def assert_binding(self): pass


class Companion(unittest.TestCase):
    def setUp(self):
        self.speech = speech_fixture.Render(); self.speech.setUp()
        self.root = self.speech.root
        self.provider = Owner()
        self.config = {'state_dir':str(self.root/'dashboard'), 'origin':'https://example.test',
            'bot_id':123, 'prefix':'/sessions',
            'companion':{'enabled':True,'grants_dir':str(self.root/'grants')},
            'speech':{'binding':str(self.speech.binding),'timeout_seconds':5}}
        self.grants = Grants(self.config, self.provider)
        self.output = self.root/'device.json'
        self.receipt = self.grants.enroll('Selected fixture button', self.output, 3600)
        self.device = read_json(self.output)
        self.record = self.root/'grants'/(self.receipt['grant_id']+'.json')
        self.client = self.client_for()
        self.headers = {'origin':self.config['origin'], 'authorization':self.device['authorization'],
            'x-dashboard-csrf':self.device['csrf']}
        self.body = {'source':self.provider.source['id'],'revision':self.provider.source['revision'],'offset':0}

    def client_for(self):
        return TestClient(create_app(self.config,self.provider,lambda raw,bot:int(raw)),base_url=self.config['origin'])

    def tearDown(self):
        self.client.close(); self.speech.tearDown()

    def audio(self):
        return self.client.post('/api/interaction/audio',json=self.body,headers=self.headers)

    def web_only(self):
        self.config.pop('bot_id')
        self.config['application_id']='fa34f9ac-3ee0-435f-87be-d91dded19b52'
        self.provider.receiver={'telegram':{'enabled':False}}
        self.config['shared_auth']={'enabled':True,'home_origin':self.config['origin'],
                                    'human_ref':'human:telegram:100'}
        self.client.close();self.client=self.client_for()

    def test_web_only_shared_identity_has_no_telegram_exchange_or_fake_bot(self):
        self.web_only()
        self.provider.conversation_inputs=lambda before,direction:{'items':[],'more':False}
        calls=[]
        self.provider.conversation_input_submit=lambda body:calls.append(body) or {'phase':'queued'}
        identity={'contract':'dm.home-session/v1','origin':self.config['origin'],
                  'expires':int(time.time())+3600,
                  'actor':{'kind':'human','ref':'human:telegram:100'}}
        headers={'Host':'example.test','Origin':self.config['origin'],'Cookie':'__Host-home='+'h'*43}
        # A prior device grant from a bot-scoped app never gains the web scope.
        self.assertEqual(self.client.get('/api/interaction/access',headers=self.headers).status_code,401)
        with patch('dashboard.home_auth.identity_response',return_value=identity):
            access=self.client.get('/api/interaction/access',headers=headers)
            self.assertEqual(access.status_code,200,access.text)
            self.assertEqual(self.client.get('/api/interaction/inputs',headers=headers).status_code,200)
            payload={'id':str(uuid.uuid4()),'text':'Synthetic web-only original'}
            self.assertEqual(self.client.post('/api/interaction/inputs',json=payload,headers=headers).status_code,403)
            write={**headers,'X-Dashboard-CSRF':access.json()['csrf']}
            self.assertEqual(self.client.post('/api/interaction/inputs',json=payload,headers={**write,'Origin':'https://other.test'}).status_code,403)
            self.assertEqual(calls,[])
            self.assertEqual(self.client.post('/api/interaction/inputs',json=payload,headers=write).status_code,200)
            self.assertEqual(calls,[payload])
            identity['actor']['ref']='human:telegram:101'
            self.assertEqual(self.client.get('/api/interaction/access',headers=headers).status_code,403)
        for route in ['/api/session','/api/alerts/attention']:
            self.assertEqual(self.client.post(route,json={'init_data':'100'},headers=headers).status_code,403)

    def test_web_only_configuration_requires_explicit_scope_and_native_transport_off(self):
        self.web_only()
        candidates=[]
        for key,value in [('bot_id',123),('bot_username','not_a_real_bot'),('miniapp_short_name','App')]:
            item=copy.deepcopy(self.config);item[key]=value;candidates.append(item)
        for name in ['alerts','traffic']:
            item=copy.deepcopy(self.config);item[name]={'enabled':True};candidates.append(item)
        for config in candidates:
            with self.assertRaises(ValueError):create_app(config,self.provider)
        self.provider.receiver={'telegram':{'enabled':True}}
        with self.assertRaises(ValueError):self.client_for()
        self.provider.receiver={'telegram':{'enabled':False}}
        del self.config['shared_auth']['human_ref']
        with self.assertRaises(ValueError):self.client_for()

    def test_web_only_scope_change_invalidates_device_and_csrf_without_changing_legacy_scope(self):
        legacy=authority(self.config,self.provider)
        expected=hashlib.sha256(json.dumps([123,self.config['origin'],'/sessions',
                self.provider.binding_bytes.hex()],separators=(',',':')).encode()).hexdigest()
        self.assertEqual(legacy,expected)
        self.web_only()
        from dashboard.home_auth import HomeAuth
        before=HomeAuth(self.config,self.provider).binding
        prior=authority(self.config,self.provider)
        self.config['application_id']=str(uuid.uuid4())
        self.assertNotEqual(prior,authority(self.config,self.provider))
        self.assertNotEqual(before,HomeAuth(self.config,self.provider).binding)
        prior=authority(self.config,self.provider)
        before=HomeAuth(self.config,self.provider).binding
        self.config['shared_auth']['human_ref']='human:telegram:101'
        self.assertNotEqual(prior,authority(self.config,self.provider))
        self.assertNotEqual(before,HomeAuth(self.config,self.provider).binding)

    def test_web_only_post_start_telegram_enable_refuses_existing_access(self):
        self.web_only()
        receiver_path=self.root/'web-only-receiver.toml'
        database_path=self.root/'web-only-users.sqlite'
        with sqlite3.connect(database_path) as db:
            db.execute('CREATE TABLE users(tg_user_id INTEGER,allowed INTEGER)')
            db.execute('INSERT INTO users VALUES(100,1)')
        db.close()
        receiver_path.write_text('db_path='+json.dumps(str(database_path))+
            '\n[session_control]\nhuman_id=100\n[telegram]\nenabled=false\n')
        receiving=Provider({'receiver_config':str(receiver_path)})
        self.provider.receiver=receiving.receiver
        self.provider.binding_bytes=receiving.binding_bytes
        self.provider.assert_binding=receiving.assert_binding
        self.provider.authorized=receiving.authorized
        self.client.close();self.client=self.client_for()
        grants=Grants(self.config,self.provider)
        output=self.root/'web-only-device.json'
        grants.enroll('Web-only fixture',output,3600)
        device=read_json(output)
        headers={'Host':'example.test','Origin':self.config['origin'],
                 'Cookie':'__Host-home='+'h'*43}
        identity={'contract':'dm.home-session/v1','origin':self.config['origin'],
                  'expires':int(time.time())+3600,
                  'actor':{'kind':'human','ref':'human:telegram:100'}}
        with patch('dashboard.home_auth.identity_response',return_value=identity):
            self.assertEqual(self.client.get('/api/interaction/access',headers=headers).status_code,200)
            self.assertIsNotNone(grants.authenticate(device['authorization'].split(' ',1)[1]))
            receiver_path.write_text(receiver_path.read_text().replace('enabled=false','enabled=true'))
            with self.assertRaises(ProviderUnavailable):receiving.assert_binding()
            self.assertEqual(self.client.get('/api/interaction/access',headers=headers).status_code,503)
            self.assertIsNone(grants.authenticate(device['authorization'].split(' ',1)[1]))
            receiving.receiver=tomllib.loads(receiver_path.read_text())
            with self.assertRaises(ValueError):create_app(self.config,receiving)

    def test_enabled_legacy_receiving_authority_keeps_its_original_bytes(self):
        receiver={'session_control':{'human_id':100},'telegram':{'api_base':'https://example.test'}}
        expected=json.dumps({'db_path':None,'session_control':receiver['session_control'],
            'interaction':None,'voice':None,'telegram':{'api_base':'https://example.test',
            'bot_token':None,'bot_token_file':None},'native_binary':'codex'},
            sort_keys=True,separators=(',',':')).encode()
        self.assertEqual(receiving_authority(receiver),expected)
        receiver['telegram']['enabled']=True
        self.assertEqual(receiving_authority(receiver),expected)
        receiver['telegram']['enabled']=False
        self.assertNotEqual(receiving_authority(receiver),expected)

    def test_malformed_identity_response_is_unavailable_not_expired(self):
        from dashboard.home_auth import identity_response
        for body in (b'{', b'\xff'):
            with patch('dashboard.home_auth.http.client.HTTPSConnection') as connection:
                response=connection.return_value.getresponse.return_value
                response.status=200;response.read.return_value=body
                with self.assertRaises(OSError):
                    identity_response('https://home.example.test','h'*43)
                connection.return_value.close.assert_called_once()

    def test_shared_home_session_is_fileless_scoped_and_revalidated(self):
        self.config['shared_auth']={'enabled':True,'home_origin':'https://home.example.test'}
        self.config['additional_origins']=['https://home.example.test']
        self.client.close();self.client=self.client_for()
        self.provider.conversation_inputs=lambda before,direction: {'items':[], 'more':False}
        self.provider.conversation_telegram_inputs=lambda before,direction: {'items':[], 'read_only':True}
        self.provider.conversation_input_trace=lambda ident: {'id':ident,'read_only':True}
        submitted=[]
        self.provider.conversation_input_submit=lambda body: submitted.append(body) or {'phase':'queued'}
        token='h'*43
        headers={'Host':'home.example.test','Cookie':'__Host-home='+token,
                 'Origin':'https://home.example.test'}
        identity={'contract':'dm.home-session/v1','origin':'https://home.example.test','expires':int(time.time())+3600,
                  'actor':{'ref':'human:telegram:100','kind':'human','name':'Fixture'}}
        with patch('dashboard.home_auth.identity_response',return_value=identity) as current:
            access=self.client.get('/api/interaction/access',headers=headers)
            self.assertEqual(access.status_code,200,access.text)
            self.assertNotIn(token,access.text)
            self.assertEqual(self.client.get('/api/interaction',headers=headers).status_code,200)
            self.assertEqual(self.client.get('/api/interaction/inputs',headers=headers).status_code,200)
            self.assertEqual(self.client.get('/api/interaction/telegram-inputs',headers=headers).status_code,200)
            self.assertEqual(self.client.get('/api/interaction/inputs/telegram:123/trace',headers=headers).status_code,200)
            payload={'id':str(uuid.uuid4()),'text':'Shared session text'}
            for csrf in ('', 'wrong'):
                denied=self.client.post('/api/interaction/inputs',json=payload,headers={**headers,'X-Dashboard-CSRF':csrf})
                self.assertEqual(denied.status_code,403)
            write_headers={**headers,'X-Dashboard-CSRF':access.json()['csrf']}
            self.assertEqual(self.client.post('/api/interaction/inputs',json=payload,headers={**write_headers,'Origin':'https://unrelated.example.test'}).status_code,403)
            self.assertEqual(submitted,[])
            self.assertEqual(self.client.post('/api/interaction/inputs',json=payload,headers=write_headers).status_code,200)
            self.assertEqual(submitted,[payload])
            for path in ('/api/state','/api/traffic','/api/alerts'):
                self.assertEqual(self.client.get(path,headers=headers).status_code,403,path)
            self.assertEqual(self.client.post('/api/stop',json={},headers=headers).status_code,403)
            self.assertEqual(current.call_args.args,('https://home.example.test',token))
            self.assertEqual(self.client.get('/api/interaction',headers={**headers,'Authorization':'Companion invalid'}).status_code,401)
            self.assertEqual(self.client.get('/api/interaction',headers={**headers,'Host':'other.example.test'}).status_code,401)
            changed={**identity,'actor':{**identity['actor'],'ref':'human:telegram:200'}}
            current.return_value=changed
            self.assertEqual(self.client.get('/api/interaction/access',headers=headers).status_code,403)
            current.return_value={'actor':None}
            self.assertEqual(self.client.get('/api/interaction/access',headers=headers).status_code,503)
            current.side_effect=ValueError('revoked')
            self.assertEqual(self.client.get('/api/interaction',headers=headers).status_code,401)
        redirect=self.client.get('/?view=conversation&client=standalone',follow_redirects=False)
        self.assertEqual(redirect.status_code,307)
        self.assertEqual(redirect.headers['location'],'https://home.example.test/interaction/?view=conversation&client=standalone')
        shell=self.client.get('/?view=conversation&client=standalone',headers={'Host':'home.example.test'})
        self.assertIn('data-shared-auth="true"',shell.text)
        self.assertIn('src="/access-client.js"',shell.text)
        self.assertNotIn('telegram.org/js',shell.text)
        self.assertLess(shell.text.index('src="/access-client.js"'),shell.text.index('src="assets/app.js'))
        clean=self.client.get('/',headers={'Host':'home.example.test','X-Forwarded-Prefix':'/interaction'},follow_redirects=False)
        self.assertEqual(clean.status_code,307)
        self.assertEqual(clean.headers['location'],'https://home.example.test/interaction/?view=conversation&client=standalone')
        shorthand=self.client.get('/?view=conversation',headers={'Host':'home.example.test'},follow_redirects=False)
        self.assertEqual(shorthand.status_code,307)

    def test_explicit_home_native_decisions_keep_device_and_admin_boundaries(self):
        self.config['shared_auth']={'enabled':True,'home_origin':'https://home.example.test'}
        self.config['additional_origins']=['https://home.example.test']
        self.client.close();self.client=self.client_for()
        identity={'contract':'dm.home-session/v1','origin':'https://home.example.test',
                  'expires':int(time.time())+3600,'actor':{'ref':'human:telegram:100','kind':'human','name':'Fixture'}}
        headers={'Host':'home.example.test','Cookie':'__Host-home='+'h'*43,'Origin':'https://home.example.test'}
        ident='b'*32;binding='a'*64;revision='c'*64;calls=[]
        original=self.provider.presentation
        self.provider.request_id=Provider.request_id
        def presentation(command):
            if command.startswith(('requests decide ','requests internal decide ')):
                calls.append(command);return {'id':ident,'binding':binding,'revision':revision,'recorded':True}
            return original(command)
        self.provider.presentation=presentation
        self.provider.conversation_request_decide=lambda ident,body,internal=False:Provider.conversation_request_decide(self.provider,ident,body,internal)
        body={'binding':binding,'revision':revision,'action':{'kind':'approval','choice':'a'}}
        with patch('dashboard.home_auth.identity_response',return_value=identity):
            access=self.client.get('/api/interaction/access',headers=headers).json()
            headers['x-dashboard-csrf']=access['csrf']
            self.assertFalse(self.client.get('/api/interaction?can_decide_requests=true',headers=headers).json()['can_decide_requests'])
            for path in ('/api/interaction/requests/'+ident,'/api/interaction/internal/requests/'+ident):
                self.assertEqual(self.client.post(path,json=body,headers=headers).status_code,403)
            self.assertEqual(calls,[])
            self.config['shared_auth']['native_decision_access']=True
            self.client.close();self.client=self.client_for()
            self.assertTrue(self.client.get('/api/interaction',headers=headers).json()['can_decide_requests'])
            path='/api/interaction/requests/'+ident
            self.assertEqual(self.client.post(path,json=body,headers={**headers,'x-dashboard-csrf':'wrong'}).status_code,403)
            self.assertEqual(calls,[])
            for path in ('/api/interaction/requests/'+ident,'/api/interaction/internal/requests/'+ident):
                result=self.client.post(path,json=body,headers=headers)
                self.assertEqual(result.status_code,200,result.text)
                self.assertEqual(json.loads(calls[-1].split('decide ',1)[1]),{**body,'id':ident})
            count=len(calls)
            limited={**headers,**self.headers}
            self.assertFalse(self.client.get('/api/interaction',headers=limited).json()['can_decide_requests'])
            for path in ('/api/interaction/requests/'+ident,'/api/interaction/internal/requests/'+ident):
                self.assertEqual(self.client.post(path,json=body,headers=limited).status_code,403)
            for path in ('/api/stop','/api/resume'):
                self.assertEqual(self.client.post(path,json={},headers=headers).status_code,403)
            self.assertEqual(self.client.get('/api/state',headers=headers).status_code,403)
            self.assertEqual(len(calls),count)
            identity['actor']['ref']='human:telegram:101'
            self.assertEqual(self.client.post('/api/interaction/internal/requests/'+ident,json=body,headers=headers).status_code,403)
            self.assertEqual(len(calls),count)

    def test_home_native_decision_policy_requires_an_explicit_boolean(self):
        from dashboard.home_auth import HomeAuth
        self.config['shared_auth']={'enabled':True,'home_origin':'https://home.example.test','native_decision_access':'true'}
        with self.assertRaises(ValueError):HomeAuth(self.config,self.provider)

    def test_shared_alert_read_is_explicit_and_does_not_widen_device_or_control_grants(self):
        class Alerts:
            binding='fixture-alert-scope'
            calls=0
            revoke=None
            def assert_binding(self): pass
            def start(self): pass
            def close(self): pass
            def snapshot(self):
                self.calls+=1
                if self.revoke: self.revoke()
                return {'state':'available','observer_state':'healthy','incidents':[
                    {'projection':{'producer_id':'fixture','incident_id':'case','severity':'error',
                                   'processing_state':'open','summary':'Safe operational summary'},
                     'acknowledgments':[]}], 'resolved_incidents':[]}
        alerts=Alerts()
        self.config['shared_auth']={'enabled':True,'home_origin':'https://home.example.test'}
        self.config['additional_origins']=['https://home.example.test']
        def reopen():
            self.client.close()
            self.client=TestClient(create_app(self.config,self.provider,lambda raw,bot:int(raw),alerts=alerts),base_url=self.config['origin'])
        reopen()
        headers={'Host':'home.example.test','Cookie':'__Host-home='+'h'*43,'Origin':'https://home.example.test'}
        identity={'contract':'dm.home-session/v1','origin':'https://home.example.test','expires':int(time.time())+3600,
                  'actor':{'ref':'human:telegram:100','kind':'human','name':'Fixture'}}
        with patch('dashboard.home_auth.identity_response',return_value=identity):
            self.assertEqual(self.client.get('/api/interaction/alerts',headers=headers).status_code,403)
            self.assertEqual(alerts.calls,0,'A default conversation grant must not read operational incidents')
            self.config['shared_auth']['alerts_access']=True
            reopen()
            response=self.client.get('/api/interaction/alerts',headers=headers)
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['attention']['level'],'error')
            self.assertEqual(response.json()['attention']['count'],1)
            self.assertIs(response.json()['read_only'],True)
            for path in ('/api/alerts','/api/state','/api/traffic'):
                self.assertEqual(self.client.get(path,headers=headers).status_code,403,path)
            self.assertEqual(self.client.post('/api/alerts/acknowledge',json={},headers=headers).status_code,403)
            self.assertEqual(self.client.post('/api/stop',json={},headers=headers).status_code,403)
            before=alerts.calls
            self.assertEqual(self.client.get('/api/interaction/alerts',headers=self.headers).status_code,403,
                             'Existing companion files do not inherit the separate shared-browser grant')
            self.assertEqual(alerts.calls,before)
            identity['actor']['ref']='human:telegram:999'
            self.assertEqual(self.client.get('/api/interaction/alerts',headers=headers).status_code,403)
            identity['actor']['ref']='human:telegram:100'
            alerts.revoke=lambda:setattr(self.provider,'authorized',lambda human:False)
            denied=self.client.get('/api/interaction/alerts',headers=headers)
            self.assertEqual(denied.status_code,403,denied.text)
            self.assertNotIn('Safe operational summary',denied.text,'Post-read revocation must fence the retained snapshot')

    def test_delayed_shared_identity_does_not_block_unrelated_dashboard_io(self):
        self.config['shared_auth']={'enabled':True,'home_origin':'https://home.example.test'}
        app=create_app(self.config,self.provider,lambda raw,bot:int(raw))
        self.provider.conversation_inputs=lambda before,direction: {'items':[], 'more':False}
        entered,release=threading.Event(),threading.Event()
        def delayed(origin,token):
            entered.set();release.wait(3)
            return {'contract':'dm.home-session/v1','origin':origin,'expires':int(time.time())+3600,
                    'actor':{'ref':'human:telegram:100','kind':'human','name':'Fixture'}}
        async def scenario():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://home.example.test') as client:
                work=asyncio.create_task(client.get('/api/interaction/inputs',headers={'Cookie':'__Host-home='+'h'*43}))
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait,1))
                    started=time.monotonic()
                    self.assertEqual((await client.get('/health')).status_code,200)
                    self.assertLess(time.monotonic()-started,.5)
                finally:release.set()
                self.assertEqual((await work).status_code,200)
        with patch('dashboard.home_auth.identity_response',side_effect=delayed) as lookup:
            asyncio.run(scenario())
        self.assertEqual(lookup.call_count,2,'Revalidate after I/O without a cross-request identity cache')

    def test_live_speech_requires_selected_configuration(self):
        self.provider.source['kind']='integrator_live'
        rejected=self.audio()
        self.assertEqual(rejected.status_code,409)
        self.assertEqual(len(self.speech.calls),0)
        self.config['speech']['live_response']=True
        self.client.close();self.client=self.client_for()
        result=self.audio()
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(len(self.speech.calls),1)

    def test_incremental_parts_preserve_full_unicode_text_and_question_contract(self):
        text=('A sentence with a technical command git status and 🙂. '*70)
        offset=0;parts=[]
        while offset<len(text):
            canonical={**self.provider.source,'text':text[offset:offset+1600],'offset':offset,
                       'next_offset':offset+1600 if offset+1600<len(text) else None}
            selected=speech_part(canonical);parts.append(selected['text'])
            self.assertEqual(selected['text'],text[offset:offset+len(selected['text'])])
            end=offset+len(selected['text']);self.assertGreater(end,offset)
            self.assertLessEqual(len(selected['text']),240 if offset==0 else 640)
            self.assertEqual(selected['next_offset'],end if end<len(text) else None)
            offset=end
        self.assertEqual(''.join(parts),text)
        question={**self.provider.source,'kind':'native_question','text':text[:1500]}
        self.assertIs(speech_part(question),question,'Synthetic question labels retain their established offsets')

    def test_incremental_part_does_not_cut_link_label_or_destination(self):
        text='A sentence explaining the result. '*6+'[the official documentation](https://example.org/'+'path/'*80+'). Continue.'
        part={'text':text,'offset':0,'next_offset':None,'kind':'integrator_answer'}
        segments=[]
        while part['text']:
            chosen=speech_part(part);segments.append(chosen['text'])
            self.assertEqual(chosen['text'].count('['),chosen['text'].count(']'))
            used=len(chosen['text']);self.assertGreater(used,0)
            part={**part,'text':part['text'][used:],'offset':part['offset']+used}
        self.assertEqual(''.join(segments),text)

    def test_worker_voice_introduction_is_natural_and_does_not_change_source(self):
        source={'entry_binding':'fixture','id':'worker:1','kind':'worker_progress',
                'label':'#Realtime','offset':0,'text':'**A useful update.**'}
        original=copy.deepcopy(source)
        self.assertEqual(speech_request(source,'es-US')['text'],'Novedades desde Realtime\n\n**A useful update.**')
        self.assertEqual(speech_request(source,'en-US')['text'],'Update from Realtime\n\n**A useful update.**')
        self.assertEqual(speech_request({**source,'offset':100},'es-US')['text'],source['text'])
        self.assertEqual(speech_request({**source,'label':'#Realtime.'},'es-US')['text'],'Novedades desde Realtime\n\n**A useful update.**')
        self.assertEqual(source,original,'Canonical source and offsets remain unchanged')

    def test_incremental_audio_is_an_exact_canonical_prefix(self):
        self.config['speech']['incremental_segments']=True
        self.provider.source['text']=('A complete sentence with Unicode 🙂 and a command git status. '*30)
        self.client.close();self.client=self.client_for()
        response=self.audio();self.assertEqual(response.status_code,200,response.text)
        end=int(response.headers['x-presentation-end-offset'])
        self.assertGreaterEqual(end,60);self.assertLessEqual(end,240)
        prefix=self.provider.source['text'][:end]
        self.assertEqual(response.headers['x-presentation-next-offset'],str(end))
        self.assertEqual(response.headers['x-presentation-text-sha256'],hashlib.sha256(prefix.encode()).hexdigest())
        self.assertEqual(response.headers['x-presentation-prefetch'],'true')
        spoken=self.speech.calls[0][2]
        self.assertIn(prefix.encode(),spoken)
        self.assertNotIn(self.provider.source['text'].encode(),spoken)
        self.assertEqual(self.audio().content,response.content)
        self.assertEqual(len(self.speech.calls),1,'Exact prefix replay reads its retained synthesis')

    def test_private_enrollment_and_actual_selected_audio_reuse_after_restart(self):
        self.assertEqual(self.output.stat().st_mode & 0o777,0o600)
        self.assertNotIn(self.device['authorization'],json.dumps(self.receipt))
        self.assertNotIn(self.device['authorization'],self.record.read_text())
        response=self.client.get('/api/interaction',headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['csrf'],self.device['csrf'])
        first=self.audio();self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.content,self.speech.data)
        self.client.close();self.client=self.client_for()
        self.assertEqual(self.audio().content,first.content)
        self.assertEqual(len(self.speech.calls),1,'A reconnect does not repeat synthesis or native work')

    def test_administrative_and_approval_routes_denied_even_with_full_session_cookie(self):
        login=self.client.post('/api/session',json={'init_data':'100'},headers={'origin':self.config['origin']})
        full=login.json()['session_token']
        headers={**self.headers,'cookie':'telecodex_dashboard='+full}
        for path in ('/api/state','/api/traffic','/api/alerts','/api/stop','/api/interaction/requests/'+'b'*32):
            method='post' if path.endswith('/stop') or '/requests/' in path else 'get'
            response=getattr(self.client,method)(path,headers=headers)
            self.assertEqual(response.status_code,403,(path,response.text))
        self.assertEqual(self.client.post('/api/session',json={'init_data':'100'},headers=headers).status_code,403)
        forged={**headers,'authorization':'Companion '+full}
        self.assertEqual(self.client.get('/api/interaction',headers=forged).status_code,401)
        malformed={**headers,'authorization':'Companion invalid'}
        self.assertEqual(self.client.get('/api/interaction',headers=malformed).status_code,401)
        duplicate=[*self.headers.items(),('authorization','Bearer '+full)]
        self.assertEqual(self.client.get('/api/interaction',headers=duplicate).status_code,401)
        self.assertEqual(len(self.speech.calls),0)

    def test_profile_is_receiver_selected_presentation_without_permission_expansion(self):
        response=self.client.get('/api/interaction?presentation_profile=explorer',headers={**self.headers,'x-presentation-profile':'explorer'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['presentation_profile'],'simple')
        selected=self.root/'explorer.json'
        self.grants.enroll('Explorer',selected,3600,profile='explorer')
        device=read_json(selected)
        headers={**self.headers,'authorization':device['authorization'],'x-dashboard-csrf':device['csrf']}
        self.assertEqual(self.client.get('/api/interaction',headers=headers).json()['presentation_profile'],'explorer')
        self.assertEqual(self.client.get('/api/state',headers=headers).status_code,403)
        self.assertEqual(self.client.post('/api/stop',json={},headers=headers).status_code,403)
        self.assertEqual(self.client.post('/api/interaction/requests/'+('a'*32),json={},headers=headers).status_code,403)
        before=read_json(self.record)
        before.pop('presentation_profile',None);write_json(self.record,before)
        self.assertEqual(self.client.get('/api/interaction',headers=self.headers).json()['presentation_profile'],'simple','old grants retain the configured simple default')
        with self.assertRaises(ValueError):self.grants.enroll('Invalid',self.root/'invalid-profile.json',3600,profile='owner')

    def test_standalone_shell_has_no_telegram_runtime_dependency(self):
        standalone=self.client.get('/?view=conversation&client=standalone')
        self.assertEqual(standalone.status_code,200)
        self.assertNotIn('https://telegram.org/js/telegram-web-app.js',standalone.text)
        self.assertIn('assets/app.js',standalone.text)
        self.assertIn('https://telegram.org/js/telegram-web-app.js',self.client.get('/').text)

    def test_conversation_grant_reads_only_its_existing_input_trace_routes(self):
        from dashboard.companion import permitted
        self.provider.conversation_input_trace=lambda ident:{'id':ident,'read_only':True}
        ident=str(uuid.uuid4())
        path='/api/interaction/inputs/'+ident+'/trace'
        self.assertEqual(self.client.get(path,headers=self.headers).json(),{'id':ident,'read_only':True})
        for route in (path,path+'/original',path+'/'+str(uuid.uuid4())):
            self.assertTrue(permitted('GET',route))
            self.assertFalse(permitted('POST',route))
        self.provider.conversation_telegram_inputs=lambda before,direction: {'items':[], 'read_only':True}
        for route in ('/api/interaction/telegram-inputs','/api/interaction/inputs/telegram:123/trace'):
            self.assertEqual(self.client.get(route,headers=self.headers).status_code,200)
            for method in ('POST','PUT','DELETE'):
                self.assertFalse(permitted(method,route))
        for route in ('/api/stop','/api/state'):
            self.assertEqual(self.client.get(route,headers=self.headers).status_code,403)

    def test_original_files_are_scoped_to_the_conversation_grant(self):
        from dashboard.companion import permitted
        path='/api/interaction/inputs/'+str(uuid.uuid4())+'/files/0'
        self.assertTrue(permitted('POST','/api/interaction/files'))
        self.assertTrue(permitted('GET',path))
        self.assertFalse(permitted('POST',path))
        self.assertFalse(permitted('GET',path.replace('/files/0','/files/8')))
        self.assertFalse(permitted('POST','/api/interaction/files','monitor_readonly'))
        self.assertFalse(permitted('GET',path,'monitor_readonly'))

    def test_monitor_grant_is_read_only_and_never_inherits_ambient_owner(self):
        from dashboard.companion import permitted
        output=self.root/'monitor.json'
        receipt=self.grants.enroll('Selected monitor',output,3600,scope='monitor_readonly')
        credential=read_json(output)
        self.assertEqual(receipt['scope'],'monitor_readonly')
        self.assertEqual(credential['scope'],'monitor_readonly')
        login=self.client.post('/api/session',json={'init_data':'100'},headers={'origin':self.config['origin']})
        headers={'origin':self.config['origin'],'authorization':credential['authorization'],
                 'cookie':'telecodex_dashboard='+login.json()['session_token']}
        self.assertEqual(self.client.get('/api/interaction',headers=headers).status_code,200)
        self.provider.conversation_inputs=lambda before,direction:{'items':[]}
        response=self.client.get('/api/interaction/inputs',headers=headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['viewer'],{'label':'Selected monitor','expires':credential['expires']})
        self.assertEqual(self.client.get('/api/interaction/inputs',headers=self.headers).json()['viewer'],
                         {'label':'Selected fixture button','expires':self.device['expires']})
        self.provider.conversation_telegram_inputs=lambda before,direction:{'items':[],'read_only':True}
        response=self.client.get('/api/interaction/telegram-inputs',headers=headers)
        self.assertEqual(response.status_code,200,response.text)
        self.provider.conversation_input_trace=lambda ident:{'id':ident,'read_only':True}
        path='/api/interaction/inputs/telegram:123/trace'
        self.assertEqual(self.client.get(path,headers=headers).status_code,200)
        allowed=['/api/interaction','/api/interaction/inputs','/api/interaction/part',
                 '/api/interaction/telegram-inputs',path,path+'/original',
                 '/api/interaction/inputs/'+'a'*36+'/trace/'+'b'*36]
        for selected in allowed:
            self.assertTrue(permitted('GET',selected,'monitor_readonly'),selected)
            for method in ('POST','PUT','DELETE'):
                self.assertFalse(permitted(method,selected,'monitor_readonly'))
        for selected in ('/api/state','/api/stop','/api/resume','/api/traffic','/api/alerts',
                         '/api/interaction/requests','/api/session','/api/interaction/audio',
                         '/api/interaction/voice','/api/interaction/visual','/api/interaction/inputs',
                         '/api/interaction/inputs/'+'a'*36+'/route'):
            if selected!='/api/interaction/inputs':
                self.assertEqual(self.client.get(selected,headers=headers).status_code,403,selected)
            self.assertEqual(self.client.post(selected,json={},headers=headers).status_code,403,selected)
        # Both clients observe the same retained human originals without writes.
        self.assertEqual(self.client.get(path,headers=self.headers).status_code,200)
        self.grants.revoke(receipt['grant_id'])
        self.assertEqual(self.client.get(path,headers=headers).status_code,401)
        self.assertEqual(len(self.speech.calls),0)

    def test_goal_review_is_readonly_for_device_and_monitor(self):
        ident='11111111-1111-4111-8111-111111111111'
        for path in ('/api/interaction/goals','/api/interaction/goals/'+ident):
            response=self.client.get(path,headers=self.headers)
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(self.client.post(path,json={},headers=self.headers).status_code,403)
            for scope in ('interaction_only','monitor_readonly'):
                from dashboard.companion import permitted
                self.assertTrue(permitted('GET',path,scope))
                for method in ('POST','PUT','DELETE'):
                    self.assertFalse(permitted(method,path,scope))
        self.assertEqual(self.client.get('/api/interaction/goals/not-a-uuid',headers=self.headers).status_code,403)
        self.grants.revoke(self.device['grant_id'])
        self.assertEqual(self.client.get('/api/interaction/goals',headers=self.headers).status_code,401)
        self.assertEqual(len(self.speech.calls),0)

    def test_origin_csrf_and_browser_chosen_speech_rejected_before_provider(self):
        self.assertEqual(self.client.post('/api/interaction/audio',json=self.body,headers={**self.headers,'origin':'https://other.test'}).status_code,403)
        self.assertEqual(self.client.post('/api/interaction/audio',json=self.body,headers={**self.headers,'x-dashboard-csrf':'wrong'}).status_code,403)
        self.assertEqual(self.client.post('/api/interaction/audio',json={**self.body,'text':'unowned words'},headers=self.headers).status_code,409)
        self.assertEqual(len(self.speech.calls),0)

    def test_explicit_speech_profile_has_no_default_fallback_and_reuses_capacity(self):
        from unittest.mock import AsyncMock
        from dashboard.speech import Speech
        selected={**self.body,'speech_provider':'openai'}
        self.assertEqual(self.client.post('/api/interaction/audio',json=selected,headers=self.headers).status_code,409)
        self.assertEqual(self.speech.calls,[])
        binding=self.root/'openai-route.json'
        binding.write_text(json.dumps({'schema':renderer.SCHEMA,'provider':'openai-realtime',
            'model':'gpt-realtime-2.1-mini','voice':'cedar','language':'es-AR',
            'credential_file':str(self.root/'unused-key'),'cache_root':str(self.root/'openai-cache')}))
        binding.chmod(0o600)
        self.config['speech_openai']={'binding':str(binding),'incremental_segments':True}
        self.client.close();self.client=self.client_for()
        engines=[]
        async def render(engine,source):
            engines.append(engine)
            return b'qualified synthetic audio',{'audio_sha256':'c'*64}
        with patch.object(Speech,'render',render):
            response=self.client.post('/api/interaction/audio',json=selected,headers=self.headers)
            self.assertEqual(response.status_code,200);self.assertEqual(response.headers['x-speech-provider'],'openai')
            self.assertEqual(engines[-1].binding,binding)
            self.assertEqual(self.client.post('/api/interaction/audio',json=self.body,headers=self.headers).status_code,200)
            self.assertIs(engines[0].capacity,engines[1].capacity)
            self.assertEqual(engines[1].binding,self.speech.binding)
            self.assertEqual(self.client.post('/api/interaction/audio',json={**selected,'speech_provider':'missing'},headers=self.headers).status_code,409)
            self.assertEqual(self.client.post('/api/interaction/audio',json={**selected,'stream':True},headers=self.headers).status_code,409)
        self.assertEqual(len(engines),2)
        self.config['voice_services_default']='openai'
        self.config['speech']['streaming_output']=True
        self.client.close();self.client=self.client_for()
        caps=self.client.get('/api/interaction',headers=self.headers).json()
        self.assertEqual(caps['voice_services_default'],'openai')
        self.assertFalse(caps['can_stream_speech'])
        self.assertTrue(caps['previous_can_stream_speech'])
        with patch.object(Speech,'render',render):
            default=self.client.post('/api/interaction/audio',json=self.body,headers=self.headers)
            self.assertEqual(default.status_code,200);self.assertEqual(default.headers['x-speech-provider'],'openai')
            self.assertEqual(engines[-1].binding,binding)
            previous=self.client.post('/api/interaction/audio',json={**self.body,'speech_provider':'current'},headers=self.headers)
            self.assertEqual(previous.status_code,200);self.assertEqual(engines[-1].binding,self.speech.binding)
        self.assertEqual(self.speech.calls,[])

    def test_conversation_reading_uses_own_saved_studio_voice(self):
        from dashboard.speech import Speech
        from dashboard.avatar_workshop import AvatarWorkshop
        binding=self.root/'openai-route.json'
        binding.write_text(json.dumps({'schema':renderer.SCHEMA,'provider':'openai-realtime',
            'model':'gpt-realtime-2.1-mini','voice':'cedar','language':'es-AR',
            'credential_file':str(self.root/'unused-key'),'cache_root':str(self.root/'openai-cache')}))
        binding.chmod(0o600)
        self.config['speech_openai']={'binding':str(binding),'incremental_segments':True}
        self.client.close();self.client=self.client_for()
        self.config['openai_live']={'api_key_file':str(self.root/'studio-key')}
        profile={'provider':'openai','api':'gpt-live','model':'gpt-live-1','voice':'willow'}
        store=AvatarWorkshop(self.config['state_dir']);ident=str(uuid.uuid4())
        store.voice_save(100,ident,profile,'Calm.',None,0);store.voice_select(100,ident,1,[profile])
        engines=[]
        self.provider.source['text']='A complete sentence with Unicode 🙂. '*50
        rendered_parts=[]
        async def render(engine,source):
            engines.append(engine);rendered_parts.append(source);return b'synthetic audio',{'audio_sha256':'c'*64}
        with patch('dashboard.voice_studio.configured_profiles',return_value=[profile]),patch.object(Speech,'render',render):
            response=self.client.post('/api/interaction/audio',json={**self.body,'speech_provider':'openai'},headers=self.headers)
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(engines[-1].receiving_route()['voice'],'willow')
            self.assertIn('Calm.',engines[-1].receiving_route()['instruction'])
            self.assertLessEqual(len(rendered_parts[-1]['text']),240)
            first_end=int(response.headers['x-presentation-next-offset'])
            second_end=int(response.headers['x-presentation-lookahead-offset'])
            self.assertGreater(second_end,first_end)
            self.assertLessEqual(second_end-first_end,240)
            self.assertEqual(self.provider.source['text'][:first_end],rendered_parts[-1]['text'])
            canonical={**self.provider.source,'offset':first_end,'text':self.provider.source['text'][first_end:]}
            self.assertEqual(second_end,speech_part(canonical,240)['next_offset'])
            self.assertEqual(self.client.post('/api/interaction/audio',json={**self.body,'speech_provider':'openai','text':'forged'},headers=self.headers).status_code,409)
        self.assertEqual(len(engines),1)

    def test_revocation_during_actual_synthesis_prevents_private_audio(self):
        self.speech.hold=True
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(self.audio)
            self.assertTrue(self.speech.entered.wait(timeout=4))
            self.assertTrue(self.grants.revoke(self.receipt['grant_id'])['revoked'])
            self.speech.release.set();result=pending.result(timeout=8)
        self.assertEqual(result.status_code,401)
        self.assertEqual(len(self.speech.calls),1)
        self.assertEqual(self.audio().status_code,401)
        self.assertTrue(self.grants.revoke(self.receipt['grant_id'])['already_absent'])

    def test_expiry_owner_and_receiving_profile_changes_fail_closed(self):
        original=read_json(self.record)
        write_json(self.record,{**original,'expires':int(time.time())-1})
        self.assertEqual(self.audio().status_code,401)
        write_json(self.record,original);self.provider.allowed=False
        self.assertEqual(self.audio().status_code,401)
        self.provider.allowed=True;self.provider.binding_bytes=b'changed owned entry or target profile'
        self.assertEqual(self.audio().status_code,401)
        self.assertEqual(len(self.speech.calls),0)

    def test_disabled_and_malformed_or_unsafe_grants_never_inherit_authority(self):
        self.client.close();self.config['companion']['enabled']=False;self.client=self.client_for()
        self.assertEqual(self.audio().status_code,401)
        self.client.close();self.config['companion']['enabled']=True;self.client=self.client_for()
        write_json(self.record,[])
        self.assertEqual(self.audio().status_code,401)
        self.record.chmod(0o644)
        self.assertEqual(self.audio().status_code,401)
        self.assertEqual(len(self.speech.calls),0)

    def test_enrollment_preserves_existing_device_credentials_and_requires_real_owner(self):
        before=self.output.read_bytes()
        with self.assertRaises(ValueError):self.grants.enroll('Another button',self.output,3600)
        self.assertEqual(self.output.read_bytes(),before)
        self.provider.allowed=False
        with self.assertRaises(ValueError):self.grants.enroll('Other',self.root/'other.json',3600)
        self.assertFalse((self.root/'other.json').exists())
        self.assertEqual(len(list((self.root/'grants').glob('*.json'))),1)

    def test_retry_after_interrupted_revocation_establishes_durable_absence(self):
        with patch('dashboard.companion.sync_directory',side_effect=OSError('synthetic barrier failure')):
            with self.assertRaises(OSError):self.grants.revoke(self.receipt['grant_id'])
        self.assertFalse(self.record.exists())
        with patch('dashboard.companion.sync_directory',wraps=renderer.sync_directory) as synced:
            self.assertTrue(self.grants.revoke(self.receipt['grant_id'])['already_absent'])
            synced.assert_called_once_with(self.root/'grants')

    def test_enrollment_establishes_new_directory_names_before_publication(self):
        config={**self.config,'companion':{'enabled':True,'grants_dir':str(self.root/'new-grants'/'nested')}}
        with patch('scripts.speech_render.sync_directory',wraps=renderer.sync_directory) as synced:
            grants=Grants(config,self.provider)
            output=self.root/'new-device'/'nested'/'device.json'
            receipt=grants.enroll('Durable fixture',output,3600)
        parents=[call.args[0] for call in synced.call_args_list]
        self.assertIn(self.root,parents)
        self.assertIn(self.root/'new-grants',parents)
        self.assertIn(self.root/'new-device',parents)
        self.assertEqual(read_json(output)['grant_id'],receipt['grant_id'])

    def test_owner_renewal_preserves_button_identity_and_permissions(self):
        original=read_json(self.record)
        expired={**original,'expires':int(time.time())-1}
        write_json(self.record,expired)
        before=self.output.read_bytes()
        self.assertEqual(self.client.get('/api/interaction',headers=self.headers).status_code,401)
        receipt=self.grants.renew(self.receipt['grant_id'],7*86400)
        self.assertEqual(self.output.read_bytes(),before,'Saved capture identity must not change')
        self.assertEqual(receipt['previous_expires'],expired['expires'])
        self.assertEqual(read_json(self.record),{**expired,'expires':receipt['expires']})
        self.assertEqual(self.client.get('/api/interaction',headers=self.headers).status_code,200)
        self.assertEqual(self.client.get('/api/state',headers=self.headers).status_code,403)
        self.assertEqual(len(self.speech.calls),0)

    def test_renewal_refuses_changed_authority_scope_owner_and_revoked_grants(self):
        original=read_json(self.record)
        for change in ({'authority':'changed'},{'scope':'monitor_readonly'},
                       {'human':101},{'csrf':'invalid'},{'expires':False}):
            write_json(self.record,{**original,**change})
            with self.assertRaises(ValueError):self.grants.renew(self.receipt['grant_id'],7*86400)
            self.assertEqual(read_json(self.record),{**original,**change})
        write_json(self.record,original)
        for seconds in (True,59,30*86400+1,60):
            with self.assertRaises(ValueError):self.grants.renew(self.receipt['grant_id'],seconds)
        self.provider.allowed=False
        with self.assertRaises(ValueError):self.grants.renew(self.receipt['grant_id'],7*86400)
        self.provider.allowed=True
        self.grants.revoke(self.receipt['grant_id'])
        with self.assertRaises(FileNotFoundError):self.grants.renew(self.receipt['grant_id'],7*86400)
        self.assertFalse(self.record.exists())

    def test_concurrent_renewal_and_revocation_cannot_resurrect_access(self):
        import threading
        entered=threading.Event();release=threading.Event()
        original=self.provider.presentation_list
        def held(*args):
            entered.set()
            if not release.wait(timeout=4):raise TimeoutError('release renewal fixture')
            return original(*args)
        self.provider.presentation_list=held
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(self.grants.renew,self.receipt['grant_id'],7*86400)
            try:
                self.assertTrue(entered.wait(timeout=4))
                with self.assertRaises(renderer.RenderError):
                    Grants(self.config,self.provider).revoke(self.receipt['grant_id'])
            finally:release.set()
            self.assertTrue(pending.result(timeout=5)['renewed'])
        self.grants.revoke(self.receipt['grant_id'])
        with self.assertRaises(FileNotFoundError):self.grants.renew(self.receipt['grant_id'],7*86400)
        self.assertEqual(self.client.get('/api/interaction',headers=self.headers).status_code,401)

    def test_profile_adoption_is_explicit_preserves_device_and_exact_retry(self):
        previous=authority(self.config,self.provider)
        before=read_json(self.record);credential=self.output.read_bytes()
        self.provider.binding_bytes=b'owner-selected-updated-transcription-route'
        self.assertEqual(self.client.get('/api/interaction',headers=self.headers).status_code,401)
        with self.assertRaises(ValueError):self.grants.renew(self.receipt['grant_id'],7*86400)
        with self.assertRaises(ValueError):self.grants.reauthorize(self.receipt['grant_id'],'0'*64)
        result=self.grants.reauthorize(self.receipt['grant_id'],previous)
        self.assertTrue(result['reauthorized']);self.assertEqual(result['expires'],before['expires'])
        after=read_json(self.record)
        self.assertEqual({k:v for k,v in before.items() if k!='authority'},
            {k:v for k,v in after.items() if k!='authority'})
        self.assertEqual(self.output.read_bytes(),credential)
        self.assertEqual(self.client.get('/api/interaction',headers=self.headers).status_code,200)
        self.assertTrue(self.grants.reauthorize(self.receipt['grant_id'],previous)['already_current'])
        self.assertEqual(self.client.post('/api/state',headers=self.headers).status_code,403)

    def test_adoption_refuses_expired_foreign_revoked_and_concurrent_revoke(self):
        previous=authority(self.config,self.provider);original=read_json(self.record)
        self.provider.binding_bytes=b'owner-selected-updated-profile'
        for change in ({'expires':int(time.time())-1},{'human':101},{'scope':'owner'},{'csrf':'invalid'}):
            write_json(self.record,{**original,**change})
            with self.assertRaises(ValueError):self.grants.reauthorize(self.receipt['grant_id'],previous)
        write_json(self.record,original)
        self.provider.allowed=False
        with self.assertRaises(ValueError):self.grants.reauthorize(self.receipt['grant_id'],previous)
        self.provider.allowed=True
        with renderer.lock(self.grants.root/'owner-mutation.lock'):
            with self.assertRaises(renderer.RenderError):self.grants.reauthorize(self.receipt['grant_id'],previous)
        self.grants.revoke(self.receipt['grant_id'])
        with self.assertRaises(FileNotFoundError):self.grants.reauthorize(self.receipt['grant_id'],previous)
        self.assertFalse(self.record.exists())


    def test_source_bound_streamed_audio_and_cache(self):
        self.speech.qwen_route();self.speech.content_type='text/event-stream';self.speech.data=self.speech.stream_data()
        self.config['speech']['streaming_output']=True
        self.client.close();self.client=self.client_for()
        result=self.client.post('/api/interaction/audio',json={**self.body,'stream':True},headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        frames=[json.loads(line) for line in result.text.splitlines()]
        self.assertEqual([f['type'] for f in frames],['audio','end'])
        self.assertEqual(result.headers['x-audio-encoding'],'mp3')
        self.assertEqual(result.headers['x-presentation-source'],self.body['source'])
        self.assertEqual(result.headers['x-presentation-offset'],'0')
        self.assertNotIn('synthetic-qwen-key',result.text)
        again=self.client.post('/api/interaction/audio',json={**self.body,'stream':True},headers=self.headers)
        self.assertEqual(again.text,result.text);self.assertEqual(len(self.speech.calls),1)
        denied=self.client.post('/api/interaction/audio',json={**self.body,'stream':True},headers={**self.headers,'x-dashboard-csrf':'wrong'})
        self.assertEqual(denied.status_code,403);self.assertEqual(len(self.speech.calls),1)

    def test_actual_http_stream_delivers_before_provider_completion(self):
        import socket
        import uvicorn
        self.speech.qwen_route();self.speech.content_type='text/event-stream';self.speech.data=self.speech.stream_data();self.speech.stream_hold=True
        self.config['speech']['streaming_output']=True
        app=create_app(self.config,self.provider,lambda raw,bot:int(raw))
        sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128)
        server=uvicorn.Server(uvicorn.Config(app,log_level='critical',lifespan='off'))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
        try:
            for _ in range(100):
                if server.started:break
                time.sleep(.01)
            self.assertTrue(server.started)
            with httpx.Client() as client,client.stream('POST',f'http://127.0.0.1:{sock.getsockname()[1]}/api/interaction/audio',
                    json={**self.body,'stream':True},headers=self.headers,timeout=5) as response:
                self.assertEqual(response.status_code,200)
                lines=response.iter_lines();first=json.loads(next(lines));self.assertEqual(first['type'],'audio')
                self.assertFalse(self.speech.release.is_set(),'First frame arrived while provider completion was held')
                self.speech.release.set();last=json.loads(next(lines));self.assertEqual(last['type'],'end')
            self.assertEqual(len(self.speech.calls),1)
        finally:
            self.speech.release.set();server.should_exit=True;thread.join(timeout=5);sock.close()
            self.assertFalse(thread.is_alive())

    def test_stream_revocation_or_source_change_stops_late_frames(self):
        self.config['speech']['streaming_output']=True
        self.client.close();self.client=self.client_for()
        original_grant=read_json(self.record)
        for failure in ('revoked','source_changed'):
            calls=[]
            async def changed(_speech,_source):
                yield {'type':'audio','sequence':0,'data':'eA==','sha256':hashlib.sha256(b'x').hexdigest()}
                if failure=='revoked':
                    self.grants.revoke(self.receipt['grant_id'])
                else:
                    self.provider.source['revision']='e'*64
                calls.append('late');yield {'type':'audio','sequence':1,'data':'eQ==','sha256':hashlib.sha256(b'y').hexdigest()}
            with patch('dashboard.speech.Speech.stream',changed):
                result=self.client.post('/api/interaction/audio',json={**self.body,'stream':True},headers=self.headers)
            frames=[json.loads(line) for line in result.text.splitlines()]
            self.assertEqual([f['type'] for f in frames],['audio','error'])
            if failure=='revoked':
                write_json(self.record,original_grant)
            self.assertEqual(len(self.speech.calls),0)


class CaptureRetention(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.provider = object.__new__(Provider)
        self.provider.receiver = {'db_path':str(self.root/'state.sqlite')}
        self.directory = self.root/'state.sqlite.voice'
        self.directory.mkdir(mode=0o700)
        self.ident = str(uuid.uuid4())
        self.path = self.directory/self.ident
        self.path.write_bytes(b'original owned clip');self.path.chmod(0o600)
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.value = {'id':self.ident,'text':'Committed words','phase':'preparing',
            'voice':{'audio_sha256':digest,'transcription':{'audio_sha256':digest,
                'capture_id':self.ident,'committed_at':'2026-10-18T00:00:00Z'}}}
    def tearDown(self):self.temp.cleanup()
    def test_confirmed_clip_removed_but_text_and_identity_survive(self):
        original = copy.deepcopy(self.value)
        self.assertTrue(self.provider.retire_voice_capture(self.value))
        self.assertFalse(self.path.exists())
        self.assertEqual(self.value,original)
        self.assertFalse(self.provider.retire_voice_capture(self.value))
    def test_pending_mismatched_empty_and_changed_audio_are_retained(self):
        for change in ('pending','identity','hash','text','commit'):
            value = copy.deepcopy(self.value)
            if change == 'pending':value['voice'].pop('transcription')
            if change == 'identity':value['voice']['transcription']['capture_id']=str(uuid.uuid4())
            if change == 'hash':value['voice']['transcription']['audio_sha256']='0'*64
            if change == 'text':value['text']=''
            if change == 'commit':value['voice']['transcription'].pop('committed_at')
            self.assertFalse(self.provider.retire_voice_capture(value),change)
            self.assertTrue(self.path.exists())
        self.path.write_bytes(b'changed bytes')
        self.assertFalse(self.provider.retire_voice_capture(self.value))
    def test_links_and_nonprivate_files_are_not_removed(self):
        self.path.chmod(0o644)
        self.assertFalse(self.provider.retire_voice_capture(self.value))
        outside = self.root/'other-recording';self.path.rename(outside)
        self.path.symlink_to(outside)
        self.assertFalse(self.provider.retire_voice_capture(self.value))
        self.assertTrue(outside.exists());self.assertTrue(self.path.is_symlink())
    def test_cleanup_error_does_not_change_committed_input(self):
        original = copy.deepcopy(self.value)
        with patch('dashboard.provider.os.open',side_effect=OSError('simulated')):
            self.assertFalse(self.provider.retire_voice_capture(self.value))
        self.assertEqual(self.value,original);self.assertTrue(self.path.exists())


class CaptureCapacity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.directory = self.root/'voice'
        self.directory.mkdir(mode=0o700)
    def tearDown(self):self.temp.cleanup()
    def retain(self, data=b'new recording', ident=None):
        ident = ident or str(uuid.uuid4())
        Provider.retain_voice_capture(self.directory,ident,data,hashlib.sha256(data).hexdigest())
        return self.directory/ident
    def protected(self, size):
        path=self.directory/str(uuid.uuid4())
        with path.open('wb') as stream:stream.truncate(size)
        path.chmod(0o600)
        return path
    def test_full_uncertain_storage_refuses_new_but_allows_exact_retry(self):
        data=b'exact retained original';path=self.retain(data)
        protected=self.protected(256*1024*1024-len(data))
        before={p.name:p.stat().st_size for p in self.directory.iterdir()}
        with self.assertRaises(ProviderUnavailable):self.retain()
        self.assertEqual(self.retain(data,path.name),path)
        self.assertEqual(path.read_bytes(),data)
        self.assertEqual({p.name:p.stat().st_size for p in self.directory.iterdir()},before)
        self.assertTrue(protected.exists())
    def test_parallel_admission_cannot_overrun_shared_budget(self):
        import concurrent.futures,threading
        self.protected(255*1024*1024)
        barrier=threading.Barrier(2)
        def submit():
            barrier.wait()
            try:self.retain(b'x'*(1024*1024));return True
            except ProviderUnavailable:return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:submit(),range(2)))
        self.assertEqual(results.count(True),1)
        self.assertLessEqual(sum(p.stat().st_size for p in self.directory.iterdir()),256*1024*1024)
    def test_exact_retry_completes_failed_publication_barrier(self):
        ident=str(uuid.uuid4());data=b'retained before failed sync'
        with patch('dashboard.provider.sync_directory',side_effect=OSError('injected')):
            with self.assertRaises(OSError):self.retain(data,ident)
        self.assertEqual((self.directory/ident).read_bytes(),data)
        with patch('dashboard.provider.sync_directory',wraps=renderer.sync_directory) as barrier:
            self.retain(data,ident)
            barrier.assert_called_once_with(self.directory)
    def test_many_small_uncertain_files_cannot_exhaust_metadata(self):
        for _ in range(128):self.protected(1)
        before={p.name for p in self.directory.iterdir()}
        with self.assertRaises(ProviderUnavailable):self.retain()
        self.assertEqual({p.name for p in self.directory.iterdir()}-{'admission.lock'},before)
    def test_unknown_unsafe_storage_and_changed_identity_are_preserved(self):
        data=b'first';path=self.retain(data)
        with self.assertRaises(ValueError):self.retain(b'changed',path.name)
        self.assertEqual(path.read_bytes(),data)
        external=self.root/'unrelated';external.write_bytes(b'preserve')
        link=self.directory/'unknown-link';link.symlink_to(external)
        with self.assertRaises(ProviderUnavailable):self.retain()
        self.assertTrue(link.is_symlink());self.assertEqual(external.read_bytes(),b'preserve')


if __name__=='__main__':
    unittest.main()
