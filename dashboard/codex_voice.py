"""Native Codex WebRTC control, independent of the provider PCM dialogue loop.

The caller supplies an already authorized, frozen native-thread binding. This
client neither creates a thread nor submits text/PCM, supplies credentials,
answers native tool/approval requests, cancels backend work or retries writes.
Application activation still needs original-media and native-collector ownership.
"""
from collections import deque
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import threading
import time
import uuid


class CodexVoiceUnavailable(Exception):
    """A missing acknowledgement is not permission to repeat an operation."""


class CodexVoiceRejected(CodexVoiceUnavailable):
    """Native owner explicitly rejected this operation; no payload is exposed."""


class AvatarVoiceLease:
    """One app-owned mode, sharing the existing provider mode's active set.

    Acquire/release on the owning application's event loop. A lease does not
    claim exclusion of independent native CLI clients: the native API replaces
    existing voice on start and its stop is thread-scoped, not a generation CAS.
    Keep that limitation explicit before application activation.
    """
    def __init__(self, active, human, binding, native_thread):
        if (not isinstance(active,set) or type(human) is not int
                or not isinstance(binding,str) or not re.fullmatch('[a-f0-9]{64}',binding)
                or not isinstance(native_thread,str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}',native_thread)):
            raise ValueError('Select a frozen authorized voice binding')
        if human in active or len(active)>=2:
            raise CodexVoiceUnavailable('Another voice mode owns this conversation')
        self._guard=threading.RLock();self._claim=None
        self._active=active;self._human=human;self.binding=binding
        self.thread_id=native_thread;self._released=False
        active.add(human)

    def assert_held(self, claim=None):
        with self._guard:
            if (self._released or self._human not in self._active
                    or claim is not None and self._claim is not claim):
                raise CodexVoiceUnavailable('Selected voice mode is no longer owned')

    def claim(self, claimant):
        with self._guard:
            self.assert_held()
            if self._claim is not None:
                raise CodexVoiceUnavailable('Selected voice mode already has a native connection')
            self._claim=claimant

    def release(self):
        with self._guard:
            if not self._released:
                self._released=True;self._active.discard(self._human)


class CodexVoice:
    mode = 'codex_webrtc'
    max_event_bytes = 262144
    max_pending_bytes = 524288
    max_pending_events = 128
    max_frame_bytes = 8 * 1024 * 1024
    stop_wait_seconds = 8

    def __init__(self, native_home, thread_id, *, lease, connect=None):
        if not isinstance(thread_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', thread_id):
            raise ValueError('Select one authorized native thread')
        if not isinstance(lease,AvatarVoiceLease) or lease.thread_id!=thread_id:
            raise ValueError('Native voice requires its application mode lease')
        self._claim=object()
        lease.claim(self._claim)
        self._lease=lease
        self.thread_id = thread_id
        self.session_id = str(uuid.uuid4())
        self._guard = threading.Condition()
        self._rpc_guard = threading.Lock()
        self._events = deque()
        self._event_bytes = 0
        self._responses = {}
        self._waiting = None
        self._sequence = 0
        self._closed = False
        self._failed = False
        self._event_failed = False
        self._attempted = False
        self._start_rejected = False
        self._voice_closed = False
        self._owned = False
        self._stop_attempted = False
        self._socket = None
        self._reader = None
        self._clock = time.monotonic
        if connect is None:
            connect = self._connect_owner
        try:
            self._socket = connect(Path(native_home))
            self._reader = threading.Thread(target=self._read, name='codex-voice-owner', daemon=True)
            self._reader.start()
            self._rpc('initialize', {'clientInfo': {'name':'daimonapp-native-voice','version':'1.0'},
                                    'capabilities': {'experimentalApi':True}})
            self._socket.send(json.dumps({'method':'initialized'}))
            result = self._rpc('thread/resume', {'threadId':self.thread_id, 'excludeTurns':True})
            if result.get('thread', {}).get('id') != self.thread_id:
                raise CodexVoiceUnavailable('Native voice binding changed')
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _connect_owner(native_home):
        """Existing owner UDS only; no second daemon, login or endpoint override."""
        import websocket
        path = (native_home/'app-server-control'/'app-server-control.sock').resolve(strict=True)
        info, parent = path.stat(), path.parent.stat()
        if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077
                or not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or parent.st_mode & 0o077):
            raise CodexVoiceUnavailable('Existing native voice owner unavailable')
        raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        raw.settimeout(5)
        try:
            raw.connect(str(path))
            if hasattr(socket, 'SO_PEERCRED'):
                _, uid, _ = struct.unpack('3i', raw.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if uid != os.getuid():
                    raise CodexVoiceUnavailable('Native voice owner changed')
            return websocket.create_connection('ws://localhost/rpc', socket=raw, timeout=.5)
        except BaseException:
            raw.close()
            raise

    def _read(self):
        import websocket
        try:
            while not self._closed:
                try:
                    raw = self._socket.recv()
                except (TimeoutError, websocket.WebSocketTimeoutException):
                    continue
                if not isinstance(raw, str) or not raw or len(raw.encode()) > self.max_frame_bytes:
                    raise CodexVoiceUnavailable('Native voice transport unavailable')
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise CodexVoiceUnavailable('Native voice frame unavailable')
                with self._guard:
                    if 'method' not in value:
                        if self._waiting is not None and type(value.get('id')) is int and value['id'] == self._waiting:
                            self._responses[value['id']] = value
                            self._guard.notify_all()
                        continue
                    params = value.get('params', {})
                    if not isinstance(params, dict) or params.get('threadId') != self.thread_id:
                        continue
                    method = value['method']
                    if method == 'thread/realtime/started':
                        if params.get('realtimeSessionId') != self.session_id:
                            # Another client selected a different voice generation.
                            self._owned = False
                            raise CodexVoiceUnavailable('Native voice generation changed')
                        self._owned = True
                    elif method == 'thread/realtime/closed':
                        self._owned = False
                        self._voice_closed = True
                    # Completed transcript items are durable; do not queue every
                    # delta twice or copy an unrelated thread's/tool's payload.
                    if method not in ('thread/realtime/started','thread/realtime/sdp',
                                      'thread/realtime/closed','thread/realtime/error',
                                      'thread/realtime/item/completed','turn/started','turn/completed'):
                        continue
                    if 'id' in value:
                        # Server requests need the enrolled native collector.
                        # Never confuse them with notifications or approve them.
                        continue
                    size = len(raw.encode())
                    if (self._event_failed or size > self.max_event_bytes or len(self._events) >= self.max_pending_events
                            or self._event_bytes + size > self.max_pending_bytes):
                        # Retire delivery, not the control reader. The explicit
                        # stop response must still be processed after overflow.
                        self._event_failed=True
                        self._guard.notify_all()
                        continue
                    self._events.append((value,size))
                    self._event_bytes += size
                    self._guard.notify_all()
        except Exception:
            with self._guard:
                self._failed = True
                self._guard.notify_all()

    def _rpc(self, method, params, timeout=20):
        with self._rpc_guard:
            with self._guard:
                if self._closed or self._failed:
                    raise CodexVoiceUnavailable('Native voice owner unavailable')
                self._sequence += 1
                ident = self._sequence
                self._waiting = ident
            try:
                self._socket.send(json.dumps({'id':ident,'method':method,'params':params}))
                deadline = self._clock() + timeout
                with self._guard:
                    while ident not in self._responses and not self._failed and not self._closed:
                        remaining = deadline-self._clock()
                        if remaining <= 0:
                            break
                        self._guard.wait(remaining)
                    value = self._responses.pop(ident, None)
                if value is None:
                    raise CodexVoiceUnavailable('Native voice operation unconfirmed; do not repeat it')
                if 'error' in value:
                    raise CodexVoiceRejected('Native voice operation rejected')
                result = value.get('result')
                if not isinstance(result, dict):
                    raise CodexVoiceUnavailable('Native voice acknowledgement unavailable')
                return result
            except (OSError, ValueError):
                raise CodexVoiceUnavailable('Native voice operation unconfirmed; do not repeat it') from None
            finally:
                with self._guard:
                    self._waiting = None

    def start(self, sdp, *, voice='cove', context=None):
        # Only the authorized application supplies this owner-selected identity
        # and capability context. Never accept it as a browser prompt override.
        if (not isinstance(sdp,str) or not sdp.startswith('v=0') or len(sdp.encode())>65536
                or not isinstance(voice,str) or not re.fullmatch('[a-z]{1,32}',voice)
                or context is not None and (not isinstance(context,str) or not context.strip()
                    or len(context.encode())>8192 or '\0' in context)):
            raise ValueError('Select one bounded WebRTC offer and native voice')
        with self._guard:
            if self._attempted:
                raise CodexVoiceUnavailable('Native voice already attempted; inspect retained outcome')
            self._lease.assert_held(self._claim)
            self._attempted = True
        # Let Codex assemble startup context and manage its own backend handoffs.
        # Do not replace the current thread, model, tools, prompt or goal.
        params={'threadId':self.thread_id,
            'realtimeSessionId':self.session_id,'version':'v3','voice':voice,
            'outputModality':'audio','includeStartupContext':True,
            'clientManagedHandoffs':False,'transport':{'type':'webrtc','sdp':sdp}}
        if context is not None:
            params['initialItems']=[{'role':'developer','text':context}]
        try:
            return self._rpc('thread/realtime/start', params)
        except CodexVoiceRejected:
            with self._guard:
                self._start_rejected = True
                self._guard.notify_all()
            raise

    def receive(self, timeout=.5):
        if not isinstance(timeout,(float,int)) or not 0<=timeout<=2:
            raise ValueError('Select a bounded event wait')
        with self._guard:
            if not self._events and not self._closed and not self._failed and not self._event_failed:
                self._guard.wait(timeout)
            values = [v for v,_ in self._events]
            self._events.clear()
            self._event_bytes = 0
            if not values and self._failed:
                raise CodexVoiceUnavailable('Native voice connection ended; inspect its state')
            if not values and self._event_failed:
                raise CodexVoiceUnavailable('Native voice event capacity reached; stop voice and inspect its state')
            return values

    def stop(self):
        # Never turn a rejected/unknown start into stopping another voice client.
        # A stop ACK concerns voice only; backend work is not interrupted.
        with self._guard:
            if self._stop_attempted or not self._attempted or self._start_rejected or self._voice_closed:
                return None
            # Native start ACK can precede provider readiness. A cancelled open
            # must await this generation rather than silently abandoning it or
            # sending a thread-only stop against another client's voice.
            deadline=self._clock()+self.stop_wait_seconds
            while not self._owned and not self._failed and not self._closed and not self._voice_closed and not self._start_rejected:
                remaining=deadline-self._clock()
                if remaining<=0:
                    raise CodexVoiceUnavailable('Native voice opening remains unconfirmed')
                self._guard.wait(remaining)
            if not self._owned or self._stop_attempted:
                return None
            self._lease.assert_held(self._claim)
            self._stop_attempted = True
        result=self._rpc('thread/realtime/stop', {'threadId':self.thread_id},timeout=8)
        # The RPC ACK can precede the persisted close notification. Keep this
        # control connection alive until closure or an explicit uncertainty.
        with self._guard:
            deadline=self._clock()+self.stop_wait_seconds
            while not self._voice_closed and not self._failed and not self._closed:
                remaining=deadline-self._clock()
                if remaining<=0:
                    break
                self._guard.wait(remaining)
            if not self._voice_closed:
                raise CodexVoiceUnavailable('Native voice closure remains unconfirmed')
        return result

    def close(self):
        """Close this control connection; voice stop is explicit and separate."""
        with self._guard:
            self._closed = True
            self._guard.notify_all()
        if self._socket is not None:
            self._socket.close()
        if self._reader is not None and self._reader is not threading.current_thread():
            self._reader.join(timeout=1)
