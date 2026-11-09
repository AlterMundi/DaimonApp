#!/usr/bin/env python3
"""One bounded maintainer update across registered App consumers; no models."""
import argparse
import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard import shared_asset_release as assets
from scripts.build_workshop_release import build

SOURCE_URL='https://github.com/AnnieScigliano/ASCII-Interfaces.git'
SOURCE_REF='refs/heads/poc/school-avatar-quest'
MAX_CACHE=64*1024*1024

# Executed through the configured existing transport. Drop to the ACTUAL service
# UID before touching its state directory; no privileged write through actor data.
RECEIVER=r'''
import base64,hashlib,json,os,signal,stat,subprocess,sys,tomllib
from pathlib import Path
signal.alarm(30)
x=json.loads(sys.stdin.read(6*1024*1024+1));service=x['service'];cfg=Path(x['config'])
env={**os.environ,**({'XDG_RUNTIME_DIR':'/run/user/1000','DBUS_SESSION_BUS_ADDRESS':'unix:path=/run/user/1000/bus'} if x.get('user') else {})}
command=['systemctl',*(['--user'] if x.get('user') else []),'show',service,'--value','-p','MainPID'];pid=subprocess.check_output(command,env=env,text=True).strip();assert pid!='0'
runtime=Path('/proc',pid,'cwd').resolve();uid=Path('/proc',pid).stat().st_uid
info=cfg.lstat();assert stat.S_ISREG(info.st_mode) and info.st_uid==uid and not info.st_mode&0o077
before=cfg.read_bytes();c=tomllib.loads(before.decode());state=Path(c['state_dir']).resolve();assert state.is_absolute()
if os.geteuid()!=uid:
 assert os.geteuid()==0;os.setgroups([]);os.setgid(info.st_gid);os.setuid(uid)
sys.path.insert(0,str(runtime));from dashboard import shared_asset_release as r
root=state/'shared-app-assets/avatar-workshop';vendor=runtime/'dashboard/web/avatar-workshop'
if (root/'disabled').exists():raise ValueError('Consumer explicitly disabled shared frontend updates')
if x['action']=='prepare':out=r.prepare(root,base64.b64decode(x['package'],validate=True),vendor)
elif x['action']=='activate':out=r.activate(root,x['release'],x['expected'],vendor)
elif x['action']=='status':out={'state':'observed','current':r.current(root)}
else:raise ValueError('Unknown supported update operation')
assert cfg.read_bytes()==before
assert subprocess.check_output(command,env=env,text=True).strip()==pid
assert Path('/proc',pid,'cwd').resolve()==runtime
out.update(native_restart=False,web_restart=False,provider_calls=0,service_uid=uid)
print(json.dumps(out))
'''

def atomic(path,value):
    raw=assets.canonical(value)
    if len(raw)>65536:raise ValueError('Update receipt bound exceeded')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as stream:
        temporary=Path(stream.name);stream.write(raw);stream.flush();os.fsync(stream.fileno())
    temporary.chmod(0o600);temporary.replace(path)

def target_call(target,action,**payload):
    argv=[target.get('python','python3'),'-B','-c',RECEIVER]
    if target.get('guest'):argv=['sudo','-n','incus','exec',target['guest'],'--',*argv]
    transport=target.get('transport',[])
    command=transport+([shlex.join(argv)] if target.get('ssh') else argv)
    raw=assets.canonical({'action':action,'service':target['service'],'config':target['config'],'user':target.get('user',False),**payload})
    try:
        value=subprocess.run(command,input=raw,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45)
    except subprocess.TimeoutExpired:raise ValueError('Consumer observation timed out; inspect exact retained selection') from None
    if value.returncode or len(value.stdout)>8192:raise ValueError('Consumer update refused; previous code/state kept')
    return json.loads(value.stdout)

def deploy(config,package,state):
    """Resume exact file selections by observation, never replay an unknown write."""
    encoded=base64.b64encode(package).decode();targets=config['targets']
    if not 1<=len(targets)<=32 or len({t['id'] for t in targets})!=len(targets):raise ValueError('Invalid consumer inventory')
    state.setdefault('targets',{});state['package_sha256']=assets.digest(package)
    for target in targets:
        if config.get('_config_path') and assets.digest(Path(config['_config_path']).read_bytes())!=config['_config_sha256']:
            state['state']='partial_update_retained';atomic(state['receipt_path'],state);return state
        row=state['targets'].setdefault(target['id'],{'phase':'known_unattempted'})
        binding=assets.digest(assets.canonical(target))
        if row.get('binding_sha256',binding)!=binding:
            row.update(phase='binding_changed',error='consumer_binding_changed');atomic(state['receipt_path'],state);continue
        row['binding_sha256']=binding
        if target.get('enabled',True) is False:
            row.update(phase='opted_out');atomic(state['receipt_path'],state);continue
        try:
            if row.get('uncertain_until',0)>time.time():continue
            observed=target_call(target,'status')['current'];current=observed['release'] if observed else None
            if row.get('release')==current and row.get('release'):
                row.update(phase='adopted_verified',observation_only=True);continue
            if row['phase']=='activation_uncertain':
                # The remote helper's30s lifetime has elapsed. Current file is
                # authoritative; a later selection is never overwritten.
                if current!=row['expected']:raise ValueError('Later consumer direction changed')
                row['phase']='prepared'
            if row['phase'] in ('known_unattempted','failed'):
                prepared=target_call(target,'prepare',package=encoded);row.update(phase='prepared',release=prepared['release'],expected=prepared['current'])
                atomic(state['receipt_path'],state)
            if config.get('_config_path') and assets.digest(Path(config['_config_path']).read_bytes())!=config['_config_sha256']:
                state['state']='partial_update_retained';atomic(state['receipt_path'],state);return state
            row.update(phase='activation_uncertain',uncertain_until=time.time()+60);atomic(state['receipt_path'],state)
            selected=target_call(target,'activate',release=row['release'],expected=row['expected']);assert selected['release']==row['release']
            actual=target_call(target,'status')['current'];assert actual and actual['release']==row['release']
            row.update(phase='adopted_verified',native_restart=False,web_restart=False,provider_calls=0);row.pop('error',None)
        except (OSError,ValueError,AssertionError,KeyError):
            if row['phase']!='activation_uncertain':row['phase']='failed'
            row['error']='shared_frontend_update_incomplete'
        finally:atomic(state['receipt_path'],state)
    state['state']='all_consumers_adopted_verified' if all(state['targets'].get(t['id'],{}).get('phase') in ('adopted_verified','opted_out') for t in targets) else 'partial_update_retained'
    atomic(state['receipt_path'],state);return state

