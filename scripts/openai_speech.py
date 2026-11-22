"""Finite OpenAI Realtime text reading for the existing speech renderer.

No microphone, tools, native work, independent cache or automatic retry. The
caller retains the render intent and owns the process deadline and audio budget.
"""
import base64
from contextlib import suppress
import io
import json
import time
from urllib.parse import urlencode
import wave


class SpeechError(Exception):
    pass


def connect(endpoint, model, token, timeout):
    import websocket
    return websocket.create_connection(endpoint+'?'+urlencode({'model':model}),
        header={'Authorization':'Bearer '+token},timeout=min(timeout,10),
        suppress_origin=True,redirect_limit=0)


def render(config, fields, token, max_audio, *, connector=None, progress=None):
    """One source-bound audio response, completed before returning a WAV."""
    started=time.monotonic();deadline=started+config['timeout_seconds']
    socket=(connector or connect)(config['endpoint'],config['model'],token,config['timeout_seconds'])
    pcm=bytearray();seen=set();response=None;item=None;first_audio=None
    transcript_bytes=0
    def send(value):socket.send(json.dumps(value,ensure_ascii=False,separators=(',',':')))
    try:
        send({'type':'session.update','session':fields['session']})
        configured=False
        for _ in range(8192):
            left=deadline-time.monotonic()
            if left<=0:raise SpeechError('speech-deadline')
            socket.settimeout(left)
            raw=socket.recv()
            if not isinstance(raw,str) or len(raw.encode())>1024*1024:
                raise SpeechError('speech-event-bound')
            event=json.loads(raw)
            if not isinstance(event,dict):raise SpeechError('speech-event-shape')
            kind=event.get('type')
            if kind=='error':raise SpeechError('speech-provider-error')
            if kind=='session.updated':
                if configured:raise SpeechError('speech-session-changed')
                session=event.get('session',{});output=session.get('audio',{}).get('output',{})
                if (session.get('model')!=config['model'] or output.get('voice')!=config['voice']
                        or output.get('format')!={'type':'audio/pcm','rate':24000}):
                    raise SpeechError('speech-session-mismatch')
                configured=True
                if progress:progress({'stage':'response_intent','model':config['model']})
                send({'type':'response.create','response':fields['response']})
            elif kind=='response.created':
                value=event.get('response',{})
                if (not configured or response is not None
                        or value.get('metadata')!=fields['response']['metadata']
                        or not isinstance(value.get('id'),str)):
                    raise SpeechError('speech-response-mismatch')
                response=value['id']
                if progress:progress({'stage':'response_created','model':config['model'],'response_id':response})
            elif kind in ('response.output_audio.delta','response.output_audio_transcript.delta'):
                if response is None or event.get('response_id')!=response:
                    raise SpeechError('speech-response-mismatch')
                ident=event.get('event_id')
                if not isinstance(ident,str) or not 1<=len(ident)<=256:
                    raise SpeechError('speech-event-identity')
                if ident in seen:continue
                seen.add(ident)
                if kind=='response.output_audio.delta':
                    if item is None:item=event.get('item_id')
                    if not isinstance(item,str) or event.get('item_id')!=item:
                        raise SpeechError('speech-audio-item-changed')
                    data=base64.b64decode(event['delta'],validate=True)
                    if not data or len(pcm)+len(data)>max_audio-44:
                        raise SpeechError('speech-audio-bound')
                    if first_audio is None:first_audio=int((time.monotonic()-started)*1000)
                    pcm.extend(data)
                else:
                    text=event.get('delta')
                    if not isinstance(text,str):raise SpeechError('speech-transcript-shape')
                    transcript_bytes+=len(text.encode())
                    if transcript_bytes>32768:raise SpeechError('speech-transcript-bound')
            elif kind=='response.done':
                value=event.get('response',{})
                if (response is None or value.get('id')!=response
                        or value.get('status')!='completed' or not pcm or len(pcm)%2):
                    raise SpeechError('speech-response-incomplete')
                usage=value.get('usage')
                if not isinstance(usage,dict) or len(json.dumps(usage).encode())>8192:
                    raise SpeechError('speech-usage-incomplete')
                wav=io.BytesIO()
                with wave.open(wav,'wb') as stream:
                    stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(24000)
                    stream.writeframes(pcm)
                # Provider captions describe generation, never certified word
                # alignment, hardware playback or a human hearing observation.
                receipt={'model':config['model'],'response_id':response,
                    'usage':usage,'first_pcm_millis':first_audio,
                    'generation_millis':int((time.monotonic()-started)*1000),
                    'audio_millis':len(pcm)*1000//48000,
                    'caption_bytes':transcript_bytes,'hearing':'not_observed'}
                if progress:progress({'stage':'response_completed',**receipt})
                return wav.getvalue(),receipt
        raise SpeechError('speech-event-count-bound')
    finally:
        with suppress(Exception):socket.close(timeout=1)
