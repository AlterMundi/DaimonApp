"""One explicit native package handoff; no scheduler, force or input replay.

Run in the receiving service's existing persistent cgroup. A detached launcher
alone does not establish that placement. The owner supplies private paths and
fresh process identities; the plan is configuration, never authorization.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import stat
import subprocess
import tempfile
import time
import uuid


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def package_identity(root):
    """Bounded complete tree identity; retain metadata only, never package copies."""
    root = Path(root).resolve(strict=True)
    files, links, directories = {}, {}, []
    pending = [root]
    count = total = 0
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                if count > 64:
                    raise ValueError('package entry capacity')
                path = Path(entry.path)
                name = path.relative_to(root).as_posix()
                metadata = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(metadata.st_mode):
                    target = os.readlink(path)
                    if Path(target).is_absolute() or not path.resolve(strict=True).is_relative_to(root):
                        raise ValueError('package link escapes tree')
                    links[name] = target
                elif stat.S_ISDIR(metadata.st_mode):
                    directories.append(name)
                    pending.append(path)
                elif stat.S_ISREG(metadata.st_mode):
                    total += metadata.st_size
                    if len(files) >= 32 or total > 1024 ** 3:
                        raise ValueError('package file capacity')
                    files[name] = digest(path)
                else:
                    raise ValueError('nonregular package entry')
    return {'files': files, 'links': links, 'directories': sorted(directories)}


def selected_package(root, candidate, previous_root, previous):
    selected_root = root.resolve(strict=True)
    observed = package_identity(selected_root)
    # The qualified Unix installer adds this compatibility entrypoint after
    # hashing/copying the supplied package (prepare_install.rs).
    installed_candidate = {**candidate, 'links': {'codex': 'bin/codex'}}
    if observed == installed_candidate:
        return True, observed
    if selected_root == previous_root and observed == previous:
        return False, observed
    raise RuntimeError('selected package uncertain; no restore attempted')


def identity(pid):
    root = Path('/proc') / str(pid)
    stat = (root / 'stat').read_text().split(') ', 1)[1].split()
    return {'pid': pid, 'start_ticks': stat[19],
            'cgroup': (root / 'cgroup').read_text().strip(),
            'argv_sha256': hashlib.sha256((root / 'cmdline').read_bytes()).hexdigest()}


def checkpoint(path, value):
    raw = (json.dumps(value, sort_keys=True) + '\n').encode()
    if len(raw) > 65536:
        raise ValueError('handoff receipt capacity')
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def exited(fd):
    poll = select.poll()
    poll.register(fd, select.POLLIN)
    return bool(poll.poll(0))


def live_children(pid):
    tasks = list((Path('/proc') / str(pid) / 'task').iterdir())
    if len(tasks) > 64:
        raise ValueError('watcher task observation capacity')
    children = {int(child) for task in tasks for child in (task / 'children').read_text().split()}
    if len(children) > 256:
        raise ValueError('watcher child observation capacity')
    for child in children:
        try:
            state = Path(f'/proc/{child}/stat').read_text().split(') ', 1)[1].split()[0]
            if state != 'Z':
                return True
        except FileNotFoundError:
            pass
    return False


def cli(binary, args, env, timeout):
    result = subprocess.run([str(binary), 'app-server', 'daemon', *args],
                            env=env, capture_output=True, timeout=timeout)
    # Never copy arbitrary native stderr/configuration into the receipt.
    if len(result.stdout) > 65536:
        raise ValueError('native result capacity')
    value = json.loads(result.stdout) if result.returncode == 0 else None
    return result.returncode, value


def adopt(plan, receipt, *, env=None):
    """Serialize this finite intent without holding the native lifecycle lock."""
    fd = os.open(str(receipt) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _adopt(plan, receipt, env=env)
    finally:
        os.close(fd)


def _adopt(plan, receipt, *, env=None):
    """Use only the qualified maintenance/update/restore commands, exactly once.

    A stopped watcher is not a stopped daemon: all native work/admission remains
    live until the receiver itself accepts a natural-idle handoff. Keeping this
    one watcher held prevents its ordinary `start` from clearing saved recovery.
    Replacement remains in the same persistent service cgroup.
    """
    if receipt.exists():
        raise ValueError('retained operation exists; inspect it, never rearm')
    if plan['schema'] != 'daimon.native-package-handoff/v1' or plan['ready'] is not True:
        raise ValueError('complete owner candidate required')
    uuid.UUID(plan['id'])
    if (Path('/proc/self/cgroup').read_text().strip() != plan['cgroup']
            or os.getuid() != plan['uid']):
        raise ValueError('receiving persistent cgroup/owner differs')
    package = Path(plan['package'])
    if not package.is_absolute() or not Path(plan['codex_home']).is_absolute():
        raise ValueError('absolute receiving package/home required')
    candidate = package_identity(package)
    if candidate['files'] != plan['files'] or candidate['links']:
        raise ValueError('qualified complete package differs')
    binary = package / 'bin/codex'
    if 'bin/codex' not in plan['files']:
        raise ValueError('qualified native CLI required')
    supervisor, receiver = plan['supervisor'], plan['receiver']
    for selected in (supervisor, receiver):
        if identity(selected['pid']) != selected or selected['cgroup'] != plan['cgroup']:
            raise ValueError('receiving process generation changed')
    native_home = Path(plan['codex_home'])
    environment = dict(os.environ if env is None else env, CODEX_HOME=str(native_home))
    selected_root = native_home / 'packages/app-server-daemon/current'
    previous_root = selected_root.resolve(strict=True)
    previous = package_identity(previous_root)
    # pidfds keep signal/exit observations tied to these processes, never reused PIDs.
    watcher_fd = os.pidfd_open(supervisor['pid'])
    try:
        receiver_fd = os.pidfd_open(receiver['pid'])
        try:
            if (identity(supervisor['pid']) != supervisor or exited(watcher_fd)
                    or identity(receiver['pid']) != receiver or exited(receiver_fd)):
                raise ValueError('receiving process changed while pinning identity')
        except Exception:
            os.close(receiver_fd)
            raise
    except Exception:
        os.close(watcher_fd)
        raise
    state = {'schema': 'daimon.native-package-handoff-receipt/v1', 'id': plan['id'],
             'phase': 'preflight', 'supervisor_resumed': False, 'commands': [],
             'old_receiver': receiver, 'native_input_sent': False}
    held = False
    restored = False
    resume_safe = True

    def command(args, timeout=140):
        code, value = cli(binary, args, environment, timeout)
        # Only fixed status metadata; neither source history nor credentials.
        state['commands'].append({'argv': args, 'returncode': code,
                                  'outcome': value.get('outcome') if isinstance(value, dict) else None})
        checkpoint(receipt, state)
        return code, value

    try:
        checkpoint(receipt, state)
        watcher_state = Path(f'/proc/{supervisor["pid"]}/stat').read_text().split(') ', 1)[1].split()[0]
        if watcher_state in ('T', 't'):
            raise ValueError('watcher already held by another operation')
        state['phase'] = 'holding_watcher'
        checkpoint(receipt, state)
        signal.pidfd_send_signal(watcher_fd, signal.SIGSTOP)
        held = True
        until = time.monotonic() + 2
        while Path(f'/proc/{supervisor["pid"]}/stat').read_text().split(') ', 1)[1].split()[0] != 'T':
            if time.monotonic() >= until:
                raise TimeoutError('watcher hold unconfirmed')
            time.sleep(.02)
        # Suspending the Python watcher does not suspend a start CLI it already
        # launched. Observe that child finishing; never race an in-flight start.
        until = time.monotonic() + 2
        while live_children(supervisor['pid']):
            if time.monotonic() >= until:
                state['phase'] = 'deferred_watcher_child'
                return state
            time.sleep(.02)
        if exited(receiver_fd) or identity(receiver['pid']) != receiver:
            raise ValueError('receiver changed before maintenance')
        state['phase'] = 'maintenance_requested'
        checkpoint(receipt, state)
        resume_safe = False
        code, value = command(['maintenance'])
        if code != 0 or not isinstance(value, dict) or value.get('pid') != receiver['pid']:
            raise RuntimeError('maintenance outcome unconfirmed')
        if value.get('outcome') != 'handoffReady':
            state['phase'] = 'deferred'
            # Already-pending or explicit Stop may still retire this receiver.
            # Only a terminal deferral establishes no future handoff effect.
            resume_safe = value.get('outcome') == 'deferred'
            return state
        state['phase'] = 'handoff_ready'
        checkpoint(receipt, state)
        until = time.monotonic() + 15
        while not exited(receiver_fd):
            if time.monotonic() >= until:
                raise TimeoutError('handoff process exit not observed')
            time.sleep(.05)
        state['phase'] = 'old_exit_observed'
        checkpoint(receipt, state)
        try:
            code, _ = command(['update', '--from-cli', '--if-stopped', '--yes'])
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            # Do not retry installation. Its atomic current selection is checked
            # below; a known old/new package can still restore confirmed recovery.
            code = -1
            state['installer_acknowledgment'] = 'unconfirmed'
        # Full files/resources identity distinguishes equal CLI binaries with
        # different helpers. Known fallback also pins the previous release path.
        installed, observed_package = selected_package(selected_root, candidate, previous_root, previous)
        actual = observed_package['files']['bin/codex']
        state['installer_returncode'] = code
        state['phase'] = 'restoring_selected' if installed else 'restoring_previous'
        checkpoint(receipt, state)
        restore_code, restored_value = command(['restart', '--if-stopped'], timeout=180)
        if restore_code != 0 or not isinstance(restored_value, dict):
            raise RuntimeError('restore outcome unconfirmed; do not repeat start')
        replacement = restored_value.get('pid')
        if not isinstance(replacement, int) or replacement == receiver['pid']:
            raise RuntimeError('replacement identity missing')
        observed = identity(replacement)
        if observed['cgroup'] != plan['cgroup'] or digest(Path(f'/proc/{replacement}/exe')) != actual:
            raise RuntimeError('replacement placement/code differs')
        if selected_package(selected_root, candidate, previous_root, previous) != (installed, observed_package):
            raise RuntimeError('selected complete package changed during restore')
        restored = True
        state['replacement'] = observed
        state['phase'] = 'restored_candidate' if installed else 'restored_previous'
        return state
    except Exception as error:
        state['failure_class'] = type(error).__name__
        state['phase'] = 'unconfirmed'
        raise
    finally:
        # Never let a generic watcher fresh-start after an uncertain exited
        # handoff. The retained receipt remains the operator recovery boundary.
        try:
            if held and (restored or resume_safe) and not exited(watcher_fd):
                signal.pidfd_send_signal(watcher_fd, signal.SIGCONT)
                state['supervisor_resumed'] = True
            checkpoint(receipt, state)
        finally:
            os.close(receiver_fd)
            os.close(watcher_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--receipt', required=True, type=Path)
    parser.add_argument('--adopt', action='store_true')
    args = parser.parse_args()
    if not args.adopt:
        raise SystemExit('No operation armed; explicit owner --adopt is required.')
    if args.plan.stat().st_size > 65536:
        raise ValueError('bounded owner plan required')
    result = adopt(json.loads(args.plan.read_text()), args.receipt)
    print(json.dumps({'phase': result['phase'], 'supervisor_resumed': result['supervisor_resumed']}))


if __name__ == '__main__':
    main()
