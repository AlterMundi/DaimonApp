#!/usr/bin/env python3
"""Owner-selected Matrix transport and reads; private binding, bounded JSON stdin.

No runtime is loaded outside its daemon, approval is signed, model is invoked
or uncertain native send retried. --receive reads one selected-thread page;
--inbox reads one selected channel page. Neither installs attention or reserves
model work. The controller owns execution and its finite producer contract.
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


def configured_client(path, source, *, required_methods=("messaging.send",)):
    from daimon_matrix.client import ClientConfig, LocalClient
    from daimon_matrix.messaging_config import protected_read

    binding = closed(
        strict_json(protected_read(path)),
        ("schema", "messaging", "observation", "source"),
    )
    if binding["schema"] != "telecodex.matrix-host-binding/v1":
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

    messaging, observation = load(binding["messaging"]), load(binding["observation"])
    methods = set(messaging.config.capability.methods)
    if not set(required_methods) <= methods or not methods <= {
        "messaging.send",
        "messaging.reply",
        "messaging.inbox",
        "messaging.delivery",
    }:
        raise MatrixExecutionError("Existing messaging-only capability required")
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


def inbox(value, client, *, timeout=10):
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
    selected = replace(client, timeout_seconds=timeout, deadline_ns=deadline)
    _, observed = selected.invoke("runtime.status", {})
    runtime = observed.get("result", {}) if observed.get("ok") is True else {}
    if (
        runtime.get("schema") != "dm.runtime.status/v1"
        or runtime.get("being_ref") != source["being_ref"]
        or runtime.get("local_origin", {}).get("embodiment_id")
        != source["embodiment_id"]
    ):
        raise MatrixExecutionError("Authenticated inbox owner changed")
    _, response = selected.invoke(
        "messaging.inbox",
        {
            "channel_id": channel,
            "after": after,
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
        if type(sequence) is not int or not cursor < sequence <= 2**53 - 1:
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
    if len(canonical(result).encode()) > 65536:
        raise MatrixExecutionError(
            "Bounded inbox projection required; cursor not advanced"
        )
    return result


def receiving_command(connection, binding, *, receive_only=False, inbox_only=False):
    """Bootstrap this host module in the existing receiving owner's SDK context.

    This is owner configuration, never request/model JSON. Read the current
    native connection each invocation so an SDK successor cannot leave a cached
    host interpreter/import selection. Do not execute a connection's code string.
    """
    if receive_only and inbox_only:
        raise MatrixExecutionError("Select one read mode")
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
    script = str(Path(__file__).resolve())
    bootstrap = (
        "import os,sys,runpy\n"
        "venv,imports,code,code_digest,code_uid,script,binding,receive_mode=sys.argv[1:]\n"
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
        "sys.argv=[script,'--binding',binding]+({'receive':['--receive'],'inbox':['--inbox'],'send':[]}[receive_mode])\n"
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
        "inbox" if inbox_only else "receive" if receive_only else "send",
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument(
        "--native-connection",
        type=Path,
        help="Current owner-local receiving SDK connection; no model/request selection",
    )
    modes = parser.add_mutually_exclusive_group()
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
    args = parser.parse_args()
    if args.native_connection is not None:
        command = receiving_command(
            args.native_connection,
            args.binding,
            receive_only=args.receive,
            inbox_only=args.inbox,
        )
        os.execv(command[0], command)
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        raise MatrixExecutionError("Bounded controller status required")
    value = closed(
        strict_json(raw),
        ("source", "channel_id", "after", "limit")
        if args.inbox
        else ("status", "source", "after", "limit")
        if args.receive
        else ("status", "source"),
    )
    operation = inbox if args.inbox else receive if args.receive else send
    required = (
        ("messaging.inbox",)
        if args.inbox
        else ("messaging.inbox", "messaging.delivery")
        if args.receive
        else ("messaging.send",)
    )
    result = operation(
        value,
        configured_client(args.binding, value["source"], required_methods=required),
    )
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
