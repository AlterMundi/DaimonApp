"""Durable public Live creation receipts, not another conversation/work store.

The authenticated service supplies the frozen human/conversation owner. These
checks bind receipts to that owner; they do not authorize a browser or grant
tools. No route is mounted here. Existing native and provider modes stay intact.
"""
import hashlib
import json
import math
import time
import uuid

from .codex_voice_history import history_lock
from .openai_live import LiveCall, LiveUnavailable, creation_request, _text
from .private_state import private_directory
from scripts.speech_render import atomic, private_bytes, RenderError


class LiveCreations:
    max_records = 512
    max_record_bytes = 262144
    max_total_bytes = 32 * 1024 * 1024
    max_active = 2
    unsettled = frozenset(('creating', 'creation_unconfirmed', 'created'))

    def __init__(self, directory):
        self.root = private_directory(directory)

    @staticmethod
    def _ident(ident):
        if not isinstance(ident, str) or str(uuid.UUID(ident)) != ident:
            raise ValueError('Select one public Live creation identity')
        return ident

    @staticmethod
    def _owner(human, frozen):
        if (type(human) is not int or human <= 0 or not isinstance(frozen, dict)
                or set(frozen) != {'binding', 'entry_binding', 'native_thread'}
                or not isinstance(frozen['binding'], str) or len(frozen['binding']) != 64
                or any(c not in '0123456789abcdef' for c in frozen['binding'])
                or not isinstance(frozen['entry_binding'], list)
                or len(frozen['entry_binding']) != 4 or frozen['entry_binding'][0] != human
                or not _text(frozen['native_thread'], 128)
                or frozen['entry_binding'][3] != frozen['native_thread']):
            raise ValueError('Select a frozen authenticated voice owner')
        raw = json.dumps({'human': human, 'frozen': frozen}, allow_nan=False,
                         ensure_ascii=False, separators=(',', ':'))
        if len(raw.encode()) > 8192:
            raise ValueError('Public Live owner snapshot exceeds its bound')
        return json.loads(raw)

    def _path(self, ident):
        return self.root / (self._ident(ident) + '.json')

    def _read(self, ident):
        value = json.loads(private_bytes(self._path(ident), self.max_record_bytes))
        if (not isinstance(value, dict) or value.get('schema') != 'daimon.live-creation/v1'
                or value.get('id') != ident or value.get('state') not in
                self.unsettled | {'creation_rejected', 'project_key_unavailable', 'closed'}):
            raise ValueError('Public Live creation record is unavailable')
        owner = value.get('owner')
        if (not isinstance(owner, dict)
                or self._owner(owner.get('human'), owner.get('frozen')) != owner):
            raise ValueError('Public Live creation owner is unavailable')
        if value['state'] in ('created', 'closed'):
            call = value.get('call')
            if (not isinstance(call, dict) or not _text(call.get('session_id'), 1024)
                    or not _text(call.get('sdp'), 65536) or not call['sdp'].startswith('v=0')):
                raise ValueError('Public Live creation receipt is unavailable')
        return value

    @staticmethod
    def _matches(value, owner, request_sha=None):
        if (value.get('owner') != owner
                or request_sha is not None and value.get('request_sha256') != request_sha):
            raise ValueError('Public Live creation belongs to another request or owner')

    def _records(self):
        records = []
        other_bytes = 0
        for index, path in enumerate(self.root.iterdir()):
            if index >= 2 * self.max_records + 1:
                raise ValueError('Public Live creation storage contains too many entries')
            if path.name == '.lock':
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError('Public Live state contains an unsafe entry')
            if len(records) >= self.max_records or other_bytes > self.max_total_bytes:
                raise ValueError('Public Live creation storage is full')
            if path.suffix == '.json':
                value = self._read(path.stem)
                records.append((value, path.stat().st_size))
            else:
                # Interrupted atomic-write fragments count toward capacity too.
                other_bytes += path.stat().st_size
        return records, other_bytes

    def _write(self, value):
        raw = json.dumps(value, allow_nan=False, ensure_ascii=False,
                         separators=(',', ':')).encode()
        if len(raw) > self.max_record_bytes:
            raise ValueError('Public Live creation receipt exceeds its bound')
        atomic(self._path(value['id']), raw)

    def read(self, ident, human, frozen):
        owner = self._owner(human, frozen)
        value = self._read(ident)
        self._matches(value, owner)
        return value

    def attach(self, ident, human, frozen, client, *, connect=None):
        value = self.read(ident, human, frozen)
        if value['state'] != 'created':
            raise LiveUnavailable('session_not_attachable')
        return client.attach(self._result(value), connect=connect)

    def create(self, ident, human, frozen, sdp, spec, client):
        """Retain intent before one POST; exact retries only read its outcome.

        A crash after intent is uncertain even if the request might not have
        left. A changed offer/spec/owner cannot reuse that ID. Unknown or active
        public calls block another call for that human, including after restart.
        The caller must freshly authenticate/recheck the frozen owner first.
        """
        owner = self._owner(human, frozen)
        path = self._path(ident)
        request = creation_request(sdp, spec)
        digest = hashlib.sha256(json.dumps(request, allow_nan=False, ensure_ascii=False,
            separators=(',', ':')).encode()).hexdigest()
        with history_lock(self.root / '.lock'):
            if path.exists() or path.is_symlink():
                value = self._read(ident)
                self._matches(value, owner, digest)
                return self._result(value)
            records, other_bytes = self._records()
            active = [v for v, _ in records if v['state'] in self.unsettled]
            if any(v['owner']['human'] == human for v in active):
                raise LiveUnavailable('prior_creation_needs_review')
            if len(active) >= self.max_active:
                raise LiveUnavailable('public_voice_capacity')
            # Reserve a full receipt before billing, including other unfinished
            # attempts. Leave space for the atomic temporary write alongside it.
            charged = other_bytes + sum(self.max_record_bytes if v['state'] in self.unsettled
                                         else size for v, size in records)
            if len(records) >= self.max_records or charged + 2 * self.max_record_bytes > self.max_total_bytes:
                raise LiveUnavailable('creation_storage_full')
            value = {'schema': 'daimon.live-creation/v1', 'id': ident, 'owner': owner,
                'request_sha256': digest, 'created_at': time.time(), 'state': 'creating'}
            self._write(value)
        # No filesystem lock spans network I/O. The durable intent owns this
        # call across process loss; another writer cannot create or replace it.
        try:
            call = client.create(request['transport']['sdp'], request['session'])
        except Exception as error:
            outcome = error.outcome if isinstance(error, LiveUnavailable) else 'creation_unconfirmed'
            if outcome not in ('creation_rejected', 'project_key_unavailable'):
                outcome = 'creation_unconfirmed'
            status = error.status if isinstance(error, LiveUnavailable) else None
            try:
                with history_lock(self.root / '.lock'):
                    current = self._read(ident)
                    self._matches(current, owner, digest)
                    current.update(state=outcome)
                    if type(status) is int:
                        current['http_status'] = status
                    self._write(current)
            except (OSError, ValueError, RenderError):
                # The already durable creating record remains uncertain.
                raise LiveUnavailable('creation_unconfirmed') from None
            raise LiveUnavailable(outcome, status=status) from None
        try:
            with history_lock(self.root / '.lock'):
                current = self._read(ident)
                self._matches(current, owner, digest)
                if current['state'] != 'creating':
                    raise LiveUnavailable('creation_unconfirmed')
                if (not isinstance(call, LiveCall) or not _text(call.session_id, 1024)
                        or not _text(call.sdp, 65536) or not call.sdp.startswith('v=0')):
                    raise LiveUnavailable('creation_unconfirmed')
                current.update(state='created', call={'session_id': call.session_id, 'sdp': call.sdp})
                self._write(current)
        except (OSError, ValueError, RenderError):
            raise LiveUnavailable('creation_unconfirmed') from None
        return call

    @staticmethod
    def _result(value):
        if value['state'] == 'created':
            return LiveCall(value['call']['session_id'], value['call']['sdp'])
        if value['state'] == 'closed':
            raise LiveUnavailable('session_closed')
        outcome = value['state'] if value['state'] in ('creation_rejected', 'project_key_unavailable') else 'creation_unconfirmed'
        raise LiveUnavailable(outcome, status=value.get('http_status'))

    def observe_closed(self, ident, human, frozen, event):
        """Trusted server-side provider event only; never a browser assertion.

        This records voice finalization/usage. It does not cancel, complete or
        rewrite any independent native/client-delegated work or human question.
        """
        owner = self._owner(human, frozen)
        if (not isinstance(event, dict) or event.get('type') != 'session.closed'
                or not isinstance(event.get('session'), dict)
                or event.get('reason') not in ('close_requested', 'expired', 'content',
                    'remote_hangup', 'connection_lost')):
            raise ValueError('Select a confirmed public Live finalization event')
        with history_lock(self.root / '.lock'):
            value = self._read(ident)
            self._matches(value, owner)
            if (value['state'] not in ('created', 'closed')
                    or event['session'].get('id') != value['call']['session_id']):
                raise ValueError('Public Live finalization belongs to another session')
            usage = event.get('usage')
            seconds = usage.get('seconds') if isinstance(usage, dict) else None
            confirmed = type(seconds) in (int, float) and math.isfinite(seconds) and seconds >= 0
            receipt = {'reason': event['reason'], 'usage_seconds': seconds if confirmed else None,
                       'voice_usage_confirmed': confirmed}
            if value['state'] == 'closed':
                if value['finalization'] != receipt:
                    raise ValueError('Public Live finalization changed')
                return value
            value.update(state='closed', finalization=receipt)
            self._write(value)
            return value
