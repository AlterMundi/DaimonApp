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
SCHEMA = 'telecodex.owner-model-migration/v4'
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

    def catalog_matches_provider(self, native, provider):
        if provider == 'openai':
            return True
        # A closed OpenAI alias with the same hosted account/default endpoint
        # uses the same native catalog. Any routing/auth/header override refuses.
        providers = native.get('model_providers', {})
        builtin = providers.get('openai', {})
        if (native.get('openai_base_url') is not None or native.get('model_catalog_json') is not None
                or builtin.get('base_url') is not None or builtin.get('model_catalog_url') is not None
                or native.get('chatgpt_base_url') not in (None, 'https://chatgpt.com',
                       'https://chatgpt.com/', 'https://chatgpt.com/backend-api/')):
            return False
        info = providers.get(provider)
        if self.account.get('type') != 'chatgpt' or not isinstance(info, dict):
            return False
        active = {key: value for key, value in info.items() if value is not None}
        allowed = {'name', 'wire_api', 'requires_openai_auth',
                   'supports_websockets', 'supports_standalone_web_search'}
        return (not set(active) - allowed and active.get('name') == 'OpenAI'
                and active.get('wire_api') == 'responses'
                and active.get('requires_openai_auth') is True
                and all(type(active[key]) is bool for key in
                        ('supports_websockets', 'supports_standalone_web_search') if key in active))

    def check(self, config, target, effort, cwd, thread_id=None, expected_native_model=None):
        # model/list is the active OpenAI catalog, not a custom provider probe.
        native = self.effective_config(cwd)
        provider = native.get('model_provider') or 'openai'
        if not self.catalog_matches_provider(native, provider):
            return 'provider_specific_availability_unverified'
        if target not in self.catalog:
            return 'target_not_advertised'
        if thread_id:
            thread = self.metadata.rpc('thread/read', {'threadId': thread_id, 'includeTurns': False})['thread']
            if thread.get('id') != thread_id:
                raise ValueError('native_thread_mismatch')
            if expected_native_model is not None and thread.get('model') != expected_native_model:
                raise ValueError('inherited_native_selection_changed')
            if not self.catalog_matches_provider(native, thread.get('modelProvider')):
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


def check_row(row, config, availability, target, excluded, *, include_unbound=False, expected_native_model=None):
    if row['codex_thread_id'] in excluded:
        return 'explicitly_preserved_workload'
    if not row['codex_thread_id'] or row['force_fresh_thread']:
        if not include_unbound or row['model'] is None:
            return 'native_thread_not_bound'
        return availability.check(config, target, row['reasoning_effort'], row['cwd'])
    return availability.check(config, target, row['reasoning_effort'], row['cwd'], row['codex_thread_id'], expected_native_model)


def prepare(config_path, metadata, excluded=(), mapping=None, *, initial_hash=None, include_inherited=False, include_unbound=False):
    mapping = MAPPING if mapping is None else mapping
    check_mapping(mapping)
    config, binding = snapshot(config_path)
    confirm_config_hash(binding['config_sha256'], initial_hash)
    availability = Availability(metadata)
    with closing(connect(binding['database'], readonly=True)) as db:
        rows = db.execute(f'SELECT {COLUMNS} FROM sessions ORDER BY id LIMIT ?', (LIMIT + 1,)).fetchall()
    if len(rows) > LIMIT:
        raise ValueError('session_bound_exceeded')
    changes, deferred, inherited = [], [], {}
    for row in rows:
        source_model = row['model']
        if source_model is None and include_inherited:
            if row['codex_thread_id'] in excluded:
                deferred.append({'id': row['id'], 'reason': 'explicitly_preserved_workload'})
                continue
            if not row['codex_thread_id'] or row['force_fresh_thread']:
                deferred.append({'id': row['id'], 'reason': 'native_thread_not_bound'})
                continue
            native_thread = metadata.rpc('thread/read', {'threadId': row['codex_thread_id'], 'includeTurns': False})['thread']
            if native_thread.get('id') != row['codex_thread_id']:
                raise ValueError('native_thread_mismatch')
            source_model = native_thread.get('model')
            if not isinstance(source_model, str):
                deferred.append({'id': row['id'], 'reason': 'inherited_native_model_unobserved'})
                continue
        target = mapping.get(source_model)
        if target is None:
            continue
        reason = check_row(row, config, availability, target, excluded, include_unbound=include_unbound,
                           expected_native_model=source_model if row['model'] is None else None)
        if reason:
            deferred.append({'id': row['id'], 'reason': reason})
        else:
            changes.append({**dict(row), 'target': target})
            if row['model'] is None:
                inherited[str(row['id'])] = source_model
    availability.confirm_account()
    read_binding(config_path, binding)
    return {'schema': SCHEMA, **binding, 'mapping': mapping,
            'changes': changes, 'deferred': deferred, 'inherited_source_models': inherited,
            'include_unbound': include_unbound}


