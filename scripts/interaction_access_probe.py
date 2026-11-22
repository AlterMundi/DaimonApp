#!/usr/bin/env python3
"""Check the existing public Conversation entry and its anonymous access fence."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import re
import signal
import urllib.error
import urllib.request

MAX_TARGETS = 16
ENTRY = "/interaction/"
ACCESS = ENTRY + "api/interaction/access"
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


def read_response(opener, url, accept, limit):
    request = urllib.request.Request(url, headers={"Accept": accept, "Cache-Control": "no-cache"})
    try:
        response = opener.open(request, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.code, response.headers.get_content_type(), response.read(limit + 1)


def probe(origin):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    status = None
    try:
        status, media, body = read_response(opener, origin + ACCESS, "application/json", 4096)
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
        entry_status, media, body = read_response(opener, entry_url, "text/html", 16384)
        ready = entry_status == 200 and media == "text/html" and b'data-shared-auth="true"' in body
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
