"""Bounded immutable sculpture exchanges, scoped by the existing App actor.

This feature store is not an identity, session, native-task or provider store.
SQLite commits each exact request/return and its quota accounting atomically.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import threading
import uuid

from .private_state import private_directory
from .codex_voice_history import history_lock

FILE_BYTES = 8 * 1024 * 1024
_validators = threading.BoundedSemaphore(1)
_validator = Path(__file__).parent / 'web/atelier-workshop/validate.mjs'


class AtelierConflict(ValueError):
    pass


def validate_transfer(raw, source=None):
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > FILE_BYTES:
        raise ValueError('This account accepts sculpture exchanges up to 8MiB')
    if source is not None and (not isinstance(source, str) or len(source.encode('utf-8')) > FILE_BYTES):
        raise ValueError('Saved source exceeds its bound')
    node = shutil.which('node')
    if not node or not _validators.acquire(blocking=False):
        raise ValueError('Sculpture validation is unavailable; your work is kept')
    try:
        result = subprocess.run([node, '--max-old-space-size=192', str(_validator)],
            input=json.dumps({'raw': raw, 'source': source}, ensure_ascii=False).encode(),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=12, check=False)
        if result.returncode or len(result.stdout) > 16384:
            raise ValueError('The sculpture exchange is not valid')
        value = json.loads(result.stdout)
        if (not isinstance(value, dict) or value.get('kind') not in ('request', 'reply')
                or value.get('fileSha256') != hashlib.sha256(raw.encode()).hexdigest()):
            raise ValueError('Sculpture validation could not be confirmed')
        return value
    except (OSError, subprocess.TimeoutExpired, UnicodeError, json.JSONDecodeError):
        raise ValueError('Sculpture validation is unavailable; your work is kept') from None
    finally:
        _validators.release()


class AtelierWorkshop:
    max_requests = 32
    max_actors = 64
    max_actor_bytes = 64 * 1024 * 1024
    max_total_bytes = 128 * 1024 * 1024
    max_database_bytes = 192 * 1024 * 1024

    def __init__(self, state_root):
        self.root = private_directory(Path(state_root) / 'atelier-workshop')
        self.path = self.root / 'exchanges.sqlite3'
        # No other application database is opened or migrated.
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS properties (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS actors (human INTEGER PRIMARY KEY, generation INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS exchanges (
                    human INTEGER NOT NULL, id TEXT NOT NULL, receipt TEXT NOT NULL,
                    request BLOB NOT NULL, request_file_sha TEXT NOT NULL, request_sha TEXT NOT NULL,
                    source_id TEXT NOT NULL, source_sha TEXT NOT NULL, project_id TEXT NOT NULL,
                    name TEXT NOT NULL, instruction TEXT NOT NULL, created_at TEXT NOT NULL,
                    reply BLOB, reply_file_sha TEXT, reply_sha TEXT, reply_id TEXT,
                    bytes INTEGER NOT NULL, PRIMARY KEY(human,id));
                CREATE TABLE IF NOT EXISTS atelier_dispatches (
                    human INTEGER NOT NULL, id TEXT NOT NULL,
                    choice TEXT NOT NULL, label TEXT NOT NULL,
                    body BLOB NOT NULL, body_sha TEXT NOT NULL,
                    state TEXT NOT NULL, receipt TEXT, origin TEXT,
                    PRIMARY KEY(human,id));
            ''')
            with db:
                db.execute('INSERT OR IGNORE INTO properties VALUES (?,?)', ('local_scope',str(uuid.uuid4())))

    @contextmanager
    def _db(self):
        with history_lock(self.root / '.lock'):
            if not self.path.exists() and not self.path.is_symlink():
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                os.close(fd)
            info = self.path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_size > self.max_database_bytes):
                raise ValueError('Sculpture state needs review; no reset was performed')
            db = sqlite3.connect(self.path, timeout=2)
            db.row_factory = sqlite3.Row
            try:
                db.execute('PRAGMA trusted_schema=OFF')
                db.execute('PRAGMA journal_mode=DELETE')
                db.execute('PRAGMA synchronous=FULL')
                page_size = db.execute('PRAGMA page_size').fetchone()[0]
                db.execute('PRAGMA max_page_count=' + str(self.max_database_bytes // page_size))
                yield db
            finally:
                db.close()

    @staticmethod
    def _human(human):
        if type(human) is not int or not 0 < human < 2**63:
            raise ValueError('Invalid sculpture account')

    @staticmethod
    def _id(ident):
        if not isinstance(ident, str) or str(uuid.UUID(ident)) != ident:
            raise ValueError('Select one sculpture request')
        return ident

    @staticmethod
    def _blob(row, kind):
        raw = row[kind]
        if raw is None:
            return None
        if len(raw) > FILE_BYTES or hashlib.sha256(raw).hexdigest() != row[kind + '_file_sha']:
            raise ValueError('The saved sculpture needs review; no reset was performed')
        return raw.decode('utf-8')

    @staticmethod
    def _receipt(row):
        return {'state': 'returned' if row['reply'] is not None else 'retained',
                'receiptId': row['receipt'], 'requestId': row['id'],
                'requestSha256': row['request_sha'], 'sourceId': row['source_id'],
                'sourceSha256': row['source_sha']}

    def snapshot(self, human):
        self._human(human)
        with self._db() as db:
            generation = db.execute('SELECT generation FROM actors WHERE human=?', (human,)).fetchone()
            rows = db.execute('''SELECT id, project_id, name, instruction, created_at,
                request_sha, source_id, source_sha, reply_id FROM exchanges
                WHERE human=? ORDER BY created_at DESC, id LIMIT ?''', (human, self.max_requests)).fetchall()
            # Scope is a deterministic local namespace selector, never a grant.
            seed = db.execute("SELECT value FROM properties WHERE key='local_scope'").fetchone()[0]
            scope = hashlib.sha256(('atelier-local/v1:' + seed + ':' + str(human)).encode()).hexdigest()[:32]
            return {'schema': 'daimon.atelier-workshop/v1', 'storageScope': scope,
                    'generation': generation[0] if generation else 0,
                    'maxFileBytes': FILE_BYTES, 'maxRequests': self.max_requests,
                    'requests': [{'id': r['id'], 'projectId': r['project_id'], 'sourceName': r['name'],
                        'instruction': r['instruction'], 'createdAt': r['created_at'],
                        'sha256': r['request_sha'], 'sourceId': r['source_id'],
                        'sourceSha256': r['source_sha'], 'returned': r['reply_id'] is not None} for r in rows]}

    def get(self, human, ident):
        self._human(human); self._id(ident)
        with self._db() as db:
            row = db.execute('SELECT * FROM exchanges WHERE human=? AND id=?', (human, ident)).fetchone()
            if row is None:
                raise KeyError('Sculpture request unavailable for this account')
            result = self._receipt(row)
            result['request'] = self._blob(row, 'request')
            reply = self._blob(row, 'reply')
            if reply is not None:
                result['reply'] = reply
            return result

    def _quota(self, db, human, added, new_request=False):
        actors = db.execute('SELECT COUNT(*) FROM actors').fetchone()[0]
        exists = db.execute('SELECT 1 FROM actors WHERE human=?', (human,)).fetchone()
        if actors + (exists is None) > self.max_actors:
            raise ValueError('Sculpture account capacity reached')
        count, own = db.execute('SELECT COUNT(*), COALESCE(SUM(bytes),0) FROM exchanges WHERE human=?', (human,)).fetchone()
        total = db.execute('SELECT COALESCE(SUM(bytes),0) FROM exchanges').fetchone()[0]
        if (count + new_request > self.max_requests or own + added > self.max_actor_bytes
                or total + added > self.max_total_bytes):
            raise ValueError('Sculpture account storage is full; existing work is kept')

    def save_request(self, human, raw):
        self._human(human)
        if not isinstance(raw,str) or len(raw.encode())>FILE_BYTES:raise ValueError('This account accepts sculpture exchanges up to 8MiB')
        try:existing_id=self._id(json.loads(json.loads(raw)['document'])['id'])
        except (ValueError,KeyError,TypeError,RecursionError):raise ValueError('Select a valid sculpture request') from None
        retained=False
        with self._db() as db:
            old=db.execute('SELECT * FROM exchanges WHERE human=? AND id=?',(human,existing_id)).fetchone()
            if old is not None:
                if self._blob(old,'request')!=raw:raise AtelierConflict('A saved sculpture request is immutable')
                retained=True
        if retained:return self.get(human,existing_id)
        value = validate_transfer(raw)
        if value['kind'] != 'request':
            raise ValueError('Select a sculpture request')
        ident = self._id(value['id']); data = raw.encode('utf-8')
        with self._db() as db, db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM exchanges WHERE human=? AND id=?', (human, ident)).fetchone()
            if old is not None:
                if self._blob(old, 'request') != raw:
                    raise AtelierConflict('A saved sculpture request is immutable')
            else:
                charge = len(data) + len(json.dumps(value, ensure_ascii=False).encode()) + 256
                self._quota(db, human, charge, new_request=True)
                db.execute('INSERT OR IGNORE INTO actors VALUES (?,0)', (human,))
                db.execute('''INSERT INTO exchanges(human,id,receipt,request,request_file_sha,request_sha,
                    source_id,source_sha,project_id,name,instruction,created_at,bytes)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''', (human, ident, str(uuid.uuid4()), data,
                    value['fileSha256'], value['sha256'], value['sourceId'], value['sourceSha256'],
                    value['projectId'], value['name'], value['instruction'], value['createdAt'], charge))
                db.execute('UPDATE actors SET generation=generation+1 WHERE human=?', (human,))
        return self.get(human, ident)

    def save_reply(self, human, ident, raw, *, native_origin=None):
        if not isinstance(raw,str) or len(raw.encode())>FILE_BYTES:raise ValueError('This account accepts sculpture exchanges up to 8MiB')
        saved=self.get(human,ident)
        if 'reply' in saved:
            if saved['reply']!=raw:raise AtelierConflict('This request already has another immutable proposal')
            if native_origin is not None:
                with self._db() as db, db:
                    self._native_origin(db, human, ident, native_origin)
            return saved
        source = saved['request']
        value = validate_transfer(raw, source)
        if value['kind'] != 'reply' or value['requestId'] != ident:
            raise ValueError('Select a return for this request')
        data = raw.encode('utf-8')
        with self._db() as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM exchanges WHERE human=? AND id=?', (human, ident)).fetchone()
            if self._blob(row, 'request') != source:
                raise AtelierConflict('The source changed; inspect the saved request')
            if row['reply'] is not None:
                if self._blob(row, 'reply') != raw:
                    raise AtelierConflict('This request already has another immutable proposal')
            else:
                self._quota(db, human, len(data))
                db.execute('''UPDATE exchanges SET reply=?, reply_file_sha=?,reply_sha=?,reply_id=?,bytes=bytes+?
                    WHERE human=? AND id=?''', (data, value['fileSha256'], value['sha256'], value['id'], len(data), human, ident))
                db.execute('UPDATE actors SET generation=generation+1 WHERE human=?', (human,))
            if native_origin is not None:
                self._native_origin(db, human, ident, native_origin)
        return self.get(human, ident)

    def dispatch(self, human, ident):
        self._human(human); self._id(ident)
        with self._db() as db:
            row = db.execute('SELECT * FROM atelier_dispatches WHERE human=? AND id=?', (human, ident)).fetchone()
            if row is None:
                return None
            if hashlib.sha256(row['body']).hexdigest() != row['body_sha']:
                raise ValueError('Saved dispatch needs review; no reset was performed')
            return {**dict(row), 'body': json.loads(row['body']),
                    'receipt': json.loads(row['receipt']) if row['receipt'] else None,
                    'origin': json.loads(row['origin']) if row['origin'] else None}

    def prepare_dispatch(self, human, ident, choice, label, body):
        self.get(human, ident)
        data = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()
        if len(data) > 12000 or not isinstance(choice, str) or len(choice) != 64:
            raise ValueError('Choose one bounded sculpture dispatch')
        with self._db() as db, db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT choice,body FROM atelier_dispatches WHERE human=? AND id=?', (human, ident)).fetchone()
            if old:
                if old['choice'] != choice or old['body'] != data:
                    raise AtelierConflict('This request already has a frozen destination')
            else:
                # One bounded record per exchange, charged before any native I/O.
                self._quota(db, human, 16384)
                db.execute('INSERT INTO atelier_dispatches VALUES (?,?,?,?,?,?,?,NULL,NULL)',
                    (human, ident, choice, str(label)[:200], data, hashlib.sha256(data).hexdigest(), 'prepared'))
                db.execute('UPDATE exchanges SET bytes=bytes+16384 WHERE human=? AND id=?', (human, ident))
                db.execute('UPDATE actors SET generation=generation+1 WHERE human=?', (human,))
        return self.dispatch(human, ident)

    def claim_dispatch(self, human, ident):
        self.dispatch(human, ident)
        with self._db() as db, db:
            row = db.execute("UPDATE atelier_dispatches SET state='attempted' WHERE human=? AND id=? AND state='prepared'", (human, ident))
            return row.rowcount == 1

    def note_dispatch(self, human, ident, receipt):
        raw = json.dumps(receipt, ensure_ascii=False)
        if len(raw.encode()) > 1200:
            raise ValueError('Native receipt exceeds its bound')
        with self._db() as db, db:
            db.execute("UPDATE atelier_dispatches SET receipt=? WHERE human=? AND id=?", (raw, human, ident))

    @staticmethod
    def _native_origin(db, human, ident, origin):
        raw = json.dumps(origin, ensure_ascii=False)
        if (set(origin) != {'inputId', 'artifactId', 'source', 'revision', 'sha256'}
                or len(raw.encode()) > 2048):
            raise ValueError('Invalid native proposal source')
        row = db.execute('SELECT body,origin FROM atelier_dispatches WHERE human=? AND id=?', (human, ident)).fetchone()
        if row is None or json.loads(row['body'])['id'] != origin['inputId']:
            raise AtelierConflict('Proposal source does not belong to this dispatch')
        if row['origin'] is not None and json.loads(row['origin']) != origin:
            raise AtelierConflict('This proposal already has another retained native source')
        db.execute('UPDATE atelier_dispatches SET origin=? WHERE human=? AND id=?', (raw, human, ident))