def validate_plan(plan):
    if (plan.get('schema') != SCHEMA or not isinstance(plan.get('mapping'), dict)
            or type(plan.get('include_unbound')) is not bool):
        raise ValueError('invalid_model_plan')
    check_mapping(plan['mapping'])
    changes = plan['changes']
    if not isinstance(changes, list) or len(changes) > LIMIT:
        raise ValueError('invalid_model_plan')
    inherited = plan.get('inherited_source_models')
    if not isinstance(inherited, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in inherited.items()):
        raise ValueError('invalid_inherited_model_plan')
    ids = set()
    for row in changes:
        if (set(row) != set(SELECTION) | {'target'} or type(row['id']) is not int
                or row['id'] in ids or not isinstance(row['target'], str)
                or plan['mapping'].get(inherited.get(str(row['id'])) if row['model'] is None else row['model']) != row['target']):
            raise ValueError('invalid_model_plan')
        if (row['model'] is None) != (str(row['id']) in inherited):
            raise ValueError('invalid_inherited_model_plan')
        ids.add(row['id'])
    if set(inherited) - {str(i) for i in ids}:
        raise ValueError('invalid_inherited_model_plan')


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
        reason = check_row(change, config, availability, change['target'], excluded,
                           include_unbound=plan['include_unbound'],
                           expected_native_model=plan['inherited_source_models'].get(str(change['id'])))
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
                'UPDATE sessions SET model=?, updated_at=? WHERE id=? AND model IS ? AND updated_at=?',
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



FAMILY_RELEASE = re.compile(r'gpt-([0-9]{1,3})(?:\.([0-9]{1,3}))?(?:\.([0-9]{1,3}))?-(sol|astra)')
FAMILY_TARGET = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')


def family_release(model):
    match = FAMILY_RELEASE.fullmatch(model) if isinstance(model, str) else None
    if match is None:
        return None
    return match[4], [int(part or 0) for part in match.groups()[:3]]


def family_fingerprint(value):
    normalized = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(normalized).hexdigest()


