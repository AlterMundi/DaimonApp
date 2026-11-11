#!/usr/bin/env python3
"""Owner-selected Matrix transport and reads; private binding, bounded JSON stdin.

No runtime is loaded outside its daemon, approval is signed, model is invoked
or uncertain native send retried. --receive reads one selected-thread page;
--inbox reads one selected channel page. Neither installs attention or reserves
model work. --native-owner is a separate, explicitly configured account-owner
pipe session over the existing signed work/journal; it never starts a model or
selects funding values. The controller owns execution and its resource contract.
"""

import argparse
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

from matrix_execution import (
    MAX_TEXT_BYTES,
    MatrixConversationReceipt,
    MatrixConversationTransport,
    MatrixExecutionError,
    canonical,
    closed,
    destination,
    identifier,
    strict_json,
)


def host_timeout():
    """Use the existing owner's remaining command budget after SDK startup."""
    value = os.environ.get("DAIMON_MATRIX_HOST_DEADLINE_MS")
    if value is None:
        return 10  # Compatible standalone invocation without an App deadline.
    if (not re.fullmatch(r"[1-9][0-9]{0,15}", value)):
        raise MatrixExecutionError("Invalid owner host deadline")
    remaining = (int(value) - time.time_ns() // 1_000_000) / 1000
    if not 0.05 <= remaining <= 60:
        raise MatrixExecutionError("Owner host deadline expired or unavailable")
    return remaining


@dataclass(frozen=True)
class NativeOwnerClient:
    """Separate existing purpose capabilities for one authenticated runtime."""

    messaging: object
    observation: object
    timeout_seconds: float = 10
    deadline_ns: int | None = None

    def __post_init__(self):
        if (
            self.messaging.config.expected_server
            != self.observation.config.expected_server
            or self.messaging.config.runtime_id != self.observation.config.runtime_id
            or self.messaging.socket_path != self.observation.socket_path
        ):
            raise MatrixExecutionError(
                "Select one authenticated runtime for both purposes"
            )

    @property
    def config(self):
        return self.messaging.config

    def invoke(self, method, params):
        if method == "runtime.status":
            client = self.observation
        elif method in (
            "messaging.send",
            "messaging.delivery",
            "messaging.reply",
            "messaging.inbox",
        ):
            client = self.messaging
        else:
            raise MatrixExecutionError("Unsupported technical host operation")
        return replace(
            client, timeout_seconds=self.timeout_seconds, deadline_ns=self.deadline_ns
        ).invoke(method, params)


@dataclass(frozen=True)
class EnrolledOwnerClient:
    """Existing signed messaging enrollment plus authenticated native responses."""

    messaging: object
    verified_source: dict
    timeout_seconds: float = 10
    deadline_ns: int | None = None
    intake_after: int = 0

    @property
    def config(self):
        return self.messaging.config

    def invoke(self, method, params):
        if method not in {"messaging.send", "messaging.reply", "messaging.inbox", "messaging.delivery"}:
            raise MatrixExecutionError("Unsupported technical host operation")
        return replace(self.messaging, timeout_seconds=self.timeout_seconds,
                       deadline_ns=self.deadline_ns).invoke(method, params)


def verified_enrollment(client, source, enrollment):
    """Verify public enrollment; never load a runtime, custody or private ledger."""
    from daimon_matrix.canonical import unb64url
    from daimon_matrix.messaging_config import protected_read, verify_public_binding

    value = closed(enrollment, ("application", "binding", "identity", "public_key"))
    for field in ("application", "binding"):
        if not isinstance(value[field], str) or not Path(value[field]).is_absolute():
            raise MatrixExecutionError("Owner-local absolute enrollment reference required")
    identity = value["identity"]
    if (not isinstance(identity, dict)
            or identity.get("runtime_id") != client.config.runtime_id
            or identity.get("runtime_label") != client.config.runtime_label
            or identity.get("origin") != dict(client.config.expected_server)
            or {"being_ref": identity.get("being_ref"),
                "embodiment_id": identity.get("origin", {}).get("embodiment_id")} != source):
        raise MatrixExecutionError("Signed enrollment differs from selected owner")
    application = strict_json(protected_read(value["application"]))
    binding = strict_json(protected_read(value["binding"]))
    verify_public_binding(identity, unb64url(value["public_key"], length=32), application, binding)
    if application.get("client", {}).get("descriptor") != client.config.capability.descriptor:
        raise MatrixExecutionError("Signed enrollment differs from active messaging client")
    return dict(source)


def configured_client(path, source, *, required_methods=("messaging.send",)):
    from daimon_matrix.client import ClientConfig, LocalClient
    from daimon_matrix.messaging_config import protected_read

    raw = strict_json(protected_read(path))
    enrolled = raw.get("schema") == "telecodex.matrix-host-binding/v2" if isinstance(raw, dict) else False
    names = ("schema", "messaging", "enrollment" if enrolled else "observation", "source")
    if enrolled and "intake_after" in raw:
        names += ("intake_after",)
    binding = closed(raw, names)
    intake_after = binding.get("intake_after", 0)
    if type(intake_after) is not int or not 0 <= intake_after <= 2**53 - 1:
        raise MatrixExecutionError("Bounded owner-selected initial inbox frontier required")
    if binding["schema"] not in {"telecodex.matrix-host-binding/v1", "telecodex.matrix-host-binding/v2"}:
        raise MatrixExecutionError("Explicit owner Matrix host binding required")
    if binding["source"] != source:
        raise MatrixExecutionError("Owner binding differs from selected source")

    def load(value):
        closed(value, ("socket", "client_config", "client_key"))
        for field in value:
            if (
                not isinstance(value[field], str)
                or not Path(value[field]).is_absolute()
            ):
                raise MatrixExecutionError(
                    "Owner-local absolute SDK reference required"
                )
        config = ClientConfig.load(
            Path(value["client_config"]),
            protected_read(Path(value["client_key"]), size=32),
        )
        return LocalClient(Path(value["socket"]), config)

    messaging = load(binding["messaging"])
    methods = set(messaging.config.capability.methods)
    if not set(required_methods) <= methods or not methods <= {
        "messaging.send",
        "messaging.reply",
        "messaging.inbox",
        "messaging.delivery",
    }:
        raise MatrixExecutionError("Existing messaging-only capability required")
    if enrolled:
        return EnrolledOwnerClient(messaging, verified_enrollment(messaging, source, binding["enrollment"]),
                                   intake_after=intake_after)
    observation = load(binding["observation"])
    if "runtime.status" not in observation.config.capability.methods:
        raise MatrixExecutionError("Existing source observation capability required")
    return NativeOwnerClient(messaging, observation)


def send(value, client, *, timeout=10, coordination=None):
    """Trusted controller snapshot plus already authenticated client; no runner."""
    closed(value, ("status", "source"))
    transport = MatrixConversationTransport(
        value["status"], value["source"], client, coordination=coordination
    )
    native = transport.send(timeout=timeout)
    request = value["status"]["request"]
    # The SDK authenticates the resolved destination (including its authority
    # metadata). The controller retains only its selected social recipient plus
    # native correlation IDs; signed wire evidence remains in the SDK journal.
    submission = {
        key: native[key]
        for key in ("send_id", "message_id", "message_hash", "thread_id", "author")
    }
    submission["destination"] = request["destination"]
    return {
        "schema": "telecodex.matrix-transport-outcome/v1",
        "request": request["id"],
        "binding": request["binding"],
        "submission": submission,
    }


def receive(value, client, *, timeout=10):
    """Explicit owner inspection only; callbacks are retained by the caller."""
    closed(value, ("status", "source", "after", "limit"))
    if value["source"] != value["status"].get("claimed_source"):
        raise MatrixExecutionError("Selected reader differs from retained source")
    return MatrixConversationReceipt(value["status"], client).read_replies(
        after=value["after"],
        limit=value["limit"],
        timeout=timeout,
    )


def inbox(value, client, *, timeout=10, intake_window=True):
    """One selected authenticated channel page; never send, poll or run a model.

    The native SDK verifies signatures and current audience. This projection
    preserves source identities; it is not an independent signature verifier,
    human original, receiving execution approval or evidence of a response.
    """
    closed(value, ("source", "channel_id", "after", "limit"))
    source = closed(value["source"], ("being_ref", "embodiment_id"))
    destination({"kind": "body", **source})
    after, limit, channel = value["after"], value["limit"], value["channel_id"]
    if (
        type(after) is not int
        or not 0 <= after <= 2**53 - 1
        or type(limit) is not int
        or not 1 <= limit <= 3
        or not isinstance(channel, str)
        or not 1 <= len(channel) <= 128
        or type(timeout) not in (int, float)
        or not math.isfinite(timeout)
        or not 0.05 <= timeout <= 60
        or client.config.expected_server.get("embodiment_id") != source["embodiment_id"]
    ):
        raise MatrixExecutionError("Bounded owner-selected inbox page required")
    deadline = time.monotonic_ns() + int(timeout * 1_000_000_000)
    if client.deadline_ns is not None:
        deadline = min(deadline, client.deadline_ns)
    selected = replace(client, timeout_seconds=timeout, deadline_ns=deadline)
    if isinstance(selected, EnrolledOwnerClient):
        if selected.verified_source != source:
            raise MatrixExecutionError("Authenticated inbox owner changed")
    else:
        _, observed = selected.invoke("runtime.status", {})
        runtime = observed.get("result", {}) if observed.get("ok") is True else {}
        if (
            runtime.get("schema") != "dm.runtime.status/v1"
            or runtime.get("being_ref") != source["being_ref"]
            or runtime.get("local_origin", {}).get("embodiment_id") != source["embodiment_id"]
        ):
            raise MatrixExecutionError("Authenticated inbox owner changed")
    native_after = after
    if isinstance(selected, EnrolledOwnerClient) and intake_window:
        if after == 0:
            native_after = selected.intake_after
        elif after < selected.intake_after:
            raise MatrixExecutionError("Initial inbox window cannot rebase an existing cursor")
    _, response = selected.invoke(
        "messaging.inbox",
        {
            "channel_id": channel,
            "after": native_after,
            "limit": limit,
        },
    )
    page = response.get("result", {}) if response.get("ok") is True else {}
    if (
        page.get("channel_id") != channel
        or not isinstance(page.get("items"), list)
        or len(page["items"]) > limit
    ):
        raise MatrixExecutionError("Authenticated selected inbox page required")
    cursor, items = after, []
    for row in page["items"]:
        sequence, message = row["inbox_sequence"], row["message"]
        if type(sequence) is not int or not max(cursor, native_after) < sequence <= 2**53 - 1:
            raise MatrixExecutionError("Inbox cursor is not monotonic")
        author = {
            "being_ref": message["being_ref"],
            "embodiment_id": message["origin"]["embodiment_id"],
        }
        destination({"kind": "body", **author})
        digest = message["content_hash"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise MatrixExecutionError("Immutable native message digest required")
        body = message["payload"]["body"]
        raw = body.get("text")
        available = (
            isinstance(raw, str)
            and bool(raw.strip())
            and len(raw.encode()) <= MAX_TEXT_BYTES
        )
        items.append(
            {
                "inbox_sequence": sequence,
                "message_id": identifier(message["event_id"]),
                "message_hash": digest,
                "author": author,
                "thread_id": identifier(message["payload"]["intent"]["thread_id"]),
                "destination": body.get("destination"),
                "response_context": body.get("response_context"),
                "coordination": body.get("coordination"),
                "text": raw if available else None,
                "state": "available" if available else "unsupported_payload",
            }
        )
        cursor = sequence
    result = {
        "schema": "daimon.matrix-inbox-page/v1",
        "source": source,
        "channel_id": channel,
        "after": after,
        "next_cursor": cursor,
        "items": items,
        "page_full": len(page["items"]) == limit,
        "meaning": "SDK-authenticated peer source, never human speech or execution authority",
    }
    if native_after != after:
        result["meaning"] = ("SDK-authenticated owner-selected intake after native frontier "
                             + str(native_after) + "; after/next_cursor are consumer cursors. "
                             "Earlier originals remain in native history; no review is claimed.")
    if len(canonical(result).encode()) > 65536:
        raise MatrixExecutionError(
            "Bounded inbox projection required; cursor not advanced"
        )
    return result


def respond(value, client, *, timeout=10, inspect_only=False):
    """Execute/inspect one already retained response intent, never make a new one.

    The application must persist its intent before invoking this adapter. Native
    Matrix retains the send identity, verifies the parent and determines the
    group/direct audience. A failed/ambiguous result is never retried here.
    """
    closed(
        value,
        ("source", "channel_id", "parent", "send_id", "text", "effect_not_after_ms"),
    )
    parent = value["parent"]
    if not isinstance(parent, dict):
        raise MatrixExecutionError("Retained native parent required")
    sequence = parent.get("inbox_sequence")
    identifier(parent.get("message_id"))
    identifier(parent.get("thread_id"))
    identifier(value["send_id"])
    closed(value["source"], ("being_ref", "embodiment_id"))
    destination({"kind": "body", **value["source"]})
    if (
        type(sequence) is not int
        or not 1 <= sequence <= 2**53 - 1
        or type(value["effect_not_after_ms"]) is not int
        or value["effect_not_after_ms"] <= 0
        or not isinstance(value["text"], str)
        or not value["text"].strip()
        or len(value["text"].encode()) > MAX_TEXT_BYTES
        or type(timeout) not in (int, float)
        or not math.isfinite(timeout)
        or not 0.05 <= timeout <= 60
    ):
        raise MatrixExecutionError("Bounded retained response intent required")
    # Reuse the same owner/signature/audience reader and absolute deadline. A
    # group parent is valid: do not apply the directed-only private-relay helper.
    deadline = time.monotonic_ns() + int(timeout * 1_000_000_000)
    selected = replace(client, timeout_seconds=timeout, deadline_ns=deadline)
    if not inspect_only:
        page = inbox(
            {
                "source": value["source"],
                "channel_id": value["channel_id"],
                "after": sequence - 1,
                "limit": 1,
            },
            selected,
            timeout=timeout, intake_window=False,
        )
        if page["items"] != [parent]:
            raise MatrixExecutionError(
                "Selected native original differs from retained parent"
            )
        method = "messaging.reply"
        params = {
            "channel_id": value["channel_id"],
            "received_channel_id": value["channel_id"],
            "message_id": parent["message_id"],
            "send_id": value["send_id"],
            "text": value["text"],
            "effect_not_after_ms": value["effect_not_after_ms"],
        }
    else:
        # Inspection cannot author or replay, including after the authoring
        # deadline. Still bind the observation to the actual current body.
        if isinstance(selected, EnrolledOwnerClient):
            if selected.verified_source != value["source"]:
                raise MatrixExecutionError("Authenticated response owner changed")
        else:
            _, observed = selected.invoke("runtime.status", {})
            status = observed.get("result", {}) if observed.get("ok") is True else {}
            if (status.get("being_ref") != value["source"]["being_ref"]
                    or status.get("local_origin", {}).get("embodiment_id") != value["source"]["embodiment_id"]):
                raise MatrixExecutionError("Authenticated response owner changed")
        method = "messaging.delivery"
        params = {"channel_id": value["channel_id"], "send_id": value["send_id"]}
    _, response = selected.invoke(method, params)
    result = response.get("result", {}) if response.get("ok") is True else {}
    expected_parent = {
        "message_id": parent["message_id"],
        "message_hash": parent["message_hash"],
        "sender_being_ref": parent["author"]["being_ref"],
        "sender_embodiment_id": parent["author"]["embodiment_id"],
    }
    if (
        result.get("schema")
        not in ("dm.tribe.delivery/v1", "dm.tribe.direct-delivery/v1")
        or result.get("send_id") != value["send_id"]
        or result.get("author") != value["source"]
        or result.get("thread_id") != parent["thread_id"]
        or result.get("response_context") != expected_parent
    ):
        raise MatrixExecutionError("Native response differs from retained intent")
    identifier(result.get("message_id"))
    if not isinstance(result.get("message_hash"), str) or not re.fullmatch(
        r"[0-9a-f]{64}", result["message_hash"]
    ):
        raise MatrixExecutionError("Immutable response digest required")
    original_destination = parent.get("destination")
    if original_destination is None:
        if result.get("destination") is not None:
            raise MatrixExecutionError(
                "A group reply cannot silently narrow its audience"
            )
    else:
        kind = original_destination.get("kind")
        expected = {"kind": kind, "being_ref": parent["author"]["being_ref"]}
        if kind == "body":
            expected["embodiment_id"] = parent["author"]["embodiment_id"]
        destination(expected)
        if not isinstance(result.get("destination"), dict) or any(
            result["destination"].get(k) != v for k, v in expected.items()
        ):
            raise MatrixExecutionError(
                "A direct reply must preserve its native recipient kind"
            )
    output = {
        "schema": "daimon.matrix-response-outcome/v1",
        "send_id": value["send_id"],
        "parent_message_id": parent["message_id"],
        "delivery": result,
        "meaning": "Native authored/receipt evidence, not model incorporation, task completion or human hearing",
    }
    if len(canonical(output).encode()) > 65536:
        raise MatrixExecutionError(
            "Bounded response receipt required; inspect retained native outcome"
        )
    return output


def native_owner_session(value, client, selection_path, *, clock=time.time, monotonic=time.monotonic):
    """Run the selected private account binding in this existing host process."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from daimon_matrix.execution_instruction import ApprovalVerifier
    from daimon_matrix.execution_store import ExecutionStore
    from daimon_matrix.messaging_config import protected_read
    from daimon_matrix.review_runner import ProviderCostBound
    from matrix_execution import prepare_native_account_owner, serve_native_account_owner

    closed(value, ("source", "channel_id", "message_id", "inbox_sequence", "thread_id", "parent_allowance", "provider", "model", "message_hash", "local_execution_id"))
    selection = closed(strict_json(protected_read(selection_path)), (
        "schema", "store", "trust", "usage_trust", "instruction_id", "revision",
        "task", "cost_bound", "cost_proof", "registration",
    ))
    if selection["schema"] != "telecodex.native-funding-binding/v1":
        raise MatrixExecutionError("Selected native funding binding required")
    for name in ("store", "trust", "usage_trust"):
        if not isinstance(selection[name], str) or not Path(selection[name]).is_absolute():
            raise MatrixExecutionError("Owner-selected absolute accounting reference required")

    def trust(path):
        keys = strict_json(protected_read(Path(path)))
        return ApprovalVerifier({principal: Ed25519PublicKey.from_public_bytes(bytes.fromhex(key))
                                 for principal, key in keys.items()})

    approval = trust(selection["trust"])
    store = ExecutionStore(Path(selection["store"]), approval, clock=clock,
                           usage_verifier=trust(selection["usage_trust"]))
    instruction = store.get_instruction(selection["instruction_id"], selection["revision"])
    bound = ProviderCostBound.verify(selection["cost_bound"], selection["cost_proof"], approval)
    if value["model"] != instruction.model or value["provider"] != instruction.provider:
        raise MatrixExecutionError("Native model selection differs from the signed cost binding")
    identifier(value["message_id"])
    if (not isinstance(value["message_hash"], str)
            or len(value["message_hash"]) != 64
            or any(c not in "0123456789abcdef" for c in value["message_hash"])
            or type(value["local_execution_id"]) is not int
            or value["local_execution_id"] < 1):
        raise MatrixExecutionError("Retained native source hash and execution required")
    closed(value["source"], ("being_ref", "embodiment_id"))
    if (value["source"] != {"being_ref": instruction.being, "embodiment_id": instruction.embodiment}
            or value["channel_id"] not in {scope.channel for scope in instruction.scope}
            or type(value["inbox_sequence"]) is not int or value["inbox_sequence"] < 1):
        raise MatrixExecutionError("Selected current original binding required")
    parent = closed(value["parent_allowance"], ("maxProviderAttempts", "maxRequestBytes", "deadlineUnixMs"))
    if (not all(type(item) is int and item > 0 for item in parent.values())
            or not 0 < parent["deadlineUnixMs"] - int(clock() * 1000) <= 600000):
        raise MatrixExecutionError("Original bounded native horizon required")
    deadline = time.monotonic_ns() + int((parent["deadlineUnixMs"] / 1000 - clock()) * 1e9)

    def read(message_id):
        if message_id != value["message_id"]:
            raise MatrixExecutionError("Only the selected original may be read")
        remaining = min(client.timeout_seconds, (deadline - time.monotonic_ns()) / 1e9)
        if remaining < 0.05:
            raise MatrixExecutionError("Native source deadline expired")
        current = replace(client, timeout_seconds=remaining, deadline_ns=deadline)
        # Reuse current owner qualification and SDK authentication; preserve the
        # raw signed event for the existing queue's immutable-source digest.
        if isinstance(current, EnrolledOwnerClient):
            if current.verified_source != value["source"]:
                raise MatrixExecutionError("Native source owner changed")
        else:
            _, observed = current.invoke("runtime.status", {})
            runtime = observed.get("result", {}) if observed.get("ok") is True else {}
            if (runtime.get("being_ref") != instruction.being
                    or runtime.get("local_origin", {}).get("embodiment_id") != instruction.embodiment):
                raise MatrixExecutionError("Native source owner changed")
        _, response = current.invoke("messaging.inbox", dict(
            channel_id=value["channel_id"], after=value["inbox_sequence"] - 1, limit=1))
        page = response.get("result", {}) if response.get("ok") is True else {}
        rows = page.get("items")
        if (page.get("channel_id") != value["channel_id"] or not isinstance(rows, list)
                or len(rows) != 1 or rows[0].get("inbox_sequence") != value["inbox_sequence"]
                or rows[0].get("message", {}).get("event_id") != message_id
                or rows[0].get("message", {}).get("content_hash") != value["message_hash"]):
            raise MatrixExecutionError("Current authenticated original unavailable")
        return rows[0]["message"]

    work_id = store.enqueue_coordination(value["message_id"], read)
    if work_id is None:
        raise MatrixExecutionError("Original is not eligible for the selected funded work")
    owner = prepare_native_account_owner(
        store, instruction, selection["task"], thread_id=value["thread_id"],
        parent_allowance=parent, cost_bound=bound, registration=selection["registration"],
        work_id=work_id, read_message=read, monotonic=monotonic,
    )
    serve_native_account_owner(owner, sys.stdin.fileno(), sys.stdout.fileno())


def read_native_owner_start():
    # Startup is bounded independently; the selected parent's original absolute
    # deadline then covers SDK reads and every session frame. Never read to EOF.
    import selectors
    deadline = time.monotonic() + host_timeout()
    raw = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(sys.stdin.fileno(), selectors.EVENT_READ)
        while b"\n" not in raw:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise MatrixExecutionError("Native owner startup deadline expired")
            chunk = os.read(sys.stdin.fileno(), min(4096, 65537 - len(raw)))
            if not chunk:
                raise MatrixExecutionError("Native owner startup pipe closed")
            raw.extend(chunk)
            if len(raw) > 65536:
                raise MatrixExecutionError("Native owner startup exceeds bound")
    if raw[-1:] != b"\n" or raw.count(b"\n") != 1:
        raise MatrixExecutionError("One sequential native owner start required")
    return strict_json(raw)


def receiving_command(
    connection,
    binding,
    *,
    receive_only=False,
    inbox_only=False,
    respond_only=False,
    response_status_only=False,
    native_owner_only=False,
    funding_binding=None,
):
    """Bootstrap this host module in the existing receiving owner's SDK context.

    This is owner configuration, never request/model JSON. Read the current
    native connection each invocation so an SDK successor cannot leave a cached
    host interpreter/import selection. Do not execute a connection's code string.
    """
    if sum((receive_only, inbox_only, respond_only, response_status_only, native_owner_only)) > 1:
        raise MatrixExecutionError("Select one host mode")
    with connection.open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise MatrixExecutionError("Bounded receiving connection required")
    value = strict_json(raw)
    command = value.get("command") if isinstance(value, dict) else None
    if (
        not isinstance(command, list)
        or len(command) != 16
        or any(
            not isinstance(item, str) or not item or len(item) > 8192
            for item in command
        )
        or command[1:5] != ["-B", "-I", "-S", "-c"]
        or command[9] != "clusterctl.onboarding_owner_client"
        or command[10] != "--code-digest"
        or command[12] != "--code-owner"
        or command[14] != "--binding"
        or len(command[11]) != 64
        or any(c not in "0123456789abcdef" for c in command[11])
        or not command[13].isdigit()
        or any(
            not Path(item).is_absolute() or ".." in Path(item).parts
            for item in (command[0], *command[6:9])
        )
    ):
        raise MatrixExecutionError("Supported receiving owner context required")
    if native_owner_only and funding_binding is None:
        raise MatrixExecutionError("Native owner requires private funding binding")
    script = str(Path(__file__).resolve())
    bootstrap = (
        "import os,sys,runpy\n"
        "venv,imports,code,code_digest,code_uid,script,binding,receive_mode,*extra=sys.argv[1:]\n"
        "sys.prefix=sys.exec_prefix=venv\n"
        "sys.path[:0]=[code,imports]\n"
        "sys.dont_write_bytecode=True\n"
        "sys.pycache_prefix=imports+'/.disabled-bytecode'\n"
        "from pathlib import Path\n"
        "try:\n"
        " from clusterctl import onboarding_sdk,onboarding_code_successor\n"
        " parameters=onboarding_code_successor.sdk_parameters(Path(code),uid=int(code_uid))\n"
        " if not parameters: raise RuntimeError('qualified receiving SDK required')\n"
        " onboarding_sdk.qualified_startup(Path(venv),Path(code),code_digest=code_digest,code_uid=int(code_uid),**parameters)\n"
        "except Exception as error:\n"
        " import json\n"
        " print(json.dumps({'error':type(error).__name__}),file=sys.stderr)\n"
        " raise SystemExit(1)\n"
        "sys.path.insert(0,os.path.dirname(script))\n"
        "sys.argv=[script,'--binding',binding]+({'receive':['--receive'],'inbox':['--inbox'],'respond':['--respond'],'response-status':['--response-status'],'native-owner':['--native-owner'],'send':[]}[receive_mode])+extra\n"
        "runpy.run_path(script,run_name='__main__')\n"
    )
    return [
        command[0],
        "-B",
        "-I",
        "-S",
        "-c",
        bootstrap,
        *command[6:9],
        command[11],
        command[13],
        script,
        str(binding),
        "native-owner"
        if native_owner_only
        else "respond"
        if respond_only
        else "response-status"
        if response_status_only
        else "inbox"
        if inbox_only
        else "receive"
        if receive_only
        else "send",
    ] + (["--funding-binding", str(funding_binding)] if native_owner_only else [])


def main(*, clock=time.time, monotonic=time.monotonic):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument(
        "--native-connection",
        type=Path,
        help="Current owner-local receiving SDK connection; no model/request selection",
    )
    parser.add_argument("--funding-binding", type=Path,
                        help="Private operator-selected native accounting binding")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--native-owner", action="store_true",
                       help="One bounded native account-owner pipe session")
    modes.add_argument(
        "--receive",
        action="store_true",
        help="Inspect one retained selected reply page; never send",
    )
    modes.add_argument(
        "--inbox",
        action="store_true",
        help="Read one owner-selected new-message page; never send",
    )
    modes.add_argument(
        "--respond",
        action="store_true",
        help="Submit one owner-retained response intent",
    )
    modes.add_argument(
        "--response-status",
        action="store_true",
        help="Inspect that retained intent; never send",
    )
    args = parser.parse_args()
    if args.native_connection is not None:
        command = receiving_command(
            args.native_connection,
            args.binding,
            receive_only=args.receive,
            inbox_only=args.inbox,
            respond_only=args.respond,
            response_status_only=args.response_status,
            native_owner_only=args.native_owner, funding_binding=args.funding_binding,
        )
        os.execv(command[0], command)
    if args.native_owner:
        if args.funding_binding is None:
            raise MatrixExecutionError("Private native funding binding required")
        value = read_native_owner_start()
        client = configured_client(args.binding, value["source"], required_methods=("messaging.inbox",))
        native_owner_session(value, client, args.funding_binding, clock=clock, monotonic=monotonic)
        return
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        raise MatrixExecutionError("Bounded controller status required")
    value = closed(
        strict_json(raw),
        ("source", "channel_id", "parent", "send_id", "text", "effect_not_after_ms")
        if args.respond or args.response_status
        else ("source", "channel_id", "after", "limit")
        if args.inbox
        else ("status", "source", "after", "limit")
        if args.receive
        else ("status", "source"),
    )
    operation = (
        (
            lambda value, client, timeout: respond(
                value, client, timeout=timeout, inspect_only=args.response_status
            )
        )
        if args.respond or args.response_status
        else inbox
        if args.inbox
        else receive
        if args.receive
        else send
    )
    required = (
        ("messaging.inbox", "messaging.reply")
        if args.respond
        else ("messaging.delivery",)
        if args.response_status
        else ("messaging.inbox",)
        if args.inbox
        else ("messaging.inbox", "messaging.delivery")
        if args.receive
        else ("messaging.send",)
    )
    client = configured_client(args.binding, value["source"], required_methods=required)
    result = operation(value, client, timeout=host_timeout())
    output = canonical(result)
    if len(output.encode()) > 65536:
        raise MatrixExecutionError("Bounded host outcome required")
    print(output)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Credentials, original text, local paths and SDK diagnostics stay local.
        print(json.dumps({"error": type(error).__name__}), file=sys.stderr)
        raise SystemExit(1)
