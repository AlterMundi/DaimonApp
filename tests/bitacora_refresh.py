"""Pinned private-projection input and whole-command serialization; no publication."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
import io

SPEC = importlib.util.spec_from_file_location(
    'private_bitacora_refresh', Path(__file__).resolve().parents[1] / 'scripts/bitacora_refresh.py')
refresh = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refresh)


class PinnedProjection(unittest.TestCase):
    def test_inspection_verifies_existing_home_without_republishing_or_checkpoint(self):
        self.inspect_existing(corrupt=False)

    def test_inspection_keeps_corrupt_serving_unverified_without_republishing(self):
        self.inspect_existing(corrupt=True)

    def inspect_existing(self, corrupt):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project = root / 'project'
            project.mkdir()
            home = root / 'home'
            desk = home / '.config/daimon-social-identity/desk'
            desk.mkdir(parents=True)
            store = home / 'store'
            selected = store / 'objects/selected'
            selected.mkdir(parents=True)
            files = {'index.html': b'view', 'desk.js': b'code', 'desk.css': b'style',
                     'artifact-style.js': b'common',
                     'data.js': b'window.BITACORA_DATA={"cards":[],"observed_at":"earlier"};\n'}
            for name, data in files.items():
                (selected / name).write_bytes(data)
            state = json.dumps({'entries': [{'id': 'bitacora-desk', 'visibility': 'human',
                'object': 'selected', 'artifact_ref': 'own-artifact', 'version_ref': 'own-version'}]}).encode()
            (store / 'state.json').write_bytes(state)
            binding_dir = home / '.config/daimon-home'
            binding_dir.mkdir(parents=True)
            helper = home / '.agents/skills/daimon-home/scripts/home.py'
            helper.parent.mkdir(parents=True)
            helper.write_text('def private_token(path): return "fixture-token"\n')
            class Handler(BaseHTTPRequestHandler):
                def do_GET(handler):
                    if handler.headers.get('Authorization') != 'Bearer fixture-token':
                        handler.send_error(401)
                        return
                    name = handler.path.rsplit('/', 1)[-1]
                    body = b'wrong' if corrupt else files[name]
                    handler.send_response(200)
                    handler.send_header('X-Home-Version', 'own-version')
                    handler.end_headers()
                    handler.wfile.write(body)
                def log_message(self, *_):
                    pass
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            (binding_dir / 'binding.json').write_text(json.dumps({'store': str(store),
                'public_port': server.server_port, 'access': {'gateway_token_file': 'fixture-only'}}))
            def build(*args, **kwargs):
                self.assertNotIn('publish', args)
                output = Path(args[args.index('--output') + 1])
                output.mkdir(exist_ok=True)
                for name, data in files.items():
                    if name == 'data.js':
                        data = b'window.BITACORA_DATA={"cards":[],"observed_at":"new"};\n'
                    (output / name).write_bytes(data)
            try:
                output = io.StringIO()
                with patch.object(refresh, 'ROOT', project), patch.object(refresh, 'DESK', desk), \
                     patch.object(refresh.Path, 'home', return_value=home), patch.object(refresh, 'run', build), redirect_stdout(output):
                    if corrupt:
                        with self.assertRaises(SystemExit):
                            refresh.main(b'{"observed_at":"pinned"}', inspect_only=True)
                    else:
                        refresh.main(b'{"observed_at":"pinned"}', inspect_only=True)
                        result = json.loads(output.getvalue())
                        self.assertEqual(result['state'], 'existing_projection_verified')
                        self.assertFalse(result['checkpoint_matches'])
                        self.assertEqual(result['invocation_execution'], 'not_established')
                        self.assertTrue(result['owner_broker_all_files_match'])
                self.assertEqual((store / 'state.json').read_bytes(), state)
                self.assertFalse((desk / 'projection-current.json').exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)

    def test_existing_no_argument_route_captures_the_same_desk_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            desk = root / 'desk'
            desk.mkdir()
            source = b'{"observed_at":"ordinary","documents":[]}'
            (desk / 'source-snapshot.json').write_bytes(source)
            captured = []
            def build(snapshot, fd, digest, observed_at, inspect_only=False):
                captured.append((snapshot.read_bytes(), digest, observed_at))
            with patch.object(refresh, 'ROOT', root), patch.object(refresh, 'DESK', desk), patch.object(refresh, '_refresh', build):
                refresh.main()
            self.assertEqual(captured, [(source, hashlib.sha256(source).hexdigest(), 'ordinary')])

    def test_anonymous_input_survives_source_replacement_and_reaches_builder(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = b'{"observed_at":"original","documents":[]}'
            captured = []

            def build(snapshot, fd, digest, observed_at, inspect_only=False):
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
