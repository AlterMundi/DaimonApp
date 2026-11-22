"""Exact recorded-prefix boundaries for trusted Live client delegations.

A seal is a capture boundary, not a completed human utterance or work authority.
It references existing recordings; it copies no media and starts no inference.
"""
import uuid

from .codex_voice_history import history_lock
from .provider import ProviderUnavailable


def request_seal(history, ident, human, owner, delegation, provider):
    """Persist one request before sending it. Repeated calls never reseal audio."""
    if not isinstance(delegation, str) or not delegation or len(delegation.encode()) > 1024:
        raise ValueError('Select one retained client delegation')
    _authorize(provider, human, owner)
    with history_lock(history.root / '.lock'):
        value = history.read(ident, human, owner)
        work = value['delegations'].get(delegation, {})
        if work.get('target') != 'client':
            raise ValueError('Only a trusted client delegation may request source sealing')
        if work.get('source_seal') is not None:
            return None
        if 'native_work' in work:
            raise ValueError('Native admission is already frozen; do not capture another source for that intent')
        history.check_capture(value)
        if value['state'] != 'created':
            raise ValueError('Source sealing needs the current live visit')
        seals = [row['source_seal'] for row in value['delegations'].values() if 'source_seal' in row]
        if any(row['state'] == 'requested' for row in seals):
            return None  # Another client task waits for this exact boundary.
        start = max((row['through_ordinal'] for row in seals if row['state'] in ('sealed','empty')), default=0)
        seal = {'state': 'requested', 'request': str(uuid.uuid4()), 'from_ordinal': start,
            'source': work['created_source']}
        work['source_seal'] = seal
        work['source_seal_reserve'] = ' ' * 12288
        history._write(value)
        command = {'type': 'source_seal_requested', 'visit': ident, 'binding': owner['binding'],
            'request': seal['request'], 'delegation': delegation}
    _authorize(provider, human, owner)
    return command


def accept_seal(history, ident, human, owner, body, provider):
    """Validate browser boundaries against server-recorded bytes/ordinals only.

    Browser text, timestamps, provider offsets and claims about speech ending
    cannot enter this receipt. Unknown/missing uploads preserve the pending seal.
    """
    if (not isinstance(body, dict) or set(body) != {'type','request','through_ordinal','capture_bytes'}
            or body['type'] != 'source_sealed' or not isinstance(body['request'], str)
            or type(body['through_ordinal']) is not int or not 0 <= body['through_ordinal'] <= 32
            or type(body['capture_bytes']) is not int or not 0 <= body['capture_bytes'] <= 600*32000
            or body['capture_bytes'] % 2):
        raise ValueError('Select an exact bounded recorded-prefix acknowledgment')
    _authorize(provider, human, owner)
    with history_lock(history.root / '.lock'):
        value = history.read(ident, human, owner)
        selected = [(key, work) for key, work in value['delegations'].items()
            if work.get('source_seal', {}).get('request') == body['request']]
        if len(selected) != 1:
            raise ValueError('This source seal has no retained trusted request')
        delegation, work = selected[0]
        seal = work['source_seal']
        stop = body['through_ordinal']
        if seal['state'] in ('sealed','empty'):
            if seal['through_ordinal'] != stop or seal['capture_bytes'] != body['capture_bytes']:
                raise ValueError('An acknowledged source boundary is immutable')
            return dict(seal)
        history.check_capture(value)
        if value['state'] != 'created' or stop < seal['from_ordinal']:
            raise ValueError('Source seal is not in the current capture chronology')
        prefix = {row['ordinal']: row for row in value['recordings'] if row['ordinal'] < stop}
        if (len(prefix) != stop or any(n not in prefix for n in range(stop))
                or any(row.get('capture_stop') for row in prefix.values())
                or sum(row['audio_bytes'] - 44 for row in prefix.values()) != body['capture_bytes']):
            raise ValueError('Every exact recording in this prefix must be confirmed first')
        references = [{key: prefix[n][key] for key in ('ordinal','id','audio_sha256','audio_bytes')}
            for n in range(seal['from_ordinal'], stop)]
        seal.update(state='sealed' if references else 'empty', through_ordinal=stop,
            capture_bytes=body['capture_bytes'], recordings=references, delegation=delegation,
            meaning='Exact raw capture prefix; not an utterance-end marker, interpretation or work admission.',
            work_admitted=False)
        del work['source_seal_reserve']
        history._write(value)
        result = dict(seal)
    _authorize(provider, human, owner)
    return result


def _authorize(provider, human, owner):
    if not provider.authorized(human) or provider.public_live_binding(owner['binding']) != owner:
        raise ProviderUnavailable('Public source seal owner changed')
