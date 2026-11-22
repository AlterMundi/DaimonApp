"""Real SQLite CAS and preservation checks; synthetic metadata, no provider calls."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

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


if __name__ == '__main__':
    unittest.main()
