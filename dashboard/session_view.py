"""Bounded, stateless read of one explicitly selected owned native conversation.

No native RPC/model, new transcript store, descendant traversal or file path
from a client. Roles are harness roles, not verified human authorship.
"""
import hashlib
import json
import os
import re
import stat
from collections import deque
from pathlib import Path

WINDOW=1024*1024
MAX_LINE=2*1024*1024
MAX_ITEMS=80
TEXT_PART=16000
MAX_RESPONSE=512*1024
ROUTED_INSTRUCTION = re.compile(r'^Current instruction: ([a-f0-9-]{36})$', re.MULTILINE)


def _text(value):
    if isinstance(value,str):return value
    if isinstance(value,list):
        return '\n'.join(v['text'] for v in value if isinstance(v,dict)
            and v.get('type') in ('text','input_text','output_text','summary_text')
            and isinstance(v.get('text'),str))
    return ''


def _conversation_input(text, routed_original):
    # Match the native conversation's user-request envelope. Ordinary text is
    # kept as written, including Markdown and paragraph spacing.
    text=text.replace('\r\n','\n')
    if text.lstrip().startswith(('# AGENTS.md instructions','<environment_context>')):
        _,marker,text=text.rpartition('\n\nUser request:\n')
        if not marker:return '', None
    if text.startswith('<codex_internal_context '):
        return '', None
    if text.startswith('[Interaction controller]\n'):
        header,marker,body=text.partition('\nCurrent attributed input:\n')
        instruction=ROUTED_INSTRUCTION.search(header)
        if not marker or not instruction or not routed_original:return '', None
        resolved=routed_original(instruction[1])
        if not resolved:return '', None
        original, input_id=resolved
        if not isinstance(original,str) or not body.startswith(original.replace('\r\n','\n')+'\n'):
            return '', None
        return original, input_id
    return text.partition('\n\nFollow these instructions for this turn:')[0], None



def _unique_fields(pairs):
    fields=dict(pairs)
    if len(fields)!=len(pairs):
        raise ValueError('Repeated result field')
    return fields


def _conversation_answer(text):
    # Match Telecodex's visible_answer projection. Only a trailing Coverage
    # declaration is metadata; quoted, fenced and malformed text is still prose.
    start, end='<daimon-result>', '</daimon-result>'
    visible=text.rstrip()
    if not visible.endswith(end):
        return text
    body, marker, raw=visible.rpartition('\n'+start)
    if not marker:
        if not visible.startswith(start):
            return text
        raw=visible[len(start):]
    try:
        fields=json.loads(raw[:-len(end)],object_pairs_hook=_unique_fields)
    except (ValueError,RecursionError):
        return text
    if (not isinstance(fields,dict) or not {'requests','covered'}<=fields.keys()
            or fields.keys()-{'requests','covered','completed','deferred'}
            or any(not isinstance(items,list) or any(not isinstance(item,str) for item in items)
                   for items in fields.values())):
        return text
    return body.rstrip()


def result_revision(item_id):
    if isinstance(item_id,str) and item_id:
        return hashlib.sha256(item_id.encode()).hexdigest()


