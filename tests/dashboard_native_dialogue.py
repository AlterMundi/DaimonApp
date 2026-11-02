"""Native audio/tool concurrency and bounded transport; zero provider/model calls."""
import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.native_dialogue import NativeDialogue, DialogueUnavailable


class Socket:
    def __init__(self):
        self.sent=[]; self.received=[]; self.closed=False; self.fail_send=False
    def settimeout(self, timeout):self.timeout=timeout
    def send(self, value):
        if self.fail_send:raise OSError('private provider detail')
        self.sent.append(json.loads(value))
    def recv(self):
        if not self.received:raise TimeoutError()
        return json.dumps(self.received.pop(0))
    def close(self):self.closed=True


class Dialogue(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.key=Path(self.tmp.name)/'key'
        self.key.write_text('synthetic-secret');self.key.chmod(0o600)
        self.socket=Socket();self.openings=[];self.now=0
        def connect(endpoint, **kwargs):
            self.openings.append((endpoint, kwargs));return self.socket
        self.connect=connect
        self.stream=NativeDialogue(self.key,activity_mode="automatic",connect=connect,clock=lambda:self.now)
        self.original=str(uuid.uuid4())
    def tearDown(self):self.stream.close();self.tmp.cleanup()
    def event(self, value):
        self.socket.received.append(value);return self.stream.receive()
    def ready(self):self.assertEqual(self.event({'setupComplete':{}})[0]['type'],'ready')
    def proposal(self, ident='call-1', **changes):
        return {'toolCall':{'functionCalls':[{'id':ident,'name':'delegate_to_integrator',
                'args':{'request':'Please resolve the refined request.','original_ids':[self.original]},**changes}]}}
    def audio(self, **extra):
        return {'serverContent':{'modelTurn':{'parts':[{'inlineData':{
            'mimeType':'audio/pcm;rate=24000','data':base64.b64encode(b'\1\0'*160).decode()}}]},**extra}}
    def test_internal_attention_is_bounded_control_not_a_human_audio_turn(self):
        self.stream.close();self.socket=Socket()
        self.stream=NativeDialogue(self.key,activity_mode='manual',connect=lambda *a,**k:self.socket,clock=lambda:self.now)
        self.ready()
        self.event({'toolCall':{'functionCalls':[{'id':'watch-existing','name':'await_integrator_update','args':{}}]}})
        self.assertFalse(self.stream.notify_integrator_update(),'An actual pending watch already owns the return')
        self.event({'toolCallCancellation':{'ids':['watch-existing']}})
        self.assertTrue(self.stream.notify_integrator_update())
        control=self.socket.sent[-1]['clientContent'];notice=json.loads(control['turns'][0]['parts'][0]['text'])
        self.assertTrue(control['turnComplete']);self.assertFalse(notice['human_speech'])
        self.assertEqual(notice['speaker'],'foreground_control');self.assertEqual(self.stream.input_bytes,0)
        self.assertFalse(self.stream.notify_integrator_update(),'Do not interrupt the pending provider response')
        self.event({'serverContent':{'turnComplete':True}})
        self.stream.activity_start();self.assertFalse(self.stream.notify_integrator_update())
        self.stream.activity_end();self.assertFalse(self.stream.notify_integrator_update())
        self.event({'serverContent':{'turnComplete':True}})
        self.stream.attention_notices=self.stream.max_attention_notices
        with self.assertRaises(DialogueUnavailable):self.stream.notify_integrator_update()
        self.assertTrue(self.socket.closed)

    def test_automatic_boundaries_gate_internal_returns_without_manual_activity(self):
        self.ready()
        setup=self.socket.sent[0]['setup']
        self.assertNotIn('explicitVadSignal',setup,'Enterprise-only setting is not a Developer API option')
        self.event({'voiceActivity':{'type':'ACTIVITY_START','audioOffset':'1s'}})
        self.assertTrue(self.stream.input_active)
        self.assertFalse(self.stream.notify_integrator_update())
        self.event({'voiceActivity':{'type':'ACTIVITY_END','audioOffset':'2s'}})
        self.assertFalse(self.stream.input_active);self.assertTrue(self.stream.response_pending)
        self.assertFalse(self.stream.notify_integrator_update())
        self.event({'serverContent':{'turnComplete':True}})
        self.assertTrue(self.stream.notify_integrator_update())

    def test_observer_tool_is_read_only_and_foreground_knows_integrator_connection(self):
        setup=self.socket.sent[0]['setup'];tools={v['name']:v for v in setup['tools'][0]['functionDeclarations']}
        self.assertIn('session_status',tools);self.assertEqual(tools['session_status']['behavior'],'NON_BLOCKING')
        self.assertIn('Do not falsely deny this access',setup['systemInstruction']['parts'][0]['text'])
        self.ready()
        self.assertEqual(self.event({'toolCall':{'functionCalls':[{'id':'status','name':'session_status','args':{}}]}}),[{'type':'session_status_query','call_id':'status'}])
        self.assertEqual(self.event({'toolCall':{'functionCalls':[{'id':'bad-status','name':'session_status','args':{'selector':'private'}}]}}),[{'type':'tool_rejected','call_id':'bad-status'}])
        self.assertEqual(self.event(self.audio())[0]['type'],'audio')

    def test_recent_results_tool_only_offers_bounded_read_cursors(self):
        self.ready()
        self.assertEqual(self.event({'toolCall':{'functionCalls':[{'id':'results','name':'recent_results','args':{}}]}}),
            [{'type':'recent_results_query','call_id':'results','delivery':0,'native':0}])
        self.assertEqual(self.event({'toolCall':{'functionCalls':[{'id':'bad-results','name':'recent_results','args':{'before_native':True}}]}}),
            [{'type':'tool_rejected','call_id':'bad-results'}])

    def test_pending_tool_has_bounded_cursor_and_no_work_proposal(self):
        self.ready()
        self.assertEqual(self.event({'toolCall':{'functionCalls':[{'id':'pending','name':'session_pending','args':{'after':41}}]}}),
            [{'type':'session_pending_query','call_id':'pending','after':41}])
        self.assertEqual(self.event({'toolCall':{'functionCalls':[{'id':'invalid-pending','name':'session_pending','args':{'after':True}}]}}),
            [{'type':'tool_rejected','call_id':'invalid-pending'}])

    def test_first_transport_failure_survives_terminal_phase_and_close(self):
        self.ready();self.socket.fail_send=True
        with self.assertRaises(DialogueUnavailable):self.stream.append(b'\0\0')
        self.assertEqual(self.stream.failure_code,'native-dialogue-send-unconfirmed')
        with self.assertRaises(ValueError):self.stream.append(b'\0\0')
        self.stream.close()
        self.assertEqual(self.stream.failure_code,'native-dialogue-send-unconfirmed')

    def test_lost_attention_write_closes_without_retry(self):
        self.stream.close();self.socket=Socket()
        self.stream=NativeDialogue(self.key,activity_mode='manual',connect=lambda *a,**k:self.socket,clock=lambda:self.now)
        self.ready();self.socket.fail_send=True
        with self.assertRaises(DialogueUnavailable):self.stream.notify_integrator_update()
        self.assertEqual(self.stream.attention_notices,1);self.assertTrue(self.socket.closed)
        with self.assertRaises(ValueError):self.stream.notify_integrator_update()
        self.assertEqual(len(self.socket.sent),1,'Only setup was confirmed; no replayed write')

    def test_native_loop_continues_while_tool_pending_then_returns_once(self):
        setup=self.socket.sent[0]['setup']
        self.assertEqual(setup['generationConfig']['responseModalities'],['AUDIO'])
        self.assertEqual(setup['tools'][0]['functionDeclarations'][0]['behavior'],'NON_BLOCKING')
        self.assertEqual(setup['realtimeInputConfig'],{'automaticActivityDetection':{'disabled':False,'startOfSpeechSensitivity':'START_SENSITIVITY_LOW','endOfSpeechSensitivity':'END_SENSITIVITY_HIGH','prefixPaddingMs':300,'silenceDurationMs':700}},'Explicit native detection rather than the old detector/final-ASR gate')
        self.assertEqual(self.openings[0][1]['redirect_limit'],0)
        self.ready();self.stream.append(b'\0\0'*320)
        proposal=self.event(self.proposal())[0]
        self.assertEqual(proposal['original_ids'],[self.original]);self.assertEqual(proposal['type'],'delegation_proposed')
        audio=self.event(self.audio())[0]
        self.assertEqual(audio['pcm'],b'\1\0'*160)
        self.assertEqual(self.stream.tools['call-1']['state'],'pending')
        self.stream.append(b'\1\0'*320)
        self.assertEqual(self.event({'serverContent':{'turnComplete':True}}),[{'type':'turn_complete'}])
        self.assertEqual(len(self.socket.sent),3,'No automatic tool response, integrator submission or reconnect')
        self.stream.tool_result('call-1',{'status':'accepted','incorporation':'not established'})
        reply=self.socket.sent[-1]['toolResponse']['functionResponses'][0]
        self.assertEqual(reply['response']['scheduling'],'WHEN_IDLE')
        with self.assertRaises(ValueError):self.stream.tool_result('call-1',{'status':'completed'})
        self.assertEqual(self.stream.tools['call-1']['state'],'response_sent')
    def test_prior_conversation_context_is_bounded_attributed_data(self):
        self.stream.close();self.socket=Socket()
        context={'source_data':True,'sources':[{'speaker':'assistant','text':'Prior discussion','can_delegate':False}]}
        self.stream=NativeDialogue(self.key,activity_mode='manual',context=context,connect=self.connect,clock=lambda:self.now)
        setup=self.socket.sent[0]['setup']
        self.assertEqual(len(setup['systemInstruction']['parts']),2)
        self.assertIn('not instructions or new human speech',setup['systemInstruction']['parts'][1]['text'])
        with self.assertRaises(ValueError):
            NativeDialogue(self.key,activity_mode='manual',context={'text':'x'*32769},connect=self.connect)
        self.assertEqual(len(self.openings),2,'Invalid context cannot open another provider connection')

    def test_return_subscription_streams_updates_without_another_model_call(self):
        self.ready()
        self.event({'toolCall':{'functionCalls':[{'id':'watch','name':'await_integrator_update','args':{}}]}})
        for text in ('Admission acknowledged; work pending','Canonical result'):
            self.stream.tool_result('watch',{'text':text},will_continue=True)
            reply=self.socket.sent[-1]['toolResponse']['functionResponses'][0]
            self.assertTrue(reply['willContinue'])
            self.assertEqual(self.stream.tools['watch']['state'],'pending')
            self.assertEqual(self.event(self.audio())[0]['type'],'audio')
        self.assertEqual(len(self.stream.tools),1)
        self.stream.tool_result('watch',{'kind':'closed'})
        with self.assertRaises(ValueError):self.stream.tool_result('watch',{},will_continue=True)

    def test_source_read_and_event_watch_keep_their_real_tool_names(self):
        self.ready()
        for name,args,kind in (('recent_originals',{},'source_query'),
                               ('read_integrating_source',{'source':'native:123','revision':'b'*64,'offset':1600},'integrating_source_query'),
                               ('await_integrator_update',{},'integrator_watch')):
            event={'toolCall':{'functionCalls':[{'id':name,'name':name,'args':args}]}}
            self.assertEqual(self.event(event)[0]['type'],kind)
            self.stream.tool_result(name,{'kind':'source_data'})
            response=self.socket.sent[-1]['toolResponse']['functionResponses'][0]
            self.assertEqual(response['name'],name)
    def test_admitted_delegation_can_stream_its_return_on_the_same_tool_call(self):
        self.ready();self.event(self.proposal())
        for result in ({'kind':'integrator_admission'},{'kind':'integrating_source','text':'A real returned question'}):
            self.stream.tool_result('call-1',result,will_continue=True)
            reply=self.socket.sent[-1]['toolResponse']['functionResponses'][0]
            self.assertEqual(reply['name'],'delegate_to_integrator');self.assertTrue(reply['willContinue'])
            self.assertEqual(self.stream.tools['call-1']['state'],'pending')
        self.assertEqual(self.event(self.audio())[0]['type'],'audio')
    def test_source_cursor_rejects_boolean_and_out_of_range(self):
        self.ready()
        self.assertEqual(self.event({'toolCall':{'functionCalls':[{'id':'read','name':'recent_originals','args':{'before':True}}]}}),[{'type':'tool_rejected','call_id':'read'}])

    def test_stopped_microphone_is_signalled_without_closing_or_reconnecting(self):
        self.ready();self.stream.append(b'\0\0');self.stream.end_input()
        self.assertEqual(self.socket.sent[-1],{'realtimeInput':{'audioStreamEnd':True}})
        self.stream.append(b'\1\0')
        self.assertEqual(self.stream.phase,'ready');self.assertEqual(len(self.openings),1)
    def test_manual_native_audio_requires_owned_acoustic_boundaries(self):
        self.stream.close();self.socket=Socket()
        self.stream=NativeDialogue(self.key,activity_mode='manual',connect=self.connect,clock=lambda:self.now)
        self.assertEqual(self.socket.sent[-1]['setup']['realtimeInputConfig'],
                         {'automaticActivityDetection':{'disabled':True}})
        self.ready()
        with self.assertRaises(ValueError):self.stream.append(b'\0\0')
        self.stream.activity_start();self.stream.append(b'\1\0')
        with self.assertRaises(ValueError):self.stream.activity_start()
        self.stream.activity_end()
        self.assertEqual(self.socket.sent[-1],{'realtimeInput':{'activityEnd':{}}})
        with self.assertRaises(ValueError):self.stream.activity_end()
        activity=self.event({'voiceActivity':{'type':'ACTIVITY_END','audioOffset':'1s'}})[0]
        self.assertEqual(activity['source'],'provider_manual_activity_ack')
        self.stream.activity_start();self.stream.end_input()
        self.assertFalse(self.stream.input_active)
        count=len(self.socket.sent);self.stream.end_input();self.assertEqual(len(self.socket.sent),count)
    def test_native_activity_is_exposed_with_its_audio_offset(self):
        self.ready()
        self.assertEqual(self.event({'voiceActivity':{'type':'ACTIVITY_END','audioOffset':'2.25s'}}),
                         [{'type':'voice_activity','activity':'ACTIVITY_END','audio_offset':'2.25s','source':'provider_automatic_activity'}])
        self.assertEqual(len(self.socket.sent),1)
    def test_transcripts_are_not_final_original_or_implicit_admission(self):
        self.ready()
        items=self.event({'serverContent':{'interimInputTranscription':{'text':'A draft'},
            'inputTranscription':{'text':'Exact provider text','startOffset':'1s','endOffset':'2s'},
            'outputTranscription':{'text':'A response'},'turnComplete':True}})
        self.assertEqual([i['type'] for i in items],['input_caption','input_transcript','output_transcript','turn_complete'])
        self.assertEqual(items[1]['end_offset'],'2s');self.assertNotIn('final',items[1])
        self.assertEqual(len(self.socket.sent),1)
    def test_explicit_transcription_fragments_and_textless_end_marker_survive_transport(self):
        self.ready()
        partial=self.event({'serverContent':{'inputTranscription':{'text':'First part ','finished':False}}})[0]
        self.assertEqual(partial['text'],'First part ');self.assertIs(partial['finished'],False)
        final=self.event({'serverContent':{'inputTranscription':{'finished':True}}})[0]
        self.assertEqual(final['type'],'input_transcript');self.assertEqual(final['text'],'');self.assertIs(final['finished'],True)
        self.assertEqual(self.event({'serverContent':{'outputTranscription':{'finished':True}}}),[])
        self.assertEqual(self.stream.tools,{})
        self.assertEqual(len(self.socket.sent),1)
    def test_empty_optional_transcriptions_do_not_drop_coincident_audio(self):
        self.ready()
        events=self.event(self.audio(inputTranscription={},outputTranscription={}))
        self.assertEqual([item['type'] for item in events],['audio'])
        self.assertEqual(events[0]['pcm'],b'\1\0'*160)
        self.assertEqual(self.event({'serverContent':{'inputTranscription':{'text':''}}}),[])
    def test_interruption_drops_same_event_audio_and_does_not_cancel_work(self):
        self.ready();self.event(self.proposal())
        items=self.event(self.audio(interrupted=True))
        self.assertEqual(items,[{'type':'interrupted'}])
        self.assertEqual(self.stream.tools['call-1']['state'],'pending')
        items=self.event({'toolCallCancellation':{'ids':['call-1']}})
        self.assertEqual(items,[{'type':'proposal_cancelled','call_id':'call-1','native_work_cancelled':False}])
        with self.assertRaises(ValueError):self.stream.tool_result('call-1',{'status':'accepted'})
        self.assertEqual(len(self.socket.sent),1)
    def test_uncertain_result_send_is_terminal_without_retry_or_secret(self):
        self.ready();self.event(self.proposal());self.socket.fail_send=True
        with self.assertRaisesRegex(DialogueUnavailable,'^native-dialogue-send-unconfirmed$'):
            self.stream.tool_result('call-1',{'status':'accepted'})
        self.assertEqual(self.stream.tools['call-1']['state'],'response_unconfirmed')
        self.assertTrue(self.socket.closed);self.assertEqual(len(self.openings),1)
    def test_invalid_or_repeated_tool_is_not_replayed(self):
        self.ready();self.event(self.proposal())
        with self.assertRaises(DialogueUnavailable):self.event(self.proposal())
        self.assertEqual(len(self.socket.sent),1);self.assertEqual(len(self.openings),1)
    def test_work_proposals_reject_extra_tools(self):
        self.ready()
        self.assertEqual(self.event(self.proposal(name='run_shell')),[{'type':'tool_rejected','call_id':'call-1'}])
        self.stream.tool_result('call-1',{'kind':'invalid_arguments','operation_started':False})
        self.assertEqual(self.stream.phase,'ready')
    def test_input_frames_and_total_input_are_bounded(self):
        self.ready()
        for frame in (b'',b'\0',b'\0'*32002):
            with self.assertRaises(ValueError):self.stream.append(frame)
        self.stream.max_input_bytes=2;self.stream.append(b'\0\0')
        with self.assertRaisesRegex(DialogueUnavailable,'input-bound'):self.stream.append(b'\0\0')
        self.assertEqual(len(self.openings),1)
    def test_invalid_source_reference_does_not_become_work(self):
        self.ready();proposal=self.proposal()
        proposal['toolCall']['functionCalls'][0]['args']['original_ids']=['invented source']
        self.assertEqual(self.event(proposal),[{'type':'tool_rejected','call_id':'call-1'}])
        self.assertEqual(self.stream.phase,'ready')
    def test_event_and_text_bounds_close_without_retry(self):
        self.ready();self.stream.max_text_bytes=2
        with self.assertRaisesRegex(DialogueUnavailable,'text-bound'):
            self.event({'serverContent':{'inputTranscription':{'text':'too long'}}})
        self.assertTrue(self.socket.closed)
    def test_event_count_bound_closes_without_retry(self):
        self.ready();self.stream.max_events=1
        with self.assertRaisesRegex(DialogueUnavailable,'event-bound'):self.event({'usageMetadata':{}})
        self.assertTrue(self.socket.closed)
    def test_output_limit_closes_before_audio_escapes(self):
        self.ready();self.stream.max_output_bytes=2
        with self.assertRaisesRegex(DialogueUnavailable,'output-bound'):self.event(self.audio())
        self.assertTrue(self.socket.closed)
    def test_silence_does_not_reconnect_and_session_expiry_closes(self):
        self.ready();self.assertEqual(self.stream.receive(),[])
        self.now=300
        with self.assertRaisesRegex(DialogueUnavailable,'session-bound'):self.stream.receive()
        self.assertTrue(self.socket.closed);self.assertEqual(len(self.openings),1)
    def test_integrating_source_offset_cannot_be_a_boolean(self):
        self.ready()
        events=self.event({'toolCall':{'functionCalls':[{'id':'read','name':'read_integrating_source',
            'args':{'source':'native:123','revision':'b'*64,'offset':True}}]}})
        self.assertEqual(events,[{'type':'tool_rejected','call_id':'read'}])
        self.assertEqual(self.stream.phase,'ready')

    def test_invalid_media_failure_names_validation_stage_without_payload(self):
        self.ready()
        with self.assertRaisesRegex(DialogueUnavailable,'invalid-provider-event-audio'):
            self.event({'serverContent':{'modelTurn':{'parts':[{'inlineData':{'mimeType':'private'}}]}}})
        self.assertEqual(self.stream.failure_code,'native-dialogue-invalid-provider-event-audio')

    def test_pending_tool_cap_does_not_block_conversation_before_limit(self):
        self.ready()
        for n in range(4):self.event(self.proposal(str(n)))
        self.assertEqual(self.event(self.audio())[0]['type'],'audio')
        with self.assertRaises(DialogueUnavailable):self.event(self.proposal('overflow'))
        self.assertEqual(len(self.stream.tools),4)


if __name__=='__main__':unittest.main()
