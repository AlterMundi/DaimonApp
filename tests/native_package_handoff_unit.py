#!/usr/bin/env python3
"""Linux operator boundaries with fixture-owned processes, never a real daemon."""
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from native_package_handoff import adopt, digest, identity, package_identity, selected_package


class HandoffBoundaries(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.watcher = self.process()
        self.receiver = self.process()
        package = self.root / 'package'
        (package / 'bin').mkdir(parents=True)
        binary = package / 'bin/codex'
        binary.write_text('#!/bin/sh\nexit 1\n')
        binary.chmod(0o700)
        current = self.root / 'packages/app-server-daemon/current/bin'
        current.mkdir(parents=True)
        (current / 'codex').write_bytes(binary.read_bytes())
        self.plan = {'schema': 'daimon.native-package-handoff/v1', 'id': str(uuid.uuid4()),
                     'ready': True, 'uid': os.getuid(), 'package': str(package),
                     'files': {'bin/codex': digest(binary)}, 'codex_home': str(self.root),
                     'cgroup': Path('/proc/self/cgroup').read_text().strip(),
                     'supervisor': identity(self.watcher.pid), 'receiver': identity(self.receiver.pid)}
        self.receipt = self.root / 'receipt.json'

    def process(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'])
        def cleanup():
            if child.poll() is None:
                child.send_signal(signal.SIGCONT)
                child.terminate()
                child.wait(timeout=5)
        self.addCleanup(cleanup)
        return child

    def state(self, child):
        return Path(f'/proc/{child.pid}/stat').read_text().split(') ', 1)[1].split()[0]

    def test_changed_process_refuses_before_any_signal_or_command(self):
        self.plan['supervisor']['start_ticks'] = '0'
        with self.assertRaisesRegex(ValueError, 'generation changed'):
            adopt(self.plan, self.receipt)
        self.assertNotEqual(self.state(self.watcher), 'T')
        self.assertFalse(self.receipt.exists())

    def test_unready_or_wrong_cgroup_cannot_arm(self):
        self.plan['ready'] = False
        with self.assertRaisesRegex(ValueError, 'complete owner candidate'):
            adopt(self.plan, self.receipt)
        self.plan['ready'] = True
        self.plan['cgroup'] = 'a different receiving service'
        with self.assertRaisesRegex(ValueError, 'cgroup/owner differs'):
            adopt(self.plan, self.receipt)
        self.assertNotEqual(self.state(self.watcher), 'T')

    def test_uncertain_maintenance_does_not_restore_or_release_fresh_start_watcher(self):
        with self.assertRaisesRegex(RuntimeError, 'maintenance outcome unconfirmed'):
            adopt(self.plan, self.receipt)
        receipt = json.loads(self.receipt.read_text())
        self.assertEqual(receipt['phase'], 'unconfirmed')
        self.assertFalse(receipt['supervisor_resumed'])
        self.assertEqual([c['argv'] for c in receipt['commands']], [['maintenance']])
        self.assertEqual(self.state(self.watcher), 'T')
        self.assertNotEqual(self.state(self.receiver), 'T')
        with self.assertRaisesRegex(ValueError, 'retained operation'):
            adopt(self.plan, self.receipt)

    def test_same_cli_different_helper_refused_install_is_previous(self):
        candidate_root = Path(self.plan['package'])
        previous_root = self.root / 'packages/app-server-daemon/current'
        (candidate_root / 'bin/helper').write_text('candidate helper')
        (previous_root / 'bin/helper').write_text('previous helper')
        candidate = package_identity(candidate_root)
        previous = package_identity(previous_root)
        self.assertEqual(candidate['files']['bin/codex'], previous['files']['bin/codex'])
        # A refused installer leaves this exact previous release selected.
        self.assertEqual(selected_package(previous_root, candidate, previous_root.resolve(), previous),
                         (False, previous))
        shutil.copyfile(candidate_root / 'bin/helper', previous_root / 'bin/helper')
        (previous_root / 'codex').symlink_to('bin/codex')
        installed = {**candidate, 'links': {'codex': 'bin/codex'}}
        self.assertEqual(selected_package(previous_root, candidate, previous_root.resolve(), previous),
                         (True, installed))
        (previous_root / 'unexpected').write_text('unqualified file')
        with self.assertRaisesRegex(RuntimeError, 'selected package uncertain'):
            selected_package(previous_root, candidate, previous_root.resolve(), previous)

    def test_candidate_map_must_cover_complete_tree(self):
        (Path(self.plan['package']) / 'bin/helper').write_text('unlisted helper')
        with self.assertRaisesRegex(ValueError, 'complete package differs'):
            adopt(self.plan, self.receipt)
        self.assertFalse(self.receipt.exists())

    def test_terminal_deferral_releases_only_exact_watcher(self):
        binary = Path(self.plan['package']) / 'bin/codex'
        binary.write_text('#!/bin/sh\nprintf \'{"pid":' + str(self.receiver.pid)
                          + ',"outcome":"deferred"}\\n\'\n')
        self.plan['files']['bin/codex'] = digest(binary)
        result = adopt(self.plan, self.receipt)
        self.assertEqual(result['phase'], 'deferred')
        self.assertTrue(result['supervisor_resumed'])
        self.assertEqual([c['argv'] for c in result['commands']], [['maintenance']])
        self.assertIsNone(self.receiver.poll())


if __name__ == '__main__':
    unittest.main()
