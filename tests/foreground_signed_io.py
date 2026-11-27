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
import signal
from socket import socket as tcp_socket
import socketserver
import sqlite3
import subprocess
import sys
import time
from threading import Event, Thread
from types import SimpleNamespace
import unittest
import uuid

import antigravity_foreground_io as foreground
from claude_provider_fixture import ANSWER, REVOKED_ANSWER, ClaudeProvider
from conversation_input_control_io import Inputs
from conversation_routing_io import CanonicalRouting


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
                      maxBudgetUsd=0.1, displayName="Fixture CompAII · claude@fixture", hostTools=[])
        worker = os.environ.get("CLAUDE_TEST_WORKER_PATH", str(
            foreground.ROOT / "adapters/claude/gateway-worker.mjs"
        ))
        return ["/usr/bin/node", worker, "--profile", str(profile)]

    home = state / "config" / "goose"
    home.mkdir(parents=True)
    extensions = {name: {"name": name, "type": "platform", "enabled": False}
                  for name in ("developer", "extensionmanager", "summon", "tom", "todo", "summarize")}
    (home / "config.yaml").write_text(json.dumps({"extensions": extensions}))
    config.update(binary=executable, cwd=str(root), provider="openai", providerKeyFile=str(key),
                  providerPort=port)
    worker = foreground.ROOT / "adapters/acp/gateway-worker.mjs"
    return ["/usr/bin/node", str(worker), "--profile", str(profile)]


