"""Bounded canonical native results to client Live context; no work dispatch."""
import hashlib
import json
import re
import time
import uuid

from .codex_voice_history import history_lock
from .openai_live import LiveUnavailable
from .provider import ProviderUnavailable


def return_native_part(history, ident, human, owner, delegation, source, revision, offset,
                       provider, sideband, *, stopped=None):
    """Read a current source, persist one append intent, then send once.

    Canonical source association is not proof of semantic incorporation, task
    completion or hearing. Long results retain their exact source/revision and
    cursor. An unknown context write never authorizes another append or work.
    """
    if (not isinstance(delegation, str) or not delegation or len(delegation.encode()) > 1024
            or not isinstance(source, str)
            or not re.fullmatch(r'(?:native:[1-9][0-9]{0,18}|delivery:[a-f0-9-]{36})', source)
            or not isinstance(revision, str) or not re.fullmatch('[a-f0-9]{64}', revision)
            or type(offset) is not int or not 0 <= offset <= 10**9):
        raise ValueError('Select an exact canonical result revision and offset')

    def authorize():
        if not provider.authorized(human) or provider.public_live_binding(owner['binding']) != owner:
            raise ProviderUnavailable('Public native result owner changed')

    def current():
        if stopped is not None and stopped.is_set():
            raise ValueError('Voice ended before a new native result append')

    current()
    authorize()
    with history_lock(history.root / '.lock'):
        value = history.read(ident, human, owner)
        work = value['delegations'].get(delegation, {})
        intent = work.get('native_work', {})
        if work.get('target') != 'client' or intent.get('state') != 'observed':
            raise ValueError('A source-bound native work acknowledgment is required')
        intent = dict(intent)
    native = provider.conversation_input_status(intent['root'])
    current()
    proof = native.get('foreground_delegation') or {}
    if (native.get('entry_binding') != owner['entry_binding'] or native.get('id') != intent['root']
            or native.get('foreground_dialogue') != ident or not isinstance(proof, dict)
            or proof.get('intent_id') != intent['intent_id']):
        raise ValueError('Native result belongs to another work intent')
    part = provider.presentation_part(source, revision, offset)
    current()
    kind = part.get('kind')
    if (part.get('id') != source or part.get('revision') != revision or part.get('offset') != offset
            or part.get('entry_binding') != owner['entry_binding'][:3] + [owner['binding']]
            or part.get('native_binding_current') is not True or part.get('current') is False
            or part.get('correction_pending') is True
            or not isinstance(part.get('text'), str) or not part['text'].strip()
            or '\0' in part['text'] or len(part['text']) > 1600
            or part.get('next_offset') is not None and (
                type(part['next_offset']) is not int or part['next_offset'] != offset + len(part['text']))):
        raise ValueError('Canonical result is stale, incomplete or belongs to another owner')
    if kind in ('integrator_answer', 'integrator_progress') and source.startswith('native:'):
        local = native.get('local_turn')
        if type(local) is not int or local <= 0 or type(part.get('local_turn')) is not int or part['local_turn'] != local:
            raise ValueError('Native answer belongs to another execution turn')
        floor = intent.get('native_source_floor')
        if type(floor) is not int or int(source.split(':')[1]) <= floor:
            raise ValueError('Native source predates this work admission boundary')
    elif kind == 'worker_result' and source.startswith('delivery:'):
        if part.get('current') is not True:
            raise ValueError('Worker result is not current')
        trace = provider.conversation_input_trace(intent['root'])
        if (trace.get('id') != intent['root'] or trace.get('entry_binding') != owner['entry_binding']
                or not any(result.get('source') == source and result.get('instruction_covered') is True
                    and result.get('current') is True and result.get('correction_pending') is False
                    for route in trace.get('routes', []) if route.get('target_available') is True
                    for result in route.get('results', []))):
            raise ValueError('Worker result has no current original-request association')
    else:
        raise ValueError('Only associated native progress/answers and canonical worker results may return')
    # A conservative UTF-8 byte cap keeps each plain-string append below the
    # documented500token bound without guessing a tokenizer. Preserve Unicode
    # and use canonical character offsets; nothing is silently discarded.
    text = part['text'].encode()[:384].decode('utf-8', errors='ignore')
    if len(text) < len(part['text']):
        # Ordinary speech should not receive half a word merely because a
        # context-append byte budget ends there. Exact cursors retain the rest.
        sentences=[m.end() for m in re.finditer(r'[.!?…]\s+',text) if m.end()>=96]
        whitespace=[m.end() for m in re.finditer(r'\s+',text)]
        boundary=max(sentences or whitespace,default=len(text))
        text=text[:boundary]
    next_offset = offset + len(text) if len(text) < len(part['text']) else part.get('next_offset')
    label = ('Native progress data' if kind == 'integrator_progress' else 'Native result data')
    content = label + (' (partial; more remains):\n' if next_offset is not None else ':\n') + text
    event_type = 'session.thinking.append' if kind == 'integrator_progress' else 'session.commentary.append'
    key = hashlib.sha256(json.dumps([delegation, source, revision, offset]).encode()).hexdigest()
    authorize()
    with history_lock(history.root / '.lock'):
        current()
        value = history.read(ident, human, owner)
        updates = value.setdefault('native_result_updates', {})
        old = updates.get(key)
        if old is not None:
            return _receipt(old)
        if (value['state'] != 'created' or value['admission']['epoch'] != history.epoch
                or time.monotonic() >= value['admission']['expires'] + 30):
            raise ValueError('Native result needs a current finite voice visit; no append attempted')
        if len(updates) >= 128:
            raise ValueError('Native result context capacity reached; retain the source cursor')
        related = [row for row in updates.values() if row['delegation'] == delegation]
        if any(row['state'] != 'context_injected' for row in related):
            raise ValueError('A previous native result append is unconfirmed; never skip or repeat it')
        if offset and not any(row['source'] == source and row['revision'] == revision
                and row['next_offset'] == offset for row in related):
            raise ValueError('Read this canonical result in exact retained cursor order')
        command = {'type': event_type, 'event_id': str(uuid.uuid4()),
            'delegation_id': delegation, 'content': content}
        updates[key] = {'state': 'intent', 'delegation': delegation, 'source': source,
            'revision': revision, 'offset': offset, 'next_offset': next_offset,
            'command': command, 'ack_reserve': ' ' * 512}
        history._write(value)
    authorize()
    if stopped is not None and stopped.is_set():
        with history_lock(history.root / '.lock'):
            value=history.read(ident,human,owner)
            row=value['native_result_updates'][key]
            row['state']='not_sent';row.pop('ack_reserve',None)
            history._write(value)
            return _receipt(row)
    try:
        sideband.send(command)
    except (OSError, ValueError, LiveUnavailable):
        authorize()
        return {**_receipt(updates[key]), 'state': 'unconfirmed'}
    with history_lock(history.root / '.lock'):
        value = history.read(ident, human, owner)
        row = value['native_result_updates'][key]
        if row['state'] == 'intent': row['state'] = 'sent'
        history._write(value)
        result = _receipt(row)
    authorize()
    return result


def _receipt(row):
    return {key: row[key] for key in ('state', 'source', 'revision', 'offset', 'next_offset')} | {
        'hearing': 'not_observed', 'work_completed': False}


def observe_append(value, event):
    """Trusted sideband only: injection ACK is not playback or task completion."""
    for row in value.get('native_result_updates', {}).values():
        command = row['command']
        if (event.get('client_event_id') == command['event_id']
                and event.get('type') == command['type'] + 'ed'):
            if row['state'] == 'context_injected': return False
            row.update(state='context_injected', ack_source=event['event_id'])
            row.pop('ack_reserve', None)
            return True
    return False
