import unittest
from unittest.mock import patch

from scripts.interaction_access_probe import probe

ORIGIN = "https://compaii.dmn.homes"
SHELL = (b'<html data-shared-auth="true">'
         b'<script src="/access-client.js"></script>'
         b'<script src="assets/conversation.js"></script>'
         b'<script src="assets/app.js?v=2d711642b726b044"></script>')
JS = (200, "text/javascript", b"x", None)
VERSIONED_JS = (206, "text/javascript", b"x", '"2d711642b726b044"')


class AccessProbe(unittest.TestCase):
    def test_reported_incident_is_not_confused_with_anonymous_refusal(self):
        for detail, expected in (
            ("Receiving control binding changed; operator must requalify Sessions", "receiver_binding_changed"),
            ("Alerts receiving binding changed; operator must requalify Sessions", "alerts_binding_changed"),
        ):
            with self.subTest(expected=expected), patch(
                "scripts.interaction_access_probe.read_response",
                return_value=(503, "application/json", ('{"detail": "%s"}' % detail).encode(), None),
            ) as request:
                self.assertEqual(probe(ORIGIN)["state"], expected)
                request.assert_called_once()

    def test_expected_app_refusal_and_shell_are_both_required(self):
        refused = (401, "application/json", b'{"detail":"Open the dashboard from this bot in Telegram"}')
        for access, entry, assets, expected in (
            (refused, (200, "text/html", SHELL), (JS, JS, VERSIONED_JS), "ready"),
            (refused, (200, "text/html", SHELL), ((404, "text/plain", b"", None),), "unexpected_entry_response"),
            (refused, (200, "text/html", SHELL), ((200, "text/html", b"login", None),), "unexpected_entry_response"),
            (refused, (200, "text/html", SHELL), (JS, JS, JS), "unexpected_entry_response"),
            (refused, (200, "text/html", SHELL.replace(b'<script src="/access-client.js"></script>', b'')), (), "unexpected_entry_response"),
            (refused, (502, "text/plain", b""), (), "unexpected_entry_response"),
            ((401, "application/json", b'{"detail":"unrelated gateway"}'), None, (), "unexpected_access_response"),
            ((302, "text/html", b""), None, (), "unexpected_access_response"),
            ((200, "application/json", b"{}"), None, (), "unexpected_access_response"),
        ):
            results = [(*access, None)]
            if entry is not None:
                results.extend([(*entry, None), *assets])
            with self.subTest(expected=expected, access=access[0]), patch(
                "scripts.interaction_access_probe.read_response", side_effect=results,
            ) as request:
                self.assertEqual(probe(ORIGIN)["state"], expected)
                self.assertEqual(request.call_count, len(results))
                if expected == "ready":
                    self.assertTrue(all(call.kwargs.get("prefix_only") for call in request.call_args_list[2:]))
                    self.assertEqual([call.args[1] for call in request.call_args_list[2:]], [
                        ORIGIN + "/access-client.js",
                        ORIGIN + "/interaction/assets/conversation.js",
                        ORIGIN + "/interaction/assets/app.js?v=2d711642b726b044",
                    ])
