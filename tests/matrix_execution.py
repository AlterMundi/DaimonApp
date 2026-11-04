"""Zero-inference adapter tests against pinned Matrix signed/HTTP fixtures.

PYTHONPATH=<matrix>/src:<matrix> python3 -B tests/matrix_execution.py
Only synthetic keys, loopback transport and synthetic approval are used.
"""

import copy
import hashlib
import json
import sys
import time
import unittest
import uuid
from contextlib import nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from daimon_matrix.execution_instruction import Instruction, Scope
from matrix_execution import (
    MatrixConversationReceipt,
    MatrixConversationTransport,
    MatrixExecutionBroker,
    MatrixExecutionError,
    canonical,
    make_conversation_task,
    make_received_task,
    make_task,
    parent_from_verified_sdk,
    validate_task,
)
from matrix_operator import NativeOwnerClient, configured_client, receiving_command
from matrix_operator import inbox as operator_inbox
from matrix_operator import receive as operator_receive
from matrix_operator import send as operator_send
from tests.test_execution_instruction import request

from tests import test_dm025_client as client_fixtures
from tests import test_execution_store as store_fixtures
from tests import test_group_messaging_runtime as group_fixtures
from tests import test_passive_messaging_execution as runner_fixtures


@dataclass(frozen=True)
class SignedGroupClient:
    """SDK group seam; not an AF_UNIX/HMAC client qualification."""

    fixture: object
    group: object
    timeout_seconds: float = 1
    deadline_ns: int | None = None

    @property
    def config(self):
        return SimpleNamespace(expected_server=self.group.ledger.local_origin)

    def invoke(self, method, params):
        assert self.deadline_ns > time.monotonic_ns()
        assert self.timeout_seconds <= 1
        if method == "runtime.status":
            assert params == {}
            return {}, {
                "ok": True,
                "result": {
                    "schema": "dm.runtime.status/v1",
                    "being_ref": self.group.lane.being_ref,
                    "local_origin": self.group.ledger.local_origin,
                },
            }
        params = dict(params)
        assert params.pop("channel_id") == "tribe"
        if method == "messaging.inbox":
            result = {"channel_id": "tribe", "items": self.group.page(**params)}
        elif method == "messaging.delivery":
            result = self.group.inspect(client_id="test", **params)
        else:
            if method == "messaging.reply":
                assert params.pop("received_channel_id") == "tribe"
                parent = self.group.message(params.pop("message_id"))
                params["thread_id"] = parent["payload"]["intent"]["thread_id"]
                params["response_to"] = (self.group, parent["event_id"])
            else:
                assert method == "messaging.send"
            result = self.fixture.send_and_settle(
                self.group, client_id="test", **params
            )
        return {}, {"ok": True, "result": result}


