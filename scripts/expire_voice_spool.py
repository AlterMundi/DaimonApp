#!/usr/bin/env python3
"""Expire temporary voice bytes for one selected receiving dashboard."""

import argparse
from contextlib import closing
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
import tomllib

MAX_AGE_SECONDS = 24 * 60 * 60
# The receiving hourly hygiene timer allows up to five minutes of randomized
# delay plus systemd scheduling accuracy. Wake before the one-day deadline.
HOURLY_LEAD_SECONDS = 70 * 60
IDENTITY = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")


def private_owned(info, predicate):
    return predicate(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077


def expire(db, *, now, lead=0, apply=False):
    spool = Path(str(db) + ".voice")
    if not private_owned(spool.lstat(), stat.S_ISDIR):
        raise ValueError("The selected recording spool is unavailable")
    cutoff = now - MAX_AGE_SECONDS + lead
    result = {"expired": 0, "bytes": 0, "protected": 0}
    lock = os.open(spool / "admission.lock", os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(lock, "rb") as handle, closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)) as conn:
        if not private_owned(os.fstat(handle.fileno()), stat.S_ISREG):
            raise ValueError("The selected capture writer lock is unavailable")
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for path in spool.iterdir():
            if not IDENTITY.fullmatch(path.name):
                continue
            try:
                info = path.lstat()
                if not private_owned(info, stat.S_ISREG) or info.st_mtime > cutoff:
                    continue
                row = conn.execute("SELECT doc FROM conversation_inputs WHERE id=?", (path.name,)).fetchone()
                if row:
                    voice = json.loads(row[0]).get("voice") or {}
                    if voice.get("preserve_original") is True:
                        result["protected"] += 1
                        continue
                if apply:
                    current = path.lstat()
                    if (current.st_dev, current.st_ino, current.st_mtime_ns) != (info.st_dev, info.st_ino, info.st_mtime_ns):
                        continue
                    path.unlink()
                result["expired"] += 1
                result["bytes"] += info.st_size
            except FileNotFoundError:
                continue
        if apply and result["expired"]:
            fd = os.open(spool, os.O_DIRECTORY | os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dashboard-config", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--hourly", action="store_true")
    args = parser.parse_args()
    dashboard = tomllib.loads(args.dashboard_config.read_text())
    receiver = tomllib.loads(Path(dashboard["receiver_config"]).read_text())
    db = Path(receiver["db_path"])
    try:
        metrics = expire(db, now=time.time(), lead=HOURLY_LEAD_SECONDS if args.hourly else 0, apply=args.apply)
    except (BlockingIOError, FileNotFoundError):
        metrics = {"deferred": True}
    print(json.dumps(metrics))


if __name__ == "__main__":
    main()
