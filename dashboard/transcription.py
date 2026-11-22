"""Bounded, transcription-only audio preparation; never conversation admission.

Qwen and Gemini use manual audio activities to emit input transcripts only.
This adapter deliberately has no dialogue, tool, native-input or retry API.
Its partials remain revisable preparation until an owning ingress commits them.
"""
import base64
from array import array
import hashlib
import json
import re
import threading
import sys
import time
from urllib.parse import parse_qsl, urlsplit

from scripts.speech_render import private_bytes


class TranscriptionUnavailable(Exception):
    """A failed stream is not permission to replay its provider operation."""


class TranscriptionStream:
    sample_rate = 16000
    max_audio_bytes = 120 * sample_rate * 2
    max_event_bytes = 65536
    max_text_bytes = 16000

    def __init__(self, endpoint, credential_file, connect=None, provider='qwen', transcription_options=None):
        url = urlsplit(endpoint)
        if provider not in ('qwen', 'gemini', 'openai'):
            raise ValueError('Select a supported transcription provider')
        options = {} if transcription_options is None else transcription_options
        if (not isinstance(options,dict) or set(options)-{'languages','keywords','delay'}
                or provider!='openai' and options
                or 'delay' in options and options['delay'] not in ('minimal','low','medium','high','xhigh')):
            raise ValueError('Select bounded live transcription options')
        for key,limit,pattern in (('languages',8,r'[a-z]{2,3}(?:-[a-z]{2,4})?'),('keywords',32,r'[^<>\r\n]{1,80}')):
            if key in options and (not isinstance(options[key],list) or not 1<=len(options[key])<=limit
                    or any(not isinstance(v,str) or not re.fullmatch(pattern,v) for v in options[key])):
                raise ValueError('Select bounded live transcription hints')
        model = 'gpt-live-transcribe' if provider=='openai' else 'gemini-3.5-transcribe-live' if provider == 'gemini' else dict(parse_qsl(url.query, strict_parsing=True)).get('model')
        if provider=='openai':
            valid=endpoint=='wss://api.openai.com/v1/realtime?intent=transcription'
        elif provider == 'gemini':
            valid = (endpoint == 'wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent')
        else:
            valid = not (url.scheme != 'wss' or not url.hostname or url.username or url.password
                or url.fragment or url.port not in (None, 443)
                or url.path != '/api-ws/v1/realtime'
                or list(parse_qsl(url.query)) != [('model', 'qwen-audio-3.0-realtime-plus')])
        if not valid:
            raise ValueError('Select an exact supported transcription endpoint')
        if provider=='openai':
            from .openai_live import OpenAILive, LiveUnavailable
            try:token=OpenAILive(credential_file)._project_key()
            except LiveUnavailable:raise ValueError('Transcription credential unavailable') from None
        else:
            token = private_bytes(credential_file, 16384).decode().strip()
        if not token or any(c.isspace() for c in token):
            raise ValueError('Transcription credential unavailable')
        self._timeout_errors = (TimeoutError,)
        if connect is None:
            import websocket
            connect = websocket.create_connection
            self._timeout_errors += (websocket.WebSocketTimeoutException,)
        self.model = model
        self.provider = provider
        self.phase = 'opening'
        self.audio_bytes = 0
        self.audio_sha256 = hashlib.sha256()
        self.started_at = time.monotonic()
        self.first_partial_at = None
        self.finalized_at = None
        self.text = ''
        self.item_id = None
        self.revision = 0
        self._lock = threading.RLock()
        self._reader = threading.Lock()
        self._socket = None
        self._resample_count = self._resample_tick = 0
        self._resample_tail = None
        try:
            # No redirects, auto-reconnect, provider trace or secret in arguments.
            credential = 'x-goog-api-key: ' if provider == 'gemini' else 'Authorization: Bearer '
            self._socket = connect(endpoint, header=[credential + token],
                                   timeout=10, redirect_limit=0, enable_multithread=True)
            if hasattr(self._socket,'settimeout'):
                self._socket.settimeout(1)
            if provider=='openai':
                self._send({'type':'session.update','session':{'type':'transcription','audio':{'input':{
                    'format':{'type':'audio/pcm','rate':24000},
                    'transcription':{'model':model,'delay':'low',**options},'turn_detection':None}}}})
            elif provider == 'gemini':
                self._send({'setup': {'model': 'models/' + model,
                    'generationConfig': {'responseModalities': ['TEXT']},
                    'inputAudioTranscription': {'mode': 'VERBATIM', 'languageCodes': []},
                    'realtimeInputConfig': {'automaticActivityDetection': {'disabled': True}}}})
            else:
                self._send({'type': 'session.update', 'session': {
                    'modalities': ['text'], 'input_audio_format': 'pcm',
                    'turn_detection': None}})
        except Exception:
            self._fail('transcription-open-unconfirmed')

    def _send(self, value):
        try:
            self._socket.send(json.dumps(value))
        except Exception:
            self._fail('transcription-send-unconfirmed')

    def _fail(self, reason):
        self.phase = 'failed'
        if self._socket is not None:
            self._socket.close()
        raise TranscriptionUnavailable(reason) from None

    def append(self, pcm):
        """Append mono16kHz PCM16; input order belongs to one stream/socket."""
        with self._lock:
            if (self.phase != 'ready' or not isinstance(pcm, bytes) or not pcm
                    or len(pcm) % 2 or len(pcm) > 32000
                    or self.audio_bytes + len(pcm) > self.max_audio_bytes):
                raise ValueError('Provide bounded PCM only after stream readiness')
            encoded = base64.b64encode(self._openai_pcm(pcm) if self.provider=='openai' else pcm).decode('ascii')
            self._send({'realtimeInput': {'audio': {'data': encoded, 'mimeType': 'audio/pcm;rate=16000'}}}
                       if self.provider == 'gemini' else {'type': 'input_audio_buffer.append', 'audio': encoded})
            self.audio_sha256.update(pcm)
            self.audio_bytes += len(pcm)

    def _openai_pcm(self, pcm):
        """Streaming16->24kHz preview only; original PCM/hash stay unchanged.

        Integer positions and one carried sample make packet boundaries inert.
        The browser's original recorder remains the sole acoustic original.
        """
        samples=array('h');samples.frombytes(pcm)
        if sys.byteorder!='little':samples.byteswap()
        base=self._resample_count
        count=len(samples)
        if self._resample_tail is not None:
            samples.insert(0,self._resample_tail);base-=1
        last=base+len(samples)-1;out=array('h');tick=self._resample_tick
        while tick<=last*3:
            index,fraction=divmod(tick,3);local=index-base
            if fraction and index==last:break
            out.append(samples[local] if not fraction else
                       (samples[local]*(3-fraction)+samples[local+1]*fraction)//3)
            tick+=2
        self._resample_count+=count;self._resample_tick=tick;self._resample_tail=samples[-1]
        if sys.byteorder!='little':out.byteswap()
        return out.tobytes()

    def finish(self):
        """Finalize recognition only. This does not admit a human instruction."""
        with self._lock:
            if self.phase != 'ready' or not self.audio_bytes:
                raise ValueError('Finish one nonempty ready stream')
            self.phase = 'finalizing'
            self._send({'realtimeInput': {'activityEnd': {}}} if self.provider == 'gemini'
                       else {'type': 'input_audio_buffer.commit'})

    def receive(self):
        """Read one provider event; partial text replaces the previous revision."""
        # Serialize dequeue and application together, while audio writes retain
        # their separate lock and can continue during a blocking provider read.
        with self._reader:
            return self._receive()

    def _receive(self):
        if self.phase in ('closed', 'failed', 'completed'):
            raise ValueError('Transcription stream is terminal')
        try:
            raw = self._socket.recv()
            if self.provider == 'gemini' and isinstance(raw, bytes):
                if len(raw) > self.max_event_bytes:
                    self._fail('invalid-transcription-event')
                raw = raw.decode('utf-8')
            if not isinstance(raw, str) or len(raw.encode()) > self.max_event_bytes:
                self._fail('invalid-transcription-event')
            event = json.loads(raw)
            if not isinstance(event, dict):
                self._fail('invalid-transcription-event')
        except self._timeout_errors:
            # Silence is not a disconnection or permission to open a new stream.
            # The owning capture's deadline/auth checks bound the whole session.
            return {'type':'status'}
        except TranscriptionUnavailable:
            raise
        except Exception:
            self._fail('transcription-receive-unconfirmed')
        with self._lock:
            if self.provider == 'gemini':
                return self._gemini_event(event)
            kind = event.get('type')
            if not isinstance(kind, str) or kind == 'error' or kind.startswith('response.'):
                # No unexpected generated answer is allowed onto the voice path.
                self._fail('unexpected-transcription-provider-event')
            if kind == 'session.updated':
                session = event.get('session', {})
                if self.provider=='openai':
                    if not isinstance(session,dict) or not isinstance(session.get('audio'),dict):
                        self._fail('transcription-manual-mode-unconfirmed')
                    audio=session['audio'].get('input',{})
                    if (not isinstance(audio,dict) or not isinstance(audio.get('transcription'),dict)
                            or self.phase!='opening' or session.get('type')!='transcription'
                            or audio.get('format')!={'type':'audio/pcm','rate':24000}
                            or audio.get('transcription',{}).get('model')!=self.model
                            or audio.get('turn_detection') is not None):
                        self._fail('transcription-manual-mode-unconfirmed')
                    self.phase='ready'
                    return {'type':'ready'}
                if (self.phase != 'opening' or not isinstance(session, dict)
                        or session.get('turn_detection') is not None
                        or session.get('model', self.model) != self.model
                        or session.get('modalities', ['text']) != ['text']):
                    self._fail('transcription-manual-mode-unconfirmed')
                # Qwen acknowledges the update but omits turn_detection from
                # its session echo. The explicit null request and updated ACK
                # establish manual mode; reject a contradictory echo/output.
                self.phase = 'ready'
                return {'type': 'ready'}
            prefix = 'conversation.item.input_audio_transcription.'
            if kind.startswith(prefix):
                if self.phase not in ('ready', 'finalizing') or not self.audio_bytes:
                    self._fail('transcription-result-before-audio')
                item = event.get('item_id')
                if not isinstance(item, str) or not item or len(item) > 256:
                    self._fail('transcription-item-unconfirmed')
                if self.item_id is not None and self.item_id != item:
                    self._fail('transcription-item-changed')
                self.item_id = item
                final = kind == prefix + 'completed'
                if final:
                    if self.phase != 'finalizing':
                        self._fail('transcription-final-before-finish')
                    text = event.get('transcript')
                elif kind in (prefix + 'delta', prefix + 'text'):
                    text, stash = (self.text,event.get('delta')) if self.provider=='openai' else (event.get('text', ''),event.get('stash', ''))
                    if not isinstance(text, str) or not isinstance(stash, str):
                        self._fail('invalid-transcription-text')
                    text += stash
                else:
                    self._fail('transcription-failed-or-unknown')
                if not isinstance(text, str) or len(text.encode()) > self.max_text_bytes:
                    self._fail('invalid-transcription-text')
                self.text = text
                self.revision += 1
                now = time.monotonic()
                if self.first_partial_at is None and text:
                    self.first_partial_at = now
                if final:
                    if not text.strip():
                        self._fail('empty-final-transcription')
                    self.phase = 'completed'
                    self.finalized_at = now
                return {'type': 'final' if final else 'partial', 'text': text,
                        'revision': self.revision}
            return {'type': 'status'}

    def _gemini_event(self, event):
        # This is the dedicated transcription model, never a live agent. Keep
        # one manual activity per capture; generated text/audio/tools are errors.
        if (not event or set(event) - {'setupComplete', 'serverContent', 'usageMetadata', 'voiceActivity'}
                or len(set(event) - {'usageMetadata', 'voiceActivity'}) > 1):
            self._fail('unexpected-transcription-provider-event')
        if 'setupComplete' in event:
            if self.phase != 'opening' or not isinstance(event['setupComplete'], dict):
                self._fail('transcription-manual-mode-unconfirmed')
            self._send({'realtimeInput': {'activityStart': {}}})
            self.phase = 'ready'
            return {'type': 'ready'}
        content = event.get('serverContent', {})
        if (not isinstance(content, dict) or any(k in content for k in ('modelTurn', 'outputTranscription'))
                or content.get('interrupted')):
            self._fail('unexpected-transcription-provider-event')
        final = 'inputTranscription' in content
        if not final and 'interimInputTranscription' not in content:
            return {'type': 'status'}
        if (self.phase not in ('ready', 'finalizing') or not self.audio_bytes
                or final and self.phase != 'finalizing'):
            self._fail('transcription-final-before-finish' if final else 'transcription-result-before-audio')
        value = content['inputTranscription' if final else 'interimInputTranscription']
        text = value.get('text') if isinstance(value, dict) else None
        if (not isinstance(text, str) or len(text.encode()) > self.max_text_bytes
                or final and not text.strip()):
            self._fail('invalid-transcription-text')
        self.text = text
        self.revision += 1
        now = time.monotonic()
        if self.first_partial_at is None and text:
            self.first_partial_at = now
        if final:
            self.phase = 'completed'
            self.finalized_at = now
        return {'type': 'final' if final else 'partial', 'text': text, 'revision': self.revision}

    def result(self):
        if self.phase != 'completed':
            raise ValueError('No completed transcription')
        return {'text': self.text, 'final': True, 'model': self.model,
                'pcm_sha256': self.audio_sha256.hexdigest(),
                'audio_millis': self.audio_bytes * 1000 // (2 * self.sample_rate)}

    def close(self):
        with self._lock:
            if self._socket is not None:
                self._socket.close()
            if self.phase not in ('completed', 'failed'):
                self.phase = 'closed'