class AdapterTests(unittest.TestCase):
    def setUp(self):
        # Reuse maintained SDK signing, native journals, authority resolution,
        # visibility and real HTTP handlers. No private runtime is opened.
        self.fixture = group_fixtures.GroupRuntimeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.sender, self.receiver = self.fixture.groups
        self.sender.direct_reader_ready = self.receiver.direct_reader_ready = (
            lambda row: True
        )
        self.scope = Scope("tribe", str(uuid.uuid4()), "messaging_send", "send")
        self.input_ref = str(uuid.uuid4())
        self.target = {
            "kind": "body",
            "being_ref": self.receiver.lane.being_ref,
            "embodiment_id": self.receiver.lane.local_embodiment_id,
        }
        self.broker = self.make_broker(self.sender, self.scope, target=self.target)

    def make_broker(
        self,
        group,
        scope,
        *,
        target=None,
        parent=None,
        revision=1,
        input_ref=None,
        task=None,
    ):
        task = task or make_task(
            "One explicitly selected technical question.",
            input_ref or self.input_ref,
            scope,
            selected_destination=target,
            verified_parent=parent,
        )
        instruction = Instruction.from_dict(
            request(
                mode="manual",
                interval=None,
                max_cycles=1,
                being=group.lane.being_ref,
                embodiment=group.lane.local_embodiment_id,
                task_sha256=hashlib.sha256(task.encode()).hexdigest(),
                scope=[
                    {
                        k: getattr(scope, k)
                        for k in ("channel", "thread", "tool", "action")
                    }
                ],
            )
        )
        if revision != 1:
            instruction = replace(instruction, revision=revision, predecessor="a" * 64)
        return MatrixExecutionBroker(
            instruction, task, SignedGroupClient(self.fixture, group)
        )

    def send(self):
        return self.broker.submit(
            self.scope, {"text": "What changed in the synthetic task?"}, 1
        )

    def technical_status(self):
        retained = {
            "schema": "telecodex.matrix-request/v1",
            "id": self.input_ref,
            "human": 100,
            "entry": {"chat_id": 100, "thread_id": 1},
            "original": {
                "human_id": 100,
                "origin": {"chat_id": 100, "thread_id": 1},
                "text": "  Exact retained human input.\nNo inference needed.  ",
                "transcription": None,
            },
            "destination": self.target,
            "parents": [],
            "relation": {"kind": "new"},
        }
        retained["binding"] = hashlib.sha256(canonical(retained).encode()).hexdigest()
        return {"request": retained, "current": True, "phase": "awaiting_execution"}

    def technical_transport(self, status=None, author=None):
        return MatrixConversationTransport(
            status or self.technical_status(),
            author
            or {
                "being_ref": self.sender.lane.being_ref,
                "embodiment_id": self.sender.lane.local_embodiment_id,
            },
            SignedGroupClient(self.fixture, self.sender),
        )

    def test_technical_original_without_execution_approval_has_verified_return(self):
        status = self.technical_status()
        transport = self.technical_transport(status)
        self.assertFalse(hasattr(transport, "controller"))
        self.assertFalse(hasattr(transport, "_instruction"))
        sent = transport.send()
        received = self.receiver.message(sent["message_id"])
        relay = json.loads(received["payload"]["body"]["text"])
        self.assertIsNone(relay["execution_ref"])
        self.assertEqual(relay["text"], status["request"]["original"]["text"])
        self.assertEqual(relay["relation"], {"kind": "new"})
        self.assertEqual(relay["input_kind"], "human_text")
        self.assertEqual(sent["thread_id"], self.input_ref)
        reply_scope = Scope("tribe", self.input_ref, "messaging_reply", "reply")
        # Technical receipt only prepares a task. Independent receiving approval
        # is still required before a runner can act or return model output.
        task = make_received_task(received, reply_scope)
        responder = self.make_broker(self.receiver, reply_scope, task=task)
        returned = responder.submit(
            reply_scope, {"text": "Independently admitted answer."}, 1
        )
        answer = self.sender.message(returned["message_id"])
        callback = transport.conversation_return(sent, answer)
        self.assertEqual(callback["binding"], status["request"]["binding"])
        self.assertEqual(callback["text"], "Independently admitted answer.")
        self.assertEqual(transport.inspect()["message_id"], sent["message_id"])
        # Rebuilding from the same retained status cannot create a second send.
        self.assertEqual(
            self.technical_transport(status).send()["message_id"], sent["message_id"]
        )
        self.assertEqual(transport.send_id, self.broker.send_id)
        with self.assertRaisesRegex(MatrixExecutionError, "model-rewritten"):
            transport.submit(transport._scope, {"text": "Rewritten input"}, 1)

    def test_technical_transport_rejects_stale_binding_and_mismatched_source(self):
        status = self.technical_status()
        status["current"] = False
        with self.assertRaisesRegex(MatrixExecutionError, "current and pending"):
            self.technical_transport(status)
        status["current"] = True
        status["request"]["original"]["text"] = "Mutated original"
        with self.assertRaisesRegex(MatrixExecutionError, "binding"):
            self.technical_transport(status)
        transport = self.technical_transport(
            author={
                "being_ref": self.receiver.lane.being_ref,
                "embodiment_id": self.sender.lane.local_embodiment_id,
            }
        )
        before = self.sender.records.page(after=0, limit=100)
        with self.assertRaisesRegex(MatrixExecutionError, "unconfirmed"):
            transport.send()
        self.assertEqual(before, self.sender.records.page(after=0, limit=100))
        # Switching from an already authored execution relay to technical mode
        # does not get a new send identity or silently replace its wire bytes.
        self.send()
        with self.assertRaisesRegex(MatrixExecutionError, "unconfirmed"):
            self.technical_transport().send()

    def acknowledged_status(self):
        pending = self.technical_status()
        transport = self.technical_transport(pending)
        sent = transport.send()
        status = {
            **pending,
            "current": False,
            "phase": "submitted",
            "claimed_source": sent["author"],
            "submission": {
                key: sent[key]
                for key in (
                    "send_id",
                    "message_id",
                    "message_hash",
                    "thread_id",
                    "author",
                )
            },
        }
        status["submission"]["destination"] = self.target
        # Match the owner RPC's JSON snapshot, with no shared Python aliases.
        return json.loads(canonical(status)), sent

    def test_historical_acknowledged_receipt_correlates_without_reviving_send(self):
        status, sent = self.acknowledged_status()
        receipt = MatrixConversationReceipt(
            status, SignedGroupClient(self.fixture, self.sender)
        )
        self.assertFalse(hasattr(receipt, "controller"))
        self.assertFalse(hasattr(receipt, "send"))
        self.assertEqual(receipt.inspect()["message_id"], sent["message_id"])
        with patch.object(
            SignedGroupClient, "invoke", side_effect=AssertionError("no native effect")
        ):
            with self.assertRaisesRegex(MatrixExecutionError, "cannot author"):
                receipt.submit(receipt._scope, {"text": "must not send"}, 1)
        message = self.receiver.message(sent["message_id"])
        reply_scope = replace(
            self.scope, thread=sent["thread_id"], tool="messaging_reply", action="reply"
        )
        responder = self.make_broker(
            self.receiver, reply_scope, task=make_received_task(message, reply_scope)
        )
        returned = responder.submit(
            reply_scope, {"text": "A late independently admitted answer."}, 1
        )
        answer = self.sender.message(returned["message_id"])
        callback = receipt.conversation_return(receipt.inspect(), answer)
        self.assertEqual(callback["request"], status["request"]["id"])
        self.assertEqual(callback["binding"], status["request"]["binding"])
        self.assertEqual(callback["submission"], status["submission"])
        self.assertEqual(callback["text"], "A late independently admitted answer.")
        self.assertNotIn("current", callback)
        self.assertFalse(status["current"])
        self.assertEqual(status["phase"], "submitted")
        changed = copy.deepcopy(sent)
        changed["message_hash"] = "e" * 64
        with self.assertRaisesRegex(MatrixExecutionError, "acknowledged submission"):
            receipt.conversation_return(changed, answer)
        status["phase"] = "reply_received"
        self.assertEqual(
            MatrixConversationReceipt(
                status, SignedGroupClient(self.fixture, self.sender)
            ).inspect()["message_id"],
            sent["message_id"],
        )

    def test_new_inbox_reads_actual_signed_original_without_human_or_work_claim(self):
        sent = self.broker.submit(
            self.scope, {"text": "Fresh peer question; no human instruction."}, 1
        )
        source = {
            "being_ref": self.receiver.lane.being_ref,
            "embodiment_id": self.receiver.lane.local_embodiment_id,
        }
        client = SignedGroupClient(self.fixture, self.receiver)
        calls, deadlines = [], []
        invoke = SignedGroupClient.invoke

        def observe(selected, method, params):
            calls.append((method, params))
            deadlines.append(selected.deadline_ns)
            return invoke(selected, method, params)

        request = {"source": source, "channel_id": "tribe", "after": 0, "limit": 3}
        with patch.object(SignedGroupClient, "invoke", observe):
            page = operator_inbox(request, client, timeout=1)
        self.assertEqual(
            [method for method, _ in calls], ["runtime.status", "messaging.inbox"]
        )
        self.assertEqual(len(set(deadlines)), 1)
        self.assertEqual(calls[-1][1], {"channel_id": "tribe", "after": 0, "limit": 3})
        self.assertEqual(page["schema"], "daimon.matrix-inbox-page/v1")
        self.assertEqual(page["items"][0]["message_id"], sent["message_id"])
        self.assertEqual(page["items"][0]["message_hash"], sent["message_hash"])
        self.assertEqual(
            page["items"][0]["author"],
            {
                "being_ref": self.sender.lane.being_ref,
                "embodiment_id": self.sender.lane.local_embodiment_id,
            },
        )
        self.assertEqual(
            page["items"][0]["text"],
            self.receiver.message(sent["message_id"])["payload"]["body"]["text"]
        )
        self.assertNotIn("human", page["items"][0])
        self.assertNotIn("execution_ref", page["items"][0])
        self.assertEqual(operator_inbox(request, client, timeout=1), page)
        self.assertEqual(
            operator_inbox(
                {**request, "after": page["next_cursor"]}, client, timeout=1
            )["items"],
            [],
        )

    def test_new_inbox_bounds_owner_and_failed_pages_do_not_supply_a_cursor(self):
        source = {
            "being_ref": self.receiver.lane.being_ref,
            "embodiment_id": self.receiver.lane.local_embodiment_id,
        }
        client = SignedGroupClient(self.fixture, self.receiver)
        request = {"source": source, "channel_id": "tribe", "after": 0, "limit": 3}
        for change in (
            {"after": True},
            {"after": -1},
            {"limit": 4},
            {"limit": 0},
            {"channel_id": ""},
            {"source": {**source, "embodiment_id": "another"}},
        ):
            with (
                self.subTest(change=change),
                patch.object(SignedGroupClient, "invoke") as invoke,
            ):
                with self.assertRaises(MatrixExecutionError):
                    operator_inbox({**request, **change}, client, timeout=1)
                invoke.assert_not_called()
        with patch.object(
            SignedGroupClient, "invoke", return_value=({}, {"ok": False})
        ), self.assertRaises(MatrixExecutionError):
            operator_inbox(request, client, timeout=1)

    def test_selected_reply_read_is_one_signed_page_without_model_or_send(self):
        status, sent = self.acknowledged_status()
        message = self.receiver.message(sent["message_id"])
        reply_scope = replace(
            self.scope, thread=sent["thread_id"], tool="messaging_reply", action="reply"
        )
        responder = self.make_broker(
            self.receiver, reply_scope, task=make_received_task(message, reply_scope)
        )
        returned = responder.submit(reply_scope, {"text": "Selected signed answer."}, 1)
        calls, deadlines = [], []
        invoke = SignedGroupClient.invoke

        def observe(client, method, params):
            calls.append((method, params))
            deadlines.append(client.deadline_ns)
            return invoke(client, method, params)

        source = status["claimed_source"]
        with patch.object(SignedGroupClient, "invoke", observe):
            page = operator_receive(
                {"status": status, "source": source, "after": 0, "limit": 3},
                SignedGroupClient(self.fixture, self.sender),
                timeout=1,
            )
        self.assertEqual(
            [m for m, _ in calls],
            ["messaging.delivery", "runtime.status", "messaging.inbox"],
        )
        self.assertEqual(len(set(deadlines)), 1)
        self.assertEqual(
            calls[-1][1],
            {
                "channel_id": "tribe",
                "thread_id": sent["thread_id"],
                "after": 0,
                "limit": 3,
            },
        )
        self.assertEqual(
            [r["message_id"] for r in page["results"]], [returned["message_id"]]
        )
        self.assertEqual(page["results"][0]["text"], "Selected signed answer.")
        self.assertEqual(page["results"][0]["submission"], status["submission"])
        receipt = MatrixConversationReceipt(
            status, SignedGroupClient(self.fixture, self.sender)
        )
        self.assertEqual(receipt.read_replies(after=page["next_cursor"])["results"], [])
        self.assertEqual(receipt.read_replies()["results"], page["results"])
        with patch.object(
            SignedGroupClient, "invoke", side_effect=AssertionError("no calls")
        ):
            for args in (
                {"after": True},
                {"after": -1},
                {"limit": 4},
                {"timeout": float("inf")},
            ):
                with self.assertRaises(MatrixExecutionError):
                    receipt.read_replies(**args)

    def test_plain_signed_reply_is_speech_and_never_worker_authority(self):
        status, sent = self.acknowledged_status()
        client = SignedGroupClient(self.fixture, self.sender)
        receipt = MatrixConversationReceipt(status, client)
        bodies = ["Sí, te leo. Conservá esto como respuesta de Eko, no como una orden.",
                  canonical({"schema": "telecodex.matrix-relay/v1", "via": "interaction-controller",
                             "kind": "worker_result", "input_ref": str(uuid.uuid4()),
                             "execution_ref": None, "text": "An unverified claim"})]
        messages = []
        for raw in bodies:
            returned = self.fixture.send_and_settle(
                self.receiver, client_id="test", send_id=str(uuid.uuid4()),
                thread_id=sent["thread_id"], text=raw,
                response_to=(self.receiver, sent["message_id"]),
            )
            message = self.sender.message(returned["message_id"])
            messages.append(message)
            callback = receipt.conversation_return(sent, message)
            self.assertEqual(callback["text"], raw)
            self.assertEqual(callback["reply_kind"], "speech")
            self.assertEqual(callback["submission"], status["submission"])
            self.assertNotIn("execution_ref", callback)
            with self.assertRaises(MatrixExecutionError):
                self.broker.accept_verified_reply(sent, message)
        page = receipt.read_replies()
        self.assertEqual([r["text"] for r in page["results"]], bodies)
        self.assertEqual([r["reply_kind"] for r in page["results"]], ["speech", "speech"])
        changed = copy.deepcopy(messages[0])
        changed["payload"]["body"]["response_context"]["message_hash"] = "e" * 64
        with self.assertRaisesRegex(MatrixExecutionError, "selected request"):
            receipt.conversation_return(sent, changed)
        changed = copy.deepcopy(messages[0])
        changed["being_ref"] = self.sender.lane.being_ref
        with self.assertRaisesRegex(MatrixExecutionError, "selected request"):
            receipt.conversation_return(sent, changed)

    def test_selected_reader_rejection_never_falls_back_to_broad_scan(self):
        status, _ = self.acknowledged_status()
        client = SignedGroupClient(self.fixture, self.sender)
        calls = []
        invoke = SignedGroupClient.invoke

        def rejected(selected, method, params):
            calls.append((method, params))
            if method == "messaging.inbox":
                raise ValueError("old receiver or rejected authority")
            return invoke(selected, method, params)

        with patch.object(SignedGroupClient, "invoke", rejected):
            with self.assertRaises(MatrixExecutionError):
                MatrixConversationReceipt(status, client).read_replies()
        self.assertEqual(len([p for m, p in calls if m == "messaging.inbox"]), 1)
        self.assertIn("thread_id", calls[-1][1])

    def test_receipt_requires_retained_ack_source_and_immutable_original(self):
        status, _ = self.acknowledged_status()
        client = SignedGroupClient(self.fixture, self.sender)
        cases = []
        unknown = copy.deepcopy(status)
        unknown["phase"] = "submission_uncertain"
        unknown["submission"] = None
        cases.append(unknown)
        unknown = copy.deepcopy(status)
        unknown["phase"] = "submitting"
        cases.append(unknown)
        changed = copy.deepcopy(status)
        changed["claimed_source"] = None
        cases.append(changed)
        changed = copy.deepcopy(status)
        changed["claimed_source"]["being_ref"] = self.receiver.lane.being_ref
        cases.append(changed)
        changed = copy.deepcopy(status)
        changed["submission"]["send_id"] = str(uuid.uuid4())
        cases.append(changed)
        changed = copy.deepcopy(status)
        changed["submission"]["thread_id"] = str(uuid.uuid4())
        cases.append(changed)
        changed = copy.deepcopy(status)
        changed["request"]["original"]["text"] = "Changed after admission"
        cases.append(changed)
        with patch.object(
            SignedGroupClient,
            "invoke",
            side_effect=AssertionError("constructor must not call SDK"),
        ):
            for index, case in enumerate(cases):
                with self.subTest(index=index, phase=case["phase"]):
                    with self.assertRaises(MatrixExecutionError):
                        MatrixConversationReceipt(case, client)
        # The ordinary sender still requires actual current/pending admission.
        with self.assertRaisesRegex(MatrixExecutionError, "current and pending"):
            MatrixConversationTransport(status, status["claimed_source"], client)

    def test_host_context_tracks_current_owner_without_executing_connection_code(self):
        import tempfile
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "connection.json"
            script = Path(tmp) / "matrix_operator.py"
            script.write_text(
                "import json,sys;print(json.dumps({'prefix':sys.prefix,'paths':sys.path[:3],'args':sys.argv[1:],'stdin':sys.stdin.buffer.read().decode(),'qualified':sys.qualified_owner}))"
            )
            code = Path(tmp) / "code-old"
            package = code / "clusterctl"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("")
            (package / "onboarding_code_successor.py").write_text(
                "def sdk_parameters(code,uid):return {'matrix_commit':'qualified-fixture'}"
            )
            (package / "onboarding_sdk.py").write_text(
                "import sys\ndef qualified_startup(venv,code,*,code_digest,code_uid,**parameters):\n assert sys.path[:2]==[str(code),'/receiving/imports-old']\n sys.qualified_owner=[code_digest,code_uid,parameters['matrix_commit']]\n"
            )
            value = {
                "command": [
                    sys.executable,
                    "-B",
                    "-I",
                    "-S",
                    "-c",
                    "raise AssertionError('connection code must not execute')",
                    "/receiving/sdk-old",
                    "/receiving/imports-old",
                    str(code),
                    "clusterctl.onboarding_owner_client",
                    "--code-digest",
                    "a" * 64,
                    "--code-owner",
                    "0",
                    "--binding",
                    "/private/chat.json",
                ]
            }
            path.write_text(json.dumps(value))
            import matrix_operator

            with patch.object(matrix_operator, "__file__", str(script)):
                first = receiving_command(path, Path("/private/host.json"))
                result = subprocess.run(
                    first,
                    input="exact original α",
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=5,
                )
                observed = json.loads(result.stdout)
                self.assertEqual(observed["prefix"], "/receiving/sdk-old")
                self.assertEqual(
                    observed["paths"], [tmp, str(code), "/receiving/imports-old"]
                )
                self.assertEqual(
                    observed["qualified"], ["a" * 64, 0, "qualified-fixture"]
                )
                self.assertEqual(observed["args"], ["--binding", "/private/host.json"])
                self.assertEqual(observed["stdin"], "exact original α")
                receive_command = receiving_command(
                    path, Path("/private/host.json"), receive_only=True
                )
                received = subprocess.run(
                    receive_command,
                    input="selected read",
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=5,
                )
                self.assertEqual(
                    json.loads(received.stdout)["args"],
                    ["--binding", "/private/host.json", "--receive"],
                )

                inbox_command = receiving_command(
                    path, Path("/private/host.json"), inbox_only=True
                )
                incoming = subprocess.run(inbox_command, input="selected page",
                                          text=True, capture_output=True, check=True, timeout=5)
                self.assertEqual(json.loads(incoming.stdout)["args"],
                                 ["--binding", "/private/host.json", "--inbox"])
                with self.assertRaises(MatrixExecutionError):
                    receiving_command(path, Path("/private/host.json"),
                                      inbox_only=True, receive_only=True)

                (package / "onboarding_sdk.py").write_text(
                    "def qualified_startup(*args,**kwargs):raise RuntimeError('private diagnostic must stay local')"
                )
                denied = subprocess.run(
                    first,
                    input="retained original",
                    text=True,
                    capture_output=True,
                    timeout=5,
                )
                self.assertEqual(denied.returncode, 1)
                self.assertEqual(denied.stdout, "")
                self.assertEqual(json.loads(denied.stderr), {"error": "RuntimeError"})
                value["command"][6:9] = [
                    "/receiving/sdk-new",
                    "/receiving/imports-new",
                    "/receiving/code-new",
                ]
                path.write_text(json.dumps(value))
                self.assertEqual(
                    receiving_command(path, Path("/private/host.json"))[6:9],
                    value["command"][6:9],
                )
            for changed in (
                ["/tmp/python", "-c", "untrusted code"],
                value["command"][:9] + ["another_owner"] + value["command"][10:],
                value["command"][:6] + ["relative-sdk"] + value["command"][7:],
                value["command"][:10]
                + ["--different-qualification"]
                + value["command"][11:],
            ):
                path.write_text(json.dumps({"command": changed}))
                with self.assertRaises(MatrixExecutionError):
                    receiving_command(path, Path("/private/host.json"))

    def funded_original(self, *, status=None):
        import tempfile
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from daimon_matrix.execution_store import ExecutionStore
        from tests.test_execution_instruction import proof, verifier

        tmp = tempfile.TemporaryDirectory(prefix="funded-conversation-")
        self.addCleanup(tmp.cleanup)
        key = Ed25519PrivateKey.generate()
        store = ExecutionStore.create(
            Path(tmp.name) / "execution.sqlite", verifier(key), clock=lambda: 100
        )
        store.enable_episode_reporting()

        def signed(value, event):
            return proof(key, "approve", value, event)

        status = status or self.technical_status()
        reply_scope = Scope(
            "tribe", status["request"]["id"], "messaging_reply", "reply"
        )
        purpose = (
            "Review one eligible signed original and return a bounded useful answer."
        )
        instruction = Instruction.from_dict(
            request(
                store_id=store.store_id,
                being=self.receiver.lane.being_ref,
                embodiment=self.receiver.lane.local_embodiment_id,
                mode="periodic",
                interval=10,
                max_cycles=2,
                max_input_tokens=16384,
                task_sha256=hashlib.sha256(purpose.encode()).hexdigest(),
                scope=[
                    {
                        k: getattr(reply_scope, k)
                        for k in ("channel", "thread", "tool", "action")
                    }
                ],
            )
        )
        for kind in ("tribe", "being", "episode"):
            account = dict(
                schema="execution/funding-account/v1",
                store_id=store.store_id,
                principal="human:test",
                account_id=kind,
                kind=kind,
                subject=instruction.being if kind == "being" else kind,
                start=100,
                end=200,
                unit="synthetic-charge",
                max_calls=3,
                max_charge=100,
                max_active=1,
                max_bindings=3,
            )
            store.grant_budget(account, signed(account, "account-" + kind))
        store.approve(instruction, signed(instruction.to_dict(), "instruction"))
        funding = dict(
            schema="execution/instruction-funding/v1",
            store_id=store.store_id,
            principal="human:test",
            instruction_sha256=instruction.sha256,
            accounts=["tribe", "being", "episode"],
            route="isolated-fake",
            max_charge=30,
        )
        store.fund_instruction(instruction, funding, signed(funding, "funding"))
        policy = dict(
            schema="execution/episode-policy/v1",
            store_id=store.store_id,
            principal="human:test",
            account_id="episode",
            participants=[self.sender.lane.being_ref],
            instructions=[instruction.sha256],
            threads=[reply_scope.thread],
            max_requests=3,
            max_pending=2,
            max_input_bytes=16384,
        )
        store.configure_episode(policy, signed(policy, "policy"))
        metadata = dict(
            schema="execution/coordination-request/v1",
            account_id="episode",
            instruction_sha256=instruction.sha256,
            kind="work",
        )
        # The approved purpose/funding/hash exist BEFORE the original message.
        transport = MatrixConversationTransport(
            status,
            {
                "being_ref": self.sender.lane.being_ref,
                "embodiment_id": self.sender.lane.local_embodiment_id,
            },
            SignedGroupClient(self.fixture, self.sender),
            coordination=metadata,
        )
        outcome = operator_send(
            {"status": status, "source": transport._author},
            SignedGroupClient(self.fixture, self.sender),
            timeout=1,
            coordination=metadata,
        )
        sent = transport.inspect()
        self.assertEqual(outcome["submission"]["message_id"], sent["message_id"])
        original = self.receiver.message(sent["message_id"])
        broker = MatrixExecutionBroker(
            instruction,
            purpose,
            SignedGroupClient(self.fixture, self.receiver),
            received_source=original,
        )
        runner = runner_fixtures.BoundedFakeRunner()
        runner.binding = instruction.binding
        reads = []

        def read(message_id):
            reads.append(message_id)
            return self.receiver.message(message_id)

        controller = broker.controller(
            store, runner, read_message=read, monotonic=lambda: 10
        )
        work = controller.enqueue_native(original["event_id"])
        return SimpleNamespace(
            store=store,
            key=key,
            instruction=instruction,
            purpose=purpose,
            metadata=metadata,
            scope=reply_scope,
            transport=transport,
            sent=sent,
            source=original,
            broker=broker,
            runner=runner,
            controller=controller,
            work=work,
            reads=reads,
            status=status,
            outcome=outcome,
        )

    def test_funded_selected_original_returns_under_the_same_conversation_root(self):
        state = self.funded_original()
        context = state.controller.run_due_once(
            state.instruction.instruction_id, 1, state.purpose, work_id=state.work
        )
        self.assertEqual(len(state.runner.starts), 1)
        self.assertEqual(
            context.selected_original()["event_id"], state.source["event_id"]
        )
        requests = []
        context.inference(
            lambda: requests.append("bounded provider request"),
            exposure=dict(
                route="isolated-fake",
                max_charge=30,
                provider=state.instruction.provider,
                model=state.instruction.model,
                max_input_tokens=state.instruction.max_input_tokens,
                max_output_tokens=state.instruction.max_output_tokens,
            ),
        )
        result = context.native(
            state.scope, {"text": "The funded selected task is complete."}
        )
        self.assertTrue(result["semantic"]["terminal"])
        state.store.finish(context.cycle, "completed")
        answer = self.sender.message(result["message_id"])
        self.assertEqual(
            answer["payload"]["body"]["coordination"],
            state.metadata | {"kind": "result"},
        )
        callback = state.transport.conversation_return(state.sent, answer)
        self.assertEqual(callback["request"], state.status["request"]["id"])
        self.assertEqual(callback["binding"], state.status["request"]["binding"])
        self.assertEqual(callback["text"], "The funded selected task is complete.")
        self.assertEqual(callback["author"]["being_ref"], self.receiver.lane.being_ref)
        self.assertIsNone(
            state.store.enqueue_coordination(answer["event_id"], self.sender.message)
        )
        self.assertEqual(requests, ["bounded provider request"])
        self.assertEqual(set(state.reads), {state.source["event_id"]})
        balance = state.store.funding_status("episode")
        self.assertEqual((balance["calls"], balance["reserved"]), (1, 30))
        self.assertEqual(
            state.store.coordination_work(state.work)["cycle_id"],
            context.cycle.cycle_id,
        )
        self.assertIsNone(
            state.controller.run_due_once(
                state.instruction.instruction_id, 1, state.purpose, work_id=state.work
            )
        )
        self.assertEqual(len(state.runner.starts), 1)

    def test_queued_broker_rejects_another_eligible_original_and_disabled_gates(self):
        from daimon_matrix.execution_instruction import ExecutionDenied

        state = self.funded_original()
        for option in ("require_funding", "require_queued_source"):
            with self.assertRaises(MatrixExecutionError):
                state.broker.controller(
                    state.store,
                    state.runner,
                    read_message=self.receiver.message,
                    **{option: False},
                )
        with self.assertRaises(ExecutionDenied):
            state.controller.run_due_once(
                state.instruction.instruction_id, 1, state.purpose
            )
        relay = json.loads(state.source["payload"]["body"]["text"])
        relay["input_ref"] = str(uuid.uuid4())
        other = self.fixture.send_and_settle(
            self.sender,
            client_id="test",
            send_id=str(uuid.uuid4()),
            thread_id=state.scope.thread,
            text=canonical(relay),
            destination=self.target,
            coordination=state.metadata,
        )
        other_work = state.controller.enqueue_native(other["message_id"])
        self.assertNotEqual(other_work, state.work)
        with self.assertRaisesRegex(ExecutionDenied, "pinned receiving original"):
            state.controller.run_due_once(
                state.instruction.instruction_id, 1, state.purpose, work_id=other_work
            )
        self.assertEqual(state.runner.starts, [])
        self.assertEqual(state.store.funding_status("episode")["calls"], 0)
        self.assertEqual(state.store.coordination_work(other_work)["state"], "queued")

    def test_signed_request_and_exact_parent_return_preserve_provenance(self):
        first = self.send()
        self.assertTrue(first["semantic"]["terminal"])
        self.assertEqual(len(first["audience"]), 1)
        received = self.receiver.message(first["message_id"])
        relay = json.loads(received["payload"]["body"]["text"])
        self.assertEqual(relay["via"], "interaction-controller")
        self.assertEqual(relay["kind"], "session_request")
        self.assertEqual(received["being_ref"], self.sender.lane.being_ref)
        scope = replace(self.scope, tool="messaging_reply", action="reply")
        responder = self.make_broker(
            self.receiver, scope, parent=parent_from_verified_sdk(received)
        )
        returned = responder.submit(
            scope, {"text": "The synthetic task is complete."}, 1
        )
        self.assertTrue(returned["semantic"]["terminal"])
        answer = self.sender.message(returned["message_id"])
        self.assertEqual(
            self.broker.accept_verified_reply(first, answer),
            "The synthetic task is complete.",
        )
        self.assertEqual(
            returned["destination"]["being_ref"], self.sender.lane.being_ref
        )
        for field, value in [("being_ref", self.sender.lane.being_ref)]:
            wrong = copy.deepcopy(answer)
            wrong[field] = value
            with self.assertRaises(MatrixExecutionError):
                self.broker.accept_verified_reply(first, wrong)
        wrong = copy.deepcopy(answer)
        wrong["payload"]["body"]["response_context"]["message_hash"] = "0" * 64
        with self.assertRaises(MatrixExecutionError):
            self.broker.accept_verified_reply(first, wrong)

    def test_conversation_original_and_selected_context_use_signed_roundtrip(self):
        original = "  Pregunta exacta: ¿qué cambió?\nConservá este contexto.  "
        retained = {
            "schema": "telecodex.matrix-request/v1",
            "id": self.input_ref,
            "human": 100,
            "entry": {"chat_id": 100, "thread_id": 1},
            "original": {
                "human_id": 100,
                "origin": {"chat_id": 100, "thread_id": 1},
                "text": original,
                "transcription": {"capture_id": "fixture"},
            },
            "destination": self.target,
            "parents": [
                {
                    "request": str(uuid.uuid4()),
                    "binding": "c" * 64,
                    "text": "Only the explicitly selected previous original.",
                    "input_kind": "human_text",
                }
            ],
        }
        retained["relation"] = {
            "kind": "amends",
            "requests": [retained["parents"][0]["request"]],
        }
        retained["binding"] = hashlib.sha256(canonical(retained).encode()).hexdigest()
        status = {"request": retained, "current": True, "phase": "awaiting_execution"}
        task = make_conversation_task(status, self.scope)
        self.assertEqual(json.loads(task)["relation"], retained["relation"])
        broker = self.make_broker(self.sender, self.scope, task=task)
        with self.assertRaises(MatrixExecutionError):
            broker.submit(self.scope, {"text": "A model's paraphrase"}, 1)
        first = broker.submit(self.scope, {"text": original}, 1)
        received = self.receiver.message(first["message_id"])
        wire = received["payload"]["body"]["text"]
        relay = json.loads(wire)
        self.assertEqual(relay["text"], original)
        self.assertEqual(relay["context"], retained["parents"])
        self.assertEqual(relay["relation"], retained["relation"])
        self.assertEqual(relay["input_kind"], "committed_machine_transcript")
        self.assertNotIn('"human"', wire)
        self.assertNotIn('"entry"', wire)
        scope = replace(self.scope, tool="messaging_reply", action="reply")
        received_task = make_received_task(received, scope)
        self.assertEqual(json.loads(received_task)["question"], original)
        self.assertEqual(json.loads(received_task)["relation"], retained["relation"])
        responder = self.make_broker(self.receiver, scope, task=received_task)
        response = responder.submit(scope, {"text": "Exact signed answer."}, 1)
        answer = self.sender.message(response["message_id"])
        callback = broker.conversation_return(first, answer)
        self.assertEqual(callback["request"], retained["id"])
        self.assertEqual(callback["binding"], retained["binding"])
        self.assertEqual(callback["text"], "Exact signed answer.")
        self.assertEqual(callback["author"]["being_ref"], self.receiver.lane.being_ref)
        wrong = copy.deepcopy(status)
        wrong["request"]["original"]["text"] = "Changed after selection"
        with self.assertRaises(MatrixExecutionError):
            make_conversation_task(wrong, self.scope)

    def test_serialized_context_bound_is_checked_before_any_execution(self):
        parent = {
            "request": str(uuid.uuid4()),
            "binding": "c" * 64,
            "text": "x" * 10000,
            "input_kind": "human_text",
        }
        with self.assertRaisesRegex(MatrixExecutionError, "serialized relay"):
            make_task(
                "x" * 10000,
                self.input_ref,
                self.scope,
                selected_destination=self.target,
                context=[parent],
                input_kind="human_text",
            )
        # Small raw text can still exceed the wire bound through JSON escaping.
        with self.assertRaisesRegex(MatrixExecutionError, "serialized relay"):
            make_task(
                "x" + "\t" * 8000,
                self.input_ref,
                self.scope,
                selected_destination=self.target,
                context=[],
                input_kind="human_text",
            )
        # Reserve worst permitted execution metadata plus all four relation IDs.
        parents = [
            {**parent, "request": str(uuid.uuid4()), "text": "Bounded selected parent."}
            for _ in range(4)
        ]
        task = make_task(
            "ñ" * 7000,
            self.input_ref,
            self.scope,
            selected_destination=self.target,
            context=parents,
            input_kind="human_text",
            relation={
                "kind": "context",
                "requests": [row["request"] for row in parents],
            },
        )
        broker = self.make_broker(self.sender, self.scope, task=task)
        instruction = replace(
            broker._instruction,
            instruction_id="x" * 200,
            revision=2**53 - 1,
            predecessor="a" * 64,
        )
        broker = MatrixExecutionBroker(instruction, task, broker._client)
        result = broker.submit(self.scope, {"text": "ñ" * 7000}, 1)
        self.assertTrue(result["semantic"]["terminal"])
        relay = json.loads(
            self.receiver.message(result["message_id"])["payload"]["body"]["text"]
        )
        self.assertEqual(
            relay["execution_ref"], {"id": "x" * 200, "revision": 2**53 - 1}
        )

    def test_signed_malformed_relation_is_refused_before_receiving_execution(self):
        relay = {
            "schema": "telecodex.matrix-relay/v1",
            "via": "interaction-controller",
            "kind": "session_request",
            "input_ref": self.input_ref,
            "execution_ref": {"id": "synthetic-selected-source", "revision": 1},
            "text": "Selected original.",
            "relation": None,
        }
        sent = self.fixture.send_and_settle(
            self.sender,
            client_id="test",
            send_id=str(uuid.uuid4()),
            thread_id=self.scope.thread,
            text=canonical(relay),
            destination=self.target,
        )
        message = self.receiver.message(sent["message_id"])
        scope = replace(self.scope, tool="messaging_reply", action="reply")
        with self.assertRaisesRegex(MatrixExecutionError, "relation object"):
            make_received_task(message, scope)

    def test_being_directed_reply_preserves_kind_and_rejects_broadcast_parent(self):
        requester = self.make_broker(
            self.sender,
            self.scope,
            target={"kind": "being", "being_ref": self.receiver.lane.being_ref},
        )
        first = requester.submit(
            self.scope, {"text": "Being-directed synthetic task"}, 1
        )
        received = self.receiver.message(first["message_id"])
        scope = replace(self.scope, tool="messaging_reply", action="reply")
        parent = parent_from_verified_sdk(received)
        responder = self.make_broker(self.receiver, scope, parent=parent)
        returned = responder.submit(scope, {"text": "Being-directed response"}, 1)
        self.assertTrue(returned["semantic"]["terminal"])
        self.assertEqual(returned["destination"]["kind"], "being")
        self.assertEqual(
            requester.accept_verified_reply(
                first, self.sender.message(returned["message_id"])
            ),
            "Being-directed response",
        )
        broadcast = copy.deepcopy(received)
        broadcast["payload"]["body"].pop("destination")
        with patch.object(
            SignedGroupClient, "invoke", side_effect=AssertionError("must not invoke")
        ):
            with self.assertRaises(MatrixExecutionError):
                parent_from_verified_sdk(broadcast)
            with self.assertRaises(MatrixExecutionError):
                self.make_broker(
                    self.receiver, scope, parent=parent | {"destination": None}
                )

    def test_retained_identity_prevents_renewal_reroute_and_changed_content(self):
        first = self.send()
        self.assertEqual(self.broker.inspect()["message_id"], first["message_id"])
        renewed = self.make_broker(
            self.sender, self.scope, target=self.target, revision=2
        )
        self.assertEqual(renewed.send_id, self.broker.send_id)
        # Revision is in provenance. Native reservation rejects different bytes
        # for an already authored input instead of creating another send.
        with self.assertRaises(MatrixExecutionError):
            renewed.submit(self.scope, {"text": "Different approved revision"}, 1)
        alternate = self.make_broker(
            self.sender,
            self.scope,
            target={
                "kind": "body",
                "being_ref": self.sender.lane.being_ref,
                "embodiment_id": self.sender.lane.local_embodiment_id,
            },
        )
        self.assertEqual(alternate.send_id, self.broker.send_id)
        with self.assertRaises(MatrixExecutionError):
            alternate.submit(self.scope, {"text": "Reroute"}, 1)
        self.assertEqual(len(self.receiver.page(after=0, limit=10)), 1)

    def test_lost_response_remains_inspectable_without_another_send(self):
        actual = SignedGroupClient.invoke

        def lose(client, method, params):
            outcome = actual(client, method, params)
            if method == "runtime.status":
                return outcome
            raise TimeoutError("synthetic response loss after actual receipt")

        with patch.object(SignedGroupClient, "invoke", lose):
            with self.assertRaisesRegex(MatrixExecutionError, "unconfirmed"):
                self.send()
        with patch.object(
            self.sender, "send", side_effect=AssertionError("must not replay")
        ):
            result = self.broker.inspect()
        self.assertTrue(result["semantic"]["terminal"])
        self.assertEqual(len(self.receiver.page(after=0, limit=10)), 1)

    def test_wrong_route_and_payload_overrides_never_invoke_sdk(self):
        with patch.object(
            SignedGroupClient, "invoke", side_effect=AssertionError("must not invoke")
        ):
            for payload in (
                {"text": "x", "destination": self.target},
                {"text": "x", "scope": 0},
                {"text": ""},
            ):
                with self.assertRaises(MatrixExecutionError):
                    self.broker.submit(self.scope, payload, 1)
            with self.assertRaises(MatrixExecutionError):
                self.broker.submit(
                    replace(self.scope, thread=str(uuid.uuid4())), {"text": "x"}, 1
                )
        with patch.object(
            SignedGroupClient, "invoke", side_effect=AssertionError("must not invoke")
        ):
            with self.assertRaises(MatrixExecutionError):
                MatrixExecutionBroker(
                    self.broker._instruction,
                    canonical(self.broker._task),
                    SignedGroupClient(self.fixture, self.receiver),
                )
        invoke = SignedGroupClient.invoke
        methods = []

        def wrong_source(client, method, params):
            methods.append(method)
            if method == "runtime.status":
                return {}, {
                    "ok": True,
                    "result": {
                        "schema": "dm.runtime.status/v1",
                        "being_ref": self.receiver.lane.being_ref,
                        "local_origin": self.sender.ledger.local_origin,
                    },
                }
            return invoke(client, method, params)

        with patch.object(SignedGroupClient, "invoke", wrong_source):
            with self.assertRaises(MatrixExecutionError):
                self.send()
        self.assertEqual(methods, ["runtime.status"])
        result = self.send()
        for changes in (
            {"schema": "dm.tribe.delivery/v1"},
            {"destination": {}},
            {"author": {}},
            {"response_context": {}},
            {"message_hash": "invalid"},
        ):
            with self.assertRaises(MatrixExecutionError):
                self.broker._validate_result(result | changes)

    def test_existing_signed_execution_store_owns_admission_and_cancellation(self):
        state = store_fixtures.StoreTests()
        state.setUp()
        self.addCleanup(state.doCleanups)
        instruction = replace(self.broker._instruction, store_id=state.store.store_id)
        task = canonical(self.broker._task)
        # make_task already emits canonical JSON; task hash stays identical.
        broker = MatrixExecutionBroker(instruction, task, self.broker._client)
        runner = runner_fixtures.BoundedFakeRunner()
        runner.binding = instruction.binding
        controller = broker.controller(state.store, runner, monotonic=lambda: 10)
        self.assertIsNone(controller.run_due_once(instruction.instruction_id, 1, task))
        from daimon_matrix.execution_instruction import ExecutionDenied

        # Independently approved task with identical Scope but another recipient
        # must not be admitted through this broker's original route/provenance.
        alternate_task = make_task(
            "A different approved task",
            self.input_ref,
            self.scope,
            selected_destination={
                "kind": "being",
                "being_ref": self.sender.lane.being_ref,
            },
        )
        alternate = replace(
            instruction,
            instruction_id="review-2",
            task_sha256=hashlib.sha256(alternate_task.encode()).hexdigest(),
        )
        state.approve(alternate, "approval-other")
        with patch.object(
            SignedGroupClient, "invoke", side_effect=AssertionError("must not invoke")
        ):
            with self.assertRaises(ExecutionDenied):
                controller.run_due_once(alternate.instruction_id, 1, alternate_task)
        self.assertEqual(len(runner.starts), 0)
        state.approve(instruction)
        context = controller.run_due_once(instruction.instruction_id, 1, task)
        self.assertIsNotNone(context)
        result = context.native(
            self.scope, {"text": "Single approved synthetic request"}
        )
        self.assertTrue(result["semantic"]["terminal"])
        self.assertIsNone(controller.run_due_once(instruction.instruction_id, 1, task))
        from tests.test_execution_instruction import proof

        payload = state.store.cancellation_payload(instruction.instruction_id, 1)
        state.store.cancel(
            instruction.instruction_id, 1, proof(state.key, "cancel", payload, "cancel")
        )
        from daimon_matrix.execution_instruction import ExecutionDenied

        with self.assertRaises(ExecutionDenied):
            context.native(self.scope, {"text": "must not escape cancellation"})
        self.assertEqual(len(self.receiver.page(after=0, limit=10)), 1)


