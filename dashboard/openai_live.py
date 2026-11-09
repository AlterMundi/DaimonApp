"""Public GPT-Live WebRTC creation, separate from Codex and Realtime.

Transport for the default-off mounted comparison. Its owner authorizes and
durably records one creation intent before calling. This helper discovers no
credentials and replays no sources or requests. Media travels on WebRTC tracks;
native/backing work keeps its existing independent owner.
"""
from dataclasses import dataclass, field
import json
import re
import threading
import time
from urllib.parse import quote

import httpx

from scripts.speech_render import private_bytes, RenderError


class LiveUnavailable(Exception):
    """Fixed outcome only; never include provider payloads or credentials."""
    def __init__(self, outcome, *, status=None):
        super().__init__(outcome)
        self.outcome = outcome
        self.status = status


def _text(value, limit):
    return (isinstance(value, str) and bool(value.strip())
            and '\0' not in value and len(value.encode()) <= limit)


def session_spec(instructions, *, backend_model=None, backend_instructions=None,
                 backend_tools=(), client_delegation=False,
                 session_options=None, backend_options=None, delegation_options=None):
    """Owner-selected session configuration; never accept this from a browser.

    Responses is the initial public comparison. Client delegation is explicit
    for existing execution owners; it does not create an application turn loop.
    Backend tools remain backend tools, independent of the voice frontend.
    """
    session_options = {} if session_options is None else session_options
    backend_options = {} if backend_options is None else backend_options
    delegation_options = {} if delegation_options is None else delegation_options
    if (not _text(instructions, 8192) or type(client_delegation) is not bool
            or not isinstance(session_options, dict) or not isinstance(backend_options, dict)
            or not isinstance(delegation_options, dict)
            or {'model', 'instructions', 'delegation'} & session_options.keys()
            or {'model', 'instructions', 'tools'} & backend_options.keys()
            or {'type', 'responses'} & delegation_options.keys()):
        raise ValueError('Select bounded owner voice instructions')
    if client_delegation:
        if backend_model is not None or backend_instructions is not None or backend_tools or backend_options:
            raise ValueError('Client delegation retains its existing backend configuration')
        delegation = {'type': 'client'}
    else:
        if (not isinstance(backend_model, str)
                or not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', backend_model)
                or not _text(backend_instructions, 8192)
                or not isinstance(backend_tools, (list, tuple)) or len(backend_tools) > 128
                or any(not isinstance(tool, dict) or not isinstance(tool.get('type'), str)
                       for tool in backend_tools)):
            raise ValueError('Select the owner Responses backend and tools')
        delegation = {'type': 'responses', 'responses': {
            'model': backend_model, 'instructions': backend_instructions,
            'tools': list(backend_tools), **backend_options}}
    delegation.update(delegation_options)
    # Freeze the owner's input, reject non-JSON/nonfinite values and bound tools.
    raw = json.dumps({'model': 'gpt-live-1', 'instructions': instructions,
                      'delegation': delegation, **session_options}, allow_nan=False, ensure_ascii=False)
    if len(raw.encode()) > 32768:
        raise ValueError('Public Live session configuration exceeds its bound')
    return json.loads(raw)


def creation_request(sdp, spec):
    """Freeze the exact owner request before a durable creation claim."""
    if not _text(sdp, 65536) or not sdp.startswith('v=0'):
        raise ValueError('Select a bounded WebRTC offer')
    if not isinstance(spec, dict) or not {'model', 'instructions', 'delegation'} <= spec.keys():
        raise ValueError('Select an owner Live session specification')
    options = {key: value for key, value in spec.items()
               if key not in ('model', 'instructions', 'delegation')}
    delegation = spec['delegation']
    if not isinstance(delegation, dict):
        raise ValueError('Select a Live delegation mode')
    delegation_options = {key: value for key, value in delegation.items() if key not in ('type', 'responses')}
    if delegation.get('type') == 'client' and 'responses' not in delegation:
        frozen = session_spec(spec['instructions'], client_delegation=True,
            session_options=options, delegation_options=delegation_options)
    elif delegation.get('type') == 'responses':
        backend = delegation.get('responses')
        if not isinstance(backend, dict) or not {'model', 'instructions', 'tools'} <= backend.keys():
            raise ValueError('Select a Responses delegation specification')
        frozen = session_spec(spec['instructions'], backend_model=backend['model'],
            backend_instructions=backend['instructions'], backend_tools=backend['tools'],
            session_options=options, delegation_options=delegation_options,
            backend_options={key: value for key, value in backend.items()
                if key not in ('model', 'instructions', 'tools')})
    else:
        raise ValueError('Select a Live delegation mode')
    if frozen != spec:
        raise ValueError('Select the requested GPT-Live model without overrides')
    return {'session': frozen, 'transport': {'type': 'webrtc', 'sdp': sdp}}


def fork_request(source_session,sdp):
    """Only the documented WebRTC offer; provider inherits stored context."""
    if not _text(source_session,1024) or not _text(sdp,65536) or not sdp.startswith('v=0'):
        raise ValueError('Select a retained stored session and bounded WebRTC offer')
    return {'transport':{'type':'webrtc','sdp':sdp}}


@dataclass(frozen=True)
class LiveCall:
    session_id: str
    sdp: str = field(repr=False)


