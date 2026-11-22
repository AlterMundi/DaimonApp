"""Freeze input-speaker language from the existing trusted Live journal.

No provider, ASR or second transcript store. A window associates approximate
provider fragments with an acoustic group, never exact words per audio chunk.
"""
import hashlib
import json
import math

from .codex_voice_history import history_lock


def freeze_input_window(history, ident, human, owner, delegation):
    with history_lock(history.root / '.lock'):
        value = history.read(ident, human, owner)
        work = value['delegations'].get(delegation, {})
        if work.get('target') != 'client' or work.get('source_seal', {}).get('state') != 'sealed':
            raise ValueError('Select a trusted delegation with a confirmed acoustic group')
        if 'live_window' in work:
            return json.loads(json.dumps(work['live_window']))
        history.check_capture(value)
        previous = [row['live_window']['proof'] for row in value['delegations'].values()
                    if 'live_window' in row]
        predecessor = max(previous, key=lambda row: row['journal_after']) if previous else None
        start = predecessor['journal_after'] if predecessor else 0
        revision = predecessor['journal_revision'] if predecessor else None
        after = start; raw = bytearray(); text = ''; inputs = records = 0
        for _ in range(128):
            page = history.source_page(ident, human, owner['binding'], after=after,
                revision=revision, with_offsets=True, with_raw_records=True)
            revision = page['revision']
            for row, offset, line in zip(page['items'], page['offsets'], page['raw_records'], strict=True):
                records += 1; raw.extend(line)
                if records > 8192 or len(raw) > 4*1024*1024:
                    raise ValueError('Complete Live input source window exceeds its bound')
                event = row['event']
                if event['type'] != 'session.input_transcript.delta':
                    continue
                encoded = json.dumps(event, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
                delta = event.get('delta'); begin = event.get('start_ms'); end = event.get('end_ms')
                if (hashlib.sha256(encoded).hexdigest() != row['sha256']
                        or event.get('event_id') != row['event_id']
                        or not isinstance(delta, str) or not delta or '\0' in delta or len(delta.encode()) > 12000
                        or any(type(n) not in (int, float) or not math.isfinite(n) for n in (begin, end))
                        or not 0 <= begin <= end <= 86400000):
                    raise ValueError('Live input source fragment changed')
                text += delta; inputs += 1
                if len(text.encode()) > 65536:
                    raise ValueError('Complete Live input language exceeds its bound')
            after = page['after']
            if not page['more']:
                break
        else:
            raise ValueError('Complete Live input source scan exceeds its bound')
        if not text.strip() or not inputs or after <= start:
            raise ValueError('No retained Live input language; keep originals without another ASR')
        result = {'path': str(history.root / (ident+'.events')), 'text': text,
            'proof': {'dialogue': ident, 'journal_revision': revision, 'journal_from': start,
                'journal_after': after, 'journal_sha256': hashlib.sha256(raw).hexdigest(),
                'text_sha256': hashlib.sha256(text.encode()).hexdigest(), 'input_events': inputs}}
        work['live_window'] = result
        history._write(value)
        return json.loads(json.dumps(result))