class AuthenticatedGroupHostTests(unittest.TestCase):
    def test_separate_capabilities_send_through_actual_authenticated_group_service(
        self,
    ):
        import socketserver
        import tempfile
        import threading

        from daimon_matrix.client import CLIENT_CONFIG_SCHEMA_V3
        from daimon_matrix.daemon import serve_connection
        from daimon_matrix.local_api import create_capability
        from daimon_matrix.service import HostedWeave, MessagingServiceContext

        sdk = AdapterTests()
        sdk.setUp()
        self.addCleanup(sdk.doCleanups)
        group = sdk.sender
        now = group.lane.clock()
        observe = create_capability(
            b"o" * 32,
            client_id="observe-test",
            methods=["runtime.status"],
            not_before_ms=now - 1000,
            not_after_ms=now + 60000,
        )
        messaging = create_capability(
            b"m" * 32,
            client_id="messaging-test",
            methods=["messaging.send", "messaging.delivery", "messaging.inbox"],
            not_before_ms=now - 1000,
            not_after_ms=now + 60000,
        )
        service = HostedWeave(
            ledger=group.ledger,
            signer=group.signer,
            capabilities={c.capability_id: c for c in (observe, messaging)},
            clock=group.lane.clock,
            runtime_id="dm:runtime:v1:" + "T" * 43,
            runtime_label="matrix-host-test",
            messaging=MessagingServiceContext(
                channels={"tribe": group},
                deliveries={"tribe": group},
                client_channels={messaging.client_id: frozenset({"tribe"})},
            ),
        )

        # Real owner-UID, frame/HMAC, service authorization and signed native
        # delivery; only the keys, recipient and operational clock are synthetic.
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                serve_connection(SimpleNamespace(service=service), self.request)

        class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sdk.sock"
            server = Server(str(path), Handler)
            path.chmod(0o600)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                source = {
                    "being_ref": group.lane.being_ref,
                    "embodiment_id": group.lane.local_embodiment_id,
                }
                references = {}
                for purpose, capability in (
                    ("messaging", messaging),
                    ("observation", observe),
                ):
                    config_path = Path(directory) / (purpose + ".json")
                    key_path = Path(directory) / (purpose + ".key")
                    config_path.write_text(
                        canonical(
                            {
                                "schema": CLIENT_CONFIG_SCHEMA_V3,
                                "capability": capability.descriptor,
                                "expected_server": group.ledger.local_origin,
                                "runtime_id": service.runtime_id,
                                "runtime_label": service.runtime_label,
                            }
                        )
                    )
                    key_path.write_bytes(capability.key)
                    config_path.chmod(0o600)
                    key_path.chmod(0o600)
                    references[purpose] = {
                        "socket": str(path),
                        "client_config": str(config_path),
                        "client_key": str(key_path),
                    }
                binding = Path(directory) / "host.json"
                binding.write_text(
                    canonical(
                        {
                            "schema": "telecodex.matrix-host-binding/v1",
                            "source": source,
                            **references,
                        }
                    )
                )
                binding.chmod(0o600)
                loaded = configured_client(binding, source)
                # Match the synthetic authority's fixed operational clock. No
                # verification, service authorization or socket I/O is mocked.
                host = replace(
                    loaded,
                    messaging=replace(loaded.messaging, clock=group.lane.clock),
                    observation=replace(loaded.observation, clock=group.lane.clock),
                )
                status = sdk.technical_status()
                outcome = operator_send({"status": status, "source": source}, host)
                transport = MatrixConversationTransport(status, source, host)
                sent = transport.inspect()
                self.assertEqual(
                    outcome["submission"]["message_id"], sent["message_id"]
                )
                self.assertEqual(
                    outcome["submission"]["destination"],
                    status["request"]["destination"],
                )
                for endpoint in sdk.fixture.servers:
                    endpoint._threads.join()
                message = sdk.receiver.message(sent["message_id"])
                relay = json.loads(message["payload"]["body"]["text"])
                self.assertEqual(relay["text"], status["request"]["original"]["text"])
                self.assertIsNone(relay["execution_ref"])
                self.assertEqual(sent["author"], source)
                self.assertEqual(transport.inspect()["message_id"], sent["message_id"])
                reply_scope = replace(sdk.scope, thread=sent["thread_id"],
                                      tool="messaging_reply", action="reply")
                reply = sdk.make_broker(sdk.receiver, reply_scope,
                                        task=make_received_task(message, reply_scope))
                returned = reply.submit(reply_scope, {"text": "Authenticated owner read."}, 1)
                retained = status | {"phase": "submitted", "claimed_source": source,
                                     "submission": outcome["submission"]}
                read = operator_receive({"status": retained, "source": source,
                                         "after": 0, "limit": 3}, host, timeout=1)
                self.assertEqual([r["message_id"] for r in read["results"]],
                                 [returned["message_id"]])
                self.assertEqual(read["results"][0]["text"], "Authenticated owner read.")
                incoming = operator_inbox({"source": source, "channel_id": "tribe",
                                           "after": 0, "limit": 3}, host, timeout=1)
                self.assertEqual(incoming["items"][0]["message_id"], returned["message_id"])
                self.assertEqual(incoming["items"][0]["text"],
                                 sdk.sender.message(returned["message_id"])["payload"]["body"]["text"])
                self.assertEqual(operator_receive({"status": retained, "source": source,
                                                   "after": read["next_cursor"], "limit": 3},
                                                  host, timeout=1)["results"], [])

            finally:
                server.shutdown()
                server.server_close()


