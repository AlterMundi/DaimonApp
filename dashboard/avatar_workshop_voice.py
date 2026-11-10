"""Voice revisions inside the existing account workshop document and quotas.

Profiles are inert exact API/model/voice references. The authenticated adapter
must offer only receiving-compatible profiles; this store performs no discovery,
provider call, microphone access or change to an already frozen conversation.
"""
import copy
import hashlib
import json
import re
import time

from .codex_voice_history import history_lock


def voice_state(document):
    value=document.get('voice',{'generation':0,'versions':[],'active':None})
    if (not isinstance(value,dict) or set(value)!={'generation','versions','active'}
            or type(value['generation']) is not int or not 0<=value['generation']<2**53
            or not isinstance(value['versions'],list) or len(value['versions'])>32
            or value['active'] is not None and not any(
                isinstance(r,dict) and r.get('id')==value['active'] for r in value['versions'])):
        raise ValueError('Voice revisions need review; previous selection is kept')
    return value


def voice_profile(profile,delivery):
    if (not isinstance(profile,dict) or set(profile)!={'provider','api','model','voice'}
            or profile['provider']!='openai' or profile['api'] not in ('gpt-live','realtime')
            or any(not isinstance(profile[key],str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,128}',profile[key])
                   for key in ('model','voice'))
            or not isinstance(delivery,str) or '\0' in delivery or len(delivery.encode())>1024):
        raise ValueError('Select a bounded compatible voice and delivery instruction')
    canonical=json.dumps({'profile':profile,'delivery':delivery},sort_keys=True,separators=(',',':'),ensure_ascii=False)
    return canonical,hashlib.sha256(canonical.encode()).hexdigest()


class WorkshopVoiceRevisions:
    """Mixin: same root, actor document, lock, atomic writer and storage limits."""
    @staticmethod
    def _voice_summary(value):
        voice=voice_state(value)
        return {'generation':voice['generation'],'active':voice['active'],
                'versions':[copy.deepcopy(r) for r in voice['versions']]}

    def voice_snapshot(self,human):
        with history_lock(self.root/'.lock'):return self._voice_summary(self._read(human))

    def voice_save(self,human,ident,profile,delivery,parent,expected,name=None):
        self._ident(ident)
        if parent is not None:self._ident(parent)
        if name is not None and (not isinstance(name,str) or not name.strip()
                or '\0' in name or len(name)>80 or len(name.encode())>320):
            raise ValueError('Give this voice a name of at most80characters')
        canonical,digest=voice_profile(profile,delivery)
        with history_lock(self.root/'.lock'):
            value=self._read(human);voice=voice_state(value)
            old=next((r for r in voice['versions'] if r['id']==ident),None)
            if old is not None:
                if old['sha256']!=digest or old['parentId']!=parent or old.get('name')!=name:
                    raise self.conflict_error('A saved voice revision is immutable')
                return self._voice_summary(value)
            self._expected(voice,expected)
            if parent is not None and not any(r['id']==parent for r in voice['versions']):
                raise KeyError('Voice parent unavailable for this account')
            if len(value['versions'])+len(voice['versions'])>=self.max_versions:
                raise ValueError('Workshop version capacity reached')
            content=json.loads(canonical)
            voice=copy.deepcopy(voice)
            voice['versions'].append({'id':ident,'parentId':parent,'createdAt':int(time.time()*1000),
                                      **content,'sha256':digest,**({'name':name} if name is not None else {})})
            voice['generation']+=1;value['voice']=voice
            self._write(human,value)
            return self._voice_summary(value)

    def voice_select(self,human,ident,expected,compatible_profiles):
        """Explicit next-conversation pointer; never alters a frozen session."""
        self._ident(ident)
        with history_lock(self.root/'.lock'):
            value=self._read(human);voice=voice_state(value);self._expected(voice,expected)
            row=next((r for r in voice['versions'] if r['id']==ident),None)
            if row is None:raise KeyError('Voice revision unavailable for this account')
            _,digest=voice_profile(row['profile'],row['delivery'])
            if digest!=row['sha256']:raise ValueError('Voice revision needs review')
            if row['profile'] not in compatible_profiles:
                raise ValueError('This voice is not available for the selected service')
            voice=copy.deepcopy(voice);voice['active']=ident;voice['generation']+=1
            value['voice']=voice;self._write(human,value)
            return self._voice_summary(value)

    def voice_for_conversation(self,human,compatible_profiles):
        """Copy once at logical creation; replacements must keep that snapshot."""
        with history_lock(self.root/'.lock'):
            value=self._read(human);voice=voice_state(value)
            if voice['active'] is None:return None
            row=next(r for r in voice['versions'] if r['id']==voice['active'])
            _,digest=voice_profile(row['profile'],row['delivery'])
            if digest!=row['sha256']:raise ValueError('Voice revision needs review')
            if row['profile'] not in compatible_profiles:
                raise ValueError('Selected voice needs review for this service')
            return copy.deepcopy(row)
