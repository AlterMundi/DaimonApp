#!/usr/bin/env python3
"""Check the existing public Conversation entry and its anonymous access fence."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import json
import re
import signal
import time
import urllib.error
import urllib.request

MAX_TARGETS = 16
ENTRY = "/interaction/"
ACCESS = ENTRY + "api/interaction/access"
ENTRY_ASSETS = {"/access-client.js", "assets/app.js", "assets/conversation.js"}
JAVASCRIPT_TYPES = {"application/javascript", "text/javascript"}
UNAUTHENTICATED = {
    "Open the dashboard from this bot in Telegram",
    "Shared browser sign-in required",
}
BINDING_FAILURES = {
    "Receiving control binding changed; operator must requalify Sessions": "receiver_binding_changed",
    "Alerts receiving binding changed; operator must requalify Sessions": "alerts_binding_changed",
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class EntryScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.shared = False
        self.paths = {}

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "html":
            self.shared = attrs.get("data-shared-auth") == "true"
        if tag == "script" and isinstance(attrs.get("src"), str):
            path, _, query = attrs["src"].partition("?")
            if path in ENTRY_ASSETS:
                self.paths[path] = query


def read_response(opener, url, accept, limit):
    """Read one full response for the existing maintenance guard."""
    status, media, body, _ = read_probe_response(opener, url, accept, limit, time.monotonic() + 5)
    return status, media, body


def read_probe_response(opener, url, accept, limit, deadline, *, prefix_only=False):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    headers = {"Accept": accept, "Cache-Control": "no-cache"}
    if prefix_only:
        headers["Range"] = f"bytes=0-{limit - 1}"
    request = urllib.request.Request(url, headers=headers)
    try:
        response = opener.open(request, timeout=min(5, remaining))
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return (response.code, response.headers.get_content_type(),
                response.read(limit if prefix_only else limit + 1), response.headers.get("ETag"))


def entry_ready(opener, origin, body, deadline):
    shell = EntryScripts()
    shell.feed(body.decode("utf-8", errors="replace"))
    if not shell.shared or shell.paths.keys() != ENTRY_ASSETS:
        return False
    for path, query in shell.paths.items():
        if query and not re.fullmatch(r"v=[a-f0-9]{16}", query):
            return False
        asset = origin + (path if path.startswith("/") else ENTRY + path)
        status, media, content, etag = read_probe_response(opener, asset + ("?" + query if query else ""),
                                                           "text/javascript", 256, deadline, prefix_only=True)
        if status not in (200, 206) or media not in JAVASCRIPT_TYPES or not content:
            return False
        if query and etag != '"' + query[2:] + '"':
            return False
    return True


def probe(origin):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    deadline = time.monotonic() + 7
    status = None
    try:
        status, media, body, _ = read_probe_response(opener, origin + ACCESS, "application/json", 4096, deadline)
        detail = None
        if media == "application/json" and len(body) <= 4096:
            try:
                value = json.loads(body)
                if isinstance(value, dict) and isinstance(value.get("detail"), str):
                    detail = value["detail"]
            except (ValueError, RecursionError):
                pass
        if status == 503 and detail in BINDING_FAILURES:
            return {"origin": origin, "state": BINDING_FAILURES[detail], "access_status": status}
        if status != 401 or detail not in UNAUTHENTICATED:
            return {"origin": origin, "state": "unexpected_access_response", "access_status": status}
        entry_url = origin + ENTRY + "?view=conversation&client=standalone"
        entry_status, media, body, _ = read_probe_response(opener, entry_url, "text/html", 16384, deadline)
        ready = entry_status == 200 and media == "text/html" and entry_ready(opener, origin, body, deadline)
        return {"origin": origin, "state": "ready" if ready else "unexpected_entry_response",
                "access_status": status, "entry_status": entry_status}
    except (OSError, ValueError):
        return {"origin": origin, "state": "transport_unavailable", "access_status": status}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origins", nargs="+", help="Existing trusted Home HTTPS origins")
    args = parser.parse_args()
    if (not 1 <= len(args.origins) <= MAX_TARGETS or len(set(args.origins)) != len(args.origins)
            or any(not re.fullmatch(r"https://[a-z0-9-]{1,63}\.dmn\.homes", url)
                   for url in args.origins)):
        parser.error("Select up to 16 distinct trusted Home HTTPS origins")
    # Bound the entire pass even when a server keeps sending partial bytes.
    signal.alarm(45)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(probe, args.origins))
    finally:
        signal.alarm(0)
    print(json.dumps({"schema": "daimonapp.conversation-access-observation/v1",
                      "scope": "anonymous_public_entry", "receivers": results}, sort_keys=True))
    return 0 if all(result["state"] == "ready" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
