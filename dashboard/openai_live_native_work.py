"""Source-bound client delegation to the existing native execution owner.

Server component only, not mounted. The caller must first seal the intended
acoustic sources and supply a separately attributed formulation. A provider
delegation contains no task text; transcript deltas are never work authority.
"""
import hashlib
import json
import uuid

from .codex_voice_history import history_lock
from .provider import ProviderUnavailable


def delegate_native(history, ident, human, owner, delegation, ordinals, formulation, provider):
    """Retain one intent, then submit once; uncertain outcomes only read status.

    This admits the original/formulation to the existing integrator, not a
    selected worker. Retention, queueing and native acceptance are not completion.
    No ASR, provider turn, fallback, question answer or native replay is performed.
    """
    if (not isinstance(delegation, str) or not delegation or len(delegation.encode()) > 1024
            or not isinstance(ordinals, list) or not 1 <= len(ordinals) <= 8
            or any(type(n) is not int or not 0 <= n < 32 for n in ordinals)
            or ordinals != sorted(set(ordinals))
            or not isinstance(formulation, str) or not formulation.strip()
            or '\0' in formulation or len(formulation.encode()) > 8192):
        raise ValueError('Select ordered acoustic sources and a bounded assistant formulation')

    def authorize():
        if not provider.authorized(human) or provider.public_live_binding(owner['binding']) != owner:
            raise ProviderUnavailable('Public native work owner changed')

    def select(value):
        work = value['delegations'].get(delegation)
        if not work or work.get('target') != 'client':
            raise ValueError('A trusted client delegation is required, not a transcript fragment')
        seal = work.get('source_seal')
        if seal is not None and (seal.get('state') != 'sealed'
                or [r['ordinal'] for r in seal['recordings']] != ordinals):
            raise ValueError('Native work must use the exact acknowledged capture window, never an uncertain or empty seal')
        sources = []
        for ordinal in ordinals:
            recording = next((r for r in value['recordings'] if r['ordinal'] == ordinal), None)
            slot = value.get('native_originals', {}).get(str(ordinal), {})
            interpreted = slot.get('interpretation', {})
            if seal is not None and recording is not None and seal['recordings'][ordinals.index(ordinal)] != {
                    key: recording[key] for key in ('ordinal','id','audio_sha256','audio_bytes')}:
                raise ValueError('Native source no longer matches the acknowledged capture seal')
            if (recording is None or recording.get('capture_stop')
                    or slot.get('state') != 'observed' or slot.get('id') != recording['id']
                    or slot.get('audio_sha256') != recording['audio_sha256']
                    or interpreted.get('state') != 'completed' or interpreted.get('model') != 'gpt-transcribe'
                    or interpreted.get('capture_id') != recording['id']
                    or interpreted.get('audio_sha256') != recording['audio_sha256']
                    or slot.get('native_commit', {}).get('state') != 'observed'
                    or not isinstance(interpreted.get('text'), str) or not interpreted['text'].strip()):
                raise ValueError('Each exact acoustic source needs a completed native interpretation')
            sources.append({'id': recording['id'], 'audio_sha256': recording['audio_sha256'],
                'text_sha256': hashlib.sha256(interpreted['text'].encode()).hexdigest()})
        if sum(len(value['native_originals'][str(n)]['interpretation']['text'].encode()) for n in ordinals) > 65536:
            raise ValueError('Native source context exceeds its bound')
        return work, sources

    authorize()
    fresh = False
    with history_lock(history.root / '.lock'):
        value = history.read(ident, human, owner)
        work, _ = select(value)
        needs_boundary = 'native_work' not in work
    source_floor = None
    if needs_boundary:
        # Read outside the journal lock. A retained answer from before this
        # admission must not be returned as a new result of the delegated work.
        page = provider.presentation_list(0, 0, 'before')
        source_floor = page.get('newest', {}).get('native')
        if (page.get('binding') != owner['binding'] or type(source_floor) is not int
                or not 0 <= source_floor <= 2**63 - 1):
            raise ValueError('Native work needs a current canonical source boundary')
        authorize()
    with history_lock(history.root / '.lock'):
        value = history.read(ident, human, owner)
        work, sources = select(value)
        previous = work.get('native_work')
        if previous:
            if previous['sources'] != sources or previous['formulation'] != formulation:
                raise ValueError('A retained native work intent cannot be reformulated or replaced')
            if previous['state'] == 'observed':
                return dict(previous)
        else:
            history.check_capture(value)
            # The native writer independently fences the latest captured
            # correction atomically. Never remove that guard to accept a chunk.
            if any(other.get('native_work', {}).get('root') == sources[-1]['id']
                    for other in value['delegations'].values()):
                raise ValueError('This original root already belongs to another retained work intent')
            previous = {'state': 'intent', 'intent_id': str(uuid.uuid4()),
                'root': sources[-1]['id'], 'sources': sources, 'formulation': formulation,
                'native_source_floor': source_floor, 'work_completed': False}
            work['native_work'] = previous
            work['native_work_reserve'] = ' ' * 2048
            history._write(value)
            fresh = True
        if previous['state'] != 'intent':
            raise ValueError('Native work receipt is unavailable')
        intent = json.loads(json.dumps(previous))

    body = {'binding': owner['binding'], 'id': intent['root'], 'intent_id': intent['intent_id'],
        'formulation': formulation, 'source_ids': [s['id'] for s in sources]}
    authorize()
    try:
        native = (provider.conversation_foreground_delegate(body) if fresh
                  else provider.conversation_input_status(intent['root']))
    except (OSError, ValueError, ProviderUnavailable):
        # Even a rejected local wrapper can hide an already admitted native
        # write. Preserve the exact intent and never issue a second submission.
        authorize()
        return {**intent, 'state': 'unconfirmed'}
    proof = native.get('foreground_delegation')
    if (native.get('id') != intent['root'] or native.get('entry_binding') != owner['entry_binding']
            or native.get('foreground_dialogue') != ident or not isinstance(proof, dict)
            or proof.get('intent_id') != intent['intent_id'] or proof.get('dialogue_id') != ident
            or proof.get('formulation') != formulation or not isinstance(proof.get('sources'), list)
            or len(proof['sources']) != len(sources)):
        raise ValueError('Native work acknowledgment does not prove this exact source-bound intent')
    by_id = {source['id']: source for source in sources}
    seen = set()
    for actual in proof['sources']:
        if not isinstance(actual, dict) or actual.get('id') not in by_id or actual['id'] in seen:
            raise ValueError('Native work source identity changed')
        expected = by_id[actual['id']]
        seen.add(actual['id'])
        if (actual.get('text_sha256') != expected['text_sha256']
                or not isinstance(actual.get('text'), str)
                or hashlib.sha256(actual['text'].encode()).hexdigest() != expected['text_sha256']
                or not isinstance(actual.get('voice'), dict)
                or actual['voice'].get('audio_sha256') != expected['audio_sha256']):
            raise ValueError('Native work source snapshot changed')
    orders = [source.get('capture_order') for source in proof['sources']]
    if (any(type(order) is not int or order <= 0 for order in orders)
            or orders != sorted(set(orders)) or proof['sources'][-1]['id'] != intent['root']):
        raise ValueError('Native source chronology is not proven')
    with history_lock(history.root / '.lock'):
        value = history.read(ident, human, owner)
        work, _ = select(value)
        if work.get('native_work') != intent:
            if work.get('native_work', {}).get('state') == 'observed':
                authorize()
                return dict(work['native_work'])
            raise ValueError('Native work intent changed before acknowledgment')
        work['native_work'].update(state='observed',
            meaning='Exact formulation and acoustic sources retained by the native integrator; work completion and hearing are not established.')
        del work['native_work_reserve']
        history._write(value)
        receipt = dict(work['native_work'])
    # Preserve the observed native effect even if access changed during its IO;
    # revocation prevents exposing the result, never causes another submission.
    authorize()
    return receipt
