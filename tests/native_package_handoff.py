#!/usr/bin/env python3
"""Actual isolated managed handoff with a live start watcher; no provider calls."""
import argparse
import json
import os
from pathlib import Path
import queue
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from activity_indicator import Native
from native_package_handoff import adopt, identity, package_identity


def rpc(client, method, params):
    client.sequence += 1
    ident = client.sequence
    client.send({'id': ident, 'method': method, 'params': params})
    until = time.monotonic() + 15
    while time.monotonic() < until:
        try:
            value = client.messages.get(timeout=1)
        except queue.Empty:
            continue
        if value.get('id') == ident:
            assert 'error' not in value, value
            return value['result']
    raise AssertionError('isolated native RPC timed out')


def qualify(old, candidate, scratch, lifecycle_seconds=None):
    home = Path(tempfile.mkdtemp(prefix='native-handoff-', dir=scratch))
    env = {**os.environ, 'CODEX_HOME': str(home), 'HOME': str(home)}
    (home / 'config.toml').write_text('model="mock-model"\nmodel_provider="fixture"\napproval_policy="never"\nsandbox_mode="read-only"\n[features]\nplugins=false\n[model_providers.fixture]\nname="Unreachable loopback fixture"\nbase_url="http://127.0.0.1:1/v1"\nwire_api="responses"\nrequires_openai_auth=false\nrequest_max_retries=0\n')
    state = home / 'app-server-daemon'
    state.mkdir()
    (state / 'settings.json').write_text(json.dumps({'remoteControlEnabled': False,
                                                   'updater': {'autoUpdateEnabled': False}}))

    def command(binary, *args):
        return subprocess.run([str(binary), 'app-server', 'daemon', *args], env=env,
                              capture_output=True, text=True, timeout=45)

    proxy = home / 'proxy'
    proxy.write_text('#!/bin/sh\nexport CODEX_HOME=' + shlex.quote(str(home))
                     + '\nexport HOME=' + shlex.quote(str(home)) + '\nexec '
                     + shlex.quote(str(candidate)) + ' app-server proxy\n')
    proxy.chmod(0o700)
    client = None
    watcher = None
    complete = False
    try:
        boot = command(old, 'bootstrap')
        assert boot.returncode == 0, boot.stderr
        original = json.loads((state / 'daemon.pid').read_text())['pid']
        client = Native(str(proxy))
        root = rpc(client, 'thread/start', {'cwd': str(home), 'model': 'mock-model',
                                         'approvalPolicy': 'never', 'sandbox': 'read-only'})['thread']['id']
        # This is a competing real CLI caller, not a fake process-state response.
        watcher_code = ('import subprocess,sys,time\n'
                        'while True:\n'
                        ' subprocess.run([sys.argv[1],"app-server","daemon","start"],'
                        'stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)\n'
                        ' time.sleep(.1)\n')
        watcher = subprocess.Popen([sys.executable, '-B', '-c', watcher_code, str(old)], env=env)
        time.sleep(.15)
        package = candidate.parent.parent
        files = package_identity(package)['files']
        for name in ('bin/codex', 'bin/codex-code-mode-host', 'codex-package.json',
                     'codex-path/rg', 'codex-resources/bwrap'):
            assert name in files, name
        # Include the canonical0.167 executor and any other qualified package
        # bytes; a fixed0.163 five-file map cannot qualify a complete successor.
        executor = json.loads((package / 'codex-package.json').read_text()).get('execServer')
        if executor:
            assert executor in files, executor
        plan = {'schema': 'daimon.native-package-handoff/v1', 'id': str(uuid.uuid4()),
                'ready': True, 'uid': os.getuid(), 'package': str(package), 'files': files,
                'codex_home': str(home), 'cgroup': Path('/proc/self/cgroup').read_text().strip(),
                'supervisor': identity(watcher.pid), 'receiver': identity(original)}
        if lifecycle_seconds is not None:
            plan['schema'] = 'daimon.native-package-handoff/v2'
            plan['lifecycle_deadline_unix'] = time.time() + lifecycle_seconds
        receipt = home / 'handoff.json'
        result = adopt(plan, receipt, env=env)
        assert result['phase'] == 'restored_candidate', result
        assert result['supervisor_resumed'] is True
        assert len(result['commands']) == 3 and all(c['returncode'] == 0 for c in result['commands'])
        client.close()
        client = Native(str(proxy))
        assert root in rpc(client, 'thread/loaded/list', {'limit': 16})['data']
        assert rpc(client, 'thread/read', {'threadId': root, 'includeTurns': False})['thread']['id'] == root
        replacement = result['replacement']['pid']
        time.sleep(.4)
        assert json.loads((state / 'daemon.pid').read_text())['pid'] == replacement
        assert watcher.poll() is None
        try:
            adopt(plan, receipt, env=env)
        except ValueError as error:
            assert 'retained operation' in str(error)
        else:
            raise AssertionError('completed handoff was rearmed')
        print(json.dumps({'state': 'PASS', 'live_watcher_held_and_resumed': True,
                          'same_persistent_cgroup': True, 'restored_original_thread': root,
                          'replacement_survives_watcher': True, 'duplicate_refused': True,
                          'native_input_sent': False, 'live_provider_calls': 0}), flush=True)
        complete = True
    finally:
        if client:
            client.close()
        if watcher:
            # Fixture-owned cleanup only. Never target the real receiving watcher.
            watcher.send_signal(__import__('signal').SIGCONT)
            watcher.terminate()
            watcher.wait(timeout=5)
        stopped = command(candidate, 'stop')
        if complete and stopped.returncode == 0:
            shutil.rmtree(home)
        else:
            print('Unfinished isolated fixture retained: ' + str(home), file=sys.stderr)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('old', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--scratch', required=True, type=Path)
    parser.add_argument('--lifecycle-seconds', type=int, help='Exercise bounded v2;200..300 seconds')
    args = parser.parse_args()
    if args.lifecycle_seconds is not None and not 200 <= args.lifecycle_seconds <= 300:
        parser.error('--lifecycle-seconds must be200..300')
    qualify(args.old.resolve(), args.candidate.resolve(), args.scratch, args.lifecycle_seconds)
