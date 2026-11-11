"""Host adapters over the existing signed Matrix execution journal and SDK.

Ordinary technical relays do not activate models. Explicitly selected native
account owners retain the existing work capability for one bounded pipe session;
legacy one-call reviews keep their existing controller. No new balance journal,
signer, scheduler or background attention is created. SDK journals own send
identity/receipts; ExecutionStore owns approval, fuel, charges and uncertainty.
These host functions are neither model tools nor an OS isolation boundary.
Real account/route/exposure/usage and credential isolation need qualification;
source preparation alone selects no account, budget or paid native execution.
"""

import hashlib
import json
import math
import re
import time
import uuid
from dataclasses import fields, is_dataclass, replace

TASK_SCHEMA = "telecodex.matrix-task/v1"
RELAY_SCHEMA = "telecodex.matrix-relay/v1"
MAX_TEXT_BYTES = 16384


class MatrixExecutionError(ValueError):
    pass


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def strict_json(text):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise MatrixExecutionError("Duplicate JSON member")
            result[key] = value
        return result

    try:
        return json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (ValueError, TypeError) as error:
        raise MatrixExecutionError("Closed JSON required") from error


def closed(value, names):
    if not isinstance(value, dict) or set(value) != set(names):
        raise MatrixExecutionError("Closed routing selection required")
    return value


def identifier(value):
    try:
        valid = isinstance(value, str) and str(uuid.UUID(value)) == value
    except ValueError:
        valid = False
    if not valid:
        raise MatrixExecutionError("Canonical UUID required")
    return value


def text(value, maximum=MAX_TEXT_BYTES):
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > maximum:
        raise MatrixExecutionError("Bounded nonempty text required")
    return value


def destination(value):
    if not isinstance(value, dict) or value.get("kind") not in ("being", "body"):
        raise MatrixExecutionError("Select an explicit Matrix recipient")
    closed(
        value,
        ("kind", "being_ref", "embodiment_id")
        if value["kind"] == "body"
        else ("kind", "being_ref"),
    )
    if not isinstance(value["being_ref"], str) or not re.fullmatch(
        r"dm:being:v1:[A-Za-z0-9_-]{43}", value["being_ref"]
    ):
        raise MatrixExecutionError("Signed being reference required")
    if value["kind"] == "body":
        text(value["embodiment_id"], 240)
    return dict(value)


def parent_from_verified_sdk(message):
    """Call only on an SDK-authenticated selected message, never wire/model JSON.

    The SDK retains/verifies signatures and audience. Extracting these fields is
    not independent signature validation or execution approval.
    """
    selected = message["payload"]["body"].get("destination")
    if not isinstance(selected, dict):
        raise MatrixExecutionError("A directed parent is required for a private return")
    selected = {
        key: selected[key]
        for key in (
            ("kind", "being_ref", "embodiment_id")
            if selected.get("kind") == "body"
            else ("kind", "being_ref")
        )
    }
    destination(selected)
    return {
        "destination": selected,
        "message_id": identifier(message["event_id"]),
        "message_hash": message["content_hash"],
        "sender_being_ref": message["being_ref"],
        "sender_embodiment_id": message["origin"]["embodiment_id"],
        "thread_id": identifier(message["payload"]["intent"]["thread_id"]),
    }


def request_relation(value, context):
    """Retain selected lineage; this data never supplies execution authority."""
    if not isinstance(value, dict):
        raise MatrixExecutionError("Explicit request relation object required")
    kind = value.get("kind")
    if kind == "new":
        closed(value, ("kind",))
        if context:
            raise MatrixExecutionError("A new relation cannot claim selected parents")
    elif kind in ("amends", "context"):
        closed(value, ("kind", "requests"))
        if not context or value["requests"] != [row["request"] for row in context]:
            raise MatrixExecutionError(
                "Relation must retain the exact selected parents"
            )
    else:
        raise MatrixExecutionError("Unsupported selected request relation")
    return value