def observe_native_family(config_path, metadata, target, *, initial_hash=None):
    """Export authenticated availability for one receiving native default."""
    if not FAMILY_TARGET.fullmatch(target):
        raise ValueError('invalid_model_family_receiver')
    raw = bounded_bytes(config_path, 1024 * 1024)
    confirm_config_hash(hashlib.sha256(raw).hexdigest(), initial_hash)
    cwd = bridge_config(raw)['codex']['default_cwd']
    availability = Availability(metadata)
    native = availability.effective_config(cwd)
    builtin = native.get('model_providers', {}).get('openai', {})
    if (
        availability.account.get('type') != 'chatgpt'
        or native.get('model_provider') not in (None, 'openai')
        or native.get('openai_base_url') is not None
        or native.get('model_catalog_json') is not None
        or native.get('chatgpt_base_url') not in (
            None, 'https://chatgpt.com', 'https://chatgpt.com/', 'https://chatgpt.com/backend-api/'
        )
        or builtin.get('wire_api') not in (None, 'responses')
        or builtin.get('requires_openai_auth') not in (None, True)
        or any(value is not None for key, value in builtin.items() if key not in {
            'name', 'wire_api', 'requires_openai_auth', 'supports_websockets',
            'supports_standalone_web_search', 'request_max_retries', 'stream_max_retries',
            'stream_idle_timeout_ms', 'websocket_connect_timeout_ms',
        })
    ):
        raise ValueError('canonical_native_family_catalog_required')
    current = native.get('model')
    current_release = family_release(current)
    if current_release is None or current not in availability.catalog:
        raise ValueError('recognized_current_family_model_required')
    family, current_version = current_release
    effort = native.get('model_reasoning_effort')
    if effort is None:
        effort = availability.catalog[current].get('defaultReasoningEffort')
    if not isinstance(effort, str):
        raise ValueError('explicit_supported_effort_required')
    role = {'route': 'native-chatgpt', 'target': target, 'family': family}
    frozen = {'cwd': cwd, 'account': availability.account, 'effort': effort}
    contract = family_fingerprint({
        **role, **frozen, 'native': {k: v for k, v in native.items() if k != 'model'},
    })
    revision = family_fingerprint({**role, **frozen, 'native': native})
    accepted = []
    for model, details in availability.catalog.items():
        release = family_release(model)
        if release is not None and release[0] == family and any(
            option['reasoningEffort'] == effort for option in details['supportedReasoningEfforts']
        ):
            accepted.append((release[1], model))
    if not any(model == current for _, model in accepted):
        raise ValueError('current_family_effort_unverified')
    availability.confirm_account()
    if metadata.rpc('config/read', {'includeLayers': False, 'cwd': cwd})['config'] != native:
        raise ValueError('native_config_changed')
    if raw != bounded_bytes(config_path, 1024 * 1024):
        raise ValueError('configuration_changed')
    now = int(time.time())
    candidates = [
        {**role, 'contract': contract, 'model': model, 'version': release,
         'available': True, 'qualification': None, 'observed_at': now}
        for release, model in sorted(accepted, reverse=True)[:16]
    ]
    return {
        'schema': 'cluster.model-family-evidence/v1',
        'workloads': [{
            **role, 'id': 'codex-default', 'contract': contract,
            'follow': True, 'current': current, 'current_version': current_version,
            'current_revision': revision, 'candidates': candidates,
        }],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--verify-default', metavar='MODEL')
    mode.add_argument('--observe-family', metavar='RECEIVER', help='Export read-only availability for the receiving native default')
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--include-unbound', action='store_true', help='Qualify explicit saved models for rows without a bound native thread')
    parser.add_argument('--include-inherited', action='store_true', help='Qualify the actual bound native model when the bridge selection is null')
    parser.add_argument('--replace', action='append', metavar='OLD=NEW', default=[])
    parser.add_argument('--exclude-native-thread', action='append', default=[])
    args = parser.parse_args()
    if not (args.verify_default or args.observe_family or args.plan):
        parser.error('--plan is required when preparing or applying')
    if args.observe_family and (args.plan or args.include_unbound or args.include_inherited
                                or args.replace or args.exclude_native_thread):
        parser.error('--observe-family is separate from migration planning and selection')
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
        elif args.observe_family:
            result = observe_native_family(args.config, native, args.observe_family, initial_hash=initial_hash)
        else:
            pairs = [value.split('=', 1) for value in args.replace]
            mapping = dict(pairs) if pairs else None
            if pairs and len(pairs) != len(mapping):
                raise ValueError('duplicate_model_mapping')
            plan = prepare(args.config, native, args.exclude_native_thread, mapping, initial_hash=initial_hash, include_inherited=args.include_inherited, include_unbound=args.include_unbound)
            with args.plan.open('x') as output:
                json.dump(plan, output, indent=2)
            result = {'state': 'prepared', 'changes': len(plan['changes']), 'deferred': plan['deferred']}
        print(json.dumps(result))
    finally:
        native.close()


if __name__ == '__main__':
    main()
