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
from datetime import datetime
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
            harness_switch = telegram_topic and os.environ.get("FOREGROUND_TEST_CLAUDE_HARNESS_SWITCH") == "1"
            visible_handoff = os.environ.get("FOREGROUND_TEST_VISIBLE_HANDOFF") if telegram_topic else None
            if visible_handoff not in {"1", "entry"}:
                visible_handoff = None
            if mixed or inverse:
                # The seeded topics represent an existing embedded Telegram
                # install. Only that predecessor runs in the legacy role.
                selected_binary = journey.binary
                if Path(selected_binary).name == "daimon-gateway" and telegram_topic:
                    predecessor = journey.root / "telecodex"
                    predecessor.symlink_to(Path(selected_binary).resolve())
                    journey.binary = str(predecessor)
                try:
                    journey.start()
                    for topic in (1, 7, 8) if visible_handoff else (1, 7) if inverse else (7,):
                        journey.admit("Fixture seed for the owned Codex conversation", topic=topic)
                        journey.wait(lambda: journey.has("Initial goal turn delivered.", topic))
                        journey.idle()
                    journey.stop()
                finally:
                    journey.binary = selected_binary
                if telegram_topic:
                    with sqlite3.connect(journey.root / "state.sqlite") as db:
                        db.execute("UPDATE sessions SET session_prompt=? WHERE thread_id=7",
                                   ("Keep the selected design instructions.",))
                targets = journey.target_config
                if inverse and not harness_switch:
                    targets = targets.replace('name="Alpha"', f'name="Alpha"\nharness="{engine}"')
                journey.config.write_text(journey.config.read_text() + targets)
                journey.routing = True
            if harness_switch or (telegram_topic and os.environ.get("FOREGROUND_TEST_CLAUDE_MISSING_RESUME") == "1"):
                folder_root = journey.root / "conversation-folders"
                folder_root.mkdir(mode=0o700)
                journey.config.write_text(journey.config.read_text().replace(
                    "[interaction]\n",
                    "[interaction]\ntopic_workspace_root=" + json.dumps(str(folder_root)) + "\n", 1))
            adapter_recovery = telegram_topic and os.environ.get(
                "FOREGROUND_TEST_CLAUDE_ADAPTER_RECOVERY") == "1"
            output_artifacts = telegram_topic and os.environ.get("FOREGROUND_TEST_CLAUDE_OUTPUT_ARTIFACTS") == "1"
            if adapter_recovery or visible_handoff or output_artifacts:
                journey.config.write_text(journey.config.read_text().replace(
                    "[interaction]\n",
                    "[interaction]\ntelegram_projection=true\ntelegram_entry_projection=true\n", 1))
            if output_artifacts:
                retained = journey.root / "retained"
                retained.mkdir(mode=0o700)
                journey.config.write_text(
                    journey.config.read_text()
                    + "\n[interaction.artifact_store]\ndirectory=" + json.dumps(str(retained)) + "\n"
                )
            topic_voice = telegram_topic and os.environ.get("FOREGROUND_TEST_CLAUDE_TOPIC_VOICE") == "1"
            if topic_voice:
                recognizer = journey.root / "topic-asr.py"
                recognizer.write_text(
                    'import json\nprint(json.dumps({"text":"Read the synthetic voice note.","final":True}))\n'
                )
                journey.config.write_text(journey.config.read_text() +
                    '\n[voice]\ntranscriber_label="synthetic topic ASR"\ntranscription_command='
                    + json.dumps(["/usr/bin/python3", str(recognizer)]) + "\n")
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
                    if expected := getattr(self.server, "returned_dependency", None):
                        ident, phase, native, scope, prompt = self.server.journey.row(
                            "SELECT i.id,i.phase,t.native_thread_id,t.execution_native_scope,t.prompt "
                            "FROM interaction_session_authors a JOIN interaction_instructions i ON i.input_id=a.input_id "
                            "JOIN interaction_session_requests r ON r.id=json_extract(a.doc,'$.local_request') "
                            "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') "
                            "WHERE t.status='running' AND json_extract(a.doc,'$.kind')='session_result' "
                            "AND ((? AND r.phase='requested' AND json_extract(a.doc,'$.dependency_status')='progress') "
                            "OR (NOT ? AND r.phase='returned' AND i.id=json_extract(r.doc,'$.return_instruction')))",
                            (expected.get("progress", False), expected.get("progress", False)),
                        )[0]
                        assert phase == "submitting"
                        assert native == expected["native"], "Returned result started a different native session"
                        assert scope == expected["scope"], "Returned result used a different tool scope"
                        assert expected["text"] in prompt
                        assert '"kind":"session_result"' in prompt
                        self.server.current = ident
                        self.server.exposures.append(ident)
                        return {"native_session_id": native, "native_session_scope": scope}
                    if inverse:
                        ident, phase, session, scope, prompt = self.server.journey.row(
                            "SELECT i.id,i.phase,t.native_thread_id,t.execution_native_scope,t.prompt "
                            "FROM interaction_instructions i JOIN interaction_sources s ON s.id=i.input_id "
                            "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') "
                            "WHERE s.event_id=? AND t.execution_harness='claude' AND t.status='running'",
                            (self.server.human_original,),
                        )[0]
                        assert phase == "submitting"
                        if getattr(self.server, "attachment", None) and not getattr(self.server, "routed_paired_human", None):
                            assert prompt == self.server.attachment["caption"]
                        else:
                            assert self.server.original in prompt
                        if telegram_topic and not getattr(self.server, "routed_paired_human", None):
                            if digest := getattr(self.server, "topic_voice_digest", None):
                                assert prompt.startswith("[Machine transcription of the human's clip]")
                                assert f"Audio SHA-256: {digest}" in prompt
                                assert "Spoken slash commands are ordinary speech." in prompt
                            elif not getattr(self.server, "attachment", None):
                                assert prompt == getattr(self.server, "goal_command", self.server.original)
                        else:
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

            class VisibleHandoffProvider(ClaudeProvider):
                def do_POST(self):
                    try:
                        assert self.path.startswith("/v1/messages")
                        length = int(self.headers["Content-Length"])
                        assert 0 < length < 262_144
                        data = json.loads(self.rfile.read(length))
                        row, = journey.row(
                            """SELECT i.id,i.phase,i.doc,t.status,t.prompt
                               FROM interaction_session_requests c
                               JOIN interaction_instructions i ON i.id=c.target_instruction
                               JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn')""")
                        instruction, phase, doc, status, prompt = row
                        assert (phase, status) == ("submitting", "running")
                        assert '"kind":"session_request"' in prompt
                        assert self.server.handoff_text in json.dumps(data["messages"])
                        self.server.exposures.append(instruction)
                        requests = json.loads(doc)["requests"]
                        claim = {"requests": requests, "covered": [instruction], "completed": requests}
                        def hold():
                            self.server.handoff_stream.set()
                            assert self.server.handoff_release.wait(20), "The early projection did not settle"
                        self.send_fixture_message(data, "visible_handoff",
                            {"type": "text", "text": ""},
                            {"type": "text_delta", "text": ANSWER + "\n<daimon-result>"
                             + json.dumps(claim) + "</daimon-result>"},
                            "end_turn", before_finish=hold)
                    except Exception as error:
                        self.server.failure = error
                        if not self.server.handoff_stream.is_set():
                            self.send_error(400)

            if visible_handoff:
                handler = VisibleHandoffProvider
            elif engine == "claude":
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
                skill_refresh = telegram_topic and os.environ.get("FOREGROUND_TEST_TELEGRAM_SKILL_REFRESH") == "1"
                if skill_refresh or (interaction and os.environ.get("FOREGROUND_TEST_SHARED_SKILLS") == "1"):
                    shared = root / "shared-agent-skills"
                    skill = shared / "fixture-skill"
                    skill.mkdir(parents=True)
                    provider.skill_name = "compaii-shared:fixture-skill"
                    provider.skill_marker = "Readback from the shared skill directory."
                    provider.skill_file = skill / "SKILL.md"
                    provider.skill_file.write_text(
                        "---\nname: fixture-skill\ndescription: A synthetic shared skill.\n"
                        'metadata:\n  version: "1.0.0"\n---\n' + provider.skill_marker
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
                if skill_refresh:
                    anchor = json.loads(subprocess.check_output(
                        [*command[:-2], "--skill-resume-anchor", str(profile)],
                        text=True, timeout=5,
                    ))
                    config["skillContinuity"] = {"layoutRevision": anchor["layoutRevision"]}
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
                    if harness_switch:
                        self._claude_harness_switch(journey, provider)
                        return
                    if adapter_recovery:
                        self._claude_adapter_recovery(journey, provider, adapter_config)
                        return
                    if telegram_topic and os.environ.get("FOREGROUND_TEST_CLAUDE_WEB_GOAL") == "1":
                        self._conversation_goal(journey, provider)
                        return
                    if telegram_topic and os.environ.get("FOREGROUND_TEST_CLAUDE_WEB_QUOTE") == "1":
                        self._exact_claude_quote(journey, provider, profile, web=True)
                        return
                    if telegram_topic and os.environ.get("FOREGROUND_TEST_CLAUDE_WEB_FILES") == "1":
                        self._conversation_attachments(journey, provider)
                        return
                    if telegram_topic and os.environ.get("FOREGROUND_TEST_CODEX_WEB_ROUNDTRIP") == "1":
                        self._telegram_codex_handoff(journey, provider)
                        return
                    if telegram_topic:
                        teledaimon = journey.root / "teledaimon"
                        teledaimon.symlink_to(Path(gateway).resolve())
                        adapter = subprocess.Popen(
                            [str(teledaimon), str(adapter_config)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                        )
                        try:
                            if visible_handoff:
                                self._visible_handoff(journey, provider, entry=visible_handoff == "entry")
                            elif os.environ.get("FOREGROUND_TEST_TELEGRAM_STEER") == "1":
                                self._telegram_steer(journey, provider, profile)
                            elif os.environ.get("FOREGROUND_TEST_CLAUDE_TELEGRAM_QUOTE") == "1":
                                self._exact_claude_quote(journey, provider, profile)
                            elif output_artifacts:
                                self._claude_output_artifacts(journey, provider, profile)
                            elif topic_voice:
                                self._claude_topic_voice(journey, provider)
                            elif os.environ.get("FOREGROUND_TEST_TELEGRAM_FILES") == "1":
                                self._telegram_attachments(journey, provider)
                            elif os.environ.get("FOREGROUND_TEST_TELEGRAM_ALBUM") == "1":
                                self._telegram_album(journey, provider)
                            elif os.environ.get("FOREGROUND_TEST_TELEGRAM_QUOTA") == "1":
                                self._telegram_quota(journey, provider)
                            elif os.environ.get("FOREGROUND_TEST_TELEGRAM_CANCEL") == "1":
                                self._telegram_cancel(journey, provider)
                            elif dmk_write:
                                self._telegram_dmk_write(journey, provider)
                            elif skill_refresh:
                                self._telegram_skill_refresh(journey, provider)
                            elif os.environ.get("FOREGROUND_TEST_TELEGRAM_CODEX_HANDOFF") == "1":
                                self._telegram_codex_handoff(journey, provider)
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
                    if signed_interrupt == "return-crash":
                        self._signed_return_crash(journey, provider, selected, return_attempts, fixture, body)
                        return
                    if signed_interrupt:
                        competing = None
                        if signed_interrupt == "crash":
                            original_two = fixture.lane("legion", at_ms=service.clock()).converse(
                                text="Another signed original for the same fixture entry.",
                                addressees=[body],
                                request_id=str(uuid.uuid4()),
                                targets=fixture.canonical_targets(),
                                ttl_ms=30_000,
                                deliver=lambda _, payload: service.we_lane.intake(payload),
                            )
                            competing = dict(cursor=None, event_id=original_two["message_id"],
                                             author=author, thread_id=original_two["thread_id"])
                        self._signed_interrupt(journey, provider, selected, return_attempts, competing)
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
                peer_context=SimpleNamespace(configured=peer, egress=receiver.peer_context.egress,
                                         authority=fixture.authority,
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

        def _signed_interrupt(self, journey, provider, selected, return_attempts, competing=None):
            provider.mode = "held"
            provider.arrived, provider.release = Event(), Event()
            cancelled = Event()
            if engine == "claude":
                provider.quote_response = "A late answer to the isolated signed original."
                provider.quote_answer_gate = (provider.arrived, provider.release, cancelled)
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
                    if signed_interrupt == "crash":
                        rejected = subprocess.run(
                            [*args[:-1], json.dumps(competing)], capture_output=True, text=True,
                            timeout=8,
                        )
                        self.assertNotEqual(rejected.returncode, 0)
                        self.assertIn("Foreground Matrix destination is at capacity",
                                      rejected.stderr + rejected.stdout)
                        self.assertEqual(journey.row(
                            "SELECT count(*) FROM interaction_matrix_requests WHERE source_event=?",
                            (competing["event_id"],),
                        ), [(0,)])
                        # The fixture owns this process. SIGKILL prevents the
                        # foreground worker from settling through clean shutdown.
                        journey.process.kill()
                        journey.process.communicate(timeout=8)
                        journey.process = None
                    else:
                        requested = journey.read("matrix", engine, "interrupt", ident)["result"]
                        self.assertTrue(requested["interruption_requested"])
                    stdout, errors = run.communicate(timeout=15)
                    if signed_interrupt != "crash":
                        self.assertEqual(run.returncode, 0, errors)
                finally:
                    cancelled.set()
                    provider.release.set()
                    if run.poll() is None:
                        run.terminate()
            if signed_interrupt == "crash":
                self._restart_after_signed_crash(journey)
                outcome = journey.read("matrix", engine, "status", ident)["result"]
                self.assertEqual(outcome["phase"], "provider_uncertain", outcome)
                for key in ("input_id", "request_id", "session_id", "native_session_id", "thread_id"):
                    self.assertEqual(outcome[key], in_flight[key], key)
                self.assertEqual(journey.read("matrix", engine, "run", json.dumps(selected))["result"],
                                 outcome)
                self.assertIsNone(provider.failure)
                self.assertEqual(provider.calls, [ident])
                self.assertEqual(return_attempts, [])
                self.assertEqual(journey.telegram_methods, [])
                self.assertEqual(journey.rpc, [])
                return

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

        def _restart_after_signed_crash(self, journey):
            # Use the real lease predicate with a shorter test-only limit.
            # The old PID is confirmed dead; preserve its journal and lease.
            heartbeat, = journey.row(
                "SELECT heartbeat_at FROM app_instance_lock WHERE key='main'"
            )[0]
            journey.extra_env = {**getattr(journey, "extra_env", {}),
                                 "TELECODEX_INSTANCE_STALE_SECONDS": "1"}
            expires = datetime.fromisoformat(heartbeat).timestamp() + 1
            journey.wait(lambda: time.time() > expires, seconds=3)
            journey.start()
            journey.wait_control_socket(journey.socket)

        def _signed_return_crash(self, journey, provider, selected, return_attempts, fixture, body):
            retained, release = Event(), Event()

            def hold_ack():
                retained.set()
                assert release.wait(12), "The fixture never released the signed return"

            def received_replies():
                return [row["event_id"] for row in fixture.ledger_a.conversation_evidence()
                        if row["subject"] == "communication"
                        and row["origin"]["embodiment_id"] == body
                        and row["payload"]["intent"]["thread_id"] == selected["thread_id"]
                        and ANSWER in row["payload"]["body"]["text"]]

            self.after_return_intake = hold_ack
            ident = selected["event_id"]
            args = [journey.binary, "--control", str(journey.config),
                    "matrix", engine, "run", json.dumps(selected)]
            with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as run:
                try:
                    self.assertTrue(retained.wait(20), provider.failure)
                    returning = journey.read("matrix", engine, "status", ident)["result"]
                    self.assertEqual(returning["phase"], "returning", returning)
                    self.assertEqual(return_attempts, [returning["result"]["send_id"]])
                    message = received_replies()
                    self.assertEqual(len(message), 1)
                    journey.process.kill()
                    journey.process.communicate(timeout=8)
                    journey.process = None
                    run.communicate(timeout=10)
                finally:
                    release.set()
                    if run.poll() is None:
                        run.terminate()

            self._restart_after_signed_crash(journey)
            outcome = journey.read("matrix", engine, "status", ident)["result"]
            self.assertEqual(outcome["phase"], "return_uncertain", outcome)
            for key in ("input_id", "request_id", "session_id", "native_session_id", "thread_id"):
                self.assertEqual(outcome[key], returning[key], key)
            self.assertEqual(outcome["result"]["send_id"], returning["result"]["send_id"])
            self.assertEqual(journey.read("matrix", engine, "run", json.dumps(selected))["result"],
                             outcome)
            self.assertEqual(received_replies(), message)
            self.assertEqual(return_attempts, [outcome["result"]["send_id"]])
            self.assertIsNone(provider.failure)
            self.assertEqual(provider.calls, [ident] * 2)
            self.assertEqual(journey.telegram_methods, [])
            self.assertEqual(journey.rpc, [])

        def _visible_handoff(self, journey, provider, *, entry=False):
            from conversation_cold_entry_http_io import Browser

            journey.allow_local_dependencies = True
            browser = Browser(journey)
            self.addCleanup(browser.provider.close)
            self.addCleanup(browser.client.close)
            alpha = next(row for row in browser.get("/api/interaction/sessions")["sessions"]
                         if row["audio_key"] == "100:7")
            path = "/api/interaction/sessions/" + alpha["id"]
            provider.handoff_text = "Check the synthetic design summary."
            provider.handoff_stream = Event()
            provider.handoff_release = Event()
            original = str(uuid.uuid4())
            original_text = "Ask Alpha for a visible report on the synthetic design."
            page = journey.read("presentation", "list", "0", "0")["result"]
            body = {"id": original, "binding": page["binding"], "text": original_text}
            journey.read("input", "submit-human", json.dumps(body))
            journey.wait(lambda: journey.row("SELECT phase FROM conversation_inputs WHERE id=?",
                                             (original,)) == [("accepted",)])
            route = journey.call("route-visible-caller", "dispatch", {
                "input_ref": original, "destinations": [
                    {"selector": "Beta", "relation": "new", "requests": []}],
            })["results"][0]
            self.assertTrue(route["new_admission"], route)
            journey.wait(lambda: journey.instructions(8) and journey.instructions(8)[0][1] == "accepted")
            beta = journey.row("SELECT codex_thread_id FROM sessions WHERE thread_id=8")[0][0]
            caller_native = journey.web_thread if entry else beta
            caller_turn = journey.web_turn if entry else journey.workers[caller_native]
            if entry:
                journey.workers[caller_native] = caller_turn
            caller_send = next(send for native, send in journey.clients.values()
                               if native == caller_native)

            def caller_call(ident, operation, arguments):
                caller_send({"id": ident, "method": "item/tool/call", "params": {
                    "threadId": caller_native, "turnId": caller_turn, "callId": ident,
                    "tool": "interaction_controller",
                    "arguments": {"operation": operation, "arguments": arguments},
                }})
                journey.wait(lambda: ident in journey.tool_results)
                result = journey.tool_results[ident]
                self.assertTrue(result["success"], result)
                return json.loads(result["contentItems"][0]["text"])

            parents = caller_call("route-visible-inputs", "coordination_inputs", {})["inputs"]
            parent, = [item for item in parents if item["eligible_coordination_parent"]]
            self.assertEqual(parent["source_event"], original)
            capabilities = caller_call("route-visible-capabilities", "capabilities", {})
            self.assertIn("report_to_topic", capabilities["operations"]["session_request"]["arguments"])
            request = {"parent_instruction": parent["instruction"], "request_id": "visible-fixture",
                       "selector": "Alpha", "text": provider.handoff_text, "report_to_topic": True}
            try:
                first = caller_call("route-visible-admit", "session_request", request)
                self.assertTrue(first.get("new_admission"), first)
                self.assertTrue(provider.handoff_stream.wait(15), (
                    provider.failure, journey.row(
                        """SELECT i.phase,t.status,t.execution_native_scope IS NOT NULL
                           FROM interaction_session_requests c
                           JOIN interaction_instructions i ON i.id=c.target_instruction
                           LEFT JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn')"""),
                ))
                journey.wait(lambda: provider.failure or journey.has(provider.handoff_text, 7), seconds=12)
                self.assertIsNone(provider.failure)
                pending, = browser.get(path)["pending_items"]
                self.assertEqual(pending["role"], "assistant")
                self.assertTrue(pending["handoff"])
                self.assertIn(provider.handoff_text, pending["text"])
                self.assertFalse(journey.has(ANSWER, 7))
                self.assertEqual(journey.row("""SELECT t.status,json_extract(i.doc,'$.native_input_accepted')
                    FROM interaction_session_requests c JOIN interaction_instructions i ON i.id=c.target_instruction
                    JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn')"""), [("running",1)])
            finally:
                provider.handoff_release.set()
            journey.wait(lambda: provider.failure or journey.has(ANSWER, 7), seconds=20)
            self.assertIsNone(provider.failure)
            items = browser.get(path)
            self.assertEqual(items["pending_items"], [])
            self.assertEqual([(row["role"], row["text"]) for row in items["items"][-2:]],
                             [("assistant", pending["text"]), ("assistant", ANSWER)])
            self.assertEqual(sum(provider.handoff_text in message["text"] for message, _ in journey.messages), 1)
            self.assertEqual(len(provider.exposures), 1)
            repeat = caller_call("route-visible-reuse", "session_request", request)
            self.assertFalse(repeat["new_admission"])
            self.assertEqual(repeat["instruction"]["id"], first["instruction"]["id"])
            if entry:
                # The general conversation can finish its request turn while
                # the retained dependency waits to enter the same thread.
                journey.finish(caller_native, caller_turn)
            journey.wait(lambda: journey.row("""
                SELECT c.phase,i.phase,json_extract(i.doc,'$.native_thread')
                FROM interaction_session_requests c JOIN interaction_instructions i
                ON i.id=json_extract(c.doc,'$.return_instruction')
            """) == [("returned", "accepted", caller_native)])
            self.assertEqual(sum(ANSWER in json.dumps(packet["input"])
                                 for packet in journey.worker_packets[caller_native]), 1)
            journey.finish(beta, journey.workers[beta])
            if not entry:
                journey.finish(journey.web_thread, journey.web_turn)

        def _telegram_codex_handoff(self, journey, provider):
            codex = journey.row("SELECT codex_thread_id FROM sessions WHERE thread_id=7")[0][0]
            provider.expected_codex_handoff = {
                "native": codex,
                "original": "Fixture seed for the owned Codex conversation",
                "reply": "Initial goal turn delivered.",
            }
            web_roundtrip = os.environ.get("FOREGROUND_TEST_CODEX_WEB_ROUNDTRIP") == "1"

            def selected_browser():
                from conversation_cold_entry_http_io import Browser

                browser = Browser(journey)
                self.addCleanup(browser.provider.close)
                self.addCleanup(browser.client.close)
                workspace = browser.get("/api/interaction/sessions")
                destination = next(row["destination"] for row in workspace["sessions"]
                                   if row["audio_key"] == "100:7")
                return browser, destination

            provider.original = "Continue our existing design from the Codex exchange."
            if web_roundtrip:
                browser, destination = selected_browser()
                provider.paired_human = False
                provider.routed_paired_human = 100
                provider.human_original = str(uuid.uuid4())
                update, _ = browser.text(provider.original, reply=destination,
                                         original_id=provider.human_original)
                journey.wait(lambda: provider.failure or journey.row(
                    "SELECT i.phase,t.status FROM interaction_instructions i "
                    "JOIN interaction_sources s ON s.id=i.input_id "
                    "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') WHERE s.event_id=?",
                    (update,),
                ) == [("accepted", "completed")], seconds=30)
                self.assertIsNone(provider.failure)
                journey.wait(lambda: any(
                    ANSWER in item.get("preview", "")
                    for item in browser.get("/api/interaction")["items"]
                ), seconds=20)
            else:
                provider.human_original = str(journey.sequence + 1)
                update = journey.admit(provider.original, topic=7)
                journey.wait(lambda: provider.failure or journey.has(ANSWER, 7), seconds=30)
            self.assertIsNone(provider.failure)
            self.assertEqual(journey.row(
                "SELECT i.id,i.phase,t.native_thread_id FROM interaction_sources s "
                "JOIN interaction_instructions i ON i.input_id=s.id "
                "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') WHERE s.event_id=?",
                (str(update),),
            ), [(provider.current, "accepted", provider.codex_handoff_native)])
            self.assertNotEqual(provider.codex_handoff_native, codex)
            self.assertEqual(journey.row("SELECT codex_thread_id FROM sessions WHERE thread_id=7"),
                             [(codex,)])
            if os.environ.get("FOREGROUND_TEST_TELEGRAM_CODEX_ROUNDTRIP") != "1":
                return

            claude_prompt = provider.original
            calls_before_switch = list(provider.calls)
            journey.idle()
            journey.stop()
            config = journey.config.read_text()
            selected = 'name="Alpha"\nharness="claude"'
            self.assertIn(selected, config)
            folder_root = journey.root / "conversation-folders"
            folder_root.mkdir(mode=0o700)
            config = config.replace("[interaction]\n",
                "[interaction]\ntopic_workspace_root=" + json.dumps(str(folder_root)) + "\n", 1)
            journey.config.write_text(config.replace(selected, 'name="Alpha"', 1))
            journey.start()
            journey.wait_control_socket(journey.socket)
            session = journey.row("SELECT id FROM sessions WHERE thread_id=7")[0][0]
            adopted = journey.read("topics", "workspace", "adopt", "7", str(session))["result"]
            self.assertTrue(adopted["folder_ready"])
            checkpoint = Path(adopted["conversation_folder"]) / "CONTINUITY.md"
            checkpoint.touch(mode=0o600, exist_ok=False)
            checkpoint.write_text("Synthetic design checkpoint at revision two.")

            browser = None
            destination = None
            if web_roundtrip:
                journey.routing = True
                browser, destination = selected_browser()

            def native_start(original):
                offset = len(journey.rpc)
                if browser:
                    original_id, _ = browser.text(original, reply=destination)
                else:
                    journey.admit(original, topic=7)

                def matching():
                    return [r["params"] for r in journey.rpc[offset:] if r.get("method") == "turn/start"
                            and any(original in i.get("text", "") for i in r["params"].get("input", []))]
                journey.wait(matching, seconds=25)
                self.assertEqual(len(matching()), 1)
                request = matching()[0]
                self.assertEqual(request["threadId"], codex)
                self.assertEqual(len(request["input"]), 1)
                if browser:
                    self.assertNotIn(claude_prompt, request["input"][0]["text"])
                    self.assertNotIn(ANSWER, request["input"][0]["text"])
                    item = "codex-return-" + original_id
                    answer = "Owned Codex answer for " + original
                    journey.answer_worker(7, answer, item=item)
                    journey.wait(lambda: journey.row(
                        "SELECT count(*) FROM interaction_results WHERE native_thread=? AND body=?",
                        (codex, answer),
                    ) == [(1,)], seconds=20)
                    self.assertEqual(browser.status(original_id)["phase"], "routed")
                    journey.wait(lambda: any(
                        item.get("preview") == answer for item in browser.get("/api/interaction")["items"]
                    ), seconds=20)
                else:
                    self.assertEqual(request["input"][0]["text"], original)
                journey.idle()
                return request.get("additionalContext") or {}

            original = "Yes, go ahead." if browser else "Continue the design back in Codex."
            context = native_start(original)
            fragments = [value for key, value in sorted(context.items())
                         if key.startswith("gateway.history.") and key != "gateway.history.source"]
            self.assertTrue(fragments, "The resumed Codex turn received no Claude context")
            self.assertTrue(all(f["kind"] == "untrusted" and f["name"] == "gateway_history" for f in fragments))
            seed = json.loads("".join(f["value"] for f in fragments))
            self.assertEqual(seed["ownedExchanges"]["human"], claude_prompt)
            self.assertIn(ANSWER, seed["ownedExchanges"]["assistant"])
            self.assertEqual(seed["ownedExchanges"]["nativeThread"], provider.codex_handoff_native)
            self.assertEqual(seed["projectCheckpoint"], "Synthetic design checkpoint at revision two.")
            later = native_start("Continue normally in Codex.")
            self.assertFalse(any(key.startswith("gateway.history.") for key in later))
            self.assertEqual(provider.calls, calls_before_switch)

        def _telegram_skill_refresh(self, journey, provider):
            def submit(text):
                provider.original = text
                provider.human_original = str(journey.sequence + 1)
                update = journey.admit(text, topic=7)
                self.assertEqual(str(update), provider.human_original)

                def accepted():
                    return journey.row(
                        "SELECT i.id,t.native_thread_id,t.execution_native_scope FROM interaction_sources s "
                        "JOIN interaction_instructions i ON i.input_id=s.id "
                        "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') "
                        "WHERE s.event_id=? AND i.phase='accepted' AND t.status='completed'",
                        (str(update),),
                    )

                journey.wait(lambda: provider.failure or accepted(), seconds=30)
                self.assertIsNone(provider.failure)
                return accepted()[0]

            first_prompt = "Load the first version of the shared skill and finish this turn."
            first, native, scope = submit(first_prompt)
            calls_per_turn = 3 + len(provider.host_tools)
            self.assertEqual(provider.calls, [first] * calls_per_turn)
            provider.skill_marker = "Readback from version two of the shared skill."
            provider.skill_file.write_text(provider.skill_file.read_text()
                .replace('"1.0.0"', '"1.1.0"')
                .replace("Readback from the shared skill directory.", provider.skill_marker))
            provider.refreshed_skill = {"native": native, "scope": scope, "previous_prompt": first_prompt}
            provider.calls.clear()
            second, resumed, refreshed_scope = submit("Load the updated shared skill in this same topic.")
            self.assertEqual(provider.calls, [second] * calls_per_turn)
            self.assertEqual((resumed, refreshed_scope), (native, scope))
            self.assertNotEqual(first, second)
            self.assertEqual(journey.row("SELECT count(*) FROM interaction_results"), [(2,)])

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

        def _claude_adapter_recovery(self, journey, provider, adapter_config):
            from conversation_cold_entry_http_io import Browser

            browser = Browser(journey)
            self.addCleanup(browser.provider.close)
            self.addCleanup(browser.client.close)
            destination = next(row["destination"]
                               for row in browser.get("/api/interaction/sessions")["sessions"]
                               if row["audio_key"] == "100:7")
            provider.paired_human = False
            provider.routed_paired_human = 100
            teledaimon = journey.root / "teledaimon"
            teledaimon.symlink_to(Path(journey.binary).resolve())

            def start_adapter():
                return subprocess.Popen([str(teledaimon), str(adapter_config)], text=True,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

            def stop_adapter(process):
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
                _, errors = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, errors)

            def result(answer):
                provider.original = "Request a fixture reply while testing Telegram delivery."
                provider.human_original = str(uuid.uuid4())
                provider.quote_response = answer
                browser.text(provider.original, reply=destination, original_id=provider.human_original)
                journey.wait(lambda: provider.failure or any(
                    row.get("preview") == answer for row in browser.get("/api/interaction")["items"]
                ), seconds=25)
                self.assertIsNone(provider.failure)
                rows = journey.row(
                    "SELECT d.id,r.id FROM interaction_deliveries d JOIN interaction_results r ON r.id=d.result_id "
                    "WHERE r.body=? AND json_extract(d.doc,'$.origin.thread_id')=1", (answer,))
                self.assertEqual(len(rows), 1)
                return rows[0]

            def topic_projection(result_id):
                return journey.row(
                    "SELECT p.phase, count(x.part), max(x.message_id) "
                    "FROM topic_publications p JOIN sessions s ON s.id=p.session_id "
                    "LEFT JOIN topic_publication_parts x ON x.publication=p.id "
                    "WHERE p.source=? AND p.kind='portable_topic_exchange' AND s.thread_id=7 GROUP BY p.id",
                    (result_id,),
                )

            def in_topic(answer, topic):
                return sum(answer in message["text"] and message["message_thread_id"] == topic
                           for message, _ in journey.messages)

            def delivery(id):
                return journey.row(
                    "SELECT d.phase,count(p.part),max(p.message_id) FROM interaction_deliveries d "
                    "LEFT JOIN interaction_delivery_parts p ON p.delivery_id=d.id WHERE d.id=? GROUP BY d.id",
                    (id,),
                )

            gateway_pid = journey.process.pid
            ready_answer = "This Claude answer was retained while Telegram was unavailable."
            ready, ready_result = result(ready_answer)
            journey.wait(lambda: journey.row(
                "SELECT phase FROM interaction_deliveries WHERE id=? "
                "AND json_extract(doc,'$.telegram_publication_selected')=1", (ready,),
            ) == [("reserved",)], seconds=8)
            self.assertEqual(delivery(ready), [("reserved", 0, None)])
            journey.wait(lambda: topic_projection(ready_result) in ([("ready", 0, None)],
                                                                   [("ready", 1, None)]))
            self.assertEqual([in_topic(ready_answer, topic) for topic in (1, 7)], [0, 0])

            adapter = start_adapter()
            try:
                journey.wait(lambda: adapter.poll() is not None or
                             (delivery(ready) and delivery(ready)[0][0] == "delivered"), seconds=12)
                self.assertIsNone(adapter.poll())
                self.assertEqual(delivery(ready)[0][:2], ("delivered", 1))
                first_receipt = delivery(ready)
                self.assertTrue(first_receipt[0][2])
                journey.wait(lambda: topic_projection(ready_result)
                             and topic_projection(ready_result)[0][:2] == ("sent", 1))
                first_projection = topic_projection(ready_result)
                self.assertTrue(first_projection[0][2])
                self.assertEqual([in_topic(ready_answer, topic) for topic in (1, 7)], [1, 1])
                lost_answer = "This Claude answer has a deliberately lost Telegram acknowledgement."
                journey.before_send_message_reply = lambda payload: (
                    False if payload.get("message_thread_id") == 1 and lost_answer in payload["text"] else None)
                lost, lost_result = result(lost_answer)
                journey.wait(lambda: delivery(lost) == [("uncertain", 1, None)], seconds=10)
                journey.wait(lambda: topic_projection(lost_result)
                             and topic_projection(lost_result)[0][:2] == ("sent", 1))
                lost_projection = topic_projection(lost_result)
            finally:
                stop_adapter(adapter)

            polls = journey.telegram_methods.count("getUpdates")
            adapter = start_adapter()
            try:
                journey.wait(lambda: journey.telegram_methods.count("getUpdates") > polls, seconds=12)
                following_answer = "This is a new Claude answer after Telegram returned."
                following, following_result = result(following_answer)
                journey.wait(lambda: delivery(following) and delivery(following)[0][0] == "delivered",
                             seconds=15)
                journey.wait(lambda: topic_projection(following_result)
                             and topic_projection(following_result)[0][:2] == ("sent", 1))
                self.assertEqual(delivery(ready), first_receipt)
                self.assertEqual(delivery(lost), [("uncertain", 1, None)])
                self.assertEqual(topic_projection(ready_result), first_projection)
                self.assertEqual(topic_projection(lost_result), lost_projection)
                for answer in (ready_answer, lost_answer, following_answer):
                    self.assertEqual([in_topic(answer, topic) for topic in (1, 7)], [1, 1])
                self.assertEqual(len(set(provider.calls)), 3)

                provider.paired_human = True
                provider.routed_paired_human = None
                provider.original = "Continue in this topic after the adapter returned."
                with journey.lock:
                    provider.human_original = str(journey.sequence + 1)
                reply = "The same Claude topic answered an original from Telegram."
                provider.quote_response = reply
                update = journey.admit(provider.original, topic=7)
                self.assertEqual(str(update), provider.human_original)
                journey.wait(lambda: provider.failure or any(
                    row.get("preview") == reply for row in browser.get("/api/interaction")["items"]
                ), seconds=20)
                self.assertIsNone(provider.failure)
                journey.wait(lambda: [in_topic(reply, topic) for topic in (1, 7)] == [1, 1])
                self.assertEqual(journey.row(
                    "SELECT count(*),count(DISTINCT t.native_thread_id) FROM interaction_results r "
                    "JOIN turns t ON t.id=r.local_turn WHERE t.execution_harness='claude' AND r.item_id='final'"
                ), [(4, 1)])
                self.assertEqual(len(set(provider.calls)), 4)
                self.assertEqual(journey.process.pid, gateway_pid)
            finally:
                stop_adapter(adapter)

        def _conversation_goal(self, journey, provider):
            from conversation_cold_entry_http_io import Browser

            browser = Browser(journey, companion=True, companion_workspace=True)
            self.addCleanup(browser.provider.close)
            self.addCleanup(browser.client.close)
            destination = next(row["destination"]
                               for row in browser.get("/api/interaction/sessions")["sessions"]
                               if row["audio_key"] == "100:7")
            provider.paired_human = False
            provider.routed_paired_human = 100
            provider.original = "Establish the selected Claude native session."
            provider.quote_response = "I am ready to inspect this topic's goal."
            provider.human_original = str(uuid.uuid4())
            browser.text(provider.original, reply=destination, original_id=provider.human_original)
            journey.wait(lambda: provider.failure or any(
                row.get("preview") == provider.quote_response
                for row in browser.get("/api/interaction")["items"]
            ), seconds=25)
            self.assertIsNone(provider.failure)
            journey.idle()
            native = journey.row("SELECT native_thread_id FROM turns WHERE execution_harness='claude'")[0][0]
            calls = list(provider.calls)
            self.assertEqual(len(calls), 1)

            goal, _ = browser.text("/goal", reply=destination)
            journey.wait(lambda: provider.failure or any(
                "No goal set." in row.get("preview", "")
                for row in browser.get("/api/interaction")["items"]
            ), seconds=25)
            self.assertIsNone(provider.failure)
            journey.idle()
            self.assertEqual(journey.row(
                "SELECT i.phase,t.execution_harness,t.status,t.native_thread_id FROM interaction_sources s "
                "JOIN interaction_instructions i ON i.input_id=s.id "
                "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') WHERE s.event_id=?",
                (goal,),
            ), [("accepted", "claude", "completed", native)])
            _, readback = browser.text("/goal", reply=destination, original_id=goal)
            self.assertIs(readback["new_input"], False)

            lifecycle = os.environ.get("FOREGROUND_TEST_CLAUDE_GOAL_LIFECYCLE")
            if lifecycle in {"active", "completed"}:
                condition = "Report that the synthetic goal fixture is ready."
                provider.routed_paired_human = None
                provider.goal_evaluations = 0
                provider.goal_met = lifecycle == "completed"
                provider.original = condition
                provider.quote_response = "The synthetic goal fixture is ready."

                def command_result(command, *, submitted=True):
                    provider.goal_command = command
                    ident = str(uuid.uuid4())
                    provider.human_original = ident
                    browser.text(command, reply=destination, original_id=ident)

                    def terminal():
                        return journey.row(
                            "SELECT i.phase,t.execution_harness,t.status,t.native_thread_id,t.assistant_text "
                            "FROM interaction_sources s "
                            "JOIN interaction_instructions i ON i.input_id=s.id "
                            "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') "
                            "WHERE s.event_id=? AND t.status IN ('completed','failed')",
                            (ident,),
                        )

                    journey.wait(lambda: provider.failure or terminal(), seconds=25)
                    self.assertIsNone(provider.failure)
                    journey.idle()
                    phase, harness, status, session_id, answer = terminal()[0]
                    self.assertEqual((harness, session_id), ("claude", native if submitted else None))
                    return ident, phase, status, answer

                set_command = f"/goal {condition}"
                goal_id, phase, status, answer = command_result(set_command)
                calls = list(provider.calls)
                evaluations = provider.goal_evaluations
                _, duplicate = browser.text(set_command, reply=destination, original_id=goal_id)
                self.assertIs(duplicate["new_input"], False)
                if provider.goal_met:
                    self.assertEqual((phase, status, answer),
                                     ("accepted", "completed", provider.quote_response))
                    self.assertEqual(evaluations, 1)
                else:
                    self.assertEqual((phase, status), ("uncertain", "failed"))
                    self.assertGreater(evaluations, 1)
                    for control in ("/goal pause", "/goal resume"):
                        _, phase, status, _ = command_result(control, submitted=False)
                        self.assertIn(phase, ("rejected", "retained_unsent"))
                        self.assertEqual(status, "failed")
                    _, phase, status, answer = command_result("/goal")
                    self.assertEqual((phase, status), ("accepted", "completed"))
                    self.assertIn(condition, answer)
                    _, phase, status, answer = command_result("/goal clear")
                    self.assertEqual((phase, status), ("accepted", "completed"))
                    self.assertIn("Goal cleared", answer)
                    self.assertIn(condition, answer)
                _, phase, status, answer = command_result("/goal")
                self.assertEqual((phase, status), ("accepted", "completed"))
                self.assertIn("No goal set.", answer)
                self.assertEqual(journey.row(
                    "SELECT i.phase,t.status,t.native_thread_id FROM interaction_sources s "
                    "JOIN interaction_instructions i ON i.input_id=s.id "
                    "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') WHERE s.event_id=?",
                    (goal_id,),
                ), [("accepted", "completed", native)] if provider.goal_met else
                    [("uncertain", "failed", native)])
                self.assertEqual(provider.goal_evaluations, evaluations)
                self.assertEqual(provider.calls, calls)

                journey.wait(lambda: any(answer in row.get("preview", "")
                                         for row in browser.get("/api/interaction")["items"]))

            browser.client.cookies.clear()
            blocked = str(uuid.uuid4())
            blocked_command = "/goal Report a denied fixture action." if lifecycle else "/goal"
            response = browser.client.post("/api/interaction/inputs", json={
                "id": blocked, "binding": browser.binding, "reply": destination, "text": blocked_command,
            }, headers=browser.device_headers)
            self.assertEqual(response.status_code, 503, response.text)
            self.assertEqual(journey.row("SELECT phase FROM conversation_inputs WHERE id=?", (blocked,)),
                             [("retained_unsent",)])
            self.assertEqual(journey.row("SELECT count(*) FROM interaction_sources WHERE event_id=?", (blocked,)),
                             [(0,)])
            self.assertEqual(provider.calls, calls)

        def _exact_claude_quote(self, journey, provider, worker_profile, *, web=False):
            import hashlib

            browser, destination = None, None
            numbered_history = web and os.environ.get("FOREGROUND_TEST_CLAUDE_NUMBERED_HISTORY") == "1"
            if web:
                from conversation_cold_entry_http_io import Browser

                browser = Browser(journey)
                self.addCleanup(browser.provider.close)
                self.addCleanup(browser.client.close)
                destination = next(row["destination"]
                                   for row in browser.get("/api/interaction/sessions")["sessions"]
                                   if row["audio_key"] == "100:7")
                provider.paired_human = False
                provider.routed_paired_human = 100

            def send(original, answer, reply):
                provider.original = original
                provider.quote_response = answer
                if browser:
                    ident = provider.human_original = str(uuid.uuid4())
                    browser.text(original, reply=reply, original_id=ident)
                    return ident
                with journey.lock:
                    provider.human_original = str(journey.sequence + 1)
                return str(journey.admit(original, topic=7, reply=reply))

            def finish(ident, original, answer, reply):
                def result():
                    if browser:
                        return next((row for row in browser.get("/api/interaction")["items"]
                                     if row["kind"] == "worker_result" and row["preview"] == answer), None)
                    return next((message for message, payload in journey.messages
                                 if answer in message["text"]
                                 and payload.get("reply_parameters", {}).get("message_id") == int(ident)), None)

                journey.wait(lambda: provider.failure or result(), seconds=25)
                self.assertIsNone(provider.failure)
                journey.idle()
                if browser:
                    _, readback = browser.text(original, reply=reply, original_id=ident)
                    self.assertIs(readback["new_input"], False)
                receipt = journey.row(
                    "SELECT i.phase,t.status,t.native_thread_id,r.id FROM interaction_instructions i "
                    "JOIN interaction_sources s ON s.id=i.input_id "
                    "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') "
                    "JOIN interaction_results r ON r.local_turn=t.id WHERE s.event_id=?",
                    (ident,),
                )
                self.assertEqual(len(receipt), 1)
                phase, status, native, result_id = receipt[0]
                self.assertEqual((phase, status), ("accepted", "completed"))
                item = result()
                if browser:
                    selection = {"source": item["id"], "revision": item["revision"]}
                    return selection, native, selection
                selection = {
                    "source": f"telegram-result:{result_id}",
                    "revision": hashlib.sha256(answer.encode()).hexdigest(),
                }
                return item["message_id"], native, selection

            proposal = ("Fixture v29 keeps the heroic idle and landing clips."
                        if numbered_history else "Use the copper clasp on the selected design.")
            question = "What's your proposal for the clasp?"
            first = send(question, proposal, destination)
            older, native, selection = finish(first, question, proposal, destination)
            if not browser and os.environ.get("FOREGROUND_TEST_CLAUDE_TEXTLESS_TELEGRAM_REPLY") == "1":
                # Force a fresh native scope while keeping the topic and
                # its approved historical exchange bound to the same body.
                provider.session_instructions = "Keep the updated design instructions."
                with sqlite3.connect(journey.root / "state.sqlite") as db:
                    db.execute("UPDATE sessions SET session_prompt=? WHERE thread_id=7",
                               (provider.session_instructions,))
                original = "Sí, mandale."
                answer = "I recovered the copper clasp proposal."
                provider.original = original
                provider.quote_response = answer
                provider.expected_recent_exchange = (question, proposal)
                with journey.lock:
                    provider.human_original = str(journey.sequence + 1)
                pending = str(journey.admit(original, topic=7, message_fields={
                    "reply_to_message": {
                        "message_id": 999999,
                        "from": {"id": 123, "is_bot": True, "first_name": "Fixture"},
                    },
                }))
                _, replacement, _ = finish(pending, original, answer, destination)
                self.assertNotEqual(replacement, native)
                self.assertEqual(len(provider.calls), 2)
                return
            arrived, release, cancelled = Event(), Event(), Event()
            provider.quote_answer_gate = (arrived, release, cancelled)
            newer_original = "Propose a finish for the stand."
            newer_answer = "Use a blue finish on the stand."
            current = send(newer_original, newer_answer, destination)
            approval = "Sí, adelante."
            approval_answer = "I'll proceed with the copper clasp."
            unavailable_quote = os.environ.get("FOREGROUND_TEST_CLAUDE_UNAVAILABLE_QUOTE") == "1"
            interrupt = os.environ.get("FOREGROUND_TEST_CLAUDE_WEB_QUOTE_INTERRUPT" if browser else
                                       "FOREGROUND_TEST_CLAUDE_TELEGRAM_QUOTE_INTERRUPT") == "1"
            try:
                self.assertTrue(arrived.wait(20), provider.failure)
                pending = send(approval, approval_answer, older)

                def queued():
                    return journey.row(
                        "SELECT i.phase,json_extract(i.doc,'$.local_turn') FROM interaction_instructions i "
                        "JOIN interaction_sources s ON s.id=i.input_id WHERE s.event_id=?",
                        (pending,),
                    ) == [("queued", None)]

                journey.wait(queued, seconds=10)
                self.assertEqual(len(provider.calls), 2)
                if unavailable_quote:
                    # Keep the selected receipt while making its answer
                    # ineligible for recovery before queued dispatch.
                    with sqlite3.connect(journey.root / "state.sqlite") as db:
                        if browser:
                            self.assertTrue(older["source"].startswith("delivery:"))
                            changed = db.execute(
                                "UPDATE interaction_deliveries SET doc=json_set(doc,'$.body',?) WHERE id=?",
                                ("x" * (13 * 1024), older["source"].removeprefix("delivery:")),
                            )
                        else:
                            changed = db.execute(
                                "UPDATE interaction_results SET body=? WHERE body=?",
                                ("x" * (13 * 1024), proposal),
                            )
                        self.assertEqual(changed.rowcount, 1)
                provider.expected_quote = {**selection, "assistant": proposal}
                provider.quote_answer_gate = None
                if interrupt:
                    provider.interrupted_quote_original = newer_original
                    if browser:
                        interrupt_id, stopped = browser.text("/interrupt", reply=destination)
                        self.assertEqual(stopped["phase"], "interruption")
                        self.assertEqual(stopped["routing"]["phase"], "requested")
                    else:
                        interrupt_id = journey.admit("/interrupt", topic=7)

                    def interrupted():
                        return journey.row(
                            "SELECT i.phase,t.status FROM interaction_sources s "
                            "JOIN interaction_instructions i ON i.input_id=s.id "
                            "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') WHERE s.event_id=?",
                            (current,),
                        ) == [("cancelled", "failed")]

                    journey.wait(interrupted, seconds=20)
                    self.assertEqual(journey.row(
                        "SELECT json_extract(i.doc,'$.native_interrupt_confirmed') "
                        "FROM interaction_sources s JOIN interaction_instructions i "
                        "ON i.input_id=s.id WHERE s.event_id=?", (current,),
                    ), [(1,)])
                    cancelled.set()
            finally:
                release.set()
            if not interrupt:
                _, later_native, _ = finish(current, newer_original, newer_answer, destination)
                self.assertEqual(later_native, native)
            if unavailable_quote:
                def retained():
                    return journey.row(
                        "SELECT i.phase,json_extract(i.doc,'$.context_unavailable'),t.native_thread_id "
                        "FROM interaction_instructions i JOIN interaction_sources s ON s.id=i.input_id "
                        "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') WHERE s.event_id=?",
                        (pending,),
                    ) == [("retained_unsent", 1, None)]

                journey.wait(retained, seconds=15)
                if browser:
                    _, replay = browser.text(approval, reply=older, original_id=pending)
                    self.assertIs(replay["new_input"], False)
                    self.assertIs(replay["routing"]["context_unavailable"], True)
                else:
                    journey.wait(lambda: any(
                        "Claude Code could not recover the earlier context" in message["text"]
                        and payload.get("reply_parameters", {}).get("message_id") == int(pending)
                        for message, payload in journey.messages
                    ), seconds=15)
                self.assertEqual(len(provider.calls), 2)
                return
            _, reply_native, _ = finish(pending, approval, approval_answer, older)
            self.assertEqual(len(provider.calls), 3)
            if interrupt:
                self.assertEqual(reply_native, native)
                self.assertEqual(journey.row("SELECT count(*) FROM interaction_results"), [(2,)])
                if browser:
                    _, replay = browser.text("/interrupt", reply=destination, original_id=interrupt_id)
                    self.assertIs(replay["new_input"], False)
                    self.assertFalse(any(row.get("preview") == newer_answer
                                         for row in browser.get("/api/interaction")["items"]))
                else:
                    self.assertFalse(journey.has(newer_answer, 7))
            else:
                self.assertEqual(reply_native, native)

            missing_resume = os.environ.get("FOREGROUND_TEST_CLAUDE_MISSING_RESUME") == "1"
            if numbered_history or missing_resume:
                if missing_resume:
                    fixture_home = Path(json.loads(worker_profile.read_text())["home"])
                    transcripts = list((fixture_home / "projects").rglob(f"{native}.jsonl"))
                    self.assertEqual(len(transcripts), 1)
                    transcripts[0].rename(fixture_home / "retained-predecessor.jsonl")
                    topic, cwd = journey.row("SELECT id,cwd FROM sessions WHERE thread_id=7")[0]
                    adopted = journey.read("topics", "workspace", "adopt", "7", str(topic))["result"]
                    self.assertTrue(adopted["folder_ready"])
                    checkpoint = Path(adopted["conversation_folder"]) / "CONTINUITY.md"
                    checkpoint.touch(mode=0o600, exist_ok=False)
                    provider.expected_project_checkpoint = "Use the synthetic design at revision two."
                    checkpoint.write_text(provider.expected_project_checkpoint)
                    self.assertEqual(journey.row("SELECT cwd FROM sessions WHERE id=?", (topic,)), [(cwd,)])
                if numbered_history:
                    first_turn, = journey.row(
                        "SELECT json_extract(i.doc,'$.local_turn') FROM interaction_instructions i "
                        "JOIN interaction_sources s ON s.id=i.input_id WHERE s.event_id=?", (first,)
                    )[0]
                    provider.expected_quote = {
                        "matchedReference": "Fixture v29",
                        "exchanges": [{"turn": first_turn, "human": question, "assistant": proposal,
                                       "harness": "claude", "nativeThread": native}],
                    }
                    recovered_quote = destination
                    original = "Contame qué clips dejamos listos en Fixture v29 y qué quedó pendiente."
                else:
                    recovered_quote, recovered_selection = older, selection
                    if browser:
                        current = next(row for row in browser.get("/api/interaction")["items"]
                                       if row["id"] == older["source"])
                        recovered_quote = {"source": current["id"], "revision": current["revision"]}
                        recovered_selection = recovered_quote
                    provider.expected_quote = {**recovered_selection, "assistant": proposal}
                    original = "Sí, retomá esa propuesta."
                answer = "I recovered the copper clasp proposal."
                try:
                    _, replacement, _ = finish(send(original, answer, recovered_quote),
                                               original, answer, recovered_quote)
                finally:
                    if missing_resume:
                        del provider.expected_project_checkpoint
                self.assertEqual(replacement == native, not missing_resume)
                self.assertEqual(len(provider.calls), 4)

                if numbered_history and os.environ.get("FOREGROUND_TEST_CLAUDE_TOPIC_LOOKUP") == "1":
                    fixture_home = Path(json.loads(worker_profile.read_text())["home"])
                    predecessor = list((fixture_home / "projects").rglob(f"{replacement}.jsonl"))
                    self.assertEqual(len(predecessor), 1)
                    predecessor[0].rename(fixture_home / "retained-lookup-predecessor.jsonl")
                    provider.expected_quote = None
                    provider.topic_history_lookup = {
                        "predecessor": replacement, "query": "landing heroic clips", "expected": proposal,
                        "exchange": {"turn": first_turn, "human": question, "assistant": proposal,
                                     "harness": "claude", "nativeThread": native},
                    }
                    try:
                        original = "What did we leave ready for the fixture?"
                        answer = "We kept the heroic idle and landing clips."
                        _, lookup_session, _ = finish(send(original, answer, destination),
                                                      original, answer, destination)
                        self.assertNotEqual(lookup_session, replacement)
                        self.assertEqual(len(provider.calls), 6)
                    finally:
                        del provider.topic_history_lookup

        def _claude_harness_switch(self, journey, provider):
            from conversation_cold_entry_http_io import Browser

            codex_target = 'name="Alpha"\ntopic_id=7'
            claude_target = 'name="Alpha"\nharness="claude"\ntopic_id=7'
            session, codex, cwd = journey.row(
                "SELECT id,codex_thread_id,cwd FROM sessions WHERE thread_id=7")[0]
            generation, = journey.row(
                "SELECT generation FROM conversation_entry_generations WHERE session_id=?", (session,))[0]
            adopted = journey.read("topics", "workspace", "adopt", "7", str(session))["result"]
            self.assertTrue(adopted["folder_ready"])
            checkpoint = Path(adopted["conversation_folder"]) / "CONTINUITY.md"
            checkpoint.touch(mode=0o600, exist_ok=False)
            checkpoint.write_text("The selected fixture workspace contains the approved clasp.")

            def browser():
                web = Browser(journey)
                self.addCleanup(web.provider.close)
                self.addCleanup(web.client.close)
                return web

            def switch(before, after):
                journey.idle()
                journey.stop()
                config = journey.config.read_text()
                self.assertEqual(config.count(before), 1)
                journey.config.write_text(config.replace(before, after, 1))
                journey.start()
                journey.wait_control_socket(journey.socket)
                self.assertEqual(journey.row(
                    "SELECT id,codex_thread_id,cwd FROM sessions WHERE thread_id=7"), [(session, codex, cwd)])
                self.assertEqual(journey.row(
                    "SELECT generation FROM conversation_entry_generations WHERE session_id=?", (session,)),
                    [(generation,)])
                return browser()

            def destination(web):
                return next(row["destination"] for row in web.get("/api/interaction/sessions")["sessions"]
                            if row["audio_key"] == "100:7")

            def reply(web, answer):
                return next(({"source": row["id"], "revision": row["revision"]}
                             for row in web.get("/api/interaction")["items"]
                             if row["kind"] == "worker_result" and row["preview"] == answer), None)

            def selection(web, answer):
                journey.wait(lambda: provider.failure or reply(web, answer), seconds=25)
                self.assertIsNone(provider.failure)
                return reply(web, answer)

            web = browser()
            previous = "The clasp selected in Codex is copper."
            codex_input, _ = web.text("Which clasp did we choose?", reply=destination(web))
            journey.answer_worker(7, previous, item="codex-before-claude")
            reference = selection(web, previous)

            web = switch(codex_target, claude_target)
            provider.paired_human = False
            provider.routed_paired_human = 100
            provider.original = "Sí, seguí con esa propuesta."
            provider.quote_response = "Claude confirmed the copper clasp for the fixture."
            provider.expected_quote = {**reference, "assistant": previous}
            provider.human_original = str(uuid.uuid4())
            claude_input, _ = web.text(provider.original, reply=reference, original_id=provider.human_original)
            selection(web, provider.quote_response)

            web = switch(claude_target, codex_target)
            next_original = "Continue this work in the selected topic."
            previous_packets = len(journey.worker_packets[codex])
            successor, _ = web.text(next_original, reply=destination(web))
            journey.wait(lambda: len(journey.worker_packets[codex]) == previous_packets + 1)
            packet = journey.worker_packets[codex][-1]
            self.assertEqual(packet["threadId"], codex)
            encoded = json.dumps(packet, ensure_ascii=False)
            self.assertIn(provider.quote_response, encoded)
            self.assertIn(checkpoint.read_text(), encoded)
            self.assertIn(next_original, encoded)
            final = "Codex resumed with the selected checkpoint."
            journey.answer_worker(7, final, item="codex-after-claude")
            selection(web, final)

            web = switch(codex_target, claude_target)
            provider.expected_native_context = provider.quote_response
            provider.expected_quote = None
            provider.original = "Resume the design in the original Claude session."
            provider.quote_response = "Claude resumed the same design session."
            provider.human_original = str(uuid.uuid4())
            resumed, _ = web.text(provider.original, reply=destination(web), original_id=provider.human_original)
            selection(web, provider.quote_response)

            turns = journey.row(
                "SELECT s.event_id,t.execution_harness,t.native_thread_id,t.status "
                "FROM interaction_sources s JOIN interaction_instructions i ON i.input_id=s.id "
                "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') "
                "WHERE t.session_id=? AND s.event_id IN (?,?,?,?) ORDER BY t.id",
                (session, codex_input, claude_input, successor, resumed))
            self.assertEqual([row[:2] for row in turns], [
                (codex_input, "codex"), (claude_input, "claude"), (successor, "codex"), (resumed, "claude"),
            ])
            self.assertEqual([row[3] for row in turns], ["completed"] * 4)
            self.assertEqual((turns[0][2], turns[2][2]), (codex, codex))
            self.assertNotEqual(turns[1][2], codex)
            self.assertEqual(turns[1][2], turns[3][2])
            self.assertEqual(len(provider.exposures), 2)
            self.assertEqual(len(set(provider.exposures)), 2)

        def _conversation_attachments(self, journey, provider):
            import base64
            import hashlib
            from urllib.parse import quote

            from conversation_cold_entry_http_io import Browser

            browser = Browser(journey, companion=True, companion_workspace=True)
            self.addCleanup(browser.provider.close)
            self.addCleanup(browser.client.close)
            destination = next(row["destination"]
                               for row in browser.get("/api/interaction/sessions")["sessions"]
                               if row["audio_key"] == "100:7")
            image = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
            pdf = b"%PDF-1.4\noriginal document fixture\n%%EOF"

            def upload(name, mime, data):
                reference = {"file_id": str(uuid.uuid4()), "name": name, "mime": mime,
                             "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                response = browser.client.post("/api/interaction/files", content=data, headers={
                    **browser.headers, "content-type": "application/octet-stream",
                    "x-file-reference": quote(json.dumps(reference), safe=""),
                })
                self.assertEqual(response.status_code, 200, response.text)
                return reference

            image_ref = upload("fixture-image.png", "image/png", image)
            pdf_ref = upload("fixture-document.pdf", "application/pdf", pdf)
            provider.paired_human = False
            provider.routed_paired_human = 100
            provider.attachment = {"blocks": [
                ("image", "image/png", base64.b64encode(image).decode()),
                ("document", "application/pdf", base64.b64encode(pdf).decode()),
            ]}

            def state(original):
                return journey.row(
                    "SELECT i.phase,t.status,t.native_thread_id FROM interaction_instructions i "
                    "JOIN interaction_sources s ON s.id=i.input_id "
                    "LEFT JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') WHERE s.event_id=?",
                    (original,),
                )

            native_sessions = set()
            for caption in ("Compare both retained originals.", ""):
                provider.original = caption
                provider.human_original = str(uuid.uuid4())
                ident, _ = browser.text(caption, reply=destination,
                                        original_id=provider.human_original, files=[image_ref, pdf_ref])
                journey.wait(lambda: provider.failure or any(
                    status in {"completed", "failed"} for _, status, _ in state(ident)
                ), seconds=25)
                self.assertIsNone(provider.failure)
                [(phase, status, native)] = state(ident)
                self.assertEqual((phase, status), ("accepted", "completed"))
                self.assertTrue(native)
                native_sessions.add(native)
                for index, data in enumerate((image, pdf)):
                    saved = browser.client.get(f"/api/interaction/inputs/{ident}/files/{index}",
                                               headers=browser.headers)
                    self.assertEqual(saved.status_code, 200)
                    self.assertEqual(saved.content, data)
                journey.idle()
            expected = len(set(provider.exposures))
            self.assertEqual(expected, 2)
            self.assertEqual(len(native_sessions), 1)
            journey.wait(lambda: sum(
                ANSWER in item.get("preview", "") for item in browser.get("/api/interaction")["items"]
            ) == expected, seconds=20)

            calls = list(provider.calls)
            browser.client.cookies.clear()
            blocked = str(uuid.uuid4())
            response = browser.client.post("/api/interaction/inputs", json={
                "id": blocked, "binding": browser.binding, "reply": destination,
                "text": "Companion attachment may not enter the paired Claude session.",
                "files": [image_ref, pdf_ref],
            }, headers=browser.device_headers)
            self.assertEqual(response.status_code, 200, response.text)
            journey.wait(lambda: [row[:2] for row in state(blocked)] == [("retained_unsent", "failed")], seconds=20)
            journey.idle()
            self.assertEqual(provider.calls, calls)
            self.assertEqual(len(set(provider.exposures)), expected)

        def _claude_topic_voice(self, journey, provider):
            import hashlib
            from conversation_voice_http_io import audio

            provider.original = "Prepare the design context before the voice input."
            with journey.lock:
                provider.human_original = str(journey.sequence + 1)
            first = journey.admit(provider.original, topic=7)
            journey.wait(lambda: provider.failure or any(
                ANSWER in message["text"] and payload.get("reply_parameters", {}).get("message_id") == first
                for message, payload in journey.messages), seconds=25)
            self.assertIsNone(provider.failure)
            journey.idle()
            provider.previous_original = provider.original
            provider.previous_session = journey.row(
                "SELECT native_thread_id FROM turns WHERE execution_harness='claude' "
                "AND status='completed' ORDER BY id DESC LIMIT 1"
            )[0][0]
            provider.original = "Read the synthetic voice note."
            provider.followup_answer = "The same native session got the voice transcript."
            clip = audio()
            provider.topic_voice_digest = hashlib.sha256(clip).hexdigest()
            journey.media_files = {"topic-voice.wav": clip}
            with journey.lock:
                provider.human_original = str(journey.sequence + 1)
            update = journey.admit(topic=7, message_fields={
                "voice": {"file_id": "topic-voice.wav", "mime_type": "audio/wav"}
            })
            journey.wait(lambda: provider.failure or any(
                provider.followup_answer in message["text"]
                and payload.get("reply_parameters", {}).get("message_id") == update
                for message, payload in journey.messages), seconds=25)
            self.assertIsNone(provider.failure)
            rows = journey.row(
                "SELECT s.doc,i.phase,t.execution_harness,t.native_thread_id,v.phase "
                "FROM interaction_sources s JOIN interaction_instructions i ON i.input_id=s.id "
                "JOIN interaction_voice_inputs v ON v.update_id=s.update_id "
                "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') WHERE s.event_id=?",
                (str(update),),
            )
            self.assertEqual(len(rows), 1)
            source, phase, harness, native, transcript_phase = rows[0]
            self.assertEqual((phase, harness, native, transcript_phase),
                             ("accepted", "claude", provider.previous_session, "committed"))
            source = json.loads(source)
            self.assertEqual(source["text"], provider.original)
            self.assertEqual(source["transcription"]["audio_sha256"], provider.topic_voice_digest)
            self.assertEqual(source["transcription"]["telegram_file_id"], "topic-voice.wav")
            self.assertEqual(len(set(provider.exposures)), 2)
            journey.idle()

            from conversation_cold_entry_http_io import Browser
            browser = Browser(journey)
            self.addCleanup(browser.provider.close)
            self.addCleanup(browser.client.close)
            destination = next(row["destination"]
                               for row in browser.get("/api/interaction/sessions")["sessions"]
                               if row["audio_key"] == "100:7")
            provider.topic_voice_digest = None
            provider.paired_human = False
            provider.routed_paired_human = 100
            provider.human_original = capture = str(uuid.uuid4())
            provider.followup_answer = "The same Claude topic answered the Conversation voice input."
            clip = audio(frequency=610)
            digest = hashlib.sha256(clip).hexdigest()
            provider.conversation_voice_digest = digest
            headers = {**browser.headers, "content-type": "audio/wav",
                       "x-input-id": capture, "x-input-binding": browser.binding,
                       "x-audio-sha256": digest, "x-reply-source": destination["source"],
                       "x-reply-revision": destination["revision"]}
            response = browser.client.post("/api/interaction/voice", content=clip, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            journey.wait(lambda: provider.failure or any(
                provider.followup_answer in item.get("preview", "")
                for item in browser.get("/api/interaction")["items"]), seconds=25)
            self.assertIsNone(provider.failure)
            source, native = journey.row(
                "SELECT s.doc,t.native_thread_id FROM interaction_sources s "
                "JOIN interaction_instructions i ON i.input_id=s.id "
                "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') "
                "WHERE s.event_id=? AND i.phase='accepted' AND t.status='completed'",
                (capture,),
            )[0]
            self.assertEqual(native, provider.previous_session)
            self.assertEqual(json.loads(source)["transcription"]["audio_sha256"], digest)
            self.assertEqual(len(set(provider.exposures)), 3)

        def _claude_output_artifacts(self, journey, provider, profile):
            from email import policy
            from email.parser import BytesParser
            from conversation_cold_entry_http_io import Browser

            selected = json.loads(profile.read_text())
            selected["hostTools"] = ["Write"]
            profile.write_text(json.dumps(selected))
            provider.host_tools = ["Write"]
            uploads = []

            def upload(method, headers, raw):
                message = BytesParser(policy=policy.default).parsebytes(
                    ("Content-Type: " + headers["Content-Type"] + "\r\n\r\n").encode() + raw
                )
                fields = {part.get_param("name", header="content-disposition"): part
                          for part in message.iter_parts()}
                self.assertEqual(method, "sendDocument")
                self.assertEqual(fields["chat_id"].get_payload(), "100")
                self.assertEqual(fields["message_thread_id"].get_payload(), "7")
                document = fields["document"]
                uploads.append((document.get_filename(), document.get_payload(decode=True)))
                return {"ok": True, "result": {"message_id": 900 + len(uploads),
                                                "chat": {"id": 100, "type": "private"},
                                                "message_thread_id": 7}}

            journey.multipart_reply = upload
            browser = Browser(journey)
            self.addCleanup(browser.provider.close)
            self.addCleanup(browser.client.close)
            destination = next(row["destination"]
                               for row in browser.get("/api/interaction/sessions")["sessions"]
                               if row["audio_key"] == "100:7")
            expected = []
            for surface in ("Telegram", "Conversation"):
                provider.original = f"Create the {surface} fixture deliverable."
                name, content = f"{surface}.txt", f"Exact {surface} file bytes.\n"
                provider.output_artifact = {"name": name, "text": content}
                provider.calls.clear()
                provider.paired_human = surface == "Telegram"
                provider.routed_paired_human = None if surface == "Telegram" else 100
                if surface == "Telegram":
                    with journey.lock:
                        provider.human_original = str(journey.sequence + 1)
                    journey.admit(provider.original, topic=7)
                else:
                    provider.human_original = str(uuid.uuid4())
                    browser.text(provider.original, reply=destination, original_id=provider.human_original)
                expected.append((name, content.encode()))
                journey.wait(lambda: provider.failure or len(uploads) == len(expected), seconds=25)
                self.assertIsNone(provider.failure, surface)
                self.assertEqual(uploads, expected)
                journey.idle()
            rows = journey.row(
                "SELECT a.name,a.native_thread,a.native_turn,r.id FROM interaction_artifacts a "
                "JOIN interaction_results r ON r.local_turn=a.source_local AND r.native_thread=a.native_thread "
                "AND r.native_turn=a.native_turn AND r.item_id=a.native_item ORDER BY a.rowid"
            )
            self.assertEqual([row[0] for row in rows], [name for name, _ in expected])
            self.assertEqual({row[1] for row in rows}, {provider.artifact_native_session})
            self.assertEqual(len({row[2] for row in rows}), 2)
            entries = browser.get("/api/interaction/artifacts")["items"]
            selected = next(entry for entry in entries if entry["name"] == "Conversation.txt")
            response = browser.client.get("/api/interaction/artifacts/" + selected["id"],
                                          headers=browser.headers)
            self.assertEqual((response.status_code, response.content), (200, expected[-1][1]))

        def _telegram_attachments(self, journey, provider):
            import base64
            import hashlib

            image = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
            pdf = b"%PDF-1.4\noriginal document fixture\n%%EOF"
            journey.media_files = {"fixture-image.png": image, "fixture-document.pdf": pdf}
            photo = {"photo": [{"file_id": "fixture-image.png", "width": 1, "height": 1}]}
            forwarded = journey.admit(topic=7, message_fields={
                **photo, "forward_origin": {"type": "hidden_user", "date": 1740000000, "sender_user_name": "Fixture"},
            })
            journey.wait(lambda: journey.has("Forwarded messages aren't supported here.", 7))
            self.assertEqual(journey.row("SELECT count(*) FROM interaction_sources WHERE event_id=?",
                                         (str(forwarded),)), [(0,)])
            document = {"document": {"file_id": "fixture-document.pdf", "file_name": "fixture-document.pdf",
                                     "mime_type": "application/pdf", "file_size": len(pdf)}}
            cases = [
                (caption, photo, "image", "image/png", image)
                for caption in ("  Please inspect this photo.  ", "", "/inspect@otherbot once you see the photo")
            ] + [("Inspect the original PDF.", document, "document", "application/pdf", pdf)]
            for caption, fields, kind, mime, data in cases:
                provider.original = caption or "Gateway attached these files"
                provider.attachment = {"caption": caption, "blocks": [
                    (kind, mime, base64.b64encode(data).decode()),
                ]}
                with journey.lock:
                    provider.human_original = str(journey.sequence + 1)
                update = journey.admit(topic=7, message_fields={**fields, **({"caption": caption} if caption else {})})
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
                expected = hashlib.sha256(data).hexdigest()
                self.assertEqual(source["telegram_files"][0]["sha256"], expected)
                self.assertEqual((journey.root / "state.sqlite.files" / expected).read_bytes(), data)
            self.assertEqual(len(set(provider.exposures)), len(cases))

        def _telegram_album(self, journey, provider):
            import base64
            import hashlib

            image = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
            images = {f"album-{index}.png": image + bytes([index]) for index in range(3)}
            journey.media_files = images
            delivered = {}

            def observe_poll(batch):
                for update in batch:
                    delivered[update["update_id"]] = update

            journey.before_poll_reply = observe_poll

            def original(*, files, caption):
                provider.original = caption
                provider.attachment = {"caption": caption, "blocks": [
                    ("image", "image/png", base64.b64encode(images[name]).decode())
                    for name in files
                ]}
                with journey.lock:
                    provider.human_original = str(journey.sequence + 1)

            def admit(name, caption):
                return journey.admit(topic=7, message_fields={
                    "photo": [{"file_id": name, "width": 1, "height": 1}],
                    "media_group_id": "shared-fixture-album",
                    "caption": caption,
                })

            def wait_reply(update):
                journey.wait(lambda: provider.failure or any(
                    ANSWER in msg["text"] and envelope.get("reply_parameters", {}).get("message_id") == update
                    for msg, envelope in journey.messages), seconds=25)
                self.assertIsNone(provider.failure)
                journey.idle()

            original(files=["album-0.png", "album-1.png"], caption="First caption.\n\nSecond caption.")
            first = admit("album-0.png", "First caption.")
            second = admit("album-1.png", "Second caption.")
            wait_reply(first)
            [(raw, native)] = journey.row(
                "SELECT s.doc,t.native_thread_id FROM interaction_sources s "
                "JOIN interaction_instructions i ON i.input_id=s.id "
                "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') WHERE s.event_id=?",
                (str(first),),
            )
            source = json.loads(raw)
            self.assertEqual(source["telegram_album_members"], [second])
            self.assertEqual([item["sha256"] for item in source["telegram_files"]], [
                hashlib.sha256(images[name]).hexdigest()
                for name in ("album-0.png", "album-1.png")
            ])
            self.assertEqual(journey.row(
                "SELECT status FROM incoming_updates WHERE update_id IN (?,?) ORDER BY update_id",
                (first, second)), [("handled",), ("handled",)])
            self.assertEqual(len(provider.exposures), 1)
            # The mock Bot API returns one update per poll. An exact old
            # member delivered again is deduplicated before native dispatch.
            with journey.lock:
                journey.updates.append(delivered[second])
            original(files=["album-2.png"], caption="Late caption.")
            late = admit("album-2.png", "Late caption.")
            wait_reply(late)
            self.assertEqual(journey.row(
                "SELECT t.native_thread_id FROM interaction_sources s "
                "JOIN interaction_instructions i ON i.input_id=s.id "
                "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') WHERE s.event_id IN (?,?)",
                (str(second), str(late)),
            ), [(native,)])
            self.assertEqual(len(provider.exposures), 2)

        def _telegram_steer(self, journey, provider, profile):
            selected = json.loads(profile.read_text())
            selected["hostTools"] = ["Bash"]
            profile.write_text(json.dumps(selected))
            started = journey.root / "steer-tool-started"
            release = journey.root / "steer-tool-release"
            provider.host_tools = ["Bash"]
            journey.allow_local_dependencies = True
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
                    "json_extract(i.doc,'$.native_turn'),json_extract(i.doc,'$.native_thread') "
                    "FROM interaction_sources s "
                    "JOIN interaction_instructions i ON i.input_id=s.id WHERE s.event_id=?",
                    (str(update),),
                )

            journey.wait(lambda: provider.failure or started.exists() or (
                state(root) and state(root)[0][1] in ("retained_unsent", "rejected", "uncertain", "accepted")
            ), seconds=25)
            self.assertIsNone(provider.failure)
            self.assertTrue(started.exists(), (state(root), provider.calls, provider.exposures))

            def original_receipt():
                return journey.row(
                    "SELECT i.phase,json_extract(i.doc,'$.native_input_accepted'),t.status "
                    "FROM interaction_sources s JOIN interaction_instructions i ON i.input_id=s.id "
                    "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') WHERE s.event_id=?",
                    (str(root),),
                )

            journey.wait(lambda: original_receipt() == [("submitting", 1, "running")], seconds=5)
            self.assertEqual(journey.row("SELECT count(*) FROM interaction_results"), [(0,)])
            from contextlib import closing
            from dashboard.session_view import read_portable
            session, = journey.row("SELECT id FROM sessions WHERE chat_id=100 AND thread_id=7")[0]
            with closing(sqlite3.connect(f"file:{journey.root / 'state.sqlite'}?mode=ro", uri=True)) as db:
                pending = read_portable(db, session, 100, "claude")["pending_items"]
            self.assertEqual([(row["text"], row["portable_phase"]) for row in pending
                              if row.get("input_id") == f"telegram:{root}"],
                             [(provider.original, "accepted")])
            followup = journey.admit(provider.steer_fixture["text"], topic=7)
            source_id = f"telegram:{followup}"

            def assert_delivery(expected):
                telegram = journey.read("input", "telegram-list", "0", "before")["result"]
                matches = [row for row in telegram["items"] if row["id"] == source_id]
                self.assertEqual([(row["preview"], row["portable_phase"]) for row in matches],
                                 [(provider.steer_fixture["text"], expected)])
                trace = journey.read("input", "trace", source_id)["result"]
                self.assertEqual(trace["text"], provider.steer_fixture["text"])
                with closing(sqlite3.connect(f"file:{journey.root / 'state.sqlite'}?mode=ro", uri=True)) as db:
                    pending = read_portable(db, session, 100, "claude")["pending_items"]
                self.assertEqual([(row["text"], row["portable_phase"]) for row in pending
                                  if row.get("input_id") == source_id],
                                 [(provider.steer_fixture["text"], expected)])
                self.assertEqual(journey.row("SELECT count(*) FROM interaction_results"), [(0,)])

            conversation = str(uuid.uuid4())
            try:
                journey.wait(lambda: provider.failure or (
                    state(followup) and state(followup)[0][1] == "steering"), seconds=6)
                assert_delivery("steering")
                page = journey.read("presentation", "list", "0", "0")["result"]
                original = {"binding": page["binding"], "id": conversation,
                            "text": "#Alpha " + provider.steer_fixture["conversation_text"]}
                self.assertTrue(journey.read("input", "submit-human", json.dumps(original))["result"]["new_input"])
                journey.wait(lambda: provider.failure or (
                    state(conversation) and state(conversation)[0][1] == "steering"), seconds=6)
                self.assertEqual(state(followup)[0][2], state(root)[0][2])
                self.assertEqual(state(conversation)[0][2], state(root)[0][2])
                provider.steer_fixture["parent"] = state(followup)[0][0]
                provider.steer_fixture["assert_delivery"] = assert_delivery
            finally:
                release.touch()
            journey.wait(lambda: provider.failure or journey.has(ANSWER, 7), seconds=25)
            self.assertIsNone(provider.failure)
            original, followup = state(root)[0], state(followup)[0]
            self.assertEqual(original[1:], followup[1:])
            self.assertEqual(original[1:], state(conversation)[0][1:])
            self.assertEqual(original[1], "accepted")
            self.assertEqual(original[4], journey.row(
                "SELECT native_thread_id FROM turns WHERE id=?", (original[2],))[0][0])
            self.assertTrue(original[4])
            self.assertEqual(provider.calls, [original[0]] * 4)
            self.assertEqual(journey.row("SELECT parent_instruction FROM interaction_session_requests"),
                             [(followup[0],)])
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
                # Admission precedes the terminal result. Remove the transcript
                # only after the resumed worker has finished writing it.
                journey.wait(lambda: journey.row(
                    "SELECT t.status FROM turns t JOIN interaction_instructions i "
                    "ON t.id=json_extract(i.doc,'$.local_turn') WHERE i.id=?",
                    (instruction,),
                ) == [("completed",)] and journey.has("I retained the first turn.", 7))
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
                def recovery():
                    return journey.row(
                        "SELECT i.phase,t.status,t.native_thread_id IS NOT NULL "
                        "FROM interaction_sources s JOIN interaction_instructions i ON i.input_id=s.id "
                        "LEFT JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') WHERE s.event_id=?",
                        (str(recovery_update),),
                    )

                journey.wait(lambda: provider.failure or recovery() and
                             recovery()[0][0] in ("accepted", "retained_unsent", "rejected", "uncertain")
                             and recovery()[0][1] != "running", seconds=35)
                self.assertIsNone(provider.failure)
                self.assertEqual(recovery(), [("accepted", "completed", 1)])
                journey.wait(lambda: journey.has("I recovered the retained design context.", 7))
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
            journey.wait(lambda: provider.failure or len(provider.calls) == 6, seconds=25)
            self.assertIsNone(provider.failure)
            journey.wait(lambda: journey.row(
                "SELECT i.phase FROM interaction_session_requests r "
                "JOIN interaction_instructions i ON i.id=r.target_instruction "
                "JOIN sessions s ON s.id=i.session_id WHERE s.thread_id=1") == [("accepted",)])
            self.assertEqual(journey.row("SELECT count(*) FROM interaction_session_requests"), [(1,)])
            if os.environ.get("FOREGROUND_TEST_TELEGRAM_DEPENDENCY_RETURN") != "1":
                return

            def source_execution():
                return journey.row(
                    "SELECT t.native_thread_id,t.execution_native_scope FROM interaction_sources s "
                    "JOIN interaction_instructions i ON i.input_id=s.id "
                    "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') "
                    "WHERE s.event_id=? AND t.status='completed' AND i.phase='accepted'",
                    (provider.human_original,),
                )

            journey.wait(source_execution)
            native, scope = source_execution()[0]
            result = "The general conversation verified the synthetic design summary."
            expected_return = {
                "text": result, "native": native, "scope": scope, "parent_prompt": provider.original,
            }
            recover = os.environ.get("FOREGROUND_TEST_TELEGRAM_DEPENDENCY_RECEIVE") == "1"
            provider.test_session_request = False
            provider.calls.clear()
            if recover:
                # Simulate loss after canonical result storage and before return
                # admission. Only the fixture's staging transaction is denied.
                with sqlite3.connect(journey.root / "state.sqlite") as db:
                    db.execute("""CREATE TRIGGER fixture_deny_initial_return
                        BEFORE UPDATE OF phase ON interaction_session_requests
                        WHEN NEW.phase='returned'
                        BEGIN SELECT RAISE(ABORT,'synthetic crash before return commit'); END""")
                journey.answer_worker(1, result)
                retained = """SELECT r.id,d.result_id FROM interaction_session_requests r
                    JOIN interaction_deliveries d ON d.request_id=r.target_instruction
                    JOIN interaction_instructions i ON i.id=r.target_instruction
                    JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn')
                    WHERE r.phase='requested' AND t.status='completed'
                      AND json_extract(d.doc,'$.completed')=1"""
                journey.wait(lambda: journey.row(retained), seconds=20)
                request_id, result_id = journey.row(retained)[0]
                helper_turns = journey.native_turns
                with sqlite3.connect(journey.root / "state.sqlite") as db:
                    db.execute("DROP TRIGGER fixture_deny_initial_return")
                provider.recover_dependency = {**expected_return, "request_id": request_id}
                provider.original = "Recover the retained answer for this synthetic design."
                provider.human_original = str(journey.sequence + 1)
                journey.admit(provider.original, topic=7)
            else:
                provider.paired_human = False
                progress = "The general conversation checked one requirement and left the rest open."
                provider.returned_dependency = {**expected_return, "text": progress, "progress": True}
                provider.original = progress
                journey.answer_worker(1, progress, item="partial-dependency", finish=False, complete=False)
                journey.wait(lambda: provider.failure or journey.row(
                    "SELECT i.phase,t.status,r.phase,json_extract(r.doc,'$.return_instruction') "
                    "FROM interaction_session_authors a JOIN interaction_instructions i ON i.input_id=a.input_id "
                    "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') "
                    "JOIN interaction_session_requests r ON r.id=json_extract(a.doc,'$.local_request') "
                    "WHERE json_extract(a.doc,'$.dependency_status')='progress'"
                ) == [("accepted", "completed", "requested", None)], seconds=30)
                self.assertIsNone(provider.failure)
                self.assertEqual(len(provider.calls), 3)
                self.assertEqual(len(set(provider.calls)), 1)
                provider.calls.clear()
                provider.returned_dependency = expected_return
                provider.original = result
                journey.answer_worker(1, result)
            journey.wait(lambda: provider.failure or journey.row(
                "SELECT i.phase,t.status FROM interaction_session_requests r "
                "JOIN interaction_instructions i ON i.id=json_extract(r.doc,'$.return_instruction') "
                "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') "
                "WHERE r.phase='returned'"
            ) == [("accepted", "completed")], seconds=30)
            self.assertIsNone(provider.failure)
            returned = journey.row(
                "SELECT json_extract(doc,'$.return_instruction') FROM interaction_session_requests"
            )[0][0]
            self.assertEqual(provider.calls, [returned] * 3)
            self.assertEqual(journey.row("SELECT count(*) FROM interaction_session_requests"), [(1,)])
            if recover:
                self.assertEqual(journey.native_turns, helper_turns)
                self.assertEqual(journey.row("""
                    SELECT count(*),min(d.result_id),min(json_extract(a.doc,'$.canonical_result'))
                    FROM interaction_session_requests r
                    JOIN interaction_deliveries d ON d.request_id=r.target_instruction
                    JOIN interaction_instructions i ON i.id=json_extract(r.doc,'$.return_instruction')
                    JOIN interaction_session_authors a ON a.input_id=i.input_id
                    WHERE r.id=? AND json_extract(d.doc,'$.completed')=1
                """, (request_id,)), [(1, result_id, result_id)])

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
    signed_interrupt = os.environ.get("FOREGROUND_TEST_SIGNED_INTERRUPT")
    if signed_interrupt not in {"1", "before", "crash", "return-crash"}:
        signed_interrupt = None
    if signed_interrupt == "return-crash" and engine != "claude":
        raise SystemExit("The signed return crash fixture requires Claude")
    if signed_interrupt and not telegram_topic:
        os.environ["FOREGROUND_TEST_WITHOUT_TELEGRAM_CODEX"] = "1"
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
