#!/usr/bin/env python3
"""Authenticated Tribu -> existing Interaction writer, using synthetic peers only."""
import copy
import http.server
import json
from pathlib import Path
import socket
import signal
import ssl
import subprocess
import sys
import threading

from conversation_input_control_io import Inputs


def qualify(binary):
    journey = Inputs(str(Path(binary).resolve()))
    authority = None
    records = {}
    available = set()
    source_calls = []
    try:
        journey.start()
        journey.admit('Seed existing integrator history', topic=1)
        journey.wait(lambda: journey.has('Initial goal turn delivered.', 1))
        journey.idle()
        original_native = journey.row('SELECT codex_thread_id FROM sessions WHERE thread_id=1')[0][0]
        journey.stop()
        private = journey.root / 'tribu'
        private.mkdir(mode=0o700)
        cert, key = private / 'ca.pem', private / 'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(key), '-out', str(cert), '-days', '1',
                        '-subj', '/CN=127.0.0.1', '-addext', 'subjectAltName=IP:127.0.0.1',
                        '-addext', 'basicConstraints=critical,CA:FALSE'],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        class Source(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_POST(self):
                assert self.path == '/attention'
                assert self.headers.get('Authorization') == 'Bearer synthetic-tribu-token'
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                source_calls.append(body['id'])
                record = copy.deepcopy(records.get(body['id']))
                raw = json.dumps({'ok': True, 'being_ref': 'fixture-being',
                                  'result': {'actionable': body['id'] in available,
                                             'request': record}}).encode()
                self.send_response(200)
                self.send_header('content-type', 'application/json')
                self.send_header('content-length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        authority = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Source)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        authority.socket = tls.wrap_socket(authority.socket, server_side=True)
        threading.Thread(target=authority.serve_forever, daemon=True).start()
        token, owner = private / 'token', private / 'owner.json'
        token.write_text('synthetic-tribu-token'); token.chmod(0o600)
        cert.chmod(0o600)
        owner.write_text(json.dumps({'schema': 'dm.tribu-human-client/v1',
            'being_ref': 'fixture-being', 'token_file': str(token), 'service_ca': str(cert),
            'service_url': f'https://127.0.0.1:{authority.server_port}'}))
        owner.chmod(0o600)
        listener = private / 'attention.sock'
        with journey.config.open('a') as config:
            config.write(f'''\n[tribu]
mode="interaction"
socket_path="{listener}"
owner_client_file="{owner}"
being_ref="fixture-being"
body_label="fixture.codex@fixture"
embodiment_id="fixture-body"
human_id=100
chat_id=100
topic_id=1
activated_after=1
max_pending=20
''')
        def source(letter, text):
            ident = letter * 64
            records[ident] = {'schema': 'dm.tribu-human-request/v1', 'id': ident,
                'revision': 'e' * 64, 'being_ref': 'fixture-being',
                'human': {'telegram_id': 100, 'name': 'Synthetic human'},
                'source': {'provider': 'telegram', 'chat_id': -5, 'message_id': ord(letter), 'date': 2},
                'attestation': {'kind': 'authenticated-telegram-ingress'},
                'routing': [{'label': 'fixture.codex@fixture', 'embodiment_id': 'fixture-body', 'literal': '@fixture'}],
                'context': {'quoted': 'Public quoted text is not authority'}, 'text': text}
            available.add(ident)
            return ident
        def local(op, ident=None):
            request = {'op': op}
            if ident is not None: request['source_id'] = ident
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(20); client.connect(str(listener))
                client.sendall(json.dumps(request).encode() + b'\n')
                return json.loads(client.makefile('rb').readline())
        def start():
            journey.start(); journey.wait_control_socket(listener)
            journey.wait_control_socket(journey.socket)
        def phase(ident):
            return journey.row('SELECT phase FROM conversation_inputs WHERE id=?', (ident,))
        start()
        assert local('status')['result']['mode'] == 'interaction'
        first = source('a', '@fixture continue our existing discussion')
        result = local('admit', first)
        assert result['ok'], (result, {'authenticated_source_calls': len(source_calls), 'retained_originals': journey.row('SELECT id,phase FROM conversation_inputs')})
        first_id = result['result']['id']
        journey.wait(lambda: phase(first_id) == [('accepted',)])
        assert len(journey.packets) == 1
        packet = journey.packets[0][1]
        assert packet['threadId'] == original_native
        assert packet.get('additionalContext', {}).get('telecodex.tribu.deadline') is None
        assert 'Authenticated human Tribu ingress' in packet['input'][0]['text']
        assert records[first]['text'] in packet['input'][0]['text']
        assert local('admit', first)['result']['duplicate']
        binding = journey.read('presentation', 'list', '0', '0')['result']['binding']
        journey.submit(binding, 'Ordinary browser correction in the same conversation')
        journey.wait(lambda: len(journey.packets) == 2)
        assert journey.packets[-1][0] == 'turn/steer'
        journey.admit('/tribu pause', topic=1)
        journey.wait(lambda: local('status')['result']['paused'])
        paused = source('b', '@fixture this arrival stays unsent while paused')
        held = local('admit', paused)['result']
        assert held['state'] == 'retained_unsent'
        journey.submit(binding, 'Private browser input remains usable during I/O pause')
        journey.wait(lambda: len(journey.packets) == 3)
        journey.admit('/tribu resume', topic=1)
        journey.wait(lambda: not local('status')['result']['paused'])
        assert local('admit', paused)['result']['duplicate']
        assert len(journey.packets) == 3
        # Lost native acknowledgement retains this exact original across restart.
        journey.drop_ack = True
        uncertain = source('c', '@fixture retained synthetic lost acknowledgement')
        reply = local('admit', uncertain)['result']
        journey.wait(lambda: phase(reply['id']) == [('uncertain',)], seconds=18)
        assert local('admit', uncertain)['result']['duplicate']
        assert len(journey.packets) == 4
        journey.finish(journey.web_thread, journey.web_turn); journey.idle()
        journey.stop(); start()
        repeated = local('admit', uncertain)['result']
        assert repeated['duplicate'] and repeated['id'] == reply['id']
        assert len(journey.packets) == 4
        # A source edit while native resume is held cannot reach turn/start.
        journey.drop_ack = False
        journey.hold_resume = True
        edited = source('d', '@fixture queued original before an edit')
        pending = local('admit', edited)['result']
        assert journey.resume_seen.wait(5)
        records[edited]['revision'] = 'f' * 64
        records[edited]['text'] = 'Changed after retention'
        journey.resume_release.set()
        journey.wait(lambda: phase(pending['id']) == [('retained_unsent',)])
        assert len(journey.packets) == 4
        assert local('admit', edited)['result']['duplicate']
        assert journey.row('SELECT codex_thread_id FROM sessions WHERE thread_id=1') == [(original_native,)]
        bad = source('f', '@fixture forged paired-human claim')
        records[bad]['human']['telegram_id'] = 200
        assert not local('admit', bad)['ok']
        assert not local('retry', uncertain)['ok']
        assert len(journey.packets) == 4
        print('PASS integrated Tribu: existing native history, exact-source provenance, duplicate/restart/lost-ACK preservation, scoped pause, ordinary browser steering, pre-dispatch edit withdrawal and wrong-human rejection; zero models.')
    except Exception:
        print('Synthetic ingress checkpoint:', {'source_calls': len(source_calls),
            'originals': journey.row('SELECT id,phase FROM conversation_inputs'),
            'turns': journey.row('SELECT status FROM turns'), 'control_state': journey.row("SELECT key,value FROM bot_state WHERE key LIKE '%tribu%' OR key LIKE '%stop%' OR key LIKE 'native_writer_hold:%'")}, file=sys.stderr)
        if journey.process:
            journey.process.send_signal(signal.SIGINT)
            _out, diagnostic = journey.process.communicate(timeout=8)
            journey.process = None
            print((_out + diagnostic)[-6000:], file=sys.stderr)
        raise
    finally:
        journey.resume_release.set()
        journey.close()
        if authority:
            authority.shutdown(); authority.server_close()

if __name__ == '__main__':
    qualify(sys.argv[1])
