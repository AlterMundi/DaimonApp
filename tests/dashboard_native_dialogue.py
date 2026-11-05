"""Native audio/tool concurrency and bounded transport; zero provider/model calls."""
import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.native_dialogue import NativeDialogue, DialogueUnavailable, DialogueCapacity


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
    def test_requested_tool_can_settle_in_reserved_context_margin(self):
        self.ready()
        self.stream.max_context_tokens=64000
        self.stream.context_estimate=55940
        self.stream.tools['settle']={'name':'recent_originals','state':'pending'}
        self.stream.tool_result('settle',{'kind':'sources','text':'retained exact source'})
        self.assertEqual(self.stream.phase,'ready')
        self.assertFalse(self.socket.closed)
        self.assertEqual(self.stream.tools['settle']['state'],'response_sent')
        self.assertLess(self.stream.context_estimate,64000-512)
        # Settling a requested operation does not reopen the input margin.
        before=len(self.socket.sent)
        with self.assertRaises(DialogueCapacity):self.stream.append(b'\1\0'*320)
        self.assertEqual(len(self.socket.sent),before)

    def test_tool_settlement_cannot_exceed_hard_context_limit(self):
        self.ready()
        self.stream.max_context_tokens=64000
        self.stream.context_estimate=63400
        self.stream.tools['settle']={'name':'recent_originals','state':'pending'}
        before=len(self.socket.sent)
        with self.assertRaises(DialogueCapacity):
            self.stream.tool_result('settle',{'kind':'sources','text':'protected exact source'})
        self.assertEqual(len(self.socket.sent),before)

    def test_close_frame_billing_is_not_misreported_as_invalid_json(self):
        self.socket.recv_data=lambda **kwargs:(8,b'\x03\xf3billing credit unavailable; synthetic private account detail')
        with self.assertRaises(DialogueUnavailable):self.stream.receive()
        self.assertEqual(self.stream.failure_code,'native-dialogue-provider-billing')
        self.assertTrue(self.socket.closed);self.assertEqual(len(self.socket.sent),1)

    def test_other_close_frame_is_distinct_and_ping_is_not_json(self):
        self.socket.recv_data=lambda **kwargs:(9,b'private ping')
        self.assertEqual(self.stream.receive(),[])
        self.socket.recv_data=lambda **kwargs:(8,b'\x03\xe8private unclassified close detail')
        with self.assertRaises(DialogueUnavailable):self.stream.receive()
        self.assertEqual(self.stream.failure_code,'native-dialogue-provider-closed')

    def test_selected_prebuilt_voice_is_kept_across_checkpoint_successor(self):
        self.stream.close();self.socket=Socket()
        self.stream=NativeDialogue(self.key,activity_mode='manual',voice_name='Charon',connect=self.connect,clock=lambda:self.now)
        voice={'voiceConfig':{'prebuiltVoiceConfig':{'voiceName':'Charon'}}}
        self.assertEqual(self.socket.sent[0]['setup']['generationConfig']['speechConfig'],voice)
        self.ready()
        successor=Socket();successor.received=[{'setupComplete':{}}]
        self.stream._connect=lambda *a,**k:successor
        basis={'revision':'a'*64,'through':0,'content':{'kind':'internal_integrator_checkpoint',
            'checkpoint':{'text':'Keep the existing conversation.'}}}
        candidate=self.stream.successor(basis)
        self.assertEqual(successor.sent[0]['setup']['generationConfig']['speechConfig'],voice)
        self.assertEqual(candidate.voice_name,'Charon');candidate.close()
        for invalid in ('',None,1,'Charon\n','Charon/other'):
            if invalid is None:continue  # Omission deliberately preserves the provider default.
            with self.assertRaises(ValueError):NativeDialogue(self.key,activity_mode='manual',voice_name=invalid,connect=self.connect)

    def pin_stream(self,context=None):
        self.stream.close();self.socket=Socket()
        self.stream=NativeDialogue(self.key,activity_mode='automatic',connect=self.connect,
            clock=lambda:self.now,context_pinning=True,context=context)
        self.ready();self.pin_owner=(str(uuid.uuid4()),str(uuid.uuid4()))

    def pin(self,text='Exact unincorporated words',through=1,checkpointed=0):
        content={'kind':'internal_live_context_pin','dialogue':self.pin_owner[0],
            'generation':self.pin_owner[1],'through':through,
            'checkpoint':{'through':checkpointed,'text':'Semantic checkpoint'},
            'events':[{'text':text,'role':'assistant','interrupted':True}]}
        raw=json.dumps(content,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        return {'content':content,'revision':hashlib.sha256(raw).hexdigest(),
            'through':through,'checkpointed':checkpointed,'bytes':len(raw)}

    def test_pin_replaces_only_preamble_and_does_not_accumulate_old_preamble_cost(self):
        self.pin_stream(context={'being_identity':{'text':'Same selected being identity'}})
        base=self.socket.sent[0]['setup']['systemInstruction']
        self.stream.input_active=True;self.stream.response_pending=True
        self.stream.queue_pin(self.pin('a'*8000),1)
        self.assertEqual(len(self.socket.sent),1,'Preparation is not a provider write')
        self.assertTrue(self.stream.flush_pin());first=self.stream.context_estimate
        history=self.stream.history_estimate
        self.stream.queue_pin(self.pin('New exact tail',through=2,checkpointed=1),2)
        self.assertTrue(self.stream.flush_pin())
        self.assertLess(self.stream.context_estimate,first)
        self.assertEqual(self.stream.context_estimate,history+self.stream.preamble_estimate)
        update=self.socket.sent[-1]
        self.assertEqual(set(update),{'contextUpdate'})
        self.assertEqual(set(update['contextUpdate']),{'systemInstruction'})
        parts=update['contextUpdate']['systemInstruction']['parts']
        self.assertEqual(len(parts),1)
        self.assertTrue(parts[0]['text'].startswith('\n\n'.join(p['text'] for p in base['parts'])))
        self.assertNotIn('a'*8000,json.dumps(update))
        self.assertTrue(self.stream.input_active);self.assertTrue(self.stream.response_pending)
        self.assertEqual(self.stream.pin_status()['attempt']['phase'],'sent')
        self.assertFalse(self.stream.flush_pin(),'Sent context is not automatically repeated')

    def test_ready_pin_precedes_pcm_even_when_queued_while_writer_lock_is_held(self):
        self.pin_stream();queued=threading.Event();errors=[]
        def queue_pin():
            try:self.stream.queue_pin(self.pin(),1)
            except BaseException as error:errors.append(error)
            finally:queued.set()
        with self.stream._lock:
            writer=threading.Thread(target=lambda:self.stream.append(b'\0\0'*1600))
            writer.start()
            producer=threading.Thread(target=queue_pin);producer.start()
            self.assertTrue(queued.wait(1),'Pin preparation must not wait behind a socket writer')
        producer.join(2);writer.join(2)
        self.assertFalse(errors);self.assertFalse(writer.is_alive())
        self.assertEqual([next(iter(v)) for v in self.socket.sent],['setup','contextUpdate','realtimeInput'])
        self.assertEqual(base64.b64decode(self.socket.sent[-1]['realtimeInput']['audio']['data']),b'\0\0'*1600)

    def test_pin_coalesces_owned_unsent_revisions_and_rejects_stale_or_changed_content(self):
        self.pin_stream();old=self.pin('Old exact text');self.stream.queue_pin(old,1)
        old['content']['events'][0]['text']='Caller mutation after preparation'
        fresh=self.pin('Current exact tail',through=2,checkpointed=1)
        self.stream.queue_pin(fresh,2)
        with self.assertRaises(ValueError):self.stream.queue_pin(fresh,2)
        with self.assertRaises(ValueError):self.stream.queue_pin(self.pin(through=1),3)
        changed=self.pin(through=3);changed['content']['events'][0]['text']='Changed without matching revision'
        with self.assertRaises(ValueError):self.stream.queue_pin(changed,3)
        self.stream.flush_pin()
        self.assertEqual(len(self.socket.sent),2)
        self.assertIn('Current exact tail',json.dumps(self.socket.sent[-1]))
        self.assertNotIn('Caller mutation',json.dumps(self.socket.sent[-1]))
        self.assertEqual(self.stream.pin_status()['attempt']['sequence'],2)

    def test_failed_pin_write_is_uncertain_and_never_automatically_retried(self):
        self.pin_stream();self.stream.queue_pin(self.pin(),1);self.socket.fail_send=True
        with self.assertRaises(DialogueUnavailable):self.stream.flush_pin()
        self.assertEqual(self.stream.pin_status()['attempt']['phase'],'uncertain')
        self.assertIsNone(self.stream.pin_status()['pending'])
        with self.assertRaises(ValueError):self.stream.flush_pin()
        self.assertEqual(len(self.socket.sent),1)

    def test_pin_reserve_refusal_is_unsent_and_provider_usage_is_not_subtracted(self):
        self.pin_stream();self.event({'usageMetadata':{'totalTokenCount':40000}})
        self.stream.queue_pin(self.pin('a'*8000),1);self.stream.flush_pin()
        self.stream.queue_pin(self.pin('Short replacement',through=2,checkpointed=1),2);self.stream.flush_pin()
        self.assertGreaterEqual(self.stream.history_estimate,40000)
        self.assertGreaterEqual(self.stream.context_estimate,40000+self.stream.preamble_estimate)
        self.stream.queue_pin(self.pin(through=3,checkpointed=2),3)
        self.stream.context_estimate=128000;before=len(self.socket.sent)
        with self.assertRaises(DialogueCapacity):self.stream.flush_pin()
        self.assertEqual(len(self.socket.sent),before)
        self.assertEqual(self.stream.pin_status()['attempt']['phase'],'unsent')

    def test_final_handover_gate_rejects_pending_tools_and_unknown_provider_writes(self):
        self.ready();self.assertTrue(self.stream.handover_ready())
        self.event({'toolCall':{'functionCalls':[{'id':'query','name':'recent_originals','args':{}}]}})
        self.assertFalse(self.stream.handover_ready('query'))
        self.stream.tool_result('query',{'kind':'sources'})
        self.assertFalse(self.stream.handover_ready())
        self.event({'serverContent':{'turnComplete':True}})
        self.event({'toolCall':{'functionCalls':[{'id':'watch','name':'await_integrator_update','args':{}}]}})
        self.assertFalse(self.stream.handover_ready());self.assertTrue(self.stream.handover_ready('watch'))
        self.stream.tools['watch']['state']='response_unconfirmed'
        self.assertFalse(self.stream.handover_ready('watch'))

    def test_successor_opens_checkpoint_only_without_retiring_or_replaying_old_socket(self):
        self.ready()
        basis={'revision':'a'*64,'through':4,'content':{'kind':'internal_integrator_checkpoint',
            'checkpoint':{'text':'Keep the current purpose, correction and unresolved request.'}}}
        successor=Socket();successor.received=[{'setupComplete':{},'usageMetadata':{'promptTokenCount':40}}]
        self.stream._connect=lambda *a,**k:successor
        candidate=self.stream.successor(basis,pending_effects=[{'original':self.original,'intent':str(uuid.uuid4()),'phase':'unconfirmed'}],
            pending_originals=[{'original':self.original,'sha256':'c'*64}])
        self.assertFalse(self.socket.closed);self.assertEqual(self.stream.phase,'ready')
        self.assertEqual(candidate.phase,'ready');self.assertEqual(len(successor.sent),1)
        self.assertEqual(set(successor.sent[0]),{'setup'})
        setup=successor.sent[0]['setup'];context=json.dumps(setup)
        self.assertIn('internal_integrator_checkpoint',context)
        self.assertIn('unconfirmed',context)
        self.assertIn('uninterpreted_originals',context)
        self.assertIn('no known words',context)
        self.assertNotIn('toolResponse',successor.sent[0]);self.assertNotIn('realtimeInput',successor.sent[0])
        candidate.close()

    def test_successor_keeps_old_transport_when_setup_fails_and_refuses_busy_floor(self):
        self.ready()
        basis={'revision':'a'*64,'through':1,'content':{'kind':'internal_integrator_checkpoint','checkpoint':{'text':'Known context'}}}
        self.stream.response_pending=True
        self.assertIsNone(self.stream.successor(basis))
        self.stream.response_pending=False
        successor=Socket();successor.fail_send=True;self.stream._connect=lambda *a,**k:successor
        with self.assertRaises(DialogueUnavailable):self.stream.successor(basis)
        self.assertFalse(self.socket.closed);self.assertTrue(successor.closed)
        self.assertEqual(self.stream.phase,'ready')

    def test_successor_uses_native_canonical_seed_bytes_without_clipping_unicode(self):
        self.ready();opened=[]
        successor=Socket();successor.received=[{'setupComplete':{}}]
        def connect(*args,**kwargs):opened.append(True);return successor
        self.stream._connect=connect
        content={'kind':'internal_integrator_checkpoint','checkpoint':{'text':''}}
        canonical=lambda:json.dumps(content,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        remaining=24576-len(canonical())
        content['checkpoint']['text']='é'*(remaining//2)+'x'*(remaining%2)
        self.assertEqual(len(canonical()),24576)
        self.assertGreater(len(json.dumps(content,ensure_ascii=False).encode()),24576)
        basis={'revision':'a'*64,'through':1,'content':content}
        candidate=self.stream.successor(basis)
        self.assertTrue(any(content['checkpoint']['text'] in part['text'] for part in successor.sent[0]['setup']['systemInstruction']['parts']))
        self.assertEqual(opened,[True]);candidate.close()
        content['checkpoint']['text']+='x'
        with self.assertRaises(ValueError):self.stream.successor(basis)
        self.assertEqual(opened,[True],'An oversize seed never opens another socket')
        self.assertFalse(self.socket.closed)
        self.assertEqual(self.stream.input_bytes,0)

    def test_successor_checks_complete_identity_and_seed_size_before_opening(self):
        self.ready();opened=[]
        self.stream._continuity_identity={'being_identity':{'text':'a'*8192}}
        self.stream._connect=lambda *a,**k:opened.append(True)
        basis={'revision':'a'*64,'through':1,'content':{'kind':'internal_integrator_checkpoint',
            'checkpoint':{'text':'b'*24200}}}
        with self.assertRaises(ValueError):self.stream.successor(basis)
        self.assertEqual(opened,[]);self.assertFalse(self.socket.closed)

    def guidance(self,mode='context_only'):
        return {'id':str(uuid.uuid4()),'dialogue':str(uuid.uuid4()),'generation':str(uuid.uuid4()),
                'basis':1,'mode':mode,'text':'A confirmed fact from Sol; not a new human request.'}

    def test_guidance_waits_for_provider_floor_and_only_spoken_offer_completes_turn(self):
        self.ready();value=self.guidance()
        self.event({'voiceActivity':{'type':'ACTIVITY_START','audioOffset':'0s'}})
        count=len(self.socket.sent);self.assertFalse(self.stream.guide(value));self.assertEqual(len(self.socket.sent),count)
        self.event({'voiceActivity':{'type':'ACTIVITY_END','audioOffset':'1s'}})
        self.assertFalse(self.stream.guide(value))
        self.event({'serverContent':{'turnComplete':True}})
        self.assertTrue(self.stream.guide(value));frame=self.socket.sent[-1]['clientContent']
        self.assertFalse(frame['turnComplete']);self.assertFalse(self.stream.response_pending)
        content=json.loads(frame['turns'][0]['parts'][0]['text'])
        self.assertEqual(content['kind'],'internal_integrator_guidance');self.assertFalse(content['human_speech'])
        self.assertEqual(content['id'],value['id'])
        with self.assertRaises(ValueError):self.stream.guide(value)
        spoken=self.guidance('spoken_offer');self.assertTrue(self.stream.guide(spoken))
        self.assertTrue(self.socket.sent[-1]['clientContent']['turnComplete']);self.assertTrue(self.stream.response_pending)

    def test_guidance_failed_send_is_not_replayed_or_reported_applied(self):
        self.ready();value=self.guidance();self.socket.fail_send=True
        with self.assertRaises(DialogueUnavailable):self.stream.guide(value)
        self.assertIn(value['id'],self.stream.guidance_attempts)
        self.assertEqual(self.stream.failure_code,'native-dialogue-send-unconfirmed')
        with self.assertRaises(ValueError):self.stream.guide(value)
        self.assertEqual(len(self.socket.sent),1)

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

    def test_provider_accounting_does_not_enable_ungated_discard(self):
        setup=self.socket.sent[0]['setup']
        self.assertNotIn('contextWindowCompression',setup)
        self.assertEqual(self.stream.max_context_tokens,128000)
        self.ready()
        self.assertEqual(self.event({'usageMetadata':{'promptTokenCount':105000,'totalTokenCount':105100,'private_payload':'not retained'}}),
            [{'type':'context_usage','usage':{'promptTokenCount':105000,'totalTokenCount':105100}}])
        self.assertEqual(self.stream.context_usage,{'promptTokenCount':105000,'totalTokenCount':105100})
        self.assertTrue(self.stream.rollover_due)
        self.assertEqual(self.stream.checkpoint_pressure,{'reason':'tokens','tokens':105100,'usage_kind':'observed'})
        self.assertEqual(self.event({'usageMetadata':{'promptTokenCount':100,'totalTokenCount':200}}),[],'A lower observation cannot authorize context discard')
        self.assertEqual(self.event({'usageMetadata':{'promptTokenCount':True,'totalTokenCount':-1}}),[])
        self.assertEqual(self.stream.phase,'ready')
        self.assertEqual(self.stream.input_bytes,0)

    def test_quiet_transport_requests_checkpoint_without_inventing_provider_usage_or_speech(self):
        self.ready()
        self.stream._clock=lambda:self.stream._started+241
        self.assertEqual(self.stream.checkpoint_pressure,{'reason':'lifetime','tokens':self.stream.context_estimate,'usage_kind':'conservative'})
        self.assertEqual(self.stream.receive(),[{'type':'context_pressure'}])
        self.assertEqual(self.stream.receive(),[])
        self.assertEqual(len(self.socket.sent),1)

    def test_context_reserve_rejects_before_write_and_allows_the_owned_phrase_end(self):
        self.stream.close();self.socket=Socket()
        self.stream=NativeDialogue(self.key,activity_mode='manual',connect=self.connect,clock=lambda:self.now)
        self.ready();self.stream.activity_start()
        self.stream.context_estimate=120000
        before=len(self.socket.sent)
        self.stream.activity_end()
        self.assertEqual(len(self.socket.sent),before+1,'Phrase end uses the reserved margin')
        self.stream.response_pending=False
        with self.assertRaises(DialogueCapacity):self.stream.activity_start()
        self.assertEqual(len(self.socket.sent),before+1,'A refused input never touches the socket')
        self.assertTrue(self.socket.closed)

    def test_missing_usage_uses_conservative_media_text_and_tool_accounting(self):
        self.ready();initial=self.stream.context_estimate
        self.assertGreater(initial,0,'Setup identity and tool context consume reserve')
        self.stream.append(b'\0\0'*1600)
        self.assertGreaterEqual(self.stream.context_estimate,initial+7)
        before=self.stream.context_estimate
        self.event({'serverContent':{'outputTranscription':{'text':'α reply'}}})
        self.assertGreaterEqual(self.stream.context_estimate,before+len('α reply'.encode()))
        self.event({'usageMetadata':{'totalTokenCount':102500}})
        self.assertTrue(self.stream.rollover_due)
        self.event({'usageMetadata':{'totalTokenCount':1}})
        self.assertGreaterEqual(self.stream.context_estimate,102500)
        with self.assertRaisesRegex(DialogueUnavailable,'context-output-bound'):
            self.event({'usageMetadata':{'totalTokenCount':128001}})

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
        self.assertEqual(reply['scheduling'],'WHEN_IDLE')
        self.assertNotIn('scheduling',reply['response'])
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
