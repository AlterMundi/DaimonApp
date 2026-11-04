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
from .native_context import NativeContext, enqueue, install_schema, semantic_revision


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
            if 'derived_caption' not in {r[1] for r in db.execute('PRAGMA table_info(foreground_utterances)')}:
                db.execute('ALTER TABLE foreground_utterances ADD COLUMN derived_caption TEXT')
            db.execute('CREATE INDEX IF NOT EXISTS foreground_utterance_owner ON foreground_utterances(human,scope,observed_at)')
            db.execute('CREATE INDEX IF NOT EXISTS foreground_utterance_dialogue ON foreground_utterances(human,scope,dialogue)')
            install_schema(db)

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

    def retain(self,human,dialogue,binding,ident,text,audio_sha256,generated_bytes,*,interrupted=False,closed=True,model="gemini-3.8-live"):
        for value in (dialogue,ident):self.ident(value)
        if (type(human) is not int or not isinstance(binding,str) or not re.fullmatch('[a-f0-9]{64}',binding)
                or not isinstance(text,str) or len(text.encode())>16384 or '\0' in text
                or not isinstance(audio_sha256,str) or not re.fullmatch('[a-f0-9]{64}',audio_sha256)
                or type(generated_bytes) is not int or not 0<=generated_bytes<=300*48000
                or type(interrupted) is not bool or type(closed) is not bool
                or model not in ('gemini-3.8-live','qwen-audio-3.0-realtime-plus','gpt-realtime-2.1')):
            raise ValueError('Select bounded assistant-authored voice output')
        with self.database() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM foreground_utterances WHERE id=?',(ident,)).fetchone()
            if old:
                if (old['human']!=human or old['scope']!=self.scope or old['dialogue']!=dialogue
                        or old['binding']!=binding or old['model']!=model or old['closed']
                        or generated_bytes<old['generated_bytes'] or not text.startswith(old['text'])):
                    raise ValueError('Retained assistant utterance cannot be rewritten')
            # PCM/hash/closed updates cannot grow the row or text quota. Keep
            # their durable transaction without scanning every actor's history
            # on the audio delivery path. Growth checks stay under this same
            # writer lock; no cached counter can drift after another writer.
            if old is None or text!=old['text']:
                count,size=db.execute('SELECT count(*),coalesce(sum(length(cast(text AS BLOB))),0) FROM foreground_utterances').fetchone()
                if (count+(old is None)>self.max_rows
                        or size+len(text.encode())-(len(old['text'].encode()) if old else 0)>self.max_bytes):
                    raise ValueError('Foreground conversation history reached its retention bound')
            if old:
                db.execute('''UPDATE foreground_utterances SET text=?,audio_sha256=?,generated_bytes=?,interrupted=?,closed=? WHERE id=?''',
                           (text,audio_sha256,generated_bytes,int(interrupted),int(closed),ident))
            else:
                db.execute('''INSERT INTO foreground_utterances(id,human,scope,dialogue,binding,observed_at,text,model,audio_sha256,generated_bytes,interrupted,closed)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (ident,human,self.scope,dialogue,binding,time.time(),text,model,audio_sha256,generated_bytes,int(interrupted),int(closed)))
            row=db.execute('SELECT rowid,* FROM foreground_utterances WHERE id=?',(ident,)).fetchone()
            enqueue(db,row)
        if (text and old is None) or old is not None and (old['text']!=text or bool(old['closed'])!=closed):
            with self._lock:listeners=tuple(self._listeners)
            for notify in listeners:
                with suppress(RuntimeError):notify()
        return self.view(row)

    def retain_caption(self,human,dialogue,binding,parent_source,pcm_sha256,generated_bytes,result):
        """One derived ASR draft; the finalized parent and its receipt stay intact.

        Server-owned recovery calls this only after verifying its configured
        file-ASR outcome. It is not an HTTP write or a human ingress path.
        """
        self.ident(dialogue);self.ident(parent_source)
        if (type(human) is not int or not isinstance(result,dict)
                or result.get('final') is not True or not isinstance(result.get('text'),str)
                or not result['text'].strip() or len(result['text'].encode())>16000 or '\0' in result['text']
                or type(generated_bytes) is not int or not 0<generated_bytes<=120*48000 or generated_bytes%2
                or not isinstance(pcm_sha256,str) or not re.fullmatch('[a-f0-9]{64}',pcm_sha256)):
            raise ValueError('Select a bounded completed file-ASR draft')
        # Preparation retirement can complete on a later read of this same ASR
        # outcome. Its cleanup flag is not a different interpretation/source.
        interpretation={k:result[k] for k in ('text','final','streaming_model') if k in result}
        raw_result=json.dumps(interpretation,sort_keys=True,ensure_ascii=False,separators=(',',':'))
        if len(raw_result.encode())>32768:raise ValueError('File-ASR result exceeds its bound')
        ident=str(uuid.uuid5(uuid.UUID(parent_source),'configured-file-asr-caption/v1'))
        evidence={'parent_source':parent_source,'pcm_sha256':pcm_sha256,'generated_bytes':generated_bytes,
            'asr_result_sha256':hashlib.sha256(raw_result.encode()).hexdigest(),'draft':True}
        encoded=json.dumps(evidence,sort_keys=True,separators=(',',':'))
        with self.database() as db:
            db.execute('BEGIN IMMEDIATE')
            parent=db.execute('SELECT * FROM foreground_utterances WHERE id=?',(parent_source,)).fetchone()
            if (parent is None or (parent['human'],parent['scope'],parent['dialogue'],parent['binding'])
                    !=(human,self.scope,dialogue,binding) or not parent['closed'] or parent['text']
                    or parent['derived_caption'] is not None
                    or (parent['audio_sha256'],parent['generated_bytes'])!=(pcm_sha256,generated_bytes)):
                raise ValueError('ASR draft does not match its finalized missing-caption parent')
            old=db.execute('SELECT rowid,* FROM foreground_utterances WHERE id=?',(ident,)).fetchone()
            if old is not None:
                if old['text']!=result['text'] or old['derived_caption']!=encoded:
                    raise ValueError('Finalized ASR draft cannot be rewritten')
                return self.view(old)
            count,size=db.execute('SELECT count(*),coalesce(sum(length(cast(text AS BLOB))),0) FROM foreground_utterances').fetchone()
            if count>=self.max_rows or size+len(result['text'].encode())>self.max_bytes:
                raise ValueError('Foreground conversation history reached its retention bound')
            db.execute("""INSERT INTO foreground_utterances(id,human,scope,dialogue,binding,observed_at,text,
                model,audio_sha256,generated_bytes,interrupted,closed,derived_caption)
                VALUES(?,?,?,?,?,?,?,'configured-file-asr',?,0,?,1,?)""",
                (ident,human,self.scope,dialogue,binding,time.time(),result['text'],pcm_sha256,parent['interrupted'],encoded))
            row=db.execute('SELECT rowid,* FROM foreground_utterances WHERE id=?',(ident,)).fetchone()
            enqueue(db,row)
            # A late finite recovery resumes context delivery, not voice/model
            # work. Explicit next-owner recovery sees this unfinished producer.
            db.execute("UPDATE foreground_context_producers SET phase='closing' WHERE dialogue=? AND phase='closed'",(dialogue,))
        with self._lock:listeners=tuple(self._listeners)
        for notify in listeners:
            with suppress(RuntimeError):notify()
        return self.view(row)

    def context_register(self,human,dialogue,binding):
        self.ident(dialogue)
        if type(human) is not int or not isinstance(binding,str) or not re.fullmatch('[a-f0-9]{64}',binding):
            raise ValueError('Select an owned Live producer')
        with self.database() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM foreground_context_producers WHERE dialogue=?',(dialogue,)).fetchone()
            if row is None:
                if db.execute('SELECT count(*) FROM foreground_context_producers').fetchone()[0]>=NativeContext.max_producers:
                    raise ValueError('Live context producer retention reached its bound')
                db.execute("INSERT INTO foreground_context_producers(dialogue,human,scope,binding,generation,phase) VALUES(?,?,?,?,?,'open')",
                    (dialogue,human,self.scope,binding,str(uuid.uuid4())))
                row=db.execute('SELECT * FROM foreground_context_producers WHERE dialogue=?',(dialogue,)).fetchone()
            record=dict(row)
            if (record['human'],record['scope'],record['binding'])!=(human,self.scope,binding):
                raise ValueError('Live context producer ownership changed')
            rows=db.execute('SELECT * FROM foreground_utterances WHERE dialogue=? AND human=? AND scope=? AND binding=? AND closed=1 ORDER BY rowid LIMIT 4097',
                (dialogue,human,self.scope,binding)).fetchall()
            if len(rows)>NativeContext.max_sources:raise ValueError('Live canonical assistant catch-up exceeds bound')
            for utterance in rows:enqueue(db,utterance)
        return record

    def context_resume_record(self,human,binding,dialogue):
        """Select an existing explicitly named producer; never create one."""
        self.ident(dialogue)
        with self.database() as db:
            row=db.execute('SELECT * FROM foreground_context_producers WHERE dialogue=? AND human=? AND scope=? AND binding=?',
                (dialogue,human,self.scope,binding)).fetchone()
        if row is None:raise ValueError('Selected prior Live conversation is unavailable')
        return dict(row)

    def context_unfinished(self,human,binding,excluding):
        with self.database() as db:
            return [dict(r) for r in db.execute("SELECT * FROM foreground_context_producers WHERE human=? AND scope=? AND binding=? AND dialogue!=? AND phase!='closed' ORDER BY rowid LIMIT 64",
                (human,self.scope,binding,excluding)).fetchall()]

    def context_rollover_intent(self,record,next_generation,revision):
        """One retained local transition intent, never provider/audio replay."""
        self.ident(next_generation)
        if not re.fullmatch('[a-f0-9]{64}',revision) or next_generation==record['generation']:
            raise ValueError('Select a distinct exact Live generation transition')
        intent={'previous':record['generation'],'next':next_generation,'revision':revision}
        with self.database() as db:
            db.execute('BEGIN IMMEDIATE');self._context_owned(db,record)
            row=db.execute('SELECT phase,rollover FROM foreground_context_producers WHERE dialogue=?',(record['dialogue'],)).fetchone()
            if row['phase']!='open':raise ValueError('Live producer is closing')
            if row['rollover'] is not None and json.loads(row['rollover'])!=intent:
                raise ValueError('Inspect the retained Live generation transition first')
            db.execute('UPDATE foreground_context_producers SET rollover=?,rollover_settled=NULL WHERE dialogue=?',
                (json.dumps(intent,separators=(',',':')),record['dialogue']))
        return intent

    def context_rollover_settle(self,record,intent,*,committed):
        """Observe native generation before clearing a local transition intent."""
        if type(committed) is not bool:raise ValueError('Select an observed generation outcome')
        receipt={**intent,'committed':committed}
        generation=intent['next'] if committed else intent['previous']
        with self.database() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM foreground_context_producers WHERE dialogue=?',(record['dialogue'],)).fetchone()
            if (row is None or any(row[k]!=record[k] for k in ('human','scope','binding'))
                    or record['scope']!=self.scope):
                raise ValueError('Live context producer ownership changed')
            if (row['rollover'] is None and row['rollover_settled'] is not None
                    and json.loads(row['rollover_settled'])==receipt and row['generation']==generation):
                return dict(row)
            self._context_owned(db,record)
            if row['rollover'] is None or json.loads(row['rollover'])!=intent or intent['previous']!=record['generation']:
                raise ValueError('Live generation transition changed')
            db.execute('UPDATE foreground_context_producers SET generation=?,rollover=NULL,rollover_settled=? WHERE dialogue=?',
                (generation,json.dumps(receipt,separators=(',',':')),record['dialogue']))
            return dict(db.execute('SELECT * FROM foreground_context_producers WHERE dialogue=?',(record['dialogue'],)).fetchone())

    def _context_owned(self,db,record):
        row=db.execute('SELECT * FROM foreground_context_producers WHERE dialogue=?',(record['dialogue'],)).fetchone()
        if row is None or any(row[k]!=record[k] for k in ('human','scope','binding','generation')) or record['scope']!=self.scope:
            raise ValueError('Live context producer ownership changed')

    def context_seal(self,record):
        """A new explicit avatar open owns no previous live audio connection.

        Preserve partial generated text as interrupted after that connection
        ended; do not manufacture missing language or a physical hearing receipt.
        """
        with self.database() as db:
            db.execute('BEGIN IMMEDIATE');self._context_owned(db,record)
            db.execute('UPDATE foreground_utterances SET closed=1,interrupted=1 WHERE human=? AND scope=? AND binding=? AND dialogue=? AND closed=0',
                (record['human'],self.scope,record['binding'],record['dialogue']))
            rows=db.execute('SELECT * FROM foreground_utterances WHERE human=? AND scope=? AND binding=? AND dialogue=? ORDER BY rowid LIMIT 4097',
                (record['human'],self.scope,record['binding'],record['dialogue'])).fetchall()
            if len(rows)>NativeContext.max_sources:raise ValueError('Live canonical assistant catch-up exceeds bound')
            for row in rows:enqueue(db,row)

    def context_pending(self,record):
        with self.database() as db:
            self._context_owned(db,record)
            rows=db.execute("SELECT u.*,o.revision AS semantic_revision FROM foreground_context_outbox o JOIN foreground_utterances u ON u.id=o.source WHERE o.dialogue=? AND o.phase='pending' ORDER BY u.rowid LIMIT 8",(record['dialogue'],)).fetchall()
            values=[];size=0
            for row in rows:
                if (row['human'],row['scope'],row['binding'])!=(record['human'],self.scope,record['binding']) or not row['closed'] or semantic_revision(row)!=row['semantic_revision']:
                    raise ValueError('Canonical Live context source changed')
                size+=len(row['text'].encode())
                if size>65536:break
                source={'source':row['id'],'text':row['text'],'interrupted':bool(row['interrupted']),'semantic_revision':row['semantic_revision']}
                if row['derived_caption'] is not None:
                    source['derived_caption']=json.loads(row['derived_caption'])
                if not row['text'] and row['generated_bytes']:
                    source['audio_without_transcript']={'pcm_sha256':row['audio_sha256'],'generated_bytes':row['generated_bytes']}
                values.append(source)
        return values

    def context_retained(self,record,sources,receipts):
        with self.database() as db:
            db.execute('BEGIN IMMEDIATE');self._context_owned(db,record)
            by_id={r['source']:r for r in receipts}
            for source in sources:
                receipt=by_id[source['source']]
                changed=db.execute("UPDATE foreground_context_outbox SET phase='retained',native_sequence=?,native_revision=? WHERE source=? AND dialogue=? AND revision=? AND phase='pending'",
                    (receipt['sequence'],receipt['revision'],source['source'],record['dialogue'],source['semantic_revision'])).rowcount
                if changed!=1:
                    old=db.execute('SELECT * FROM foreground_context_outbox WHERE source=? AND dialogue=?',
                        (source['source'],record['dialogue'])).fetchone()
                    if (old is None or old['phase']!='retained' or old['revision']!=source['semantic_revision']
                            or old['native_sequence']!=receipt['sequence'] or old['native_revision']!=receipt['revision']):
                        raise ValueError('Live context source receipt changed before commit')

    def context_phase(self,record,phase):
        if phase not in ('closing','closed'):raise ValueError('Invalid Live producer phase')
        with self.database() as db:
            db.execute('BEGIN IMMEDIATE');self._context_owned(db,record)
            db.execute("UPDATE foreground_context_producers SET phase=? WHERE dialogue=? AND (phase!='closed' OR ?='closed')",(phase,record['dialogue'],phase))

    def pending_audio(self,human,dialogue):
        self.ident(dialogue)
        with self.database() as db:
            # Both shipped playback owners serialize output. A later fully
            # played source cannot coexist with an older queued source: gaps
            # belong to retired audio. Do not turn those gaps into hearing
            # receipts or let them permanently block later attention.
            row=db.execute('''SELECT interrupted,closed,played_bytes,generated_bytes
                FROM foreground_utterances WHERE human=? AND scope=? AND dialogue=?
                AND (generated_bytes>0 OR closed=0) ORDER BY rowid DESC LIMIT 1''',
                (human,self.scope,dialogue)).fetchone()
        return bool(row and not row['interrupted'] and
                    (not row['closed'] or row['played_bytes']<row['generated_bytes']))

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
        if row['derived_caption'] is not None:value['derived_caption']=json.loads(row['derived_caption'])
        value['revision']=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        return value

    def page(self,human,before=0,*,binding=None,dialogue=None):
        if type(before) is not int or not 0<=before<=2**63-1:raise ValueError('Invalid foreground history cursor')
        if binding is not None and (not isinstance(binding,str) or not re.fullmatch('[a-f0-9]{64}',binding)):
            raise ValueError('Select one foreground history binding')
        if dialogue is not None:self.ident(dialogue)
        with self.database() as db:
            rows=db.execute('''SELECT rowid,* FROM foreground_utterances WHERE human=? AND scope=? AND rowid<?'''
                +(' AND binding=?' if binding is not None else '')+(' AND dialogue=?' if dialogue is not None else '')
                +' ORDER BY rowid DESC LIMIT 17',
                (human,self.scope,before or 2**63-1)+((binding,) if binding is not None else ())
                +((dialogue,) if dialogue is not None else ())).fetchall()
        values=[self.view(row) for row in rows[:16]]
        return {'items':values,'before':values[-1]['cursor'] if values else before,'more':len(rows)>16,
                'meaning':'Assistant-authored voice conversation. These are not human originals or native work results.'}