def _event(record,technical,routed_original):
    if not isinstance(record,dict):return None
    p=record.get('payload',{})
    if not isinstance(p,dict) or record.get('type')!='response_item':return None
    kind=p.get('type')
    if kind=='message':
        role=p.get('role')
        if role not in ('user','assistant'):return None
        # Private analysis is never the CLI's exposed reasoning summary. Only
        # conversational assistant phases/channels enter either presentation.
        if role=='assistant' and (p.get('channel')=='analysis' or p.get('phase')=='analysis'):return None
        text=_text(p.get('content'))
        input_id=None
        if not technical:
            if role=='user':
                text,input_id=_conversation_input(text,routed_original)
            else:
                text=_conversation_answer(text)
        if not technical and not text.strip():return None
        result={'kind':'message','role':role,'text':text}
        if input_id:result['input_id']=input_id
        if not technical and role=='assistant' and p.get('phase') in (None,'final_answer','final'):
            revision=result_revision(p.get('id'))
            if revision:
                result['result_revision']=revision
        return result
    if not technical:return None
    if kind in ('function_call','custom_tool_call'):
        value=p.get('arguments') if kind=='function_call' else p.get('input')
        return {'kind':'tool_call','role':'tool','name':str(p.get('name','Tool'))[:128],
            'call_id':str(p.get('call_id',''))[:128],
            'text':value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)}
    if kind in ('function_call_output','custom_tool_call_output'):
        value=p.get('output')
        return {'kind':'tool_output','role':'tool','call_id':str(p.get('call_id',''))[:128],
            'text':_text(value) if isinstance(value,(str,list)) else json.dumps(value,ensure_ascii=False)}
    if kind=='reasoning':
        text=_text(p.get('summary'))
        if text:return {'kind':'reasoning_summary','role':'assistant','text':text}
    return None


