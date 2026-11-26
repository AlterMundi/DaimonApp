#!/usr/bin/env python3
"""Real Antigravity SDK through Gateway with synthetic Matrix and loopback provider."""

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import sys
from threading import Event, Thread
from uuid import uuid4

from conversation_input_control_io import Inputs


ORIGINAL = "Read the exact fixture memory 7349."
MARKER = "The fixture used a blue marker."
BEING = "dm:being:v1:" + "A" * 43
BODY = "fixture-receiver"
MANIFEST = "a" * 64
RECORD = "00000000-0000-4000-8000-000000000003"
ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "adapters/antigravity/gateway-worker.py"


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def admitted(self):
        phase, raw = self.server.journey.row(
            "SELECT phase, submission FROM interaction_matrix_requests WHERE source_event=?",
            (self.server.current,),
        )[0]
        assert phase == "provider_exposed"
        assert json.loads(raw)["engine"] == self.server.engine

    def do_POST(self):
        try:
            assert self.path == "/v1/chat/completions"
            call = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            text = json.dumps(call["messages"])
            assert self.server.original in text
            assert "A decoy record." not in text
            if self.server.engine == "antigravity":
                assert "Reply with the catalog check marker:" not in text
                assert sum(message["role"] == "user" for message in call["messages"]) == 1
            tool = self.server.tool_prefix + "dmk_read_selected"
            names = [item["function"]["name"] for item in call["tools"]]
            assert sorted(names) == sorted([self.server.tool_prefix + "daimon_status", tool]), names
            self.admitted()
            self.server.calls.append(self.server.current)
            if self.server.mode == "held":
                self.server.arrived.set()
                self.server.release.wait(timeout=8)
                return
            if self.server.mode == "lost":
                self.send_error(503)
                return
            if MARKER in text:
                assert self.server.calls.count(self.server.current) == 2
                payload = {"content": "Selected memory: " + MARKER, "role": "assistant"}
                finish = "stop"
            else:
                assert self.server.calls.count(self.server.current) == 1
                payload = {"role": "assistant", "tool_calls": [{"index": 0, "id": "call_fixture",
                    "type": "function", "function": {"name": tool, "arguments": "{}"}}]}
                finish = "tool_calls"
            streaming = call.get("stream")
            result = {"id": "fixture", "created": 1, "model": self.server.model,
                      "object": "chat.completion.chunk" if streaming else "chat.completion"}
            usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            if streaming:
                chunks = [
                    {**result, "choices": [{"index": 0, "finish_reason": None, "delta": payload}]},
                    {**result, "choices": [{"index": 0, "finish_reason": finish, "delta": {}}]},
                    {**result, "choices": [], "usage": usage},
                ]
                body = ("".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
                        + "data: [DONE]\n\n").encode()
            else:
                result["choices"] = [{"index": 0, "finish_reason": finish, "message": payload}]
                result["usage"] = usage
                body = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if streaming else "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as error:
            self.server.failure = error
            self.send_error(400)


def host_cli(path):
    path.write_text('''
import json
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4
fixture = json.loads(Path(sys.argv[1]).read_text())
operation = sys.argv[2]
request = json.load(sys.stdin)
if operation == "--body-status":
    assert request == {"source": {"being_ref": fixture["being"], "embodiment_id": fixture["body"]}}
    reply = {"schema": "dm.runtime.status/v1", "integrity": "ok", "being_ref": fixture["being"],
        "manifest_hash": fixture["manifest"], "local_origin": {"incarnation_id": "fixture-incarnation",
        "embodiment_id": fixture["body"]}}
elif operation == "--we-read":
    reply = {field: request["original"][field] for field in ("author", "event_id", "thread_id")}
    reply.update(schema="daimon-gateway.matrix-we-original/v1", receipt_event_id=str(uuid4()), text=fixture["original"])
elif operation == "--request-stdin":
    assert request == {"action":"read","pool":"main","record_uid":fixture["record"],"expected_revision":1,"offset":0}
    with Path(fixture["effects"]).open("a") as effects:
        effects.write("memory\\n")
    reply = {"being_ref": fixture["being"], "body_ref": "fixture:antigravity", "pools":[
        {"pool":"main","result":{"status":"ok","record":{"record_uid":fixture["record"],"revision":1},
         "complete":True,"raw_offset":0,"next_offset":None,"raw":fixture["marker"]}}]}
else:
    assert operation == "--we-return"
    original = request["original"]
    with sqlite3.connect(fixture["database"]) as db:
        phase, submission = db.execute("select phase, submission from interaction_matrix_requests where source_event=?",
            (original["event_id"],)).fetchone()
    assert phase == "returning" and json.loads(submission)["send_id"] == request["send_id"]
    assert fixture["marker"] in request["text"]
    with Path(fixture["effects"]).open("a") as effects:
        effects.write("return\\n")
    reply = {"schema":"daimon-gateway.matrix-we-return/v1","request_id":request["send_id"],"state":"delivered",
             "thread_id":original["thread_id"],"message_id":str(uuid4()),"message_hash":"b"*64,
             "receipt_event_id":str(uuid4())}
print(json.dumps(reply))
''')


