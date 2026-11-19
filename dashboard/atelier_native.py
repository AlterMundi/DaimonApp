"""Compose Atelier with the existing owned input, session and artifact writer.

No native client, queue, provider selection or background result collector lives
here. A first explicit Send claims one frozen original before calling the existing
writer; later Sends only inspect that original. Returns use its actual trace.
"""
import hashlib
import json
from pathlib import Path
import re
import uuid

from .atelier_workshop import AtelierConflict, FILE_BYTES
from .provider import ProviderUnavailable

ASSETS = Path(__file__).parent / 'web/atelier-workshop'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class AtelierNative:
    def __init__(self, store, provider):
        self.store, self.provider = store, provider

    def _destinations(self):
        workspace = self.provider.session_workspace()
        rows = workspace.get('sessions')
        if workspace.get('destinations_state') != 'available' or not isinstance(rows, list) or len(rows) > 128:
            raise ProviderUnavailable('Open your conversation to choose a current session')
        result = []
        for row in rows:
            ref = row.get('destination')
            if ref is None:
                continue
            self.provider.check_reply(ref)
            if not ref.get('source', '').startswith('session:'):
                raise ValueError('Choose an owned session destination')
            result.append({'key': digest([row['id'], ref]), 'label': str(row['title'])[:200], 'ref': ref})
        return result

    def choices(self):
        return {'choices': [{k: r[k] for k in ('key', 'label')} for r in self._destinations()]}

    @staticmethod
    def _id(human, ident, label):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f'daimonatelier/v1/{human}/{ident}/{label}'))

    def _files(self, human, ident, raw):
        selected = [('request.clayrequest', raw.encode(), 'application/json'),
                    ('daimonatelier-tools.mjs', (ASSETS / 'tool.mjs').read_bytes(), 'text/javascript'),
                    ('daimonatelier-guide.txt', (ASSETS / 'guide.txt').read_bytes(), 'text/plain')]
        if any(len(data) > (FILE_BYTES if i == 0 else 65536) for i, (_, data, _) in enumerate(selected)):
            raise ValueError('Sculpture tool/source exceeds its receiving bound')
        return [(data, {'file_id': self._id(human, ident, name), 'name': name, 'mime': mime,
                'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}) for name, data, mime in selected]

    def send(self, human, ident, choice, reauthorize):
        saved = self.store.get(human, ident)
        frozen = self.store.dispatch(human, ident)
        if frozen is not None and frozen['choice'] != choice:
            raise AtelierConflict('This request already has a frozen destination')
        if frozen is not None and frozen['state'] != 'prepared':
            return self.status(human, ident, False)
        files = self._files(human, ident, saved['request'])
        if frozen is None:
            selected = next((r for r in self._destinations() if r['key'] == choice), None)
            if selected is None:
                raise ValueError('The destination changed; choose the session again')
            page = self.provider.conversation_inputs()
            if not re.fullmatch('[a-f0-9]{64}', page.get('binding', '')):
                raise ProviderUnavailable('Current conversation binding unavailable')
            instruction = json.loads(json.loads(saved['request'])['document'])['instruction']
            # The application envelope is explicit. A leading #Topic inside the
            # human's verbatim instruction cannot override the selected session.
            text = ('DaimonAtelier request (application-composed envelope).\n'
                    'The human selected the attached sculpture and this destination.\n'
                    'Human instruction, verbatim:\n' + instruction + '\n\n'
                    'The .clayrequest is the exact source. The attached guide/tool '
                    'describe the editable return format; they are application context.')
            body = {'binding': page['binding'], 'id': self._id(human, ident, 'input'),
                    'text': text, 'reply': selected['ref'], 'files': [ref for _, ref in files]}
            frozen = self.store.prepare_dispatch(human, ident, choice, selected['label'], body)
        if [ref for _, ref in files] != frozen['body']['files']:
            raise AtelierConflict('Prepared tool/source bytes changed; inspect the retained dispatch')
        for data, ref in files:
            reauthorize()
            self.provider.conversation_file_upload(data, ref)
        reauthorize()
        if self.store.claim_dispatch(human, ident):
            reauthorize()
            # Exactly one attempt; the native journal owns ACK/retirement and
            # deduplication. Unknown outcomes remain attempted, never restarted.
            receipt = self.provider.conversation_input_submit(frozen['body'])
            if receipt.get('id') != frozen['body']['id']:
                raise ProviderUnavailable('The native input receipt could not be confirmed')
            self.store.note_dispatch(human, ident, self._receipt(receipt))
        return self.status(human, ident, False)

    @staticmethod
    def _receipt(value):
        return {'inputId': value['id'], 'phase': str(value.get('phase', 'unconfirmed'))[:80],
                'retired': value.get('retired') is True,
                'accepted': value.get('native_acceptance') == 'observed'}

    def retry(self, human, ident, reauthorize):
        frozen = self.store.dispatch(human, ident)
        if frozen is None or frozen['state'] != 'attempted':
            raise ValueError('Inspect the original attempted dispatch first')
        reauthorize()
        # A separate explicit human action. The existing writer compares this
        # identical UUID/body and never admits it twice, including across restart.
        receipt = self.provider.conversation_input_submit(frozen['body'])
        if receipt.get('id') != frozen['body']['id']:
            raise ProviderUnavailable('The original input receipt could not be confirmed')
        self.store.note_dispatch(human, ident, self._receipt(receipt))
        return self.status(human, ident, False)

    def _results(self, frozen, source=None):
        ident = frozen['body']['id']
        trace = (self.provider.conversation_input_trace_result(ident, source) if source
                 else self.provider.conversation_input_trace(ident))
        if trace.get('id') != ident or trace.get('retired') is True:
            raise ValueError('This native request is no longer current')
        results = []
        for route in trace.get('routes', [])[:5]:
            for result in route.get('results', [])[:8]:
                if (result.get('instruction_covered') is True and result.get('current') is True
                        and result.get('correction_pending') is not True):
                    results.append(result)
        return results[:8]

    def _artifacts(self, frozen, source=None, revision=None):
        result = []
        for item in self._results(frozen, source):
            if source is not None and (item['source'] != source or item['revision'] != revision):
                continue
            part = self.provider.presentation_part(item['source'], item['revision'], 0)
            for ref in part.get('artifacts', [])[:10]:
                if (ref.get('available') is True and str(ref.get('name', '')).endswith('.clayreply')
                        and type(ref.get('bytes')) is int and 0 < ref['bytes'] <= FILE_BYTES):
                    result.append({k: ref[k] for k in ('id', 'name', 'sha256', 'bytes')} |
                                  {'source': item['source'], 'revision': item['revision']})
        return result[:10]

    def status(self, human, ident, artifacts):
        self.store.get(human, ident)
        frozen = self.store.dispatch(human, ident)
        if frozen is None:
            return {'state': 'not-sent', 'artifacts': []}
        view = {'state': frozen['state'], 'inputId': frozen['body']['id'],
                'destination': frozen['label'], 'choice': frozen['choice'], 'artifacts': [], 'origin': frozen['origin']}
        if frozen['receipt']:
            view.update(frozen['receipt'])
        if frozen['state'] == 'prepared':
            return view
        try:
            value = self.provider.conversation_input_status(frozen['body']['id'])
            if value.get('id') != frozen['body']['id']:
                raise ProviderUnavailable('Unexpected native receipt')
            view.update(self._receipt(value))
            if artifacts and view['accepted'] and not view['retired']:
                view['artifacts'] = self._artifacts(frozen)
        except (ProviderUnavailable, ValueError, OSError):
            view['state'] = 'unconfirmed'
        return view

    def collect(self, human, ident, artifact, source, revision, reauthorize):
        frozen = self.store.dispatch(human, ident)
        if frozen is None or frozen['state'] != 'attempted':
            raise ValueError('Send this request to its selected session first')
        selected = next((r for r in self._artifacts(frozen, source, revision) if r['id'] == artifact), None)
        if selected is None:
            raise ValueError('This file is not a current return for this exact input')
        reauthorize()
        ref, stream = self.provider.artifact_open(artifact)
        with stream:
            raw = stream.read(FILE_BYTES + 1)
        if (len(raw) != selected['bytes'] or len(raw) > FILE_BYTES
                or ref['sha256'] != selected['sha256'] or hashlib.sha256(raw).hexdigest() != selected['sha256']):
            raise ValueError('The returned sculpture changed or exceeds its bound')
        reauthorize()
        origin = {'inputId': frozen['body']['id'], 'artifactId': artifact, 'source': source,
                  'revision': revision, 'sha256': selected['sha256']}
        return self.store.save_reply(human, ident, raw.decode('utf-8'), native_origin=origin)
