"""Deterministic Anthropic streaming endpoint for the signed foreground fixture."""

from http.server import BaseHTTPRequestHandler
import json


TOOL = "mcp__matrix__daimon_status"
CONTROLLER = "mcp__gateway__interaction_controller"
DMK = ["mcp__hmk__dmk_recall", "mcp__hmk__hmk_recall"]
FOUNDATION = "mcp__matrix_foundation__fixture_read"
ANSWER = "The selected Matrix body reported integrity ok."
REVOKED_ANSWER = "I can continue without the earlier memory."


class ClaudeProvider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def admitted(self):
        phase, submission = self.server.journey.row(
            "SELECT phase, submission FROM interaction_matrix_requests WHERE source_event=?",
            (self.server.current,),
        )[0]
        assert phase == "provider_exposed"
        return json.loads(submission)

    def do_POST(self):
        try:
            assert self.path.startswith("/v1/messages")
            length = int(self.headers["Content-Length"])
            assert 0 < length < 262_144
            data = json.loads(self.rfile.read(length))
            if getattr(self.server, "rate_limited", False):
                self.admitted()
                body = json.dumps({"type": "error", "error": {
                    "type": "rate_limit_error", "message": "Rate limit exceeded",
                }}).encode()
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("x-should-retry", "false")
                self.send_header("retry-after", "0")
                self.end_headers()
                self.wfile.write(body)
                return
            system = json.dumps(data["system"], ensure_ascii=False)
            assert self.server.display_name in system
            assert "Claude Code is your harness" in system
            if getattr(self.server, "session_instructions", None):
                assert self.server.session_instructions in system
            if getattr(self.server, "paired_human", False):
                assert "The Gateway authenticated that sender as the human paired with this daimon." in system
                assert "The Claude subscription account is a service credential and does not identify the sender." in system
            memory = getattr(self.server, "dmk_record", None)
            skill = getattr(self.server, "skill_name", None)
            foundation = getattr(self.server, "foundation_marker", None)
            foundation_tools = [FOUNDATION, "mcp__matrix_foundation__daimon_status"] if foundation else []
            extra_foundation = getattr(self.server, "deferred_foundation", [])
            foundation_tools += [f"mcp__matrix_foundation__{name}" for name in extra_foundation]
            host_tools = getattr(self.server, "host_tools", [])
            expected = [TOOL] + (DMK if memory else []) + (["Skill"] if skill else []) + foundation_tools + host_tools
            controller = getattr(self.server, "controller", False)
            routed_controller = getattr(self.server, "inverse_paired", False)
            if controller or routed_controller:
                expected.append(CONTROLLER)
            by_name = {tool["name"]: tool for tool in data["tools"]}
            if extra_foundation:
                expected = [name for name in expected if name not in foundation_tools]
                expected += ["ToolSearch", "DeferredToolPlaceholder"]
                found = set(foundation_tools) & by_name.keys()
                assert found <= {FOUNDATION}, found
                expected.extend(found)
                assert all(not by_name[name].get("defer_loading") for name in (DMK if memory else []))
            assert sorted(by_name) == sorted(expected), sorted(by_name)
            steps = [(DMK[0], memory, self.server.dmk_marker) if memory else (TOOL, {}, self.server.body)]
            if controller:
                steps.append((CONTROLLER, {"operation": "capabilities", "arguments": {}},
                              "telecodex.interaction-controller/v1"))
                steps.append((CONTROLLER, {"operation": "candidates",
                                           "arguments": {"mode": "inventory", "selectors": []}},
                              "observer_candidate_inventory"))
            if skill:
                steps.append(("Skill", {"skill": skill}, self.server.skill_marker))
            if foundation:
                if extra_foundation:
                    steps.append(("ToolSearch", {"query": f"select:{FOUNDATION}"}, FOUNDATION))
                steps.append((FOUNDATION, {}, foundation))
            steer = getattr(self.server, "steer_fixture", None)
            if steer:
                steps = [("Bash", {"command": steer["command"]}, "Native steer gate opened.")]
            elif write_memory := getattr(self.server, "memory_write_command", None):
                assert "owner-configured DMK wrapper" in system
                steps.append(("Bash", {"command": write_memory}, "Native DMK write accepted."))
            elif host_tools:
                steps += [
                    ("Read", {"file_path": str(self.server.host_file)}, "Native file readback marker."),
                    ("Bash", {"command": "test -z \"${ANTHROPIC_API_KEY+x}\" && fixture-shared-command"},
                     "Native shell readback marker."),
                ]
            if getattr(self.server, "mixed", False):
                marker = self.server.mixed_worker_reply
                destination = {"selector": "Alpha", "relation": "new", "requests": []}
                dispatch = {"operation": "dispatch", "arguments": {
                    "input_ref": self.server.current, "destinations": [destination],
                }}
                steps = [
                    (CONTROLLER, {"operation": "inputs", "arguments": {}}, self.server.current),
                    (CONTROLLER, dispatch, '"new_admission":true'),
                    (CONTROLLER, dispatch, '"new_admission":false'),
                    (CONTROLLER, {"operation": "conversation", "arguments": {}}, marker),
                ]
            assert self.server.original in json.dumps(data["messages"])
            attachment = getattr(self.server, "attachment", None)
            if attachment:
                assert any(
                    block.get("type") == "image" and block["source"]["data"] == attachment["base64"]
                    and block["source"]["media_type"] == "image/png"
                    for msg in data["messages"] if isinstance(msg["content"], list)
                    for block in msg["content"]
                )
            submission = self.admitted()
            assert submission["native_session_id"]
            distinct_request = getattr(self.server, "test_session_request", False)
            fixture_id = "scoped" if distinct_request else "fixture"
            returned_dependency = getattr(self.server, "returned_dependency", None)
            if returned_dependency:
                fixture_id = "returned"
                steps = [
                    (CONTROLLER, {"operation": "inputs", "arguments": {}}, '"eligible_coordination_parent":false'),
                    (CONTROLLER, {"operation": "session_request", "arguments": {
                        "parent_instruction": self.server.current, "request_id": "result-cannot-delegate",
                        "selector": "general", "text": "This request must never be admitted.",
                    }}, '"kind":"session_request_rejected"'),
                ]
            if distinct_request:
                request = {"parent_instruction": self.server.current, "request_id": "fixture-general",
                           "selector": "general", "text": "Check the design summary for the current request."}
                steps = [
                    (CONTROLLER, {"operation": "inputs", "arguments": {}}, self.server.current),
                    (CONTROLLER, {"operation": "capabilities", "arguments": {}}, "telecodex.local-session/v1"),
                    (CONTROLLER, {"operation": "session_request",
                                  "arguments": {**request, "report_to_topic": True}},
                     '"kind":"topic_report_destination_unsupported"'),
                    (CONTROLLER, {"operation": "session_request", "arguments": request}, '"new_admission":true'),
                    (CONTROLLER, {"operation": "session_request", "arguments": request}, '"new_admission":false'),
                ]
            prior = len(self.server.calls)
            self.server.calls.append(self.server.current)
            if steer and prior:
                messages = json.dumps(data["messages"])
                assert steer["text"] in messages
                assert steer["conversation_text"] in messages
            previous = getattr(self.server, "previous_original", None)
            messages = data["messages"]
            if returned_dependency:
                assert returned_dependency["parent_prompt"] in json.dumps(messages)
            skill_refresh = getattr(self.server, "refreshed_skill", None)
            if skill_refresh:
                fixture_id = "refreshed-skill"
                assert submission["native_session_id"] == skill_refresh["native"]
                assert submission["native_session_scope"] == skill_refresh["scope"]
                assert skill_refresh["previous_prompt"] in json.dumps(messages)
            if distinct_request or returned_dependency or skill_refresh:
                original = next(index for index, message in enumerate(messages)
                                if self.server.original in json.dumps(message["content"]))
                messages = messages[original:]
            result = [
                item for message in messages if isinstance(message["content"], list)
                for item in message["content"] if item["type"] == "tool_result"
            ]
            if self.server.current == getattr(self.server, "interrupted_id", None):
                block = {"type": "text", "text": ""}
                delta = {"type": "text_delta", "text": "A delayed synthetic response."}
                reason = "end_turn"
            elif hasattr(self.server, "old_skill_marker"):
                assert submission["native_session_id"] != self.server.previous_session
                messages = json.dumps(data["messages"])
                assert self.server.old_skill_marker not in messages and REVOKED_ANSWER not in messages
                if not result:
                    block = {"type": "tool_use", "id": "toolu_updated_skill", "name": "Skill", "input": {}}
                    delta = {"type": "input_json_delta", "partial_json": json.dumps({"skill": skill})}
                    reason = "tool_use"
                else:
                    assert result[0]["tool_use_id"] == "toolu_updated_skill" and not result[0].get("is_error")
                    assert self.server.skill_marker in messages
                    block = {"type": "text", "text": ""}
                    delta = {"type": "text_delta", "text": self.server.skill_marker}
                    reason = "end_turn"
            elif getattr(self.server, "dmk_revoked", False):
                assert not result
                assert self.server.dmk_marker not in json.dumps(data["messages"])
                assert ANSWER not in json.dumps(data["messages"])
                assert submission["native_session_id"] != self.server.previous_session
                assert submission["native_session_scope"] != self.server.previous_scope
                block = {"type": "text", "text": ""}
                delta = {"type": "text_delta", "text": REVOKED_ANSWER}
                reason = "end_turn"
            elif attachment:
                block = {"type": "text", "text": ""}
                delta = {"type": "text_delta", "text": ANSWER}
                reason = "end_turn"
            elif (recovered := getattr(self.server, "expected_recovered_history", None)) is not None:
                assert submission["native_session_id"] != self.server.previous_session
                assert any(
                    "Gateway historical context (JSON):" in block.get("text", "")
                    and recovered in block.get("text", "")
                    for message in messages if isinstance(message["content"], list)
                    for block in message["content"] if block.get("type") == "text"
                )
                block = {"type": "text", "text": ""}
                delta = {"type": "text_delta", "text": "I recovered the retained design context."}
                reason = "end_turn"
            elif previous is not None:
                assert prior == len(steps) + 1
                assert previous in json.dumps(data["messages"])
                assert ANSWER in json.dumps(data["messages"])
                assert submission["native_session_id"] == self.server.previous_session
                block = {"type": "text", "text": ""}
                delta = {"type": "text_delta", "text": getattr(self.server, "followup_answer", "I retained the first turn.")}
                reason = "end_turn"
            else:
                assert prior <= len(steps) and len(result) == prior, (prior, len(steps), [r["tool_use_id"] for r in result])
                if prior:
                    entry = next(item for item in result if item["tool_use_id"] == f"toolu_{fixture_id}_{prior-1}")
                    assert entry.get("is_error") is not True
                    payload = json.dumps(entry["content"], ensure_ascii=False) if isinstance(
                        entry["content"], (dict, list)) else entry["content"]
                    expected_result = steps[prior - 1][2]
                    if getattr(self.server, "mixed", False) and prior in (2, 3):
                        if isinstance(entry["content"], list):
                            payload = "".join(item.get("text", "") for item in entry["content"])
                        assert expected_result in payload
                        if prior == 2:
                            self.server.journey.wait(lambda: self.server.journey.instructions(7)
                                and self.server.journey.instructions(7)[0][1] == "accepted")
                            self.server.journey.answer_worker(7, self.server.mixed_worker_reply)
                            self.server.journey.wait(lambda: self.server.journey.row(
                                "SELECT count(*) FROM interaction_results") == [(1,)])
                    else:
                        if (distinct_request or returned_dependency) and isinstance(entry["content"], list):
                            payload = "".join(item.get("text", "") for item in entry["content"])
                        tool = steps[prior - 1][0]
                        if tool == "Skill":
                            # Recent Claude releases return the launch acknowledgment in
                            # tool_result and the instructions in a separate message.
                            assert f"Launching skill: {skill}" in payload or expected_result in payload
                            payload = json.dumps(messages, ensure_ascii=False)
                        assert expected_result in payload, tool
                if prior < len(steps):
                    tool, inputs, _ = steps[prior]
                    if tool == FOUNDATION and extra_foundation:
                        assert FOUNDATION in by_name
                    block = {"type": "tool_use", "id": f"toolu_{fixture_id}_{prior}", "name": tool, "input": {}}
                    delta = {"type": "input_json_delta", "partial_json": json.dumps(inputs)}
                    reason = "tool_use"
                else:
                    block = {"type": "text", "text": ""}
                    delta = {"type": "text_delta", "text": ANSWER}
                    reason = "end_turn"
            message = {
                "id": f"msg_{fixture_id}_{prior}", "type": "message", "role": "assistant", "content": [],
                "model": data["model"], "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": 8, "output_tokens": 1},
            }
            frames = [
                ("message_start", {"message": message}),
                ("content_block_start", {"index": 0, "content_block": block}),
                ("content_block_delta", {"index": 0, "delta": delta}),
                ("content_block_stop", {"index": 0}),
                ("message_delta", {"delta": {"stop_reason": reason, "stop_sequence": None},
                                   "usage": {"output_tokens": 4}}),
                ("message_stop", {}),
            ]
            response = "".join(
                f"event: {event}\ndata: {json.dumps({'type': event, **value})}\n\n"
                for event, value in frames
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
        except Exception as error:
            import traceback
            point = traceback.extract_tb(error.__traceback__)[-1]
            if self.server.failure is None:
                self.server.failure = AssertionError(f"{point.name}:{point.lineno}: {error}")
            self.send_error(400)
