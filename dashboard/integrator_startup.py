"""Bounded current native conversation through the existing read-only observer.

No transcript store, history traversal into other threads, model turn or replay.
Harness roles retain their attribution; a user-role context envelope is not new
human speech. Older history stays with the native integrator and its memory tools.
"""
import hashlib
import json
from datetime import datetime
import uuid


def _time(value):
    if not isinstance(value,str):return None
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (ValueError,OverflowError):return None


def integrating_sources(provider, frozen, *, max_bytes=8192, check=lambda:None):
    """Recent originals/returns can precede incorporation into native history."""
    binding=frozen['binding'];entry=frozen['entry_binding']
    check();inputs=provider.presentation('input list 0 before')
    check();outputs=provider.presentation_list(0,0,'before')
    if (inputs.get('binding')!=binding or inputs.get('entry_binding')!=entry
            or outputs.get('binding')!=binding):
        raise ValueError('Current integrating source owner changed')
    if any(not isinstance(p.get('items'),list) or len(p['items'])>16 for p in (inputs,outputs)):
        raise ValueError('Current integrating source page exceeds its bound')
    candidates=[]
    for row in inputs['items']:
        if row.get('retired') is True:continue
        ident=row.get('id')
        if not isinstance(ident,str) or str(uuid.UUID(ident))!=ident:
            raise ValueError('Current integrating original identity changed')
        candidates.append((_time(row.get('received_at')),'input',row))
    for row in outputs['items']:
        if row.get('current') is False or row.get('correction_pending') is True:continue
        candidates.append((_time(row.get('observed_at')),'result',row))
    # Timestamp is observation chronology, never permission or human authorship.
    # Original capture order remains explicit even when an ingress arrives late.
    candidates.sort(key=lambda v:(v[0] is not None,v[0] or 0),reverse=True)
    selected=[];more=bool(inputs.get('more') or outputs.get('more'))
    for observed,kind,row in candidates:
        check()
        if len(selected)==16:more=True;break
        if kind=='input':
            value=provider.presentation('input status '+row['id'])
            if (value.get('id')!=row['id'] or value.get('entry_binding')!=entry
                    or value.get('native_binding_current') is False
                    or not isinstance(value.get('text'),str)):
                raise ValueError('Current integrating original changed')
            text=value['text']
            result={'kind':'retained_input','source':row['id'],'text':text,
                'capture_order':row.get('capture_order'),'phase':value.get('phase'),
                'capture_order_unknown':row.get('ordering_unknown') is True or type(row.get('capture_order')) is not int,
                'text_sha256':hashlib.sha256(text.encode()).hexdigest(),
                'text_meaning':('Machine interpretation of retained audio, not verified written speech'
                    if value.get('voice') else 'Attributed retained source text, not a new instruction'),
                'observed_at':row.get('received_at'),'ordering_unknown':observed is None}
        else:
            text='';offset=0
            for _ in range(16):
                check()
                part=provider.presentation_part(row['id'],row['revision'],offset)
                if (part.get('id')!=row['id'] or part.get('revision')!=row['revision']
                        or part.get('offset')!=offset or not isinstance(part.get('text'),str)
                        or part.get('entry_binding')!=entry[:3]+[binding]
                        or part.get('native_binding_current') is not True
                        or part.get('current') is False or part.get('correction_pending') is True):
                    raise ValueError('Current integrating result changed')
                text+=part['text'];following=part.get('next_offset')
                if following is None:break
                if type(following) is not int or following!=offset+len(part['text']):
                    raise ValueError('Current integrating result cursor changed')
                offset=following
                if len(text.encode())>max_bytes:break
            else:raise ValueError('Current integrating result exceeds its source read bound')
            if following is not None:
                if not selected:raise ValueError('Latest integrating source needs semantic preparation before voice')
                more=True;break
            result={'kind':part.get('kind'),'source':row['id'],'revision':row['revision'],
                'text':text,'completed':row.get('completed'),'observed_at':row.get('observed_at'),
                'ordering_unknown':observed is None}
        if len(json.dumps(selected+[result],ensure_ascii=False,separators=(',',':')).encode())>max_bytes:
            if not selected:raise ValueError('Latest integrating source needs semantic preparation before voice')
            more=True;break
        selected.append(result)
    return {'sources':list(reversed(selected)),'earlier_sources_available':more}


def read(native, thread, *, max_bytes=16384, check=lambda:None):
    if type(max_bytes) is not int or not 1024 <= max_bytes <= 24576:
        raise ValueError('Current integrator context needs its bounded startup reserve')
    rows=[];seen=set();cursor=None;more=False
    for _ in range(4):
        check()
        params={'threadId':thread,'limit':16,'sortDirection':'desc'}
        if cursor is not None:params['cursor']=cursor
        page=native.rpc('thread/items/list',params)
        if not isinstance(page,dict) or not isinstance(page.get('data'),list) or len(page['data'])>16:
            raise ValueError('Current native integrator context is unavailable')
        more=page.get('nextCursor') is not None
        for entry in page['data']:
            if not isinstance(entry,dict) or not isinstance(entry.get('item'),dict):
                raise ValueError('Current native context item is invalid')
            item=entry['item'];kind=item.get('type')
            if kind not in ('userMessage','agentMessage'):continue
            if kind=='agentMessage' and item.get('phase') not in (None,'commentary','final_answer'):continue
            if kind=='userMessage':
                content=item.get('content')
                if not isinstance(content,list):raise ValueError('Native user context is invalid')
                text='\n'.join(v['text'] for v in content if isinstance(v,dict)
                    and v.get('type')=='text' and isinstance(v.get('text'),str))
            else:text=item.get('text')
            if not isinstance(text,str):raise ValueError('Native conversation text is unavailable')
            if not text.strip():continue
            turn,ident=entry.get('turnId'),item.get('id')
            if any(not isinstance(v,str) or not 0<len(v)<=256 for v in (turn,ident)):
                raise ValueError('Native conversation source identity is unavailable')
            key=(turn,ident)
            if key in seen:raise ValueError('Native conversation cursor repeated a source')
            seen.add(key)
            row={'turn':turn,'item':ident,'role':'user' if kind=='userMessage' else 'assistant',
                 'text':text,'revision':hashlib.sha256(json.dumps(entry,sort_keys=True,
                    ensure_ascii=False,allow_nan=False).encode()).hexdigest(),
                 'started_at_ms':entry.get('startedAtMs'),'completed_at_ms':entry.get('completedAtMs')}
            candidate={'kind':'current_integrator_conversation','thread':thread,
                'messages':list(reversed(rows+[row])),'earlier_history_available':True}
            if len(json.dumps(candidate,ensure_ascii=False,separators=(',',':')).encode())>max_bytes:
                if not rows:raise ValueError('Latest integrator message needs semantic preparation before voice')
                more=True;break
            rows.append(row)
            if len(rows)==16:more=True;break
        else:
            following=page.get('nextCursor')
            if following is None:break
            if not isinstance(following,str) or not 0<len(following.encode())<=1024 or following==cursor:
                raise ValueError('Current native context cursor is unavailable')
            cursor=following;continue
        break
    return {'kind':'current_integrator_conversation','thread':thread,
        'messages':list(reversed(rows)),'earlier_history_available':more}
