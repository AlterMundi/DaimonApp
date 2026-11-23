#!/usr/bin/env python3
"""Fence one existing, finite web-only operator; never select/stop services here."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.interaction_access_probe import BINDING_FAILURES, NoRedirect, UNAUTHENTICATED, read_response
from dashboard.private_state import private_directory, write_json
from dashboard.voice_admission import HEADER, COVERAGE_HEADER, COVERAGE, MAINTENANCE_FD, maintenance_guard


def private_config(path, owner_uid):
    fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=owner_uid or info.st_mode&0o077:
            raise ValueError('Select an owner-private configuration')
        data=stream.read(65537)
        if len(data)>65536:
            raise ValueError('Selected configuration exceeds the maintenance bound')
        return data


def observer_transition(preimage, receiver, expected_sha256):
    if hashlib.sha256(receiver).hexdigest()!=expected_sha256:
        raise ValueError('Planned receiver bytes changed')
    before=tomllib.loads(preimage.decode())
    after=tomllib.loads(receiver.decode())
    original=before.get('interaction')
    upcoming=after.get('interaction')
    if not isinstance(original,dict) or not isinstance(upcoming,dict):
        raise ValueError('An existing Conversation receiver is required')
    previous=original.pop('observer_model',None)
    current=upcoming.pop('observer_model',None)
    if previous==current or before!=after:
        raise ValueError('Only the explicitly prepared observer model transition is supported')
    if any(value is not None and (not isinstance(value,str) or not value or len(value.encode())>128
            or not value.isprintable() or any(c.isspace() for c in value)) for value in (previous,current)):
        raise ValueError('Select a bounded observer model')


def access_state(opener, access_url):
    def expired(_signum, _frame):
        raise TimeoutError('Conversation access check exceeded its deadline')
    previous=signal.signal(signal.SIGALRM,expired)
    signal.alarm(6)
    try:
        status,media,body=read_response(opener, access_url, 'application/json', 4096)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM,previous)
    if media!='application/json' or len(body)>4096:
        return None
    value=json.loads(body)
    detail=value.get('detail') if isinstance(value,dict) else None
    if not isinstance(detail,str):
        return None
    if status==503:
        return BINDING_FAILURES.get(detail)
    if status==401 and detail in UNAUTHENTICATED:
        return 'anonymous_refused'
    return None


def claim_observer_repair(path, receipt):
    """Retain the exact possible write before starting the selected operator."""
    if not path.parent.is_dir():
        raise ValueError('The selected private repair directory must already exist')
    parent = private_directory(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(receipt, stream)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--health-url',required=True)
    parser.add_argument('--owner-uid',type=int,default=os.getuid())
    parser.add_argument('--seconds',type=int,default=180)
    parser.add_argument('--require-speech',action='store_true',help='Require the serving reader to fence Conversation synthesis too')
    parser.add_argument('--observer-preimage',type=Path)
    parser.add_argument('--receiver-sha256',help='Exact planned native configuration digest')
    parser.add_argument('--observer-receipt',type=Path,help='One owner-private receipt per prepared repair')
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args(argv)
    command=args.command[1:] if args.command[:1]==['--'] else args.command
    url=urllib.parse.urlsplit(args.health_url)
    if (not command or not 1<=args.seconds<=300 or args.owner_uid<0
            or url.scheme not in ('http','https') or not url.hostname
            or url.username or url.password or url.query or url.fragment):
        parser.error('Select the current private config, local health route and one bounded operator')
    repair=args.observer_preimage is not None
    if args.observer_receipt is not None and (not repair or not args.observer_receipt.is_absolute()):
        parser.error('Select an absolute receipt path for the exact observer repair')
    if (repair != (args.receiver_sha256 is not None) or repair and (
            not re.fullmatch(r'[a-f0-9]{64}',args.receiver_sha256)
            or url.hostname not in ('127.0.0.1','::1') or url.path!='/health' or not args.require_speech)):
        parser.error('Select a pinned observer transition with the loopback voice and speech fence')
    try:
        raw=private_config(args.config,args.owner_uid)
        config=tomllib.loads(raw.decode())
        root=Path(config['state_dir'])
        if not root.is_absolute():raise ValueError('Select an absolute state directory')
    except (OSError,ValueError,KeyError,TypeError):
        parser.error('Select the actual service user private configuration')
    timeout=shutil.which('timeout')
    if not timeout:parser.error('The existing finite-command timeout utility is required')
    operator_started=False
    try:
        with maintenance_guard(root,owner_uid=args.owner_uid) as guard:
            # A leftover file after rollback, or another state root, is not proof
            # that the currently serving process participates in the fence.
            with urllib.request.urlopen(args.health_url,timeout=3) as response:
                body=response.read(8193)
                if (response.headers.get(HEADER)!=guard.header
                        or args.require_speech and response.headers.get(COVERAGE_HEADER)!=COVERAGE
                        or len(body)>8192
                        or json.loads(body)!={'ok':True}):
                    raise ValueError('Selected server does not advertise this exact voice lock')
            if args.config.read_bytes()!=raw:
                raise ValueError('Selected configuration changed before maintenance')
            # timeout + the operator inherit the same open file description.
            # The kernel keeps exclusion through exec and releases on exit/death.
            bounded=[timeout,'--signal=TERM','--kill-after=5',str(args.seconds),*command]
            if not repair:
                os.set_inheritable(guard.fd,True)
                os.execv(timeout,bounded)
            receiver=Path(config['receiver_config'])
            if not receiver.is_absolute():
                raise ValueError('Select the current receiver configuration')
            current=private_config(receiver,args.owner_uid)
            preimage=private_config(args.observer_preimage,args.owner_uid)
            observer_transition(preimage,current,args.receiver_sha256)
            receipt_path=args.observer_receipt
            if receipt_path is not None and (receipt_path.exists() or receipt_path.is_symlink()):
                print('Observer repair has a retained attempt. Inspect that receipt.',file=sys.stderr)
                return 80
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
            access_url=urllib.parse.urlunsplit((url.scheme,url.netloc,'/api/interaction/access','',''))
            if access_state(opener,access_url) not in BINDING_FAILURES.values():
                raise ValueError('No matching Conversation binding fault is present')
            if (private_config(receiver,args.owner_uid)!=current or private_config(args.config,args.owner_uid)!=raw
                    or private_config(args.observer_preimage,args.owner_uid)!=preimage):
                raise ValueError('Selected receiver changed before maintenance')
            if receipt_path is not None:
                receipt=dict(schema='daimonapp.observer-repair-attempt/v1',state='attempt_claimed',
                    receiver_sha256=args.receiver_sha256,preimage_sha256=hashlib.sha256(preimage).hexdigest(),
                    config_sha256=hashlib.sha256(raw).hexdigest())
                try:
                    claim_observer_repair(receipt_path,receipt)
                except FileExistsError:
                    print('Observer repair has a retained attempt. Inspect that receipt.',file=sys.stderr)
                    return 80
            operator_started=True
            environment={**os.environ,MAINTENANCE_FD:str(guard.fd)}
            outcome=subprocess.run(bounded,pass_fds=(guard.fd,),env=environment)
            if outcome.returncode:
                if receipt_path is not None:
                    write_json(receipt_path,{**receipt,'state':'recovery_unconfirmed','operator_exit':outcome.returncode})
                return outcome.returncode
            if (private_config(receiver,args.owner_uid)!=current or private_config(args.config,args.owner_uid)!=raw
                    or access_state(opener,access_url)!='anonymous_refused'):
                raise ValueError('Conversation recovery is unconfirmed')
            if receipt_path is not None:
                write_json(receipt_path,{**receipt,'state':'recovery_verified','access_status':401})
            print('Conversation binding recovery verified by the anonymous access check.')
            return 0
    except BlockingIOError:
        print('Voice is active; web maintenance was not started.',file=sys.stderr)
        return 75
    except (OSError,ValueError,KeyError,TypeError,RecursionError):
        if operator_started:
            print('Web maintenance ran; recovery is unconfirmed. Read the owning receipt before another action.',file=sys.stderr)
            return 79
        print('Web maintenance was not started: verify the selected reader, state and health binding.',file=sys.stderr)
        return 78


if __name__=='__main__':raise SystemExit(main())
