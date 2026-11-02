#!/usr/bin/env python3
"""Authenticated conversation -> signed SDK -> canonical HTTP result; zero inference.

Run with the selected SDK source on PYTHONPATH and an existing dashboard Python.
The approved instruction fixtures and native App Server are synthetic. This does
not qualify a real receiving model, human account, participant or funding grant.
"""

import importlib.util
import json
import sys
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conversation_cold_entry_http_io import Browser, ColdEntry

spec = importlib.util.spec_from_file_location(
    "adapter_fixtures", Path(__file__).with_name("matrix_execution.py")
)
adapter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = adapter
spec.loader.exec_module(adapter)
MatrixConversationTransport = adapter.MatrixConversationTransport
make_received_task = adapter.make_received_task
operator_send = adapter.operator_send


def qualify(binary, *, funded=False):
    sdk = adapter.AdapterTests()
    sdk.setUp()
    j = ColdEntry(str(Path(binary).resolve()))
    b = None
    observed = []
    mode = {"drop": False, "funded": None}
    source_author = {
        "being_ref": sdk.sender.lane.being_ref,
        "embodiment_id": sdk.sender.lane.local_embodiment_id,
    }

    class Host(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            value = json.loads(self.rfile.read(int(self.headers["content-length"])))
            assert value["source"] == source_author
            client = adapter.SignedGroupClient(sdk.fixture, sdk.sender)
            if funded and mode["funded"] is None:
                state = sdk.funded_original(status=value["status"])
                mode["funded"] = state
                outcome = state.outcome
            else:
                outcome = operator_send(value, client, timeout=1)
            observed.append((value, outcome))
            if mode["drop"]:
                self.close_connection = True
                return
            raw = json.dumps(outcome).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    host = ThreadingHTTPServer(("127.0.0.1", 0), Host)
    threading.Thread(target=host.serve_forever, daemon=True).start()
    try:
        j.prepare()
        j.stop()
        target = sdk.target
        configured = (
            'matrix_targets=[{name="SelectedPeer",destination={kind="body",being_ref='
            + json.dumps(target["being_ref"])
            + ",embodiment_id="
            + json.dumps(target["embodiment_id"])
            + "}}]"
        )
        command = j.root / "configured-matrix-host.py"
        command.write_text(
            "import sys,urllib.request\n"
            + "raw=sys.stdin.buffer.read(65537)\n"
            + "request=urllib.request.Request("
            + repr("http://127.0.0.1:" + str(host.server_port))
            + ",data=raw,headers={'content-type':'application/json'})\n"
            + "with urllib.request.urlopen(request,timeout=12)as response: sys.stdout.buffer.write(response.read(65537))\n"
        )
        argv = json.dumps([sys.executable, "-B", str(command)])
        source = (
            '{kind="body",being_ref='
            + json.dumps(source_author["being_ref"])
            + ",embodiment_id="
            + json.dumps(source_author["embodiment_id"])
            + "}"
        )
        configured += (
            "\nmatrix_transport={command="
            + argv
            + ",source="
            + source
            + ",timeout_seconds=15}"
        )
        j.config.write_text(
            j.config.read_text().replace(
                "[interaction]", "[interaction]\n" + configured
            )
        )
        j.start()
        j.wait_control_socket(j.socket)
        b = Browser(j)
        original = "  Pregunta exacta para el daimon seleccionado: ¿qué cambió?  "
        ident, _ = b.text(original)
        j.wait(lambda: b.status(ident)["phase"] == "accepted")
        selected = j.call(
            "route-matrix-original",
            "matrix_request",
            {
                "input_ref": ident,
                "selector": "SelectedPeer",
                "relation": "new",
                "requests": [],
            },
        )
        request = selected["request"]
        assert request["original"]["text"] == original
        assert b.status(ident)["phase"] == "matrix_requested"
        assert selected["phase"] == "submitted", {
            "phase": selected["phase"],
            "host_calls": len(observed),
        }
        assert len(observed) == 1
        assert selected["claimed_source"] == source_author
        snapshot, outcome = observed[0]
        broker = MatrixConversationTransport(
            snapshot["status"],
            source_author,
            adapter.SignedGroupClient(sdk.fixture, sdk.sender),
        )
        sent = sdk.sender.inspect(
            client_id="test", send_id=outcome["submission"]["send_id"]
        )
        assert selected["submission"]["message_id"] == sent["message_id"]
        duplicate = j.call(
            "route-duplicate-matrix-selection",
            "matrix_request",
            {
                "input_ref": ident,
                "selector": "SelectedPeer",
                "relation": "new",
                "requests": [],
            },
        )
        assert duplicate["phase"] == "submitted" and len(observed) == 1
        message = sdk.receiver.message(sent["message_id"])
        reply_scope = replace(
            sdk.scope, thread=sent["thread_id"], tool="messaging_reply", action="reply"
        )
        if funded:
            state = mode["funded"]
            assert state.sent["message_id"] == sent["message_id"]
            context = state.controller.run_due_once(
                state.instruction.instruction_id, 1, state.purpose, work_id=state.work
            )
            admissions = []
            context.inference(
                lambda: admissions.append("synthetic bounded provider admission"),
                exposure=dict(
                    route="isolated-fake",
                    max_charge=30,
                    provider=state.instruction.provider,
                    model=state.instruction.model,
                    max_input_tokens=state.instruction.max_input_tokens,
                    max_output_tokens=state.instruction.max_output_tokens,
                ),
            )
            returned = context.native(
                reply_scope, {"text": "La respuesta exacta del daimon seleccionado."}
            )
            state.store.finish(context.cycle, "completed")
            assert admissions == ["synthetic bounded provider admission"]
            assert state.store.funding_status("episode")["calls"] == 1
            assert state.store.funding_status("episode")["reserved"] == 30
            assert len(state.runner.starts) == 1
        else:
            receiving_task = make_received_task(message, reply_scope)
            responder = sdk.make_broker(sdk.receiver, reply_scope, task=receiving_task)
            returned = responder.submit(
                reply_scope, {"text": "La respuesta exacta del daimon seleccionado."}, 1
            )
        signed_answer = sdk.sender.message(returned["message_id"])
        callback = broker.conversation_return(sent, signed_answer)
        if funded:
            assert signed_answer["payload"]["body"]["coordination"]["kind"] == "result"
            assert (
                state.store.enqueue_coordination(
                    signed_answer["event_id"], sdk.sender.message
                )
                is None
            )
        outcome = j.read("matrix", "return", json.dumps(callback))["result"]
        assert outcome["phase"] == "reply_received" and outcome["current"]
        j.read("matrix", "return", json.dumps(callback))
        assert j.row("SELECT count(*) FROM interaction_matrix_results") == [(1,)]
        page = b.get("/api/interaction?matrix=0")
        source = next(v for v in page["items"] if v["kind"] == "matrix_result")
        assert source["label"] == "#SelectedPeer" and source["completed"] is None
        part = b.get(
            "/api/interaction/part?source="
            + source["id"]
            + "&revision="
            + source["revision"]
        )
        assert part["text"] == callback["text"]
        after = b.get("/api/interaction?matrix=" + str(page["cursor"]["matrix"]))
        assert not any(v["kind"] == "matrix_result" for v in after["items"])
        # A contextual response carries the selected canonical event, not an
        # automatic peer send or a forged local worker request.
        next_id, _ = b.text(
            "Corregí el requisito anterior.",
            {
                "source": source["id"],
                "revision": source["revision"],
                "context_only": True,
            },
        )
        j.wait(lambda: b.status(next_id)["phase"] == "accepted")
        amended = j.call(
            "route-matrix-amendment",
            "matrix_request",
            {
                "input_ref": next_id,
                "selector": "SelectedPeer",
                "relation": "amends",
                "requests": [request["id"]],
            },
        )
        assert amended["request"]["parents"][0]["text"] == original
        assert amended["phase"] == "submitted" and len(observed) == 2
        amendment = sdk.receiver.message(amended["submission"]["message_id"])
        assert json.loads(amendment["payload"]["body"]["text"])["relation"] == {
            "kind": "amends",
            "requests": [request["id"]],
        }
        current = b.get("/api/interaction?matrix=0")
        old = next(v for v in current["items"] if v["kind"] == "matrix_result")
        assert old["correction_pending"] and not old["current"]
        j.call(
            "route-matrix-no-local-reuse",
            "dispatch",
            {
                "input_ref": ident,
                "destinations": [
                    {"selector": "Alpha", "relation": "new", "requests": []}
                ],
            },
            ok=False,
        )
        assert j.row("SELECT count(*) FROM interaction_instructions") == [(0,)]
        assert not j.messages
        # The native journal retains the actual send when the child loses its
        # response; normal controller retries and restart never submit it again.
        lost, _ = b.text("Distinct original whose host response will be lost.")
        j.wait(lambda: b.status(lost)["phase"] == "accepted")
        mode["drop"] = True
        args = {
            "input_ref": lost,
            "selector": "SelectedPeer",
            "relation": "new",
            "requests": [],
        }
        uncertain = j.call("route-matrix-lost-host-response", "matrix_request", args)
        assert uncertain["phase"] == "submission_uncertain" and len(observed) == 3
        lost_id = uncertain["request"]["id"]
        assert sdk.receiver.message(observed[-1][1]["submission"]["message_id"])
        duplicate = j.call("route-matrix-no-uncertain-replay", "matrix_request", args)
        assert duplicate["phase"] == "submission_uncertain" and len(observed) == 3
        j.stop()
        j.start()
        j.wait_control_socket(j.socket)
        retained = j.read("matrix", "status", lost_id)["result"]
        assert retained["phase"] == "submission_uncertain" and len(observed) == 3
        assert retained["claimed_source"] == source_author
        if funded:
            print(
                "FUNDED_RETURN_EVIDENCE",
                json.dumps(
                    {
                        "call_fuel_consumed": 1,
                        "reserved_charge_retained": 30,
                        "selected_source_only": set(state.reads)
                        == {state.source["event_id"]},
                        "result_passive": True,
                        "canonical_return_rows": 1,
                        "provider_model_calls": 0,
                        "native_reader_identity_preserved": True,
                        "worker_kind": "controlled-model-free-stand-in",
                        "real_peer_activation": False,
                    }
                ),
            )
        print(
            "PASS actual HTTP/native controller automatically invokes configured host -> signed SDK technical send -> owner callback -> canonical HTTP; duplicate reservation, explicit signed amendment, lost child response/restart without replay, independent cursor and local exclusion; zero provider/model calls. Funded mode uses a controlled worker stand-in; real receiving native work/automatic integrator incorporation remain unqualified."
        )
    finally:
        if b:
            b.client.close()
        j.close()
        host.shutdown()
        host.server_close()
        sdk.doCleanups()


if __name__ == "__main__":
    qualify(sys.argv[1], funded="--funded" in sys.argv[2:])
