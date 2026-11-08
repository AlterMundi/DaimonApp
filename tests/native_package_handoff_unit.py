#!/usr/bin/env python3
"""Linux operator boundaries with fixture-owned processes, never a real daemon."""
import json
import os
from pathlib import Path
import signal
import select
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

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
        child = subprocess.Popen([sys.executable, '-c',
                                  'import time;print("ready",flush=True);time.sleep(60)'],
                                 stdout=subprocess.PIPE)
        def cleanup():
            if child.poll() is None:
                child.send_signal(signal.SIGCONT)
                child.terminate()
                child.wait(timeout=5)
        self.addCleanup(cleanup)
        self.addCleanup(child.stdout.close)
        # Capture identity only after exec: the pre-exec argv may briefly still
        # belong to the parent, correctly refused by the real generation fence.
        self.assertTrue(select.select([child.stdout], [], [], 5)[0], 'Fixture child did not become ready')
        self.assertEqual(child.stdout.readline(), b'ready\n')
        return child

    def state(self, child):
        return Path(f'/proc/{child.pid}/stat').read_text().split(') ', 1)[1].split()[0]

    def scoped_clock(self, remaining):
        self.clock = 1000.0
        self.plan['schema'] = 'daimon.native-package-handoff/v2'
        self.plan['lifecycle_deadline_unix'] = 1000.0 + remaining
        self.addCleanup(patch.stopall)
        patch('native_package_handoff.time.time', return_value=1000.0).start()
        patch('native_package_handoff.time.monotonic', side_effect=lambda: self.clock).start()

    def test_bounded_plan_cannot_silently_use_legacy_semantics(self):
        self.scoped_clock(240)
        self.plan['schema'] = 'daimon.native-package-handoff/v1'
        with self.assertRaisesRegex(ValueError, 'requires v2'):
            adopt(self.plan, self.receipt)
        self.plan['schema'] = 'daimon.native-package-handoff/v2'
        del self.plan['lifecycle_deadline_unix']
        with self.assertRaisesRegex(ValueError, 'absolute lifecycle deadline'):
            adopt(self.plan, self.receipt)
        for invalid in [None, True, '1240', float('nan'), float('inf')]:
            self.plan['lifecycle_deadline_unix'] = invalid
            with self.subTest(deadline=invalid), self.assertRaises(ValueError):
                adopt(self.plan, self.receipt)
        self.assertFalse(self.receipt.exists())
        self.assertNotEqual(self.state(self.watcher), 'T')

    def test_short_scoped_window_defers_before_native_request(self):
        self.scoped_clock(199)
        with patch('native_package_handoff.cli') as command:
            result = adopt(self.plan, self.receipt)
        command.assert_not_called()
        self.assertEqual(result['phase'], 'deferred_window_budget')
        self.assertTrue(result['supervisor_resumed'])
        self.assertIsNone(self.receiver.poll())

    def test_expired_window_refuses_before_watcher_hold(self):
        self.scoped_clock(-1)
        with self.assertRaisesRegex(ValueError, 'fresh bounded'):
            adopt(self.plan, self.receipt)
        self.assertFalse(self.receipt.exists())
        self.assertNotEqual(self.state(self.watcher), 'T')

    def prepare_python_package(self):
        # Real fixture processes make exit/executable/cgroup checks meaningful.
        binary = Path(self.plan['package']) / 'bin/codex'
        shutil.copyfile(sys.executable, binary)
        previous = self.root / 'packages/app-server-daemon/current/bin/codex'
        shutil.copyfile(sys.executable, previous)
        self.plan['files']['bin/codex'] = digest(binary)

    def test_long_maintenance_preserves_reserve_by_skipping_install(self):
        self.prepare_python_package()
        self.scoped_clock(201)
        calls = []
        def command(binary, args, env, timeout):
            calls.append((args[0], timeout))
            if args == ['maintenance']:
                self.clock += 138
                self.receiver.terminate()
                self.receiver.wait(timeout=5)
                return 0, {'pid': self.receiver.pid, 'outcome': 'handoffReady'}
            self.assertEqual(args, ['restart', '--if-stopped'])
            self.clock += 30
            replacement = self.process()
            return 0, {'pid': replacement.pid}
        with patch('native_package_handoff.cli', side_effect=command):
            result = adopt(self.plan, self.receipt)
        self.assertEqual(calls, [('maintenance', 138), ('restart', 45)])
        self.assertEqual(result['phase'], 'restored_previous')
        self.assertEqual(result['installer_skipped'], 'preserve_stopped_restore_reserve')
        self.assertTrue(result['supervisor_resumed'])
        self.assertLess(self.clock, self.plan['lifecycle_deadline_unix'])

    def test_installer_ack_loss_reads_selection_without_retry(self):
        self.prepare_python_package()
        self.scoped_clock(240)
        calls = []
        def command(binary, args, env, timeout):
            calls.append((args[0], timeout))
            if args == ['maintenance']:
                self.clock += 1
                self.receiver.terminate()
                self.receiver.wait(timeout=5)
                return 0, {'pid': self.receiver.pid, 'outcome': 'handoffReady'}
            if args[0] == 'update':
                selected = self.root / 'packages/app-server-daemon/current'
                (selected / 'codex').symlink_to('bin/codex')
                self.clock += timeout
                raise subprocess.TimeoutExpired(args, timeout)
            self.assertEqual(args, ['restart', '--if-stopped'])
            self.clock += 5
            replacement = self.process()
            return 0, {'pid': replacement.pid}
        with patch('native_package_handoff.cli', side_effect=command):
            result = adopt(self.plan, self.receipt)
        self.assertEqual(calls, [('maintenance', 138), ('update', 15), ('restart', 45)])
        self.assertEqual(result['phase'], 'restored_candidate')
        self.assertEqual(result['installer_acknowledgment'], 'unconfirmed')
        self.assertTrue(result['supervisor_resumed'])

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

    def test_stock_package_inventory_and_file_capacity(self):
        package = self.root / 'stock-package'
        package.mkdir()
        # Actual receiving stock0.167 packages contain44 regular files.
        for index in range(44):
            (package / str(index)).write_text('fixture')
        self.assertEqual(len(package_identity(package)['files']), 44)
        for index in range(44, 65):
            (package / str(index)).write_text('fixture')
        with self.assertRaisesRegex(ValueError, 'package file capacity'):
            package_identity(package)

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
