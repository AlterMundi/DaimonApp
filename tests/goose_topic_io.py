#!/usr/bin/env python3
"""Qualify an owned Goose topic through Gateway with the real ACP binary and a local provider."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import sqlite3
import sys
from threading import Thread
import uuid

from conversation_routing_io import CanonicalRouting


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(body)
        answer = "History retained." if "remember-heron-381" in json.dumps(body["messages"]) else "History absent."
        events = []
        for delta, reason in [({"role": "assistant", "content": answer}, None), ({}, "stop")]:
            events.append(dict(id="fixture", created=1766229303, model="gpt-4o-mini",
                               object="chat.completion.chunk",
                               choices=[dict(index=0, delta=delta, finish_reason=reason)]))
        data = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
        encoded = data.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def qualify(binary, goose):
    journey = CanonicalRouting(binary)
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    provider.requests = []
    serving = Thread(target=provider.serve_forever, daemon=True)
    serving.start()
    try:
        journey.start()
        for topic in (1, 7):
            journey.admit("Seed an isolated topic.", topic=topic)
            journey.wait(lambda: journey.has("Initial goal turn delivered.", topic))
            journey.idle()
        journey.stop()

        cwd = journey.root / "topic"
        cwd.mkdir(mode=0o700)
        with sqlite3.connect(journey.root / "state.sqlite") as db:
            assert db.execute("UPDATE sessions SET cwd=? WHERE thread_id=7", (str(cwd),)).rowcount == 1
        profile = journey.root / "goose.json"
        key = journey.root / "local-provider.key"
        key.touch(mode=0o600)
        key.write_text("fixture-only")
        body = dict(beingRef="dm:being:v1:" + "A" * 43, embodimentId="embodiment:fixture-goose",
                    incarnationId="fixture", manifestHash="a" * 64)
        status = journey.root / "body.py"
        status.write_text("import json\nprint(" + repr(json.dumps(dict(
            schema="dm.runtime.status/v1", integrity="ok", being_ref=body["beingRef"],
            manifest_hash=body["manifestHash"], local_origin=dict(
                embodiment_id=body["embodimentId"], incarnation_id=body["incarnationId"])))) + ")\n")
        status_command = ["/usr/bin/python3", str(status)]
        config = journey.root / "config" / "goose"
        config.mkdir(parents=True)
        extensions = {name: dict(name=name, type="platform", enabled=False)
                      for name in ("developer", "extensionmanager", "summon", "tom", "todo", "summarize")}
        (config / "config.yaml").write_text(json.dumps(dict(extensions=extensions)))
        store_id = str(uuid.uuid4())
        store_identity = journey.root / "goose-topic-store-id"
        store_identity.touch(mode=0o600)
        store_identity.write_text(store_id + "\n")
        profile.touch(mode=0o600)
        profile_doc = dict(binary=goose, cwd=str(cwd), stateRoot=str(journey.root),
                           body=body, matrixStatusCommand=status_command, provider="openai",
                           model="gpt-4o-mini", providerKeyFile=str(key), providerPort=provider.server_port)
        profile.write_text(json.dumps(profile_doc))
        worker = Path(__file__).resolve().parents[1] / "adapters" / "acp" / "gateway-worker.mjs"
        command = ["/usr/bin/node", str(worker), "--profile", str(profile)]
        journey.config.write_text(journey.config.read_text()
            + "\ntelegram_projection=true\ntelegram_entry_projection=true\n"
            + journey.target_config.replace('name="Alpha"', 'name="Alpha"\nharness="goose"')
            + f"""
[interaction.goose_foreground]
interaction_direct=true
goose_topic_store_id="{store_id}"
worker_command={json.dumps(command)}
[interaction.goose_foreground.transport]
command={json.dumps(status_command)}
source={{kind="body",being_ref="{body['beingRef']}",embodiment_id="{body['embodimentId']}"}}
timeout_seconds=5
""")

        def state(original):
            rows = journey.row("""
                SELECT i.phase,t.status,t.native_thread_id,t.execution_native_scope,t.assistant_text
                FROM interaction_sources s JOIN interaction_instructions i ON i.input_id=s.id
                JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') WHERE s.event_id=?
                """, (str(original),))
            return rows[0] if rows else (None,) * 5

        def settled(original):
            journey.wait(lambda: state(original)[1] in {"completed", "failed"}, seconds=20)
            return state(original)

        journey.start()
        journey.wait_control_socket(journey.socket)
        first = journey.admit("Remember remember-heron-381 and acknowledge.", topic=7)
        phase, turn, session, scope, answer = settled(first)
        assert (phase, turn, answer) == ("accepted", "completed", "History retained."), state(first)
        assert session and scope.startswith("goose-acp/")
        journey.wait(lambda: journey.has("History retained.", 7))
        journey.stop()
        journey.start()
        journey.wait_control_socket(journey.socket)

        original = str(uuid.uuid4())
        binding = journey.read("presentation", "list", "0", "0")["result"]["binding"]
        request = dict(binding=binding, id=original, text="#Alpha Recall the previous synthetic original.")
        assert journey.read("input", "submit-human", json.dumps(request))["result"]["new_input"]
        assert settled(original) == ("accepted", "completed", session, scope, "History retained."), state(original)
        assert len(provider.requests) == 2
        assert "remember-heron-381" in json.dumps(provider.requests[1]["messages"])
        retained = journey.read("input", "submit-human", json.dumps(request))["result"]
        assert retained.get("new_input") is False, retained
        assert journey.row("SELECT count(*) FROM turns WHERE execution_harness='goose'") == [(2,)]
        assert len(provider.requests) == 2

        journey.stop()
        other_store = journey.root / "other-goose-store"
        other_store.mkdir(mode=0o700)
        # The second store can resolve the same native ID. Gateway still owns
        # the original store identity and must refuse before opening a session.
        for part in ("config", "data"):
            shutil.copytree(journey.root / part, other_store / part)
        other_identity = other_store / store_identity.name
        other_identity.touch(mode=0o600)
        other_identity.write_text(str(uuid.uuid4()) + "\n")
        profile.write_text(json.dumps({**profile_doc, "stateRoot": str(other_store)}))
        journey.start()
        journey.wait_control_socket(journey.socket)
        replaced_store = journey.admit("Do not load another session store.", topic=7)
        assert settled(replaced_store) == ("retained_unsent", "failed", None, None, None), state(replaced_store)
        assert len(provider.requests) == 2

        journey.stop()
        profile.write_text(json.dumps(profile_doc))
        moved = journey.root / "different-topic-workspace"
        moved.mkdir(mode=0o700)
        with sqlite3.connect(journey.root / "state.sqlite") as db:
            assert db.execute("UPDATE sessions SET cwd=? WHERE thread_id=7", (str(moved),)).rowcount == 1
        journey.start()
        journey.wait_control_socket(journey.socket)
        refused = journey.admit("Do not load the other workspace.", topic=7)
        assert settled(refused) == ("retained_unsent", "failed", None, None, None), state(refused)
        assert len(provider.requests) == 2
        print("Goose resumed the same scoped topic across Gateway restart and both surfaces, "
              "deduplicated the original and refused a mismatched store or workspace.")
    finally:
        journey.close()
        provider.shutdown()
        provider.server_close()
        serving.join()


if __name__ == "__main__":
    qualify(str(Path(sys.argv[1]).absolute()), str(Path(sys.argv[2]).absolute()))
