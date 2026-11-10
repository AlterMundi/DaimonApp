"""Compose the existing School host with this App's selected own learner."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys


def _read(path,limit):
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(descriptor,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid not in (0,os.geteuid()) or info.st_mode&0o022 or info.st_size>limit:
            raise ValueError('Unsafe selected School source')
        raw=stream.read(limit+1)
        if len(raw)>limit:raise ValueError('School source exceeds its selected bound')
        return raw


def source(selection):
    if not isinstance(selection,dict) or set(selection)!={'root','state','manifest_sha256'}:
        raise ValueError('Select the existing School source and ledger')
    root=Path(selection['root']);state=Path(selection['state'])
    for directory in (root,state):
        if not directory.is_absolute() or '..' in directory.parts:
            raise ValueError('Select absolute School paths')
        for path in [directory,*directory.parents]:
            if not stat.S_ISDIR(path.lstat().st_mode):raise ValueError('School paths must not traverse symlinks')
    info=root.stat()
    if info.st_uid not in (0,os.geteuid()) or info.st_mode&0o022:raise ValueError('Unsafe School source directory')
    raw=_read(root/'MANIFEST.json',262144)
    if len(raw)>262144 or hashlib.sha256(raw).hexdigest()!=selection['manifest_sha256']:
        raise ValueError('Selected School source manifest changed')
    manifest=json.loads(raw);rows=manifest['files']
    if not isinstance(rows,list) or not 1<=len(rows)<=64:raise ValueError('School source inventory exceeds its bound')
    seen=set();total=0
    for row in rows:
        relative=PurePosixPath(row['archive_path'])
        if relative.is_absolute() or '..' in relative.parts or not relative.parts or relative.as_posix() in seen:
            raise ValueError('Invalid School source inventory')
        seen.add(relative.as_posix());path=root/relative
        for parent in path.parents:
            if parent==root:break
            if not stat.S_ISDIR(parent.lstat().st_mode):raise ValueError('Unsafe School source path')
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid not in (0,os.geteuid()) or info.st_mode&0o022:
            raise ValueError('Unsafe selected School source')
        total+=info.st_size
        if total>2*1024*1024 or info.st_size!=row['bytes']:
            raise ValueError('School source exceeds its selected bound')
        if hashlib.sha256(_read(path,2*1024*1024)).hexdigest()!=row['sha256']:
            raise ValueError('Selected School source bytes changed')
    python_files={path.relative_to(root).as_posix() for path in (root/'scripts').rglob('*.py')}
    if python_files!={name for name in seen if name.startswith('scripts/') and name.endswith('.py')} or list((root/'scripts').rglob('*.pyc')):
        raise ValueError('School imports differ from the selected source inventory')
    if not {'scripts/schoolctl.py','scripts/learning_engine.py','scripts/ascii_mission_host.py',
            'scripts/ascii_workshop_adapter.py','curriculum/program.json','curriculum/superpowers.json'}<=seen:
        raise ValueError('Select the existing School CLI and engine')
    return root,state



def resolve_selected(config,provider,actor,request_id):
    """Existing Home/account authorization plus an operator-held own selection.

    The descriptor is configuration written by the current host owner under the
    recorded human task. It is not an invitation, grant store or browser claim.
    """
    from scripts.speech_render import private_bytes
    selected=config['school_mission']
    raw=private_bytes(Path(selected['selection']),65536)
    if hashlib.sha256(raw).hexdigest()!=selected['selection_sha256']:
        raise ValueError('School selection changed or was retired; retained work is kept')
    value=json.loads(raw)
    if (value.get('schema')!='school-creativity.app-selection/v1' or value.get('active') is not True
            or type(actor) is not int or actor!=provider.human or value.get('actor')!=actor
            or not provider.authorized(actor)
            or value.get('human_ref')!=config.get('shared_auth',{}).get('human_ref')
            or value.get('application_id')!=config.get('application_id')):
        raise KeyError('No current own School selection')
    context=value['request']
    if (context.get('request_id')!=request_id or context.get('mission_id')!='ascii'
            or context.get('space_ref')!=config['application_id']):
        raise KeyError('No current own School mission request')
    tools=json.loads(private_bytes(Path(value['tool_bindings']),131072))
    if (tools.get('learner_id')!=context.get('learner_id')
            or tools.get('companion_ref')!=context.get('daimon_ref')):
        raise ValueError('Selected School learner/companion no longer matches this App')
    return json.loads(json.dumps(context))


def compose(config,provider):
    selected=config.get('school_mission')
    if selected is None:return None
    root,state=source(selected['source'])
    # Existing living state is mandatory; never create a new ledger to make
    # composition appear ready. The source's own Ledger still owns its schema.
    database=state/'learning.sqlite3'
    if not database.is_file() or database.is_symlink():
        raise ValueError('The selected existing School ledger is unavailable')
    for name in ('ascii_mission_host','ascii_workshop_adapter','learning_engine'):
        loaded=sys.modules.get(name)
        if loaded is not None and Path(loaded.__file__).resolve()!=root/'scripts'/(name+'.py'):
            raise ValueError('Another School source is already loaded; use the scoped maintenance route')
    directory=str(root/'scripts')
    if directory not in sys.path:sys.path.insert(0,directory)
    from ascii_mission_host import AsciiMissionHost
    from learning_engine import Ledger
    def resolve(actor,request_id):
        source(selected['source'])
        return resolve_selected(config,provider,actor,request_id)
    with closing(Ledger(state)) as ledger:
        return AsciiMissionHost(ledger,resolve)
