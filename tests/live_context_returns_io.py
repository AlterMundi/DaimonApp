#!/usr/bin/env python3
"""Actual owner/native-controller/SQLite context journey with a synthetic Core.

No model/provider/audio calls. This qualifies wrapper delivery and presentation,
not actual Core admission, semantic model incorporation or device acceptance.
"""
import hashlib
import json
from pathlib import Path
import sys
import uuid

from workflow_native_returns_io import Returning
from conversation_routing_io import CanonicalRouting


class ContextReturning(Returning):
    def handle_extra_rpc(self, message, send):
        method = message.get('method'); p = message.get('params', {}); ident = message.get('id')
        if method == 'turn/start' and 'toolOutput' in p:
            assert p['input'] == [] and 'clientUserMessageId' not in p
            assert p['toolOutput']['name'] == 'foreground_context'
            assert p['toolOutput']['namespace'] is None and p['toolOutput']['retain']
            output = json.loads(p['toolOutput']['output'])
            assert output['schema'] == 'telecodex.foreground-context/v1'
            self.internal_packets.append(p)
            turn = self.web_turn if len(self.internal_packets) == 1 else 'idle-live-context'
            self.internal[turn] = (send, output)
            send({'id': ident, 'result': {'turn': {'id': turn}}})
            if len(self.internal_packets) > 1:
                self.web_turn = turn
                self.broadcast(self.web_thread, 'turn/started', {'turn': {'id': turn, 'status': 'inProgress'}})
                # The actual dynamic-controller path must deny producer authority.
                self.controller(send, turn, 'route-live-deny-' + turn, {
                    'operation': 'live_context', 'arguments': {
                        'action': 'open', 'dialogue': str(uuid.uuid4()),
                        'generation': str(uuid.uuid4()), 'binding': self.binding}})
            else:
                self.controller(send, turn, 'route-live-ack-' + turn, output['after_incorporation'])
            return True
        if method is None and str(ident).startswith('route-live-deny-'):
            assert message['result']['success'] is False, message
            turn = str(ident).removeprefix('route-live-deny-')
            send, output = self.internal[turn]
            self.controller(send, turn, 'route-live-pin-deny-' + turn, {
                'operation':'live_context','arguments':{'action':'pin_read',
                    'dialogue':self.dialogue,'generation':self.generation}})
            return True
        if method is None and str(ident).startswith('route-live-pin-deny-'):
            assert message['result']['success'] is False, message
            turn = str(ident).removeprefix('route-live-pin-deny-')
            send, output = self.internal[turn]
            self.controller(send, turn, 'route-live-ack-' + turn, output['after_incorporation'])
            return True
        if method is None and str(ident).startswith('route-live-ack-'):
            assert message['result']['success'], message
            turn = str(ident).removeprefix('route-live-ack-')
            # Emit ordinary native output deliberately: the publication owner,
            # not a polite model prompt, enforces the internal-only lifetime.
            text = 'Reply to the actual human question.' if len(self.internal_packets) == 1 else 'INTERNAL_CONTEXT_MUST_NOT_PUBLISH'
            for phase in ('commentary', 'final_answer'):
                self.broadcast(self.web_thread, 'item/completed', {'turnId': turn, 'item': {
                    'id': phase + '-' + turn, 'type': 'agentMessage', 'phase': phase, 'text': text}})
            self.broadcast(self.web_thread, 'turn/completed', {'turn': {'id': turn, 'status': 'completed'}})
            return True
        return CanonicalRouting.handle_extra_rpc(self, message, send)

    def controller(self, send, turn, ident, arguments):
        send({'id': ident, 'method': 'item/tool/call', 'params': {
            'threadId': self.web_thread, 'turnId': turn, 'callId': ident,
            'tool': 'interaction_controller', 'arguments': arguments}})

    def context(self, action, **extra):
        return self.read('input', 'foreground', 'context', json.dumps({
            'action': action, 'dialogue': self.dialogue, **extra}))['result']


