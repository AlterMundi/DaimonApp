"""Pinned private-projection input and whole-command serialization; no publication."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    'private_bitacora_refresh', Path(__file__).resolve().parents[1] / 'scripts/bitacora_refresh.py')
refresh = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refresh)


class PinnedProjection(unittest.TestCase):
    def test_anonymous_input_survives_source_replacement_and_reaches_builder(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = b'{"observed_at":"original","documents":[]}'
            captured = []

            def build(snapshot, fd, digest, observed_at):
                self.assertEqual(os.fstat(fd).st_nlink, 0)
                (root / 'source-snapshot.json').write_bytes(b'{"observed_at":"later"}')
                actual = refresh.run(sys.executable, '-c',
                    'import pathlib,sys;print(pathlib.Path(sys.argv[1]).read_text())',
                    str(snapshot), pass_fds=(fd,))
                self.assertEqual(actual.strip().encode(), source)
                self.assertEqual(digest, hashlib.sha256(source).hexdigest())
                self.assertEqual(observed_at, 'original')
                captured.append(snapshot)

            with patch.object(refresh, 'ROOT', root), patch.object(refresh, '_refresh', build):
                refresh.main(source)
            self.assertFalse(captured[0].exists())
            self.assertEqual(sorted(p.name for p in root.iterdir()),
                             ['.refresh.lock', 'source-snapshot.json'])

    def test_two_commands_serialize_before_render_or_publish(self):
        with tempfile.TemporaryDirectory() as root:
            first_entered = threading.Event()
            release = threading.Event()
            second_entered = threading.Event()
            errors = []

            def build(snapshot, *_):
                if json.loads(snapshot.read_bytes())['observed_at'] == 'first':
                    first_entered.set()
                    self.assertTrue(release.wait(2))
                else:
                    second_entered.set()

            def run(label):
                try:
                    refresh.main(json.dumps({'observed_at': label}).encode())
                except BaseException as error:
                    errors.append(error)

            with patch.object(refresh, 'ROOT', Path(root)), patch.object(refresh, '_refresh', build):
                first = threading.Thread(target=run, args=('first',))
                second = threading.Thread(target=run, args=('second',))
                first.start()
                self.assertTrue(first_entered.wait(1))
                second.start()
                self.assertFalse(second_entered.wait(.05))
                release.set()
                first.join(2)
                second.join(2)
                self.assertFalse(first.is_alive() or second.is_alive())
            self.assertFalse(errors)
            self.assertTrue(second_entered.is_set())

    def test_invalid_or_oversized_input_never_enters_publisher(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(refresh, 'ROOT', Path(root)), patch.object(refresh, '_refresh') as publish:
                with self.assertRaises(json.JSONDecodeError):
                    refresh.main(b'not JSON')
                with self.assertRaises(SystemExit):
                    refresh.main(b'x' * (2 * 1024 * 1024 + 1))
                publish.assert_not_called()


if __name__ == '__main__':
    unittest.main()