def validate_task(task):
    parsed = strict_json(task)
    names = ("schema", "question", "input_ref", "scope", "destination", "parent")
    value = closed(
        parsed,
        names
        + tuple(
            key
            for key in ("origin", "context", "input_kind", "relation")
            if isinstance(parsed, dict) and key in parsed
        ),
    )
    text(value["question"])
    kinds = ("human_text", "committed_machine_transcript", "session_authored")
    if value.get("input_kind", "session_authored") not in kinds:
        raise MatrixExecutionError("Explicit input authorship kind required")
    context = value.get("context", [])
    if not isinstance(context, list) or len(context) > 4:
        raise MatrixExecutionError("Bounded selected parent context required")
    size = len(value["question"].encode())
    seen = set()
    for row in context:
        closed(row, ("request", "binding", "text", "input_kind"))
        identifier(row["request"])
        if row["request"] in seen or row["input_kind"] not in kinds:
            raise MatrixExecutionError("Distinct attributed parent context required")
        seen.add(row["request"])
        if not isinstance(row["binding"], str) or not re.fullmatch(
            "[a-f0-9]{64}", row["binding"]
        ):
            raise MatrixExecutionError("Frozen parent binding required")
        size += len(text(row["text"]).encode())
    if "relation" in value:
        request_relation(value["relation"], context)
    if size > 24000:
        raise MatrixExecutionError(
            "Selected source context exceeds the bounded package"
        )
    if any(key in value for key in ("context", "origin", "input_kind", "relation")):
        # Same serialized-content bound as transactional Telecodex selection.
        # The remaining 1024 bytes cover the closed relay schema/execution ref.
        content = {
            "text": value["question"],
            "context": context,
            "input_kind": value.get("input_kind", "session_authored"),
        }
        if len(canonical(content).encode()) > MAX_TEXT_BYTES - 1024:
            raise MatrixExecutionError(
                "Selected context exceeds serialized relay limit"
            )
    if value.get("origin") is not None:
        origin = closed(
            value["origin"], ("schema", "request", "binding", "source_sha256")
        )
        if origin["schema"] != "telecodex.matrix-origin/v1":
            raise MatrixExecutionError("Unsupported conversation origin")
        identifier(origin["request"])
        if origin["request"] != value["input_ref"]:
            raise MatrixExecutionError(
                "Conversation request identity differs from native send"
            )
        for key in ("binding", "source_sha256"):
            if not isinstance(origin[key], str) or not re.fullmatch(
                "[a-f0-9]{64}", origin[key]
            ):
                raise MatrixExecutionError("Frozen conversation origin digest required")
        if (
            hashlib.sha256(value["question"].encode()).hexdigest()
            != origin["source_sha256"]
        ):
            raise MatrixExecutionError("Question differs from frozen original")
    if value["schema"] != TASK_SCHEMA:
        raise MatrixExecutionError("Unsupported task schema")
    text(value["question"])
    identifier(value["input_ref"])
    scope = closed(value["scope"], ("channel", "thread", "tool", "action"))
    identifier(scope["thread"])
    # Current receiving profiles use one membership channel. Archived bilateral
    # channels cannot become a fallback for an unavailable selected recipient.
    if scope["channel"] != "tribe":
        raise MatrixExecutionError("Selected membership-group channel required")
    if (scope["tool"], scope["action"]) == ("messaging_send", "send"):
        destination(value["destination"])
        if value["parent"] is not None:
            raise MatrixExecutionError("Send cannot override a reply parent")
    elif (scope["tool"], scope["action"]) == ("messaging_reply", "reply"):
        parent = closed(
            value["parent"],
            (
                "message_id",
                "message_hash",
                "sender_being_ref",
                "sender_embodiment_id",
                "thread_id",
                "destination",
            ),
        )
        destination(parent["destination"])
        identifier(parent["message_id"])
        if not isinstance(parent["message_hash"], str) or not re.fullmatch(
            "[a-f0-9]{64}", parent["message_hash"]
        ):
            raise MatrixExecutionError("Verified parent digest required")
        if parent["thread_id"] != scope["thread"] or value["destination"] is not None:
            raise MatrixExecutionError("Reply must inherit its exact parent route")
        destination(
            {
                "kind": "body",
                "being_ref": parent["sender_being_ref"],
                "embodiment_id": parent["sender_embodiment_id"],
            }
        )
    else:
        raise MatrixExecutionError("Only one selected request or reply is supported")
    return value


def make_task(
    question,
    input_ref,
    scope,
    *,
    selected_destination=None,
    verified_parent=None,
    origin=None,
    context=None,
    input_kind=None,
    relation=None,
):
    task = canonical(
        {
            "schema": TASK_SCHEMA,
            "question": question,
            "input_ref": input_ref,
            "scope": {
                k: getattr(scope, k) for k in ("channel", "thread", "tool", "action")
            },
            "destination": selected_destination,
            "parent": verified_parent,
        }
    )
    extras = {
        key: value
        for key, value in (
            ("origin", origin),
            ("context", context),
            ("input_kind", input_kind),
            ("relation", relation),
        )
        if value is not None
    }
    if extras:
        value = strict_json(task)
        value.update(extras)
        task = canonical(value)
    validate_task(task)
    return task


def make_conversation_task(status, scope):
    """Trusted host only: consume an authenticated Telecodex matrix status.

    No input is captured or rewritten. The native request is a child of the
    frozen retained original; private human return coordinates stay in Telecodex.
    This prepares an exact task, not approval, sending or receiving inference.
    """
    if status.get("current") is not True or status.get("phase") != "awaiting_execution":
        raise MatrixExecutionError(
            "Selected conversation request is not current and pending"
        )
    return _retained_conversation_task(status, scope)


