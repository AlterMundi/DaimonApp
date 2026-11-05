"""Native WebRTC owner transport; synthetic sockets, no provider/model calls."""
import json
from pathlib import Path
import queue
import sys
import threading
import time
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.codex_voice import AvatarVoiceLease, CodexVoice, CodexVoiceRejected, CodexVoiceUnavailable


class Socket:
    def __init__(self):
        self.sent=[]; self.incoming=queue.Queue(); self.closed=False
        self.reject=False; self.lose=False
    def event(self, method, **params):
        self.incoming.put(json.dumps({'method':method,'params':{'threadId':'owned',**params}}))
    def send(self, raw):
        value=json.loads(raw);self.sent.append(value)
        if 'id' not in value:return
        method=value['method']
        if method=='thread/realtime/start':
            if self.reject:
                self.incoming.put(json.dumps({'id':value['id'],'error':{'message':'private provider payload'}}));return
            if self.lose:return
            self.event('thread/realtime/started',realtimeSessionId=value['params']['realtimeSessionId'])
            self.event('thread/realtime/sdp',sdp='v=0\r\nanswer')
        if method=='thread/realtime/stop':self.event('thread/realtime/closed',reason='requested')
        result={'thread':{'id':'owned'}} if method=='thread/resume' else {}
        self.incoming.put(json.dumps({'id':value['id'],'result':result}))
    def recv(self):
        try:return self.incoming.get(timeout=.05)
        except queue.Empty:
            if self.closed:return ''
            raise TimeoutError()
    def close(self):self.closed=True