def qualify(engine, gateway, executable, scripts, *, interaction=False, direct=False, mixed=False,
            inverse=False, telegram_topic=False, signed_interrupt=False):
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
            journey = CanonicalRouting(gateway) if mixed or inverse else Inputs(gateway)
            self.addCleanup(journey.close)
            if mixed or inverse:
                journey.start()
                for topic in (1, 7) if inverse else (7,):
                    journey.admit("Fixture seed for the owned Codex conversation", topic=topic)
                    journey.wait(lambda: journey.has("Initial goal turn delivered.", topic))
                    journey.idle()
                journey.stop()
                if telegram_topic:
                    with sqlite3.connect(journey.root / "state.sqlite") as db:
                        db.execute("UPDATE sessions SET session_prompt=? WHERE thread_id=7",
                                   ("Keep the selected design instructions.",))
                targets = journey.target_config
                if inverse:
                    targets = targets.replace('name="Alpha"', f'name="Alpha"\nharness="{engine}"')
                journey.config.write_text(journey.config.read_text() + targets)
                journey.routing = True
            if telegram_topic or os.environ.get("FOREGROUND_TEST_WITHOUT_TELEGRAM_CODEX") == "1":
                if telegram_topic:
                    adapter_config = journey.root / "telegram-adapter.toml"
                    adapter_config.write_text(journey.config.read_text().replace(
                        "[telegram]\n", "[telegram]\nexternal_polling=true\n", 1
                    ))
                gateway_config = re.sub(r'^(bot_token_file|api_base)=.*\n', '', journey.config.read_text(),
                                        flags=re.MULTILINE)
                gateway_config = gateway_config.replace(
                    "[telegram]\n",
                    '[telegram]\nexternal_polling=true\nexternal_bot_id=123\n'
                    'api_base="http://127.0.0.1:1"\n',
                )
                journey.config.write_text(gateway_config)
                if not (mixed or inverse):
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

            class DirectProvider(ClaudeProvider):
                def admitted(self):
                    if inverse:
                        ident, phase, session, scope, prompt = self.server.journey.row(
                            "SELECT i.id,i.phase,t.native_thread_id,t.execution_native_scope,t.prompt "
                            "FROM interaction_instructions i JOIN interaction_sources s ON s.id=i.input_id "
                            "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') "
                            "WHERE s.event_id=? AND t.execution_harness='claude' AND t.status='running'",
                            (self.server.human_original,),
                        )[0]
                        assert phase == "submitting"
                        if getattr(self.server, "attachment", None):
                            assert prompt == self.server.attachment["caption"]
                        else:
                            assert self.server.original in prompt
                        if telegram_topic and not getattr(self.server, "attachment", None):
                            assert prompt == self.server.original
                        elif not telegram_topic:
                            assert '"original_human_author":100' in prompt
                        self.server.current = ident
                        self.server.exposures.append(ident)
                        if getattr(self.server, "hold", None):
                            self.server.interrupted_id = ident
                            self.server.exposed.set()
                            if not self.server.hold.wait(10):
                                raise AssertionError("Fixture did not release the blocked request")
                        return {"native_session_id":session, "native_session_scope":scope}
                    phase, session, scope = self.server.journey.row(
                        "SELECT c.phase,t.native_thread_id,t.execution_native_scope "
                        "FROM conversation_inputs c JOIN turns t ON t.id=c.local_turn "
                        "WHERE c.id=? AND t.execution_harness='claude' AND t.status='running'",
                        (self.server.current,),
                    )[0]
                    if phase != "sending":
                        raise AssertionError("Direct original was released before journal exposure")
                    self.server.exposures.append(self.server.current)
                    if getattr(self.server, "hold", None):
                        self.server.exposed.set()
                        if not self.server.hold.wait(10):
                            raise AssertionError("The bounded fixture never released this provider call")
                    return {"native_session_id":session, "native_session_scope":scope}

            class RoutedProvider(foreground.Provider):
                def admitted(self):
                    ident, phase, native, prompt = self.server.journey.row(
                        "SELECT i.id,i.phase,t.native_thread_id,t.prompt "
                        "FROM interaction_instructions i JOIN interaction_sources s ON s.id=i.input_id "
                        "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') "
                        "WHERE s.event_id=? AND t.execution_harness=? AND t.status='running'",
                        (self.server.human_original, self.server.engine),
                    )[0]
                    assert phase == "submitting" and native
                    assert self.server.original in prompt
                    assert '"original_human_author":100' in prompt
                    assert "Return a plain-language answer to the attributed input." in prompt
                    assert "Return your answer followed by <daimon-result>" not in prompt
                    self.server.current = ident
                    self.server.exposures.append(ident)

            if engine == "claude":
                handler = DirectProvider if direct else InteractionProvider if interaction else ClaudeProvider
            else:
                handler = RoutedProvider if inverse else foreground.Provider
            with ThreadingHTTPServer(("127.0.0.1", 0), handler) as provider:
                provider.journey = journey
                provider.calls = []
                provider.exposures = []
                provider.failure = None
                provider.mode = "accepted"
                provider.engine = engine
                provider.model = {"antigravity": "fixture", "goose": "gpt-4o-mini",
                                  "claude": "claude-sonnet-4-5"}[engine]
                provider.body = body
                provider.paired_human = telegram_topic or (direct and not inverse)
                if telegram_topic:
                    provider.session_instructions = "Keep the selected design instructions."
                provider.controller = direct and not inverse
                provider.inverse_paired = inverse and engine == "claude" and (
                    telegram_topic or os.environ.get("FOREGROUND_TEST_INVERSE_PAIRED") == "1"
                )
                provider.mixed = mixed
                provider.mixed_worker_reply = "Codex worker fixture result from the original request."
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
                real_provider = os.environ.get("FOREGROUND_TEST_ANTIGRAVITY_PROVIDER_COMMAND")
                if real_provider and engine == "antigravity" and inverse:
                    with tcp_socket() as reservation:
                        reservation.bind(("127.0.0.1", 0))
                        config["providerPort"] = reservation.getsockname()[1]
                    config["providerCommand"] = [
                        arg.replace("{port}", str(config["providerPort"]))
                        for arg in json.loads(real_provider)
                    ]
                dmk_write = telegram_topic and os.environ.get("FOREGROUND_TEST_TELEGRAM_DMK_WRITE") == "1"
                if dmk_write and scripts is None:
                    self.fail("The disposable DMK writer fixture needs CLAUDE_TEST_DMK_SCRIPTS")
                if (interaction or dmk_write) and scripts:
                    python = os.environ.get("CLAUDE_TEST_DMK_PYTHON", sys.executable)
                    selected, memory_db = selected_memory(root, python, scripts, being, provider.current, engine)
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
                if interaction and os.environ.get("FOREGROUND_TEST_FOUNDATION") == "1":
                    foundation = root / "foundation"
                    foundation.mkdir(mode=0o700)
                    binding = foundation / "client.json"
                    binding.touch(mode=0o600)
                    now = int(time.time() * 1000)
                    binding.write_text(json.dumps({
                        "schema": "dm.local.client-config/v3",
                        "expected_server": {"embodiment_id": body, "incarnation_id": origin["incarnation_id"]},
                        "capability": {"status": "active", "not_before_ms": now-1000, "not_after_ms": now+120000},
                    }))
                    server = foundation / "mcp.mjs"
                    provider.foundation_revocation = foundation / "revoked"
                    status = {
                        "schema": "dm.runtime.status/v1", "integrity": "ok", "being_ref": being,
                        "manifest_hash": config["body"]["manifestHash"],
                        "local_origin": {"embodiment_id": body, "incarnation_id": origin["incarnation_id"]},
                    }
                    extra_tools = [f"fixture_extra_{n}" for n in range(10)] if os.environ.get(
                        "FOREGROUND_TEST_DEFERRED_TOOLS"
                    ) == "1" else []
                    tool_names = ["fixture_read", "daimon_status", *extra_tools]
                    provider.deferred_foundation = extra_tools
                    server.write_text("const status = " + json.dumps(status) + ";\n"
                                      + "const toolNames = " + json.dumps(tool_names) + ";\n" + """
import { createInterface } from 'node:readline';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
const revoked = fileURLToPath(new URL('revoked', import.meta.url));
for await (const line of createInterface({ input: process.stdin })) {
  const {id, method, params} = JSON.parse(line);
  if (id === undefined) continue;
  const result = {
    'initialize': { protocolVersion: params?.protocolVersion, capabilities: {tools:{}},
      serverInfo: {name:'foundation-fixture', version:'1'} },
    'tools/list': { tools: toolNames.map(name => ({
       name, description:'Read a synthetic status', inputSchema: {type:'object',properties:{}} })) },
    'tools/call': params?.name === 'daimon_status'
      ? { isError:existsSync(revoked), content:[], structuredContent:{ok:!existsSync(revoked),result:status} }
      : { content: [{type:'text',text:'Fixture Foundation readback.'}] },
  }[method];
  console.log(JSON.stringify({jsonrpc:'2.0', id, result}));
}
""")
                    config["matrixFoundation"] = {
                        "command": ["/usr/bin/node",str(server),"--runtime-root",str(foundation)],
                        "tools": tool_names,
                    }
                    provider.foundation_marker = "Fixture Foundation readback."
                if interaction and os.environ.get("FOREGROUND_TEST_HOST_TOOLS") == "1":
                    provider.host_file = root / "host-tools-fixture.txt"
                    provider.host_file.write_text("Native file readback marker.")
                    provider.host_tools = ["Read", "Bash"]
                    config["hostTools"] = provider.host_tools
                if inverse and engine == "claude":
                    provider.host_file = root / "host-tools-fixture.txt"
                    provider.host_file.write_text("Native file readback marker.")
                    provider.host_tools = ["Read", "Bash"] if provider.inverse_paired else []
                    config["hostTools"] = ["Read", "Bash"]
                if config.get("hostTools") and "Bash" in config["hostTools"]:
                    host_bin = root / "owner-bin"
                    host_bin.mkdir()
                    helper = host_bin / "fixture-shared-command"
                    helper.write_text("#!/bin/sh\nprintf 'Native shell %s.' 'readback marker'\n")
                    helper.chmod(0o700)
                    config["hostToolDirectory"] = str(host_bin)
                    if dmk_write:
                        writer = host_bin / "dmk"
                        writer.write_text(
                            f"#!/bin/sh\nexec /bin/bash {shlex.quote(str(scripts / 'hmk'))} \"$@\"\n"
                        )
                        writer.chmod(0o700)
                        provider.memory_db = memory_db
                        provider.memory_write_text = "A synthetic memory from the paired Claude turn."
                        command_env = [f"PATH={Path(python).parent}:/usr/bin:/bin",
                                       f"HMK_WORKSPACE_ROOT={root}",
                                       f"HMK_AGENT_MEMORY_BASE={root}", f"HMK_DB_PATH={memory_db}"]
                        command_line = ["env", *command_env, str(host_bin / "dmk"),
                                        "memoryctl.py", "add-text", "--shelf", "library",
                                        "--title", "Claude native writer fixture", "--raw",
                                        provider.memory_write_text]
                        provider.memory_write_command = shlex.join(command_line) + (
                            " && printf 'Native DMK write accepted.'"
                        )
                profile.write_text(json.dumps(config))
                original_host = ""
                if interaction and not direct:
                    sender_source, sender = self._start_sender(root, fixture, service, capabilities, body)
                    original_host = f"""
[interaction.claude_foreground.interaction_origin]
command={json.dumps([*sender,"--we-origin",body])}
source={{kind="body",being_ref="{being}",embodiment_id="{sender_source["embodiment_id"]}"}}
timeout_seconds=5
"""
                if signed_interrupt == "before":
                    command = ["/bin/sh", "-c", 'sleep 60; exec "$@"', "--", *command]
                journey.config.write_text(journey.config.read_text() + f"""
[interaction.{engine}_foreground]
worker_command={json.dumps(command)}
interaction_direct={str(direct or inverse).lower()}
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
                    if telegram_topic:
                        adapter = subprocess.Popen(
                            [gateway, "--tele-daimon-poll", str(adapter_config)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                        )
                        try:
                            if os.environ.get("FOREGROUND_TEST_TELEGRAM_STEER") == "1":
                                self._telegram_steer(journey, provider, profile)
                            elif os.environ.get("FOREGROUND_TEST_TELEGRAM_FILES") == "1":
                                self._telegram_attachments(journey, provider)
                            elif os.environ.get("FOREGROUND_TEST_TELEGRAM_QUOTA") == "1":
                                self._telegram_quota(journey, provider)
                            elif os.environ.get("FOREGROUND_TEST_TELEGRAM_CANCEL") == "1":
                                self._telegram_cancel(journey, provider)
                            elif dmk_write:
                                self._telegram_dmk_write(journey, provider)
                            else:
                                self._telegram_topic_exchange(journey, provider, return_attempts, profile)
                        finally:
                            if adapter.poll() is None:
                                adapter.send_signal(signal.SIGINT)
                            _, errors = adapter.communicate(timeout=10)
                        self.assertEqual(adapter.returncode, 0, errors)
                        return
                    if inverse:
                        self._inverse_exchange(journey, provider, return_attempts, profile)
                        if memory:
                            self.assertEqual(database.read_bytes(), initial_database)
                        return
                    if direct:
                        self._direct_exchange(journey, provider, return_attempts)
                        return
                    if interaction:
                        self._interaction_exchange(journey, provider, fixture, body, return_attempts)
                        return
                    selected = dict(cursor=None, event_id=original["message_id"], author=author,
                                    thread_id=original["thread_id"])
                    if signed_interrupt:
                        self._signed_interrupt(journey, provider, selected, return_attempts)
                        return
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

        def _signed_interrupt(self, journey, provider, selected, return_attempts):
            provider.mode = "held"
            provider.arrived, provider.release = Event(), Event()
            ident = selected["event_id"]
            args = [journey.binary, "--control", str(journey.config),
                    "matrix", engine, "run", json.dumps(selected)]
            before = signed_interrupt == "before"
            with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as run:
                try:
                    if before:
                        journey.wait(lambda: journey.row(
                            "SELECT phase FROM interaction_matrix_requests WHERE source_event=?", (ident,)
                        ) == [("starting",)])
                    else:
                        self.assertTrue(provider.arrived.wait(35), provider.failure)
                    in_flight = journey.read("matrix", engine, "status", ident)["result"]
                    self.assertEqual(in_flight["phase"], "starting" if before else "provider_exposed")
                    self.assertEqual(journey.read("matrix", engine, "run", json.dumps(selected))["result"],
                                     in_flight)
                    other = "goose" if engine == "antigravity" else "antigravity"
                    wrong = journey.read("matrix", other, "interrupt", ident)["result"]
                    self.assertFalse(wrong["interruption_requested"])
                    requested = journey.read("matrix", engine, "interrupt", ident)["result"]
                    self.assertTrue(requested["interruption_requested"])
                    stdout, errors = run.communicate(timeout=15)
                    self.assertEqual(run.returncode, 0, errors)
                finally:
                    provider.release.set()
                    if run.poll() is None:
                        run.terminate()
            outcome = json.loads(stdout)["result"]
            self.assertEqual(outcome["phase"], "rejected" if before else "provider_uncertain", outcome)
            self.assertEqual(outcome["result"]["reason"],
                             "interrupted_before_submission" if before else "foreground_interrupted")
            expected_calls = [] if before else [ident]
            self.assertEqual(provider.calls, expected_calls)
            self.assertEqual(return_attempts, [])
            terminal = journey.read("matrix", engine, "interrupt", ident)["result"]
            self.assertFalse(terminal["interruption_requested"])
            journey.stop()
            journey.start()
            journey.wait_control_socket(journey.socket)
            self.assertEqual(journey.read("matrix", engine, "run", json.dumps(selected))["result"], outcome)
            self.assertEqual(provider.calls, expected_calls)
            self.assertEqual(return_attempts, [])

        def _telegram_dmk_write(self, journey, provider):
            provider.original = "Read the selected fixture memory and save one synthetic record."
            provider.human_original = str(journey.sequence + 1)
            update = journey.admit(provider.original, topic=7)
            self.assertEqual(str(update), provider.human_original)
            journey.wait(lambda: provider.failure or journey.has(ANSWER, 7), seconds=35)
            self.assertIsNone(provider.failure)
            with sqlite3.connect(provider.memory_db.as_uri() + "?mode=ro", uri=True) as connection:
                rows = connection.execute(
                    "SELECT raw FROM chapters WHERE title='Claude native writer fixture'"
                ).fetchall()
            self.assertEqual(rows, [(provider.memory_write_text,)])

        def _telegram_cancel(self, journey, provider):
            native_turns = journey.native_turns
            provider.exposed, provider.hold = Event(), Event()
            provider.original = "Keep this synthetic original if I interrupt the selected turn."
            provider.human_original = str(journey.sequence + 1)
            update = journey.admit(provider.original, topic=7)

            def state():
                return journey.row(
                    "SELECT i.id,i.phase,t.status,s.busy FROM interaction_sources x "
                    "JOIN interaction_instructions i ON i.input_id=x.id "
                    "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') "
                    "JOIN sessions s ON s.id=t.session_id WHERE x.event_id=?", (str(update),)
                )

            try:
                self.assertTrue(provider.exposed.wait(8), provider.failure)
                ident = state()[0][0]
                self.assertEqual(state(), [(ident, "submitting", "running", 1)])
                journey.command("/stop", "Stop signal sent.", topic=7)
                journey.wait(lambda: state() == [(ident, "uncertain", "failed", 0)])
            finally:
                provider.hold.set()

            original = json.loads(journey.row("SELECT payload_json FROM incoming_updates WHERE update_id=?",
                                              (update,))[0][0])
            duplicate_polled = Event()
            journey.before_poll_reply = lambda updates: (
                duplicate_polled.set() if any(event["update_id"] == update for event in updates) else None
            )
            with journey.lock:
                journey.updates.append(original)
            self.assertTrue(duplicate_polled.wait(5))
            journey.command("/status", "Claude Code", topic=7)
            self.assertEqual(state(), [(ident, "uncertain", "failed", 0)])
            self.assertEqual(provider.exposures, [ident])
            self.assertEqual(journey.row("SELECT count(*) FROM interaction_results"), [(0,)])
            self.assertEqual(journey.native_turns, native_turns)

        def _telegram_quota(self, journey, provider):
            provider.rate_limited = True
            provider.original = "Please retain this original if the provider refuses it."
            with journey.lock:
                provider.human_original = str(journey.sequence + 1)
            update = journey.admit(provider.original, topic=7)
            journey.wait(lambda: journey.has("Claude Code reached its usage limit.", 7) or provider.failure, seconds=40)
            self.assertIsNone(provider.failure)
            rows = journey.row(
                "SELECT i.phase,json_extract(i.doc,'$.subscription_limit'),t.status FROM interaction_sources s "
                "JOIN interaction_instructions i ON i.input_id=s.id "
                "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') WHERE s.event_id=?", (str(update),))
            self.assertEqual(rows, [("rejected", '{"window":null,"resets_at":null}', "failed")])
            notices = [payload for message,payload in journey.messages
                       if "Claude Code reached its usage limit." in message["text"]]
            self.assertEqual([payload["reply_parameters"]["message_id"] for payload in notices], [update])

        def _telegram_attachments(self, journey, provider):
            import base64
            import hashlib

            image = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
            journey.media_files = {"fixture-image.png": image}
            photo = {"photo": [{"file_id": "fixture-image.png", "width": 1, "height": 1}]}
            forwarded = journey.admit(topic=7, message_fields={
                **photo, "forward_origin": {"type": "hidden_user", "date": 1740000000, "sender_user_name": "Fixture"},
            })
            journey.wait(lambda: journey.has("Forwarded messages aren't supported here.", 7))
            self.assertEqual(journey.row("SELECT count(*) FROM interaction_sources WHERE event_id=?",
                                         (str(forwarded),)), [(0,)])
            for caption in ("  Please inspect this photo.  ", "", "/inspect@otherbot once you see the photo"):
                provider.original = caption or "Gateway attached these files"
                provider.attachment = {"caption": caption, "base64": base64.b64encode(image).decode()}
                with journey.lock:
                    provider.human_original = str(journey.sequence + 1)
                update = journey.admit(topic=7, message_fields={**photo, **({"caption": caption} if caption else {})})
                journey.wait(lambda: provider.failure or any(
                    ANSWER in message["text"] and payload.get("reply_parameters", {}).get("message_id") == update
                    for message, payload in journey.messages), seconds=25)
                self.assertIsNone(provider.failure)
                rows = journey.row("SELECT s.doc,i.phase FROM interaction_sources s "
                                   "JOIN interaction_instructions i ON i.input_id=s.id WHERE s.event_id=?", (str(update),))
                self.assertEqual(len(rows), 1)
                source, phase = rows[0]
                self.assertEqual(phase, "accepted")
                source = json.loads(source)
                self.assertEqual(source["text"], caption)
                expected = hashlib.sha256(image).hexdigest()
                self.assertEqual(source["telegram_files"][0]["sha256"], expected)
                self.assertEqual((journey.root / "state.sqlite.files" / expected).read_bytes(), image)
            self.assertEqual(len(set(provider.exposures)), 3)

        def _telegram_steer(self, journey, provider, profile):
            selected = json.loads(profile.read_text())
            selected["hostTools"] = ["Bash"]
            profile.write_text(json.dumps(selected))
            started = journey.root / "steer-tool-started"
            release = journey.root / "steer-tool-release"
            provider.host_tools = ["Bash"]
            provider.steer_fixture = {
                "text": "New Telegram original while the tool is working.",
                "conversation_text": "New Conversation original while the tool is working.",
                "command": (
                    f"touch {shlex.quote(str(started))}; "
                    f"for n in $(seq 1 150); do if test -f {shlex.quote(str(release))}; "
                    "then sleep 0.5; echo 'Native steer gate opened.'; exit 0; fi; "
                    "sleep 0.1; done; exit 1"
                ),
            }
            with journey.lock:
                provider.original = "Run the synthetic gate tool and answer."
                provider.human_original = str(journey.sequence + 1)
            root = journey.admit(provider.original, topic=7)
            def state(update):
                return journey.row(
                    "SELECT i.id,i.phase,json_extract(i.doc,'$.local_turn'),"
                    "json_extract(i.doc,'$.native_turn') FROM interaction_sources s "
                    "JOIN interaction_instructions i ON i.input_id=s.id WHERE s.event_id=?",
                    (str(update),),
                )

            journey.wait(lambda: provider.failure or started.exists() or (
                state(root) and state(root)[0][1] in ("retained_unsent", "rejected", "uncertain", "accepted")
            ), seconds=25)
            self.assertIsNone(provider.failure)
            self.assertTrue(started.exists(), (state(root), provider.calls, provider.exposures))
            followup = journey.admit(provider.steer_fixture["text"], topic=7)
            conversation = str(uuid.uuid4())
            try:
                journey.wait(lambda: provider.failure or (
                    state(followup) and state(followup)[0][1] == "steering"), seconds=6)
                page = journey.read("presentation", "list", "0", "0")["result"]
                original = {"binding": page["binding"], "id": conversation,
                            "text": "#Alpha " + provider.steer_fixture["conversation_text"]}
                self.assertTrue(journey.read("input", "submit-human", json.dumps(original))["result"]["new_input"])
                journey.wait(lambda: provider.failure or (
                    state(conversation) and state(conversation)[0][1] == "steering"), seconds=6)
                self.assertEqual(state(followup)[0][2], state(root)[0][2])
                self.assertEqual(state(conversation)[0][2], state(root)[0][2])
            finally:
                release.touch()
            journey.wait(lambda: provider.failure or journey.has(ANSWER, 7), seconds=25)
            self.assertIsNone(provider.failure)
            original, followup = state(root)[0], state(followup)[0]
            self.assertEqual(original[1:], followup[1:])
            self.assertEqual(original[1:], state(conversation)[0][1:])
            self.assertEqual(original[1], "accepted")
            self.assertEqual(provider.calls, [original[0], original[0]])
            self.assertEqual(journey.row("SELECT count(*) FROM interaction_results"), [(1,)])
            self.assertEqual(journey.row("SELECT count(*) FROM interaction_delivery_requests"), [(3,)])
            self.assertEqual(journey.row(
                "SELECT count(*) FROM turns WHERE execution_harness='claude'"
            ), [(1,)])

        def _telegram_topic_exchange(self, journey, provider, return_attempts, profile):
            codex = journey.row("SELECT codex_thread_id FROM sessions WHERE thread_id=7")
            native_turns = journey.native_turns
            forwarded = journey.admit("/stop all", topic=7, message_fields={
                "forward_origin": {"type": "hidden_user", "date": 1740000000, "sender_user_name": "Fixture"}
            })
            journey.wait(lambda: journey.has("Forwarded messages aren't supported here.", 7))
            journey.command("/retry 1", "to stop the current turn", topic=7)
            self.assertEqual(journey.row("SELECT count(*) FROM interaction_sources WHERE event_id=?",
                                         (str(forwarded),)), [(0,)])
            self.assertEqual(journey.native_turns, native_turns)

            selected = "  This text was written directly in the selected topic.  "
            launcher = Path(json.loads(profile.read_text())["binary"])
            startup = launcher.read_text()
            launcher.write_text(startup.replace(
                "#!/bin/sh\n", '#!/bin/sh\nif [ "$1" != auth ]; then sleep 11; fi\n', 1
            ))
            with journey.lock:
                provider.original = selected
                provider.human_original = str(journey.sequence + 1)
            update = journey.admit(selected, topic=7)
            self.assertEqual(str(update), provider.human_original)
            journey.wait(lambda: journey.row(
                "SELECT count(*) FROM turns WHERE execution_harness='claude' AND status='running'"
            ) == [(1,)])
            journey.command("/status", "Claude Code is working on a message.", topic=7)
            journey.wait(lambda: provider.failure or journey.has(ANSWER, 7), seconds=30)
            launcher.write_text(startup)
            self.assertIsNone(provider.failure)
            self.assertFalse(journey.has("native submission has not started", 7))
            delivered = [(message, payload) for message, payload in journey.messages if ANSWER in message["text"]]
            self.assertEqual(len(delivered), 1)
            message, payload = delivered[0]
            self.assertEqual(payload["reply_parameters"]["message_id"], update)
            self.assertNotIn("Worker instruction coverage was not reported", message["text"])
            self.assertEqual(journey.row(
                "SELECT i.phase,t.execution_harness,t.status,t.prompt FROM interaction_sources s "
                "JOIN interaction_instructions i ON i.input_id=s.id "
                "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') WHERE s.event_id=?",
                (str(update),)), [("accepted", "claude", "completed", selected)])
            self.assertEqual(journey.row("SELECT status FROM incoming_updates WHERE update_id=?", (update,)),
                             [("handled",)])
            self.assertEqual(journey.row("SELECT codex_thread_id FROM sessions WHERE thread_id=7"), codex)
            self.assertEqual(journey.native_turns, native_turns)
            self.assertEqual(len(set(provider.exposures)), 1)
            calls = list(provider.calls)
            provider.previous_original = selected
            provider.previous_session = journey.row(
                "SELECT native_thread_id FROM turns WHERE execution_harness='claude'"
            )[0][0]
            original = json.loads(journey.row("SELECT payload_json FROM incoming_updates WHERE update_id=?",
                                              (update,))[0][0])
            duplicate_polled = Event()
            journey.before_poll_reply = lambda updates: (
                duplicate_polled.set() if any(event["update_id"] == update for event in updates) else None
            )
            with journey.lock:
                journey.updates.append(original)
            self.assertTrue(duplicate_polled.wait(5))
            journey.command("/retry 1", "to stop the current turn", topic=7)
            self.assertEqual(provider.calls, calls)
            self.assertEqual(journey.native_turns, native_turns)
            self.assertEqual(return_attempts, [])

            selected_profile = profile.read_text()
            unavailable_profile = json.loads(selected_profile)
            unavailable_profile["cliVersion"] = "0.0.0"
            profile.write_text(json.dumps(unavailable_profile))
            provider.original = "A fresh topic original for the known-unsent recovery check."
            with journey.lock:
                provider.human_original = str(journey.sequence + 1)
            update = journey.admit(provider.original, topic=7)
            def retained():
                return journey.row(
                    "SELECT i.id,i.phase FROM interaction_instructions i JOIN interaction_sources s "
                    "ON s.id=i.input_id WHERE s.event_id=?", (str(update),))
            journey.wait(lambda: retained() and retained()[0][1] == "retained_unsent")
            instruction, _ = retained()[0]
            self.assertEqual(provider.calls, calls)
            profile.write_text(selected_profile)
            command = "/interaction retry " + instruction
            journey.admit(command, topic=1, message_fields={
                "forward_origin": {"type": "hidden_user", "date": 1740000000, "sender_user_name": "Fixture"}
            })
            journey.wait(lambda: journey.has("That saved input could not be recovered", 1))
            self.assertEqual(retained(), [(instruction, "retained_unsent")])
            self.assertEqual(provider.calls, calls)
            journey.admit(command, topic=7)
            journey.wait(lambda: provider.failure or retained() == [(instruction, "accepted")], seconds=30)
            self.assertIsNone(provider.failure)
            self.assertTrue(any(item == instruction for item in provider.calls[len(calls):]))
            self.assertEqual(journey.native_turns, native_turns)

            if os.environ.get("FOREGROUND_TEST_CLAUDE_MISSING_RESUME") == "1":
                previous_native = provider.previous_session
                fixture_home = Path(json.loads(profile.read_text())["configurationDirectory"])
                native_files = list((fixture_home / "projects").rglob(previous_native + ".jsonl"))
                self.assertEqual(len(native_files), 1)
                native_file = native_files[0]
                native_file.rename(native_file.with_suffix(".unavailable"))
                before_missing_resume = len(provider.calls)
                provider.expected_recovered_history = provider.original
                provider.original = "Resume this design using the last retained context."
                provider.human_original = str(journey.sequence + 1)
                recovery_update = journey.admit(provider.original, topic=7)
                journey.wait(lambda: provider.failure or
                             journey.has("I recovered the retained design context.", 7), seconds=35)
                self.assertIsNone(provider.failure)
                del provider.expected_recovered_history
                self.assertEqual(provider.calls[before_missing_resume:], [
                    journey.row("SELECT i.id FROM interaction_instructions i "
                                "JOIN interaction_sources s ON s.id=i.input_id WHERE s.event_id=?",
                                (str(recovery_update),))[0][0]
                ])
                self.assertEqual(journey.row(
                    "SELECT i.phase,t.native_thread_id<>?,t.status FROM interaction_sources s "
                    "JOIN interaction_instructions i ON i.input_id=s.id "
                    "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') WHERE s.event_id=?",
                    (previous_native, str(recovery_update))), [("accepted", 1, "completed")])
                self.assertEqual(journey.native_turns, native_turns)

            after_retry = list(provider.calls)
            forwarded_goal = journey.admit("/goal", topic=7, message_fields={
                "forward_origin": {"type": "hidden_user", "date": 1740000000, "sender_user_name": "Fixture"}
            })
            journey.wait(lambda: journey.row("SELECT status FROM incoming_updates WHERE update_id=?",
                                               (forwarded_goal,)) == [("handled",)])
            self.assertEqual(journey.row("SELECT count(*) FROM interaction_sources WHERE event_id=?",
                                         (str(forwarded_goal),)), [(0,)])
            goal = journey.admit("/goal", topic=7)
            journey.wait(lambda: journey.has("No goal set.", 7), seconds=30)
            self.assertEqual(journey.row(
                "SELECT i.phase,t.execution_harness,t.status,t.prompt FROM interaction_sources s "
                "JOIN interaction_instructions i ON i.input_id=s.id "
                "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') WHERE s.event_id=?",
                (str(goal),)), [("accepted", "claude", "completed", "/goal")])
            self.assertEqual(provider.calls, after_retry)
            self.assertEqual(journey.native_turns, native_turns)

            # The earlier checks had no Codex activity. This next distinct
            # human input explicitly needs the local general conversation.
            provider.previous_original = None
            provider.calls.clear()
            provider.test_session_request = True
            journey.allow_local_dependencies = True
            provider.original = "Ask our general conversation to check the design summary."
            provider.human_original = str(journey.sequence + 1)
            journey.admit(provider.original, topic=7)
            journey.wait(lambda: provider.failure or journey.row(
                "SELECT count(*) FROM interaction_session_requests") == [(1,)], seconds=25)
            self.assertIsNone(provider.failure)
            journey.wait(lambda: provider.failure or len(provider.calls) == 5, seconds=25)
            self.assertIsNone(provider.failure)
            journey.wait(lambda: journey.row(
                "SELECT i.phase FROM interaction_session_requests r "
                "JOIN interaction_instructions i ON i.id=r.target_instruction "
                "JOIN sessions s ON s.id=i.session_id WHERE s.thread_id=1") == [("accepted",)])
            self.assertEqual(journey.row("SELECT count(*) FROM interaction_session_requests"), [(1,)])

        def _inverse_exchange(self, journey, provider, return_attempts, profile):
            answer = ANSWER if engine == "claude" else "Selected memory: " + foreground.MARKER
            page = journey.read("presentation", "list", "0", "0")["result"]
            previous_codex = journey.row("SELECT codex_thread_id FROM sessions WHERE thread_id=7")
            provider.original = "Please send this exact fixture work to Alpha."
            def submit_original(text):
                body = {"id":str(uuid.uuid4()),"binding":page["binding"],"text":text}
                command = "submit-human" if provider.inverse_paired else "submit"
                response = journey.read("input", command, json.dumps(body))["result"]
                self.assertTrue(response["new_input"])
                opposite = "submit" if provider.inverse_paired else "submit-human"
                receipt = journey.read("input", opposite, json.dumps(body))["result"]
                self.assertFalse(receipt["new_input"])
                retained = journey.row("SELECT json_extract(doc,'$.paired_actor') FROM conversation_inputs WHERE id=?",
                                       (body["id"],))
                self.assertEqual(retained, [(1 if provider.inverse_paired else None,)])
                return body

            def select_memory_for(body):
                if engine == "claude":
                    return
                target_id = journey.row("SELECT id FROM sessions WHERE thread_id=7")[0][0]
                source_id = uuid.uuid5(uuid.NAMESPACE_URL, "telecodex:interaction:conversation:" + body["id"])
                instruction_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{source_id}:{target_id}")
                contents = json.loads(profile.read_bytes())
                contents["selectedMemory"]["inputId"] = str(instruction_id)
                profile.write_text(json.dumps(contents))

            profile_doc = json.loads(profile.read_bytes())
            if "providerCommand" in profile_doc:
                text = ("#Alpha Verify the body with daimon_status and read the record with "
                        "dmk_read_selected. Your visible answer must start with the exact sentence "
                        "from the selected memory record. Put any required result metadata after "
                        "that sentence.")
                original = {"id": str(uuid.uuid4()), "binding": page["binding"], "text": text}
                select_memory_for(original)
                status = journey.read("input", "submit-human", json.dumps(original))["result"]
                self.assertTrue(status["new_input"])
                journey.wait(lambda: journey.row(
                    "SELECT i.phase FROM interaction_instructions i "
                    "JOIN interaction_sources s ON s.id=i.input_id WHERE s.event_id=? "
                    "AND i.phase IN ('accepted','uncertain','retained_unsent','rejected')",
                    (original["id"],),
                ), seconds=115)
                phase, native = journey.row(
                    "SELECT i.phase,t.native_thread_id FROM interaction_instructions i "
                    "JOIN interaction_sources s ON s.id=i.input_id "
                    "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') WHERE s.event_id=?",
                    (original["id"],),
                )[0]
                transcript_path = (Path(profile_doc["stateRoot"]) / "brain" / (native or "missing")
                                   / ".system_generated/logs/transcript.jsonl")
                log = transcript_path.read_text() if transcript_path.is_file() else ""
                tool_steps = [event["tool_calls"] for row in log.splitlines()
                              if (event := json.loads(row)).get("tool_calls")]
                self.assertEqual(phase, "accepted", f"Native tool selections: {tool_steps}")
                rows = journey.row(
                    "SELECT r.body,t.execution_harness,t.native_thread_id FROM interaction_results r "
                    "JOIN turns t ON t.id=r.local_turn"
                )
                self.assertEqual(len(rows), 1, rows)
                self.assertEqual(rows[0][1], engine)
                self.assertIn(foreground.MARKER, rows[0][0])
                self.assertEqual(rows[0][2], native)
                for tool in ("daimon_status", "dmk_read_selected"):
                    self.assertIn(f"Tool response for {tool}:", log)
                self.assertEqual(journey.row("SELECT count(*) FROM interaction_matrix_requests"), [(0,)])
                self.assertFalse(journey.packets or journey.worker_packets or return_attempts or provider.calls)
                self.assertEqual(journey.row("SELECT codex_thread_id FROM sessions WHERE thread_id=7"),
                                 previous_codex)
                with tcp_socket() as endpoint:
                    self.assertNotEqual(endpoint.connect_ex(("127.0.0.1", profile_doc["providerPort"])), 0)
                return

            original = submit_original(provider.original)
            select_memory_for(original)
            provider.human_original = original["id"]
            journey.wait(lambda: journey.row("SELECT phase FROM conversation_inputs WHERE id=?",
                                             (original["id"],)) == [("accepted",)])
            selection = {"input_ref":original["id"],"destinations":[
                {"selector":"Alpha","relation":"new","requests":[]} ]}
            first = journey.call("route-inverse-first", "dispatch", selection)["results"][0]
            repeated = journey.call("route-inverse-repeat", "dispatch", selection)["results"][0]
            self.assertTrue(first["new_admission"])
            self.assertFalse(repeated["new_admission"])
            self.assertEqual(first["instruction"], repeated["instruction"])
            instruction = first["instruction"]
            journey.wait(lambda: provider.failure or journey.row(
                "SELECT phase FROM interaction_instructions WHERE id=?", (instruction,)
            ) in ([("accepted",)], [("uncertain",)], [("rejected",)], [("retained_unsent",)]),seconds=30)
            self.assertIsNone(provider.failure)
            self.assertEqual(journey.row("SELECT phase FROM interaction_instructions WHERE id=?",
                                         (instruction,)), [("accepted",)])
            self.assertEqual(provider.calls, [instruction] * (4 if provider.inverse_paired else 2))
            self.assertFalse(journey.worker_packets)
            self.assertFalse(return_attempts)
            self.assertEqual(journey.row("SELECT count(*) FROM interaction_matrix_requests"), [(0,)])
            rows = journey.row("SELECT r.body,t.execution_harness FROM interaction_results r "
                               "JOIN turns t ON t.id=r.local_turn")
            self.assertEqual(rows, [(answer, engine)])
            self.assertEqual(journey.row("SELECT native_turn FROM interaction_results"),
                             [(f"gateway:{engine}:{instruction}",)])
            self.assertEqual(journey.row("SELECT count(*) FROM interaction_deliveries"), [(1,)])
            presentation = journey.call("route-inverse-result", "conversation", {})
            self.assertIn(answer, json.dumps(presentation))
            result = next(row for row in presentation["presentation"]["items"]
                          if row["kind"] == "worker_result" and answer in row["preview"])
            part = journey.call("route-inverse-result-part", "conversation_part",
                                {"source":result["id"],"revision":result["revision"]})
            self.assertIn(answer, json.dumps(part))
            self.assertTrue(part["native_binding_current"])
            self.assertEqual(journey.row("SELECT codex_thread_id FROM sessions WHERE thread_id=7"),
                             previous_codex)
            history = journey.call("route-inverse-history", "target_inputs", {"selector":"Alpha"})["inputs"]
            self.assertTrue(any(row["instruction"] == instruction for row in history))
            observed = journey.call("route-inverse-observer", "candidates",
                                    {"mode":"inspect", "selectors":["Alpha"]})
            evidence = observed["candidates"][0]["evidence"]
            self.assertEqual(evidence["selected_harness"], engine)
            self.assertEqual(evidence["live_status"]["availability"], "unsupported")
            self.assertIsNone(evidence["live_status"]["native_thread"])
            self.assertEqual(evidence["retained_codex"]["native"], previous_codex[0][0])
            attempts = {row["harness"]: row["phase"] for row in evidence["latest_executions"]}
            self.assertEqual(attempts, {engine: "accepted", "codex": "completed"})

            extra_turns = 0
            extra_results = 0
            if engine != "claude":
                provider.original = "#Alpha Read the explicitly selected fixture memory."
                explicit = {"id":str(uuid.uuid4()),"binding":page["binding"],"text":provider.original}
                provider.human_original = explicit["id"]
                select_memory_for(explicit)
                response = journey.read("input", "submit", json.dumps(explicit))["result"]
                self.assertTrue(response["new_input"])
                journey.wait(lambda: provider.failure or journey.row(
                    "SELECT count(*) FROM interaction_results") == [(2,)])
                self.assertIsNone(provider.failure)
                self.assertEqual(journey.row(
                    "SELECT i.phase,json_extract(i.doc,'$.target_execution.harness') "
                    "FROM interaction_instructions i JOIN interaction_sources s ON s.id=i.input_id "
                    "WHERE s.event_id=?", (explicit["id"],)), [("accepted",engine)])
                self.assertEqual(journey.row(
                    "SELECT COUNT(DISTINCT native_thread_id) FROM turns "
                    "WHERE execution_harness=? AND status='completed'", (engine,)), [(2,)])
                extra_turns, extra_results = 1, 1
            if provider.inverse_paired:
                original_profile = profile.read_bytes()
                profile_doc = json.loads(original_profile)
                profile_doc["body"]["manifestHash"] = "e" * 64
                profile.write_text(json.dumps(profile_doc))
                try:
                    held = submit_original("A paired fixture original with no provider exposure.")
                    journey.wait(lambda: journey.row("SELECT phase FROM conversation_inputs WHERE id=?",
                                                     (held["id"],)) == [("accepted",)])
                    saved = journey.call("route-inverse-unsent", "dispatch",
                                         {**selection, "input_ref":held["id"]})["results"][0]["instruction"]

                    def attempt():
                        return journey.row("SELECT phase,json_extract(doc,'$.local_turn') "
                                           "FROM interaction_instructions WHERE id=?", (saved,))[0]

                    journey.wait(lambda: attempt()[0] == "retained_unsent")
                    first_attempt = attempt()
                    retry = {"id":held["id"], "binding":page["binding"], "instruction":saved}
                    journey.read("input", "retry", json.dumps(retry), ok=False)
                    self.assertEqual(attempt(), first_attempt)
                    journey.read("input", "retry-human", json.dumps(retry))
                    journey.wait(lambda: attempt()[0] == "retained_unsent" and attempt() != first_attempt)
                    self.assertEqual(provider.calls, [instruction] * 4)
                    extra_turns = 2
                finally:
                    profile.write_bytes(original_profile)

            provider.original = "Keep this routed fixture attempt if the Gateway stops."
            lost = submit_original(provider.original)
            select_memory_for(lost)
            provider.human_original = lost["id"]
            journey.wait(lambda: journey.row("SELECT phase FROM conversation_inputs WHERE id=?",
                                             (lost["id"],)) == [("accepted",)])
            provider.hold = Event()
            provider.exposed = Event()
            if engine != "claude":
                provider.mode = "held"
                provider.arrived = provider.exposed
                provider.release = provider.hold
            try:
                submitted = journey.call("route-inverse-interrupt", "dispatch", {
                    **selection, "input_ref":lost["id"],
                })["results"][0]["instruction"]
                self.assertTrue(provider.exposed.wait(12))
                self.assertEqual(journey.row("SELECT phase FROM interaction_instructions WHERE id=?",
                                             (submitted,)), [("submitting",)])
                journey.process.kill()
                journey.process.communicate(timeout=8)
                journey.process = None
            finally:
                provider.hold.set()
            with sqlite3.connect(journey.root / "state.sqlite") as db:
                db.execute("UPDATE app_instance_lock SET heartbeat_at=datetime('now','-1 hour')")
            journey.start()
            journey.wait_control_socket(journey.socket)
            self.assertEqual(journey.row(
                "SELECT i.phase,t.status,s.busy FROM interaction_instructions i "
                "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') "
                "JOIN sessions s ON s.id=t.session_id WHERE i.id=?", (submitted,),
            ), [("uncertain", "failed", 0)])
            self.assertEqual(provider.exposures.count(submitted), 1)
            self.assertEqual(journey.row("SELECT count(*) FROM turns WHERE execution_harness=?", (engine,)), [(2 + extra_turns,)])
            self.assertEqual(journey.row("SELECT count(*) FROM interaction_results"), [(1 + extra_results,)])


        def _direct_exchange(self, journey, provider, return_attempts):
            page = journey.read("presentation", "list", "0", "0")["result"]
            self.assertIs(page["can_select_claude"], True)
            request = dict(binding=page["binding"], id=str(uuid.uuid4()), text=provider.original,
                           target="claude")

            def submit(original, *, fresh):
                result = journey.read("input","submit-human",json.dumps(original))["result"]
                self.assertIs(result["new_input"], fresh)
                return result

            def readback(original):
                ident = original["id"]
                journey.wait(lambda: provider.failure or journey.row(
                    "SELECT phase FROM conversation_inputs WHERE id=?", (ident,)
                )[0][0] in ("claude_replied", "claude_rejected", "claude_unconfirmed", "retained_unsent", "uncertain"), seconds=30)
                self.assertIsNone(provider.failure)
                result = journey.read("input", "status", ident)["result"]
                self.assertEqual(result["phase"], "claude_replied", result)
                return result["claude_reply"]["text"]

            journey.read("input","submit",json.dumps(request),ok=False)
            self.assertEqual(journey.row("SELECT count(*) FROM conversation_inputs"), [(0,)])
            provider.current = request["id"]
            submit(request, fresh=True)
            self.assertIn(ANSWER, readback(request))
            if mixed:
                self.assertEqual(provider.calls, [request["id"]] * 5)
                self.assertEqual(len(journey.worker_packets["native-topic-7"]), 1)
                instruction, phase, doc = journey.instructions(7)[0]
                self.assertIn(phase, ("accepted", "completed"))
                self.assertEqual(json.loads(doc)["text"], request["text"])
                source = journey.row(
                    "SELECT s.event_id,s.human_id,s.channel FROM interaction_sources s "
                    "JOIN interaction_instructions i ON i.input_id=s.id WHERE i.id=?",
                    (instruction,),
                )
                self.assertEqual(source, [(request["id"], 100, "conversation")])
                self.assertEqual(journey.row(
                    "SELECT r.native_thread,r.body FROM interaction_results r "
                    "JOIN turns t ON t.id=r.local_turn WHERE t.execution_harness='codex'"
                ), [("native-topic-7", provider.mixed_worker_reply)])
                self.assertEqual(journey.row("SELECT count(*) FROM interaction_matrix_requests"), [(0,)])
                self.assertFalse(return_attempts)
                return
            self.assertEqual(provider.calls, [request["id"]] * 4)
            provider.previous_session = journey.row(
                "SELECT t.native_thread_id FROM conversation_inputs c JOIN turns t ON t.id=c.local_turn "
                "WHERE c.id=? AND t.execution_harness='claude' AND t.status='completed'",
                (request["id"],),
            )[0][0]
            journey.stop()
            journey.start()
            journey.wait_control_socket(journey.socket)
            self.assertEqual(submit(request, fresh=False)["phase"], "claude_replied")
            self.assertEqual(provider.calls, [request["id"]] * 4)
            # Simulate first Codex initialization of this logical conversation.
            # This uses the real generation triggers and performs no native work.
            with sqlite3.connect(journey.root / "state.sqlite") as db:
                db.execute(
                    "UPDATE sessions SET codex_thread_id='fixture-codex-thread' WHERE chat_id=100 AND thread_id=1"
                )
            self.assertEqual(journey.read("presentation", "list", "0", "0")["result"]["binding"], request["binding"])
            self.assertIs(journey.read("input", "status", request["id"])["result"]["retired"], False)

            provider.previous_original = provider.original
            provider.followup_answer = "I retained the first turn. " * 180 + "End of full reply."
            provider.original = "What did this same conversation retain?"
            followup = dict(request, id=str(uuid.uuid4()), text=provider.original)
            provider.current = followup["id"]
            provider.exposed = Event()
            provider.hold = Event()
            try:
                submit(followup, fresh=True)
                self.assertTrue(provider.exposed.wait(8))
                self.assertEqual(submit(followup, fresh=False)["phase"], "sending")
                self.assertEqual(journey.row("SELECT count(*) FROM turns WHERE execution_harness='claude'"), [(2,)])
            finally:
                provider.hold.set()
            self.assertEqual(readback(followup), provider.followup_answer[:2048])
            offset = 0
            retained = []
            while offset is not None:
                part = journey.read("input", "trace-text", followup["id"], "claude-reply", str(offset))["result"]
                retained.append(part["text"])
                offset = part["next_offset"]
            self.assertEqual("".join(retained), provider.followup_answer)
            self.assertEqual(journey.row(
                "SELECT t.assistant_text FROM conversation_inputs c JOIN turns t ON t.id=c.local_turn "
                "WHERE c.id=? AND t.execution_harness='claude' AND t.status='completed'",(followup["id"],)
            ), [(provider.followup_answer,)])
            self.assertEqual(provider.calls, [request["id"]] * 4 + [followup["id"]])
            provider.original = "Fixture input whose provider result will remain unconfirmed."
            interrupted = dict(request, id=str(uuid.uuid4()), text=provider.original)
            provider.current = interrupted["id"]
            provider.interrupted_id = interrupted["id"]
            provider.exposed = Event()
            provider.hold = Event()
            try:
                submit(interrupted, fresh=True)
                self.assertTrue(provider.exposed.wait(8))
                self.assertEqual(journey.row("SELECT phase FROM conversation_inputs WHERE id=?",
                                             (interrupted["id"],)), [("sending",)])
                # Crash this synthetic Gateway after durable exposure. Its
                # replacement must recover the original without invoking Claude.
                journey.process.kill()
                journey.process.communicate(timeout=8)
                journey.process = None
            finally:
                provider.hold.set()
            with sqlite3.connect(journey.root / "state.sqlite") as db:
                db.execute("UPDATE app_instance_lock SET heartbeat_at=datetime('now','-1 hour')")
            journey.start()
            journey.wait_control_socket(journey.socket)
            self.assertEqual(submit(interrupted, fresh=False)["phase"], "uncertain")
            self.assertEqual(journey.row(
                "SELECT t.status,s.busy FROM conversation_inputs c JOIN turns t ON t.id=c.local_turn "
                "JOIN sessions s ON s.id=t.session_id WHERE c.id=?", (interrupted["id"],)),
                [("failed",0)])
            self.assertEqual(provider.exposures.count(interrupted["id"]), 1)
            self.assertEqual(journey.row("SELECT count(*) FROM interaction_matrix_requests"), [(0,)])
            self.assertEqual(return_attempts, [])
            self.assertEqual(journey.telegram_methods, [])
            self.assertEqual(journey.rpc, [])

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
                forged = client.post("/api/interaction/inputs",
                    json={**request, "private_host_access": True}, headers=headers)
                self.assertEqual(forged.status_code, 400)
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
                first_calls = (2 + hasattr(provider, "skill_name") + hasattr(provider, "foundation_marker")
                               + bool(getattr(provider, "deferred_foundation", []))
                               + len(getattr(provider, "host_tools", [])))
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
                if hasattr(provider, "foundation_revocation"):
                    provider.foundation_revocation.touch()
                    previous_calls = list(provider.calls)
                    denied = {**request, "id": str(uuid.uuid4()), "text": "Probe a revoked Foundation capability."}
                    provider.human_original = denied["id"]
                    submitted = client.post("/api/interaction/inputs", json=denied, headers=headers)
                    self.assertEqual(submitted.status_code, 200, submitted.text)
                    journey.wait(lambda: journey.row(
                        "SELECT phase FROM interaction_matrix_requests WHERE source_event=("
                        "SELECT json_extract(doc,'$.private_matrix_origin.message_id') "
                        "FROM conversation_inputs WHERE id=?) AND phase='rejected'", (denied["id"],)
                    ) == [("rejected",)], seconds=20)
                    status = client.get("/api/interaction/inputs/"+denied["id"], headers=headers).json()
                    self.assertEqual(status["phase"], "claude_rejected")
                    self.assertNotIn("claude_reply", status)
                    self.assertEqual(provider.calls, previous_calls)
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
    direct = engine == "claude" and os.environ.get("FOREGROUND_TEST_INTERACTION_DIRECT") == "1"
    mixed = direct and os.environ.get("FOREGROUND_TEST_MIXED_HARNESSES") == "1"
    telegram_topic = engine == "claude" and os.environ.get("FOREGROUND_TEST_TELEGRAM_TOPIC") == "1"
    inverse = telegram_topic or os.environ.get("FOREGROUND_TEST_INVERSE_HARNESSES") == "1"
    signed_interrupt = os.environ.get("FOREGROUND_TEST_SIGNED_INTERRUPT") if engine != "claude" else None
    if signed_interrupt not in {"1", "before"}:
        signed_interrupt = None
    if inverse and engine == "claude":
        direct = True
    if (interaction or direct or inverse) and not telegram_topic:
        os.environ["FOREGROUND_TEST_WITHOUT_TELEGRAM_CODEX"] = "1"
    if interaction or direct or inverse:
        sys.path.insert(0, str(foreground.ROOT))
    dmk_scripts = os.environ.get("CLAUDE_TEST_DMK_SCRIPTS") if interaction or telegram_topic else None
    scripts = Path(sys.argv[4]) if engine != "claude" else Path(dmk_scripts) if dmk_scripts else None
    raise SystemExit(qualify(engine, gateway, executable, scripts,
                            interaction=interaction, direct=direct, mixed=mixed, inverse=inverse,
                            telegram_topic=telegram_topic, signed_interrupt=signed_interrupt))
