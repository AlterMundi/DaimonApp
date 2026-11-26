"""Deterministic Anthropic streaming endpoint for the signed foreground fixture."""

from http.server import BaseHTTPRequestHandler
import json


TOOL = "mcp__matrix__daimon_status"
DMK = ["mcp__hmk__dmk_recall", "mcp__hmk__hmk_recall"]
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
            assert sorted(tool["name"] for tool in data["tools"]) == sorted([TOOL, *DMK] if memory else [TOOL])
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
            if getattr(self.server, "dmk_revoked", False):
                assert not result
                assert self.server.dmk_marker not in json.dumps(data["messages"])
                assert ANSWER not in json.dumps(data["messages"])
                assert json.loads(submission)["native_session_id"] != self.server.previous_session
                assert json.loads(submission)["native_session_scope"] != self.server.previous_scope
                block = {"type": "text", "text": ""}
                delta = {"type": "text_delta", "text": REVOKED_ANSWER}
                reason = "end_turn"
            elif previous is not None:
                assert prior == 2
                assert previous in json.dumps(data["messages"])
                assert ANSWER in json.dumps(data["messages"])
                assert json.loads(submission)["native_session_id"] == self.server.previous_session
                block = {"type": "text", "text": ""}
                delta = {"type": "text_delta", "text": "I retained the first turn."}
                reason = "end_turn"
            elif prior == 0:
                assert not result
                block = {"type": "tool_use", "id": "toolu_fixture", "name": DMK[0] if memory else TOOL, "input": {}}
                delta = {"type": "input_json_delta", "partial_json": json.dumps(memory or {})}
                reason = "tool_use"
            else:
                assert prior == 1 and len(result) == 1
                assert result[0]["tool_use_id"] == "toolu_fixture"
                assert result[0].get("is_error") is not True
                assert (self.server.dmk_marker if memory else self.server.body) in json.dumps(result[0]["content"])
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
