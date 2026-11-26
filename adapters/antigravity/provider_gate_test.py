"""Exercise the provider authorization boundary without a model or native SDK."""

from concurrent.futures import ThreadPoolExecutor
import json
import unittest
from unittest.mock import patch

from provider_gate import ProviderGate


def payload(text, history=(), tools=("daimon_status",)):
    return json.dumps({
        "model": "fixture",
        "tools": [{"type": "function", "function": {
            "name": name, "parameters": {"type": "object", "properties": {}},
        }} for name in tools],
        "messages": [{"role": "user", "content": text}, *history],
    })


class ProviderReservation(unittest.TestCase):
    def test_followups_require_new_approved_observations(self):
        tools = ("daimon_status", "dmk_read_selected")
        gate = ProviderGate("fixture", 1, tools, "Exact original")
        gate.respond(payload(gate.challenge, tools=tools))
        status = {"role": "tool", "content": "Signed body"}
        memory = {"role": "tool", "content": "Selected memory"}
        with ThreadPoolExecutor(max_workers=1) as worker, patch("provider_gate.HTTPConnection") as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 200
            response.getheader.return_value = "application/json"
            response.read.return_value = b"{}"
            first = worker.submit(gate.respond, payload("Exact original", tools=tools))
            try:
                self.assertTrue(gate.request_waiting.wait(timeout=1))
                gate.release()
                first.result(timeout=1)
                gate.allow_followup()
                gate.respond(payload("Exact original", [status], tools))
                with self.assertRaises(ValueError):
                    gate.respond(payload("Exact original", [status, memory], tools))
                gate.allow_followup()
                gate.respond(payload("Exact original", [status, memory], tools))
                sent = connection.return_value.request.call_args.args[2]
                self.assertEqual(json.loads(sent)["tool_choice"], "none")
                with self.assertRaises(ValueError):
                    gate.respond(payload("Exact original", [status, memory], tools))
                with self.assertRaises(ValueError):
                    gate.allow_followup()
                self.assertEqual(connection.call_count, 3)
            finally:
                gate.abort()

    def test_original_reservation_and_abort(self):
        gate = ProviderGate("fixture", 1, {"daimon_status"}, "Exact original")
        gate.respond(payload(gate.challenge))
        with self.assertRaises(ValueError):
            gate.respond(payload("Different original"))
        with self.assertRaises(ValueError):
            gate.respond(payload("Exact original", [{"role": "assistant", "content": gate.marker}]))
        with ThreadPoolExecutor(max_workers=1) as worker, patch("provider_gate.HTTPConnection") as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 200
            response.getheader.return_value = "application/json"
            response.read.return_value = b"{}"
            first = worker.submit(gate.respond, payload("Exact original"))
            try:
                self.assertTrue(gate.request_waiting.wait(timeout=1))
                connection.assert_not_called()
                gate.release()
                with self.assertRaises(ValueError):
                    gate.respond(payload("Exact original", [{"role": "assistant", "content": "Different envelope"}]))
                self.assertEqual(first.result(timeout=1), ("application/json", b"{}"))
                gate.allow_followup()
                gate.abort()
                with self.assertRaises(ValueError):
                    gate.respond(payload("Exact original", [{"role": "tool", "content": "Selected observation"}]))
                connection.assert_called_once()
            finally:
                gate.abort()

    def test_expired_reservation_cannot_be_released(self):
        gate = ProviderGate("fixture", 1, {"daimon_status"}, "Exact original")
        gate.respond(payload(gate.challenge))
        with ThreadPoolExecutor(max_workers=1) as worker, patch("provider_gate.HTTPConnection") as connection:
            first = worker.submit(gate.respond, payload("Exact original"))
            try:
                self.assertTrue(gate.request_waiting.wait(timeout=1))
                with patch("provider_gate.monotonic", return_value=gate.first_deadline + 1):
                    with self.assertRaises(ValueError):
                        gate.release()
                gate.abort()
                with self.assertRaises(ValueError):
                    first.result(timeout=1)
                connection.assert_not_called()
            finally:
                gate.abort()


if __name__ == "__main__":
    unittest.main()
