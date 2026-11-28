#!/usr/bin/env python3
"""Qualify the real Codex successor boundary with an isolated loopback model."""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import uuid

PROMPT = "Continue the story by reviewing the second scene."
ANSWER = "The second scene is ready for review."
WORK = "Keep the main character's name."
PENDING = str(uuid.UUID(int=1))
RESOLVED = str(uuid.UUID(int=2))
MODEL_USAGE = {"input_tokens": 210, "output_tokens": 8, "total_tokens": 218}


class Model(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        size = int(self.headers["Content-Length"])
        assert self.path == "/v1/responses" and size <= 1024 * 1024
        packet = json.loads(self.rfile.read(size))
        self.server.packets.append(packet)
        events = [
            {"type": "response.created", "response": {"id": "fixture-response"}},
            {"type": "response.output_item.done", "item": {
                "type": "message", "role": "assistant", "id": "fixture-answer",
                "phase": "final_answer",
                "content": [{"type": "output_text", "text": self.server.answer}],
            }},
            {"type": "response.completed", "response": {
                "id": "fixture-response", "usage": MODEL_USAGE,
            }},
        ]
        body = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextlib.contextmanager
def connection(binary, state):
    # An isolated app-server profile and loopback-only inference configuration.
    settings = {"PATH": os.environ["PATH"], "CODEX_HOME": str(state)}
    with (state / "native.log").open("a+", errors="replace") as log:
        process = subprocess.Popen(
            [binary, "app-server", "--listen", "stdio://"], cwd=state,
            env=settings, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=log, text=True,
        )
        inbox = queue.Queue(maxsize=256)

        def collect():
            for line in process.stdout:
                inbox.put(json.loads(line), timeout=2)
            inbox.put(None, timeout=2)

        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        sequence = 0
        seen = []

        def send(message):
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()

        def wait(match):
            deadline = time.monotonic() + 20
            while remaining := deadline - time.monotonic():
                if remaining <= 0:
                    break
                message = inbox.get(timeout=remaining)
                assert message is not None, "Fixture App Server exited"
                seen.append(message)
                if match(message):
                    return message
            raise AssertionError("Fixture App Server response was missing")

        def rpc(method, params, *, error=False):
            nonlocal sequence
            sequence += 1
            ident = sequence
            send({"id": ident, "method": method, "params": params})
            reply = wait(lambda message: message.get("id") == ident)
            assert ("error" in reply) == error, reply
            return reply["error" if error else "result"]

        try:
            rpc("initialize", {"clientInfo": {"name": "checkpoint-fixture", "version": "1.0"},
                               "capabilities": {"experimentalApi": True}})
            send({"method": "initialized"})
            yield rpc, wait, seen
        except Exception:
            log.flush()
            log.seek(0, os.SEEK_END)
            log.seek(max(0, log.tell() - 2500))
            print(log.read(), file=sys.stderr)
            raise
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            reader.join(timeout=2)


@contextlib.contextmanager
def loopback_model(state):
    with ThreadingHTTPServer(("127.0.0.1", 0), Model) as model:
        model.packets = []
        model.answer = ANSWER
        thread = threading.Thread(target=model.serve_forever, daemon=True)
        thread.start()
        try:
            (state / "config.toml").write_text(f"""model = "gpt-5.4"
model_provider = "fixture"
approval_policy = "never"
sandbox_mode = "read-only"
[features]
plugins = false
[model_providers.fixture]
name = "Local fixture"
base_url = "http://127.0.0.1:{model.server_port}/v1"
wire_api = "responses"
requires_openai_auth = false
request_max_retries = 0
stream_max_retries = 0
""")
            yield model
        finally:
            model.shutdown()
            thread.join(timeout=5)


def qualify(binary):
    with tempfile.TemporaryDirectory(prefix="daimon-project-successor-") as directory:
        state = Path(directory)
        with loopback_model(state) as model:
            missing = str(uuid.uuid4())
            with connection(binary, state) as (rpc, wait, seen):
                def refusal(thread_id):
                    result = rpc("thread/resume", {"threadId": thread_id, "excludeTurns": True}, error=True)
                    assert result["code"] == -32600, result
                    assert result["message"] == f"no rollout found for thread id {thread_id}", result

                refusal(missing)
                successor = rpc("thread/start", {"cwd": directory})["thread"]["id"]
                assert successor != missing
                refusal(successor)
                assert model.packets == []
                checkpoint = json.dumps({
                    "kind": "gateway_project_recovery", "status": "verified",
                    "repositories": [{"work": [{"kind": "decision", "text": WORK}]}],
                    "effectReceipts": [
                        {"original": PENDING, "disposition": "unresolved"},
                        {"original": RESOLVED, "disposition": "result_retained"},
                    ],
                })
                started = time.monotonic()
                started_turn = rpc("turn/start", {
                    "threadId": successor,
                    "input": [{"type": "text", "text": PROMPT, "text_elements": []}],
                    "additionalContext": {"gateway.history.00000000": {
                        "kind": "untrusted", "name": "gateway_history", "value": checkpoint,
                    }},
                })["turn"]["id"]
                terminal = wait(lambda event: event.get("method") == "turn/completed"
                                and event["params"]["threadId"] == successor)
                assert terminal["params"]["turn"]["id"] == started_turn, terminal
                assert terminal["params"]["turn"]["status"] == "completed", terminal
                elapsed = round((time.monotonic() - started) * 1000)

                def usage_event(event):
                    return (event.get("method") == "thread/tokenUsage/updated"
                            and event["params"]["threadId"] == successor
                            and event["params"]["turnId"] == started_turn)

                usage = next((event for event in reversed(seen) if usage_event(event)), None)
                if usage is None:
                    usage = wait(usage_event)
                tokens = usage["params"]["tokenUsage"]["last"]["totalTokens"]
                assert tokens == MODEL_USAGE["total_tokens"], usage

            with connection(binary, state) as (rpc, _, _):
                resumed = rpc("thread/resume", {"threadId": successor, "excludeTurns": True})
                assert resumed["thread"]["id"] == successor
                history = rpc("thread/read", {"threadId": successor, "includeTurns": True})["thread"]
                assert len(history["turns"]) == 1, history
                assert history["turns"][0]["id"] == started_turn
                assert ANSWER in json.dumps(history)

            assert len(model.packets) == 1, len(model.packets)
            packet = json.dumps(model.packets[0])
            assert packet.count(PROMPT) == 1, "The new original was duplicated"
            assert packet.count(json.dumps(checkpoint)[1:-1]) == 1, (
                "The exact checkpoint was absent or duplicated at inference"
            )
            print(json.dumps({"fixture": "native_codex_project_successor", "turn_ms": elapsed,
                              "loopback_calls": len(model.packets), "reported_fixture_tokens": tokens,
                              "real_provider_calls": 0, "native_user_turns": 1,
                              "metadata_only_successor_resumable": False,
                              "materialized_successor_resumed": True}), flush=True)


if __name__ == "__main__":
    qualify(str(Path(sys.argv[1]).resolve()))
