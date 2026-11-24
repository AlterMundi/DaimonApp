#!/usr/bin/env python3
"""Actual bridge/SQLite/native-peer/Telegram-HTTP projection; all identities synthetic."""
from contextlib import contextmanager
import http.client
import http.server
import json
import signal
import subprocess
from pathlib import Path
import sys
import threading
from conversation_routing_io import CanonicalRouting


class Projected(CanonicalRouting):
    def __init__(self, binary):
        self.worker_sequence = 0
        self.direct_packets = []
        self.echo_held, self.release_echo = threading.Event(), threading.Event()
        self.hold_echo = False
        self.hold_match = "First projected input"
        self.drop_answer = False
        self.reject_echo = False
        self.rejections = 0
        self.external = False
        self.adapter = None
        self.adapter_config = None
        super().__init__(binary)

    def start(self):
        if self.external and "external_polling=true" not in self.config.read_text():
            self.config.write_text(self.config.read_text().replace(
                "[telegram]\n", "[telegram]\nexternal_polling=true\n"))
        super().start()
        if self.external:
            self.wait_control_socket(self.socket)
            self.start_adapter()

    def start_adapter(self):
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.root), "LANG": "C.UTF-8"}
        self.adapter = subprocess.Popen(
            [self.binary, "--tele-daimon-poll", str(self.adapter_config or self.config)], cwd=self.root,
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )

    def stop_adapter(self):
        if self.adapter is None:
            return
        adapter, self.adapter = self.adapter, None
        if adapter.poll() is None:
            adapter.send_signal(signal.SIGINT)
        try:
            _, error = adapter.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            adapter.kill()
            adapter.communicate(timeout=8)
            raise
        assert adapter.returncode == 0, error

    def stop(self):
        try:
            self.stop_adapter()
        finally:
            super().stop()

    def handle_extra_rpc(self, message, send):
        method, params = message.get('method'), message.get('params', {})
        native = params.get('threadId', '')
        if self.routing and native in ('native-topic-7', 'native-topic-8') and method in ('turn/start', 'turn/steer'):
            text = '\n'.join(part.get('text', '') for part in params['input'])
            if text.startswith('[Interaction controller]'):
                provenance = json.loads(next(line.removeprefix('Transport provenance: ')
                    for line in text.splitlines() if line.startswith('Transport provenance: ')))
                assert provenance['original_human_author'] == 100
                self.worker_packets.setdefault(native, []).append(params)
            else:
                self.direct_packets.append(params)
            if method == 'turn/start':
                self.worker_sequence += 1
                self.workers[native] = 'projected-turn-'+str(self.worker_sequence)
                send({'id': message['id'], 'result': {'turn': {'id': self.workers[native]}}})
                self.broadcast(native, 'turn/started', {'turn': {'id': self.workers[native], 'status': 'inProgress'}})
            else:
                send({'id': message['id'], 'result': {'turnId': self.workers[native]}})
            return True
        return super().handle_extra_rpc(message, send)

    def before_send_message_reply(self, payload):
        text = payload['text']
        if self.hold_echo and self.hold_match in text:
            self.echo_held.set()
            assert self.release_echo.wait(timeout=30), 'Synthetic mirror hold expired'
        if self.drop_answer and 'Lost mirror acknowledgment.' == text:
            self.drop_answer = False
            return False
        if self.reject_echo and 'Retryable projected input' in text:
            self.reject_echo = False
            self.rejections += 1
            return {'ok': False, 'error_code': 429, 'description': 'Synthetic known rejection',
                    'parameters': {'retry_after': 1}}

    def answer(self, topic, text, *, duplicate=False, direct=False):
        native = 'native-topic-'+str(topic)
        turn = self.workers[native]
        rows = [row for row in self.instructions(topic) if json.loads(row[2]).get('native_turn') == turn]
        requests = sorted({request for _, _, doc in rows for request in json.loads(doc)['requests']})
        claim = {'requests': requests, 'covered': [row[0] for row in rows], 'completed': requests}
        body = text if direct else text+'\n<daimon-result>'+json.dumps(claim)+'</daimon-result>'
        item = {'turnId': turn, 'item': {'id': turn+'-answer', 'type': 'agentMessage',
                                       'phase': 'final_answer', 'text': body}}
        self.broadcast(native, 'item/completed', item)
        if duplicate:
            self.broadcast(native, 'item/completed', item)
        self.broadcast(native, 'turn/completed', {'turn': {'id': turn, 'status': 'completed'}})

    def retained(self, text):
        return any(text in item['preview'] for item in
                   self.read('presentation', 'list', '0', '0')['result']['items'])

    def primary(self, text):
        return any(item['id'].startswith('delivery:') and item.get('current') is True
                   and not item.get('correction_pending') and text in item['preview']
                   for item in self.read('presentation', 'list', '0', '0')['result']['items'])

    def sent(self, text, topic):
        return sum(message['message_thread_id'] == topic and message['text'] == text
                   for message, _ in self.messages)


