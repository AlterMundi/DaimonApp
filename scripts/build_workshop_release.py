#!/usr/bin/env python3
"""Compose one maintainer frontend into the existing App adapter, without activation."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard import shared_asset_release as releases
from dashboard.avatar_workshop_provenance import refresh

MAX_TEXT=65536

def edits(base,value):
    return [(i,j,value[k:l]) for tag,i,j,k,l in difflib.SequenceMatcher(None,base,value,autojunk=False).get_opcodes() if tag!='equal']

def merge(base,local,incoming):
    if local==base:return incoming
    if incoming==base or local==incoming:return local
    if max(len(base),len(local),len(incoming))>MAX_TEXT:raise ValueError('Changed adapted text exceeds merge bound')
    a=edits(base,local);b=edits(base,incoming)
    for left in a:
        for right in b:
            if left==right:continue
            overlap=max(left[0],right[0])<min(left[1],right[1])
            insertion=(left[0]==left[1] and right[0]<=left[0]<=right[1]) or (right[0]==right[1] and left[0]<=right[0]<=left[1])
            if overlap or insertion:raise ValueError('Maintainer/adapter conflict; previous release kept')
    value=base
    for i,j,text in sorted(set(a+b),key=lambda e:(e[0],e[1]),reverse=True):value=value[:i]+text+value[j:]
    return value

def git_bytes(repo,revision,name):
    if not re.fullmatch('[0-9a-f]{40}',revision) or not releases.safe_name(name):raise ValueError('Invalid source selector')
    obj=revision+':'+name
    size=int(subprocess.check_output(['git','-C',str(repo),'cat-file','-s',obj],timeout=30))
    if size>1024*1024:raise ValueError('Maintainer asset exceeds1MiB')
    mode=subprocess.check_output(['git','-C',str(repo),'ls-tree',revision,'--',name],timeout=30,text=True).split()[0]
    if mode not in ('100644','100755'):raise ValueError('Source symlink is not an asset')
    return subprocess.check_output(['git','-C',str(repo),'show',obj],timeout=30)

def build(repo,revision,baseline,destination):
    baseline=Path(baseline).resolve();destination=Path(destination)
    if destination.exists():raise ValueError('Inspect retained build; do not overwrite it')
    doc=json.loads(releases.read_beneath(baseline,'PROVENANCE.json',65536));previous=doc['source_revision']
    if doc['source']!=releases.SOURCE or not re.fullmatch('[0-9a-f]{40}',previous):raise ValueError('Select the exact admitted upstream baseline')
    # Read all inputs and resolve every conflict before writing the candidate.
    files={n:releases.read_beneath(baseline,n,1024*1024) for n in doc['receiving_hashes']}
    if any(releases.digest(files[n])!=h for n,h in doc['receiving_hashes'].items()):raise ValueError('Baseline receiving bytes changed')
    upstream=dict(doc['files']);changed=[]
    for name,expected in list(upstream.items()):
        old=git_bytes(repo,previous,name)
        if releases.digest(old)!=expected:raise ValueError('Original source provenance changed')
        incoming=git_bytes(repo,revision,name)
        if incoming!=old:
            local=files[name]
            if local!=old and local!=incoming:
                try:files[name]=merge(old.decode(),local.decode(),incoming.decode()).encode()
                except (UnicodeError,ValueError):raise ValueError('Adapter conflict in selected source asset: '+name) from None
            else:files[name]=incoming
            changed.append(name)
        upstream[name]=releases.digest(incoming)
    names=subprocess.check_output(['git','-C',str(repo),'diff','--name-only','--diff-filter=A',previous,revision,'--','experiments/school-avatar-quest'],text=True,timeout=30).splitlines()
    for name in names:
        if name.endswith('/check.mjs'):continue
        if not releases.safe_name(name) or Path(name).suffix not in releases.PACKAGE_SUFFIXES:raise ValueError('New runtime dependency needs its owning adapter')
        data=git_bytes(repo,revision,name);files[name]=data;upstream[name]=releases.digest(data);changed.append(name)
    if len(files)>releases.MAX_FILES or sum(map(len,files.values()))>releases.MAX_BYTES:raise ValueError('Release inventory exceeds bounds')
    destination.mkdir(parents=True)
    for name,data in files.items():p=destination/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    doc['previous_source_revision']=previous;doc['source_revision']=revision;doc['files']=upstream
    (destination/'PROVENANCE.json').write_text(json.dumps(doc,indent=2)+'\n');refresh(destination)
    return {'source_revision':revision,'previous_source_revision':previous,'changed':changed,'bytes':sum(map(len,files.values())),'state':'prepared_not_selected'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-repo',type=Path,required=True);p.add_argument('--revision',required=True);p.add_argument('--baseline',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--package',type=Path,required=True);a=p.parse_args()
    result=build(a.source_repo,a.revision,a.baseline,a.output);raw=releases.package(a.output,a.revision)
    if a.package.exists():raise ValueError('Retained release transfer exists')
    a.package.write_bytes(raw);print(json.dumps({**result,'package_sha256':releases.digest(raw)}))

if __name__=='__main__':main()
