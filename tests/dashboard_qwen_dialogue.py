"""Qwen wire ownership: exact commits, asynchronous returns and barge-in."""
import base64
from collections import deque
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
    def test_pressure_tool_settles_and_reaches_handover_without_replay(self):
        self.ready();self.event({'type':'response.created','response':{'id':'pressure'}})
        self.event({'type':'response.function_call_arguments.done','call_id':'sources','name':'recent_originals','arguments':'{}'})
        self.stream.context_estimate=55940
        self.assertTrue(self.stream.rollover_due)
        result={'kind':'sources','text':'Exact retained human correction'}
        self.stream.tool_result('sources',result)
        # The provider is still producing its function-call response: defer the
        # one result, then let both responses finish before physical renewal.
        self.assertFalse(self.stream.handover_ready())
        self.event({'type':'response.done','response':{'status':'completed'}})
        frames=[f for f in self.socket.sent if f.get('item',{}).get('type')=='function_call_output']
        self.assertEqual(len(frames),1)
        self.assertEqual(json.loads(frames[0]['item']['output'])['result'],result)
        self.event({'type':'response.created','response':{'id':'settled'}})
        self.event({'type':'response.done','response':{'status':'completed'}})
        self.assertTrue(self.stream.handover_ready())
        self.assertFalse(self.socket.closed)
        self.assertLess(self.stream.context_estimate,64000-512)

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
        self.assertEqual(self.stream.checkpoint_pressure['reason'],'tokens')
        self.stream.context_estimate=1000;self.stream.turns_finished=40
        self.assertEqual(self.stream.checkpoint_pressure['reason'],'tools')
        self.stream.turns_finished=0;self.stream.input_bytes=240*32000
        self.assertEqual(self.stream.checkpoint_pressure['reason'],'lifetime')
        candidate.close()

    def test_incomplete_response_requires_review_instead_of_silent_completion(self):
        self.ready()
        with self.assertRaises(DialogueUnavailable):self.event({'type':'response.done','response':{'status':'incomplete'}})

    def cancel_error(self,**updates):
        return {'type':'error','error':{'type':'invalid_request_error','code':'invalid_value',
                'message':'No active response',**updates}}

    def test_late_cancel_noop_preserves_new_input_generation_and_owned_tools(self):
        self.ready();self.event({'type':'response.created','response':{'id':'old'}})
        self.event({'type':'response.function_call_arguments.done','call_id':'owned','name':'session_status','arguments':'{}'})
        self.stream.activity_start();self.stream.append(b'\0\0'*1600);self.stream.activity_end()
        self.event({'type':'input_audio_buffer.committed','item_id':'next'})
        self.event({'type':'response.done','response':{'status':'completed'}})
        self.event({'type':'response.created','response':{'id':'new'}})
        before=len(self.socket.sent)
        self.assertEqual(self.event(self.cancel_error()),[])
        self.assertEqual(self.stream.phase,'ready');self.assertIsNone(self.stream.failure_code)
        self.assertEqual(self.stream._qresponse,'new');self.assertTrue(self.stream._qgenerating)
        self.assertEqual(self.stream.tools['owned']['state'],'pending')
        self.assertEqual(len(self.socket.sent),before,'No command, original or work replay')
        self.assertEqual(self.stream.control_diagnostics,{'cancel_noops':1})
        self.event({'type':'conversation.item.input_audio_transcription.completed','item_id':'next','transcript':'Exact next phrase.'})
        self.assertEqual(self.event({'type':'response.audio.delta','delta':base64.b64encode(b'\1\0'*10).decode()})[0]['type'],'audio')
        with self.assertRaises(DialogueUnavailable):self.event(self.cancel_error())

    def test_unrequested_expired_and_other_provider_errors_are_not_ignored(self):
        self.ready()
        with self.assertRaises(DialogueUnavailable):self.event(self.cancel_error())
        self.assertEqual(self.stream.failure_code,'native-dialogue-qwen-provider-error')
        for expired,error in [(True,self.cancel_error()),(False,self.cancel_error(code='other'))]:
            with self.subTest(expired=expired):
                socket=Socket();stream=QwenDialogue(self.key,activity_mode='manual',connect=lambda *a,**k:socket)
                socket.received=[{'type':'session.updated'}];stream.receive()
                stream._qcancels=deque([('old',stream._clock()+(-1 if expired else 10))])
                socket.received=[error]
                with self.assertRaises(DialogueUnavailable):stream.receive()
                stream.close()

    def test_multiple_pending_cancel_noops_do_not_consume_new_input_or_replay(self):
        self.ready()
        for n in range(2):
            self.event({'type':'response.created','response':{'id':f'r{n}'}})
            self.phrase()
            self.event({'type':'input_audio_buffer.committed','item_id':f'input{n}'})
            self.event({'type':'conversation.item.input_audio_transcription.completed','item_id':f'input{n}','transcript':f'Phrase {n}'})
            self.event({'type':'response.done','response':{'id':f'r{n}','status':'completed'}})
        self.assertEqual(len(self.stream._qcancels),2)
        sent=len(self.socket.sent)
        self.assertEqual(self.event(self.cancel_error()),[])
        self.assertEqual(self.event(self.cancel_error()),[])
        self.assertEqual(self.stream.control_diagnostics['cancel_noops'],2)
        self.assertEqual(len(self.socket.sent),sent)
        self.assertEqual(self.stream.phase,'ready')

    def test_qwen_wrapper_preserves_actual_websocket_close_frames(self):
        self.ready()
        self.socket.recv_data=lambda **kwargs:(8,b'\x03\xf3Billing unavailable')
        with self.assertRaises(DialogueUnavailable):self.stream.receive()
        self.assertEqual(self.stream.failure_code,'native-dialogue-provider-billing')

    def test_audio_is_validated_by_existing_normalizer(self):
        self.ready();e=self.event({'type':'response.audio.delta','delta':base64.b64encode(b'\1\0'*10).decode()})
        self.assertEqual(e[0]['pcm'],b'\1\0'*10);self.assertEqual(e[0]['sample_rate'],24000)
    def test_unknown_original_and_automatic_mode_refuse(self):
        self.ready()
        with self.assertRaises(DialogueUnavailable):self.event({'type':'conversation.item.input_audio_transcription.completed','item_id':'unknown','transcript':'text'})
        with self.assertRaises(ValueError):QwenDialogue(self.key,activity_mode='automatic')

if __name__=='__main__':unittest.main()
