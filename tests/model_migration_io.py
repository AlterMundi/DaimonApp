"""Real SQLite CAS and preservation checks; synthetic metadata, no provider calls."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import model_migration as migration


class Metadata:
    def rpc(self, method, params):
        if method == 'account/read': return {'account': {'type': 'chatgpt', 'email': 'fixture@example.test'}}
        if method == 'account/rateLimits/read': return {'rateLimits': {'primary': {'usedPercent': 25}}}
        if method == 'config/read': return {'config': {'model_provider': 'openai', 'model_reasoning_effort': 'medium', 'model': 'gpt-6.2-sol'}}
        if method == 'model/list':
            return {'data': [{'model': 'gpt-6.2-sol', 'supportedReasoningEfforts': [{'reasoningEffort': 'medium'}]}], 'nextCursor': None}
        if method == 'thread/read':
            return {'thread': {'id': params['threadId'], 'modelProvider': 'openai' if params['threadId'] != 'foreign' else 'other'}}
        raise AssertionError(method)


class Cases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'native.sqlite3'
        self.config = self.root / 'config.toml'
        self.config.write_text('db_path = '+json.dumps(str(self.db))+'\n[codex]\nbinary="codex"\nshared_app_server=true\ndefault_cwd="/fixture"\ndefault_reasoning_effort="medium"\n')
        self.c = sqlite3.connect(self.db)
        self.addCleanup(self.c.close)
        self.c.execute('CREATE TABLE sessions(id INTEGER PRIMARY KEY,chat_id INTEGER,thread_id INTEGER,creator_user_id INTEGER,codex_thread_id TEXT,force_fresh_thread INTEGER,cwd TEXT,model TEXT,reasoning_effort TEXT,updated_at TEXT,busy INTEGER,history TEXT)')
        for i, thread, model in [(1,'one','gpt-6.1-sol'),(2,'foreign','gpt-6.1-sol'),(3,'pinned','gpt-6.1-sol'),(4,'visual','gpt-6.1-terra')]:
            self.c.execute('INSERT INTO sessions VALUES(?,1,?,1,?,0,"/fixture",?,"medium","revision",1,"original")',(i,i,thread,model))
        self.c.commit()
        self.plan = migration.prepare(self.config, Metadata(), ['pinned'])

    def apply(self, plan, metadata=None, excluded=('pinned',)):
        return migration.apply(self.config, plan, metadata or Metadata(), excluded)

    def test_exact_scope_busy_history_and_repeat(self):
        self.assertEqual([c['id'] for c in self.plan['changes']], [1])
        before = self.c.execute('SELECT id,busy,history,reasoning_effort FROM sessions').fetchall()
        self.assertEqual(self.apply(self.plan)['count'],1)
        self.assertEqual(self.c.execute('SELECT id,busy,history,reasoning_effort FROM sessions').fetchall(),before)
        self.assertEqual(self.apply(self.plan)['state'],'already-selected')
        self.assertEqual(self.c.execute('SELECT model FROM sessions WHERE id=2').fetchone()[0],'gpt-6.1-sol')

    def test_model_cas_preserves_newer_selection(self):
        self.c.execute('UPDATE sessions SET model="gpt-6.2-astra" WHERE id=1');self.c.commit()
        with self.assertRaisesRegex(ValueError,'concurrent_model'):self.apply(self.plan)

    def test_changed_native_binding_refuses(self):
        self.c.execute('UPDATE sessions SET codex_thread_id="replacement" WHERE id=1');self.c.commit()
        with self.assertRaisesRegex(ValueError,'binding_changed'):self.apply(self.plan)

    def test_changed_effort_refuses(self):
        self.c.execute('UPDATE sessions SET reasoning_effort="xhigh" WHERE id=1');self.c.commit()
        with self.assertRaisesRegex(ValueError,'binding_changed'):self.apply(self.plan)

    def test_config_cas(self):
        self.config.write_text(self.config.read_text()+'\n# later writer\n')
        with self.assertRaisesRegex(ValueError,'configuration_or_database_binding_changed'):self.apply(self.plan)

    def test_foreign_target_plan_refuses(self):
        self.plan['changes'][0]['target']='gpt-6.2-astra'
        with self.assertRaisesRegex(ValueError,'invalid_model_plan'):self.apply(self.plan)

    def test_missing_catalog_and_unsupported_effort_are_deferred(self):
        class Empty(Metadata):
            def rpc(self, method, params):
                if method=='model/list':return {'data':[]}
                return super().rpc(method, params)
        self.assertFalse(migration.prepare(self.config, Empty())['changes'])
        self.c.execute('UPDATE sessions SET reasoning_effort="none" WHERE id=1');self.c.commit()
        self.assertFalse(migration.prepare(self.config, Metadata(), ['pinned'])['changes'])

    def test_transaction_atomicity(self):
        self.c.execute('UPDATE sessions SET codex_thread_id="two" WHERE id=2');self.c.commit()
        plan=migration.prepare(self.config,Metadata(),['pinned'])
        self.c.execute('UPDATE sessions SET model="gpt-6-astra" WHERE id=2');self.c.commit()
        with self.assertRaises(ValueError):self.apply(plan)
        self.assertEqual(self.c.execute('SELECT model FROM sessions WHERE id=1').fetchone()[0],'gpt-6.1-sol')

    def test_apply_refuses_lost_advertisement_or_new_exclusion(self):
        class Empty(Metadata):
            def rpc(self, method, params):
                if method == 'model/list':
                    return {'data': []}
                return super().rpc(method, params)
        with self.assertRaisesRegex(ValueError, 'target_not_advertised'):
            self.apply(self.plan, Empty())
        with self.assertRaisesRegex(ValueError, 'explicitly_preserved_workload'):
            self.apply(self.plan, excluded=('one',))
        self.assertEqual(self.c.execute('SELECT model FROM sessions WHERE id=1').fetchone()[0], 'gpt-6.1-sol')

    def test_commit_checks_binding_again_after_live_rpc(self):
        config = self.config
        class ConcurrentWriter(Metadata):
            def rpc(self, method, params):
                if method == 'thread/read':
                    config.write_text(config.read_text() + '\n# later writer\n')
                return super().rpc(method, params)
        with self.assertRaisesRegex(ValueError, 'configuration_or_database_binding_changed'):
            self.apply(self.plan, ConcurrentWriter())
        self.assertEqual(self.c.execute('SELECT model FROM sessions WHERE id=1').fetchone()[0], 'gpt-6.1-sol')

    def test_replaced_database_at_same_path_is_refused(self):
        copy = self.root / 'replacement.sqlite3'
        with sqlite3.connect(copy) as replacement:
            self.c.backup(replacement)
        copy.replace(self.db)
        with self.assertRaisesRegex(ValueError, 'configuration_or_database_binding_changed'):
            self.apply(self.plan)

    def test_account_switch_during_qualification_is_refused(self):
        class Switch(Metadata):
            reads = 0
            def rpc(self, method, params):
                if method == 'account/read':
                    self.reads += 1
                    return {'account': {'type': 'chatgpt', 'email': f'fixture-{self.reads}@example.test'}}
                return super().rpc(method, params)
        with self.assertRaisesRegex(ValueError, 'native_account_changed'):
            self.apply(self.plan, Switch())

    def test_default_qualification_distinguishes_native_inheritance_and_override(self):
        result = migration.verify_default(self.config, Metadata(), 'gpt-6.2-sol')
        self.assertEqual((result['source'], result['loaded']), ('native-config', 'unobserved'))
        self.config.write_text(self.config.read_text() + 'default_model="gpt-6.1-sol"\n')
        with self.assertRaisesRegex(ValueError, 'effective_default_mismatch'):
            migration.verify_default(self.config, Metadata(), 'gpt-6.2-sol')
        self.config.write_text(self.config.read_text().replace('gpt-6.1-sol', 'gpt-6.2-sol'))
        self.assertEqual(migration.verify_default(self.config, Metadata(), 'gpt-6.2-sol')['source'], 'bridge-config')

    def test_standalone_config_cannot_borrow_shared_daemon(self):
        self.config.write_text(self.config.read_text().replace('shared_app_server=true', 'shared_app_server=false'))
        with self.assertRaisesRegex(ValueError, 'shared_native_receiver_required'):
            migration.verify_default(self.config, Metadata(), 'gpt-6.2-sol')

    def test_unset_existing_effort_does_not_borrow_bridge_creation_default(self):
        self.c.execute('UPDATE sessions SET reasoning_effort=NULL WHERE id=1')
        self.c.commit()
        class HighNativeEffort(Metadata):
            def rpc(self, method, params):
                result = super().rpc(method, params)
                if method == 'config/read':
                    result['config']['model_reasoning_effort'] = 'high'
                return result
        metadata = HighNativeEffort()
        plan = migration.prepare(self.config, metadata, ('pinned',))
        self.assertIn({'id': 1, 'reason': 'effort_not_supported'}, plan['deferred'])
        self.assertEqual(migration.verify_default(self.config, metadata, 'gpt-6.2-sol')['source'], 'native-config')

    def test_project_effective_default_must_match(self):
        class ProjectOverride(Metadata):
            def rpc(self, method, params):
                result = super().rpc(method, params)
                if method == 'config/read' and params.get('cwd') == '/fixture':
                    result['config']['model'] = 'different-project-model'
                return result
        with self.assertRaisesRegex(ValueError, 'effective_default_mismatch'):
            migration.verify_default(self.config, ProjectOverride(), 'gpt-6.2-sol')

    def test_ordinary_settings_revision_invalidates_old_plan(self):
        self.c.execute('UPDATE sessions SET updated_at="later" WHERE id=1')
        self.c.commit()
        with self.assertRaisesRegex(ValueError, 'binding_changed'):
            self.apply(self.plan)

    def test_applied_plan_cannot_reapply_after_a_later_reverse_migration(self):
        class BothModels(Metadata):
            def rpc(self, method, params):
                result = super().rpc(method, params)
                if method == 'model/list':
                    result['data'].append({**result['data'][0], 'model': 'gpt-6.1-sol'})
                return result
        metadata = BothModels()
        self.apply(self.plan, metadata)
        reverse = migration.prepare(self.config, metadata, mapping={'gpt-6.2-sol': 'gpt-6.1-sol'})
        self.assertEqual(self.apply(reverse, metadata)['state'], 'selected-for-next-turn')
        with self.assertRaisesRegex(ValueError, 'settings_revision'):
            self.apply(self.plan, metadata)

    def test_changed_proxy_config_cannot_qualify_with_old_attachment(self):
        with self.assertRaisesRegex(ValueError, 'configuration_changed_before_native_observation'):
            migration.prepare(self.config, Metadata(), initial_hash='0' * 64)
        with self.assertRaisesRegex(ValueError, 'configuration_changed_before_native_observation'):
            migration.apply(self.config, self.plan, Metadata(), initial_hash='0' * 64)
        with self.assertRaisesRegex(ValueError, 'configuration_changed_before_native_observation'):
            migration.verify_default(self.config, Metadata(), 'gpt-6.2-sol', initial_hash='0' * 64)

    def test_future_mapping_and_preexisting_plan_version(self):
        plan = migration.prepare(self.config, Metadata(), ('pinned',), {'gpt-6.1-terra': 'gpt-6.2-sol'})
        self.assertEqual([change['id'] for change in plan['changes']], [4])
        plan['schema'] = 'telecodex.owner-model-migration/v1'
        with self.assertRaisesRegex(ValueError, 'invalid_model_plan'):
            self.apply(plan)





class InheritedCases(unittest.TestCase):
    setUp = Cases.setUp
    apply = Cases.apply
    def inherited(self, model='gpt-6.1-sol'):
        class Own(Metadata):
            def rpc(self, method, params):
                response=super().rpc(method,params)
                if method=='thread/read':response['thread']['model']=model
                return response
        return Own()

    def test_null_is_not_implicitly_migrated(self):
        self.c.execute('UPDATE sessions SET model=NULL WHERE id=1');self.c.commit()
        self.assertFalse(migration.prepare(self.config,self.inherited(),['pinned'])['changes'])

    def test_actual_native_model_is_frozen_and_null_cas_applies(self):
        self.c.execute('UPDATE sessions SET model=NULL WHERE id=1');self.c.commit()
        plan=migration.prepare(self.config,self.inherited(),['pinned'],include_inherited=True)
        self.assertEqual(plan['inherited_source_models'],{'1':'gpt-6.1-sol'})
        self.assertIsNone(plan['changes'][0]['model'])
        result=self.apply(plan,self.inherited())
        self.assertEqual(result['state'],'selected-for-next-turn')
        self.assertEqual(self.c.execute('SELECT model,reasoning_effort,busy,history FROM sessions WHERE id=1').fetchone(),('gpt-6.2-sol','medium',1,'original'))

    def test_newer_native_choice_is_preserved(self):
        self.c.execute('UPDATE sessions SET model=NULL WHERE id=1');self.c.commit()
        plan=migration.prepare(self.config,self.inherited(),['pinned'],include_inherited=True)
        with self.assertRaisesRegex(ValueError,'inherited_native_selection_changed'):
            self.apply(plan,self.inherited('gpt-6-astra'))
        self.assertIsNone(self.c.execute('SELECT model FROM sessions WHERE id=1').fetchone()[0])

    def test_missing_native_source_does_not_assume_a_default(self):
        self.c.execute('UPDATE sessions SET model=NULL WHERE id=1');self.c.commit()
        plan=migration.prepare(self.config,Metadata(),['pinned'],include_inherited=True)
        self.assertFalse(plan['changes'])
        self.assertIn({'id':1,'reason':'inherited_native_model_unobserved'},plan['deferred'])



class RemainingSelections(unittest.TestCase):
    setUp = Cases.setUp
    apply = Cases.apply

    def test_unbound_explicit_selection_requires_opt_in(self):
        self.c.execute('UPDATE sessions SET codex_thread_id=NULL WHERE id=1');self.c.commit()
        self.assertFalse(migration.prepare(self.config,Metadata(),['pinned'])['changes'])
        plan=migration.prepare(self.config,Metadata(),['pinned'],include_unbound=True)
        self.assertEqual([row['id'] for row in plan['changes']],[1])
        self.assertEqual(self.apply(plan)['state'],'selected-for-next-turn')
        self.assertEqual(self.c.execute('SELECT codex_thread_id,busy,history FROM sessions WHERE id=1').fetchone(),(None,1,'original'))

    def test_new_binding_after_unbound_preparation_is_preserved(self):
        self.c.execute('UPDATE sessions SET codex_thread_id=NULL WHERE id=1');self.c.commit()
        plan=migration.prepare(self.config,Metadata(),['pinned'],include_unbound=True)
        self.c.execute('UPDATE sessions SET codex_thread_id="new-choice" WHERE id=1');self.c.commit()
        with self.assertRaisesRegex(ValueError,'binding_changed'):self.apply(plan)

    def test_unknown_unbound_inherited_model_still_refuses(self):
        self.c.execute('UPDATE sessions SET codex_thread_id=NULL,model=NULL WHERE id=1');self.c.commit()
        plan=migration.prepare(self.config,Metadata(),['pinned'],include_unbound=True,include_inherited=True)
        self.assertFalse(plan['changes'])
        self.assertIn({'id':1,'reason':'native_thread_not_bound'},plan['deferred'])

    def test_forced_fresh_preserves_exclusions_and_requires_saved_model(self):
        self.c.execute('UPDATE sessions SET force_fresh_thread=1 WHERE id IN (1,3)');self.c.commit()
        plan=migration.prepare(self.config,Metadata(),['pinned'],include_unbound=True)
        self.assertEqual([row['id'] for row in plan['changes']],[1])
        self.assertEqual(self.apply(plan)['count'],1)
        self.assertEqual(self.c.execute('SELECT force_fresh_thread FROM sessions WHERE id=1').fetchone()[0],1)

    def alias(self, **overrides):
        class Alias(Metadata):
            def rpc(self,method,params):
                response=super().rpc(method,params)
                if method=='config/read':
                    response['config']['model_providers']={'openai_http':{
                        'name':'OpenAI','wire_api':'responses','requires_openai_auth':True,
                        'supports_websockets':True,'base_url':None,**overrides}}
                if method=='thread/read' and params['threadId']=='one':
                    response['thread']['modelProvider']='openai_http'
                return response
        return Alias()

    def test_hosted_openai_alias_keeps_same_provider_and_account(self):
        plan=migration.prepare(self.config,self.alias(),['pinned'])
        self.assertEqual([row['id'] for row in plan['changes']],[1])
        self.assertEqual(self.apply(plan,self.alias())['count'],1)

    def test_alias_auth_route_headers_catalog_or_capabilities_are_not_assumed(self):
        for values in [dict(base_url='https://other.test/v1'),dict(auth={}),
                       dict(http_headers={'X-Route':'different'}),dict(model_catalog_url='https://other.test/models'),
                       dict(requires_openai_auth=False),dict(capabilities={})]:
            with self.subTest(values=values):
                self.assertFalse(migration.prepare(self.config,self.alias(**values),['pinned'])['changes'])
        with self.assertRaisesRegex(ValueError,'live_qualification_lost'):
            self.apply(migration.prepare(self.config,self.alias(),['pinned']),self.alias(base_url='https://later.test/v1'))

    def test_alias_api_key_account_requires_its_own_catalog(self):
        base=self.alias()
        class APIKey:
            def rpc(self,method,params):
                if method=='account/read':return {'account':{'type':'apiKey'}}
                return base.rpc(method,params)
        self.assertFalse(migration.prepare(self.config,APIKey(),['pinned'])['changes'])



class ReviewRegressions(unittest.TestCase):
    setUp = Cases.setUp
    apply = Cases.apply

    def test_newer_choice_in_prepare_qualification_is_not_ignored(self):
        self.c.execute('UPDATE sessions SET model=NULL WHERE id=1');self.c.commit()
        class Switch(Metadata):
            reads=0
            def rpc(self,method,params):
                response=super().rpc(method,params)
                if method=='thread/read' and params['threadId']=='one':
                    self.reads+=1;response['thread']['model']='gpt-6.1-sol' if self.reads==1 else 'gpt-6-astra'
                return response
        with self.assertRaisesRegex(ValueError,'inherited_native_selection_changed'):
            migration.prepare(self.config,Switch(),['pinned'],include_inherited=True)
        self.assertIsNone(self.c.execute('SELECT model FROM sessions WHERE id=1').fetchone()[0])

    def test_apply_uses_one_checked_native_model_observation(self):
        self.c.execute('UPDATE sessions SET model=NULL WHERE id=1');self.c.commit()
        old=InheritedCases.inherited(self)
        plan=migration.prepare(self.config,old,['pinned'],include_inherited=True)
        class Count(Metadata):
            reads=0
            def rpc(self,method,params):
                response=super().rpc(method,params)
                if method=='thread/read':
                    self.reads+=1;response['thread']['model']='gpt-6-astra'
                return response
        changed=Count()
        with self.assertRaisesRegex(ValueError,'inherited_native_selection_changed'):self.apply(plan,changed)
        self.assertEqual(changed.reads,1)

    def test_catalog_side_overrides_do_not_qualify_default_endpoint_alias(self):
        for override in [dict(openai_base_url='https://other.test/v1'),
                         dict(model_catalog_json='/fixture/catalog.json'),
                         dict(chatgpt_base_url='https://gov.chatgpt.com/backend-api/'),
                         {'model_providers':{'openai':{'model_catalog_url':'https://chatgpt.com/backend-api/codex/models'}}},
                         {'model_providers':{'openai':{'base_url':'https://other.test/v1'}}}]:
            with self.subTest(override=override):
                base=RemainingSelections.alias(self)
                class Override:
                    def rpc(self,method,params):
                        r=base.rpc(method,params)
                        if method=='config/read':
                            for k,v in override.items():
                                if k=='model_providers':r['config'].setdefault(k,{}).update(v)
                                else:r['config'][k]=v
                        return r
                self.assertFalse(migration.prepare(self.config,Override(),['pinned'])['changes'])



class FamilyObservation(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.config = Path(root.name) / 'config.toml'
        self.config.write_text('[codex]\nshared_app_server=true\ndefault_cwd="/fixture"\n')

    def test_exports_available_family_with_no_qualification_or_account_data(self):
        class Catalog(Metadata):
            def rpc(self, method, params):
                if method == 'model/list':
                    rows = [('gpt-6.2-sol', 'medium'), ('gpt-6.3-sol', 'medium'),
                            ('gpt-6.3-astra', 'medium'), ('gpt-6.4-sol', 'high'),
                            ('gpt-6.3-sol-2026-11-24', 'medium')]
                    return {'data': [{'model': model, 'supportedReasoningEfforts': [
                        {'reasoningEffort': effort}]} for model, effort in rows], 'nextCursor': None}
                return super().rpc(method, params)

        report = migration.observe_native_family(self.config, Catalog(), 'fixture')
        self.assertEqual(report['schema'], 'cluster.model-family-evidence/v1')
        workload, = report['workloads']
        self.assertEqual((workload['target'], workload['family'], workload['current_version']),
                         ('fixture', 'sol', [6, 2, 0]))
        self.assertEqual([item['model'] for item in workload['candidates']], ['gpt-6.3-sol', 'gpt-6.2-sol'])
        self.assertTrue(all(item['qualification'] is None for item in workload['candidates']))
        self.assertNotIn('fixture@example', json.dumps(report))
        self.assertNotIn('/fixture', json.dumps(report))

    def test_refuses_local_catalog_override(self):
        class LocalCatalog(Metadata):
            def rpc(self, method, params):
                result = super().rpc(method, params)
                if method == 'config/read':
                    result['config']['model_catalog_json'] = '/local/catalog.json'
                return result

        with self.assertRaisesRegex(ValueError, 'canonical_native'):
            migration.observe_native_family(self.config, LocalCatalog(), 'fixture')

    def test_refuses_change_in_the_selected_native_config(self):
        class ChangingConfig(Metadata):
            reads = 0

            def rpc(self, method, params):
                result = super().rpc(method, params)
                if method == 'config/read':
                    self.reads += 1
                    if self.reads == 2:
                        result['config']['model_reasoning_effort'] = 'low'
                return result

        with self.assertRaisesRegex(ValueError, 'native_config_changed'):
            migration.observe_native_family(self.config, ChangingConfig(), 'fixture')

    def test_requires_current_model_effort_to_be_advertised(self):
        class MissingEffort(Metadata):
            def rpc(self, method, params):
                result = super().rpc(method, params)
                if method == 'model/list':
                    result['data'][0]['supportedReasoningEfforts'] = [{'reasoningEffort': 'low'}]
                return result

        with self.assertRaisesRegex(ValueError, 'current_family_effort_unverified'):
            migration.observe_native_family(self.config, MissingEffort(), 'fixture')


class FamilyWriter(Metadata):
    revision = 'sha256:' + 'a' * 64

    def __init__(self, origin):
        self.origin = origin
        self.model = 'gpt-6.2-sol'
        self.candidate = 'gpt-6.3-sol'
        self.writes = []
        self.concurrent_edit = False

    def rpc(self, method, params):
        if method == 'model/list':
            models = ['gpt-6.2-sol', self.candidate]
            return {'data': [{'model': model, 'supportedReasoningEfforts': [
                {'reasoningEffort': 'medium'}]} for model in models]}
        if method == 'config/read':
            return {
                'config': {'model': self.model, 'model_provider': 'openai', 'model_reasoning_effort': 'medium'},
                'origins': {'model': {'name': {'type': 'user', 'file': str(self.origin)},
                                      'version': self.revision}},
            }
        if method == 'config/batchWrite':
            self.writes.append(params)
            if self.concurrent_edit:
                raise ValueError('config_version_conflict')
            self.model = params['edits'][0]['value']
            return {'status': 'ok'}
        return super().rpc(method, params)


class FamilySelection(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.home = Path(root.name)
        self.config = self.home / 'bridge.toml'
        self.config.write_text('[codex]\nshared_app_server=true\ndefault_cwd="/fixture"\n')
        self.native_file = self.home / '.codex/config.toml'
        self.native_file.parent.mkdir()
        self.native_file.write_text('model = "gpt-6.2-sol"\n')
        self.intent = self.home / 'family-intent.json'
        self.native = FamilyWriter(self.native_file)
        self.plan = migration.observe_native_family(self.config, self.native, 'fixture')
        workload, = self.plan['workloads']
        self.proof = workload['candidates'][0]['qualification'] = {
            'previous_model': workload['current'], 'previous_revision': workload['current_revision'],
            'observed_at': workload['candidates'][0]['observed_at'],
        }

    def apply(self):
        with patch.object(migration.Path, 'home', return_value=self.home):
            return migration.apply_native_family(self.config, self.native, 'fixture', self.plan, self.intent)

    def test_qualified_candidate_writes_only_model_with_native_version(self):
        result = self.apply()
        self.assertEqual(result['state'], 'selected-for-new-native-work')
        self.assertEqual(self.native.writes, [{
            'edits': [{'keyPath': 'model', 'value': 'gpt-6.3-sol', 'mergeStrategy': 'replace'}],
            'filePath': str(self.native_file), 'expectedVersion': FamilyWriter.revision,
            'reloadUserConfig': False,
        }])
        self.assertEqual(result['model'], json.loads(self.intent.read_text())['model'])
        self.assertEqual(result['new_turns'], 0)

    def test_unqualified_newer_candidate_does_not_fall_back(self):
        self.native.candidate = 'gpt-6.4-sol'
        with self.assertRaisesRegex(ValueError, 'qualified_native_family_successor_required'):
            self.apply()
        self.assertEqual(self.native.writes, [])

    def test_stale_qualification_refuses(self):
        self.proof['observed_at'] -= 86401
        with self.assertRaisesRegex(ValueError, 'qualified_native_family_successor_required'):
            self.apply()
        self.assertFalse(self.intent.exists())

    def test_project_or_other_config_file_refuses(self):
        self.native.origin = self.config
        with self.assertRaisesRegex(ValueError, 'versioned_native_user_model_required'):
            self.apply()
        self.assertEqual(self.native.writes, [])

    def test_failed_intent_directory_fsync_prevents_writer(self):
        with patch.object(migration.os, 'fsync', side_effect=[None, OSError('directory sync failed')]):
            with self.assertRaisesRegex(OSError, 'directory sync failed'):
                self.apply()
        self.assertEqual(self.native.writes, [])
        self.assertTrue(self.intent.exists())

    def test_version_conflict_retains_intent_and_cannot_repeat(self):
        self.native.concurrent_edit = True
        with self.assertRaisesRegex(ValueError, 'config_version_conflict'):
            self.apply()
        self.assertTrue(self.intent.exists())
        with self.assertRaises(FileExistsError):
            self.apply()
        self.assertEqual(len(self.native.writes), 1)


if __name__ == '__main__':
    unittest.main()
