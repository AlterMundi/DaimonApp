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
        if message.get('method')=='initialize':
            send({'id':message['id'],'result':{'boundedIdleTurn':True}})
            return True
        if message.get('method')=='thread/read':
            send({'id':message['id'],'result':{'thread':{'id':message['params']['threadId'],'model':'fixture-model','modelProvider':'fixture','canAcceptDirectInput':True,'status':{'type':'active' if getattr(self,'native_fixture_busy',False) else 'idle'}}}})
            return True
        if message.get('method')=='thread/turns/list' and getattr(self,'native_continuation',None):
            send({'id':message['id'],'result':{'data':[{'id':self.native_continuation,'status':'inProgress'}],'nextCursor':None}})
            return True
        if message.get('method') == 'turn/startBoundedIfIdle':
            p = message['params']
            turn = p['turn']
            assert turn['input'] == [] and 'clientUserMessageId' not in turn
            assert p['allowance']['maxProviderAttempts'] == getattr(self,'expected_attempts',3)
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
                    'matrix_replies': False, 'workflows': True,
                    'purpose': {'input_ref': original['id'], 'channel': 'conversation'}}
        configured = j.read('heartbeat', 'configure-producer', str(paused['generation']), json.dumps(contract))['result']
        assert configured['attention_engine'] == 'finite_canonical_offer_producer'
        assert all(lane['paused'] for lane in configured['lanes'].values())
        j.read('heartbeat', 'resume-lane', 'workflow_returns',
               str(configured['lanes']['workflow_returns']['generation']))
        j.read('heartbeat', 'resume', str(paused['generation']))
        # Release the ordinary human writer; maintenance must create a fresh root.
        j.broadcast(j.web_thread, 'turn/completed', {'turn': {'id': j.web_turn, 'status': 'completed'}})
        j.idle()
        j.wait(lambda: len(j.bounded) == 1, seconds=45)
        j.wait(lambda: j.row("SELECT count(*) FROM bot_state,json_each(bot_state.value,'$.native_returns') r WHERE bot_state.key LIKE 'heartbeat_producer:%' AND json_extract(r.value,'$.phase')='accepted'") == [(1,)])
        packet = json.loads(j.bounded[0]['turn']['toolOutput']['output'])
        assert packet['schema'] == 'daimon.heartbeat-batch/v1'
        purpose = packet['evidence']['operating_purpose']
        purpose_read = j.call('route-read-human-purpose', purpose['reader']['operation'], purpose['reader']['arguments'])
        assert purpose_read['input_ref'] == original['id']
        assert purpose_read['retained_human_original'] and not purpose_read['new_human_input']
        assert purpose_read['text'] == 'Produce a checkpoint and verify it in the existing second session.'
        offer = packet['evidence']['offers'][0]['evidence']
        reader = offer['reader']
        j.call('route-source-read', reader['operation'], reader['arguments'])
        # Select the remaining authorized subtask, rather than retrying the
        # already completed production workflow or its original input.
        verification = dict(plan, input_ref=purpose_read['input_ref'], request_id='heartbeat-verification', steps=[
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
        # Simulate the finite observation period's exhausted counter in this
        # synthetic journal, then exercise the actual owner command boundary.
        j.row("UPDATE bot_state SET value=json_set(value,'$.checks',json_extract(value,'$.contract.max_checks')) WHERE key LIKE 'heartbeat_producer:%'")
        predecessor = j.read('heartbeat', 'status')['result']
        successor_args = ('renew-observation', str(paused['generation']), str(expiry), str(expiry + 60_000), '10')
        successor = j.read('heartbeat', *successor_args)['result']
        assert successor['producer']['checks'] == predecessor['producer']['checks'] == 4
        assert successor['producer']['contract']['max_checks'] == 10
        assert successor['producer']['observation_window_renewal']['previous_max_checks'] == 4
        assert successor['resources'] == predecessor['resources']
        assert successor['admission_paused'] and successor['generation'] == paused['generation']
        repeated = j.read('heartbeat', *successor_args)['result']
        # The renewal/accounting result is idempotent; readiness is a fresh
        # observation, whose timestamp must not be frozen by an exact retry.
        assert repeated['operational_evidence']['observed_at_unix_ms'] >= successor['operational_evidence']['observed_at_unix_ms']
        repeated['operational_evidence']['observed_at_unix_ms'] = successor['operational_evidence']['observed_at_unix_ms']
        assert repeated == successor
        j.stop(); j.start(); j.wait_control_socket(j.socket)
        restarted = j.read('heartbeat', 'status')['result']
        assert restarted['producer'] == successor['producer']
        assert restarted['resources'] == successor['resources']
        assert len(j.bounded) == 2
        print('PASS finite maintenance -> exact bounded root -> owned controller source read -> reserved bounded workflow child -> batch review -> same Conversation report; Telegram disabled, original account charged6, no fabricated original or provider call. Synthetic native, not receiving/model/device acceptance.')
        print('PASS owner-only finite observation successor and lost-ACK repeat/restart conserve count4, original sources and inference account; explicit cumulative ceiling10 creates no native execution.')
        # Explicit permanent-operation selection retains pilot history while
        # replacing its expired operating lifetime, through the actual CLI.
        current = j.read('heartbeat', 'status')['result']
        j.row("UPDATE bot_state SET value=json_set(value,'$.contract.expires_at_unix_ms',1,'$.checks',json_extract(value,'$.contract.max_checks'),'$.next_check_ms',0) WHERE key LIKE 'heartbeat_producer:%'")
        j.row("UPDATE bot_state SET value=json_set(value,'$.contract.expires_at_unix_ms',1) WHERE key LIKE 'heartbeat_resources:%'")
        pilot = j.read('heartbeat', 'status')['result']
        adopted = j.read('heartbeat', 'continuous', str(current['generation']), '6')['result']
        assert adopted['admission_paused'] and adopted['producer']['mode'] == 'continuous'
        assert adopted['producer']['checks'] == pilot['producer']['checks']
        assert adopted['producer']['contract'] == pilot['producer']['contract']
        assert adopted['resources']['contract'] == pilot['resources']['contract']
        assert adopted['resources']['reserved_provider_attempts'] == pilot['resources']['reserved_provider_attempts'] == 6
        assert adopted['resources']['continuous']['reserved_provider_attempts'] == 0
        assert adopted['producer']['state'] == 'configured' and adopted['resources']['state'] == 'available'
        j.read('heartbeat', 'resume', str(adopted['generation']))
        try:
            j.wait(lambda: j.read('heartbeat', 'status')['result']['producer']['checks'] > pilot['producer']['checks'], seconds=45)
        except AssertionError:
            status = j.read('heartbeat', 'status')['result']
            raise AssertionError(json.dumps({'producer': status['producer'], 'lanes': status['lanes'],
                'executions': status.get('executions'), 'running_turns': j.row("SELECT id,status,native_thread_id FROM turns WHERE status='running'")})) from None
        observed = j.read('heartbeat', 'pause')['result']
        j.stop(); j.start(); j.wait_control_socket(j.socket)
        permanent = j.read('heartbeat', 'status')['result']
        assert permanent['admission_paused'] and permanent['resources'] == observed['resources']
        assert permanent['producer']['checks'] == observed['producer']['checks']
        assert permanent['producer']['mode'] == 'continuous' and len(j.bounded) == 2
        print('PASS owner continuous selection beyond expired/exhausted pilot, preserved counters/reservations, model-free ongoing observation and paused restart; no extra native/provider turn.')

    finally:
        j.close()


def qualify_inbox(binary):
    """Existing finite producer + real signed SDK channel; synthetic native only."""
    import importlib.util
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from unittest.mock import patch
    from daimon_matrix import synthetic_relationships

    spec = importlib.util.spec_from_file_location(
        "heartbeat_matrix_fixtures", Path(__file__).with_name("matrix_execution.py")
    )
    adapter = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = adapter
    spec.loader.exec_module(adapter)
    sdk = adapter.AdapterTests()
    # Keep the signed fixture's operational epoch compatible with real backend
    # absolute deadlines. Its default year2027 epoch correctly rejects our2026
    # expiry before authoring; do not weaken that native deadline check.
    with patch.object(synthetic_relationships, "NOW", int(datetime.now(timezone.utc).timestamp()*1000)):
        sdk.setUp()
    j = HeartbeatJourney(str(Path(binary).resolve()))
    source = {
        "being_ref": sdk.sender.lane.being_ref,
        "embodiment_id": sdk.sender.lane.local_embodiment_id,
    }
    calls, errors, cursors, response_calls = [], [], [], []
    lost_ack = {"next": False}
    hold = {"enabled": False}
    entered, released = threading.Event(), threading.Event()

    class Host(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            try:
                size = int(self.headers["content-length"])
                assert size <= 65536 and len(calls) < 8
                value = json.loads(self.rfile.read(size))
                assert value["source"] == source and value["channel_id"] == "tribe"
                mode = self.headers.get("x-matrix-mode", "--inbox")
                if mode in ("--respond", "--response-status"):
                    response_calls.append((mode, value["send_id"]))
                    result = adapter.operator_respond(
                        value, adapter.SignedGroupClient(sdk.fixture, sdk.sender), timeout=1,
                        inspect_only=mode == "--response-status",
                    )
                    if mode == "--respond" and lost_ack["next"]:
                        lost_ack["next"] = False
                        self.send_error(503, "Synthetic lost authoring ACK; native journal retained")
                        return
                else:
                    assert mode == "--inbox"
                    calls.append(value["after"])
                    result = adapter.operator_inbox(
                        value, adapter.SignedGroupClient(sdk.fixture, sdk.sender), timeout=1
                    )
                if mode == "--inbox":
                    cursors.append(result["next_cursor"])
                if hold["enabled"] and mode == "--inbox":
                    entered.set()
                    assert released.wait(timeout=8), (
                        "Paused source read was not released"
                    )
                raw = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                assert entered.is_set(), "Unexpected source disconnect"
            except Exception as error:
                errors.append(repr(error))
                self.send_error(502, "Synthetic source failed")

    host = ThreadingHTTPServer(("127.0.0.1", 0), Host)
    threading.Thread(target=host.serve_forever, daemon=True).start()

    def fresh(text):
        return sdk.fixture.send_and_settle(
            sdk.receiver,
            client_id="test",
            send_id=str(uuid.uuid4()),
            thread_id=str(uuid.uuid4()),
            text=text,
            destination={"kind": "body", **source},
        )

    def due():
        # Advance only the source eligibility deadline. The existing30second
        # maintenance clock is still real; never reset counters/cursor/expiry.
        import sqlite3

        with sqlite3.connect(j.root / "state.sqlite") as db:
            db.execute(
                "UPDATE bot_state SET value=json_set(value,'$.next_check_ms',0) WHERE key LIKE 'heartbeat_producer:%'"
            )

    def finish(packet):
        j.call(
            "route-inbox-reviewed-" + str(len(j.bounded)),
            "heartbeat_reported",
            {
                "return_id": packet["return_id"],
                "revision": packet["evidence"]["revision"],
            },
        )
        j.broadcast(
            j.web_thread,
            "item/completed",
            {
                "turnId": j.web_turn,
                "item": {
                    "id": "inbox-report-" + str(len(j.bounded)),
                    "type": "agentMessage",
                    "phase": "commentary",
                    "text": "Reviewed the selected signed Matrix original in this conversation.",
                },
            },
        )
        j.broadcast(
            j.web_thread,
            "turn/completed",
            {"turn": {"id": j.web_turn, "status": "completed"}},
        )
        j.wait(lambda: j.row("SELECT count(*) FROM sessions WHERE busy=1 AND thread_id<>8") == [(0,)])

    try:
        j.start()
        for topic in (7, 8, 1):
            j.admit(
                "Seed existing native metadata for finite inbox qualification",
                topic=topic,
            )
            j.wait(lambda: j.has("Initial goal turn delivered.", topic))
            j.idle()
        j.stop()
        command = j.root / "matrix-inbox-host.py"
        command.write_text(
            "import sys,urllib.request\nraw=sys.stdin.buffer.read(65537)\nrequest=urllib.request.Request("
            + repr("http://127.0.0.1:" + str(host.server_port))
            + ',data=raw,headers={"content-type":"application/json","x-matrix-mode":sys.argv[1]})\nwith urllib.request.urlopen(request,timeout=12)as response:sys.stdout.buffer.write(response.read(65537))\n'
        )
        options = (
            'matrix_inbox_channel="tribe"\nmatrix_transport={command='
            + json.dumps([sys.executable, "-B", str(command)])
            + ",source="
            + json.dumps({"kind": "body", **source}).replace(": ", "=")
            + ",timeout_seconds=15}\n"
        )
        # JSON object keys are quoted, which is valid in the TOML inline table.
        config = (
            j.config.read_text().replace("[telegram]", "[telegram]\nenabled=false")
            + j.target_config
        )
        j.config.write_text(
            config.replace("[interaction]", "[interaction]\n" + options)
        )
        j.start()
        j.wait_control_socket(j.socket)
        j.routing = True
        journal = j.row("SELECT count(*) FROM incoming_updates")
        j.messages.clear()
        j.telegram_methods.clear()
        binding = j.read("presentation", "list", "0", "0")["result"]["binding"]
        purpose_original, _ = j.submit(binding,
            "Attend these selected Matrix originals, use the existing worker to check relevant evidence, and reply with the observed result.")
        j.wait(lambda: j.row("SELECT phase FROM conversation_inputs WHERE id=?", (purpose_original["id"],)) == [("accepted",)])
        j.call("route-operating-primary", "dispatch", {
            "input_ref": purpose_original["id"],
            "destinations": [{"selector": "t8", "relation": "new", "requests": []}],
        })
        j.wait(lambda: j.instructions(8) and j.instructions(8)[0][1] == "accepted")
        primary_before = j.instructions(8)[0]
        j.broadcast(j.web_thread, "turn/completed", {"turn": {"id": j.web_turn, "status": "completed"}})
        j.wait(lambda: j.row("SELECT busy FROM sessions WHERE thread_id=1") == [(0,)])
        assert j.row("SELECT busy FROM sessions WHERE thread_id=8") == [(1,)]
        first = fresh("First fresh Matrix original.")
        paused = j.read("heartbeat", "pause")["result"]
        expiry = int(
            (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp() * 1000
        )
        resources = {
            "contract_id": str(uuid.uuid4()),
            "max_provider_attempts": 12,
            "provider_attempts_per_execution": 3,
            "max_request_bytes": 1024 * 1024,
            "execution_seconds": 60,
            "expires_at_unix_ms": expiry,
        }
        j.read(
            "heartbeat",
            "configure-resources",
            str(paused["generation"]),
            json.dumps(resources),
        )
        contract = {
            "interval_seconds": 30,
            "max_checks": 6,
            "expires_at_unix_ms": expiry,
            "matrix_replies": False,
            "workflows": False,
            "session_progress": True,
            "matrix_inbox": {"source": source, "channel_id": "tribe"},
            "purpose": {"input_ref": purpose_original["id"], "channel": "conversation"},
        }
        j.read(
            "heartbeat",
            "configure-producer",
            str(paused["generation"]),
            json.dumps(contract),
        )
        j.answer_worker(8, "The original owner is still progressing.", finish=False, phase="commentary")
        selected = j.read("heartbeat", "resume-lane", "messaging",
                          str(paused["generation"]), "0")["result"]
        assert selected["controls"]["conditional_global"] is True
        assert selected["controls"]["conditional_lane"] is True
        assert not selected["lanes"]["messaging"]["paused"]
        assert all(v["paused"] for k, v in selected["lanes"].items() if k != "messaging")
        j.read("heartbeat", "resume", str(paused["generation"]))
        j.wait(lambda: len(j.bounded) == 1, seconds=45)
        j.wait(
            lambda: (
                j.row(
                    "SELECT count(*) FROM bot_state,json_each(bot_state.value,'$.native_returns') r WHERE bot_state.key LIKE 'heartbeat_producer:%' AND json_extract(r.value,'$.phase')='accepted'"
                )
                == [(1,)]
            )
        )
        packet = json.loads(j.bounded[0]["turn"]["toolOutput"]["output"])
        offered = next(
            o["evidence"]
            for o in packet["evidence"]["offers"]
            if o["evidence"]["reason"] == "matrix_original_available"
        )
        assert offered["source"] == "matrix-inbox:" + first["message_id"]
        # A stale app pause must not interrupt this actual owned execution.
        before_stale = j.read("heartbeat", "status")["result"]
        j.read("heartbeat", "pause", "0", ok=False)
        after_stale = j.read("heartbeat", "status")["result"]
        assert after_stale["executions"] == before_stale["executions"]
        assert after_stale["generation"] == before_stale["generation"]
        assert not after_stale["admission_paused"]
        # A configured progress source remains silent while its lane is paused.
        assert not any(o["evidence"]["reason"] == "worker_progress_available"
                       for o in packet["evidence"]["offers"])
        unrelated = j.read("heartbeat", "pause-lane", "reports")["result"]
        assert not unrelated["admission_paused"]
        assert not unrelated["lanes"]["messaging"]["paused"]
        read = offered["reader"]
        exact = j.call(
            "route-periodic-inbox-source", read["operation"], read["arguments"]
        )
        assert (
            exact["text"] == "First fresh Matrix original."
            and exact["kind"] == "matrix_inbox"
        )
        assert (
            exact["source_author"]["being_ref"] == sdk.receiver.lane.being_ref
            and exact["completed"] is None
        )
        deferred = j.call("route-inbox-defer", "matrix_response", {
            "action": "defer", "message_id": first["message_id"],
            "revision": offered["revision"], "reason": "Wait for the next relevant observation.",
            "condition": "Review the next original from this peer.",
        })
        assert deferred["handling"]["phase"] == "deferred"
        finish(packet)
        due()
        j.wait(lambda: len(calls) >= 2, seconds=45)
        j.wait(
            lambda: j.read("heartbeat", "status")["result"]["producer"]["checks"] == 2
        )
        # Native cursors are global opaque sequence values, not row counts.
        assert len(j.bounded) == 1 and calls == [0, cursors[0]]
        second = fresh("Second fresh Matrix original, held across pause.")
        hold["enabled"] = True
        due()
        assert entered.wait(timeout=45), "Finite source read did not start"
        current = j.read("heartbeat", "status")["result"]
        paused = j.read("heartbeat", "pause-lane", "messaging",
                        str(current["generation"]),
                        str(current["lanes"]["messaging"]["generation"]))["result"]
        assert not paused["admission_paused"] and paused["lanes"]["messaging"]["paused"]
        assert (
            paused["producer"]["checks"] == 3
            and paused["resources"]["reserved_provider_attempts"] == 3
        )
        released.set()
        j.stop()
        hold["enabled"] = False
        j.start()
        j.wait_control_socket(j.socket)
        status = j.read("heartbeat", "status")["result"]
        assert not status["admission_paused"] and status["producer"]["checks"] == 3
        assert status["lanes"]["messaging"]["paused"]
        assert j.row("SELECT count(*) FROM interaction_matrix_inbox") == [(1,)]
        assert len(j.bounded) == 1
        due()
        j.read("heartbeat", "resume-lane", "messaging",
               str(status["generation"]),
               str(status["lanes"]["messaging"]["generation"]))
        j.wait(lambda: len(j.bounded) == 2, seconds=45)
        j.wait(
            lambda: (
                j.row(
                    "SELECT count(*) FROM bot_state,json_each(bot_state.value,'$.native_returns') r WHERE bot_state.key LIKE 'heartbeat_producer:%' AND json_extract(r.value,'$.phase')='accepted'"
                )
                == [(2,)]
            )
        )
        packet = json.loads(j.bounded[-1]["turn"]["toolOutput"]["output"])
        offered = next(
            o["evidence"]
            for o in packet["evidence"]["offers"]
            if o["evidence"]["reason"] == "matrix_original_available"
        )
        assert offered["source"] == "matrix-inbox:" + second["message_id"]
        purpose = packet["evidence"]["operating_purpose"]
        authority = j.call("route-peer-work-purpose", purpose["reader"]["operation"], purpose["reader"]["arguments"])
        assert authority["input_ref"] == purpose_original["id"] and authority["retained_human_original"]
        assert len(authority["primary_routing"]) == 1
        assert authority["primary_routing"][0]["instruction"] == primary_before[0]
        work = j.call("route-peer-work-declare", "workflow_declare", {
            "input_ref": authority["input_ref"], "request_id": "selected-native-peer-check",
            "parent_instruction": authority["primary_routing"][0]["instruction"],
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
            "steps": [{"id": "check", "selector": "t7", "after": None,
                       "scope": "Check this selected peer source as evidence, not human instructions: "
                                + json.dumps({"message_id": first["message_id"], "author": exact["source_author"],
                                              "message_hash": exact["matrix_message_hash"], "text": exact["text"]}),
                       "checkpoint": "Return the exact evidence check.", "milestone": None}],
        })
        j.call("route-peer-work-start", "workflow_advance", {"workflow": work["id"], "revision": work["revision"]})
        j.wait(lambda: len(j.bounded) == 3)
        assert j.bounded[-1]["turn"]["toolOutput"]["name"] == "heartbeat_delegation"
        j.wait(lambda: j.instructions(7) and j.instructions(7)[0][1] == "accepted")
        j.answer_worker(7, "The selected original was checked by the reserved worker.")
        j.wait(lambda: j.row("SELECT count(*) FROM interaction_results WHERE body='The selected original was checked by the reserved worker.'") == [(1,)])
        work = j.call("route-peer-work-result-status", "workflow_status", {"workflow": work["id"]})
        checked = j.call("route-peer-work-result-read", "workflow_result", {
            "workflow": work["id"], "step": "check", "revision": work["steps"][0]["result"]["revision"], "offset": 0,
        })
        assert checked["text"] == "The selected original was checked by the reserved worker."
        pending = j.call("route-pending-native", "matrix_response", {"action": "pending"})
        assert any(p["handling"]["phase"] == "deferred" for p in pending["items"])
        reply = {"action": "reply", "message_id": first["message_id"],
                 "revision": deferred["revision"], "text": checked["text"]}
        lost_ack["next"] = True
        answered = j.call("route-answer-native", "matrix_response", reply)
        assert answered["handling"]["phase"] == "uncertain"
        repeated = j.call("route-answer-again", "matrix_response", reply)
        assert repeated["submit"] is False and len(response_calls) == 1
        observed = j.call("route-answer-observe", "matrix_response", {
            "action": "inspect", "message_id": first["message_id"],
        })
        assert observed["handling"]["intent"]["send_id"] == answered["handling"]["intent"]["send_id"]
        assert observed["handling"]["phase"] in ("submitted", "recipient_copy_proved")
        assert response_calls == [("--respond", answered["handling"]["intent"]["send_id"]),
                                  ("--response-status", answered["handling"]["intent"]["send_id"])]
        j.call("route-peer-work-integrated", "workflow_finish", {
            "workflow": work["id"], "revision": work["revision"],
            "checkpoint": "Read the exact reserved worker result and retained its correlated native reply outcome.",
        })
        assert j.instructions(8)[0] == primary_before, "Primary original was replayed, rewritten or retired"
        finish(packet)
        final = j.read("heartbeat", "pause", str(status["generation"]))["result"]
        assert (
            final["producer"]["checks"] == 4
            and final["resources"]["reserved_provider_attempts"] == 9
        )
        assert j.row("SELECT count(*) FROM conversation_inputs") == [(1,)]
        assert j.row("SELECT count(*) FROM incoming_updates") == journal
        assert j.row("SELECT count(*) FROM interaction_matrix_inbox") == [(2,)]
        assert not errors and not j.messages and not j.telegram_methods, (
            errors,
            j.telegram_methods,
        )
        presentation = j.read("presentation", "list", "0", "0")["result"]
        assert any(
            i["preview"].startswith("Reviewed the selected signed Matrix original")
            for i in presentation["items"]
        )
        print(
            "PASS signed Matrix original -> finite shared producer -> bounded idle integrator -> exact source and actual human-purpose read -> durable defer -> ordinary workflow with reserved child -> exact result -> correlated native reply -> canonical Conversation report; no-news quiet; messaging-only lane persists; unrelated lane pause leaves source reads active; held read lane-pause/restart rejects late cursor; lost reply ACK stays uncertain, duplicate does not resend, delivery-only inspection recovers same intent; checks/account9of12 conserved; Telegram disabled, one actual synthetic human-purpose original with no fabricated peer/human input or real provider/model call. Synthetic native; live receiving/model/device acceptance remains separate."
        )
    except Exception:
        print("INBOX_FIXTURE_DIAGNOSTICS", {"calls":calls,"errors":errors,"bounded":len(j.bounded)},file=sys.stderr)
        try:
            print("INBOX_FIXTURE_STATUS",json.dumps(j.read("heartbeat","status")["result"]),file=sys.stderr)
            print("INBOX_FIXTURE_SESSIONS",j.row("SELECT thread_id,busy FROM sessions"),file=sys.stderr)
        except Exception as diagnostic:
            print("INBOX_FIXTURE_DIAGNOSTIC_ERROR",type(diagnostic).__name__,file=sys.stderr)
        raise
    finally:
        released.set()
        j.close()
        host.shutdown()
        host.server_close()
        sdk.doCleanups()

if __name__ == '__main__':
    if '--inbox' in sys.argv[2:]:
        qualify_inbox(sys.argv[1])
    else:
        qualify(sys.argv[1])
