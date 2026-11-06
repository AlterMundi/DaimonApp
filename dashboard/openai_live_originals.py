"""Public acoustic originals enter the existing native foreground journal once.

This reserves original chronology, not a transcript, task or provider call. Native
handoffs still require a verified interpretation and an explicit formulation.
"""
import hashlib
from pathlib import Path

from .codex_voice_history import history_lock
from .provider import ProviderUnavailable
from scripts.speech_render import private_bytes


def enroll_original(history, ident, human, owner, ordinal, provider):
    if type(ordinal) is not int or not 0 <= ordinal < 32:
        raise ValueError('Select one bounded public recording ordinal')

    def receipt(value):
        return {k:v for k,v in value.items() if k not in ('interpretation','interpretation_reserve')}

    def authorized():
        if (not provider.authorized(human)
                or provider.public_live_binding(owner['binding']) != owner):
            raise ProviderUnavailable('Public original owner changed')

    authorized()
    with history_lock(history.root / '.lock'):
        value = history.read(ident, human, owner)
        recording = next((r for r in value['recordings'] if r['ordinal'] == ordinal), None)
        if recording is None:
            raise ValueError('Retain the exact public acoustic original first')
        if recording.get('capture_stop'):
            return {'state': 'review_required', 'work_admitted': False,
                    'meaning': 'Interrupted prefix is retained; its missing ending needs review.'}
        slots = value.setdefault('native_originals', {})
        key = str(ordinal)
        previous = slots.get(key)
        if previous is not None:
            if previous['id'] != recording['id'] or previous['audio_sha256'] != recording['audio_sha256']:
                raise ValueError('Native original identity changed')
            if previous['state'] == 'observed':
                return receipt(previous)
        else:
            if value.get('admission', {}).get('epoch') != history.epoch:
                raise ValueError('A restarted voice visit cannot enroll old originals')
            path = Path(str(provider.receiver['db_path']) + '.voice') / recording['id']
            data = private_bytes(path, 120 * 32000 + 44)
            if len(data) != recording['audio_bytes'] or hashlib.sha256(data).hexdigest() != recording['audio_sha256']:
                raise ValueError('Retained original bytes changed before enrollment')
            # Record before the only native write. A missing acknowledgement
            # never authorizes another submission, even if status is missing.
            slots[key] = {'id': recording['id'], 'audio_sha256': recording['audio_sha256'],
                          'state': 'intent', 'work_admitted': False}
            history._write(value)
    if previous is not None:
        try:
            authorized()
            result = provider.conversation_input_status(recording['id'])
        except (OSError, ValueError, ProviderUnavailable):
            return {**previous, 'state': 'unconfirmed'}
    else:
        authorized()
        try:
            result = provider.conversation_voice_submit(
                {'binding': owner['binding'], 'id': recording['id'],
                 'audio_sha256': recording['audio_sha256'], 'mime': 'audio/wav'},
                data, foreground_dialogue=ident, defer_foreground=True)
        except (OSError, ValueError, ProviderUnavailable):
            return {**slots[key], 'state': 'unconfirmed'}
    authorized()
    # This is the existing writer's retained original, never generated text or
    # a fabricated human utterance. Later completed interpretation is allowed.
    if (result.get('id') != recording['id'] or result.get('entry_binding') != owner['entry_binding']
            or result.get('foreground_dialogue') != ident
            or result.get('voice', {}).get('audio_sha256') != recording['audio_sha256']
            or result.get('phase') not in ('foreground_captured', 'foreground')
            or result.get('native_acceptance') != 'not_requested'):
        raise ValueError('Native acoustic original acknowledgement changed')
    with history_lock(history.root / '.lock'):
        value = history.read(ident, human, owner)
        current = value['native_originals'][key]
        if current['id'] != recording['id'] or current['audio_sha256'] != recording['audio_sha256']:
            raise ValueError('Native original intent changed')
        current.update(state='observed', phase=result['phase'], work_admitted=False,
                       meaning='Native acoustic original retained; no ASR, formulation or work requested.')
        history._write(value)
        return receipt(current)
