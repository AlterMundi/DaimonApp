#!/usr/bin/env python3
"""Finite heartbeat through real wrapper/controller/store with a synthetic native.
Zero provider calls. Native admission itself is qualified separately by Core.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import uuid
from workflow_io import WorkflowJourney


class HeartbeatJourney(WorkflowJourney):
    def __init__(self, binary):
        self.bounded = []
        super().__init__(binary)

    def wait(self, condition, seconds=15):
        try:
            return super().wait(condition, seconds)
        except AssertionError as error:
            raise AssertionError(str(error).split('; messages=', 1)[0]) from None

    def handle_extra_rpc(self, message, send):
        if message.get('method') == 'turn/startBoundedIfIdle':
            p = message['params']
            turn = p['turn']
            assert turn['input'] == [] and 'clientUserMessageId' not in turn
            assert p['allowance']['maxProviderAttempts'] == 3
            assert 0 < p['allowance']['maxRequestBytes'] <= 1024 * 1024
            assert p['allowance']['deadlineUnixMs'] > datetime.now(timezone.utc).timestamp() * 1000
            kind = turn['toolOutput']['name']
            assert kind in ('heartbeat_attention', 'heartbeat_delegation')
            self.bounded.append(p)
            physical = 'bounded-heartbeat-' + str(len(self.bounded))
            native = turn['threadId']
            if kind == 'heartbeat_attention':
                self.web_thread, self.web_turn = native, physical
            else:
                assert turn['toolOutput']['output'].startswith('[Interaction controller]')
                self.workers[native] = physical
                self.worker_packets.setdefault(native, []).append(turn)
            send({'id': message['id'], 'result': {'turn': {'id': physical}}})
            self.broadcast(native, 'turn/started', {'turn': {'id': physical, 'status': 'inProgress'}})
            return True
        return super().handle_extra_rpc(message, send)


def qualify(binary):
    j = HeartbeatJourney(str(Path(binary).resolve()))
    try:
        j.start()
        for topic in (7, 8, 1):
            j.admit('Seed this synthetic owned native context', topic=topic)
            j.wait(lambda: j.has('Initial goal turn delivered.', topic)); j.idle()
        j.stop()
        j.config.write_text(j.config.read_text().replace('[telegram]', '[telegram]\nenabled=false') + j.target_config)
        j.start(); j.wait_control_socket(j.socket); j.routing = True
        journal = j.row('SELECT count(*) FROM incoming_updates')
        j.messages.clear(); j.telegram_methods.clear()
        binding = j.read('presentation', 'list', '0', '0')['result']['binding']
        original, _ = j.submit(binding, 'Produce a checkpoint and verify it in the existing second session.')
        j.wait(lambda: j.row('SELECT phase FROM conversation_inputs WHERE id=?', (original['id'],)) == [('accepted',)])
        plan = {'input_ref': original['id'], 'request_id': 'heartbeat-fixture',
                'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), 'steps': [
                    {'id': 'produce', 'selector': 't7', 'after': None, 'scope': 'Produce checkpoint.',
                     'checkpoint': 'Checkpoint', 'milestone': 'Ready'}]}
        view = j.call('route-declare', 'workflow_declare', plan)
        j.call('route-first-step', 'workflow_advance', {'workflow': view['id'], 'revision': view['revision']})
        j.wait(lambda: j.instructions(7) and j.instructions(7)[0][1] == 'accepted')
        j.answer_worker(7, 'Exact predecessor for the heartbeat.')
        j.wait(lambda: j.row("SELECT count(*) FROM interaction_results WHERE body='Exact predecessor for the heartbeat.'") == [(1,)])
        paused = j.read('heartbeat', 'pause')['result']
        expiry = int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp() * 1000)
        resources = {'contract_id': str(uuid.uuid4()), 'max_provider_attempts': 12,
                     'provider_attempts_per_execution': 3, 'max_request_bytes': 1024 * 1024,
                     'execution_seconds': 60, 'expires_at_unix_ms': expiry}
        j.read('heartbeat', 'configure-resources', str(paused['generation']), json.dumps(resources))
        contract = {'interval_seconds': 30, 'max_checks': 4, 'expires_at_unix_ms': expiry,
                    'matrix_replies': False, 'workflows': True}
        configured = j.read('heartbeat', 'configure-producer', str(paused['generation']), json.dumps(contract))['result']
        assert configured['attention_engine'] == 'finite_canonical_offer_producer'
        j.read('heartbeat', 'resume', str(paused['generation']))
        # Release the ordinary human writer; maintenance must create a fresh root.
        j.broadcast(j.web_thread, 'turn/completed', {'turn': {'id': j.web_turn, 'status': 'completed'}})
        j.idle()
        j.wait(lambda: len(j.bounded) == 1, seconds=45)
        j.wait(lambda: j.row("SELECT count(*) FROM bot_state,json_each(bot_state.value,'$.native_returns') r WHERE bot_state.key LIKE 'heartbeat_producer:%' AND json_extract(r.value,'$.phase')='accepted'") == [(1,)])
        packet = json.loads(j.bounded[0]['turn']['toolOutput']['output'])
        assert packet['schema'] == 'daimon.heartbeat-batch/v1'
        offer = packet['evidence']['offers'][0]['evidence']
        reader = offer['reader']
        j.call('route-source-read', reader['operation'], reader['arguments'])
        # Select the remaining authorized subtask, rather than retrying the
        # already completed production workflow or its original input.
        verification = dict(plan, request_id='heartbeat-verification', steps=[
            {'id': 'verify', 'selector': 't8', 'after': None,
             'scope': 'Verify the exact selected production checkpoint.',
             'checkpoint': 'Verified', 'milestone': None}])
        current = j.call('route-verify-declare', 'workflow_declare', verification)
        j.call('route-next-step', 'workflow_advance', {'workflow': current['id'], 'revision': current['revision']})
        j.wait(lambda: len(j.bounded) == 2)
        assert j.bounded[1]['turn']['toolOutput']['name'] == 'heartbeat_delegation'
        j.wait(lambda: j.instructions(8) and j.instructions(8)[0][1] == 'accepted')
        j.answer_worker(8, 'Verified by the reserved child.')
        j.wait(lambda: j.row("SELECT count(*) FROM interaction_results WHERE body='Verified by the reserved child.'") == [(1,)])
        j.call('route-review-batch', 'heartbeat_reported', {
            'return_id': packet['return_id'], 'revision': packet['evidence']['revision']})
        j.broadcast(j.web_thread, 'item/completed', {'turnId': j.web_turn, 'item': {
            'id': 'heartbeat-action-report', 'type': 'agentMessage', 'phase': 'commentary',
            'text': 'Heartbeat reviewed the checkpoint and the reserved worker verified it.'}})
        j.broadcast(j.web_thread, 'turn/completed', {'turn': {'id': j.web_turn, 'status': 'completed'}})
        j.idle()
        paused = j.read('heartbeat', 'pause')['result']
        assert paused['admission_paused'] and paused['resources']['reserved_provider_attempts'] == 6
        page = j.read('presentation', 'list', '0', '0')['result']
        assert any(i['preview'].startswith('Heartbeat reviewed the checkpoint') for i in page['items']), page
        assert j.row('SELECT count(*) FROM incoming_updates') == journal
        assert j.row('SELECT count(*) FROM conversation_inputs') == [(1,)]
        assert not j.messages and not j.telegram_methods, j.telegram_methods
        assert len(j.bounded) == 2
        print('PASS finite maintenance -> exact bounded root -> owned controller source read -> reserved bounded workflow child -> batch review -> same Conversation report; Telegram disabled, original account charged6, no fabricated original or provider call. Synthetic native, not receiving/model/device acceptance.')
    finally:
        j.close()


if __name__ == '__main__':
    qualify(sys.argv[1])
