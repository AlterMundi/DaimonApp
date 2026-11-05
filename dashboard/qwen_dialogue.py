"""Qwen native speech behind the existing foreground/source ownership contract.

The shared foreground policy and bounded command accounting stay in NativeDialogue.
Only the wire protocol changes. A commit ACK identifies buffered input; it is not
reported as provider acoustic VAD or a provider-reported sample offset.
"""
from collections import deque
import json
import time

from .native_dialogue import NativeDialogue


class _Wire:
    def __init__(self, owner, socket):self.owner,self.socket=owner,socket
    def send(self, value):self.owner._qsend(json.loads(value))
    def recv(self):return self.socket.recv()
    def settimeout(self, value):self.socket.settimeout(value)
    def close(self):self.socket.close()
    def __getattr__(self,name):
        # Preserve actual control frames; recv() otherwise collapses CLOSE to
        # empty JSON and hides the provider-close category from the reader.
        if name=='recv_data':return getattr(self.socket,name)
        raise AttributeError(name)


class QwenDialogue(NativeDialogue):
    endpoint='wss://token-plan.ap-southeast-1.maas.aliyuncs.com/api-ws/v1/realtime?model=qwen-audio-3.0-realtime-plus'
    model='qwen-audio-3.0-realtime-plus'
    commit_source='provider_qwen_commit'
    # Conservative reserve, not a claim about the provider's context capacity.
    max_context_tokens=64000

    def __init__(self, credential_file, *, activity_mode, voice_name=None, context=None,
                 connect=None, clock=time.monotonic, context_pinning=False):
        if activity_mode!='manual' or context_pinning:
            raise ValueError('Qwen pilot requires explicit local acoustic ownership without context pinning')
        self._qsocket=None;self._qgenerating=False;self._qresponse=None
        self._qcancels=deque();self._qcancel_noops=0
        self._qstart=None;self._qcommit=None;self._qitems={};self._qanswered=set();self._qinput_response=False
        self._qdeferred=deque();self._qdeferred_bytes=0
        self._qbase='';self._qvoice=voice_name or 'longanqian'
        original_connect=connect
        if connect is None:
            import websocket
            connect=websocket.create_connection
        def opening(endpoint, *, header, **kwargs):
            # Reuse existing private credential read; never reinterpret ChatGPT auth.
            token=header[0].split(': ',1)[1]
            self._qsocket=connect(self.endpoint,header=['Authorization: Bearer '+token],**kwargs)
            return _Wire(self,self._qsocket)
        super().__init__(credential_file,activity_mode=activity_mode,voice_name=self._qvoice,
            context=context,connect=opening,clock=clock,context_pinning=False)
        self._connect=original_connect
        import websocket
        self._timeouts+=(websocket.WebSocketTimeoutException,)

    @property
    def checkpoint_pressure(self):
        # Use the existing native checkpoint vocabulary; provider names are
        # not pressure reasons accepted by the receiving Store.
        reason=('tokens' if self.context_estimate>=48000 else
            'tools' if self.turns_finished>=40 else
            'lifetime' if self.input_bytes/32000+self.output_bytes/48000>=240 else None)
        if reason is not None:
            return {'reason':reason,'tokens':self.context_estimate,'usage_kind':'conservative'}
        return super().checkpoint_pressure

    @staticmethod
    def _schema(value):
        if isinstance(value,list):return [QwenDialogue._schema(v) for v in value]
        if not isinstance(value,dict):return value
        return {k:(v.lower() if k=='type' and isinstance(v,str) else QwenDialogue._schema(v))
                for k,v in value.items()}

    def _raw(self,value):self._qsocket.send(json.dumps(value,ensure_ascii=False,separators=(',',':')))

    def _create_response(self):
        if self._qgenerating or self.input_active:return
        self._qgenerating=True;self.response_pending=True
        self._raw({'type':'response.create'})

    def _later(self, frames):
        size=len(json.dumps(frames,ensure_ascii=False).encode())
        if len(self._qdeferred)>=64 or self._qdeferred_bytes+size>262144:
            raise ValueError('Qwen deferred controls exceed their bound')
        self._qdeferred.append((frames,size));self._qdeferred_bytes+=size
        self._drain_qwen()

    def _drain_qwen(self):
        if self.input_active or self._qgenerating or self._qcommit is not None:return
        if self._qinput_response:
            self._qinput_response=False;self._create_response();return
        if self._qdeferred:
            frames,size=self._qdeferred.popleft();self._qdeferred_bytes-=size
            for frame in frames:self._raw(frame)
            self._create_response()

    @staticmethod
    def _context_item(text):
        return {'type':'conversation.item.create','item':{'type':'message','role':'user',
            'content':[{'type':'input_text','text':text}]}}

    def _qsend(self,value):
        if 'setup' in value:
            setup=value['setup'];self._qbase='\n\n'.join(p['text'] for p in setup['systemInstruction']['parts'])
            tools=[{'type':'function','name':t['name'],'description':t['description'],
                    'parameters':self._schema(t['parameters'])}
                   for t in setup['tools'][0]['functionDeclarations']]
            self._raw({'type':'session.update','session':{'modalities':['text','audio'],
                'voice':self._qvoice,'instructions':self._qbase,
                'input_audio_format':'pcm','output_audio_format':'pcm',
                'turn_detection':None,'tools':tools,'tool_choice':'auto','max_history_turns':50}})
            return
        if 'realtimeInput' in value:
            data=value['realtimeInput']
            if 'activityStart' in data:
                if self._qstart is not None or self._qcommit is not None:
                    raise ValueError('Qwen input commitment is still pending')
                self._qstart=self.input_bytes
                if self._qgenerating and self._qresponse:
                    self._expire_cancels()
                    if not any(ident==self._qresponse for ident,_ in self._qcancels):
                        if len(self._qcancels)>=8:raise ValueError('Qwen cancel receipts exceed their bound')
                        self._qcancels.append((self._qresponse,self._clock()+10))
                        self._raw({'type':'response.cancel'})
                return
            if 'audio' in data:
                self._raw({'type':'input_audio_buffer.append','audio':data['audio']['data']});return
            if 'activityEnd' in data:
                if self._qstart is None or self.input_bytes<=self._qstart:
                    raise ValueError('Qwen cannot commit empty input')
                self._qcommit=(self._qstart,self.input_bytes);self._qstart=None
                self._raw({'type':'input_audio_buffer.commit'});return
            raise ValueError('Unsupported Qwen realtime control')
        if 'clientContent' in value:
            content=value['clientContent']
            text='\n'.join(p['text'] for t in content['turns'] for p in t['parts'])
            if content['turnComplete']:
                self._later([self._context_item(text)])
            else:self._raw(self._context_item(text))
            return
        if 'toolResponse' in value:
            frames=[]
            for item in value['toolResponse']['functionResponses']:
                ident=item['id'];text=json.dumps(item['response'],ensure_ascii=False)
                if ident not in self._qanswered:
                    self._qanswered.add(ident)
                    frames.append({'type':'conversation.item.create','item':{'type':'function_call_output',
                        'call_id':ident,'output':text}})
                else:
                    # Qwen has one terminal function output per call. Subsequent
                    # source-bound returns are attributed context, never a new call.
                    frames.append(self._context_item(json.dumps({'kind':'internal_integrator_tool_update',
                        'human_speech':False,'call_id':ident,'source_data':True,'result':item['response']},ensure_ascii=False)))
            self._later(frames);return
        raise ValueError('Unsupported Qwen foreground command')

    def _expire_cancels(self):
        now=self._clock()
        while self._qcancels and self._qcancels[0][1]<now:self._qcancels.popleft()

    @property
    def control_diagnostics(self):
        return {'cancel_noops':self._qcancel_noops}

    def _provider_error(self,value):
        self._expire_cancels()
        error=value.get('error')
        if isinstance(error,dict):
            message=error.get('message')
            if (value.get('type')=='error' and error.get('type')=='invalid_request_error'
                    and error.get('code')=='invalid_value' and isinstance(message,str)
                    and len(message)<=512 and 'no active response' in message.lower()
                    and self._qcancels):
                # A response can finish on the server before the local reader
                # processes response.done. Its late cancellation is a no-op,
                # not input failure. Do not clear a newer response/commit, retry
                # the command or replay any original/tool.
                self._qcancels.popleft();self._qcancel_noops+=1
                return []
        self._fail('native-dialogue-qwen-provider-error')

    def _events(self,value):
        kind=value.get('type')
        if not isinstance(kind,str):raise ValueError('Qwen event type unavailable')
        if kind=='session.created':return []
        if kind=='session.updated':
            if self.phase=='opening':return super()._events({'setupComplete':{}})
            return []
        if self.phase!='ready':raise ValueError('Qwen output before readiness')
        mapped={}
        if kind=='input_audio_buffer.committed':
            ident=value.get('item_id')
            if (self._qcommit is None or not isinstance(ident,str) or not ident or len(ident)>256
                    or ident in self._qitems or len(self._qitems)>=128):
                raise ValueError('Qwen input ACK cannot be correlated')
            start,end=self._qcommit;self._qcommit=None;self._qitems[ident]=False
            self._qinput_response=True;self._drain_qwen()
            return [{'type':'input_committed','source':self.commit_source,'item_id':ident,
                     'stream_start':start,'stream_end':end}]
        if kind=='conversation.item.input_audio_transcription.completed':
            ident=value.get('item_id')
            if ident not in self._qitems or self._qitems[ident]:raise ValueError('Qwen transcript is not a new committed original')
            self._qitems[ident]=True
            mapped={'serverContent':{'inputTranscription':{'text':value['transcript'],'finished':True}}}
        elif kind=='response.created':
            response=value.get('response',{});ident=response.get('id')
            if not isinstance(ident,str) or not ident or len(ident)>256:raise ValueError('Invalid Qwen response')
            self._qresponse=ident;self._qgenerating=True
        elif kind=='response.audio.delta':
            mapped={'serverContent':{'modelTurn':{'parts':[{'inlineData':{
                'mimeType':'audio/pcm;rate=24000','data':value['delta']}}]}}}
        elif kind=='response.audio_transcript.delta':
            mapped={'serverContent':{'outputTranscription':{'text':value['delta']}}}
        elif kind=='response.function_call_arguments.done':
            mapped={'toolCall':{'functionCalls':[{'id':value['call_id'],'name':value['name'],
                'args':json.loads(value['arguments'])}]}}
        elif kind=='response.done':
            if value.get('response',{}).get('status') not in ('completed','cancelled'):
                raise ValueError('Qwen response did not complete')
            if value.get('response',{}).get('status')=='cancelled':
                ident=value['response'].get('id',self._qresponse)
                self._qcancels=deque((r,t) for r,t in self._qcancels if r!=ident)
            self._qgenerating=False;self._qresponse=None
            mapped={'serverContent':{'turnComplete':True,**({'interrupted':True}
                if value.get('response',{}).get('status')=='cancelled' else {})}}
        elif kind=='conversation.item.input_audio_transcription.failed':
            raise ValueError('Qwen final input transcription unavailable')
        events=super()._events(mapped) if mapped else []
        self._drain_qwen()
        return events
