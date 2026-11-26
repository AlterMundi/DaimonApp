"""Deterministic Anthropic streaming endpoint for the signed foreground fixture."""

from http.server import BaseHTTPRequestHandler
import json


TOOL = "mcp__matrix__daimon_status"
DMK = ["mcp__hmk__dmk_recall", "mcp__hmk__hmk_recall"]
FOUNDATION = "mcp__matrix_foundation__fixture_read"
ANSWER = "The selected Matrix body reported integrity ok."
REVOKED_ANSWER = "I can continue without the earlier memory."


class ClaudeProvider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        try:
            assert self.path.startswith("/v1/messages")
            length = int(self.headers["Content-Length"])
            assert 0 < length < 262_144
            data = json.loads(self.rfile.read(length))
            system = json.dumps(data["system"], ensure_ascii=False)
            assert self.server.display_name in system
            assert "Claude Code is your harness" in system
            memory = getattr(self.server, "dmk_record", None)
            skill = getattr(self.server, "skill_name", None)
            foundation = getattr(self.server, "foundation_marker", None)
            foundation_tools = [FOUNDATION, "mcp__matrix_foundation__daimon_status"] if foundation else []
            extra_foundation = getattr(self.server, "deferred_foundation", [])
            foundation_tools += [f"mcp__matrix_foundation__{name}" for name in extra_foundation]
            host_tools = getattr(self.server, "host_tools", [])
            expected = [TOOL] + (DMK if memory else []) + (["Skill"] if skill else []) + foundation_tools + host_tools
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
            if skill:
                steps.append(("Skill", {"skill": skill}, self.server.skill_marker))
            if foundation:
                if extra_foundation:
                    steps.append(("ToolSearch", {"query": f"select:{FOUNDATION}"}, FOUNDATION))
                steps.append((FOUNDATION, {}, foundation))
            if host_tools:
                steps += [
                    ("Read", {"file_path": str(self.server.host_file)}, "Native file readback marker."),
                    ("Bash", {"command": "test -z \"${ANTHROPIC_API_KEY+x}\" && printf 'Native shell %s.' 'readback marker'"},
                     "Native shell readback marker."),
                ]
            assert self.server.original in json.dumps(data["messages"])
            phase, submission = self.server.journey.row(
                "SELECT phase, submission FROM interaction_matrix_requests WHERE source_event=?",
                (self.server.current,),
            )[0]
            assert phase == "provider_exposed"
            assert json.loads(submission)["native_session_id"]
            prior = len(self.server.calls)
            self.server.calls.append(self.server.current)
            previous = getattr(self.server, "previous_original", None)
            result = [
                item for message in data["messages"] if isinstance(message["content"], list)
                for item in message["content"] if item["type"] == "tool_result"
            ]
            if hasattr(self.server, "old_skill_marker"):
                assert json.loads(submission)["native_session_id"] != self.server.previous_session
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
                assert json.loads(submission)["native_session_id"] != self.server.previous_session
                assert json.loads(submission)["native_session_scope"] != self.server.previous_scope
                block = {"type": "text", "text": ""}
                delta = {"type": "text_delta", "text": REVOKED_ANSWER}
                reason = "end_turn"
            elif previous is not None:
                assert prior == len(steps) + 1
                assert previous in json.dumps(data["messages"])
                assert ANSWER in json.dumps(data["messages"])
                assert json.loads(submission)["native_session_id"] == self.server.previous_session
                block = {"type": "text", "text": ""}
                delta = {"type": "text_delta", "text": "I retained the first turn."}
                reason = "end_turn"
            else:
                assert prior <= len(steps) and len(result) == prior
                if prior:
                    entry = next(item for item in result if item["tool_use_id"] == f"toolu_fixture_{prior-1}")
                    assert entry.get("is_error") is not True
                    assert steps[prior - 1][2] in json.dumps(data["messages"])
                if prior < len(steps):
                    tool, inputs, _ = steps[prior]
                    if tool == FOUNDATION and extra_foundation:
                        assert FOUNDATION in by_name
                    block = {"type": "tool_use", "id": f"toolu_fixture_{prior}", "name": tool, "input": {}}
                    delta = {"type": "input_json_delta", "partial_json": json.dumps(inputs)}
                    reason = "tool_use"
                else:
                    block = {"type": "text", "text": ""}
                    delta = {"type": "text_delta", "text": ANSWER}
                    reason = "end_turn"
            message = {
                "id": f"msg_fixture_{prior}", "type": "message", "role": "assistant", "content": [],
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
            self.server.failure = error
            self.send_error(400)