class HostClientTests(unittest.TestCase):
    def setUp(self):
        self.fixture = client_fixtures.ClientFixture()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.addCleanup(self.fixture.tearDown)

    def test_separate_source_capability_uses_same_runtime_and_absolute_deadline(self):
        client = self.fixture.client()
        connections = []

        def observe(*args):
            connections.append(args)
            return nullcontext()

        observation = replace(client, connection_observer=observe)
        host = NativeOwnerClient(
            client, observation, deadline_ns=time.monotonic_ns() + 2_000_000_000
        )
        _, result = host.invoke("runtime.status", {})
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["schema"], "dm.runtime.status/v1")
        self.assertEqual(len(connections), 1)
        with self.assertRaisesRegex(MatrixExecutionError, "Unsupported technical"):
            host.invoke("scope.we", {})
        wrong = replace(
            client, config=replace(client.config, runtime_id="unselected-runtime")
        )
        with self.assertRaisesRegex(MatrixExecutionError, "one authenticated runtime"):
            NativeOwnerClient(client, wrong)
        wrong = replace(client, socket_path=client.socket_path.with_name("other.sock"))
        with self.assertRaisesRegex(MatrixExecutionError, "one authenticated runtime"):
            NativeOwnerClient(client, wrong)

    def test_owner_binding_rejects_observation_capability_for_messaging(self):
        root = self.fixture.state_root
        key = root / "host-test-capability.key"
        key.write_bytes(bytes(self.fixture.capability.key))
        key.chmod(0o600)
        reference = {
            "socket": str(self.fixture.runtime.socket_path),
            "client_config": str(self.fixture.config_path),
            "client_key": str(key),
        }
        source = {
            "being_ref": "dm:being:v1:" + "A" * 43,
            "embodiment_id": self.fixture.origins["legion"]["embodiment_id"],
        }
        path = root / "host-test-binding.json"
        path.write_text(
            canonical(
                {
                    "schema": "telecodex.matrix-host-binding/v1",
                    "source": source,
                    "messaging": reference,
                    "observation": reference,
                }
            )
        )
        path.chmod(0o600)
        with self.assertRaisesRegex(MatrixExecutionError, "messaging-only capability"):
            configured_client(path, source)
        with self.assertRaisesRegex(
            MatrixExecutionError, "differs from selected source"
        ):
            configured_client(path, {**source, "embodiment_id": "other-body"})