def _retained_conversation_task(status, scope):
    """Validate immutable owner-retained content without claiming new admission."""
    request = status["request"]
    if request.get("schema") != "telecodex.matrix-request/v1":
        raise MatrixExecutionError("Authenticated retained Matrix request required")
    original = request["original"]
    source = text(original["text"])
    if (
        original["human_id"] != request["human"]
        or original["origin"]["chat_id"] != request["entry"]["chat_id"]
        or original["origin"]["thread_id"] != request["entry"]["thread_id"]
    ):
        raise MatrixExecutionError(
            "Original human/return scope differs from retained entry"
        )
    bound = {key: value for key, value in request.items() if key != "binding"}
    if hashlib.sha256(canonical(bound).encode()).hexdigest() != request["binding"]:
        raise MatrixExecutionError(
            "Retained conversation binding differs from its original"
        )
    return make_task(
        source,
        identifier(request["id"]),
        scope,
        selected_destination=destination(request["destination"]),
        context=request.get("parents", []),
        relation=request["relation"],
        input_kind="committed_machine_transcript"
        if original.get("transcription")
        else "human_text",
        origin={
            "schema": "telecodex.matrix-origin/v1",
            "request": request["id"],
            "binding": request["binding"],
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        },
    )


def make_received_task(message, scope):
    """Prepare one selected SDK-verified request for independent human approval.

    Peer content is data. This does not approve/reserve a cycle, run a model,
    register a listener, read an inbox or widen the existing reply audience.
    """
    parent = parent_from_verified_sdk(message)
    relay = strict_json(message["payload"]["body"]["text"])
    names = ("schema", "via", "kind", "input_ref", "execution_ref", "text")
    closed(
        relay,
        names
        + tuple(key for key in ("context", "input_kind", "relation") if key in relay),
    )
    if (
        relay["schema"] != RELAY_SCHEMA
        or relay["via"] != "interaction-controller"
        or relay["kind"] != "session_request"
    ):
        raise MatrixExecutionError("Selected attributed session request required")
    if "relation" in relay and not isinstance(relay["relation"], dict):
        raise MatrixExecutionError("Explicit request relation object required")
    if scope.tool != "messaging_reply" or scope.action != "reply":
        raise MatrixExecutionError(
            "Receiving execution must preserve the verified reply route"
        )
    return make_task(
        text(relay["text"]),
        identifier(relay["input_ref"]),
        scope,
        verified_parent=parent,
        context=relay.get("context", []),
        input_kind=relay.get("input_kind", "session_authored"),
        relation=relay.get("relation"),
    )