def read(path,native,*,technical=False,revision=None,before=None,after=None,event=None,text_offset=0,expected_file=None,scan=False,routed_original=None):
    if (type(technical) is not bool or type(scan)is not bool
            or scan and before is None and after is None
            or sum(v is not None for v in (before,after,event))>1):
        raise ValueError('Select one native conversation window')
    for offset in (before,after,event,text_offset):
        if offset is not None and (type(offset) is not int or not 0<=offset<=2**63-1):
            raise ValueError('Invalid native conversation offset')
    if revision is not None and (not isinstance(revision,str) or not re.fullmatch('[a-f0-9]{64}',revision)):
        raise ValueError('Invalid native conversation revision')
    if any(v is not None for v in (before,after,event)) and revision is None:
        raise ValueError('A continuation needs its exact native file revision')
    if text_offset and event is None:raise ValueError('Select one event before reading its next part')
    # The provider has already resolved and admitted this exact owned root.
    # Refuse a final-component link/replacement between resolution and opening.
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):raise ValueError('Native history is not a regular file')
        if expected_file is not None and (info.st_dev,info.st_ino)!=expected_file:
            raise ValueError('Native history was replaced before reading')
        header=stream.readline(MAX_LINE+1)
        if len(header)>MAX_LINE or not header.endswith(b'\n'):raise ValueError('Incomplete native history identity')
        first=json.loads(header)
        if not isinstance(first,dict) or first.get('type')!='session_meta' or not isinstance(first.get('payload'),dict) or first['payload'].get('id')!=native:
            raise ValueError('Native history belongs to another session')
        identity=hashlib.sha256(json.dumps([native,info.st_dev,info.st_ino,hashlib.sha256(header).hexdigest()]).encode()).hexdigest()
        if revision is not None and revision!=identity:raise ValueError('Native history changed; select the conversation again')
        start_of_events=stream.tell();end=info.st_size
        # A writer may have appended only part of its final record. Keep the
        # next cursor at the last complete boundary so a later refresh can read
        # that record exactly once when its newline arrives.
        if end>start_of_events:
            stream.seek(end-1)
            if stream.read(1)!=b'\n':
                tail=max(start_of_events,end-MAX_LINE)
                stream.seek(tail);pending=stream.read(end-tail)
                boundary=pending.rfind(b'\n')
                if boundary<0 and tail>start_of_events:
                    raise ValueError('Incomplete native record exceeds the read bound')
                end=tail+boundary+1 if boundary>=0 else start_of_events
        skipped=0;before_scan=False;after_scan=False;scan_before=None
        if event is not None:
            if not start_of_events<=event<end:raise ValueError('Selected event is outside native history')
            if event>start_of_events:
                stream.seek(event-1)
                if stream.read(1)!=b'\n':raise ValueError('Select an exact native record boundary')
            start=event
        elif after is not None:
            if not start_of_events<=after<=end:raise ValueError('Native history cursor is unavailable')
            start=after
            if start>start_of_events and not scan:
                stream.seek(start-1)
                if stream.read(1)!=b'\n':raise ValueError('Select an exact native record boundary')
        else:
            limit=end if before is None else before
            if not start_of_events<=limit<=end:raise ValueError('Earlier native history cursor is unavailable')
            if limit>start_of_events and not scan:
                stream.seek(limit-1)
                if stream.read(1)!=b'\n':raise ValueError('Select an exact native record boundary')
            end=limit;start=max(start_of_events,end-WINDOW)
            if start>start_of_events:
                # Include the record crossing the window start, rather than
                # returning an empty non-progressing page for one long record.
                preceding=max(start_of_events,start-MAX_LINE)
                stream.seek(preceding);prefix=stream.read(start-preceding)
                boundary=prefix.rfind(b'\n')
                if boundary<0 and preceding>start_of_events:
                    # The latest window starts inside a huge record (for
                    # example an inline image). Skip only its fragment, not
                    # the readable messages after it. Earlier scans progress
                    # through that record without loading it into memory.
                    scan_before=preceding;before_scan=True;skipped+=1
                    stream.seek(start);fragment=stream.read(end-start)
                    boundary=fragment.find(b'\n')
                    start=start+boundary+1 if boundary>=0 else end
                else:start=preceding+boundary+1 if boundary>=0 else start_of_events
        latest=after is None and event is None
        stream.seek(start);items=deque();sizes=deque();consumed=0;response_bytes=0
        scan_bound=WINDOW+MAX_LINE if latest else WINDOW
        if after is not None and scan and start>start_of_events:
            stream.seek(start-1);boundary=stream.read(1)==b'\n';stream.seek(start)
            if not boundary:
                fragment=stream.read(min(WINDOW,end-start));consumed+=len(fragment)
                following=fragment.find(b'\n');skipped+=1
                if following>=0:stream.seek(start+following+1);consumed=following+1
                else:after_scan=True
        while stream.tell()<end and consumed<scan_bound and (latest or len(items)<MAX_ITEMS):
            position=stream.tell();line=stream.readline(min(MAX_LINE+1,end-position))
            if len(line)>MAX_LINE or not line.endswith(b'\n'):
                if event is not None:raise ValueError('Selected native record exceeds the read bound')
                skipped+=1;consumed+=len(line)
                # Continue past a complete oversized record if its newline is
                # within this page's remaining byte allowance. Otherwise return
                # a scan cursor, never reinterpret its JSON fragment as a row.
                if not line.endswith(b'\n') and stream.tell()<end:
                    at=stream.tell();tail=stream.read(min(end-at,max(0,scan_bound-consumed)))
                    boundary=tail.find(b'\n')
                    if boundary>=0:stream.seek(at+boundary+1);consumed+=boundary+1
                    else:consumed+=len(tail);after_scan=True
                elif not line.endswith(b'\n'):after_scan=True
                if latest and not items and scan_before is None:scan_before=position
                continue
            consumed+=len(line)
            try:record=json.loads(line)
            except (ValueError,UnicodeError):skipped+=1;continue
            value=_event(record,technical,routed_original)
            if event is not None and value is None:raise ValueError('Selected native event is not exposed in this view')
            if value is None:continue
            text=value.pop('text');size=len(text)
            if event is not None and text_offset>size:raise ValueError('Native event text offset is unavailable')
            offset=text_offset if event is not None else 0
            part=text[offset:offset+TEXT_PART]
            item={**value,'id':hashlib.sha256(f'{identity}:{position}:'.encode()+line).hexdigest()[:32],
                'position':position,'next_position':stream.tell(),'timestamp':str(record.get('timestamp',''))[:64],
                'text':part,'offset':offset,'next':offset+len(part),'characters':size,'more':offset+len(part)<size}
            encoded=len(json.dumps(item,ensure_ascii=False).encode())
            if not latest and response_bytes+encoded>MAX_RESPONSE:stream.seek(position);break
            response_bytes+=encoded;items.append(item);sizes.append(encoded)
            if latest:
                while len(items)>MAX_ITEMS or response_bytes>MAX_RESPONSE:
                    items.popleft();response_bytes-=sizes.popleft()
            if event is not None:break
        following=stream.tell()
        if latest and items:start=items[0]['position']
        if scan_before is not None:start=scan_before
        fresh=os.fstat(stream.fileno())
        if (fresh.st_dev,fresh.st_ino)!=(info.st_dev,info.st_ino) or fresh.st_size<info.st_size:
            raise ValueError('Native history changed while reading')
    return {'schema':'daimon.session-view/v1','revision':identity,'technical':technical,'items':list(items),
        'before':start,'after':following,'before_scan':before_scan,'after_scan':after_scan,
        'has_earlier':start>start_of_events,
        'more':following<end,'skipped_records':skipped,
        'links_input_ids':routed_original is not None and not technical,
        'role_meaning':'Harness message roles; input can include attributed context, not verified human speech.',
        'source_meaning':'Read-only selected native history; no work, routing, hearing or hidden reasoning is established.'}