class AuthenticatedSourceTests(unittest.TestCase):
    def test_wrong_being_is_rejected_by_real_local_client_before_send(self):
        fixture = client_fixtures.ClientFixture()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.addCleanup(fixture.tearDown)
        client = fixture.client()
        scope = Scope("tribe", str(uuid.uuid4()), "messaging_send", "send")
        task = make_task(
            "Synthetic local source check",
            str(uuid.uuid4()),
            scope,
            selected_destination={
                "kind": "being",
                "being_ref": "dm:being:v1:" + "A" * 43,
            },
        )
        instruction = Instruction.from_dict(
            request(
                mode="manual",
                interval=None,
                max_cycles=1,
                being="dm:being:v1:" + "B" * 43,
                embodiment=client.config.expected_server["embodiment_id"],
                task_sha256=hashlib.sha256(task.encode()).hexdigest(),
                scope=[
                    {
                        k: getattr(scope, k)
                        for k in ("channel", "thread", "tool", "action")
                    }
                ],
            )
        )
        broker = MatrixExecutionBroker(instruction, task, client)
        from daimon_matrix.client import LocalClient

        invoke = LocalClient.invoke
        calls = []

        def observed(selected, method, params):
            calls.append(method)
            result = invoke(selected, method, params)
            self.assertTrue(result[1]["ok"])
            return result

        with patch.object(LocalClient, "invoke", observed):
            with self.assertRaises(MatrixExecutionError):
                broker.submit(scope, {"text": "Must never be authored"}, 1)
        self.assertEqual(calls, ["runtime.status"])