class _NativeMatrixTransport:
    """Fixed authenticated native route; no inference or execution admission."""

    def __init__(self, task, scope, author, native_client, execution_ref):
        value = validate_task(task)
        closed(author, ("being_ref", "embodiment_id"))
        destination({"kind": "body", **author})
        parent = value["parent"]
        if parent is not None:
            selected = parent["destination"]
            if selected["being_ref"] != author["being_ref"] or (
                selected["kind"] == "body"
                and selected["embodiment_id"] != author["embodiment_id"]
            ):
                raise MatrixExecutionError(
                    "Reply parent was addressed to another source"
                )
        if value["scope"] != {
            k: getattr(scope, k) for k in ("channel", "thread", "tool", "action")
        }:
            raise MatrixExecutionError("Task route differs from selected native scope")
        if not is_dataclass(native_client) or "deadline_ns" not in {
            f.name for f in fields(native_client)
        }:
            raise MatrixExecutionError(
                "Selected SDK must support an absolute client deadline"
            )
        server = getattr(getattr(native_client, "config", None), "expected_server", {})
        if server.get("embodiment_id") != author["embodiment_id"]:
            raise MatrixExecutionError(
                "Selected client differs from selected source body"
            )
        self._scope, self._task, self._client = scope, value, native_client
        self._author, self._execution_ref = dict(author), execution_ref
        self._coordination = None
        # The native journal owns idempotency even across host restart. A changed
        # recipient, payload or execution reference cannot reuse this send ID.
        role = "request" if scope.tool == "messaging_send" else "result"
        self.send_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                "telecodex.matrix/" + role + ":" + value["input_ref"],
            )
        )

    def authorize(self, scope):
        # This is route matching only, never execution approval. An admitted
        # runner separately uses ExecutionStore; the SDK rechecks authority.
        return scope == self._scope

    def _invoke(self, method, params, timeout, *, validator=None, deadline_ns=None):
        if (
            type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or not 0.05 <= timeout <= 60
        ):
            raise MatrixExecutionError("Bounded native timeout required")
        deadline = time.monotonic_ns() + int(timeout * 1_000_000_000)
        if deadline_ns is not None:
            deadline = min(deadline, deadline_ns)
        client = replace(self._client, timeout_seconds=timeout, deadline_ns=deadline)
        try:
            if method in ("messaging.send", "messaging.reply", "messaging.inbox"):
                # Same authenticated client and absolute deadline for both
                # observations. Origin is bound before any authored effect.
                enrolled_source = getattr(client, "verified_source", None)
                if enrolled_source is not None:
                    if enrolled_source != self._author:
                        raise MatrixExecutionError("Authenticated source differs from selected source")
                else:
                    _, status = client.invoke("runtime.status", {})
                    source = status.get("result", {}) if status.get("ok") is True else {}
                    if (
                        source.get("schema") != "dm.runtime.status/v1"
                        or source.get("being_ref") != self._author["being_ref"]
                        or source.get("local_origin", {}).get("embodiment_id") != self._author["embodiment_id"]
                    ):
                        raise MatrixExecutionError("Authenticated source differs from selected source")
            _, response = client.invoke(method, params)
            if not isinstance(response, dict) or response.get("ok") is not True:
                raise MatrixExecutionError("Native response not successful")
            return (validator or self._validate_result)(response["result"])
        except Exception:
            # Native journals retain uncertainty. An execution cycle additionally
            # keeps its charge. Never substitute a send, recipient or refund.
            raise MatrixExecutionError(
                "Native outcome unconfirmed; inspect the same send ID"
            ) from None

    def _validate_result(self, result):
        if (
            not isinstance(result, dict)
            or result.get("schema") != "dm.tribe.direct-delivery/v1"
        ):
            raise MatrixExecutionError("Authenticated native delivery result required")
        return self._validate_submission(result)

    def _validate_submission(self, result):
        if (
            not isinstance(result, dict)
            or result.get("send_id") != self.send_id
            or result.get("thread_id") != self._scope.thread
            or result.get("author")
            != {
                "being_ref": self._author["being_ref"],
                "embodiment_id": self._author["embodiment_id"],
            }
        ):
            raise MatrixExecutionError("Native outcome does not match the fixed route")
        identifier(result.get("message_id"))
        if not isinstance(result.get("message_hash"), str) or not re.fullmatch(
            "[a-f0-9]{64}", result["message_hash"]
        ):
            raise MatrixExecutionError("Native message digest required")
        parent = self._task["parent"]
        wanted_parent = (
            None
            if parent is None
            else {
                k: v for k, v in parent.items() if k not in ("thread_id", "destination")
            }
        )
        target = self._task["destination"]
        if parent is not None:
            target = {
                "kind": parent["destination"]["kind"],
                "being_ref": parent["sender_being_ref"],
            }
            if target["kind"] == "body":
                target["embodiment_id"] = parent["sender_embodiment_id"]
        actual = result.get("destination")
        if (
            not isinstance(actual, dict)
            or any(actual.get(k) != v for k, v in target.items())
            or result.get("response_context") != wanted_parent
        ):
            raise MatrixExecutionError(
                "Native recipient or parent differs from approved route"
            )
        return result

    def submit(self, scope, payload, timeout):
        if not self.authorize(scope):
            raise MatrixExecutionError("Outside selected scope")
        closed(payload, ("text",))
        if (
            self._task.get("origin") is not None
            and scope.tool == "messaging_send"
            and payload["text"] != self._task["question"]
        ):
            raise MatrixExecutionError(
                "A relayed original cannot become model-rewritten human speech"
            )
        body = canonical(
            {
                "schema": RELAY_SCHEMA,
                "via": "interaction-controller",
                "kind": "session_request"
                if scope.tool == "messaging_send"
                else "worker_result",
                "input_ref": self._task["input_ref"],
                "execution_ref": self._execution_ref,
                "text": text(payload["text"]),
            }
        )
        if scope.tool == "messaging_send":
            relay = strict_json(body)
            if self._task.get("context"):
                relay["context"] = self._task["context"]
            if self._task.get("input_kind"):
                relay["input_kind"] = self._task["input_kind"]
            if "relation" in self._task:
                relay["relation"] = self._task["relation"]
            body = canonical(relay)
        text(body)
        params = {"channel_id": scope.channel, "send_id": self.send_id, "text": body}
        if scope.tool == "messaging_send":
            params.update(thread_id=scope.thread, destination=self._task["destination"])
        else:
            params.update(
                received_channel_id=scope.channel,
                message_id=self._task["parent"]["message_id"],
            )
        if self._coordination is not None:
            params["coordination"] = dict(self._coordination)
        return self._invoke("messaging." + scope.action, params, timeout)

    def inspect(self, timeout=1.0):
        """Explicit host observation, not a model operation or execution recovery.

        Does not refund an ambiguous cycle, send again or create another root.
        Call only under human-authorized status inspection, never an intake hook.
        """
        return self._invoke(
            "messaging.delivery",
            {"channel_id": self._scope.channel, "send_id": self.send_id},
            timeout,
        )

    def conversation_return(self, request_result, message):
        """Owner-local callback after SDK verification; no delivery claim.

        Recording this through the authenticated Telecodex owner retains the
        canonical external reply. It does not authorize another native turn.
        """
        answer = self.accept_verified_reply(request_result, message)
        return self._conversation_callback(request_result, message, answer)

    def _conversation_callback(self, request_result, message, answer):
        # Callers have already checked the authenticated route and reply kind.
        origin = self._task.get("origin")
        if origin is None:
            raise MatrixExecutionError("Frozen conversation origin required")
        selected = request_result["destination"]
        recipient = {
            key: selected[key]
            for key in (
                ("kind", "being_ref", "embodiment_id")
                if selected["kind"] == "body"
                else ("kind", "being_ref")
            )
        }
        submission = {
            key: request_result[key]
            for key in ("send_id", "message_id", "message_hash", "thread_id", "author")
        }
        submission["destination"] = recipient
        return {
            "request": origin["request"],
            "binding": origin["binding"],
            "submission": submission,
            "message_id": identifier(message["event_id"]),
            "message_hash": message["content_hash"],
            "author": {
                "being_ref": message["being_ref"],
                "embodiment_id": message["origin"]["embodiment_id"],
            },
            "text": answer,
        }

    def _verified_reply_body(self, request_result, message):
        """Check the authenticated exact parent/author/thread, without inference."""
        if self._scope.tool != "messaging_send":
            raise MatrixExecutionError("Outgoing request required")
        self._validate_result(request_result)
        body = message["payload"]["body"]
        parent = body.get("response_context")
        wanted = {
            "message_id": request_result["message_id"],
            "message_hash": request_result["message_hash"],
            "sender_being_ref": self._author["being_ref"],
            "sender_embodiment_id": self._author["embodiment_id"],
        }
        target = self._task["destination"]
        if (
            request_result.get("send_id") != self.send_id
            or request_result.get("thread_id") != self._scope.thread
            or parent != wanted
            or message["payload"]["intent"]["thread_id"] != self._scope.thread
            or message["being_ref"] != target["being_ref"]
            or target["kind"] == "body"
            and message["origin"]["embodiment_id"] != target["embodiment_id"]
        ):
            raise MatrixExecutionError(
                "Reply is not from the selected request and recipient"
            )
        return body

    def accept_verified_reply(self, request_result, message):
        """Strict controller-worker result; never ordinary speech or approval."""
        body = self._verified_reply_body(request_result, message)
        relay = closed(
            strict_json(body["text"]),
            ("schema", "via", "kind", "input_ref", "execution_ref", "text"),
        )
        if (
            relay["schema"] != RELAY_SCHEMA
            or relay["via"] != "interaction-controller"
            or relay["kind"] != "worker_result"
            or relay["input_ref"] != self._task["input_ref"]
        ):
            raise MatrixExecutionError(
                "Reply provenance does not match the original input"
            )
        reference = closed(relay["execution_ref"], ("id", "revision"))
        text(reference["id"], 240)
        if type(reference["revision"]) is not int or reference["revision"] < 1:
            raise MatrixExecutionError("Positive execution revision required")
        return text(relay["text"])