class OpenAILive:
    """One explicitly owned POST, using a separately configured project key.

    A timeout/lost/malformed response is unconfirmed creation, not permission to
    try another call. This in-process guard is not the owner's durable journal.
    A definitive HTTP rejection is retained as a numeric status, without raw
    provider text. No Codex login files, tokens or alternate endpoints are used.
    """
    endpoint = 'https://api.openai.com/v1/live/sessions'
    max_response_bytes = 131072

    def __init__(self, api_key_file, *, transport=None):
        self._api_key_file = api_key_file
        self._transport = transport
        self._attempted = False
        self._guard = threading.Lock()

    @staticmethod
    def _sideband_connector():
        try:
            from websocket import create_connection
        except ImportError:
            raise LiveUnavailable('sideband_dependency_unavailable') from None
        return create_connection

    def prepare_transport(self):
        """Check configured access and the required local control transport before admission."""
        self._project_key()
        self._sideband_connector()

    def _project_key(self):
        try:
            key = private_bytes(self._api_key_file, 16384).decode().strip()
        except (OSError, UnicodeError, RenderError):
            raise LiveUnavailable('project_key_unavailable') from None
        if not re.fullmatch(r'sk-[A-Za-z0-9_-]{16,512}', key):
            raise LiveUnavailable('project_key_unavailable')
        return key

    def create(self, sdp, spec):
        payload = creation_request(sdp, spec)
        return self._post(self.endpoint,payload)

    def fork(self,source_session,sdp):
        payload=fork_request(source_session,sdp)
        call=self._post(self.endpoint+'/'+quote(source_session,safe='')+'/fork',payload,successful=(200,201))
        if call.session_id==source_session:raise LiveUnavailable('creation_unconfirmed')
        return call

    def _post(self,endpoint,payload,*,successful=(201,)):
        key = self._project_key()
        with self._guard:
            if self._attempted:
                raise LiveUnavailable('creation_already_attempted')
            self._attempted = True
        try:
            deadline = time.monotonic() + 30
            with httpx.Client(transport=self._transport, follow_redirects=False,
                              timeout=httpx.Timeout(20, connect=5, write=10, pool=5)) as client:
                with client.stream('POST', endpoint,
                        headers={'Authorization': 'Bearer ' + key}, json=payload) as response:
                    if response.status_code not in successful:
                        outcome = ('creation_rejected' if 400 <= response.status_code < 500
                                   and response.status_code != 408 else 'creation_unconfirmed')
                        raise LiveUnavailable(outcome, status=response.status_code)
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        if time.monotonic() > deadline or len(body) + len(chunk) > self.max_response_bytes:
                            raise LiveUnavailable('creation_unconfirmed')
                        body.extend(chunk)
            value = json.loads(body)
            ident = value['session']['id']
            answer = value['transport']
            if (not _text(ident, 1024) or answer['type'] != 'webrtc'
                    or not _text(answer['sdp'], 65536) or not answer['sdp'].startswith('v=0')):
                raise LiveUnavailable('creation_unconfirmed')
            return LiveCall(ident, answer['sdp'])
        except LiveUnavailable:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise LiveUnavailable('creation_unconfirmed') from None

    def attach(self, call, *, connect=None):
        """Attach to this owner's retained call; never create or restart it."""
        if not isinstance(call, LiveCall) or not _text(call.session_id, 1024):
            raise ValueError('Select one retained owner Live call')
        key = self._project_key()
        if connect is None:
            connect = self._sideband_connector()
        url = 'wss://api.openai.com/v1/live/sessions/' + quote(call.session_id, safe='') + '/attach'
        connection = None
        try:
            connection = connect(url, header={'Authorization': 'Bearer ' + key}, timeout=5)
            connection.settimeout(.5)
            return LiveSideband(call.session_id, connection)
        except Exception:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            raise LiveUnavailable('sideband_unavailable') from None


class LiveSideband:
    """Foreground control/event connection, independent of primary media/work.

    The application owns its single reader and each action/delegation. This
    class dispatches no tools, stores no reflected audio, and installs no loop,
    wakeup or automatic retry. Detaching does not close the provider session.
    """
    max_event_bytes = 1024 * 1024

    def __init__(self, session_id, connection):
        self.session_id = session_id
        self._connection = connection
        self._write_lock = threading.Lock()
        self._detached = False
        self._uncertain_write = False

    def receive(self):
        from websocket import WebSocketTimeoutException
        if self._detached:
            raise LiveUnavailable('sideband_detached')
        try:
            raw = self._connection.recv()
        except (TimeoutError, WebSocketTimeoutException):
            return None
        except Exception:
            raise LiveUnavailable('sideband_unavailable') from None
        if not raw:
            raise LiveUnavailable('sideband_closed')
        if not isinstance(raw, str) or len(raw.encode()) > self.max_event_bytes:
            raise LiveUnavailable('sideband_event_exceeds_bound')
        try:
            value = json.loads(raw)
        except ValueError:
            raise LiveUnavailable('sideband_event_invalid') from None
        if not isinstance(value, dict) or not _text(value.get('type'), 128):
            raise LiveUnavailable('sideband_event_invalid')
        return value  # Source data, never tool-execution authority.

    def send(self, event):
        if (not isinstance(event, dict) or not _text(event.get('type'), 128)
                or event['type'] == 'session.start'):
            raise ValueError('Send a command to the existing Live session')
        raw = json.dumps(event, allow_nan=False, ensure_ascii=False)
        if len(raw.encode()) > self.max_event_bytes:
            raise ValueError('Public Live command exceeds its bound')
        with self._write_lock:
            if self._detached or self._uncertain_write:
                raise LiveUnavailable('sideband_write_unavailable')
            try:
                self._connection.send(raw)
            except Exception:
                self._uncertain_write = True
                raise LiveUnavailable('command_unconfirmed') from None

    def detach(self):
        with self._write_lock:
            if self._detached:
                return
            self._detached = True
            try:
                self._connection.close()
            except Exception:
                pass
