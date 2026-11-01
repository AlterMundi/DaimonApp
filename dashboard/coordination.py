"""Explicit owner reads of Matrix's existing funding journal; no executor."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import signal
import uuid

from .private_state import read_json
from .speech import retain_io


class CoordinationUnavailable(Exception):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def reject_constant(value):
    raise ValueError('Non-finite operator value')


def unsigned(value):
    return type(value) is int and 0 <= value <= 2**53 - 1


class Coordination:
    """One human-requested snapshot, bounded to eight selected episodes.

    The configured command is the host's isolated Matrix operator CLI prefix.
    No browser value selects a command, journal, trust file or account. The app
    keeps no balance copy, timer, delivery queue or provider credentials.
    """
    def __init__(self, config, provider):
        selected = config.get('coordination', {})
        self.enabled = selected.get('enabled') is True
        self.lock = asyncio.Lock()
        if not self.enabled:
            return
        if set(selected) != {'enabled', 'command', 'store_id', 'principal', 'episodes'}:
            raise ValueError('Closed coordination reader configuration required')
        self.command = selected['command']
        self.store = selected['store_id']
        self.principal = selected['principal']
        self.human = provider.human
        if (not isinstance(self.command, list) or not 1 <= len(self.command) <= 24
                or not all(isinstance(v, str) and 0 < len(v) <= 4096 and '\0' not in v for v in self.command)
                or not Path(self.command[0]).is_absolute()
                or not isinstance(self.principal, str) or not 0 < len(self.principal) <= 200
                or not isinstance(self.store, str) or str(uuid.UUID(self.store)) != self.store
                or not isinstance(selected['episodes'], list) or not 1 <= len(selected['episodes']) <= 8):
            raise ValueError('Bounded explicit coordination reader required')
        self.episodes = []
        for episode in selected['episodes']:
            if (not isinstance(episode, dict) or set(episode) != {'account_id', 'instruction_file', 'task'}
                    or not isinstance(episode['account_id'], str) or not 0 < len(episode['account_id']) <= 200
                    or '\0' in episode['account_id'] or not isinstance(episode['task'], str)
                    or not 0 < len(episode['task'].encode('utf-8')) <= 16384):
                raise ValueError('Exact selected episode and approved objective required')
            path = Path(episode['instruction_file'])
            if not path.is_absolute():
                raise ValueError('Absolute existing instruction reference required')
            instruction = read_json(path)
            if (not isinstance(instruction, dict) or instruction.get('store_id') != self.store or instruction.get('principal') != self.principal
                    or instruction.get('task_sha256') != hashlib.sha256(episode['task'].encode()).hexdigest()):
                raise ValueError('Objective differs from the selected instruction')
            self.episodes.append({**episode, 'instruction': instruction,
                                  'instruction_sha256': hashlib.sha256(canonical(instruction)).hexdigest()})
        if len({e['account_id'] for e in self.episodes}) != len(self.episodes):
            raise ValueError('Duplicate coordination episode')

    def assert_binding(self):
        for episode in self.episodes:
            if read_json(episode['instruction_file']) != episode['instruction']:
                raise CoordinationUnavailable('instruction_binding_changed')

    async def _read(self, episode):
        child = await asyncio.create_subprocess_exec(
            *self.command, 'episode-report', '--', episode['account_id'],
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
        output = bytearray()
        try:
            async with asyncio.timeout(5):
                while chunk := await child.stdout.read(min(8192, 2097153 - len(output))):
                    output.extend(chunk)
                    if len(output) > 2097152:
                        raise CoordinationUnavailable('response_too_large')
                if await child.wait() != 0:
                    raise CoordinationUnavailable('operator_unavailable')
        finally:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await child.wait()
        value = json.loads(output, parse_constant=reject_constant)
        if not isinstance(value, dict) or value.get('schema') != 'execution/episode-report/v1':
            raise CoordinationUnavailable('invalid_report')
        snapshot = value.get('snapshot', {})
        if (not isinstance(snapshot, dict) or snapshot.get('store_id') != self.store or snapshot.get('principal') != self.principal
                or snapshot.get('account_id') != episode['account_id']
                or not isinstance(snapshot.get('instructions'), list)
                or not all(isinstance(v, dict) for v in snapshot['instructions'])
                or episode['instruction_sha256'] not in [v.get('instruction_sha256') for v in snapshot['instructions']]):
            raise CoordinationUnavailable('report_binding_changed')
        accounts = snapshot.get('accounts')
        if not isinstance(accounts, list) or not 3 <= len(accounts) <= 1024:
            raise CoordinationUnavailable('invalid_balances')
        fields = ('max_calls', 'calls', 'available_calls', 'max_charge', 'spent',
                  'reserved', 'available_charge', 'active', 'uncertain')
        balances = []
        for account in accounts:
            if (not isinstance(account, dict) or not all(unsigned(account.get(k)) for k in fields)
                    or account.get('kind') not in ('tribe', 'being', 'episode')
                    or not isinstance(account.get('unit'), str) or not isinstance(account.get('account_id'), str)
                    or type(account.get('paused')) is not bool
                    or account['calls'] + account['available_calls'] != account['max_calls']
                    or account['spent'] + account['reserved'] + account['available_charge'] != account['max_charge']):
                raise CoordinationUnavailable('invalid_balances')
            balances.append({k: account[k] for k in (*fields, 'kind', 'unit', 'account_id', 'paused')})
        if (not isinstance(snapshot.get('participants'), list) or len(snapshot['participants']) > 1024
                or not all(isinstance(v, str) and len(v) <= 200 for v in snapshot['participants'])
                or not isinstance(snapshot.get('work'), dict)
                or not set(snapshot['work']) <= {'queued', 'intent', 'withdrawn'}
                or not all(unsigned(v) for v in snapshot['work'].values())
                or not unsigned(snapshot.get('start')) or not unsigned(snapshot.get('end'))
                or not isinstance(snapshot.get('funding_constraints'), list)
                or len(snapshot['funding_constraints']) > 16
                or not all(isinstance(v, str) and len(v) <= 100 for v in snapshot['funding_constraints'])
                or len({a['account_id'] for a in balances}) != len(balances)
                or not any(a['kind'] == 'episode' and a['account_id'] == episode['account_id'] for a in balances)):
            raise CoordinationUnavailable('invalid_report')
        notice = value.get('notice')
        if notice is not None:
            if (not isinstance(notice, dict) or notice.get('schema') != 'execution/episode-notice/v1'
                    or notice.get('store_id') != self.store or notice.get('account_id') != episode['account_id']
                    or not isinstance(notice.get('notice_id'), str) or len(notice['notice_id']) != 64):
                raise CoordinationUnavailable('invalid_notice')
            notice = {'id': notice['notice_id'], 'kind': notice['kind'], 'observed_at': notice.get('observed_at')}
        return {'id': episode['account_id'], 'objective': episode['task'],
                'participants': snapshot['participants'], 'accounts': balances,
                'work': snapshot['work'], 'start': snapshot['start'], 'end': snapshot['end'],
                'observed_at': snapshot['observed_at'], 'constraints': snapshot['funding_constraints'],
                'notice': notice, 'read_only': True}

    async def snapshot(self):
        if not self.enabled:
            return {'state': 'not_configured', 'episodes': [], 'read_only': True}
        if self.lock.locked():
            return {'state': 'busy', 'episodes': [], 'read_only': True}
        async with self.lock:
            await retain_io(self.assert_binding)
            semaphore = asyncio.Semaphore(2)
            async def read(episode):
                async with semaphore:
                    return await self._read(episode)
            values = await asyncio.gather(*(read(e) for e in self.episodes), return_exceptions=True)
            if any(isinstance(v, BaseException) for v in values):
                raise CoordinationUnavailable('episode_read_unavailable')
            await retain_io(self.assert_binding)
            return {'state': 'available', 'episodes': values, 'read_only': True}