def serve_native_account_owner(owner, input_fd, output_fd):
    """One bounded per-turn pipe session; no listener, retry or new balance store.

    Only the trusted App host owns these pipes. It supplies observed native
    binding/terminal reconciliation and separately authenticated usage proofs;
    this is not an agent tool or a replacement for host/process isolation.
    EOF, deadline and lost writes retain uncertainty instead of reconstructing
    the capability or claiming that external effects stopped.
    """
    import os
    import selectors

    context = owner._context
    original_modes = (os.get_blocking(input_fd), os.get_blocking(output_fd))
    os.set_blocking(input_fd, False)
    os.set_blocking(output_fd, False)
    buffered = bytearray()
    native_turn = None

    def publish(value):
        raw = (canonical(value) + "\n").encode()
        # Replies fit in one atomic, nonblocking pipe write. Do not wait for a
        # consumer or reenter the journal while a provider dispatch owns it.
        if len(raw) > os.fpathconf(output_fd, "PC_PIPE_BUF") or os.write(output_fd, raw) != len(raw):
            raise MatrixExecutionError("Native owner reply unconfirmed")

    def read_frame(selector):
        while b"\n" not in buffered:
            # Accounting and terminal reconciliation remain possible while
            # admission is paused. reserve() independently rechecks admission.
            remaining = min(context.remaining(),
                            owner._allowance["deadlineUnixMs"] / 1000
                            - context._store.observe_clock())
            if remaining <= 0 or not selector.select(remaining):
                raise MatrixExecutionError("Native owner session deadline reached")
            chunk = os.read(input_fd, min(4096, 65537 - len(buffered)))
            if not chunk:
                raise MatrixExecutionError("Native owner pipe closed without reconciliation")
            buffered.extend(chunk)
            if len(buffered) > 65536:
                raise MatrixExecutionError("Native owner frame exceeds bound")
        end = buffered.index(b"\n")
        frame = bytes(buffered[:end])
        del buffered[:end + 1]
        return strict_json(frame)

    try:
        publish({"ready": owner.descriptor()})
        with selectors.DefaultSelector() as selector:
            selector.register(input_fd, selectors.EVENT_READ)
            # One reservation and usage receipt per attempt, plus bind/terminal.
            # Duplicate requests are refused rather than growing retained state.
            for _ in range(owner._allowance["maxProviderAttempts"] * 2 + 2):
                value = read_frame(selector)
                operation = value.get("operation") if isinstance(value, dict) else None
                if operation == "reserve":
                    closed(value, ("operation", "params"))
                    owner.reserve(value["params"], publish)
                elif operation == "bind":
                    closed(value, ("operation", "cycleId", "nativeTurnId"))
                    if value["cycleId"] != context.cycle.cycle_id or native_turn is not None:
                        raise MatrixExecutionError("Native owner binding changed")
                    native_turn = identifier(value["nativeTurnId"])
                    publish({"bound": native_turn, "cycleId": context.cycle.cycle_id})
                elif operation == "settle":
                    closed(value, ("operation", "usage", "proof"))
                    context._store.settle_charge(context.cycle, value["usage"], value["proof"])
                    publish({"settled": value["usage"]["operation_id"],
                             "cycleId": context.cycle.cycle_id})
                elif operation == "reconcile":
                    closed(value, ("operation", "cycleId", "nativeTurnId", "outcome", "effectsReconciled"))
                    if value["outcome"] == "not_started":
                        if (native_turn is not None or value["nativeTurnId"] is not None
                                or value["cycleId"] != context.cycle.cycle_id
                                or value["effectsReconciled"] is not True):
                            raise MatrixExecutionError("Exact native non-submission required")
                        # One atomic journal check: even a pre-ACK provider
                        # intent forbids claiming that this owner never started.
                        context._finish("stopped", require_unstarted=True)
                        publish({"reconciled": "not_started", "cycleId": context.cycle.cycle_id})
                        return
                    if (native_turn is None or value["nativeTurnId"] != native_turn
                            or value["cycleId"] != context.cycle.cycle_id
                            or value["effectsReconciled"] is not True
                            or value["outcome"] not in ("completed", "stopped")):
                        raise MatrixExecutionError("Observed native reconciliation required")
                    context._finish(value["outcome"])
                    publish({"reconciled": value["outcome"], "cycleId": context.cycle.cycle_id})
                    return
                else:
                    raise MatrixExecutionError("Unsupported native owner frame")
        raise MatrixExecutionError("Native owner session frame allowance exhausted")
    except BaseException:
        context._store.mark_ambiguous(context.cycle)
        raise
    finally:
        os.set_blocking(input_fd, original_modes[0])
        os.set_blocking(output_fd, original_modes[1])