def directory_bytes(path):return sum(p.stat().st_size for p in Path(path).rglob('*') if p.is_file() and not p.is_symlink())

def run(config_path):
    config_path=Path(config_path);info=config_path.lstat()
    if info.st_uid!=os.getuid() or info.st_mode&0o077 or not config_path.is_file() or config_path.is_symlink():raise ValueError('Select the existing private owner configuration')
    raw=config_path.read_bytes();c=json.loads(raw);c['_config_path']=str(config_path);c['_config_sha256']=assets.digest(raw)
    if c.get('source_url')!=SOURCE_URL or c.get('source_ref')!=SOURCE_REF:raise ValueError('Select the admitted maintainer production source')
    state_root=Path(c['state_root']);state_root.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (state_root/'update.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'state':'existing_update_running'}
        receipt=state_root/'current.json';old=json.loads(receipt.read_text()) if receipt.exists() else None
        if old and old['state']!='all_consumers_adopted_verified':
            package=Path(old['package_path']).read_bytes()
            if assets.digest(package)!=old['package_sha256']:raise ValueError('Retained transfer changed')
            return deploy(c,package,old)
        cache=state_root/'source.git'
        if not cache.exists():
            subprocess.run(['git','init','--bare',str(cache)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True,timeout=15)
            subprocess.run(['git','-C',str(cache),'remote','add','origin',SOURCE_URL],check=True,timeout=15)
        if directory_bytes(cache)>MAX_CACHE:raise ValueError('Maintainer source cache reached64MiB')
        subprocess.run(['git','-C',str(cache),'-c','protocol.file.allow=never','fetch','--depth=1','--filter=blob:none','origin',SOURCE_REF],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=90)
        revision=subprocess.check_output(['git','-C',str(cache),'rev-parse','FETCH_HEAD'],text=True,timeout=5).strip()
        if not re.fullmatch('[0-9a-f]{40}',revision):raise ValueError('Invalid maintainer source identity')
        if old and old.get('source_revision')==revision:
            # Newly registered consumers join the existing current release.
            package=Path(old['package_path']).read_bytes()
            if assets.digest(package)!=old['package_sha256']:raise ValueError('Retained transfer changed')
            old['observed_at']=time.time()
            return deploy(c,package,old)
        baseline=Path(c['baseline']).resolve();doc=json.loads((baseline/'PROVENANCE.json').read_text());previous=doc['source_revision']
        if previous!=revision:
            subprocess.run(['git','-C',str(cache),'-c','protocol.file.allow=never','fetch','--depth=1','--filter=blob:none','origin',previous],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=90)
        build_root=Path(c['build_root']);build_root.mkdir(parents=True,exist_ok=True,mode=0o700)
        # One replaceable code-only build; never a production account/state copy.
        work=build_root/'candidate';temporary=build_root/'temporary'
        if work.exists():shutil.rmtree(work)
        if temporary.exists():shutil.rmtree(temporary)
        temporary.mkdir(mode=0o700)
        result=build(cache,revision,baseline,work)
        try:
            env={**os.environ,**c['qualification_environment'],'QUALIFICATION_WORKSHOP_ROOT':str(work),'TMPDIR':str(temporary)}
            qualified=subprocess.run(c['qualification_command'],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=130)
            (state_root/'qualification.log').write_bytes(qualified.stdout[-65536:])
            if qualified.returncode:raise ValueError('Maintainer update failed existing editor/store qualification')
            package=assets.package(work,revision)
        finally:
            if work.exists():shutil.rmtree(work)
            if temporary.exists():shutil.rmtree(temporary)
        if directory_bytes(cache)>MAX_CACHE:raise ValueError('Maintainer source cache reached64MiB')
        if config_path.read_bytes()!=raw:raise ValueError('Later update configuration changed')
        if old:atomic(state_root/'previous.json',old)
        package_path=state_root/'current.release.gz';previous_package=state_root/'previous.release.gz'
        if package_path.exists():package_path.replace(previous_package)
        package_path.write_bytes(package);package_path.chmod(0o600)
        value={'schema':'daimon.shared-application-update/v1','state':'prepared','source_revision':revision,'source':assets.SOURCE,'package_path':str(package_path),'package_sha256':assets.digest(package),'receipt_path':str(receipt),'created_at':time.time(),'observed_at':time.time(),'qualification':result,'provider_calls':0,'targets':{}}
        atomic(receipt,value);return deploy(c,package,value)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);a=p.parse_args();signal.alarm(600)
    try:value=run(a.config);print(json.dumps({'state':value['state'],'source_revision':value.get('source_revision'),'consumers':{k:v['phase'] for k,v in value.get('targets',{}).items()},'provider_calls':0}));return 0 if value['state'] in ('all_consumers_adopted_verified','existing_update_running') else 1
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):
        print('Shared application update failed; previous frontend and account state retained.',file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
