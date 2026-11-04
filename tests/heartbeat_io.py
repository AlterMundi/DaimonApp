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


def qualify_inbox(binary):
    """Existing finite producer + real signed SDK channel; synthetic native only."""
    import importlib.util
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    spec = importlib.util.spec_from_file_location(
        "heartbeat_matrix_fixtures", Path(__file__).with_name("matrix_execution.py")
    )
    adapter = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = adapter
    spec.loader.exec_module(adapter)
    sdk = adapter.AdapterTests()
    sdk.setUp()
    j = HeartbeatJourney(str(Path(binary).resolve()))
    source = {
        "being_ref": sdk.sender.lane.being_ref,
        "embodiment_id": sdk.sender.lane.local_embodiment_id,
    }
    calls, errors, cursors = [], [], []
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
                calls.append(value["after"])
                result = adapter.operator_inbox(
                    value, adapter.SignedGroupClient(sdk.fixture, sdk.sender), timeout=1
                )
                cursors.append(result["next_cursor"])
                if hold["enabled"]:
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
        j.idle()

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
            + ',data=raw,headers={"content-type":"application/json"})\nwith urllib.request.urlopen(request,timeout=12)as response:sys.stdout.buffer.write(response.read(65537))\n'
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
            "matrix_inbox": {"source": source, "channel_id": "tribe"},
        }
        j.read(
            "heartbeat",
            "configure-producer",
            str(paused["generation"]),
            json.dumps(contract),
        )
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
        paused = j.read("heartbeat", "pause")["result"]
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
        assert status["admission_paused"] and status["producer"]["checks"] == 3
        assert j.row("SELECT count(*) FROM interaction_matrix_inbox") == [(1,)]
        assert len(j.bounded) == 1
        due()
        j.read("heartbeat", "resume", str(status["generation"]))
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
        finish(packet)
        final = j.read("heartbeat", "pause")["result"]
        assert (
            final["producer"]["checks"] == 4
            and final["resources"]["reserved_provider_attempts"] == 6
        )
        assert j.row("SELECT count(*) FROM conversation_inputs") == [(0,)]
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
            "PASS signed new Matrix originals -> finite shared producer -> bounded idle native -> exact source read -> canonical Conversation report; no-news quiet; held read pause/restart rejects late cursor, explicit resume retains counters and account6/12; Telegram disabled, no fabricated human input or real provider/model call. Synthetic native; live receiving/model/device acceptance remains separate."
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