def prepare_native_account_owner(
    store, instruction, task, *, thread_id, parent_allowance, cost_bound,
    registration, work_id, read_message, host_source=None, monotonic=time.monotonic,
):
    """Concrete provider-account factory for the current signed queued original.

    The trusted host selects instruction, cost registration and actual thread.
    The existing native reader revalidates the original at journal checkpoints.
    This does not force a private reply route or create a one-call review runner;
    communication still uses the App's existing authorized native tool routes.
    """
    from daimon_matrix.execution_instruction import ExecutionDenied
    from daimon_matrix.review_runner import CycleContext, NativeProviderOwner

    if (store.store_id != instruction.store_id
            or store.get_instruction(instruction.instruction_id, instruction.revision).sha256
            != instruction.sha256
            or registration.get("native_thread_id") != thread_id
            or registration.get("binding") != list(instruction.binding)
            or hashlib.sha256(task.encode()).hexdigest() != instruction.task_sha256):
        raise ExecutionDenied("Native owner differs from the selected work binding")
    from daimon_matrix.execution_instruction import digest

    mode = registration.get("source_mode", "coordination")
    if (digest(dict(registration)) != cost_bound.registration_sha256
            or mode not in {"coordination", "app_owned_inbox"}
            or (mode == "coordination" and (work_id is None or host_source is not None))
            or (mode == "app_owned_inbox" and (
                work_id is not None or host_source is None
                or registration.get("instruction_sha256") != instruction.sha256
                or registration.get("source_channel") != host_source.get("channel_id")))):
        raise ExecutionDenied("Signed native source policy differs from selected work")
    context = CycleContext.prepare(
        store, None, instruction.instruction_id, instruction.revision, task,
        principal=registration.get("principal"), binding=instruction.binding,
        work_id=work_id, require_funding=True, require_queued_source=True,
        read_message=read_message, host_source=host_source, monotonic=monotonic,
    )
    if context is None:
        raise ExecutionDenied("Selected native work cannot be reserved")
    try:
        return NativeProviderOwner(
            context, thread_id=thread_id, parent_allowance=parent_allowance,
            cost_bound=cost_bound, registration=registration,
        )
    except BaseException:
        # A reserved cycle is never reconstructed/refunded on startup loss.
        store.mark_ambiguous(context.cycle)
        raise


