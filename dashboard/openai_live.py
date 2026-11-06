"""Public GPT-Live WebRTC creation, separate from Codex and Realtime.

Unselected transport primitive: its owner must authorize and durably record one
creation intent before calling. No browser route, default change, credential
discovery, source replay or automatic retry is installed here. Media travels on
WebRTC tracks; native/backing work keeps its existing independent owner.
"""
from dataclasses import dataclass, field
import json
import re
import threading

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
                 backend_tools=(), client_delegation=False):
    """Owner-selected session configuration; never accept this from a browser.

    Responses is the initial public comparison. Client delegation is explicit
    for existing execution owners; it does not create an application turn loop.
    Backend tools remain backend tools, independent of the voice frontend.
    """
    if not _text(instructions, 8192) or type(client_delegation) is not bool:
        raise ValueError('Select bounded owner voice instructions')
    if client_delegation:
        if backend_model is not None or backend_instructions is not None or backend_tools:
            raise ValueError('Client delegation retains its existing backend configuration')
        delegation = {'type': 'client'}
    else:
        if (not isinstance(backend_model, str)
                or not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', backend_model)
                or not _text(backend_instructions, 8192)
                or not isinstance(backend_tools, (list, tuple)) or len(backend_tools) > 8
                or any(not isinstance(tool, dict) or not isinstance(tool.get('type'), str)
                       for tool in backend_tools)):
            raise ValueError('Select the owner Responses backend and tools')
        delegation = {'type': 'responses', 'responses': {
            'model': backend_model, 'instructions': backend_instructions,
            'tools': list(backend_tools)}}
    # Freeze the owner's input, reject non-JSON/nonfinite values and bound tools.
    raw = json.dumps({'model': 'gpt-live-1', 'instructions': instructions,
                      'delegation': delegation}, allow_nan=False, ensure_ascii=False)
    if len(raw.encode()) > 32768:
        raise ValueError('Public Live session configuration exceeds its bound')
    return json.loads(raw)


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

    def create(self, sdp, spec):
        if not _text(sdp, 65536) or not sdp.startswith('v=0'):
            raise ValueError('Select a bounded WebRTC offer')
        if not isinstance(spec, dict) or set(spec) != {'model', 'instructions', 'delegation'}:
            raise ValueError('Select an owner Live session specification')
        delegation = spec['delegation']
        if not isinstance(delegation, dict):
            raise ValueError('Select a Live delegation mode')
        if delegation.get('type') == 'client' and set(delegation) == {'type'}:
            frozen = session_spec(spec['instructions'], client_delegation=True)
        elif delegation.get('type') == 'responses' and set(delegation) == {'type', 'responses'}:
            backend = delegation['responses']
            if not isinstance(backend, dict) or set(backend) != {'model', 'instructions', 'tools'}:
                raise ValueError('Select a Responses delegation specification')
            frozen = session_spec(spec['instructions'], backend_model=backend['model'],
                backend_instructions=backend['instructions'], backend_tools=backend['tools'])
        else:
            raise ValueError('Select a Live delegation mode')
        if frozen != spec:
            raise ValueError('Select the requested GPT-Live model without overrides')
        try:
            key = private_bytes(self._api_key_file, 16384).decode().strip()
        except (OSError, UnicodeError, RenderError):
            raise LiveUnavailable('project_key_unavailable') from None
        if not re.fullmatch(r'sk-[A-Za-z0-9_-]{16,512}', key):
            raise LiveUnavailable('project_key_unavailable')
        with self._guard:
            if self._attempted:
                raise LiveUnavailable('creation_already_attempted')
            self._attempted = True
        payload = {'session': frozen, 'transport': {'type': 'webrtc', 'sdp': sdp}}
        try:
            with httpx.Client(transport=self._transport, follow_redirects=False,
                              timeout=httpx.Timeout(20, connect=5, write=10, pool=5)) as client:
                with client.stream('POST', self.endpoint,
                        headers={'Authorization': 'Bearer ' + key}, json=payload) as response:
                    if response.status_code != 201:
                        outcome = ('creation_rejected' if 400 <= response.status_code < 500
                                   and response.status_code != 408 else 'creation_unconfirmed')
                        raise LiveUnavailable(outcome, status=response.status_code)
                    body = bytearray()
                    for chunk in response.iter_bytes(chunk_size=16384):
                        if len(body) + len(chunk) > self.max_response_bytes:
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
