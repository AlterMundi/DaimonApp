"""GA schema and streaming PCM phase; no API request or account entitlement claim."""
from array import array
import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.openai_dialogue import OpenAIDialogue, Pcm16To24
from dashboard.native_dialogue import DialogueUnavailable
from dashboard_qwen_dialogue import Socket

class OpenAI(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.key=Path(self.tmp.name)/'key'
        self.key.write_text('synthetic-api-key');self.key.chmod(0o600);self.socket=Socket()
        self.s=OpenAIDialogue(self.key,activity_mode='manual',connect=lambda *a,**k:self.socket)
    def tearDown(self):self.s.close();self.tmp.cleanup()
    def event(self,value):self.socket.received.append(value);return self.s.receive()
    def ready(self):self.event({'type':'session.updated'})
    def test_ga_session_uses_explicit_api_audio_and_tool_contract(self):
        s=self.socket.sent[0]['session'];self.assertEqual(s['type'],'realtime')
        self.assertEqual(s['model'],'gpt-realtime-2.1');self.assertEqual(s['output_modalities'],['audio'])
        self.assertIsNone(s['audio']['input']['turn_detection'])
        self.assertEqual(s['audio']['input']['format'],{'type':'audio/pcm','rate':24000})
        self.assertEqual(s['audio']['input']['transcription']['model'],'gpt-transcribe')
        self.assertEqual(s['audio']['output']['voice'],'cedar')
        self.assertNotIn('max_history_turns',s);self.assertNotIn('modalities',s)
    def test_resampling_preserves_frame_phase_and_duration(self):
        pcm=array('h',range(-800,800)).tobytes()
        whole=Pcm16To24();expected=whole.feed(pcm)+whole.finish()
        split=Pcm16To24();actual=b''.join(split.feed(pcm[i:i+14]) for i in range(0,len(pcm),14))+split.finish()
        self.assertEqual(actual,expected);self.assertEqual(len(actual),4800)
        samples=array('h');samples.frombytes(actual)
        self.assertEqual(samples[0],-800);self.assertEqual(samples[-1],799)
        self.assertEqual(split.finish(),b'')
    def test_commit_correlation_stays_in_original_16khz_coordinates(self):
        self.ready();self.s.activity_start();self.s.append(b'\0\0'*1600);self.s.activity_end()
        chunks=[base64.b64decode(v['audio']) for v in self.socket.sent if v['type']=='input_audio_buffer.append']
        self.assertEqual(sum(map(len,chunks)),4800)
        e=self.event({'type':'input_audio_buffer.committed','item_id':'original1'})[0]
        self.assertEqual(e['source'],'provider_openai_commit');self.assertEqual(e['stream_end'],3200)
    def test_ga_audio_names_and_owned_function_arguments(self):
        self.ready()
        e=self.event({'type':'response.output_audio.delta','delta':base64.b64encode(b'\1\0'*10).decode()})
        self.assertEqual(e[0]['type'],'audio')
        self.event({'type':'response.output_item.added','item':{'type':'function_call','call_id':'c1','name':'session_status'}})
        e=self.event({'type':'response.function_call_arguments.done','call_id':'c1','arguments':'{}'})
        self.assertEqual(e[0]['type'],'session_status_query')
        with self.assertRaises(DialogueUnavailable):self.event({'type':'response.function_call_arguments.done','call_id':'unknown','arguments':'{}'})

if __name__=='__main__':unittest.main()