def portable_binding(db, session, human, harness):
    generation = db.execute('''SELECT g.generation FROM conversation_entry_generations g
        JOIN sessions s ON s.id=g.session_id JOIN users u ON u.tg_user_id=s.creator_user_id
        WHERE g.session_id=? AND s.creator_user_id=? AND u.allowed=1''',
        (session, human)).fetchone()
    if generation is None:
        raise ValueError('Portable conversation binding is unavailable')
    return generation[0], hashlib.sha256(json.dumps([session, human, harness, generation[0]]).encode()).hexdigest()


def read_portable(db, session, human, harness, *, technical=False, revision=None,
                  before=None, after=None, event=None, text_offset=0, scan=False):
    """Project accepted human exchanges from the owning Gateway journal."""
    if (type(technical) is not bool or scan
            or sum(v is not None for v in (before, after, event)) > 1):
        raise ValueError('Select one portable conversation window')
    for offset in (before, after, event, text_offset):
        if offset is not None and (type(offset) is not int or not 0 <= offset < 2**63):
            raise ValueError('Invalid portable conversation offset')
    if text_offset and event is None:
        raise ValueError('Select a portable event for text continuation')
    generation, identity = portable_binding(db, session, human, harness)
    if (revision is not None or any(v is not None for v in (before, after, event))) and revision != identity:
        raise ValueError('Portable conversation binding changed')
    # Only an accepted human original can create an ordinary conversation pair.
    # Local dependencies and their returns have their own frozen audience.
    ownership = """i.session_id=? AND s.human_id=? AND i.phase='accepted'
          AND t.session_id=i.session_id AND t.from_user_id=s.human_id
          AND t.execution_harness=? AND t.execution_generation=?"""
    human_original = "NOT EXISTS (SELECT 1 FROM interaction_session_authors a WHERE a.input_id=s.id)"
    accepted = """FROM interaction_instructions i
        JOIN interaction_sources s ON s.id=i.input_id
        JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn')"""
    final = """r.local_turn=t.id AND r.native_thread=t.native_thread_id
          AND r.native_turn=json_extract(i.doc,'$.native_turn') AND r.item_id='final'
          AND length(trim(r.body))>0 AND t.status='completed'"""
    # An older Gateway can serve this dashboard during a rolling update. Its
    # selected answer remains readable before it exposes the scoped request view.
    has_request_view = db.execute("""SELECT 1 FROM sqlite_schema
        WHERE type='view' AND name='visible_portable_report_requests'""").fetchone()
    handoff_view = ('visible_portable_report_requests' if has_request_view else
                    '(SELECT id,source,session_id,human_id,local_turn,body FROM topic_publications WHERE 0)')
    source = f"""{accepted} JOIN interaction_results r ON {final}
        LEFT JOIN topic_publications p ON p.kind='portable_report' AND p.source=r.id
          AND p.session_id=i.session_id AND p.human_id=s.human_id AND p.local_turn=t.id
        LEFT JOIN topic_publications selected ON p.id IS NOT NULL AND selected.kind='portable_report_request'
          AND selected.source=p.source AND selected.session_id=p.session_id
          AND selected.human_id=p.human_id AND selected.local_turn=p.local_turn
        LEFT JOIN {handoff_view} handoff ON p.id IS NOT NULL AND handoff.source=r.id
          AND handoff.session_id=p.session_id AND handoff.human_id=p.human_id AND handoff.local_turn=p.local_turn
        WHERE {ownership} AND ({human_original}
          OR (p.id IS NOT NULL AND (selected.id IS NULL OR handoff.id IS NOT NULL)))"""
    scope = (session, human, harness, generation)
    # Keep outstanding originals separate from the append-only result cursor.
    # A final result can arrive out of order and still has its own position.
    pending_items = []
    original_id = """CASE WHEN s.channel='conversation' THEN s.event_id
        WHEN s.channel LIKE 'telegram:%' THEN 'telegram:'||s.update_id END"""
    if event is None and before is None:
        chat, topic = db.execute('SELECT chat_id,thread_id FROM sessions WHERE id=?', (session,)).fetchone()
        dispatch_binding = hashlib.sha256(json.dumps(
            [human, {'chat_id':chat, 'thread_id':topic}, session, generation],
            ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        running_here = """t.status='running' AND t.session_id=i.session_id
            AND t.from_user_id=s.human_id AND t.execution_harness=?3 AND t.execution_generation=?4"""
        native_receipt = """i.phase='submitting'
            AND json_extract(i.doc,'$.native_input_accepted')=1
            AND json_extract(i.doc,'$.native_thread')=t.native_thread_id"""
        pending = db.execute(f"""SELECT i.id,COALESCE(s.created_at,t.started_at),
                substr(json_extract(s.doc,'$.text'),1,1001),{original_id},
                CASE WHEN {native_receipt} AND {running_here} THEN 'accepted' ELSE i.phase END
            FROM interaction_instructions i JOIN interaction_sources s ON s.id=i.input_id
            LEFT JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn')
            WHERE i.session_id=?1 AND s.human_id=?2 AND {human_original}
            AND (((i.phase='accepted' OR ({native_receipt})) AND {running_here}
                  AND NOT EXISTS (SELECT 1 FROM interaction_results r WHERE {final}))
                OR (i.phase IN ('queued','submitting','steering','retained_unsent','uncertain')
                  AND json_extract(i.doc,'$.target_execution.harness')=?3
                  AND json_extract(i.doc,'$.target_execution.revision')=?5
                  AND s.origin_chat=?6 AND s.origin_thread=?7 AND s.channel LIKE 'telegram:%'
                  AND s.update_id IS NOT NULL AND s.origin_message IS NOT NULL
                  AND json_type(s.doc,'$.tribu_source') IS NOT 'object'))
            ORDER BY i.sequence DESC LIMIT 8""", (*scope, dispatch_binding, chat, topic))
        for instruction, started, text, input_id, phase in reversed(pending.fetchall()):
            if isinstance(text, str) and text.strip():
                if len(text)>1000:text=text[:1000]+'…'
                item_id = hashlib.sha256(f'{identity}:pending:{instruction}'.encode()).hexdigest()[:32]
                pending_items.append({'id':item_id,'kind':'message','role':'user','text':text,
                                      'timestamp':started,'pending':True,'portable_phase':phase})
                if input_id:pending_items[-1]['input_id']=input_id
        has_early_view = db.execute("""SELECT 1 FROM sqlite_schema
            WHERE type='view' AND name='visible_portable_handoff_inputs'""").fetchone()
        if has_early_view:
            handoffs = db.execute("""SELECT h.source,t.started_at,substr(h.body,1,1001)
                FROM visible_portable_handoff_inputs h JOIN turns t ON t.id=h.local_turn
                WHERE h.session_id=? AND h.human_id=? AND t.execution_harness=?
                  AND t.execution_generation=? AND t.status='running'
                ORDER BY h.id DESC LIMIT 8""", scope)
            for instruction, started, text in reversed(handoffs.fetchall()):
                if len(text) > 1000:
                    text = text[:1000] + '…'
                item_id = hashlib.sha256(f'{identity}:handoff:{instruction}'.encode()).hexdigest()[:32]
                pending_items.append({'id':item_id,'kind':'message','role':'assistant','text':text,
                                      'timestamp':started,'pending':True,'handoff':True})
            pending_items.sort(key=lambda item: item['timestamp'] or '')
            pending_items = pending_items[-8:]
    ordered = after is not None
    bound = after // 2 if ordered else (before // 2 if before is not None else 2**62)
    order = 'ASC' if ordered else 'DESC'
    if event is not None:
        where, bound = 'r.rowid=?', event // 2
    else:
        where = 'r.rowid>=?' if ordered else 'r.rowid<=?'
    rows = db.execute(f'''SELECT r.rowid,t.started_at,t.completed_at,
        CASE WHEN p.id IS NULL THEN json_extract(s.doc,'$.text') ELSE handoff.body END,
        r.body,{original_id},handoff.id IS NOT NULL {source} AND {where}
        ORDER BY r.rowid {order} LIMIT {MAX_ITEMS + 1}''', (*scope, bound))
    items = deque()
    total = 0
    examined_through = after
    for sequence, started, completed, original, answer, input_id, handoff in rows:
        pair = [(sequence * 2, 'assistant' if handoff else 'user', started, original),
                (sequence * 2 + 1, 'assistant', completed, _conversation_answer(answer))]
        for position, role, timestamp, text in (pair if ordered else reversed(pair)):
            if (event is not None and position != event
                    or after is not None and position < after
                    or before is not None and position >= before):
                continue
            if not isinstance(text, str) or not text.strip():
                if ordered:examined_through=position+1
                continue
            if text_offset > len(text):
                raise ValueError('Portable event text offset is unavailable')
            part = text[text_offset:text_offset+TEXT_PART]
            item = {'kind':'message', 'role':role, 'position':position, 'next_position':position+1,
                    'id':hashlib.sha256(f'{identity}:{position}'.encode()).hexdigest()[:32],
                    'timestamp':timestamp, 'text':part, 'offset':text_offset,
                    'next':text_offset+len(part), 'characters':len(text),
                    'more':text_offset+len(part)<len(text)}
            if role=='user' and input_id:item['input_id']=input_id
            total += len(json.dumps(item, ensure_ascii=False).encode())
            if len(items) == MAX_ITEMS or total > MAX_RESPONSE:
                break
            (items.append if ordered else items.appendleft)(item)
            if ordered:examined_through=position+1
        else:
            continue
        break
    if event is not None and not items:
        raise ValueError('Selected portable event is unavailable')
    first = items[0]['position'] if items else bound * 2 if ordered else 0
    following = (examined_through if ordered else
                 items[-1]['next_position'] if items else 0)
    earlier = db.execute(f'SELECT 1 {source} AND r.rowid*2<? LIMIT 1', (*scope, first)).fetchone()
    newer = db.execute(f'SELECT 1 {source} AND r.rowid*2+1>=? LIMIT 1', (*scope, following)).fetchone()
    return {'schema':'daimon.session-view/v1', 'revision':identity, 'technical':technical,
            'items':list(items), 'pending_items':pending_items, 'links_input_ids':not technical, 'before':first, 'after':following, 'has_earlier':bool(earlier),
            'more':bool(newer), 'before_scan':False, 'after_scan':False, 'skipped_records':0,
            'role_meaning':'Human originals, selected attributed handoffs and retained assistant responses.',
            'source_meaning':'Read-only portable conversation history.'}
