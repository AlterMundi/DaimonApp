"""Account-scoped immutable workshop versions in the existing App state root.

No renderer activation, voice/provider change or browser-local authority. The
caller supplies an authenticated human; HTTP grants/CSRF remain the App's job.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid

from .codex_voice_history import history_lock
from .avatar_workshop_voice import WorkshopVoiceRevisions,voice_state
from .voice_studio_batches import WorkshopPreviewBatches,preview_state
from .private_state import private_directory
from scripts.speech_render import atomic, private_bytes


_validators=threading.BoundedSemaphore(2)
_validator=Path(__file__).parent/'web/avatar-workshop/validate-design.mjs'


class WorkshopConflict(ValueError):
    pass


def validate_design(design):
    """Reuse the original inert-model/design validator with finite CPU/heap."""
    raw=json.dumps(design,ensure_ascii=False,allow_nan=False).encode()
    if len(raw)>1024*1024:raise ValueError('Avatar import exceeds 1MiB')
    node=shutil.which('node')
    if not node:raise ValueError('The workshop validator is unavailable; previous avatar is kept')
    if not _validators.acquire(blocking=False):raise ValueError('The workshop validator is busy')
    try:
        result=subprocess.run([node,'--max-old-space-size=64',str(_validator)],input=raw,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=4,check=False)
        if result.returncode or len(result.stdout)>2*1024*1024:raise ValueError('Invalid workshop design')
        value=json.loads(result.stdout)
        canonical=value['canonical']
        if (not isinstance(canonical,str) or len(canonical.encode())>512*1024
                or value['sha256']!=hashlib.sha256(canonical.encode()).hexdigest()
                or json.loads(canonical).get('schema')!='ascii-quest-design/v2'):
            raise ValueError('Invalid workshop canonical design')
        return canonical,value['sha256']
    except (OSError,subprocess.TimeoutExpired,KeyError,TypeError,json.JSONDecodeError):
        raise ValueError('Workshop validation unavailable; previous avatar is kept') from None
    finally:_validators.release()


class AvatarWorkshop(WorkshopVoiceRevisions,WorkshopPreviewBatches):
    """One atomic actor document: revisions and pointers commit together.

    The configured App state root belongs to one receiving being. Actor IDs
    come only from existing authentication, never an import or browser field.
    Quota refusal is the stop path; no automatic version/media deletion runs.
    """
    conflict_error=WorkshopConflict
    max_versions=32
    max_actor_bytes=8*1024*1024
    max_actors=64
    max_total_bytes=32*1024*1024

    def __init__(self,state_root):
        self.root=private_directory(Path(state_root)/'avatar-workshop')

    def _path(self,human):
        if type(human) is not int or not 0<human<2**63:raise ValueError('Invalid workshop actor')
        return self.root/(str(human)+'.json')

    @staticmethod
    def _ident(value):
        if not isinstance(value,str) or str(uuid.UUID(value))!=value:raise ValueError('Invalid revision identity')
        return value

    def _read(self,human):
        path=self._path(human)
        if not path.exists() and not path.is_symlink():
            return {'schema':'daimon.avatar-workshop/v1','human':human,'generation':0,
                    'versions':[],'editing':None,'active':None}
        value=json.loads(private_bytes(path,self.max_actor_bytes))
        if (value.get('schema')!='daimon.avatar-workshop/v1' or value.get('human')!=human
                or type(value.get('generation')) is not int or not 0<=value['generation']<2**53
                or not isinstance(value.get('versions'),list) or len(value['versions'])>self.max_versions):
            raise ValueError('Workshop state needs review; no reset was performed')
        if 'voice' in value:voice_state(value)
        if 'voice_previews' in value:preview_state(value)
        return value

    def _write(self,human,value):
        raw=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
        if len(raw)>self.max_actor_bytes:raise ValueError('Avatar version storage is full; export before removing versions')
        path=self._path(human);files=list(self.root.glob('*.json'))
        if len(files)+(path not in files)>self.max_actors:raise ValueError('Workshop actor storage is full')
        charge=0
        for entry in files:
            info=entry.lstat()
            if entry.is_symlink() or not entry.is_file():raise ValueError('Unsafe workshop state')
            if entry!=path:charge+=info.st_size
        if charge+len(raw)>self.max_total_bytes:raise ValueError('Workshop storage is full')
        atomic(path,raw)

    @staticmethod
    def _summary(value):
        return {'schema':value['schema'],'generation':value['generation'],
            'editing':value['editing'],'active':value['active'],
            'versions':[{k:r[k] for k in ('id','parentId','artId','name','createdAt','sha256')}
                        for r in value['versions']]}

    def snapshot(self,human):
        with history_lock(self.root/'.lock'):return self._summary(self._read(human))

    def get(self,human,ident):
        self._ident(ident)
        with history_lock(self.root/'.lock'):
            value=self._read(human)
            row=next((r for r in value['versions'] if r['id']==ident),None)
            if row is None:raise KeyError('Avatar revision unavailable for this account')
            if hashlib.sha256(row['canonical'].encode()).hexdigest()!=row['sha256']:
                raise ValueError('Avatar revision needs review')
            return {k:copy.deepcopy(v) for k,v in row.items() if k!='canonical'}|{'design':json.loads(row['canonical'])}

    @staticmethod
    def _expected(value,expected):
        if type(expected) is not int or expected!=value['generation']:
            raise WorkshopConflict('Avatar selection changed; refresh without replaying the action')

    def save(self,human,ident,design,parent,expected):
        self._path(human);self._ident(ident)
        if parent is not None:self._ident(parent)
        canonical,digest=validate_design(design)
        normalized=json.loads(canonical)
        with history_lock(self.root/'.lock'):
            value=self._read(human)
            old=next((r for r in value['versions'] if r['id']==ident),None)
            if old is not None:
                if old['sha256']!=digest or old['parentId']!=parent:raise WorkshopConflict('A saved avatar revision is immutable')
                return self._summary(value)  # Exact lost-ACK readback, no pointer mutation.
            self._expected(value,expected)
            if parent is not None and not any(r['id']==parent for r in value['versions']):
                raise KeyError('Avatar parent is unavailable for this account')
            if parent is not None and next(r for r in value['versions'] if r['id']==parent)['artId']!=normalized['artId']:
                raise ValueError('An avatar version must preserve its design identity')
            if len(value['versions'])+len(voice_state(value)['versions'])>=self.max_versions:raise ValueError('Avatar version capacity reached')
            value['versions'].append({'id':ident,'parentId':parent,'artId':normalized['artId'],
                'name':normalized['name'],'createdAt':int(time.time()*1000),
                'canonical':canonical,'sha256':digest})
            value['editing']=ident;value['generation']+=1
            self._write(human,value)
            return self._summary(value)

    def select(self,human,ident,expected,*,activate=False):
        """Preview/edit selection and explicit use have distinct durable pointers."""
        self._ident(ident)
        if type(activate) is not bool:raise ValueError('Select an explicit avatar action')
        with history_lock(self.root/'.lock'):
            value=self._read(human);self._expected(value,expected)
            if not any(r['id']==ident for r in value['versions']):raise KeyError('Avatar revision unavailable for this account')
            value['active' if activate else 'editing']=ident;value['generation']+=1
            self._write(human,value)
            return self._summary(value)
