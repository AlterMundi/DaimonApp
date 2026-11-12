#!/usr/bin/env python3
"""Requalify one stopped owner's Alerts journal after a private projection selection.

No send, model, recovery, configuration write or ignored fingerprint field.
Run inside the existing voice-fenced receiving maintenance, after web exit.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tomllib
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.alerts import Client, Sender, private_token, receiving_binding
from dashboard.private_state import private_directory, read_json, write_json
from dashboard.provider import receiving_authority


def private_config(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Select an owner-private regular configuration')
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError('Configuration exceeds bound')
    return raw, tomllib.loads(raw.decode())


def stopped(pid):
    if type(pid) is not int or pid <= 1:
        raise ValueError('Select the observed prior web process')
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return
    raise ValueError('Prior web process has not exited')


def settle(root, before, after):
    """Only binding metadata changes; attempts and uncertain deliveries stay intact."""
    root = private_directory(private_directory(root) / 'alerts')
    journal = root / 'delivery.sqlite3'
    info = journal.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('Select the existing owner-private Alerts journal')
    menu = root / 'menu-attention.json'
    with closing(sqlite3.connect(journal.as_uri() + '?mode=rw', uri=True, timeout=3)) as db, db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute('SELECT value FROM binding LIMIT 2').fetchall()
        if len(rows) != 1 or rows[0][0] not in (before, after):
            raise ValueError('Alerts selection changed; retain and inspect')
        previous = rows[0][0]
        if menu.exists() or menu.is_symlink():
            record = read_json(menu)
            if record.get('binding') not in (before, after):
                raise ValueError('Menu selection changed; retain and inspect')
            if previous == after and record['binding'] != after:
                raise ValueError('Menu conflicts with settled journal')
            if record['binding'] != after:
                # Durable first; a crash before SQLite commit is recoverable with
                # the same old/new identity. Preserve pending setter outcomes.
                write_json(menu, {**record, 'binding': after})
        if previous != after:
            changed = db.execute('UPDATE binding SET value=? WHERE value=?', (after, before))
            if changed.rowcount != 1:
                raise ValueError('Alerts binding changed during qualification')
        db.commit()
    return {'phase': 'qualified', 'binding_changed': previous != after,
            'delivery_attempts_modified': False, 'delivery_sent': False}


def qualify(config_path, before_path, expected_before, expected_current, web_pid):
    stopped(web_pid)
    _, config = private_config(config_path)
    old_raw, old = private_config(before_path)
    current_path = Path(config['receiver_config'])
    new_raw, new = private_config(current_path)
    if (hashlib.sha256(old_raw).hexdigest() != expected_before
            or hashlib.sha256(new_raw).hexdigest() != expected_current):
        raise ValueError('Exact retained receiver selection required')
    old_without, new_without = json.loads(json.dumps(old)), json.loads(json.dumps(new))
    old_without['interaction'].pop('private_projection', None)
    new_without['interaction'].pop('private_projection', None)
    if old_without != new_without or old == new:
        raise ValueError('Only the selected private projection may change')
    bindings, credentials = [], []
    for receiver in (old, new):
        provider = SimpleNamespace(receiver=receiver,
            human=int(receiver['session_control']['human_id']),
            binding_bytes=receiving_authority(receiver))
        client, sender = Client(config['alerts']), Sender(provider, config)
        bindings.append(receiving_binding(config, provider, client, sender))
        credentials.append((client.base, client.fingerprint, sender.base, sender.token))
    if credentials[0] != credentials[1]:
        raise ValueError('Credential selection changed during qualification')
    client.assert_binding()
    if private_token(sender.token_file) != sender.token:
        raise ValueError('Bot credential changed during qualification')
    # No credential/base/audience/provider selector was excluded or substituted.
    stopped(web_pid)
    if current_path.read_bytes() != new_raw:
        raise ValueError('Receiver changed during qualification')
    return settle(Path(config['state_dir']), *bindings)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--before-sha256', required=True)
    parser.add_argument('--current-sha256', required=True)
    parser.add_argument('--stopped-web-pid', type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.config, args.before, args.before_sha256,
                             args.current_sha256, args.stopped_web_pid)))


if __name__ == '__main__':
    main()
