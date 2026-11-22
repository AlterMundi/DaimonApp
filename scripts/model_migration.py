#!/usr/bin/env python3
"""Qualify Codex bridge model selections locally without starting a turn."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import signal
import sqlite3
import time
import tomllib

from activity_indicator import Native

MAPPING = {
    'gpt-6.1-sol': 'gpt-6.2-sol', 'gpt-6-sol': 'gpt-6.2-sol',
    'gpt-6-astra': 'gpt-6.2-astra', 'gpt-6.1-astra': 'gpt-6.2-astra',
}
SCHEMA = 'telecodex.owner-model-migration/v2'
LIMIT = 512
SELECTION = ('id', 'chat_id', 'thread_id', 'creator_user_id', 'codex_thread_id',
             'force_fresh_thread', 'cwd', 'model', 'reasoning_effort', 'updated_at')
COLUMNS = ','.join(SELECTION)


def private_file(path):
    path = Path(path)
    metadata = path.lstat()
    if path.is_symlink() or not path.is_file() or metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
        raise ValueError('owner_regular_file_required')
    return path.resolve()


def bounded_bytes(path, limit):
    with private_file(path).open('rb') as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError('file_size_bound_exceeded')
    return data


def identity(path):
    info = private_file(path).stat()
    return [info.st_dev, info.st_ino]


def bridge_config(raw):
    config = tomllib.loads(raw.decode())
    if config['codex'].get('shared_app_server') is not True:
        raise ValueError('shared_native_receiver_required')
    return config


def snapshot(path):
    path = private_file(path)
    raw = bounded_bytes(path, 1024 * 1024)
    config = bridge_config(raw)
    database = private_file(config['db_path'])
    return config, {
        'config': str(path),
        'config_sha256': hashlib.sha256(raw).hexdigest(),
        'database': str(database),
        'database_identity': identity(database),
    }


class Metadata(Native):
    def rpc(self, method, params):
        if method not in ('initialize', 'model/list', 'config/read', 'thread/read', 'account/rateLimits/read', 'account/read'):
            raise ValueError('metadata_method_required')
        self.sequence += 1
        self.send({'id': self.sequence, 'method': method, 'params': params})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                response = self.messages.get(timeout=max(.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if response.get('id') == self.sequence:
                if 'error' in response or not isinstance(response.get('result'), dict):
                    raise ValueError('native_metadata_unavailable')
                return response['result']
        raise TimeoutError('native_metadata_deadline')


class Availability:
    def __init__(self, metadata):
        self.metadata = metadata
        self.account = self.read_account()
        limits = metadata.rpc('account/rateLimits/read', None)
        if not any(isinstance(limits.get(k), dict) and limits[k]
                   for k in ('rateLimits', 'rateLimitsByLimitId')):
            raise ValueError('native_rate_limits_unverified')
        self.native_configs = {}
        self.catalog = {}
        cursor = None
        for _ in range(4):
            page = metadata.rpc('model/list', {'limit': 100, 'cursor': cursor, 'includeHidden': False})
            self.catalog.update({model['model']: model for model in page['data']})
            cursor = page.get('nextCursor')
            if not cursor:
                break
        if cursor:
            raise ValueError('catalog_bound_exceeded')

    def read_account(self):
        account = self.metadata.rpc('account/read', {'refreshToken': False}).get('account')
        if not isinstance(account, dict) or not account.get('type'):
            raise ValueError('native_account_unverified')
        return account

    def confirm_account(self):
        if self.read_account() != self.account:
            raise ValueError('native_account_changed')

    def effective_config(self, cwd):
        if not isinstance(cwd, str) or not Path(cwd).is_absolute():
            raise ValueError('absolute_receiver_workspace_required')
        if cwd not in self.native_configs:
            self.native_configs[cwd] = self.metadata.rpc(
                'config/read', {'includeLayers': False, 'cwd': cwd})['config']
        return self.native_configs[cwd]

    def check(self, config, target, effort, cwd, thread_id=None):
        # model/list is the active OpenAI catalog, not a custom provider probe.
        native = self.effective_config(cwd)
        provider = native.get('model_provider') or 'openai'
        if provider != 'openai':
            return 'provider_specific_availability_unverified'
        if target not in self.catalog:
            return 'target_not_advertised'
        if thread_id:
            thread = self.metadata.rpc('thread/read', {'threadId': thread_id, 'includeTurns': False})['thread']
            if thread.get('id') != thread_id:
                raise ValueError('native_thread_mismatch')
            if thread.get('modelProvider') != provider:
                return 'provider_specific_availability_unverified'
        # Existing rows pass their nullable effort directly. The bridge
        # default is copied only when creating/resetting a session.
        if not thread_id:
            effort = effort or config['codex'].get('default_reasoning_effort')
        effort = effort or native.get('model_reasoning_effort')
        model = self.catalog[target]
        effort = effort or model.get('defaultReasoningEffort')
        if effort not in {item['reasoningEffort'] for item in model['supportedReasoningEfforts']}:
            return 'effort_not_supported'
        return None


def connect(path, *, readonly=False):
    uri = private_file(path).as_uri()
    db = sqlite3.connect(uri + ('?mode=ro' if readonly else '?mode=rw'), uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def check_mapping(mapping):
    ids = list(mapping) + list(mapping.values())
    if not mapping or len(mapping) > 32 or any(
        not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', model)
        for model in ids
    ) or set(mapping).intersection(mapping.values()):
        raise ValueError('invalid_model_mapping')


def check_row(row, config, availability, target, excluded):
    if row['codex_thread_id'] in excluded:
        return 'explicitly_preserved_workload'
    if not row['codex_thread_id'] or row['force_fresh_thread']:
        return 'native_thread_not_bound'
    return availability.check(config, target, row['reasoning_effort'], row['cwd'], row['codex_thread_id'])


def prepare(config_path, metadata, excluded=(), mapping=None, *, initial_hash=None):
    mapping = MAPPING if mapping is None else mapping
    check_mapping(mapping)
    config, binding = snapshot(config_path)
    confirm_config_hash(binding['config_sha256'], initial_hash)
    availability = Availability(metadata)
    with closing(connect(binding['database'], readonly=True)) as db:
        rows = db.execute(f'SELECT {COLUMNS} FROM sessions ORDER BY id LIMIT ?', (LIMIT + 1,)).fetchall()
    if len(rows) > LIMIT:
        raise ValueError('session_bound_exceeded')
    changes, deferred = [], []
    for row in rows:
        target = mapping.get(row['model'])
        if target is None:
            continue
        reason = check_row(row, config, availability, target, excluded)
        if reason:
            deferred.append({'id': row['id'], 'reason': reason})
        else:
            changes.append({**dict(row), 'target': target})
    availability.confirm_account()
    read_binding(config_path, binding)
    return {'schema': SCHEMA, **binding, 'mapping': mapping,
            'changes': changes, 'deferred': deferred}


def validate_plan(plan):
    if plan.get('schema') != SCHEMA or not isinstance(plan.get('mapping'), dict):
        raise ValueError('invalid_model_plan')
    check_mapping(plan['mapping'])
    changes = plan['changes']
    if not isinstance(changes, list) or len(changes) > LIMIT:
        raise ValueError('invalid_model_plan')
    ids = set()
    for row in changes:
        if (set(row) != set(SELECTION) | {'target'} or type(row['id']) is not int
                or row['id'] in ids or not isinstance(row['target'], str)
                or plan['mapping'].get(row['model']) != row['target']):
            raise ValueError('invalid_model_plan')
        ids.add(row['id'])


def read_binding(config_path, plan):
    config, binding = snapshot(config_path)
    if binding != {key: plan[key] for key in binding}:
        raise ValueError('configuration_or_database_binding_changed')
    return config


def confirm_config_hash(current, expected):
    if expected is not None and current != expected:
        raise ValueError('configuration_changed_before_native_observation')


def selected_models(db, changes):
    states = []
    for change in changes:
        row = db.execute(f'SELECT {COLUMNS} FROM sessions WHERE id=?', (change['id'],)).fetchone()
        if row is None or any(row[key] != change[key] for key in SELECTION
                              if key not in ('model', 'updated_at')):
            raise ValueError('session_binding_changed')
        states.append(row)
    if all(row['model'] == change['target'] for row, change in zip(states, changes)):
        return False
    if any(row['model'] != change['model'] for row, change in zip(states, changes)):
        raise ValueError('concurrent_model_selection_preserved')
    if any(row['updated_at'] != change['updated_at'] for row, change in zip(states, changes)):
        raise ValueError('session_binding_changed: settings_revision')
    return True


def apply(config_path, plan, metadata, excluded=(), *, initial_hash=None):
    validate_plan(plan)
    config = read_binding(config_path, plan)
    confirm_config_hash(plan['config_sha256'], initial_hash)
    changes = plan['changes']
    result = {'state': 'already-selected' if changes else 'no-changes', 'count': len(changes), 'new_turns': 0}
    with closing(connect(plan['database'], readonly=True)) as db:
        if not selected_models(db, changes):
            return result
    availability = Availability(metadata)
    for change in changes:
        reason = check_row(change, config, availability, change['target'], excluded)
        if reason:
            raise ValueError('live_qualification_lost: ' + reason)
    availability.confirm_account()
    with closing(connect(plan['database'])) as db:
        db.execute('BEGIN IMMEDIATE')
        read_binding(config_path, plan)
        if not selected_models(db, changes):
            return result
        revision = datetime.now(timezone.utc).isoformat(timespec='microseconds')
        for change in changes:
            affected = db.execute(
                'UPDATE sessions SET model=?, updated_at=? WHERE id=? AND model=? AND updated_at=?',
                (change['target'], revision, change['id'], change['model'], change['updated_at']))
            if affected.rowcount != 1:
                raise ValueError('concurrent_model_selection_preserved')
        db.commit()
    return {**result, 'state': 'selected-for-next-turn'}


def verify_default(config_path, metadata, expected, *, initial_hash=None):
    # Candidate and selected TOML both use the existing listener's default.
    # The caller owns selection/reload and has to verify loaded behavior separately.
    raw = bounded_bytes(config_path, 1024 * 1024)
    config = bridge_config(raw)
    confirm_config_hash(hashlib.sha256(raw).hexdigest(), initial_hash)
    availability = Availability(metadata)
    configured = config['codex'].get('default_model')
    cwd = config['codex']['default_cwd']
    target = configured or availability.effective_config(cwd).get('model')
    if target != expected:
        raise ValueError('effective_default_mismatch')
    reason = availability.check(config, target, None, cwd)
    if reason:
        raise ValueError(reason)
    availability.confirm_account()
    if raw != bounded_bytes(config_path, 1024 * 1024):
        raise ValueError('configuration_changed')
    return {'state': 'default-qualified-on-disk', 'model': target,
            'source': 'bridge-config' if configured else 'native-config', 'loaded': 'unobserved'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--verify-default', metavar='MODEL')
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--replace', action='append', metavar='OLD=NEW', default=[])
    parser.add_argument('--exclude-native-thread', action='append', default=[])
    args = parser.parse_args()
    if not args.verify_default and not args.plan:
        parser.error('--plan is required when preparing or applying')
    if args.replace and (args.apply or args.verify_default):
        parser.error('--replace is used only when preparing a plan')
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError('migration_deadline')))
    signal.alarm(300)
    os.umask(0o077)
    raw = bounded_bytes(args.config, 1024 * 1024)
    config = bridge_config(raw)
    initial_hash = hashlib.sha256(raw).hexdigest()
    native = Metadata(config['codex'].get('binary', 'codex'))
    try:
        if args.apply:
            plan = json.loads(bounded_bytes(args.plan, 512 * 1024))
            result = apply(args.config, plan, native, args.exclude_native_thread, initial_hash=initial_hash)
        elif args.verify_default:
            result = verify_default(args.config, native, args.verify_default, initial_hash=initial_hash)
        else:
            pairs = [value.split('=', 1) for value in args.replace]
            mapping = dict(pairs) if pairs else None
            if pairs and len(pairs) != len(mapping):
                raise ValueError('duplicate_model_mapping')
            plan = prepare(args.config, native, args.exclude_native_thread, mapping, initial_hash=initial_hash)
            with args.plan.open('x') as output:
                json.dump(plan, output, indent=2)
            result = {'state': 'prepared', 'changes': len(plan['changes']), 'deferred': plan['deferred']}
        print(json.dumps(result))
    finally:
        native.close()


if __name__ == '__main__':
    main()
