"""Configured frame presentation only; existing Home/auth/input writers own access."""
import re
import uuid
from urllib.parse import urlsplit


def parent_origins(config):
    values=config.get('conversation_surface',{}).get('parent_origins',[])
    if not isinstance(values,list) or len(values)>8:raise ValueError('Select at most eight exact surface parent origins')
    for value in values:
        if not isinstance(value,str):raise ValueError('Select an exact HTTPS parent origin')
        parsed=urlsplit(value)
        if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment or parsed.netloc!=parsed.hostname+((':'+str(parsed.port)) if parsed.port else '')
                or not re.fullmatch(r'https://[a-z0-9.-]+(?::[0-9]+)?',value)):
            raise ValueError('Select an exact HTTPS parent origin')
    return tuple(values)


def selection(request,config,shared_enabled):
    if request.query_params.get('surface') is None:return None
    q=request.query_params;parent=q.get('surface_parent');visit=q.get('surface_visit','')
    if (not shared_enabled or q.get('surface')!='holodeck' or q.get('view')!='conversation'
            or q.get('client')!='standalone' or parent not in parent_origins(config)):
        raise ValueError('Conversation surface unavailable')
    try:
        if str(uuid.UUID(visit))!=visit:raise ValueError('Invalid surface visit')
    except (ValueError,TypeError):raise ValueError('Invalid surface visit') from None
    return {'parent':parent,'visit':visit}
