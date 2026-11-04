"""Explicit OpenAI Realtime API pilot; ChatGPT login is not an API credential.

Shares bounded foreground commands, original commitment and tool scheduling with
Qwen. GA event names and 24kHz input are translated at this provider boundary.
This adapter requires account-level qualification before receiving selection.
"""
from array import array
import base64
import json
import sys

from .qwen_dialogue import QwenDialogue


class Pcm16To24:
    """Causal linear interpolation, preserving phase across PCM frame boundaries."""
    def __init__(self):self.index=-1;self.next=0;self.previous=0
    def feed(self,pcm):
        values=array('h');values.frombytes(pcm)
        if sys.byteorder!='little':values.byteswap()
        out=array('h')
        for current in values:
            self.index+=1
            while self.next<=3*self.index:
                fraction=self.next-3*(self.index-1)
                sample=current if self.index==0 else round((self.previous*(3-fraction)+current*fraction)/3)
                out.append(sample);self.next+=2
            self.previous=current
        if sys.byteorder!='little':out.byteswap()
        return out.tobytes()
    def finish(self):
        # Hold the last sample only through the final sample interval.
        out=array('h')
        while self.index>=0 and self.next<3*(self.index+1):out.append(self.previous);self.next+=2
        if sys.byteorder!='little':out.byteswap()
        return out.tobytes()


class OpenAIDialogue(QwenDialogue):
    endpoint='wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1'
    model='gpt-realtime-2.1'
    commit_source='provider_openai_commit'

    def __init__(self,*args,voice_name=None,**kwargs):
        self._resampler=Pcm16To24();self._openai_calls={}
        super().__init__(*args,voice_name=voice_name or 'cedar',**kwargs)

    def _raw(self,value):
        kind=value['type']
        if kind=='session.update':
            s=value['session']
            value={'type':kind,'session':{'type':'realtime','model':self.model,
                'instructions':s['instructions'],'output_modalities':['audio'],
                'max_output_tokens':512,'tools':s['tools'],'tool_choice':s['tool_choice'],
                'audio':{'input':{'format':{'type':'audio/pcm','rate':24000},
                    'turn_detection':None,'transcription':{'model':'gpt-transcribe'}},
                    'output':{'format':{'type':'audio/pcm','rate':24000},'voice':s['voice']}}}}
        elif kind=='input_audio_buffer.append':
            pcm=base64.b64decode(value['audio'],validate=True)
            value={**value,'audio':base64.b64encode(self._resampler.feed(pcm)).decode()}
        elif kind=='input_audio_buffer.commit':
            tail=self._resampler.finish()
            if tail:super()._raw({'type':'input_audio_buffer.append','audio':base64.b64encode(tail).decode()})
            self._resampler=Pcm16To24()
        super()._raw(value)

    def _events(self,value):
        value=dict(value);kind=value.get('type')
        if kind=='response.output_item.added':
            item=value.get('item',{})
            if item.get('type')=='function_call':
                ident,name=item.get('call_id'),item.get('name')
                if (not isinstance(ident,str) or not ident or len(ident)>256
                        or not isinstance(name,str) or not name or len(name)>128
                        or len(self._openai_calls)>=self.max_tools):raise ValueError('OpenAI tool item exceeds its bound')
                self._openai_calls[ident]=name
        if kind=='response.function_call_arguments.done':
            ident=value.get('call_id')
            if ident not in self._openai_calls:raise ValueError('OpenAI function arguments lack their owned item')
            value['name']=self._openai_calls[ident]
        names={'response.output_audio.delta':'response.audio.delta',
               'response.output_audio_transcript.delta':'response.audio_transcript.delta'}
        value['type']=names.get(kind,kind)
        return super()._events(value)