class TaskRelationTests(unittest.TestCase):
    def setUp(self):
        self.scope = Scope("tribe", str(uuid.uuid4()), "messaging_send", "send")
        self.target = {
            "kind": "body",
            "being_ref": "dm:being:v1:" + "A" * 43,
            "embodiment_id": "embodiment:selected",
        }
        self.parent = {
            "request": str(uuid.uuid4()),
            "binding": "c" * 64,
            "text": "Only the selected original.",
            "input_kind": "human_text",
        }

    def task(self, relation, context):
        return make_task(
            "The exact new original.",
            str(uuid.uuid4()),
            self.scope,
            selected_destination=self.target,
            relation=relation,
            context=context,
        )

    def test_relation_keeps_exact_selected_lineage_and_rejects_overrides(self):
        for kind in ("amends", "context"):
            selected = {"kind": kind, "requests": [self.parent["request"]]}
            task = self.task(selected, [self.parent])
            self.assertEqual(validate_task(task)["relation"], selected)
            for wrong in (
                None,
                {},
                {"kind": "unknown"},
                {"kind": "new"},
                {"kind": kind, "requests": []},
                {"kind": kind, "requests": [str(uuid.uuid4())]},
                {**selected, "selector": "unselected"},
            ):
                raw = json.loads(task)
                raw["relation"] = wrong
                with (
                    self.subTest(kind=kind, wrong=wrong),
                    self.assertRaises(MatrixExecutionError),
                ):
                    validate_task(canonical(raw))
        self.assertEqual(
            validate_task(self.task({"kind": "new"}, []))["relation"], {"kind": "new"}
        )
        with self.assertRaises(MatrixExecutionError):
            self.task({"kind": "new", "requests": []}, [])

    def test_relation_alone_also_reserves_serialized_relay_space(self):
        with self.assertRaisesRegex(MatrixExecutionError, "serialized relay"):
            make_task(
                "x" * 16000,
                str(uuid.uuid4()),
                self.scope,
                selected_destination=self.target,
                relation={"kind": "new"},
            )
        second = {**self.parent, "request": str(uuid.uuid4())}
        with self.assertRaisesRegex(MatrixExecutionError, "exact selected parents"):
            self.task(
                {
                    "kind": "amends",
                    "requests": [second["request"], self.parent["request"]],
                },
                [self.parent, second],
            )

    def test_legacy_task_without_relation_retains_its_exact_closed_shape(self):
        task = make_task(
            "Legacy selected work.",
            str(uuid.uuid4()),
            self.scope,
            selected_destination=self.target,
        )
        value = validate_task(task)
        self.assertEqual(
            set(value),
            {"schema", "question", "input_ref", "scope", "destination", "parent"},
        )
        self.assertEqual(task, canonical(value))


if __name__ == "__main__":
    unittest.main()
