#!/usr/bin/env python3
"""Fence one existing, finite web-only operator; never select/stop services here."""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tomllib
import urllib.parse
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.voice_admission import HEADER, maintenance_guard


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--health-url',required=True)
    parser.add_argument('--owner-uid',type=int,default=os.getuid())
    parser.add_argument('--seconds',type=int,default=180)
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args(argv)
    command=args.command[1:] if args.command[:1]==['--'] else args.command
    url=urllib.parse.urlsplit(args.health_url)
    if (not command or not 1<=args.seconds<=300 or args.owner_uid<0
            or url.scheme not in ('http','https') or not url.hostname
            or url.username or url.password or url.query or url.fragment):
        parser.error('Select the current private config, local health route and one bounded operator')
    with args.config.open('rb') as stream:
        info=os.fstat(stream.fileno());raw=stream.read(65537)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid!=args.owner_uid
            or info.st_mode&0o077 or len(raw)>65536):
        parser.error('Select the actual service user private configuration')
    config=tomllib.loads(raw.decode());root=Path(config['state_dir'])
    if not root.is_absolute():parser.error('Select the actual absolute state directory')
    timeout=shutil.which('timeout')
    if not timeout:parser.error('The existing finite-command timeout utility is required')
    try:
        with maintenance_guard(root,owner_uid=args.owner_uid) as guard:
            # A leftover file after rollback, or another state root, is not proof
            # that the currently serving process participates in the fence.
            with urllib.request.urlopen(args.health_url,timeout=3) as response:
                body=response.read(8193)
                if (response.headers.get(HEADER)!=guard.header or len(body)>8192
                        or json.loads(body)!={'ok':True}):
                    raise ValueError('Selected server does not advertise this exact voice lock')
            if args.config.read_bytes()!=raw:
                raise ValueError('Selected configuration changed before maintenance')
            # timeout + the operator inherit the same open file description.
            # The kernel keeps exclusion through exec and releases on exit/death.
            os.set_inheritable(guard.fd,True)
            os.execv(timeout,[timeout,'--signal=TERM','--kill-after=5',str(args.seconds),*command])
    except BlockingIOError:
        print('Voice is active; web maintenance was not started.',file=sys.stderr)
        return 75
    except (OSError,ValueError):
        print('Web maintenance was not started: verify the selected reader, state and health binding.',file=sys.stderr)
        return 78


if __name__=='__main__':raise SystemExit(main())
