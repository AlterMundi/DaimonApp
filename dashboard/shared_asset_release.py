"""Bounded immutable frontend releases; account data and backend code stay outside."""
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path,PurePosixPath
import re
import shutil
import tempfile
import time

MAX_BYTES=4*1024*1024
MAX_FILES=128
MAX_RELEASES=16
SOURCE='AnnieScigliano/ASCII-Interfaces'
CONTRACT=('validate-design.mjs','experiments/school-avatar-quest/model.mjs','skills/ascii-avatar-author/scripts/model-runtime.mjs')
PUBLIC_SUFFIXES={'.mjs','.css','.html','.json','.ttf','.woff2','.txt'}

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def digest(raw):return hashlib.sha256(raw).hexdigest()
def safe_name(name):
    return isinstance(name,str) and re.fullmatch(r'[A-Za-z0-9_./-]+',name) is not None and len(name)<240 and not name.startswith('/') and '\\' not in name and all(p not in ('','..','.') for p in name.split('/')) and PurePosixPath(name).as_posix()==name

def read_beneath(root,name,limit):
    """Open each directory relative to its descriptor, never through a symlink."""
    if not safe_name(name):raise ValueError('Invalid release asset path')
    root=Path(root)
    if not root.is_absolute():raise ValueError('Release root must be absolute')
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in [*root.parts[1:],*PurePosixPath(name).parts[:-1]]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=child
        leaf=os.open(PurePosixPath(name).name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
        with os.fdopen(leaf,'rb') as stream:raw=stream.read(limit+1)
        if len(raw)>limit:raise ValueError('Release asset exceeds its bound')
        return raw
    finally:os.close(fd)

def package(vendor,revision):
    vendor=Path(vendor).resolve();provenance=json.loads(read_beneath(vendor,'PROVENANCE.json',65536))
    if provenance['source']!=SOURCE or provenance['source_revision']!=revision or not re.fullmatch('[0-9a-f]{40}',revision):raise ValueError('Wrong maintainer source')
    names=provenance['receiving_hashes'];files={}
    if not 1<=len(names)<=MAX_FILES:raise ValueError('Release file count exceeded')
    for name,expected in names.items():
        raw=read_beneath(vendor,name,1024*1024)
        if digest(raw)!=expected:raise ValueError('Unqualified receiving asset')
        files[name]=base64.b64encode(raw).decode()
    if sum(len(base64.b64decode(v)) for v in files.values())>MAX_BYTES:raise ValueError('Release byte bound exceeded')
    manifest={'schema':'daimon.shared-assets/v1','component':'avatar-workshop','source':SOURCE,'source_revision':revision,'files':dict(names),'compatibility':{n:names[n] for n in CONTRACT},'upstream_files':provenance['files'],'author':provenance['author'],'handoff_revision':provenance['handoff_revision']}
    return gzip.compress(canonical({'manifest':manifest,'files':files}),mtime=0)

def unpack(raw,baseline):
    if len(raw)>MAX_BYTES:raise ValueError('Release transfer bound exceeded')
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        body=stream.read(6*1024*1024+1)
    if len(body)>6*1024*1024:raise ValueError('Release expansion bound exceeded')
    value=json.loads(body);manifest=value['manifest'];files=value['files']
    if manifest.get('schema')!='daimon.shared-assets/v1' or manifest.get('component')!='avatar-workshop' or manifest.get('source')!=SOURCE or not re.fullmatch('[0-9a-f]{40}',manifest.get('source_revision','')):raise ValueError('Untrusted component release')
    if not 1<=len(files)<=MAX_FILES or set(files)!=set(manifest['files']):raise ValueError('Release inventory mismatch')
    if manifest.get('compatibility')!={n:digest(read_beneath(Path(baseline).resolve(),n,1024*1024)) for n in CONTRACT}:raise ValueError('Frontend needs a compatible App validator update')
    decoded={};total=0
    for name,encoded in files.items():
        if not safe_name(name) or (Path(name).suffix not in PUBLIC_SUFFIXES and name!='LICENSE'):raise ValueError('Unsupported release file')
        data=base64.b64decode(encoded,validate=True);total+=len(data)
        if len(data)>1024*1024 or total>MAX_BYTES or digest(data)!=manifest['files'][name]:raise ValueError('Release bytes changed')
        decoded[name]=data
    return manifest,decoded

def current(root):
    try:value=json.loads(read_beneath(root,'current.json',512))
    except FileNotFoundError:return None
    if set(value) not in ({'release','previous'},{'release','previous','generation'}) or not re.fullmatch('[0-9a-f]{64}',value['release']) or (value['previous'] is not None and not re.fullmatch('[0-9a-f]{64}',value['previous'])):raise ValueError('Invalid release selection')
    generation=value.get('generation',0)
    if type(generation) is not int or not 0<=generation<2**63:raise ValueError('Invalid release generation')
    return {**value,'generation':generation}

def manifest(root,release,baseline):
    if not re.fullmatch('[0-9a-f]{64}',release):raise ValueError('Invalid release identity')
    value=json.loads(read_beneath(root,release+'/manifest.json',65536))
    if digest(canonical(value))!=release or value.get('source')!=SOURCE or value.get('component')!='avatar-workshop':raise ValueError('Release identity changed')
    if value['compatibility']!={n:digest(read_beneath(Path(baseline).resolve(),n,1024*1024)) for n in CONTRACT}:raise ValueError('Incompatible selected frontend')
    return value

def prepare(root,raw,baseline):
    import fcntl
    root=Path(root)
    if root.is_symlink():raise ValueError('Release root cannot be a symlink')
    root.mkdir(parents=True,exist_ok=True,mode=0o755)
    with (root/'prepare.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        return _prepare(root,raw,baseline)

def _prepare(root,raw,baseline):
    root=Path(root);m,files=unpack(raw,baseline);release=digest(canonical(m));root.mkdir(parents=True,exist_ok=True,mode=0o755)
    selected=current(root);target=root/release
    if target.exists():
        if manifest(root,release,baseline)!=m:raise ValueError('Existing release changed')
        for n,h in m['files'].items():
            if digest(read_beneath(root,release+'/'+n,1024*1024))!=h:raise ValueError('Existing asset changed')
        return {'release':release,'current':selected['release'] if selected else None,'selection':selected,'state':'prepared'}
    known=[p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and re.fullmatch('[0-9a-f]{64}',p.name)]
    keep={selected['release'],selected['previous']} if selected else set()
    for path in known:
        if path.name not in keep and time.time()-path.stat().st_mtime>86400:
            # Only this component's verified immutable code, never actor records.
            manifest(root,path.name,baseline);shutil.rmtree(path)
    known=[p for p in root.iterdir() if p.is_dir()]
    if len(known)>=MAX_RELEASES:raise ValueError('Release history capacity reached; current frontend kept')
    stage=Path(tempfile.mkdtemp(prefix='.incoming-',dir=root))
    try:
        for n,data in files.items():p=stage/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);p.chmod(0o644)
        (stage/'manifest.json').write_bytes(canonical(m));(stage/'manifest.json').chmod(0o644)
        for p in [stage,*[p for p in stage.rglob('*') if p.is_dir()]]:p.chmod(0o755)
        stage.rename(target)
    finally:
        if stage.exists():shutil.rmtree(stage)
    return {'release':release,'current':selected['release'] if selected else None,'selection':selected,'state':'prepared'}

def activate(root,release,expected,baseline):
    """One observable compare-and-swap; exact retries never select twice."""
    import fcntl
    root=Path(root);manifest(root,release,baseline)
    with (root/'selection.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);old=current(root);previous=old['release'] if old else None
        if previous==release:return {'state':'already_selected','release':release}
        if old!=expected:raise ValueError('Later release direction changed selection')
        generation=(old['generation'] if old else 0)+1
        if generation>=2**63:raise ValueError('Release generation exhausted')
        with tempfile.NamedTemporaryFile(dir=root,delete=False) as stream:
            temporary=Path(stream.name);stream.write(canonical({'release':release,'previous':previous,'generation':generation}));stream.flush();os.fsync(stream.fileno())
        temporary.chmod(0o644);temporary.replace(root/'current.json')
    return {'state':'selected','release':release}

def asset(root,release,name,baseline):
    if not safe_name(name) or name in ('PROVENANCE.json','validate-design.mjs') or Path(name).suffix not in PUBLIC_SUFFIXES:raise FileNotFoundError(name)
    m=manifest(root,release,baseline)
    if name not in m['files']:raise FileNotFoundError(name)
    raw=read_beneath(root,release+'/'+name,1024*1024)
    if digest(raw)!=m['files'][name]:raise ValueError('Asset bytes changed')
    return raw,m['files'][name]