class MatrixExecutionBroker(_NativeMatrixTransport):
    """One independently approved execution cycle's fixed native broker."""

    def __init__(self, instruction, task, native_client, *, received_source=None):
        if (
            received_source is None
            and (instruction.mode != "manual" or instruction.max_cycles != 1)
            or len(instruction.scope) != 1
            or hashlib.sha256(task.encode()).hexdigest() != instruction.task_sha256
        ):
            raise MatrixExecutionError(
                "Exact approved purpose and one native scope required; legacy tasks stay manual"
            )
        self._instruction = instruction
        self._received_source = None
        self._queued_metadata = None
        route_task = task
        if received_source is not None:
            from daimon_matrix.execution_instruction import (
                coordination_metadata,
                digest,
            )

            metadata = coordination_metadata(
                received_source["payload"]["body"].get("coordination")
            )
            if (
                metadata["kind"] != "work"
                or metadata["instruction_sha256"] != instruction.sha256
            ):
                raise MatrixExecutionError(
                    "Selected original differs from the approved instruction"
                )
            route_task = make_received_task(received_source, instruction.scope[0])
            self._received_source = {
                "message_id": received_source["event_id"],
                "source_sha256": digest(received_source),
            }
            self._queued_metadata = metadata
        super().__init__(
            route_task,
            instruction.scope[0],
            {"being_ref": instruction.being, "embodiment_id": instruction.embodiment},
            native_client,
            {"id": instruction.instruction_id, "revision": instruction.revision},
        )
        if self._queued_metadata is not None:
            self._coordination = self._queued_metadata | {"kind": "result"}

    def controller(self, store, runner, **options):
        """Create the only supported host controller, pinned to this approval.

        Scope alone omits the recipient. Never reuse this broker with an
        unpinned ReviewController or a cycle from another approved task.
        """
        from daimon_matrix.execution_instruction import ExecutionDenied
        from daimon_matrix.review_runner import ReviewController

        broker = self
        instruction = self._instruction
        if store.store_id != instruction.store_id:
            raise MatrixExecutionError("Execution store differs from approved root")
        if self._received_source is not None:
            for required in ("require_funding", "require_queued_source"):
                if options.get(required, True) is not True:
                    raise MatrixExecutionError(
                        "Queued reply requires existing funding/source gates"
                    )
                options[required] = True

        class PinnedController(ReviewController):
            def run_due_once(self, identity, revision, task, *, work_id=None):
                if (
                    identity != instruction.instruction_id
                    or revision != instruction.revision
                    or hashlib.sha256(task.encode()).hexdigest()
                    != instruction.task_sha256
                ):
                    raise ExecutionDenied(
                        "Controller is pinned to another approved task"
                    )
                if broker._received_source is not None:
                    if work_id is None:
                        raise ExecutionDenied(
                            "Queued reply requires its exact selected work"
                        )
                    work = self.store.coordination_work(work_id)
                    if (
                        work["account_id"] != broker._queued_metadata["account_id"]
                        or work["instruction_sha256"] != instruction.sha256
                        or any(
                            work["source"].get(k) != v
                            for k, v in broker._received_source.items()
                        )
                    ):
                        raise ExecutionDenied(
                            "Queued work differs from the pinned receiving original"
                        )
                elif work_id is not None:
                    raise ExecutionDenied(
                        "Queued work requires the explicit selected-source broker"
                    )
                queued = {} if work_id is None else {"work_id": work_id}
                try:
                    retained = self.store.get_instruction(identity, revision)
                except ExecutionDenied:
                    return super().run_due_once(identity, revision, task, **queued)
                if retained.sha256 != instruction.sha256:
                    raise ExecutionDenied(
                        "Controller instruction differs from approved root"
                    )
                return super().run_due_once(identity, revision, task, **queued)

        return PinnedController(store, runner, broker, **options)


class MatrixConversationTransport(_NativeMatrixTransport):
    """Relay an authenticated retained human original without running a model.

    Construct only in the trusted selected host, never from model/peer JSON.
    Source pins come from owner setup; status comes from the authenticated
    controller. No approval, funding, listener or receiving turn is created.
    """

    def __init__(self, status, author, native_client, *, coordination=None):
        from daimon_matrix.execution_instruction import Scope

        scope = Scope(
            "tribe", identifier(status["request"]["id"]), "messaging_send", "send"
        )
        task = make_conversation_task(status, scope)
        super().__init__(task, scope, author, native_client, None)
        if coordination is not None:
            from daimon_matrix.execution_instruction import coordination_metadata

            metadata = coordination_metadata(coordination)
            if metadata["kind"] != "work":
                raise MatrixExecutionError(
                    "Technical request requires explicit work correlation"
                )
            self._coordination = metadata

    def send(self, timeout=1.0):
        return self.submit(self._scope, {"text": self._task["question"]}, timeout)


