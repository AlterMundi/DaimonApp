"""Retain the Sessions authority during the move to TeleDaimon."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tomllib

from .private_state import read_json, write_json

SCHEMA = 'daimon.sessions-telegram-split/v1'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def private_toml(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Telegram split requires an owner-only configuration')
        raw = stream.read(262145)
    if len(raw) > 262144:
        raise ValueError('Telegram split configuration exceeds its bound')
    return raw, tomllib.loads(raw.decode())


def verified_binding(record, provider):
    from .provider import receiving_authority

    if not isinstance(record, dict) or set(record) != {
        'schema', 'bot_id', 'bot_username', 'human', 'credential_fingerprint',
        'telegram_endpoint', 'gateway_authority_sha256', 'legacy_authority',
        'legacy_receiver_sha256', 'legacy_alerts_binding', 'alerts_projection',
        'traffic_config_sha256',
    } or record['schema'] != SCHEMA:
        raise ValueError('Invalid Sessions Telegram split binding')
    for key in ('credential_fingerprint', 'gateway_authority_sha256', 'legacy_receiver_sha256'):
        if not isinstance(record[key], str) or re.fullmatch(r'[0-9a-f]{64}', record[key]) is None:
            raise ValueError('Invalid Sessions Telegram binding digest')
    for key in ('legacy_alerts_binding', 'alerts_projection', 'traffic_config_sha256'):
        if record[key] is not None and (
                not isinstance(record[key], str) or re.fullmatch(r'[0-9a-f]{64}', record[key]) is None):
            raise ValueError('Invalid Sessions Telegram binding digest')
    gateway = provider.receiver.get('telegram', {})
    legacy = json.loads(bytes.fromhex(record['legacy_authority']))
    previously_selected = legacy.pop('telegram')
    current = json.loads(provider.selected_binding)
    current.pop('telegram')
    current_legacy = json.loads(receiving_authority(provider.receiver, legacy_native_helpers=True))
    current_legacy.pop('telegram')
    if (legacy not in (current, current_legacy) or provider.human != record['human'] or provider.config['bot_id'] != record['bot_id']
            or provider.config.get('bot_username') != record['bot_username']
            or gateway.get('enabled', True) is not True or gateway.get('external_polling') is not True
            or gateway.get('external_bot_id') not in (None, record['bot_id'])
            or any(gateway.get(key) for key in ('bot_token', 'bot_token_file', 'bot_token_env'))
            or previously_selected.get('bot_token') is not None
            or digest(provider.selected_binding) != record['gateway_authority_sha256']):
        raise ValueError('Sessions Telegram split authority changed')
    return record


def prepare(config, gateway_path, adapter_path, output, *, legacy_native_helpers=False):
    """Verify the two profiles and retained bindings without dispatching Telegram."""
    from scripts.bot_traffic import private_token as meter_fingerprint
    from .alerts import Client, delivery_binding, private_token
    from .provider import Provider, receiving_authority

    old_bytes, old = private_toml(config['receiver_config'])
    _, gateway = private_toml(gateway_path)
    _, adapter = private_toml(adapter_path)
    previous = old['telegram']
    transport = adapter['telegram']
    if (previous.get('bot_token') is not None or previous.get('external_polling') is True
            or transport.get('external_polling') is not True
            or transport.get('enabled', True) is not True
            or previous.get('api_base') != transport.get('api_base')
            or previous.get('local_file_root') != transport.get('local_file_root')
            or adapter['session_control']['socket_path'] != old['session_control']['socket_path']
            or gateway['session_control'] != old['session_control']):
        raise ValueError('TeleDaimon profile changes the retained receiving scope')
    legacy_authority = receiving_authority(old, legacy_native_helpers=legacy_native_helpers)
    current_authority = receiving_authority(gateway)
    before, after = json.loads(receiving_authority(old)), json.loads(current_authority)
    before.pop('telegram')
    after.pop('telegram')
    if before != after:
        raise ValueError('Gateway profile changes the existing Sessions authority')
    token = private_token(previous['bot_token_file'])
    if not token.startswith(str(config['bot_id']) + ':') or token != private_token(transport['bot_token_file']):
        raise ValueError('TeleDaimon credential does not match the selected bot')
    fingerprint = digest(token.encode())
    endpoint = previous.get('api_base', 'https://api.telegram.org').rstrip('/')
    provider = Provider(config)
    provider.binding_bytes = legacy_authority
    settings = config.get('alerts', {})
    legacy_alerts = alerts_projection = None
    if settings.get('enabled') is True:
        client = Client(settings)
        legacy_alerts = delivery_binding(client, settings, config, provider, token)
        alerts_projection = delivery_binding(client, settings, config, provider, '')
        path = Path(config['state_dir']) / 'alerts/delivery.sqlite3'
        if path.exists():
            with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=2)) as db:
                if db.execute('SELECT value FROM binding').fetchall() != [(legacy_alerts,)]:
                    raise ValueError('Alerts retained journal has another binding')
    traffic_digest = None
    traffic = config.get('traffic', {})
    if traffic.get('enabled') is True:
        meter_bytes, meter = private_toml(traffic['meter_config'])
        if (meter_fingerprint(meter['token_file']).hex() != fingerprint
                or endpoint != 'http://127.0.0.1:' + str(meter['port'])):
            raise ValueError('Traffic meter does not match the retained bot')
        traffic_digest = digest(meter_bytes)
    record = {
        'schema': SCHEMA,
        'bot_id': config['bot_id'],
        'bot_username': config.get('bot_username'),
        'human': provider.human,
        'credential_fingerprint': fingerprint,
        'telegram_endpoint': endpoint,
        'gateway_authority_sha256': digest(current_authority),
        'legacy_authority': legacy_authority.hex(),
        'legacy_receiver_sha256': digest(old_bytes),
        'legacy_alerts_binding': legacy_alerts,
        'alerts_projection': alerts_projection,
        'traffic_config_sha256': traffic_digest,
    }
    provider.receiver = gateway
    provider.selected_binding = current_authority
    verified_binding(record, provider)
    if Path(output).exists() or Path(output).is_symlink():
        if read_json(output) != record:
            raise ValueError('A different Telegram split binding is already retained')
    else:
        write_json(output, record)
