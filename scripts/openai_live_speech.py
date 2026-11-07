"""Finite GPT-Live preview reading on one primary WebSocket.

The existing speech renderer owns the durable intent/cache/audio reservation.
Silence is synthetic clocking, not microphone input, a native human original or
execution authority. No Responses backend, tools, fallback or automatic retry.
"""
import base64
from contextlib import suppress
import hashlib
import io
import json
import math
import re
import time
import uuid
import wave


class SpeechError(Exception):
    pass


def connect(endpoint,model,token,timeout):
    import websocket
    return websocket.create_connection(endpoint,header={'Authorization':'Bearer '+token},
        timeout=min(timeout,10),suppress_origin=True,redirect_limit=0)


def normalized(text):
    return ' '.join(re.findall(r'\w+',text.casefold()))


def render(config,fields,token,max_audio,*,connector=None,progress=None,cancel=None,clock=time.monotonic):
    """One<=30second attempt including finalization, with no audio hardware."""
    if cancel is not None and cancel.is_set():raise SpeechError('audition-cancelled-before-connect')
    started=clock();deadline=started+config['timeout_seconds'];generation_end=deadline-5
    socket=(connector or connect)(config['endpoint'],config['model'],token,config['timeout_seconds'])
    pcm=bytearray();transcript='';seen={};session=None;closing=False;failure=None
    first_audio=None;last_audio=None;next_silence=None;closed=False;sent_silence=0;close_deadline=None
    max_pcm=min(max_audio-44,30*48000)
    def send(value):socket.send(json.dumps(value,ensure_ascii=False,separators=(',',':')))
    def report(value):
        if progress:progress(value)
    def close():
        nonlocal closing,close_deadline
        if not closing and session is not None:
            # The event reader is already installed and keeps draining this
            # same socket. Never recreate a connection after an unknown write.
            closing=True;close_deadline=min(deadline,clock()+5);send({'type':'session.close'})
    try:
        send({'type':'session.start','event_id':str(uuid.uuid4()),'session':fields['session']})
        for _ in range(8192):
            now=clock()
            if now>=deadline or closing and now>=close_deadline:raise SpeechError('audition-finalization-unconfirmed')
            if cancel is not None and cancel.is_set():failure=failure or 'audition-cancelled'
            complete=normalized(transcript)==normalized(fields['passage'])
            if session is not None and (failure or now>=generation_end
                    or pcm and complete and now-last_audio>=1):close()
            if session is None and now>=min(generation_end,started+10):
                raise SpeechError('audition-start-unconfirmed')
            if session is not None and not closing and now>=next_silence:
                send({'type':'session.input_audio.append','audio':base64.b64encode(b'\0'*960).decode()})
                sent_silence+=960;next_silence=now+.02
            socket.settimeout(min(.02,max(.001,deadline-clock())))
            try:raw=socket.recv()
            except TimeoutError:continue
            except Exception as error:
                # websocket-client has its own timeout class. Only a timeout
                # is an observation gap; disconnects are never reconnected.
                if type(error).__name__=='WebSocketTimeoutException':continue
                raise SpeechError('audition-connection-unconfirmed') from None
            try:
                if not isinstance(raw,str) or len(raw.encode())>1024*1024:raise ValueError()
                event=json.loads(raw)
                if not isinstance(event,dict):raise ValueError()
                ident=event.get('event_id')
                if not isinstance(ident,str) or not 1<=len(ident)<=1024:raise ValueError()
                digest=hashlib.sha256(raw.encode()).hexdigest()
                if ident in seen:
                    if seen[ident]!=digest:raise ValueError()
                    continue
                seen[ident]=digest;kind=event.get('type')
                if kind=='session.started':
                    actual=event.get('session',{});audio=actual.get('audio',{})
                    if session is not None:raise ValueError()
                    session=actual.get('id')
                    if not isinstance(session,str) or not 1<=len(session)<=1024:raise ValueError()
                    next_silence=clock()
                    if (actual.get('model')!=config['model'] or audio.get('format')!={'type':'audio/pcm','rate':24000}
                            or audio.get('output',{}).get('voice')!=config['voice']):raise ValueError()
                    report({'stage':'session_started','model':config['model'],'session_id':session})
                    if cancel is not None and cancel.is_set():failure=failure or 'audition-cancelled'
                    if failure or clock()>=generation_end:close()
                    else:send({'type':'session.commentary.append','event_id':str(uuid.uuid4()),
                               'delegation_id':None,'content':fields['greeting']})
                elif kind=='session.output_audio.delta':
                    if session is None:raise ValueError()
                    data=base64.b64decode(event['delta'],validate=True)
                    if not data or len(data)%2 or len(pcm)+len(data)>max_pcm:raise ValueError()
                    if first_audio is None:first_audio=int((clock()-started)*1000)
                    pcm.extend(data);last_audio=clock()
                elif kind=='session.output_transcript.delta':
                    text=event.get('delta')
                    if session is None or not isinstance(text,str) or len((transcript+text).encode())>16384:raise ValueError()
                    transcript+=text
                elif kind=='session.closed':
                    if session is None or event.get('session',{}).get('id')!=session:raise ValueError()
                    usage=event.get('usage');seconds=usage.get('seconds') if isinstance(usage,dict) else None
                    if type(seconds) not in (int,float) or not math.isfinite(seconds) or seconds<0 or len(json.dumps(usage).encode())>8192:raise ValueError()
                    if not isinstance(event.get('reason'),str) or len(event['reason'])>128:raise ValueError()
                    closed=True
                    receipt={'model':config['model'],'session_id':session,'usage':usage,'reason':event.get('reason'),
                        'finalized':True,'first_pcm_millis':first_audio,'generation_millis':int((clock()-started)*1000),
                        'audio_millis':len(pcm)*1000//48000,'transcript':transcript,
                        'passage_match':normalized(transcript)==normalized(fields['passage']),
                        'synthetic_silence_bytes':sent_silence,'hearing':'not_observed','live_conversation_latency':'not_measured'}
                    report({'stage':'session_closed',**receipt})
                    if failure:raise SpeechError(failure)
                    if not pcm:raise SpeechError('audition-no-audio')
                    output=io.BytesIO()
                    with wave.open(output,'wb') as wav:
                        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(pcm)
                    return output.getvalue(),receipt
                elif kind in ('error','session.delegation.created'):failure=failure or 'audition-provider-error'
            except SpeechError:raise
            except (ValueError,KeyError,TypeError):failure=failure or 'audition-event-mismatch'
        raise SpeechError('audition-event-count-bound')
    finally:
        if not closed:report({'stage':'transport_released','finalized':False,'session_id':session})
        with suppress(Exception):socket.close(timeout=1)