def qualify(binary, *, external=False):
    j = Projected(str(Path(binary).resolve()))
    j.external = external
    try:
        j.start()
        for topic in (7, 8, 1):
            j.admit('Seed existing context', topic=topic)
            j.wait(lambda: j.has('Initial goal turn delivered.', topic)); j.idle()
        j.stop()
        j.config.write_text(j.config.read_text().replace('[interaction]\n',
            '[interaction]\ntelegram_projection=true\n')+j.target_config)
        j.start(); j.wait_control_socket(j.socket); j.routing = True
        binding = j.read('presentation', 'list', '0', '0')['result']['binding']
        j.messages.clear()
        j.hold_echo = True
        original, _ = j.submit(binding, '#Alpha First projected input')
        j.wait(lambda: j.instructions(7) and j.instructions(7)[0][1] == 'accepted')
        assert j.echo_held.wait(timeout=10)
        j.answer(7, 'Primary result while mirror is held.', duplicate=True)
        j.wait(lambda: j.primary('Primary result while mirror is held.'))
        assert j.sent('Primary result while mirror is held.', 7) == 0
        j.submit(binding, '#Beta Independent parallel input')
        j.wait(lambda: j.instructions(8) and j.instructions(8)[0][1] == 'accepted')
        j.answer(8, 'Independent mirror and primary result.')
        j.wait(lambda: j.sent('Independent mirror and primary result.', 8) == 1)
        j.hold_echo = False; j.release_echo.set()
        j.wait(lambda: j.sent('Primary result while mirror is held.', 7) == 1)
        j.wait(lambda: j.row("SELECT COUNT(*) FROM topic_publications WHERE phase!='sent'") == [(0,)])
        j.idle()
        j.submit(binding, original['text'], ident=original['id'])
        assert len(j.instructions(7)) == 1
        assert j.row("SELECT COUNT(*) FROM topic_publications WHERE kind='input'") == [(2,)]
        assert j.sent('Primary result while mirror is held.', 7) == 1
        assert not any('daimon-result' in message['text'] for message, _ in j.messages)

        # Publication is never ingress: Telegram echoes its own bot-authored item.
        before = j.row('SELECT COUNT(*) FROM turns')
        echoed = next(message for message, _ in j.messages if message['text'] == 'Primary result while mirror is held.')
        with j.lock:
            j.sequence += 1; update = j.sequence
            j.updates.append({'update_id': update, 'message': echoed})
        j.wait(lambda: j.row('SELECT status FROM incoming_updates WHERE update_id=?', (update,)) == [('handled',)])
        assert j.row('SELECT COUNT(*) FROM turns') == before
        assert len(j.instructions(7)) == 1

        # Ordinary direct input uses the same native session, without router wrapping.
        direct_update=j.admit('Direct work-topic text.', topic=7)
        j.wait(lambda: len(j.direct_packets)==1 and j.row('SELECT native_turn FROM native_input_receipts WHERE update_id=?',(direct_update,))==[(j.workers['native-topic-7'],)])
        assert j.direct_packets[0]['input'][0]['text'] == 'Direct work-topic text.'
        j.answer(7, 'Direct answer once.', direct=True, duplicate=True)
        j.wait(lambda: j.sent('Direct answer once.', 7) == 1); j.idle()
        assert len(j.instructions(7)) == 1
        assert not j.retained('Direct answer once.')

        j.submit(binding, '#Alpha Input whose answer loses its mirror receipt')
        j.wait(lambda: len(j.instructions(7)) == 2 and j.instructions(7)[-1][1] == 'accepted')
        j.drop_answer = True
        j.answer(7, 'Lost mirror acknowledgment.')
        j.wait(lambda: j.primary('Lost mirror acknowledgment.'))
        j.wait(lambda: j.row("SELECT COUNT(*) FROM topic_publications WHERE phase='uncertain'") == [(1,)])
        j.idle(); j.stop(); j.start(); j.wait_control_socket(j.socket)
        assert j.sent('Lost mirror acknowledgment.', 7) == 1
        inspection = j.read('topics', 'publications')['result']
        assert any(row['phase'] == 'uncertain' for row in inspection['items'])

        j.reject_echo = True
        j.submit(binding, '#Alpha Retryable projected input')
        j.wait(lambda: len(j.instructions(7)) == 3 and j.instructions(7)[-1][1] == 'accepted')
        j.answer(7, 'New work after uncertain publication.')
        j.wait(lambda: j.sent('New work after uncertain publication.', 7) == 1)
        j.wait(lambda: j.row("SELECT COUNT(*) FROM topic_publications WHERE phase IN ('ready','publishing')") == [(0,)])
        assert j.rejections == 1
        assert j.sent('Lost mirror acknowledgment.', 7) == 1
        assert len(j.worker_packets['native-topic-7']) == 3
        if external:
            j.stop_adapter()
            pending = 'Retained projection with "quoted text".'
            j.submit(binding, '#Alpha Continue with TeleDaimon stopped')
            j.wait(lambda: len(j.instructions(7)) == 4 and j.instructions(7)[-1][1] == 'accepted')
            j.answer(7, pending + '\n\nSecond paragraph.')
            j.wait(lambda: j.primary('Retained projection with'))
            j.wait(lambda: j.row(
                "SELECT p.phase,COALESCE(x.phase,'ready') FROM topic_publications p "
                "LEFT JOIN topic_publication_parts x ON x.publication=p.id "
                "WHERE p.body LIKE 'Retained projection with%'"
            ) == [('ready', 'ready')])
            assert not any(pending in m["text"] for m, _ in j.messages)
            j.start_adapter()
            j.wait(lambda: sum(pending in m["text"] and 'Second paragraph.' in m["text"]
                              for m, _ in j.messages) == 1)
            assert j.sent('Lost mirror acknowledgment.', 7) == 1
            print('PASS stopped projection adapter leaves a ready part; reconnect publishes it once')
            j.hold_echo = True
            j.hold_match = 'Transport interrupted after submission.'
            j.echo_held.clear()
            j.release_echo.clear()
            j.submit(binding, '#Alpha Keep the independently retained result')
            j.wait(lambda: len(j.instructions(7)) == 5 and j.instructions(7)[-1][1] == 'accepted')
            j.answer(7, j.hold_match)
            assert j.echo_held.wait(timeout=10)
            j.stop_adapter()
            j.release_echo.set()
            j.wait(lambda: j.row(
                "SELECT phase FROM topic_publications WHERE body=?", (j.hold_match,)
            ) == [('uncertain',)])
            j.wait(lambda: j.primary(j.hold_match))
            polls = j.telegram_methods.count("getUpdates")
            j.start_adapter()
            j.wait(lambda: j.telegram_methods.count("getUpdates") > polls)
            assert j.sent(j.hold_match, 7) == 1
            print('PASS adapter stop after Bot API submission preserves uncertainty and the canonical result')
        print('PASS canonical event/destination identity, attributed echoes, independent return/parallel topic, direct switch, bot feedback, duplicate/restart/lost ACK and known rejection')
    finally:
        j.release_echo.set()
        j.close()

