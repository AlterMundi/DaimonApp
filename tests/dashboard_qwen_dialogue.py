"""Qwen wire ownership: exact commits, asynchronous returns and barge-in."""
import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.qwen_dialogue import QwenDialogue
from dashboard.native_dialogue import DialogueUnavailable

class Socket:
    def __init__(self):self.sent=[];self.received=[];self.closed=False
    def send(self,v):self.sent.append(json.loads(v))
    def recv(self):
        if not self.received:raise TimeoutError()
        return json.dumps(self.received.pop(0))
    def settimeout(self,v):pass
    def close(self):self.closed=True

class Qwen(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.key=Path(self.tmp.name)/'key'
        self.key.write_text('synthetic');self.key.chmod(0o600);self.socket=Socket();self.opens=[]
        def connect(endpoint,**kw):self.opens.append((endpoint,kw));return self.socket
        self.stream=QwenDialogue(self.key,activity_mode='manual',connect=connect)
    def tearDown(self):self.stream.close();self.tmp.cleanup()
    def event(self,value):self.socket.received.append(value);return self.stream.receive()
    def ready(self):
        self.assertEqual(self.event({'type':'session.created'}),[])
        self.assertEqual(self.event({'type':'session.updated'})[0]['type'],'ready')
    def phrase(self):
        self.stream.activity_start();self.stream.append(b'\0\0'*1600);self.stream.activity_end()
    def test_private_auth_shared_policy_and_explicit_local_endpointing(self):
        self.assertEqual(self.opens[0][1]['header'],['Authorization: Bearer synthetic'])
        s=self.socket.sent[0]['session'];self.assertIsNone(s['turn_detection'])
        self.assertIn('same being',s['instructions']);self.assertEqual(s['voice'],'longanqian')
        self.assertIn('delegate_to_integrator',[t['name'] for t in s['tools']])
        self.assertTrue(all(t['parameters']['type']=='object' for t in s['tools']))
    def test_commit_ack_is_not_synthetic_vad_and_transcript_is_exact_once(self):
        self.ready();self.phrase();self.assertEqual(self.socket.sent[-1]['type'],'input_audio_buffer.commit')
        events=self.event({'type':'input_audio_buffer.committed','item_id':'item1'})
        self.assertEqual(events,[{'type':'input_committed','source':'provider_qwen_commit','item_id':'item1','stream_start':0,'stream_end':3200}])
        self.assertEqual(self.socket.sent[-1]['type'],'response.create')
        e=self.event({'type':'conversation.item.input_audio_transcription.completed','item_id':'item1','transcript':'Corrección: diecinueve.'})
        self.assertEqual(e[0]['text'],'Corrección: diecinueve.');self.assertTrue(e[0]['finished'])
        with self.assertRaises(DialogueUnavailable):self.event({'type':'conversation.item.input_audio_transcription.completed','item_id':'item1','transcript':'duplicate'})
    def test_uncorrelated_commit_and_transcript_refuse(self):
        self.ready()
        with self.assertRaises(DialogueUnavailable):self.event({'type':'input_audio_buffer.committed','item_id':'unknown'})
    def test_tool_return_waits_for_output_and_streamed_updates_are_context(self):
        self.ready();self.event({'type':'response.created','response':{'id':'r1'}})
        proposal=self.event({'type':'response.function_call_arguments.done','call_id':'call1','name':'await_integrator_update','arguments':'{}'})
        self.assertEqual(proposal[0]['type'],'integrator_watch')
        count=len(self.socket.sent);self.stream.tool_result('call1',{'status':'waiting'},will_continue=True)
        self.assertEqual(len(self.socket.sent),count)
        self.event({'type':'response.done','response':{'status':'completed'}})
        self.assertEqual(self.socket.sent[-2]['item']['type'],'function_call_output')
        self.event({'type':'response.done','response':{'status':'completed'}})
        self.stream.tool_result('call1',{'status':'ready'},will_continue=False)
        packet=json.loads(self.socket.sent[-2]['item']['content'][0]['text'])
        self.assertEqual(packet['kind'],'internal_integrator_tool_update');self.assertFalse(packet['human_speech'])
    def test_interruption_cancels_generation_without_cancelling_owned_tools(self):
        self.ready();self.event({'type':'response.created','response':{'id':'r1'}})
        self.event({'type':'response.function_call_arguments.done','call_id':'call1','name':'session_status','arguments':'{}'})
        self.stream.activity_start();self.assertEqual(self.socket.sent[-1],{'type':'response.cancel'})
        self.assertEqual(self.stream.tools['call1']['state'],'pending')
        self.stream.append(b'\0\0'*1000);self.stream.activity_end()
        self.event({'type':'input_audio_buffer.committed','item_id':'item1'})
        before=len([x for x in self.socket.sent if x['type']=='response.create'])
        cancelled=self.event({'type':'response.done','response':{'status':'cancelled'}})
        self.assertIn('interrupted',[e['type'] for e in cancelled])
        self.assertEqual(len([x for x in self.socket.sent if x['type']=='response.create']),before+1)
    def test_successor_preserves_provider_voice_and_conservative_pressure(self):
        self.ready();successor=Socket();successor.received=[{'type':'session.created'},{'type':'session.updated'}]
        self.stream._connect=lambda *args,**kwargs:successor
        basis={'revision':'a'*64,'through':0,'content':{'kind':'internal_integrator_checkpoint',
            'checkpoint':{'text':'Synthetic semantic continuity.'}}}
        candidate=self.stream.successor(basis)
        self.assertEqual(candidate.model,self.stream.model)
        self.assertEqual(successor.sent[0]['session']['voice'],'longanqian')
        self.assertIn('Synthetic semantic continuity.',successor.sent[0]['session']['instructions'])
        self.stream.context_estimate=48000
        self.assertEqual(self.stream.checkpoint_pressure['reason'],'qwen_context')
        candidate.close()

    def test_incomplete_response_requires_review_instead_of_silent_completion(self):
        self.ready()
        with self.assertRaises(DialogueUnavailable):self.event({'type':'response.done','response':{'status':'incomplete'}})

    def test_audio_is_validated_by_existing_normalizer(self):
        self.ready();e=self.event({'type':'response.audio.delta','delta':base64.b64encode(b'\1\0'*10).decode()})
        self.assertEqual(e[0]['pcm'],b'\1\0'*10);self.assertEqual(e[0]['sample_rate'],24000)
    def test_unknown_original_and_automatic_mode_refuse(self):
        self.ready()
        with self.assertRaises(DialogueUnavailable):self.event({'type':'conversation.item.input_audio_transcription.completed','item_id':'unknown','transcript':'text'})
        with self.assertRaises(ValueError):QwenDialogue(self.key,activity_mode='automatic')

if __name__=='__main__':unittest.main()
