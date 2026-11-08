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
                self.protocol_before = self.protocol_state()
                self.controller(send, turn, 'route-live-invalid-' + turn, {
                    'operation': 'live_context', 'arguments': {
                        'action': 'after_incorporation', 'dialogue': self.dialogue,
                        'revision': output['after_incorporation']['arguments']['revision']}})
            return True
        if method is None and str(ident).startswith('route-live-invalid-'):
            assert message['result']['success'] is False, message
            value = json.loads(message['result']['contentItems'][0]['text'])
            assert value['code'] == 'live_context_invalid_command' and value['mutated'] is False
            assert self.protocol_before == self.protocol_state()
            turn = str(ident).removeprefix('route-live-invalid-')
            self.controller(send, turn, 'route-live-switch-' + turn, {
                'operation': 'live_context', 'arguments': {
                    'action': 'read', 'dialogue': self.dialogue, 'full': True}})
            return True
        if method is None and str(ident).startswith('route-live-switch-'):
            assert message['result']['success'] is False, message
            value = json.loads(message['result']['contentItems'][0]['text'])
            assert value['code'] == 'live_context_selected_range_pending' and value['mutated'] is False
            assert self.protocol_before == self.protocol_state()
            turn = str(ident).removeprefix('route-live-switch-')
            self.controller(send, turn, 'route-live-recover-' + turn, value['recovery']['reader'])
            return True
        if method is None and str(ident).startswith('route-live-recover-'):
            assert message['result']['success'], message
            value = json.loads(message['result']['contentItems'][0]['text'])
            turn = str(ident).removeprefix('route-live-recover-')
            _, output = self.internal[turn]
            assert value['after_incorporation'] == output['after_incorporation']
            assert value['range']['complete'] is True
            assert self.protocol_before == self.protocol_state()
            self.controller(send, turn, 'route-live-ack-' + turn, value['after_incorporation'])
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

    def protocol_state(self):
        doc = json.loads(self.row('SELECT doc FROM live_context WHERE dialogue=?', (self.dialogue,))[0][0])
        # Transport ACK bookkeeping may settle independently of a controller
        # response; language, checkpoint and exact reader state must not change.
        return {key: doc[key] for key in ('high', 'incorporated', 'checkpoint', 'range', 'events', 'sources')}

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


class RetryContext(ContextReturning):
    def __init__(self, binary):
        self.refuse_resume = False
        super().__init__(binary)

    def handle_extra_rpc(self, message, send):
        if (self.refuse_resume and message.get('method') == 'thread/resume'
                and message.get('params', {}).get('threadId') == self.web_thread):
            self.refuse_resume = False
            # Explicitly fail before any native turn/start or possible inference.
            send({'id': message['id'], 'error': {
                'code': -32001, 'message': 'Synthetic metadata resume unavailable'}})
            return True
        return super().handle_extra_rpc(message, send)


def qualify_foreground_retry_without_workflow_flags(binary):
    j = RetryContext(binary)
    try:
        j.start(); j.admit('Seed synthetic foreground retry ownership.', topic=1)
        j.wait(lambda: j.has('Initial goal turn delivered.', 1)); j.idle()
        j.stop()
        # Foreground voice context does not require enabling routed work or
        # workflow attention. Their independent switches remain explicitly off.
        j.config.write_text(j.config.read_text().replace('[interaction]\n',
            '[interaction]\nnative_workflow_returns=false\nnative_routed_returns=false\n'))
        j.web_thread = j.row('SELECT codex_thread_id FROM sessions WHERE thread_id=1')[0][0]
        j.web_turn = 'synthetic-context-retry'
        j.refuse_resume = True; j.messages.clear()
        j.start(); j.wait_control_socket(j.socket)
        j.binding = j.read('presentation', 'list', '0', '0')['result']['binding']
        j.dialogue = str(uuid.uuid4()); j.generation = str(uuid.uuid4())
        j.context('open', generation=j.generation, binding=j.binding)
        j.context('sync', generation=j.generation, assistant=[{
            'source': str(uuid.uuid4()), 'text': 'Fresh synthetic voice context only.',
            'interrupted': True}])
        def receipts():
            return json.loads(j.row('SELECT doc FROM live_context WHERE dialogue=?',
                (j.dialogue,))[0][0])['native_returns']
        j.wait(lambda: receipts() and receipts()[0]['phase'] == 'retained_unsent')
        first = receipts()[0]
        assert first['attempts'] == 1 and first['native_turn'] is None
        assert not j.internal_packets, 'No model input preceded explicit known-unsent recovery'
        # The existing maintenance runner owns this retry, not a new event or
        # duplicate source notification. Its normal tick can take 30 seconds.
        j.wait(lambda: j.row("SELECT json_extract(doc,'$.incorporated') FROM live_context WHERE dialogue=?",
            (j.dialogue,)) == [(1,)], seconds=40)
        j.wait(lambda: receipts()[0]['phase'] == 'accepted')
        last = receipts()
        assert len(last) == 1 and last[0]['id'] == first['id']
        assert last[0]['attempts'] == 2 and last[0]['reported_revision']
        j.wait(lambda: j.row('SELECT busy FROM sessions WHERE thread_id=1') == [(0,)])
        assert len(j.internal_packets) == 1 and not j.errors
        assert not j.messages, 'Pure foreground retry cannot create a human publication'
        assert j.row('SELECT count(*) FROM interaction_workflows') == [(0,)]
        print('PASS foreground known-unsent retry preserves original return ID and bounds with workflow/routed switches off; zero models')
    finally:
        j.close()


if __name__ == '__main__':
    qualify(str(Path(sys.argv[1]).resolve()))
    qualify_foreground_retry_without_workflow_flags(str(Path(sys.argv[1]).resolve()))