@contextmanager
def distinct_adapter_endpoint(journey):
    j = journey
    observed = []

    class AdapterAPI(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            method = self.path.rsplit("/", 1)[-1]
            content_type = self.headers.get("Content-Type", "application/json")
            received = data if self.headers.get_content_maintype() == "multipart" else json.loads(data or b"{}")
            observed.append((method, received))
            local_paths = getattr(j, "adapter_local_files", {})
            if method == "getFile" and received["file_id"] in local_paths:
                source = local_paths[received["file_id"]]
                self.reply(200, json.dumps({"ok": True, "result": {
                    "file_path": str(source), "file_size": source.stat().st_size,
                }}).encode())
                return
            self.forward(data, {"Content-Type": content_type})

        def do_GET(self):
            observed.append(("download", self.path.rsplit("/", 1)[-1]))
            self.forward(None, {})

        def forward(self, data, headers):
            conn = http.client.HTTPConnection("127.0.0.1", j.telegram.server_port, timeout=10)
            try:
                conn.request(self.command, self.path, data, headers)
                reply = conn.getresponse()
                self.reply(reply.status, reply.read())
            finally:
                conn.close()

        def reply(self, status, body):
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    relay = http.server.ThreadingHTTPServer(("127.0.0.1", 0), AdapterAPI)
    thread = threading.Thread(target=relay.serve_forever, daemon=True)
    thread.start()
    try:
        base = j.config.read_text()
        j.adapter_config = j.root / "adapter.toml"
        j.adapter_config.write_text(base.replace("[telegram]\n", "[telegram]\nexternal_polling=true\n")
                                    .replace(f":{j.telegram.server_port}", f":{relay.server_port}"))
        j.adapter_config.chmod(0o600)
        yield observed
    finally:
        relay.shutdown()
        relay.server_close()
        thread.join(timeout=5)


def direct_json_ownership(binary):
    j = Projected(str(Path(binary).resolve()))
    j.external = True
    with distinct_adapter_endpoint(j) as observed:
        try:
            j.start()
            j.admit('Establish an existing native conversation', topic=7)
            j.wait(lambda: j.has('Initial goal turn delivered.', 7))
            j.idle()
            before = len(observed)
            original = j.admit('/status', topic=7)
            j.wait(lambda: j.row("SELECT status FROM incoming_updates WHERE update_id=?", (original,))
                   == [('handled',)])
            assert any(method == "sendMessage" and payload["message_thread_id"] == 7
                       for method, payload in observed[before:]), observed[before:]
            assert len(j.row("SELECT id FROM turns")) == 1
            print("PASS direct Telegram status reached only the adapter Bot API endpoint")
        finally:
            j.close()


def direct_download_ownership(binary):
    class Downloads(Projected):
        def __init__(self, binary):
            self.native_files = set()
            super().__init__(binary)

        def handle_extra_rpc(self, message, send):
            if message.get("method") == "turn/start":
                self.native_files.update(
                    path.read_bytes() for path in self.root.glob(".telecodex/inbox/*/*_text.txt")
                )
            return super().handle_extra_rpc(message, send)

    j = Downloads(str(Path(binary).resolve()))
    j.external = True
    data = b'Synthetic attachment crosses a bounded chunk.\n' * 4000
    file_id = 'relay-attachment.txt'
    j.media_files = {file_id: data}
    local_id = 'relay-local-attachment'
    local_root = j.root / "adapter-only"
    local_root.mkdir(mode=0o700)
    source = local_root / "bot-private-route.txt"
    source.write_bytes(data[::-1])
    j.adapter_local_files = {local_id: source}

    with distinct_adapter_endpoint(j) as observed:
        try:
            j.adapter_config.write_text(j.adapter_config.read_text().replace(
                "[telegram]\n", f'[telegram]\nlocal_file_root="{local_root}"\n'))
            j.start()
            j.wait_control_socket(j.socket)
            for entry_id in (file_id, local_id):
                with j.lock:
                    original = j.admit(topic=7)
                    message = j.updates[-1]["message"]
                    message["caption"] = "Use the attached fixture text."
                    message["document"] = {"file_id": entry_id, "mime_type": "text/plain"}
                j.wait(lambda: j.row("SELECT status FROM incoming_updates WHERE update_id=?", (original,))
                       == [('settled',)])
                j.idle()
            assert j.native_files == {data, data[::-1]}
            assert [payload["file_id"] for method, payload in observed if method == "getFile"] == [file_id, local_id]
            assert [name for method, name in observed if method == "download"] == [file_id]
            print("PASS adapter resolves getFile, downloads HTTP bytes and copies trusted local bytes before Gateway admission")
        finally:
            j.close()



if __name__ == '__main__':
    external = "--external" in sys.argv[2:]
    qualify(sys.argv[1], external=external)
    if external:
        direct_json_ownership(sys.argv[1])
        direct_download_ownership(sys.argv[1])
