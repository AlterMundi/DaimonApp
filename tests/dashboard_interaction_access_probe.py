import unittest
from unittest.mock import patch

from scripts.interaction_access_probe import probe

ORIGIN = "https://compaii.dmn.homes"


class AccessProbe(unittest.TestCase):
    def test_reported_incident_is_not_confused_with_anonymous_refusal(self):
        for detail, expected in (
            ("Receiving control binding changed; operator must requalify Sessions", "receiver_binding_changed"),
            ("Alerts receiving binding changed; operator must requalify Sessions", "alerts_binding_changed"),
        ):
            with self.subTest(expected=expected), patch(
                "scripts.interaction_access_probe.read_response",
                return_value=(503, "application/json", ('{"detail": "%s"}' % detail).encode()),
            ) as request:
                self.assertEqual(probe(ORIGIN)["state"], expected)
                request.assert_called_once()

    def test_expected_app_refusal_and_shell_are_both_required(self):
        refused = (401, "application/json", b'{"detail":"Open the dashboard from this bot in Telegram"}')
        for access, entry, expected in (
            (refused, (200, "text/html", b'<html data-shared-auth="true">'), "ready"),
            (refused, (502, "text/plain", b""), "unexpected_entry_response"),
            ((401, "application/json", b'{"detail":"unrelated gateway"}'), None, "unexpected_access_response"),
            ((302, "text/html", b""), None, "unexpected_access_response"),
            ((200, "application/json", b"{}"), None, "unexpected_access_response"),
        ):
            results = [access] if entry is None else [access, entry]
            with self.subTest(expected=expected, access=access[0]), patch(
                "scripts.interaction_access_probe.read_response", side_effect=results,
            ) as request:
                self.assertEqual(probe(ORIGIN)["state"], expected)
                self.assertEqual(request.call_count, len(results))