def qualify(j, python, provider):
    provider.journey = j
    provider.original = ORIGINAL
    provider.engine = "antigravity"
    provider.model = "fixture"
    provider.tool_prefix = ""
    provider.calls = []
    provider.mode = None
    provider.failure = None
    provider.arrived = Event()
    provider.release = Event()
    root = j.root
    state = root / "agy-state"
    state.mkdir(mode=0o700)
    profile = root / "agy.json"
    status = root / "matrix-fixture.py"
    fixture = root / "matrix-fixture.json"
    effects = root / "effects"
    database = root / "state.sqlite"
    host_cli(status)
    fixture.write_text(json.dumps(dict(being=BEING, body=BODY, manifest=MANIFEST,
        record=RECORD, original=ORIGINAL, marker=MARKER, effects=str(effects), database=str(database))))
    command = ["/usr/bin/python3", str(status), str(fixture)]
    body = dict(beingRef=BEING, embodimentId=BODY, incarnationId="fixture-incarnation", manifestHash=MANIFEST)
    settings = dict(node="/usr/bin/node", stateRoot=str(state), model="fixture",
        providerPort=provider.server_port, body=body, matrixStatusCommand=command)
    profile.touch(mode=0o600)
    j.config.write_text(j.config.read_text() + f"""
[interaction.antigravity_foreground]
worker_command={json.dumps([python, "-B", str(WORKER), "--profile", str(profile)])}
[interaction.antigravity_foreground.transport]
command={json.dumps(command)}
source={{kind="body", being_ref="{BEING}", embodiment_id="{BODY}"}}
timeout_seconds=5
""")
    j.start()
    j.wait_control_socket(j.socket)
    thread = str(uuid4())

    def select(mode, *, provider_port=None):
        selected = str(uuid4())
        original = dict(event_id=selected, author="fixture-sender", thread_id=thread, cursor=None)
        memory = dict(command=command, inputId=selected, pool="main", recordUid=RECORD,
                      revision=1, bodyRef="fixture:antigravity")
        config = {**settings, "selectedMemory": memory}
        if mode == "mismatched":
            config["body"] = {**body, "incarnationId": "another-incarnation"}
        if provider_port is not None:
            config["providerPort"] = provider_port
        if mode == "startup_failed":
            config["providerCommand"] = ["/usr/bin/false"]
        profile.write_text(json.dumps(config))
        provider.current = selected
        provider.mode = mode
        return original

    def run(original):
        return j.read("matrix", "antigravity", "run", json.dumps(original))["result"]

    def attempt(mode, *, provider_port=None):
        original = select(mode, provider_port=provider_port)
        outcome = run(original)
        assert provider.failure is None, provider.failure
        return original, outcome

    _, refused = attempt("mismatched")
    assert refused["phase"] == "rejected" and provider.calls == [] and not effects.exists(), refused
    with socket.socket() as offline:
        offline.bind(("127.0.0.1", 0))
        _, refused = attempt("offline", provider_port=offline.getsockname()[1])
    assert refused["phase"] == "rejected", refused
    assert refused["result"]["reason"] == "antigravity_provider_unavailable", refused
    assert provider.calls == [] and not effects.exists(), refused
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        port = unused.getsockname()[1]
    _, refused = attempt("startup_failed", provider_port=port)
    assert refused["phase"] == "rejected", refused
    assert refused["result"]["reason"] == "antigravity_provider_unavailable", refused
    assert provider.calls == [] and not effects.exists(), refused
    first, delivered = attempt("accepted")
    assert delivered["phase"] == "delivered", delivered
    assert delivered["native_session_id"] == delivered["session_id"]
    assert effects.read_text().splitlines() == ["memory", "return"]
    assert not list(state.glob("catalog-check-*"))
    assert all(b"Reply with the catalog check marker:" not in item.read_bytes()
               for item in state.rglob("*") if item.is_file())
    lost, uncertain = attempt("lost")
    assert uncertain["phase"] == "provider_uncertain", uncertain
    assert provider.calls == [first["event_id"], first["event_id"], lost["event_id"]], provider.calls
    held = select("held")
    with ThreadPoolExecutor(max_workers=1) as pool:
        foreground = pool.submit(run, held)
        try:
            assert provider.arrived.wait(timeout=8), "Antigravity did not reach the held provider"
            j.stop()
        finally:
            provider.release.set()
        try:
            foreground.result(timeout=10)
        except (AssertionError, ValueError):
            # Shutdown can close the command socket before its final read.
            # The restarted Gateway's canonical journal decides the outcome.
            pass
    j.start()
    j.wait_control_socket(j.socket)
    assert j.read("matrix", "antigravity", "status", first["event_id"])["result"] == delivered
    assert j.read("matrix", "goose", "run", json.dumps(lost))["result"] == uncertain
    interrupted = j.read("matrix", "antigravity", "status", held["event_id"])["result"]
    assert interrupted["phase"] == "provider_uncertain" and interrupted["native_session_id"]
    assert j.read("matrix", "goose", "run", json.dumps(held))["result"] == interrupted
    assert provider.calls == [first["event_id"], first["event_id"], lost["event_id"], held["event_id"]]
    assert effects.read_text().splitlines() == ["memory", "return"]
    print("PASS real Antigravity SDK, canonical original, selected MCP read, uncertainty and restart")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: antigravity_foreground_io.py GATEWAY SDK_PYTHON")
    journey = Inputs(sys.argv[1])
    with ThreadingHTTPServer(("127.0.0.1", 0), Provider) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            qualify(journey, sys.argv[2], server)
        finally:
            journey.close()
            server.shutdown()
            thread.join()