class MatrixConversationReceipt(_NativeMatrixTransport):
    """Read-only correlation of an acknowledged retained technical submission.

    Trusted owner status and SDK-verified messages only. Historical/current-false
    requests remain correlatable without reviving admission. An uncertain send
    without a known submission is not evidence of the original wire contents.
    This class is a host API, not OS isolation or independent signature checking.
    """

    def __init__(self, status, native_client):
        from daimon_matrix.execution_instruction import Scope

        if status.get("phase") not in ("submitted", "reply_received"):
            raise MatrixExecutionError(
                "Acknowledged retained technical submission required"
            )
        author = closed(status.get("claimed_source"), ("being_ref", "embodiment_id"))
        submission = closed(
            status.get("submission"),
            (
                "send_id",
                "message_id",
                "message_hash",
                "thread_id",
                "author",
                "destination",
            ),
        )
        destination(submission["destination"])
        scope = Scope(
            "tribe", identifier(status["request"]["id"]), "messaging_send", "send"
        )
        task = _retained_conversation_task(status, scope)
        super().__init__(task, scope, author, native_client, None)
        self._validate_submission(submission)
        self._retained_submission = strict_json(canonical(submission))

    def conversation_return(self, request_result, message):
        """Retain signed speech as speech; structured work results stay strict.

        This read-only receipt cannot create an execution controller. A native
        human-authorized reply needs no invented worker execution reference.
        Neither kind establishes task completion, spending or a native turn.
        """
        body = self._verified_reply_body(request_result, message)
        raw = text(body["text"])
        try:
            return super().conversation_return(request_result, message)
        except MatrixExecutionError:
            # The outer signed route already passed. Non-worker text, including
            # unverified structured claims, remains verbatim peer speech. It is
            # not decoded into an instruction, work result or execution grant.
            pass
        result = self._conversation_callback(request_result, message, raw)
        result["reply_kind"] = "speech"
        return result

    def read_replies(self, *, after=0, limit=3, timeout=1.0):
        """One authenticated selected-thread page; no polling or native input.

        Only correlated worker replies leave this host boundary. The global
        cursor advances across other speech in that thread, never another thread.
        The same absolute deadline covers retained send observation and page read.
        """
        if (
            type(after) is not int
            or not 0 <= after <= 2**53 - 1
            or type(limit) is not int
            or not 1 <= limit <= 3
            or type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or not 0.05 <= timeout <= 60
        ):
            raise MatrixExecutionError("Bounded selected reply page required")
        deadline = time.monotonic_ns() + int(timeout * 1_000_000_000)
        original = self._invoke(
            "messaging.delivery",
            {
                "channel_id": self._scope.channel,
                "send_id": self.send_id,
            },
            timeout,
            deadline_ns=deadline,
        )

        def validate(page):
            if (
                not isinstance(page, dict)
                or page.get("channel_id") != self._scope.channel
                or not isinstance(page.get("items"), list)
                or len(page["items"]) > limit
            ):
                raise MatrixExecutionError("Selected authenticated inbox page required")
            cursor, results = after, []
            wanted_parent = {
                "message_id": original["message_id"],
                "message_hash": original["message_hash"],
                "sender_being_ref": self._author["being_ref"],
                "sender_embodiment_id": self._author["embodiment_id"],
            }
            target = self._task["destination"]
            for row in page["items"]:
                sequence, message = row["inbox_sequence"], row["message"]
                if (
                    type(sequence) is not int
                    or not cursor < sequence <= 2**53 - 1
                    or message["payload"]["intent"]["thread_id"] != self._scope.thread
                ):
                    raise MatrixExecutionError(
                        "Selected inbox cursor or thread changed"
                    )
                body = message["payload"]["body"]
                if (
                    body.get("response_context") == wanted_parent
                    and message["being_ref"] == target["being_ref"]
                    and (
                        target["kind"] != "body"
                        or message["origin"]["embodiment_id"] == target["embodiment_id"]
                    )
                ):
                    results.append(self.conversation_return(original, message))
                cursor = sequence
            return {
                "after": after,
                "next_cursor": cursor,
                "results": results,
                "page_full": len(page["items"]) == limit,
            }

        return self._invoke(
            "messaging.inbox",
            {
                "channel_id": self._scope.channel,
                "thread_id": self._scope.thread,
                "after": after,
                "limit": limit,
            },
            timeout,
            validator=validate,
            deadline_ns=deadline,
        )

    def submit(self, scope, payload, timeout):
        raise MatrixExecutionError("Receipt correlation cannot author a native message")

    def _validate_result(self, result):
        super()._validate_result(result)
        selected = result["destination"]
        actual = {
            key: result[key]
            for key in ("send_id", "message_id", "message_hash", "thread_id", "author")
        }
        actual["destination"] = {
            key: selected[key]
            for key in (
                ("kind", "being_ref", "embodiment_id")
                if selected["kind"] == "body"
                else ("kind", "being_ref")
            )
        }
        if actual != self._retained_submission:
            raise MatrixExecutionError(
                "Native outcome differs from acknowledged submission"
            )
        return result
