"""Real App/owner socket/SQLite/native output; numerical synthetic peer, zero models."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fastapi.testclient import TestClient
from dashboard.app import create_app
from dashboard.atelier_native import digest
from dashboard.provider import Provider, ProviderUnavailable
from dashboard.companion import Grants
from conversation_routing_io import CanonicalRouting
from conversation_files_http_io import received_originals
from dashboard_atelier_workshop import fixtures


class NumericalPeer(CanonicalRouting):
    def handle_extra_rpc(self, message, send):
        p = message.get('params', {})
        if self.routing and message.get('method') == 'turn/start' and p.get('threadId') == 'native-topic-7':
            text = '\n'.join(v.get('text', '') for v in p['input'])
            originals = json.loads(text.split('[Retained original file attachments]\n', 1)[1].splitlines()[0])
            by_name = {r['name']: Path(r['local_path']) for r in originals}
            context = ''.join(v['value'] for k, v in sorted(p['additionalContext'].items())
                              if k == 'telecodex.runtime' or k.startswith('telecodex.runtime.'))
            self.output = Path(re.search(r'\n([^\n]+/out)\n', context).group(1)) / 'proposal.clayreply'
            result = subprocess.run(['node', '--max-old-space-size=192', str(by_name['daimonatelier-tools.mjs']),
                'stretch', str(by_name['request.clayrequest']), str(self.output), 'y', '1.15'], capture_output=True, check=True)
            assert json.loads(result.stdout)['kind'].startswith('Explicit CPU')
        return super().handle_extra_rpc(message, send)


def qualify(binary):
    j = NumericalPeer(str(Path(binary).resolve())); client = None
    try:
        j.start()
        for topic in (7, 8, 1):
            j.admit('Seed existing owned context', topic=topic)
            j.wait(lambda: j.has('Initial goal turn delivered.', topic)); j.idle()
        j.stop()
        retained = j.root / 'retained'; retained.mkdir(mode=0o700)
        j.config.write_text(j.config.read_text() + '\n[interaction.artifact_store]\ndirectory=' +
                            json.dumps(str(retained)) + '\nmax_file_bytes=8388608\nmax_total_bytes=67108864\n' + j.target_config)
        j.start(); j.wait_control_socket(j.socket); j.routing = True; j.messages.clear()
        config = {'receiver_config': str(j.config), 'state_dir': str(j.root / 'dashboard'),
                  'origin': 'https://example.test', 'bot_id': 123,
                  'companion': {'enabled': True, 'grants_dir': str(j.root / 'grants')}}
        provider = Provider(config)
        def open_client():
            return TestClient(create_app(config, provider, lambda raw, bot: int(raw)), base_url=config['origin'])
        client = open_client()
        token = client.post('/api/session', json={'init_data': '100'}, headers={'origin': config['origin']}).json()['session_token']
        headers = {'authorization': 'Bearer ' + token, 'origin': config['origin']}
        headers['x-dashboard-csrf'] = client.get('/api/state', headers=headers).json()['csrf']
        base = '/api/interaction/atelier'
        f = fixtures(); envelope = json.loads(f['request']); doc = json.loads(envelope['document'])
        doc['instruction'] = '#Beta /interrupt is literal sculpture text, not the selected destination'
        envelope['document'] = json.dumps(doc, ensure_ascii=False, separators=(',', ':'))
        envelope['sha256'] = hashlib.sha256(envelope['document'].encode()).hexdigest()
        raw = json.dumps(envelope, ensure_ascii=False); ident = doc['id']
        def post(body):
            return client.post(base, json=body, headers=headers)
        assert post({'action': 'save-request', 'request': raw}).status_code == 200
        choices = client.get(base + '/destinations', headers=headers); assert choices.status_code == 200, choices.text
        session = next(r for r in provider.session_workspace()['sessions'] if r['audio_key'] == '100:7')
        choice = digest([session['id'], session['destination']]); assert any(r['key'] == choice for r in choices.json()['choices'])
        body = {'action': 'dispatch', 'requestId': ident, 'choice': choice}
        assert post({**body, 'binding': 'forged'}).status_code == 400
        assert client.post(base, json=body, headers={**headers, 'x-dashboard-csrf': 'wrong'}).status_code == 403
        grants = Grants(config, provider)
        credential_path = j.root / 'device.json'
        enrolled = grants.enroll('Synthetic scoped Atelier client', credential_path, 60)
        credential = json.loads(credential_path.read_text())
        device = {'authorization': credential['authorization'], 'origin': config['origin']}
        device['x-dashboard-csrf'] = client.get('/api/interaction/inputs', headers=device).json()['csrf']
        assert client.get(base + '/destinations', headers=device).status_code == 403
        assert client.post(base, json=body, headers=device).status_code == 403
        before = j.row('SELECT count(*) FROM conversation_inputs')
        submit = Provider.conversation_input_submit
        attempts = []
        def lost_ack(selected_provider, original):
            attempts.append(original['id'])
            submit(selected_provider, original)
            raise ProviderUnavailable('Synthetic lost HTTP acknowledgment after real native retention')
        with patch.object(Provider, 'conversation_input_submit', lost_ack):
            result = post(body)
        assert result.status_code == 503, result.text
        input_id = client.get(base + '/requests/' + ident + '/native', headers=headers).json()['inputId']
        j.wait(lambda: j.instructions(7) and j.instructions(7)[0][1] == 'accepted')
        assert not j.instructions(8), 'Instruction hashtag overrode the selected session'
        original = provider.conversation_input_status(input_id)
        assert doc['instruction'] in original['text'] and original['text'].startswith('DaimonAtelier request')
        assert len(original['files']) == 3
        received_originals(j.worker_packets['native-topic-7'][-1], original['files'])
        j.answer_worker(7, 'A numerical synthetic peer returned an editable proposal.')
        def status():
            value = client.get(base + '/requests/' + ident + '/native', headers=headers)
            assert value.status_code == 200, value.text
            return value.json()
        j.wait(lambda: status()['artifacts'])
        selected = status()['artifacts'][0]
        grants.workspace(enrolled['grant_id'], True)
        assert client.get(base + '/requests/' + ident + '/native', headers=device).json()['artifacts'] == []
        collect = {'action': 'collect', 'requestId': ident, 'artifactId': selected['id'],
                   'source': selected['source'], 'revision': selected['revision']}
        assert client.post(base, json=collect, headers=device).status_code == 403
        assert post({**collect, 'artifactId': str(uuid.uuid4())}).status_code == 400
        assert post({**body, 'choice': '0' * 64}).status_code == 409
        result = post({'action': 'collect', 'requestId': ident, 'artifactId': selected['id'],
                       'source': selected['source'], 'revision': selected['revision']})
        assert result.status_code == 200, result.text
        assert result.json()['reply'] == j.output.read_text()
        assert status()['origin']['inputId'] == input_id
        turns = j.row('SELECT count(*) FROM turns')
        assert post(body).status_code == 200
        assert post({'action': 'retry-dispatch', 'requestId': ident}).status_code == 200
        assert j.row('SELECT count(*) FROM conversation_inputs') == [(before[0][0] + 1,)]
        assert j.row('SELECT count(*) FROM turns') == turns
        assert attempts == [input_id]
        client.close(); provider = Provider(config); client = open_client()
        assert status()['origin']['inputId'] == input_id
        assert client.get(base + '/requests/' + ident, headers=headers).json()['reply'] == j.output.read_text()
        assert j.row('SELECT count(*) FROM turns') == turns
        assert not j.messages, 'Canonical request produced Telegram speech'
        print('PASS actual App/owner/native roundtrip, chosen session over literal hashtag, source/tool/guide originals, lost ACK with one input/attempt, workspace/artifact entitlements, foreign-file refusal, numerical child revision, canonical collect and restart without replay; zero models')
    finally:
        if client: client.close()
        j.close()


if __name__ == '__main__':
    qualify(sys.argv[1])