class Voice(unittest.TestCase):
    def setUp(self):
        self.socket=Socket()
        self.active=set();self.lease=AvatarVoiceLease(self.active,100,'a'*64,'owned')
        self.addCleanup(self.lease.release)
        self.voice=CodexVoice('/unused','owned',lease=self.lease,connect=lambda root:self.socket)
        self.addCleanup(self.voice.close)
    def wait(self, check):
        end=time.monotonic()+1
        while not check():
            if time.monotonic()>end:self.fail('Synthetic native reader did not settle')
            time.sleep(.002)
    def test_native_owner_and_thread_are_reused_without_custom_turn_loop(self):
        self.voice.start('v=0\r\noffer')
        frames=self.socket.sent
        self.assertEqual([v['method'] for v in frames],['initialize','initialized','thread/resume','thread/realtime/start'])
        self.assertTrue(frames[0]['params']['capabilities']['experimentalApi'])
        self.assertEqual(frames[2]['params'],{'threadId':'owned','excludeTurns':True})
        p=frames[3]['params']
        self.assertEqual(p['transport'],{'type':'webrtc','sdp':'v=0\r\noffer'})
        self.assertTrue(p['includeStartupContext']);self.assertFalse(p['clientManagedHandoffs'])
        self.assertNotIn('prompt',p);self.assertNotIn('model',p)
        self.assertNotIn('authorization',json.dumps(frames).lower())
        self.assertEqual([e['method'] for e in self.voice.receive(0)],['thread/realtime/started','thread/realtime/sdp'])
    def test_foreign_thread_and_noisy_deltas_are_not_retained(self):
        self.socket.event('thread/realtime/sdp',threadId='foreign',sdp='private unrelated answer')
        self.socket.event('thread/realtime/transcript/delta',delta='partial')
        self.socket.event('thread/realtime/item/transcript/delta',delta='partial duplicate')
        self.socket.event('thread/realtime/item/completed',item={'text':'complete retained source'})
        self.wait(lambda:len(self.voice._events)==1)
        self.assertEqual(self.voice.receive(0)[0]['params']['item']['text'],'complete retained source')
    def test_owner_context_uses_native_developer_item_without_prompt_replacement(self):
        context='Owner-selected CompAII identity and concise conversational style.'
        self.voice.start('v=0\r\noffer',context=context)
        params=self.socket.sent[-1]['params']
        self.assertEqual(params['initialItems'],[{'role':'developer','text':context}])
        self.assertNotIn('prompt',params)
        self.assertNotIn('model',params)
        self.assertFalse(params['clientManagedHandoffs'])
        self.assertFalse(any(v['method']in('turn/start','thread/realtime/appendText')for v in self.socket.sent))
    def test_invalid_owner_context_never_attempts_native_start(self):
        for context in ('', 'x'*8193, 'bad\0context', {'role':'user','text':'fake human'}):
            with self.assertRaises(ValueError):self.voice.start('v=0\r\noffer',context=context)
        self.assertFalse(self.voice._attempted)
        self.assertFalse(any(v['method']=='thread/realtime/start'for v in self.socket.sent))
    def test_stop_never_interrupts_a_backend_and_is_not_repeated(self):
        self.voice.start('v=0 offer')
        self.voice.stop();self.voice.stop()
        methods=[v['method'] for v in self.socket.sent]
        self.assertEqual(methods.count('thread/realtime/stop'),1)
        self.assertNotIn('turn/interrupt',methods)
        self.voice.close()
        self.assertEqual([v['method'] for v in self.socket.sent],methods)
        self.assertFalse(self.voice._reader.is_alive())
    def test_rejected_start_never_stops_someone_elses_voice(self):
        self.socket.reject=True
        with self.assertRaisesRegex(CodexVoiceRejected,'rejected'):
            self.voice.start('v=0 offer')
        self.assertIsNone(self.voice.stop())
        with self.assertRaises(CodexVoiceUnavailable):self.voice.start('v=0 offer')
        self.assertEqual(sum(v['method']=='thread/realtime/start' for v in self.socket.sent),1)
        self.assertNotIn('thread/realtime/stop',[v['method'] for v in self.socket.sent])
    def test_unowned_close_is_not_proof_our_generation_closed(self):
        self.socket.event('thread/realtime/closed',reason='older voice')
        time.sleep(.02)
        self.assertFalse(self.voice.closure_observed)
        self.voice.start('v=0 offer')
        self.assertFalse(self.voice.closure_observed)
        self.voice.stop()
        self.assertTrue(self.voice.closure_observed)
    def test_generation_change_retires_ownership(self):
        self.voice.start('v=0 offer')
        self.socket.event('thread/realtime/started',realtimeSessionId='another-client')
        self.wait(lambda:self.voice._failed)
        self.assertIsNone(self.voice.stop())
    def test_lost_ack_is_not_retried_and_does_not_claim_ownership(self):
        self.socket.lose=True
        original=self.voice._rpc
        self.voice._rpc=lambda method,params:original(method,params,timeout=.02)
        with self.assertRaisesRegex(CodexVoiceUnavailable,'unconfirmed'):
            self.voice.start('v=0 offer')
        with self.assertRaises(CodexVoiceUnavailable):self.voice.start('v=0 offer')
        self.voice.stop_wait_seconds=.01
        with self.assertRaisesRegex(CodexVoiceUnavailable,'unconfirmed'):self.voice.stop()
        self.assertEqual(sum(v['method']=='thread/realtime/start' for v in self.socket.sent),1)
    def test_pending_events_have_a_hard_byte_bound(self):
        self.voice.max_pending_bytes=120
        self.socket.event('thread/realtime/item/completed',item={'text':'x'*200})
        self.wait(lambda:self.voice._event_failed)
        with self.assertRaises(CodexVoiceUnavailable):self.voice.receive(0)
        self.assertEqual(self.voice._event_bytes,0)
    def test_overflow_keeps_an_explicit_voice_stop_path(self):
        self.voice.start('v=0 offer');self.voice.receive(0)
        self.voice.max_pending_bytes=120
        self.socket.event('thread/realtime/item/completed',item={'text':'x'*200})
        self.wait(lambda:self.voice._event_failed)
        with self.assertRaises(CodexVoiceUnavailable):self.voice.receive(0)
        self.voice.stop();self.wait(lambda:not self.voice._owned)
        self.assertEqual(sum(v['method']=='thread/realtime/stop'for v in self.socket.sent),1)
        self.assertNotIn('turn/interrupt',[v['method']for v in self.socket.sent])
    def test_mode_lease_shares_provider_capacity_and_fences_stale_owners(self):
        with self.assertRaises(CodexVoiceUnavailable):AvatarVoiceLease(self.active,100,'a'*64,'owned')
        self.assertIn(100,self.active,'Existing Qwen/Gemini active check excludes another mode too')
        self.lease.release()
        successor=AvatarVoiceLease(self.active,100,'a'*64,'owned')
        try:
            with self.assertRaises(CodexVoiceUnavailable):self.voice.start('v=0 offer')
            self.lease.release()
            self.assertIn(100,self.active,'Old repeated release must not free a successor')
        finally:successor.release()
    def test_one_lease_cannot_open_two_native_clients(self):
        opened=[]
        with self.assertRaisesRegex(CodexVoiceUnavailable,'already has'):
            CodexVoice('/unused','owned',lease=self.lease,connect=lambda root:opened.append(root))
        self.assertEqual(opened,[],'Duplicate client must fail before a native connection')
    def test_explicit_stop_waits_for_its_pending_native_start(self):
        send=self.socket.send
        def delayed(raw):
            v=json.loads(raw)
            if v.get('method')=='thread/realtime/start':
                self.socket.sent.append(v)
                self.socket.incoming.put(json.dumps({'id':v['id'],'result':{}}))
                threading.Timer(.02,lambda:self.socket.event('thread/realtime/started',realtimeSessionId=v['params']['realtimeSessionId'])).start()
            else:send(raw)
        self.socket.send=delayed
        self.voice.start('v=0 offer')
        self.voice.stop()
        self.assertEqual(sum(v['method']=='thread/realtime/stop'for v in self.socket.sent),1)
    def test_stop_ack_does_not_claim_an_unobserved_close_or_repeat_stop(self):
        self.voice.start('v=0 offer');send=self.socket.send
        def acknowledge_only(raw):
            v=json.loads(raw)
            if v.get('method')=='thread/realtime/stop':
                self.socket.sent.append(v);self.socket.incoming.put(json.dumps({'id':v['id'],'result':{}}))
            else:send(raw)
        self.socket.send=acknowledge_only;self.voice.stop_wait_seconds=.01
        with self.assertRaisesRegex(CodexVoiceUnavailable,'closure remains unconfirmed'):self.voice.stop()
        self.voice.stop()
        self.assertEqual(sum(v['method']=='thread/realtime/stop'for v in self.socket.sent),1)
    def test_invalid_browser_offer_never_touches_owner(self):
        n=len(self.socket.sent)
        for offer in ('https://private', 'v=0'+'x'*65536, None):
            with self.assertRaises(ValueError):self.voice.start(offer)
        self.assertEqual(len(self.socket.sent),n)
        self.voice.start('v=0 valid')
    def test_native_tool_requests_are_never_answered_as_approvals(self):
        self.socket.incoming.put(json.dumps({'id':55,'method':'item/tool/call','params':{'threadId':'owned','callId':'private'}}))
        self.socket.event('thread/realtime/sdp',sdp='v=0 answer')
        self.wait(lambda:bool(self.voice._events))
        self.assertEqual(len(self.voice.receive(0)),1)
        self.assertFalse(any(v.get('id')==55 for v in self.socket.sent))


if __name__=='__main__':unittest.main()