def qualify(binary):
    j = ContextReturning(binary)
    try:
        j.start()
        j.admit('Seed the existing synthetic integrating context.', topic=1)
        j.wait(lambda: j.has('Initial goal turn delivered.', 1)); j.idle()
        j.wait_control_socket(j.socket)
        j.binding = j.read('presentation', 'list', '0', '0')['result']['binding']
        journal = j.row('SELECT count(*) FROM incoming_updates')
        j.messages.clear()
        real, _ = j.submit(j.binding, 'An actual independent human question.')
        j.wait(lambda: j.row('SELECT phase FROM conversation_inputs WHERE id=?', (real['id'],)) == [('accepted',)])
        j.dialogue = str(uuid.uuid4()); generation = j.generation = str(uuid.uuid4())
        j.context('open', generation=generation, binding=j.binding)
        human = {'binding': j.binding, 'id': str(uuid.uuid4()),
                 'dialogue_id': j.dialogue, 'text': 'Una idea conversada sin delegar trabajo.'}
        j.read('input', 'foreground', 'retain', json.dumps(human))
        # Catch up from canonical retention, as after a process exit before its
        # projection notification. No new ASR or original is manufactured.
        j.context('sync', generation=generation)
        j.wait(lambda: len(j.internal_packets) == 1)
        j.wait(lambda: j.row("SELECT json_extract(doc,'$.incorporated') FROM live_context WHERE dialogue=?", (j.dialogue,)) == [(1,)])
        j.wait(lambda: j.row('SELECT busy FROM sessions WHERE thread_id=1') == [(0,)])
        first = json.loads(j.internal_packets[0]['toolOutput']['output'])
        assert first['evidence']['content']['events'][0]['source'] == human['id']
        assert first['evidence']['content']['events'][0]['role'] == 'human'
        j.context('sync', generation=generation, assistant=[{'source':str(uuid.uuid4()),
                  'text':'A terminal assistant utterance; generated is not necessarily heard.', 'interrupted':True}])
        j.wait(lambda: len(j.internal_packets) == 2)
        j.wait(lambda: j.row("SELECT json_extract(doc,'$.incorporated') FROM live_context WHERE dialogue=?", (j.dialogue,)) == [(2,)])
        j.wait(lambda: j.row('SELECT busy FROM sessions WHERE thread_id=1') == [(0,)])
        receipts=json.loads(j.row('SELECT doc FROM live_context WHERE dialogue=?',(j.dialogue,))[0][0])['native_returns']
        j.wait(lambda: all(r['phase'].startswith('accepted') for r in json.loads(j.row('SELECT doc FROM live_context WHERE dialogue=?',(j.dialogue,))[0][0])['native_returns']))
        assert len(receipts)==2 and all(r['reported_revision'] for r in receipts)
        before=j.row('SELECT doc FROM live_context WHERE dialogue=?',(j.dialogue,))
        pin=j.context('pin_read',generation=generation)['pin']
        encoded=json.dumps(pin['content'],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        assert pin['bytes']==len(encoded) and pin['revision']==hashlib.sha256(encoded).hexdigest()
        assert pin['through']==2 and pin['checkpointed']==0
        assert [e['role'] for e in pin['content']['events']]==['human','assistant']
        assert pin['content']['events'][1]['interrupted'] is True
        assert before==j.row('SELECT doc FROM live_context WHERE dialogue=?',(j.dialogue,))
        assert len(j.internal_packets)==2,'Owner pin read must not wake native context'
        sources=j.read('presentation','list','0','0')['result']['items']
        assert any(i['preview']=='Reply to the actual human question.' for i in sources), sources
        assert not any('INTERNAL_CONTEXT_MUST_NOT_PUBLISH' in i['preview'] for i in sources), sources
        assert j.row('SELECT phase,local_turn FROM conversation_inputs WHERE id=?',(human['id'],))==[('foreground',None)]
        assert j.row('SELECT count(*) FROM interaction_workflows')==[(0,)]
        assert j.row('SELECT count(*) FROM interaction_instructions')==[(0,)]
        assert j.row('SELECT count(*) FROM conversation_inputs')==[(2,)]
        assert j.row('SELECT count(*) FROM incoming_updates')==journal
        assert not j.messages
        assert all(not p['input'] for p in j.internal_packets)
        print('PASS selected canonical human catch-up + assistant context; active/idle internal delivery, actual controller incorporation, owner-only immutable pin, producer denial, pure-context silence, independent human publication, no workflow/worker/original replay; zero models')
    finally:
        j.close()


if __name__ == '__main__':
    qualify(str(Path(sys.argv[1]).resolve()))
