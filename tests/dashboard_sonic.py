#!/usr/bin/env python3
"""Actual private observer cache, SQLite ownership and HTTP sonic-state reads."""
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
import json
import sqlite3
import sys
import tempfile
import time
import unittest
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from dashboard.app import create_app
from dashboard.provider import Provider
from dashboard.companion import Grants,permitted
from dashboard.home_auth import HomeAuth
from dashboard.session_view import read
from dashboard.sonic import descriptor,DEFAULT
from scripts.activity_indicator import atomic_json,inventory_source,readonly


class SonicStateIO(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.db=self.root/'state.sqlite'
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript('''CREATE TABLE users(tg_user_id INTEGER,allowed INTEGER);
                INSERT INTO users VALUES(100,1),(101,1);
                CREATE TABLE sessions(id INTEGER,chat_id INTEGER,thread_id INTEGER,creator_user_id INTEGER,codex_thread_id TEXT,force_fresh_thread INTEGER,session_title TEXT);
                INSERT INTO sessions VALUES(1,100,1,100,'entry',0,'Entry'),(2,100,7,100,'worker',0,'Worker'),(3,100,8,101,'foreign',0,'Private foreign title');
                CREATE TABLE turns(session_id INTEGER,from_user_id INTEGER,started_at TEXT);
                CREATE TABLE bot_state(key TEXT,value TEXT);''')
        self.receiver=self.root/'receiver.toml'
        self.receiver.write_text(f'''db_path={json.dumps(str(self.db))}
[codex]
binary="MUST-NOT-START-A-NATIVE-PROCESS"
[session_control]
human_id=100
socket_path={json.dumps(str(self.root/'no-socket'))}
[interaction]
human_id=100
chat_id=100
topic_id=1
[[interaction.targets]]
name="Alpha"
topic_id=7
[[interaction.targets]]
name="Selected but not owned"
topic_id=8
''')
        self.state=self.root/'activity';self.state.mkdir(mode=0o700)
        db=readonly(self.db)
        self.observation={'schema':'telecodex.topic-observations/v1','source':inventory_source(db),
            'connected':True,'observations':{
                '100:1':{'native':'entry','human':100,'execution':'idle','goal_state':'absent','waiting_for_human':False,'observed_at':time.time()},
                '100:7':{'native':'worker','human':100,'work_started_at':time.time()-125,'execution':'working','goal_state':'blocked','waiting_for_human':True,'observed_at':time.time()},
                '100:8':{'native':'foreign','human':101,'execution':'working','goal_state':'active','waiting_for_human':True,'observed_at':time.time()}}}
        db.close();self.save()
        self.config={'receiver_config':str(self.receiver),'state_dir':str(self.root/'dashboard'),
            'origin':'https://example.test','bot_id':123,'activity_state_dir':str(self.state),
            'companion':{'enabled':True,'grants_dir':str(self.root/'grants')}}
        self.provider=Provider(self.config)
        # Registry selection is owned by the receiving control service. These
        # cache/HTTP cases isolate that read; conversation_cold_entry_http_io
        # covers the actual registry rather than duplicating its SQL here.
        self.destinations=[];self.entry_latest=None
        self.choices=[{'selector':'t7','label':'Alpha'},{'selector':'t8','label':'Selected but not owned'}]
        self.registry=patch.object(self.provider,'presentation',side_effect=self.presentation)
        self.registry.start()
        self.client=TestClient(create_app(self.config,self.provider,lambda raw,bot:int(raw)),base_url=self.config['origin'])
        login=self.client.post('/api/session',json={'init_data':'100'},headers={'origin':self.config['origin']})
        self.owner={'authorization':'Bearer '+login.json()['session_token']}
    def save(self):atomic_json(self.state/'topics.json',self.observation)
    def presentation(self,command):
        if command=='presentation list 0 0':return {'binding':'a'*64,'items':[]}
        if command=='input workspace':return {'schema':'daimon.session-destinations/v1','items':self.destinations,'entry_latest_reply':self.entry_latest}
        self.assertEqual(command,f'input list {2**63-1} after')
        return {'routing_choices':self.choices}
    def tearDown(self):self.client.close();self.provider.close();self.registry.stop();self.temp.cleanup()
    def sources(self):
        response=self.client.get('/api/interaction/sonic',headers=self.owner)
        self.assertEqual(response.status_code,200,response.text)
        return {s['id']:s for s in response.json()['sources']}
    def test_selected_history_is_owned_and_requires_the_workspace_grant(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('ALTER TABLE sessions ADD COLUMN busy INTEGER DEFAULT 0')
            db.execute('ALTER TABLE sessions ADD COLUMN updated_at TEXT');db.commit()
        native=self.root/'native';sessions=native/'sessions';sessions.mkdir(parents=True)
        self.provider.native_home=native
        history=sessions/'worker.jsonl'
        history.write_text(json.dumps({'type':'session_meta','payload':{'id':'worker'}})+'\n'+
            json.dumps({'type':'response_item','payload':{'type':'message','role':'assistant',
                'content':[{'type':'output_text','text':'Retained worker result'}]}})+'\n')
        with closing(sqlite3.connect(native/'state_5.sqlite')) as db:
            db.execute('CREATE TABLE threads(id TEXT,rollout_path TEXT,archived INTEGER)')
            db.execute('INSERT INTO threads VALUES(?,?,0)',('worker',str(history)));db.commit()
        workspace=self.client.get('/api/interaction/sessions',headers=self.owner).json()
        worker=next(row for row in workspace['sessions'] if row['title']=='Worker')
        url='/api/interaction/sessions/'+worker['id']
        response=self.client.get(url,headers=self.owner)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['items'][0]['text'],'Retained worker result')
        self.assertIsNone(self.provider.native,'Reading a selected history must not open native processes')
        self.assertEqual(self.client.get('/api/interaction/sessions/'+'f'*24,headers=self.owner).status_code,409)
        grants=Grants(self.config,self.provider);output=self.root/'history-device.json'
        enrolled=grants.enroll('History device',output,3600)
        device=json.loads(output.read_text());headers={'authorization':device['authorization']}
        self.assertEqual(self.client.get(url,headers=headers).status_code,403)
        grants.workspace(enrolled['grant_id'],True)
        self.assertEqual(self.client.get(url,headers=headers).status_code,200)
        grants.workspace(enrolled['grant_id'],False)
        self.assertEqual(self.client.get(url,headers=headers).status_code,403)
        history.write_text(json.dumps({'type':'session_meta','payload':{'id':'foreign'}})+'\n')
        self.assertEqual(self.client.get(url,headers=self.owner).status_code,409)
        history.unlink();history.symlink_to(self.root/'outside.jsonl')
        history.resolve().write_text(json.dumps({'type':'session_meta','payload':{'id':'worker'}})+'\n')
        self.assertEqual(self.client.get(url,headers=self.owner).status_code,409)

    def test_workspace_grant_is_explicit_and_revocation_blocks_new_pin_text_and_voice(self):
        import uuid
        grants=Grants(self.config,self.provider);output=self.root/'workspace-device.json'
        enrolled=grants.enroll('Workspace device',output,3600)
        device=json.loads(output.read_text());headers={'authorization':device['authorization'],'origin':self.config['origin'],'x-dashboard-csrf':device['csrf']}
        self.assertEqual(self.client.get('/api/interaction/sessions',headers=headers).status_code,403)
        grants.workspace(enrolled['grant_id'],True)
        self.assertEqual(self.client.get('/api/interaction/sessions',headers=headers).status_code,200)
        grants.workspace(enrolled['grant_id'],False)
        self.assertEqual(self.client.get('/api/interaction/sessions',headers=headers).status_code,403)
        reply={'source':'session:2','revision':'b'*64}
        body={'id':str(uuid.uuid4()),'binding':'a'*64,'text':'Frozen original','reply':reply}
        self.assertEqual(self.client.post('/api/interaction/inputs',json=body,headers=headers).status_code,403)
        voice={**headers,'content-type':'audio/wav','x-input-id':str(uuid.uuid4()),'x-input-binding':'a'*64,'x-audio-sha256':'c'*64,'x-reply-source':reply['source'],'x-reply-revision':reply['revision']}
        self.assertEqual(self.client.post('/api/interaction/voice',content=b'RIFF',headers=voice).status_code,403)
        self.assertFalse(permitted('GET','/api/interaction/sessions','monitor_readonly',workspace_access=True))
        self.assertFalse(permitted('POST','/api/stop','interaction_only',workspace_access=True))

    def test_shared_home_workspace_permission_is_explicit_and_actor_bound(self):
        import time
        identity={'contract':'dm.home-session/v1','origin':self.config['origin'],'expires':int(time.time())+300,'actor':{'kind':'human','ref':'human:telegram:100'}}
        self.config['shared_auth']={'enabled':True,'home_origin':self.config['origin']}
        with patch('dashboard.home_auth.identity_response',return_value=identity):
            for allowed,expected in ((False,403),(True,200)):
                self.config['shared_auth']['workspace_access']=allowed
                with TestClient(create_app(self.config,self.provider,lambda raw,bot:int(raw)),base_url=self.config['origin']) as client:
                    client.cookies.set('__Host-home','h'*43)
                    self.assertEqual(client.get('/api/interaction/sessions').status_code,expected)
            identity['actor']['ref']='human:telegram:101'
            with TestClient(create_app(self.config,self.provider,lambda raw,bot:int(raw)),base_url=self.config['origin']) as client:
                client.cookies.set('__Host-home','h'*43)
                self.assertEqual(client.get('/api/interaction/sessions').status_code,403)

    def test_workspace_joins_only_native_owned_destination_references_and_validates_shape(self):
        self.destinations=[{'audio_key':'100:7','destination':{'source':'session:2','revision':'b'*64}},
            {'audio_key':'100:8','destination':{'source':'session:3','revision':'c'*64}}]
        response=self.client.get('/api/interaction/sessions',headers=self.owner)
        self.assertEqual(response.status_code,200,response.text)
        items={v['audio_key']:v for v in response.json()['sessions']}
        self.assertEqual(items['100:7']['destination'],self.destinations[0]['destination'])
        self.assertNotIn('100:8',items)
        self.destinations[0]['destination']['source']='native:1'
        self.assertEqual(self.client.get('/api/interaction/sessions',headers=self.owner).status_code,503)

    def test_entry_latest_reply_is_contextual_and_does_not_select_a_worker(self):
        self.entry_latest={'source':'native:42','revision':'a'*64,'context_only':True}
        value=self.client.get('/api/interaction/sessions',headers=self.owner)
        self.assertEqual(value.status_code,200,value.text)
        entry=next(row for row in value.json()['sessions'] if row['is_entry'])
        self.assertEqual(entry['latest_reply'],self.entry_latest);self.assertIsNone(entry['destination'])
        self.entry_latest={'source':'session:2','revision':'a'*64}
        self.assertEqual(self.client.get('/api/interaction/sessions',headers=self.owner).status_code,503)

    def test_workspace_lists_owned_unrouted_sessions_by_activity_not_observer_refresh(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO sessions VALUES(4,100,9,100,'unrouted',0,'Unrouted owned session')")
            db.execute("INSERT INTO turns VALUES(4,100,'2024-01-02T00:00:00Z')")
            db.execute("INSERT INTO turns VALUES(1,100,'2024-01-01T00:00:00Z')");db.commit()
        response=self.client.get('/api/interaction/sessions',headers=self.owner)
        self.assertEqual(response.status_code,200,response.text)
        rows=response.json()['sessions']
        self.assertEqual([r['title'] for r in rows],['Unrouted owned session','Entry','Worker'])
        self.assertNotIn('foreign',json.dumps(rows).lower())
        self.assertFalse(rows[0]['fresh']);self.assertEqual(rows[0]['goal_state'],'unknown')
        self.assertTrue(rows[2]['human_action_pending']);self.assertEqual(rows[2]['goal_state'],'blocked')
        self.assertEqual(rows[2]['results_review'],'unknown')
        self.assertIsNone(self.provider.native,'Metadata must not open native processes')

    def test_live_owner_bound_goal_and_human_wait_are_distinct_from_foreign_unknown(self):
        items=self.sources()
        self.assertEqual(items['100:7']['goal_state'],'blocked')
        self.assertGreater(time.time()-items['100:7']['work_started_at'],124)
        self.assertIsNone(items['100:8']['work_started_at'])
        self.assertTrue(items['100:7']['waiting_for_human'])
        self.assertFalse(items['100:1']['waiting_for_human'])
        self.assertFalse(items['100:8']['fresh'])
        self.assertIsNone(items['100:8']['session'])
        self.assertNotIn('foreign',json.dumps(items))
        self.assertIsNone(self.provider.native,'A cached state read spawned native work')
    def test_stale_replaced_and_legacy_observation_never_invent_a_wait_or_goal(self):
        self.observation['observations']['100:7']['observed_at']=time.time()-30;self.save()
        item=self.sources()['100:7'];self.assertFalse(item['fresh']);self.assertEqual(item['goal_state'],'unknown');self.assertIsNone(item['waiting_for_human'])
        self.observation['observations']['100:7']['observed_at']=time.time();self.observation['source']='different database';self.save()
        self.assertFalse(self.sources()['100:7']['fresh'])
        db=readonly(self.db);self.observation['source']=inventory_source(db);db.close()
        self.observation['observations']['100:7'].pop('waiting_for_human');self.save()
        self.assertIsNone(self.sources()['100:7']['waiting_for_human'])
        with closing(sqlite3.connect(self.db)) as db:db.execute("UPDATE sessions SET codex_thread_id='renewed' WHERE thread_id=7");db.commit()
        item=self.sources()['100:7'];self.assertEqual(item['id'],'100:7');self.assertFalse(item['fresh'])
    def test_readonly_devices_can_inspect_but_never_control_through_state_endpoint(self):
        grants=Grants(self.config,self.provider);destination=self.root/'monitor.json'
        # The control-socket enrollment preflight is outside this read-only
        # SQLite/cache/HTTP case; grant validation and revocation remain real.
        with patch.object(self.provider,'presentation_list',return_value={'items':[]}):
            grants.enroll('Synthetic sonic monitor',destination,60,scope='monitor_readonly')
        header={'authorization':json.loads(destination.read_text())['authorization']}
        self.assertEqual(self.client.get('/api/interaction/sonic',headers=header).status_code,200)
        self.assertEqual(self.client.get('/api/interaction/sessions',headers=header).status_code,403)
        self.assertEqual(self.client.post('/api/interaction/sonic',headers=header,json={}).status_code,403)
        self.assertTrue(permitted('GET','/api/interaction/sonic'))
        self.assertFalse(permitted('POST','/api/interaction/sonic'))
        with closing(sqlite3.connect(self.db)) as db:db.execute('UPDATE users SET allowed=0 WHERE tg_user_id=100');db.commit()
        self.assertEqual(self.client.get('/api/interaction/sonic',headers=self.owner).status_code,401)
    def test_no_config_and_private_cache_refusal_are_truthful_without_native_fallback(self):
        self.config.pop('activity_state_dir')
        value=self.provider.sonic_activity();self.assertFalse(value['configured']);self.assertFalse(value['connected'])
        self.config['activity_state_dir']=str(self.state)
        (self.state/'topics.json').chmod(0o644)
        self.assertEqual(self.client.get('/api/interaction/sonic',headers=self.owner).status_code,503)
        self.assertIsNone(self.provider.native)

    def test_weekly_quota_reuses_bound_fresh_status_observer_without_native_calls(self):
        health={'source':self.observation['source'],'updated_at':time.time(),'connected':True,'weekly_available':42.5,'weekly_resets_at':time.time()+172800}
        path=self.state/'health.json';atomic_json(path,health)
        quota=self.provider.sonic_activity()['weekly_quota'];self.assertEqual(quota['available_percent'],42.5);self.assertEqual(quota['state'],'observed')
        for change in ({'source':'retired'},{'updated_at':time.time()-21},{'weekly_available':101},{'weekly_available':True},{'connected':False}):
            atomic_json(path,{**health,**change});self.assertEqual(self.provider.sonic_activity()['weekly_quota']['state'],'unavailable')
        path.chmod(0o644);self.assertEqual(self.provider.sonic_activity()['weekly_quota']['state'],'unavailable')
        self.assertIsNone(self.provider.native)

    def test_dynamic_membership_comes_from_canonical_registry_not_static_config(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("INSERT INTO sessions VALUES(4,100,9,100,'discovered',0,'Discovered')")
            db.commit()
        self.choices.append({'selector':'t9','label':'Live discovered label'})
        items=self.sources()
        self.assertIn('100:9',items)
        self.assertEqual(items['100:9']['label'],'Live discovered label')
        self.assertEqual(items['100:9']['session'],4)
        self.assertFalse(items['100:9']['fresh'])
        self.choices=[{'selector':'t9','label':'Renamed'}]
        self.assertEqual(set(self.sources()),{'100:1','100:9'})
        self.choices=[{'selector':'invalid','label':'Invalid'}]
        self.assertEqual(self.client.get('/api/interaction/sonic',headers=self.owner).status_code,503)


    def test_component_observations_are_current_and_not_inferred_from_working(self):
        item=self.sources()['100:7']
        self.assertIsNone(item['tools_running'])
        self.assertIsNone(item['error'])
        self.assertTrue(item['pending'])
        self.observation['observations']['100:7'].update(tools_running=True,error=False)
        self.save();item=self.sources()['100:7']
        self.assertTrue(item['tools_running']);self.assertFalse(item['error'])
        self.observation['observations']['100:7']['observed_at']=time.time()-30
        self.save();item=self.sources()['100:7']
        self.assertIsNone(item['tools_running']);self.assertIsNone(item['error'])


    def test_durable_pending_task_contributes_without_native_wait(self):
        self.observation['observations']['100:7']['waiting_for_human']=False;self.save()
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript("""CREATE TABLE human_interactions(kind TEXT,state TEXT,instance_id TEXT,native_thread TEXT,session_id INTEGER,requester INTEGER);
                CREATE TABLE app_instance_lock(key TEXT,instance_id TEXT,heartbeat_at TEXT);
                INSERT INTO human_interactions VALUES('task','pending','owner','worker',2,100);""")
        self.assertTrue(self.sources()['100:7']['pending'])
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE human_interactions SET state='completed'");db.commit()
        self.assertFalse(self.sources()['100:7']['pending'])


    def test_home_scope_restores_only_selected_session_and_rejects_other_input(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('ALTER TABLE sessions ADD COLUMN busy INTEGER DEFAULT 0')
            db.execute('ALTER TABLE sessions ADD COLUMN updated_at TEXT')
            db.execute("INSERT INTO sessions VALUES(4,100,9,100,'private',0,'Other owned private',0,NULL)")
            db.commit()
        native=self.root/'native';sessions=native/'sessions';sessions.mkdir(parents=True)
        self.provider.native_home=native
        history=sessions/'worker.jsonl'
        history.write_text(json.dumps({'type':'session_meta','payload':{'id':'worker'}})+'\n'+
            json.dumps({'type':'response_item','payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':'Selected current progress'}]}})+'\n')
        with closing(sqlite3.connect(native/'state_5.sqlite')) as db:
            db.execute('CREATE TABLE threads(id TEXT,rollout_path TEXT,archived INTEGER)')
            db.execute('INSERT INTO threads VALUES(?,?,0)',('worker',str(history)));db.commit()
        self.config['shared_auth']={'enabled':True,'home_origin':self.config['origin'],
            'workspace_topics':[7],'workspace_follow_topic':7}
        app=create_app(self.config,self.provider,lambda raw,bot:int(raw))
        client=TestClient(app,base_url=self.config['origin'])
        client.cookies.set('__Host-home','h'*43,path='/')
        identity={'contract':'dm.home-session/v1','origin':self.config['origin'],'expires':int(time.time())+3600,
            'actor':{'kind':'human','ref':'human:telegram:100'}}
        with patch('dashboard.home_auth.identity_response',return_value=identity),patch('dashboard.session_view.read',wraps=read) as reads:
            listing=client.get('/api/interaction/sessions')
            self.assertEqual(listing.status_code,200,listing.text)
            rows=listing.json()['sessions'];self.assertEqual([r['title'] for r in rows],['Worker'])
            ident=rows[0]['id'];self.assertEqual(listing.json()['preferred_session'],ident)
            selected=client.get('/api/interaction/sessions/'+ident)
            self.assertEqual(selected.status_code,200,selected.text)
            self.assertEqual(selected.json()['items'][0]['text'],'Selected current progress')
            other=self.provider.identity({'id':4,'chat_id':100,'thread_id':9,'codex_thread_id':'private'})
            self.assertEqual(client.get('/api/interaction/sessions/'+other).status_code,409)
            self.assertEqual(reads.call_count,1,'Other owned history must be refused before any file read')
            csrf=client.get('/api/interaction/access').json()['csrf']
            headers={'origin':self.config['origin'],'x-dashboard-csrf':csrf}
            reply={'source':'session:4','revision':'b'*64}
            with patch.object(self.provider,'conversation_input_submit') as text,patch.object(self.provider,'conversation_voice_submit') as voice:
                value={'id':str(uuid.uuid4()),'binding':'a'*64,'text':'Original','reply':reply}
                self.assertEqual(client.post('/api/interaction/inputs',json=value,headers=headers).status_code,403)
                headers.update({'x-reply-source':reply['source'],'x-reply-revision':reply['revision']})
                self.assertEqual(client.post('/api/interaction/voice',content=b'not submitted',headers=headers).status_code,403)
                text.assert_not_called();voice.assert_not_called()
            identity['actor']['ref']='human:telegram:101'
            self.assertEqual(client.get('/api/interaction/sessions/'+ident).status_code,403)
            self.assertEqual(reads.call_count,1,'Foreign actor must not open the selected history')
        self.assertIsNone(self.provider.native)
        client.close()

    def test_follow_requires_explicit_valid_scope(self):
        for values in [{'workspace_topics':[True]},{'workspace_topics':[7,7]},
                {'workspace_topics':[7],'workspace_follow_topic':9},
                {'workspace_topics':'7'},{'workspace_topics':[0]}]:
            with self.subTest(values=values),self.assertRaises(ValueError):
                HomeAuth({**self.config,'shared_auth':{'enabled':True,'home_origin':self.config['origin'],**values}},self.provider)

    def test_files_intersect_existing_canonical_audience_and_selected_session(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('ALTER TABLE sessions ADD COLUMN busy INTEGER DEFAULT 0')
            db.execute('ALTER TABLE sessions ADD COLUMN updated_at TEXT')
            db.execute('CREATE TABLE interaction_artifacts(id TEXT,source_session INTEGER,human_id INTEGER,native_thread TEXT)')
            db.executemany('INSERT INTO interaction_artifacts VALUES(?,?,?,?)',[
                ('selected',2,100,'worker'),('no-existing-audience',2,100,'worker'),('other',1,100,'entry')]);db.commit()
        ident=self.provider.identity({'id':2,'chat_id':100,'thread_id':7,'codex_thread_id':'worker'})
        with patch.object(self.provider,'artifacts',return_value={'items':[{'id':'selected','available':True},{'id':'other','available':True}]}) as canonical:
            self.assertEqual(self.provider.session_artifacts(ident,(7,)),[{'id':'selected','available':True}])
            self.assertEqual(canonical.call_count,1)



    def test_selected_history_omits_files_if_artifact_grant_is_revoked_during_read(self):
        grants=Grants(self.config,self.provider);output=self.root/'file-device.json'
        enrolled=grants.enroll('Selected files',output,3600,workspace_access=True,artifact_access=True)
        device=json.loads(output.read_text());headers={'authorization':device['authorization']}
        def files(*args,**kwargs):
            grants.artifacts(enrolled['grant_id'],False)
            return [{'id':'private-descriptor','name':'Must not leave the server','sha256':'a'*64}]
        with patch.object(self.provider,'session_view',return_value={'items':[]}),patch.object(self.provider,'session_artifacts',side_effect=files):
            response=self.client.get('/api/interaction/sessions/'+'a'*24,headers=headers)
            self.assertEqual(response.status_code,200,response.text)
            self.assertNotIn('artifacts',response.json())
            self.assertNotIn('private-descriptor',response.text)


class SonicVocabulary(unittest.TestCase):
    def test_confirmed_additive_sine_vocabulary_and_rejected_extra_texture(self):
        value=json.loads(descriptor({})['vocabulary_json'])
        self.assertEqual(value['fundamental_hz'],40.4)
        self.assertEqual(value['components'],dict(idle=1,active=2,tools=3,goal=4,pending=7,blocked=11))
        for field,value in [('wave','triangle'),('partials',[[1,1]]),('texture_hz',18),
                            ('pulse_mode','unrecognized'),('pulse_depth',0.6),('pulse_hz',18),('pulse_depth',float('nan')),
                            ('components',{'idle':1}),('schema','daimon.sonic-expression/v1')]:
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):
                descriptor({'sonic_vocabulary':{**DEFAULT,field:value}})



if __name__=='__main__':unittest.main()
