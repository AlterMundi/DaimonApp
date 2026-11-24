"""One Antigravity connection's loopback catalog and release boundary."""

from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from secrets import token_hex
from threading import Lock, Thread


class ProviderGate:
    def __init__(self, model, port, tools):
        self.model = model
        self.port = port
        self.tools = set(tools)
        self.challenge = "Reply with the catalog check marker: " + token_hex(16)
        self.marker = self.challenge.split()[-1]
        self.path = "/" + token_hex(32) + "/v1"
        self.checked = False
        self.released = False
        self.forwarded = 0
        self.succeeded = 0
        self.first_request = None
        self.ready_for_followup = False
        self.lock = Lock()

    def release(self):
        with self.lock:
            if not self.checked or self.released:
                raise ValueError("Unverified provider catalog")
            self.released = True

    def allow_followup(self):
        with self.lock:
            if not self.released or self.forwarded != 1 or self.ready_for_followup:
                raise ValueError("Unexpected tool result")
            self.ready_for_followup = True

    def respond(self, data):
        request = json.loads(data)
        declarations = request["tools"]
        names = set()
        for declaration in declarations:
            function = declaration["function"]
            schema = function["parameters"]
            if (
                declaration["type"] != "function"
                or schema != {"type": "object", "properties": {}}
                or function["name"] in names
            ):
                raise ValueError("Unexpected provider tool")
            names.add(function["name"])
        if names != self.tools or request["model"] != self.model:
            raise ValueError("Provider catalog or model mismatch")
        with self.lock:
            if not self.released:
                if self.checked or not any(
                    message["role"] == "user" and self.challenge in json.dumps(message["content"])
                    for message in request["messages"]
                ):
                    raise ValueError("Unexpected preflight input")
                self.checked = True
                return self._preflight(request.get("stream"))
            if self.forwarded:
                if (
                    self.forwarded != 1 or not self.ready_for_followup
                    or self.first_request == request
                    or not any(message["role"] == "tool" for message in request["messages"])
                ):
                    raise ValueError("Additional provider request refused")
            else:
                self.first_request = request
            self.forwarded += 1
        connection = HTTPConnection("127.0.0.1", self.port, timeout=35)
        try:
            connection.request("POST", "/v1/chat/completions", data, {"Content-Type": "application/json"})
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError("Selected provider declined the request")
            media = response.getheader("Content-Type", "").split(";", 1)[0]
            body = response.read(524_289)
            if media not in {"application/json", "text/event-stream"} or len(body) > 524_288:
                raise ValueError("Invalid bounded provider response")
            with self.lock:
                self.succeeded += 1
            return media, body
        finally:
            connection.close()

    def _preflight(self, stream):
        choice = {"index": 0, "finish_reason": "stop"}
        payload = {"id": "catalog-check", "created": 1, "model": self.model, "choices": [choice]}
        reply = {"role": "assistant", "content": self.marker}
        if stream:
            choice["delta"] = reply
            payload["object"] = "chat.completion.chunk"
            return "text/event-stream", ("data: " + json.dumps(payload) + "\n\ndata: [DONE]\n\n").encode()
        choice["message"] = reply
        payload["object"] = "chat.completion"
        payload["usage"] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        return "application/json", json.dumps(payload).encode()

    @contextmanager
    def serve(self):
        gate = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def setup(self):
                self.request.settimeout(40)
                super().setup()

            def do_POST(self):
                if self.path != gate.path + "/chat/completions":
                    self.send_error(404)
                    return
                try:
                    length = int(self.headers["Content-Length"])
                    if not 0 < length <= 262_144:
                        raise ValueError("Invalid provider request length")
                    media, body = gate.respond(self.rfile.read(length))
                except (KeyError, OSError, TypeError, ValueError):
                    self.send_error(400, "Provider request refused")
                    return
                self.send_response(200)
                self.send_header("Content-Type", media)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            thread.start()
            try:
                yield f"http://127.0.0.1:{server.server_port}{self.path}"
            finally:
                server.shutdown()
                thread.join()
