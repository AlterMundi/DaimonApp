#!/usr/bin/env python3
"""Joined Gateway harness qualification with signed disposable Matrix and native DMK.

Use PYTHONPATH=<Matrix>/src:<Matrix> and a disposable test environment.
All identity, model output and memory content belong to fixtures.
"""

from http.server import ThreadingHTTPServer
import importlib.util
import json
import os
import re
from pathlib import Path
import shlex
import socketserver
import subprocess
import sys
from threading import Thread
from types import SimpleNamespace
import unittest
import uuid

import antigravity_foreground_io as foreground
from claude_provider_fixture import ANSWER, REVOKED_ANSWER, ClaudeProvider
from conversation_input_control_io import Inputs


def matrix_fixture():
    spec = importlib.util.spec_from_file_location(
        "app_matrix_fixture", Path(__file__).with_name("matrix_execution.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.AuthenticatedWeHostTests


def selected_memory(root, python, scripts, being, original, engine):
    database = root / "fixture-dmk.db"
    result = subprocess.run(
        [python, "-B", "-c", """
import json
import sys
sys.path.insert(0, sys.argv[1])
import memoryctl as memory
memory.init_db()
selected = memory.add_text("library", "Selected qualification record", sys.argv[2])
memory.add_text("library", "Unselected control", "A decoy record.")
print(json.dumps(memory._read_chapter(selected)))
""", str(scripts), foreground.MARKER],
        env={"PATH": "/usr/bin:/bin", "HOME": str(root), "HMK_AGENT_MEMORY_BASE": str(root),
             "HMK_DB_PATH": str(database)},
        text=True, capture_output=True, check=True, timeout=10,
    )
    selected = json.loads(result.stdout)
    binding = root / "dmk.json"
    body_ref = f"fixture:{engine}"
    binding.touch(mode=0o600)
    binding.write_text(json.dumps({
        "schema": "hmk.deep-recall.binding/v1", "being_ref": being, "body_ref": body_ref,
        "pools": [{"name": "main", "database": str(database)}],
    }))
    return {
        "command": [python, "-B", str(scripts / "dmk_mcp.py"), "--binding", str(binding)],
        "inputId": original, "pool": "main", "recordUid": selected["record_uid"],
        "revision": selected["revision"], "bodyRef": body_ref,
    }, database


def configure_worker(engine, executable, root, state, profile, port, config):
    if engine == "antigravity":
        config.update(node="/usr/bin/node", providerPort=port)
        return [executable, "-B", str(foreground.WORKER), "--profile", str(profile)]

    key = root / "provider-fixture"
    key.touch(mode=0o600)
    key.write_text("fixture-only\n")
    if engine == "claude":
        wrapper = root / "claude-loopback"
        wrapper.write_text(f"""#!/bin/sh
export ANTHROPIC_BASE_URL=http://127.0.0.1:{port}
exec {shlex.quote(executable)} "$@"
""")
        wrapper.chmod(0o700)
        del config["stateRoot"]
        config.update(sdk=os.environ["CLAUDE_TEST_SDK_PATH"], binary=str(wrapper), cwd=str(root),
                      home=str(state), configurationDirectory=str(state), apiKeyFile=str(key),
                      cliVersion=os.environ.get("CLAUDE_TEST_CLI_VERSION", "2.1.325"),
                      maxBudgetUsd=0.1, displayName="Fixture CompAII · claude@fixture")
        worker = os.environ.get("CLAUDE_TEST_WORKER_PATH", str(
            foreground.ROOT / "adapters/claude/gateway-worker.mjs"
        ))
        return ["/usr/bin/node", worker, "--profile", str(profile)]

    home = state / "config" / "goose"
    home.mkdir(parents=True)
    extensions = {name: {"name": name, "type": "platform", "enabled": False}
                  for name in ("developer", "extensionmanager", "summon", "tom", "todo", "summarize")}
    (home / "config.yaml").write_text(json.dumps({"extensions": extensions}))
    wrapper = root / "goose-loopback"
    wrapper.write_text(f"""#!/bin/sh
export OPENAI_HOST=http://127.0.0.1:{port}
exec {shlex.quote(executable)} "$@"
""")
    wrapper.chmod(0o700)
    config.update(binary=str(wrapper), cwd=str(root), provider="openai", providerKeyFile=str(key))
    worker = foreground.ROOT / "adapters/acp/gateway-worker.mjs"
    return ["/usr/bin/node", str(worker), "--profile", str(profile)]


def qualify(engine, gateway, executable, scripts, *, interaction=False):
    parent = matrix_fixture()

    class SignedForeground(parent):
        deliver_followup = interaction

        def _host_command(self, root, socket, service, capabilities):
            import daimon_matrix
            from daimon_matrix.client import CLIENT_CONFIG_SCHEMA_V3

            origin = service.ledger.local_origin
            source = {"being_ref": service.ledger.authority.manifest.being_ref,
                      "embodiment_id": origin["embodiment_id"]}
            binding = {"schema": "daimon-gateway.matrix-we-binding/v1", "source": source}
            for purpose, cap in capabilities.items():
                config = root / f"{purpose}.json"
                key = root / f"{purpose}.key"
                config.touch(mode=0o600)
                config.write_text(json.dumps({
                    "schema": CLIENT_CONFIG_SCHEMA_V3, "capability": cap.descriptor,
                    "expected_server": origin, "runtime_id": service.runtime_id,
                    "runtime_label": service.runtime_label,
                }))
                key.touch(mode=0o600)
                key.write_bytes({"conversation": b"w", "observation": b"o"}[purpose] * 32)
                binding[purpose] = dict(socket=str(socket), client_config=str(config), client_key=str(key))
            document = root / "matrix.json"
            document.touch(mode=0o600)
            document.write_text(json.dumps(binding))
            # The SDK fixture has a fixed clock for deterministic signed events.
            # Use the real CLI operator against that same clock in its host process.
            wrapper = root / "matrix-host.py"
            runtime_paths = [str(foreground.ROOT / "scripts"), str(Path(daimon_matrix.__file__).parents[1])]
            runtime_paths.extend(path for path in sys.path if Path(path).name == "site-packages")
            wrapper.write_text(f"""
import sys
from dataclasses import replace
sys.path[:0] = {runtime_paths!r}
import matrix_operator as operator
select = operator.configured_client
def configured(*args, **kwargs):
    client = select(*args, **kwargs)
    clock = lambda: {service.clock()}
    return replace(client, messaging=replace(client.messaging, clock=clock),
                   observation=replace(client.observation, clock=clock))
operator.configured_client = configured
operator.main()
""")
            return source, [sys.executable, "-B", str(wrapper), "--binding", str(document)]

        def _check_round_trip(self, root, socket, fixture, service, capabilities, original,
                              author, body, return_attempts):
            source, host = self._host_command(root, socket, service, capabilities)
            being = source["being_ref"]
            origin = fixture.ledger_b.local_origin
            live_status = subprocess.run(
                [*host, "--body-status"], input=json.dumps({"source": source}),
                text=True, capture_output=True, check=True, timeout=5,
            )
            status = json.loads(live_status.stdout)
            self.assertEqual(status["local_origin"]["embodiment_id"], body)
            memory = None
            if engine != "claude":
                memory, database = selected_memory(root, sys.executable, scripts, being, original["message_id"], engine)
                initial_database = database.read_bytes()
            journey = Inputs(gateway)
            self.addCleanup(journey.close)
            if os.environ.get("FOREGROUND_TEST_WITHOUT_TELEGRAM_CODEX") == "1":
                gateway_config = re.sub(r'^(bot_token_file|api_base)=.*\n', '', journey.config.read_text(),
                                        flags=re.MULTILINE)
                gateway_config = gateway_config.replace(
                    "[telegram]\n",
                    '[telegram]\nexternal_polling=true\nexternal_bot_id=123\n'
                    'api_base="http://127.0.0.1:1"\n',
                )
                journey.config.write_text(gateway_config)
                (journey.root / "codex").write_text("#!/bin/sh\nexit 7\n")
            profile = root / "worker.json"
            state = root / "native-state"
            state.mkdir(mode=0o700)
            profile.touch(mode=0o600)

            class InteractionProvider(ClaudeProvider):
                def do_POST(self):
                    self.server.current = self.server.journey.row(
                        "SELECT json_extract(doc,'$.private_matrix_origin.message_id') FROM conversation_inputs WHERE id=?",
                        (self.server.human_original,),
                    )[0][0]
                    super().do_POST()

            handler = InteractionProvider if interaction else (
                ClaudeProvider if engine == "claude" else foreground.Provider)
            with ThreadingHTTPServer(("127.0.0.1", 0), handler) as provider:
                provider.journey = journey
                provider.calls = []
                provider.failure = None
                provider.mode = "accepted"
                provider.engine = engine
                provider.model = {"antigravity": "fixture", "goose": "gpt-4o-mini",
                                  "claude": "claude-sonnet-4-5"}[engine]
                provider.body = body
                if engine == "claude":
                    provider.display_name = "Fixture CompAII · claude@fixture"
                provider.tool_prefix = "" if engine == "antigravity" else "matrix__"
                provider.current = original["message_id"]
                provider.original = "Material for the selected turn"
                config = {
                    "stateRoot": str(state), "model": provider.model, "matrixStatusCommand": host,
                    "body": {"beingRef": being, "embodimentId": body, "incarnationId": origin["incarnation_id"],
                             "manifestHash": status["manifest_hash"]},
                }
                if memory:
                    config["selectedMemory"] = memory
                command = configure_worker(engine, executable, root, state, profile, provider.server_port, config)
                if interaction and scripts:
                    python = os.environ.get("CLAUDE_TEST_DMK_PYTHON", sys.executable)
                    selected, _ = selected_memory(root, python, scripts, being, provider.current, engine)
                    config["sharedDmk"] = {
                        "command": selected["command"][:-2],
                        "bindingFile": selected["command"][-1],
                        "bodyRef": selected["bodyRef"],
                    }
                    provider.dmk_marker = foreground.MARKER
                    provider.dmk_record = {"action": "read", "pool": selected["pool"],
                                           "record_uid": selected["recordUid"],
                                           "expected_revision": selected["revision"]}
                    provider.worker_profile = profile
                if interaction and os.environ.get("FOREGROUND_TEST_SHARED_SKILLS") == "1":
                    shared = root / "shared-agent-skills"
                    skill = shared / "fixture-skill"
                    skill.mkdir(parents=True)
                    provider.skill_name = "compaii-shared:fixture-skill"
                    provider.skill_marker = "Readback from the shared skill directory."
                    provider.skill_file = skill / "SKILL.md"
                    provider.skill_file.write_text(
                        "---\nname: fixture-skill\ndescription: A synthetic shared skill.\n---\n"
                        + provider.skill_marker
                    )
                    config["sharedSkillsDirectory"] = str(shared)
                profile.write_text(json.dumps(config))
                original_host = ""
                if interaction:
                    sender_source, sender = self._start_sender(root, fixture, service, capabilities, body)
                    original_host = f"""
[interaction.claude_foreground.interaction_origin]
command={json.dumps([*sender,"--we-origin",body])}
source={{kind="body",being_ref="{being}",embodiment_id="{sender_source["embodiment_id"]}"}}
timeout_seconds=5
"""
                journey.config.write_text(journey.config.read_text() + f"""
[interaction.{engine}_foreground]
worker_command={json.dumps(command)}
[interaction.{engine}_foreground.transport]
command={json.dumps(host)}
source={{kind="body", being_ref="{being}", embodiment_id="{body}"}}
timeout_seconds=5
""" + original_host)
                server = Thread(target=provider.serve_forever, daemon=True)
                server.start()
                try:
                    journey.start()
                    journey.wait_control_socket(journey.socket)
                    if interaction:
                        self._interaction_exchange(journey, provider, fixture, body, return_attempts)
                        return
                    selected = dict(cursor=None, event_id=original["message_id"], author=author,
                                    thread_id=original["thread_id"])
                    reply = journey.read("matrix", engine, "run", json.dumps(selected))["result"]
                    self.assertIsNone(provider.failure)
                    self.assertEqual(reply["phase"], "delivered", reply)
                    # The original Claude-only journal did not emit an engine field.
                    self.assertEqual(reply.get("engine", "claude"), engine)
                    self.assertTrue(reply["native_session_id"])
                    self.assertEqual(return_attempts, [reply["result"]["send_id"]])
                    self.assertEqual(provider.calls, [original["message_id"]] * 2)
                    if memory:
                        self.assertEqual(database.read_bytes(), initial_database)
                    synced = fixture.ledger_a
                    result = reply["result"]["delivery"]
                    event = synced.event(result["message_id"])
                    if event is None and hasattr(synced, "conversation_evidence"):
                        event = next((row for row in synced.conversation_evidence()
                                      if row["event_id"] == result["message_id"]), None)
                    self.assertIsNotNone(event)
                    self.assertEqual(event["origin"]["embodiment_id"], body)
                    self.assertEqual(event["payload"]["intent"]["thread_id"], original["thread_id"])
                    expected = ANSWER if engine == "claude" else foreground.MARKER
                    self.assertIn(expected, event["payload"]["body"]["text"])
                    receipt = synced.event(result["receipt_event_id"])
                    self.assertEqual(receipt["origin"]["embodiment_id"], author)
                    self.assertEqual(receipt["payload"]["message_ref"]["event_hash"], result["message_hash"])
                    journey.stop()
                    journey.start()
                    journey.wait_control_socket(journey.socket)
                    status = journey.read("matrix", engine, "status", original["message_id"])["result"]
                    self.assertEqual(status, reply)
                    observed = journey.read("matrix", engine, "run", json.dumps(selected))["result"]
                    self.assertEqual(observed, reply)
                    self.assertEqual(provider.calls, [original["message_id"]] * 2)
                    self.assertEqual(return_attempts, [reply["result"]["send_id"]])
                    if os.environ.get("FOREGROUND_TEST_WITHOUT_TELEGRAM_CODEX") == "1":
                        self.assertEqual(journey.telegram_methods, [])
                        self.assertEqual(journey.rpc, [])
                finally:
                    journey.stop()
                    provider.shutdown()
                    server.join()

        def _start_sender(self, root, fixture, receiver, capabilities, body):
            from daimon_matrix.daemon import serve_connection
            from daimon_matrix.scopes import ScopeResolver
            from daimon_matrix.service import HostedWeave

            directory = root / "interaction-author"
            directory.mkdir(mode=0o700)
            socket = directory / "sdk.sock"
            now = receiver.clock()

            def peer(recipient):
                self.assertEqual(recipient, body)
                return None, SimpleNamespace(call=lambda payload, **_: receiver.we_lane.intake(payload))

            sender = HostedWeave(
                fixture.ledger_a, fixture.signers["legion"],
                {cap.capability_id: cap for cap in capabilities.values()}, lambda: now,
                "dm:runtime:v1:" + "X" * 43, "interaction-author-test",
                scopes=ScopeResolver(fixture.ledger_a, clock=lambda: now),
                peer_context=SimpleNamespace(configured=peer, authority=fixture.authority,
                                             local_origin=fixture.ledger_a.local_origin),
                we_lane=fixture.lane("legion", at_ms=now),
            )

            class Handler(socketserver.BaseRequestHandler):
                def handle(self):
                    serve_connection(SimpleNamespace(service=sender), self.request)

            server = socketserver.UnixStreamServer(str(socket), Handler)
            socket.chmod(0o600)
            worker = Thread(target=server.serve_forever, daemon=True)
            worker.start()
            self.addCleanup(server.server_close)
            self.addCleanup(worker.join)
            self.addCleanup(server.shutdown)
            return self._host_command(directory, socket, sender, capabilities)

        def _interaction_exchange(self, journey, provider, fixture, receiver, return_attempts):
            from fastapi.testclient import TestClient
            from dashboard.app import create_app
            from dashboard.provider import Provider

            self.assertEqual(journey.row(
                "SELECT creator_user_id,codex_thread_id FROM sessions WHERE chat_id=100 AND thread_id=1"
            ), [(100, None)])
            config = {"receiver_config":str(journey.config), "state_dir":str(journey.root/"dashboard"),
                      "origin":"https://example.test","bot_id":123}
            with TestClient(create_app(config, Provider(config), lambda raw, bot: int(raw)),
                            base_url=config["origin"]) as client:
                headers = {"origin":config["origin"]}
                issued = client.post("/api/session", json={"init_data":"100"}, headers=headers)
                headers["authorization"] = "Bearer " + issued.json()["session_token"]
                page = client.get("/api/interaction", headers=headers).json()
                self.assertIs(page["can_select_claude"], True)
                headers["x-dashboard-csrf"] = page["csrf"]
                provider.human_original = str(uuid.uuid4())
                request = {"binding":page["binding"], "id":provider.human_original,
                           "text":provider.original, "target":"claude"}
                submitted = client.post("/api/interaction/inputs", json=request, headers=headers)
                self.assertEqual(submitted.status_code, 200, submitted.text)
                journey.wait(lambda: bool(provider.failure) or journey.row(
                    "SELECT phase FROM conversation_inputs WHERE id=?", (request["id"],)
                )[0][0] in {"matrix_replied", "retained_unsent", "uncertain"}, seconds=40)
                self.assertIsNone(provider.failure)
                status = client.get("/api/interaction/inputs/"+request["id"], headers=headers).json()
                self.assertEqual(status["phase"], "matrix_replied")
                result = status["claude_reply"]
                self.assertIn(ANSWER, result["text"])
                signed = next(row for row in fixture.ledger_a.conversation_evidence()
                              if row["event_id"] == result["message_id"])
                self.assertEqual(signed["origin"]["embodiment_id"], receiver)
                self.assertEqual(signed["payload"]["body"]["text"], result["text"])
                first_calls = 3 if hasattr(provider, "skill_name") else 2
                self.assertEqual(provider.calls, [provider.current] * first_calls)
                self.assertEqual(len(return_attempts), 1)
                self.assertEqual(journey.telegram_methods, [])
                self.assertEqual(journey.rpc, [])
                journey.stop()
                journey.start()
                journey.wait_control_socket(journey.socket)
                self.assertEqual(client.post("/api/interaction/inputs", json=request, headers=headers)
                                 .json()["claude_reply"], result)
                self.assertEqual(provider.calls, [provider.current] * first_calls)
                self.assertEqual(len(return_attempts), 1)
                first_event = provider.current
                provider.previous_session = journey.row(
                    "SELECT json_extract(submission,'$.native_session_id') FROM interaction_matrix_requests WHERE source_event=?",
                    (first_event,),
                )[0][0]
                provider.previous_original = provider.original
                provider.original = "What did we discuss in the first turn?"
                provider.human_original = str(uuid.uuid4())
                followup = {**request, "id": provider.human_original, "text": provider.original}
                submitted = client.post("/api/interaction/inputs", json=followup, headers=headers)
                self.assertEqual(submitted.status_code, 200, submitted.text)
                journey.wait(lambda: bool(provider.failure) or journey.row(
                    "SELECT phase FROM conversation_inputs WHERE id=?", (followup["id"],)
                )[0][0] in {"matrix_replied", "retained_unsent", "uncertain"}, seconds=40)
                self.assertIsNone(provider.failure)
                status = client.get("/api/interaction/inputs/"+followup["id"], headers=headers).json()
                self.assertEqual(status["phase"], "matrix_replied")
                self.assertIn("I retained the first turn.", status["claude_reply"]["text"])
                self.assertNotEqual(provider.current, first_event)
                self.assertEqual(provider.calls, [first_event] * first_calls + [provider.current])
                self.assertEqual(len(return_attempts), 2)
                self.assertEqual(journey.telegram_methods, [])
                self.assertEqual(journey.rpc, [])
                if not hasattr(provider, "dmk_record"):
                    return
                provider.previous_scope = journey.row(
                    "SELECT json_extract(submission,'$.native_session_scope') FROM interaction_matrix_requests WHERE source_event=?",
                    (provider.current,),
                )[0][0]
                # Revoke the provider's direct DMK route without changing
                # the receiving Matrix body or the Interaction conversation.
                worker = json.loads(provider.worker_profile.read_text())
                del worker["sharedDmk"]
                provider.worker_profile.write_text(json.dumps(worker))
                del provider.dmk_record
                provider.dmk_revoked = True
                provider.human_original = str(uuid.uuid4())
                provider.original = "What can you see after the access change?"
                revoked = {**request, "id": provider.human_original, "text": provider.original}
                submitted = client.post("/api/interaction/inputs", json=revoked, headers=headers)
                self.assertEqual(submitted.status_code, 200, submitted.text)
                journey.wait(lambda: bool(provider.failure) or journey.row(
                    "SELECT phase FROM conversation_inputs WHERE id=?", (revoked["id"],)
                )[0][0] in {"matrix_replied", "retained_unsent", "uncertain"}, seconds=40)
                self.assertIsNone(provider.failure)
                status = client.get("/api/interaction/inputs/"+revoked["id"], headers=headers).json()
                self.assertEqual(status["phase"], "matrix_replied")
                self.assertEqual(status["claude_reply"]["text"], REVOKED_ANSWER)
                self.assertEqual(len(return_attempts), 3)
                if not hasattr(provider, "skill_file"):
                    return
                provider.previous_session = journey.row(
                    "SELECT json_extract(submission,'$.native_session_id') FROM interaction_matrix_requests WHERE source_event=?",
                    (provider.current,),
                )[0][0]
                provider.dmk_revoked = False
                provider.old_skill_marker = provider.skill_marker
                provider.skill_marker = "Updated shared skill instructions."
                provider.skill_file.write_text(
                    provider.skill_file.read_text().replace(provider.old_skill_marker, provider.skill_marker)
                )
                provider.human_original = str(uuid.uuid4())
                provider.original = "Load the latest shared skill instructions."
                updated = {**request, "id": provider.human_original, "text": provider.original}
                submitted = client.post("/api/interaction/inputs", json=updated, headers=headers)
                self.assertEqual(submitted.status_code, 200, submitted.text)
                journey.wait(lambda: bool(provider.failure) or journey.row(
                    "SELECT phase FROM conversation_inputs WHERE id=?", (updated["id"],)
                )[0][0] in {"matrix_replied", "retained_unsent", "uncertain"}, seconds=40)
                self.assertIsNone(provider.failure)
                status = client.get("/api/interaction/inputs/"+updated["id"], headers=headers).json()
                self.assertEqual(status["phase"], "matrix_replied")
                self.assertEqual(status["claude_reply"]["text"], provider.skill_marker)
                self.assertEqual(len(return_attempts), 4)

    result = unittest.TextTestRunner(verbosity=2).run(SignedForeground("test_exact_original_and_signed_same_thread_return"))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    if len(sys.argv) < 4 or sys.argv[1] not in ("antigravity", "claude", "goose"):
        raise SystemExit("Usage: foreground_signed_io.py ENGINE GATEWAY NATIVE_EXECUTABLE [DMK_SCRIPTS]")
    engine, gateway, executable = sys.argv[1:4]
    if len(sys.argv) != (4 if engine == "claude" else 5):
        raise SystemExit("Supply the DMK scripts directory for Antigravity and Goose.")
    interaction = engine == "claude" and os.environ.get("FOREGROUND_TEST_INTERACTION") == "1"
    if interaction:
        os.environ["FOREGROUND_TEST_WITHOUT_TELEGRAM_CODEX"] = "1"
        sys.path.insert(0, str(foreground.ROOT))
    dmk_scripts = os.environ.get("CLAUDE_TEST_DMK_SCRIPTS") if interaction else None
    scripts = Path(sys.argv[4]) if engine != "claude" else Path(dmk_scripts) if dmk_scripts else None
    raise SystemExit(qualify(engine, gateway, executable, scripts,
                            interaction=interaction))
