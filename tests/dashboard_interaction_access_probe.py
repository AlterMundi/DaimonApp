from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
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
HOME_STATUS = (200, "application/json",
               b'{"contract":"dm.home-browser/v1","signed_in":false,"shared_login":true}', None)
HOME_IDENTITY = (401, "application/json", b'{"detail":"human_browser_required"}', None)
APP_IDENTITY = (401, "application/json", b'{"detail":"Sign in to your conversation"}', None)


class AccessProbe(unittest.TestCase):
    def test_reported_incident_is_not_confused_with_anonymous_refusal(self):
        for detail, expected in (
            ("Receiving control binding changed; operator must requalify Sessions", "receiver_binding_changed"),
            ("Alerts receiving binding changed; operator must requalify Sessions", "alerts_binding_changed"),
        ):
            with self.subTest(expected=expected), patch(
                "scripts.interaction_access_probe.read_probe_response",
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
            if expected == "ready":
                results.extend([HOME_STATUS, HOME_IDENTITY, APP_IDENTITY])
            with self.subTest(expected=expected, access=access[0]), patch(
                "scripts.interaction_access_probe.read_probe_response", side_effect=results,
            ) as request:
                self.assertEqual(probe(ORIGIN)["state"], expected)
                self.assertEqual(request.call_count, len(results))
                if expected == "ready":
                    self.assertTrue(all(call.kwargs.get("prefix_only") for call in request.call_args_list[2:5]))
                    self.assertEqual([call.args[1] for call in request.call_args_list[2:]], [
                        ORIGIN + "/access-client.js",
                        ORIGIN + "/interaction/assets/conversation.js",
                        ORIGIN + "/interaction/assets/app.js?v=2d711642b726b044",
                        ORIGIN + "/access/status",
                        ORIGIN + "/access/identity",
                        ORIGIN + "/interaction/api/interaction/access",
                    ])
                    self.assertTrue(request.call_args.kwargs["synthetic_session"])

    def test_real_http_shared_sign_in_failure_then_recovery(self):
        paths = {
            "/interaction/api/interaction/access": (
                401, "application/json", b'{"detail":"Shared browser sign-in required"}', None),
            "/interaction/": (200, "text/html", SHELL, None),
            "/access-client.js": JS,
            "/interaction/assets/conversation.js": JS,
            "/interaction/assets/app.js": VERSIONED_JS,
            "/access/status": (200, "application/json",
                               b'{"contract":"dm.home-browser/v1","signed_in":false}', None),
            "/access/identity": HOME_IDENTITY,
        }
        seen = []
        app_identity = (503, "application/json", b'{"detail":"Shared authentication unavailable; retry shortly"}', None)

        class Gateway(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path.split("?")[0])
                assert not self.headers.get("Authorization")
                cookie = self.headers.get("Cookie")
                if cookie:
                    assert self.path == "/interaction/api/interaction/access"
                    assert cookie.startswith("__Host-home=") and len(cookie.split("=",1)[1])==43
                status, media, body, etag = app_identity if cookie else paths[self.path.split("?")[0]]
                self.send_response(status)
                self.send_header("Content-Type", media)
                self.send_header("Content-Length", str(len(body)))
                if etag:
                    self.send_header("ETag", etag)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format, *_args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Gateway) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                origin = f"http://127.0.0.1:{server.server_port}"
                missing = probe(origin)
                self.assertEqual((missing["state"], missing["sign_in"]),
                                 ("unexpected_entry_response", "status_unavailable"))
                self.assertNotIn("/access/identity", seen)
                paths["/access/status"] = HOME_STATUS
                paths["/access/identity"] = (503, "text/html", b"Unavailable", None)
                broken = probe(origin)
                self.assertEqual((broken["state"], broken["sign_in"]),
                                 ("unexpected_entry_response", "identity_unavailable"))
                paths["/access/identity"] = HOME_IDENTITY
                for unexpected in (app_identity, paths["/interaction/api/interaction/access"],
                                   (200, "application/json", b"{}", None)):
                    app_identity = unexpected
                    broken = probe(origin)
                    self.assertEqual((broken["state"], broken["sign_in"]),
                                     ("unexpected_entry_response", "app_identity_unavailable"))
                app_identity = APP_IDENTITY
                ready = probe(origin)
                self.assertEqual((ready["state"], ready["sign_in"]), ("ready", "ready"))
            finally:
                server.shutdown()
                thread.join(3)
