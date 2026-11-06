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


def _text(value):
    if isinstance(value,str):return value
    if isinstance(value,list):
        return '\n'.join(v['text'] for v in value if isinstance(v,dict)
            and v.get('type') in ('text','input_text','output_text','summary_text')
            and isinstance(v.get('text'),str))
    return ''


def _event(record,technical):
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
        return {'kind':'message','role':role,'text':_text(p.get('content'))}
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


def read(path,native,*,technical=False,revision=None,before=None,after=None,event=None,text_offset=0,expected_file=None,scan=False):
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
            value=_event(record,technical)
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
        'role_meaning':'Harness message roles; input can include attributed context, not verified human speech.',
        'source_meaning':'Read-only selected native history; no work, routing, hearing or hidden reasoning is established.'}
