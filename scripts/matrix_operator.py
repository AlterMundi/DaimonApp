#!/usr/bin/env python3
"""One selected technical Matrix send; private owner binding, bounded JSON stdin.

No runtime is loaded outside its daemon, inbox is read, approval is signed, model
is invoked or uncertain native send retried. The controller owns its reservation.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from matrix_execution import (
    MatrixConversationTransport,
    MatrixExecutionError,
    canonical,
    closed,
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
        elif method in ("messaging.send", "messaging.delivery", "messaging.reply"):
            client = self.messaging
        else:
            raise MatrixExecutionError("Unsupported technical host operation")
        return replace(
            client, timeout_seconds=self.timeout_seconds, deadline_ns=self.deadline_ns
        ).invoke(method, params)


def configured_client(path, source):
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
    if "messaging.send" not in methods or not methods <= {
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


def receiving_command(connection, binding):
    """Bootstrap this host module in the existing receiving owner's SDK context.

    This is owner configuration, never request/model JSON. Read the current
    native connection each invocation so an SDK successor cannot leave a cached
    host interpreter/import selection. Do not execute a connection's code string.
    """
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
        "venv,imports,code,code_digest,code_uid,script,binding=sys.argv[1:]\n"
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
        "sys.argv=[script,'--binding',binding]\n"
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
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument(
        "--native-connection",
        type=Path,
        help="Current owner-local receiving SDK connection; no model/request selection",
    )
    args = parser.parse_args()
    if args.native_connection is not None:
        command = receiving_command(args.native_connection, args.binding)
        os.execv(command[0], command)
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        raise MatrixExecutionError("Bounded controller status required")
    value = closed(strict_json(raw), ("status", "source"))
    result = send(value, configured_client(args.binding, value["source"]))
    print(canonical(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Credentials, original text, local paths and SDK diagnostics stay local.
        print(json.dumps({"error": type(error).__name__}), file=sys.stderr)
        raise SystemExit(1)
