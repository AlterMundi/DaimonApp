#!/usr/bin/env python3
"""Joined Antigravity qualification with signed disposable Matrix and native DMK.

Use PYTHONPATH=<Matrix>/src:<Matrix> and a disposable test environment.
All identity, model output and memory content belong to fixtures.
"""

from http.server import ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from threading import Thread
import unittest

import antigravity_foreground_io as foreground
from conversation_input_control_io import Inputs


def matrix_fixture():
    spec = importlib.util.spec_from_file_location(
        "app_matrix_fixture", Path(__file__).with_name("matrix_execution.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.AuthenticatedWeHostTests


def selected_memory(root, python, scripts, being, original):
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
    body_ref = "fixture:antigravity"
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


def qualify(gateway, sdk_python, scripts):
    parent = matrix_fixture()

    class SignedAntigravity(parent):
        def _check_round_trip(self, root, socket, fixture, service, capabilities, original,
                              author, body, return_attempts):
            import daimon_matrix
            from daimon_matrix.client import CLIENT_CONFIG_SCHEMA_V3

            being = fixture.ledger_b.authority.manifest.being_ref
            origin = fixture.ledger_b.local_origin
            source = {"being_ref": being, "embodiment_id": body}
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
            host = [sys.executable, "-B", str(wrapper), "--binding", str(document)]
            live_status = subprocess.run(
                [*host, "--body-status"], input=json.dumps({"source": source}),
                text=True, capture_output=True, check=True, timeout=5,
            )
            status = json.loads(live_status.stdout)
            self.assertEqual(status["local_origin"]["embodiment_id"], body)
            memory, database = selected_memory(root, sys.executable, scripts, being, original["message_id"])
            initial_database = database.read_bytes()
            journey = Inputs(gateway)
            self.addCleanup(journey.close)
            profile = root / "worker.json"
            state = root / "native-state"
            state.mkdir(mode=0o700)
            profile.touch(mode=0o600)

            with ThreadingHTTPServer(("127.0.0.1", 0), foreground.Provider) as provider:
                provider.journey = journey
                provider.calls = []
                provider.failure = None
                provider.mode = "accepted"
                provider.current = original["message_id"]
                provider.original = "Material for the selected turn"
                profile.write_text(json.dumps({
                    "node": "/usr/bin/node", "stateRoot": str(state), "model": "fixture",
                    "providerPort": provider.server_port, "matrixStatusCommand": host,
                    "body": {"beingRef": being, "embodimentId": body, "incarnationId": origin["incarnation_id"],
                             "manifestHash": status["manifest_hash"]},
                    "selectedMemory": memory,
                }))
                journey.config.write_text(journey.config.read_text() + f"""
[interaction.antigravity_foreground]
worker_command={json.dumps([sdk_python, "-B", str(foreground.WORKER), "--profile", str(profile)])}
[interaction.antigravity_foreground.transport]
command={json.dumps(host)}
source={{kind="body", being_ref="{being}", embodiment_id="{body}"}}
timeout_seconds=5
""")
                server = Thread(target=provider.serve_forever, daemon=True)
                server.start()
                try:
                    journey.start()
                    journey.wait_control_socket(journey.socket)
                    selected = dict(cursor=None, event_id=original["message_id"], author=author,
                                    thread_id=original["thread_id"])
                    reply = journey.read("matrix", "antigravity", "run", json.dumps(selected))["result"]
                    self.assertIsNone(provider.failure)
                    self.assertEqual(reply["phase"], "delivered", reply)
                    self.assertEqual(return_attempts, [reply["result"]["send_id"]])
                    self.assertEqual(provider.calls, [original["message_id"]] * 2)
                    self.assertEqual(database.read_bytes(), initial_database)
                    synced = fixture.ledger_a
                    result = reply["result"]["delivery"]
                    event = next(row for row in synced.conversation_evidence()
                                 if row["event_id"] == result["message_id"])
                    self.assertEqual(event["origin"]["embodiment_id"], body)
                    self.assertEqual(event["payload"]["intent"]["thread_id"], original["thread_id"])
                    self.assertIn(foreground.MARKER, event["payload"]["body"]["text"])
                    receipt = synced.event(result["receipt_event_id"])
                    self.assertEqual(receipt["origin"]["embodiment_id"], author)
                    self.assertEqual(receipt["payload"]["message_ref"]["event_hash"], result["message_hash"])
                finally:
                    provider.shutdown()
                    server.join()

    result = unittest.TextTestRunner(verbosity=2).run(SignedAntigravity("test_exact_original_and_signed_same_thread_return"))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("Usage: antigravity_signed_io.py GATEWAY SDK_PYTHON DMK_SCRIPTS")
    raise SystemExit(qualify(sys.argv[1], sys.argv[2], Path(sys.argv[3])))
