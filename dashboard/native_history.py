"""Assistant-authored foreground utterances in the existing app state database.

This is conversation text, not human ingress or a native worker/result registry.
History has no automatic deletion: exhausting its explicit bound stops new voice
instead of silently losing an original or pretending that generated speech was heard.
"""
from contextlib import suppress
import hashlib
import json
import re
import time
import threading
import uuid


class NativeHistory:
    max_bytes=64*1024*1024
    max_rows=16384

    def __init__(self,database,scope):
        self.database,self.scope=database,scope
        self._lock=threading.Lock();self._listeners=set()
        with database() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS foreground_utterances(
                id TEXT PRIMARY KEY,human INTEGER NOT NULL,scope TEXT NOT NULL,
                dialogue TEXT NOT NULL,binding TEXT NOT NULL,observed_at REAL NOT NULL,
                text TEXT NOT NULL,model TEXT NOT NULL,audio_sha256 TEXT NOT NULL,
                generated_bytes INTEGER NOT NULL,interrupted INTEGER NOT NULL,
                closed INTEGER NOT NULL,played_bytes INTEGER NOT NULL DEFAULT 0)''')
            db.execute('CREATE INDEX IF NOT EXISTS foreground_utterance_owner ON foreground_utterances(human,scope,observed_at)')

    def subscribe(self,notify):
        with self._lock:
            if len(self._listeners)>=128:raise ValueError('Foreground history subscribers reached bound')
            self._listeners.add(notify)
        def close():
            with self._lock:self._listeners.discard(notify)
        return close

    @staticmethod
    def ident(value):
        if not isinstance(value,str) or str(uuid.UUID(value))!=value:
            raise ValueError('Select one foreground utterance')
        return value

    def capacity(self):
        with self.database() as db:
            count,size=db.execute('SELECT count(*),coalesce(sum(length(cast(text AS BLOB))),0) FROM foreground_utterances').fetchone()
        if count>=self.max_rows or size+16384>self.max_bytes:
            raise ValueError('Foreground conversation history reached its retention bound')

    def retain(self,human,dialogue,binding,ident,text,audio_sha256,generated_bytes,*,interrupted=False,closed=True):
        for value in (dialogue,ident):self.ident(value)
        if (type(human) is not int or not isinstance(binding,str) or not re.fullmatch('[a-f0-9]{64}',binding)
                or not isinstance(text,str) or len(text.encode())>16384 or '\0' in text
                or not isinstance(audio_sha256,str) or not re.fullmatch('[a-f0-9]{64}',audio_sha256)
                or type(generated_bytes) is not int or not 0<=generated_bytes<=300*48000
                or type(interrupted) is not bool or type(closed) is not bool):
            raise ValueError('Select bounded assistant-authored voice output')
        with self.database() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM foreground_utterances WHERE id=?',(ident,)).fetchone()
            if old:
                if (old['human']!=human or old['scope']!=self.scope or old['dialogue']!=dialogue
                        or old['binding']!=binding or old['closed']
                        or generated_bytes<old['generated_bytes'] or not text.startswith(old['text'])):
                    raise ValueError('Retained assistant utterance cannot be rewritten')
            count,size=db.execute('SELECT count(*),coalesce(sum(length(cast(text AS BLOB))),0) FROM foreground_utterances').fetchone()
            if (count+(old is None)>self.max_rows
                    or size+len(text.encode())-(len(old['text'].encode()) if old else 0)>self.max_bytes):
                raise ValueError('Foreground conversation history reached its retention bound')
            if old:
                db.execute('''UPDATE foreground_utterances SET text=?,audio_sha256=?,generated_bytes=?,interrupted=?,closed=? WHERE id=?''',
                           (text,audio_sha256,generated_bytes,int(interrupted),int(closed),ident))
            else:
                db.execute('''INSERT INTO foreground_utterances(id,human,scope,dialogue,binding,observed_at,text,model,audio_sha256,generated_bytes,interrupted,closed)
                    VALUES(?,?,?,?,?,?,?,'gemini-3.8-live',?,?,?,?)''',
                    (ident,human,self.scope,dialogue,binding,time.time(),text,audio_sha256,generated_bytes,int(interrupted),int(closed)))
            row=db.execute('SELECT rowid,* FROM foreground_utterances WHERE id=?',(ident,)).fetchone()
        if (text and old is None) or old is not None and (old['text']!=text or bool(old['closed'])!=closed):
            with self._lock:listeners=tuple(self._listeners)
            for notify in listeners:
                with suppress(RuntimeError):notify()
        return self.view(row)

    def played(self,human,dialogue,ident,count):
        self.ident(dialogue);self.ident(ident)
        if type(count) is not int or count<0 or count%2:raise ValueError('Invalid played PCM position')
        with self.database() as db:
            row=db.execute('SELECT rowid,* FROM foreground_utterances WHERE id=? AND human=? AND scope=? AND dialogue=?',
                           (ident,human,self.scope,dialogue)).fetchone()
            if row is None or not row['played_bytes']<=count<=row['generated_bytes']:
                raise ValueError('Playback observation does not match generated audio')
            db.execute('UPDATE foreground_utterances SET played_bytes=? WHERE id=?',(count,ident))
        return {'id':ident,'played_bytes':count,'meaning':'Client playback position; intelligibility and physical hearing are not established.'}

    @staticmethod
    def view(row):
        value={k:row[k] for k in ('id','dialogue','binding','observed_at','text','model','audio_sha256','generated_bytes','played_bytes')}
        value.update(speaker='assistant',kind='voice_foreground',interrupted=bool(row['interrupted']),closed=bool(row['closed']),
                     cursor=row['rowid'],playback_meaning='Highest client-reported PCM position; not a contiguous heard range or physical hearing receipt.',playback='client_reported' if row['played_bytes'] else 'not_observed')
        value['revision']=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        return value

    def page(self,human,before=0,*,binding=None):
        if type(before) is not int or not 0<=before<=2**63-1:raise ValueError('Invalid foreground history cursor')
        if binding is not None and (not isinstance(binding,str) or not re.fullmatch('[a-f0-9]{64}',binding)):
            raise ValueError('Select one foreground history binding')
        with self.database() as db:
            rows=db.execute('''SELECT rowid,* FROM foreground_utterances WHERE human=? AND scope=? AND rowid<?'''
                +(' AND binding=?' if binding is not None else '')+' ORDER BY rowid DESC LIMIT 17',
                (human,self.scope,before or 2**63-1)+((binding,) if binding is not None else ())).fetchall()
        values=[self.view(row) for row in rows[:16]]
        return {'items':values,'before':values[-1]['cursor'] if values else before,'more':len(rows)>16,
                'meaning':'Assistant-authored voice conversation. These are not human originals or native work results.'}
