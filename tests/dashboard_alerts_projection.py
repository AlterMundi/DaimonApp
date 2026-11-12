"""Real stopped-owner configuration/SQLite/JSON qualification; no network/model."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.alerts import Client, Receiver, Sender
from dashboard.private_state import read_json, write_json
from dashboard.provider import receiving_authority
from scripts import requalify_alerts_projection as operator


class Qualification(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        for name in ('alert-token', 'bot-token'):
            self.private(name, b'fictional-private-token')
        raw = f'''db_path = "{self.root}/native.sqlite"
[session_control]
human_id = 100
[telegram]
bot_token_file = "{self.root}/bot-token"
[interaction]
human_id = 100
chat_id = 100
topic_id = 1
'''.encode()
        self.before = self.private('before.toml', raw)
        self.current = self.private('current.toml', raw)
        self.config = self.private('dashboard.toml', f'''receiver_config = "{self.current}"
state_dir = "{self.root}/state"
bot_id = 123
[alerts]
base_url = "http://127.0.0.1:9999"
token_file = "{self.root}/alert-token"
receiving_scope = "human"
adapter_id = "telegram"
deliver = false
'''.encode())
        config = tomllib.loads(self.config.read_text())
        old = tomllib.loads(raw.decode())
        provider = SimpleNamespace(receiver=old, human=100, binding_bytes=receiving_authority(old))
        receiver = Receiver(config, provider, Client(config['alerts']), Sender(provider, config))
        self.journal = receiver.db_path
        with receiver.database() as db:
            db.execute('INSERT INTO attempts VALUES(?,?,?,?,?)', ('original', 'request', 'uncertain', None, 17))
            db.execute('INSERT INTO attempts VALUES(?,?,?,?,?)', ('delivered', 'request2', 'delivered', 'receipt', 18))
        self.old_binding = receiver.binding
        self.menu = self.journal.parent / 'menu-attention.json'
        self.record = {'binding': self.old_binding, 'original': {'text': 'Apps'},
                       'selected': {'text': 'Apps'}, 'pending': {'text': 'Pending Apps'}, 'observed_at': 17}
        write_json(self.menu, self.record)
        self.attempts = self.rows()
        self.current.write_bytes(raw + b'\n[interaction.private_projection]\ntask_id = "selected-task"\n')
        process = subprocess.Popen(['/bin/true'])
        process.wait(timeout=2)
        self.stopped_pid = process.pid

    def private(self, name, raw):
        path = self.root / name
        path.write_bytes(raw)
        path.chmod(0o600)
        return path

    def rows(self):
        with closing(sqlite3.connect(self.journal)) as db:
            return db.execute('SELECT * FROM attempts ORDER BY delivery_id').fetchall()

    def run_qualification(self, **overrides):
        options = dict(config_path=self.config, before_path=self.before,
            expected_before=hashlib.sha256(self.before.read_bytes()).hexdigest(),
            expected_current=hashlib.sha256(self.current.read_bytes()).hexdigest(), web_pid=self.stopped_pid)
        return operator.qualify(**{**options, **overrides})

    def test_real_constructor_accepts_exact_requalification_preserving_uncertain_delivery(self):
        result = self.run_qualification()
        self.assertTrue(result['binding_changed'])
        self.assertFalse(result['delivery_sent'])
        self.assertEqual(self.rows(), self.attempts)
        changed = read_json(self.menu)
        self.assertEqual({**changed, 'binding': self.old_binding}, self.record)
        config = tomllib.loads(self.config.read_text())
        current = tomllib.loads(self.current.read_text())
        provider = SimpleNamespace(receiver=current, human=100, binding_bytes=receiving_authority(current))
        receiver = Receiver(config, provider, Client(config['alerts']), Sender(provider, config))
        self.assertEqual(receiver.binding, changed['binding'])
        self.assertFalse(self.run_qualification()['binding_changed'])

    def test_menu_then_database_crash_recovers_without_touching_delivery(self):
        write = operator.write_json
        def interrupted(path, record):
            write(path, record)
            raise RuntimeError('Synthetic crash after durable menu write')
        with patch.object(operator, 'write_json', interrupted):
            with self.assertRaises(RuntimeError):
                self.run_qualification()
        with closing(sqlite3.connect(self.journal)) as db:
            self.assertEqual(db.execute('SELECT value FROM binding').fetchone()[0], self.old_binding)
        self.assertNotEqual(read_json(self.menu)['binding'], self.old_binding)
        self.assertTrue(self.run_qualification()['binding_changed'])
        self.assertEqual(self.rows(), self.attempts)

    def test_active_process_or_wrong_revision_cannot_change_binding(self):
        for kwargs in ({'web_pid': os.getpid()}, {'expected_before': 'not-current'}):
            with self.assertRaises(ValueError):
                self.run_qualification(**kwargs)
        self.assertEqual(read_json(self.menu), self.record)
        self.assertEqual(self.rows(), self.attempts)

    def test_other_actor_or_selector_change_is_refused(self):
        self.current.write_text(self.current.read_text().replace('human_id = 100', 'human_id = 101'))
        with self.assertRaises(ValueError):
            self.run_qualification()
        self.assertEqual(read_json(self.menu), self.record)

    def test_conflicting_menu_remains_untouched(self):
        write_json(self.menu, {**self.record, 'binding': 'unrelated'})
        with self.assertRaises(ValueError):
            self.run_qualification()
        self.assertEqual(read_json(self.menu)['binding'], 'unrelated')
        self.assertEqual(self.rows(), self.attempts)

    def test_symlink_or_public_preimage_is_refused(self):
        alias = self.root / 'alias.toml'
        alias.symlink_to(self.before)
        with self.assertRaises(OSError):
            self.run_qualification(before_path=alias)
        self.before.chmod(0o644)
        with self.assertRaises(ValueError):
            self.run_qualification()


if __name__ == '__main__':
    unittest.main()
