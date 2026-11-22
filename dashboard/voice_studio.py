"""Configured OpenAI identity and frozen studio choices; no provider discovery."""
import copy
import re
import uuid
from .avatar_workshop_voice import voice_profile

# Official GPT-Live voice options; regional labels are not language restrictions.
# https://developers.openai.com/api/docs/guides/live-conversations#voice-options
LIVE_VOICES=('marin','cedar','quartz','ripple','vesper','willow','stone','gleam',
    'meridian','bossa','tempo','beacon','delta','cinder','nuri','juni','flitz',
    'brise','sillage','nira','harema','shida','noeul')


def configured_profiles(config):
    selected=config.get('openai_live',{})
    voice=selected.get('session_options',{}).get('audio',{}).get('output',{}).get('voice')
    if selected.get('enabled') is not True or not isinstance(voice,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',voice):
        return []
    # Public built-ins plus this receiver's explicit current identity. No
    # account/custom-voice discovery, permission change or provider call.
    approved=config.get('voice_studio',{}).get('voices',[])
    if (not isinstance(approved,list) or len(approved)>len(LIVE_VOICES)
            or any(not isinstance(name,str) or name not in LIVE_VOICES for name in approved)):
        raise ValueError('Select documented receiving-qualified studio voices')
    return [{'provider':'openai','api':'gpt-live','model':'gpt-live-1','voice':name}
            for name in dict.fromkeys((voice,*approved))]


def choice(revision,profile):
    delivery=revision['delivery'] if revision is not None else ''
    actual=revision['profile'] if revision is not None else profile
    if actual!=profile:raise ValueError('Selected voice needs review for this service')
    _,digest=voice_profile(actual,delivery)
    if revision is not None and revision['sha256']!=digest:raise ValueError('Voice revision needs review')
    return {'revision':revision['id'] if revision is not None else None,
            'profile':copy.deepcopy(actual),'delivery':delivery,'sha256':digest}


def validate_choice(value):
    if not isinstance(value,dict) or set(value)!={'revision','profile','delivery','sha256'}:
        raise ValueError('Select an exact frozen voice choice')
    if value['revision'] is not None and (not isinstance(value['revision'],str)
            or str(uuid.UUID(value['revision']))!=value['revision']):
        raise ValueError('Voice revision identity changed')
    _,digest=voice_profile(value['profile'],value['delivery'])
    if value['sha256']!=digest:raise ValueError('Frozen voice choice changed')
    return copy.deepcopy(value)


def apply_choice(spec,value,compatible_profiles=None):
    value=validate_choice(value);profile=value['profile'];result=copy.deepcopy(spec)
    if (profile['api']!='gpt-live' or profile['model']!=result['model']
            or not isinstance(result.get('audio'),dict) or not isinstance(result['audio'].get('output'),dict)
            or (profile not in compatible_profiles if compatible_profiles is not None
                else profile['voice']!=result.get('audio',{}).get('output',{}).get('voice'))):
        raise ValueError('The frozen voice is incompatible with this connection')
    result['audio']['output']['voice']=profile['voice']
    if value['delivery']:
        result['instructions']+='\nVoice delivery only; preserve identity, language, pronunciation and execution instructions:\n'+value['delivery']
        if len(result['instructions'].encode())>8192:raise ValueError('Voice delivery exceeds the existing instruction bound')
    return result
