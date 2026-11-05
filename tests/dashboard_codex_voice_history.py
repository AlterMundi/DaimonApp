"""Native voice original retention/restart; no ASR, native input or inference."""
import hashlib
import os
import subprocess
import threading
import time
import json
import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.codex_voice_history import CodexVoiceHistory, native_transcripts
from dashboard.live_transcription import wav_bytes
from dashboard.media_retention import RetentionUnavailable
from dashboard.provider import Provider, ProviderUnavailable


class History(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.history=CodexVoiceHistory(self.root/'visits')
        self.visit=str(uuid.uuid4());self.session=str(uuid.uuid4())
        self.frozen={'binding':'a'*64,'entry_binding':[100,100,7,'native'],'native_thread':'native'}
        self.history.open(self.visit,100,self.frozen,self.session,session_seconds=1)
        self.provider=Mock(spec=['receiver','retain_voice_capture','media_retention'])
        self.provider.receiver={'db_path':str(self.root/'receiver.sqlite')}
        self.provider.retain_voice_capture=Mock(side_effect=Provider.retain_voice_capture)
        self.provider.media_retention=None
        self.audio=wav_bytes(b'\x01\x00'*8000)
    def retain(self,ordinal=0,audio=None):
        return self.history.recording(self.visit,100,'a'*64,ordinal,audio or self.audio,self.provider)
    def test_recording_waits_for_concurrent_close_and_both_commits_survive(self):
        from scripts.speech_render import lock
        entered=threading.Event();finished=threading.Event();results=[]
        def retain():
            entered.set()
            try:results.append(self.retain())
            finally:finished.set()
        with lock(self.history.root/'.lock'):
            worker=threading.Thread(target=retain);worker.start();self.assertTrue(entered.wait(1))
            self.assertFalse(finished.wait(.05))
        worker.join(timeout=2);self.assertFalse(worker.is_alive());self.assertEqual(len(results),1)
        self.history.complete_transcript(self.visit,100,'a'*64)
        retained=self.history.read(self.visit,100,'a'*64)
        self.assertTrue(retained['transcript_complete']);self.assertEqual(len(retained['recordings']),1)

    def test_original_survives_restart_and_exact_retry_verifies_bytes(self):
        receipt=self.retain()
        self.history=CodexVoiceHistory(self.root/'visits')
        self.assertEqual(self.retain(),receipt)
        self.assertEqual(self.provider.retain_voice_capture.call_count,2)
        raw=self.root/'receiver.sqlite.voice'/receipt['id']
        self.assertEqual(hashlib.sha256(raw.read_bytes()).hexdigest(),receipt['audio_sha256'])
        raw.unlink()  # Simulate absent backing bytes: receipt alone is not retention.
        self.assertEqual(self.retain(),receipt)
        self.assertTrue(raw.exists())
        self.assertEqual(len(self.history.read(self.visit,100,'a'*64)['recordings']),1)
        self.assertEqual(receipt['native_replay'],'never')
    def test_same_ordinal_cannot_replace_original_or_escape_binding(self):
        self.retain()
        with self.assertRaises(ValueError):self.retain(audio=wav_bytes(b'\x02\x00'*8000))
        with self.assertRaises(ValueError):self.history.read(self.visit,101,'a'*64)
        with self.assertRaises(ValueError):self.history.read(self.visit,100,'b'*64)
        self.assertEqual(self.provider.retain_voice_capture.call_count,1)
    def test_duration_and_index_bounds_refuse_before_media_admission(self):
        self.retain(0);self.retain(1)
        with self.assertRaises(ValueError):self.retain(2)
        with self.assertRaises(ValueError):self.retain(32)
        self.assertEqual(self.provider.retain_voice_capture.call_count,2)
    def test_archive_pending_keeps_original_and_retry_never_dispatches_work(self):
        retention=Mock();retention.selected.return_value=True
        retention.retain.side_effect=RetentionUnavailable('Synthetic archive full')
        self.provider.media_retention=retention
        first=self.retain();self.assertEqual(first['archive'],'pending')
        self.assertTrue((self.root/'receiver.sqlite.voice'/first['id']).exists())
        retention.retain.side_effect=None
        second=self.retain();self.assertEqual(second['archive'],'retained')
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(len(self.history.read(self.visit,100,'a'*64)['recordings']),1)
    def test_completed_transcript_is_generation_scoped_and_immutable(self):
        item={'id':'item_1','type':'transcriptSegment','role':'user','text':'A retained source',
              'realtimeSessionId':self.session}
        self.history.item(self.visit,100,'a'*64,item)
        self.history.item(self.visit,100,'a'*64,item)
        with self.assertRaises(ValueError):self.history.item(self.visit,100,'a'*64,{**item,'text':'changed'})
        with self.assertRaises(ValueError):self.history.item(self.visit,100,'a'*64,{**item,'realtimeSessionId':str(uuid.uuid4())})
        self.assertEqual(len(self.history.read(self.visit,100,'a'*64)['items']),1)
    def test_visit_is_not_reopened_and_metadata_is_bounded(self):
        with self.assertRaises(ValueError):self.history.open(self.visit,100,self.frozen,self.session)
        self.history.state(self.visit,100,'a'*64,'closed')
        self.history.state(self.visit,100,'a'*64,'active')
        self.assertEqual(self.history.list(100,'a'*64)[0]['state'],'closed')
        self.history.max_visits=1
        with self.assertRaises(ValueError):self.history.open(str(uuid.uuid4()),100,self.frozen,str(uuid.uuid4()))
    def test_metadata_capacity_failure_keeps_original_and_exact_retry(self):
        self.history.max_record_bytes=1
        with self.assertRaises(ValueError):self.retain()
        original=str(uuid.uuid5(uuid.UUID(self.visit),'human-recording:0'))
        raw=self.root/'receiver.sqlite.voice'/original
        self.assertEqual(raw.read_bytes(),self.audio)
        self.history.max_record_bytes=65536
        with self.assertRaises(ValueError):self.retain(1,wav_bytes(b'\x02\x00'*16000))
        self.assertEqual(raw.read_bytes(),self.audio)
        self.assertEqual(self.retain()['id'],original)
        self.assertEqual(len(self.history.read(self.visit,100,'a'*64)['recordings']),1)

    def test_flat_source_restore_survives_repeated_visits_without_recursive_growth(self):
        text='Use "hojasol", not \"brisacedro\". '+('\\'*4)
        self.history.item(self.visit,100,'a'*64,{'id':'correction','type':'transcriptSegment',
            'role':'user','text':text,'realtimeSessionId':self.session})
        self.history.complete_transcript(self.visit,100,'a'*64)
        expected=self.history.continuation(100,self.frozen)
        self.assertEqual(expected['items'],[{'role':'user','text':text}])
        for _ in range(20):
            visit=str(uuid.uuid4())
            self.history.open(visit,100,self.frozen,str(uuid.uuid4()),startup=expected)
            self.history.complete_transcript(visit,100,'a'*64)
            self.history.state(visit,100,'a'*64,'closed')
            self.assertEqual(self.history.continuation(100,self.frozen),expected)
        self.assertEqual(expected['sources'][0]['visit'],self.visit)
        self.assertEqual(expected['sources'][0]['sha256'],hashlib.sha256(text.encode()).hexdigest())

    def test_restore_keeps_latest_complete_sources_and_reports_older_omission(self):
        for index in range(40):
            self.history.item(self.visit,100,'a'*64,{'id':'source_'+str(index),'type':'transcriptSegment',
                'role':'user'if index%2==0 else'assistant','text':'Source '+str(index),
                'realtimeSessionId':self.session})
        self.history.complete_transcript(self.visit,100,'a'*64)
        value=self.history.continuation(100,self.frozen)
        self.assertTrue(value['more']);self.assertEqual(len(value['items']),32)
        self.assertEqual(value['items'][0]['text'],'Source 8')
        self.assertEqual(value['items'][-1]['text'],'Source 39')
        long=str(uuid.uuid4());generation=str(uuid.uuid4())
        self.history.open(long,100,self.frozen,generation)
        self.history.item(long,100,'a'*64,{'id':'newest','type':'transcriptSegment','role':'user',
            'text':'x'*16384,'realtimeSessionId':generation})
        self.history.complete_transcript(long,100,'a'*64)
        value=self.history.continuation(100,self.frozen)
        self.assertTrue(value['more']);self.assertEqual(value['items'][-1]['text'],'x'*16384)
        self.assertLessEqual(len(__import__('json').dumps(value['items']).encode()),18432)

    def test_incomplete_transcript_is_not_silently_restored_even_after_closed(self):
        self.history.item(self.visit,100,'a'*64,{'id':'old','type':'transcriptSegment',
            'role':'user','text':'Old value','realtimeSessionId':self.session})
        self.history.state(self.visit,100,'a'*64,'closed')
        with self.assertRaisesRegex(ValueError,'needs reconciliation'):
            CodexVoiceHistory(self.root/'visits').continuation(100,self.frozen)

    def native_fixture(self,closed=True):
        directory=self.root/'native'/'sessions';directory.mkdir(parents=True)
        path=directory/'selected.jsonl'
        rows=[{'type':'session_meta','payload':{'id':'native'}},
            {'type':'realtime_item','payload':{'id':'start','realtime_session_id':self.session,'type':'realtime_session_started'}},
            {'type':'realtime_item','payload':{'id':'correction','realtime_session_id':self.session,
                'type':'transcript_segment','role':'user','text':'Use hojasol'}}]
        if closed:rows.append({'type':'realtime_item','payload':{'id':'end','realtime_session_id':self.session,
            'type':'realtime_session_closed','outcome':'ended'}})
        path.write_text(''.join(json.dumps(row)+'\n'for row in rows))
        return path

    def test_canonical_recovery_requires_exact_thread_start_and_closure(self):
        path=self.native_fixture();info=path.stat()
        sources=native_transcripts(path,'native',[self.session],expected_file=(info.st_dev,info.st_ino))
        self.history.reconcile(100,self.frozen,sources)
        self.assertEqual(self.history.continuation(100,self.frozen)['items'],[{'role':'user','text':'Use hojasol'}])
        with self.assertRaises(ValueError):native_transcripts(path,'another',[self.session],expected_file=(info.st_dev,info.st_ino))
        with self.assertRaises(ValueError):native_transcripts(path,'native',[str(uuid.uuid4())],expected_file=(info.st_dev,info.st_ino))
        with self.assertRaises(ValueError):native_transcripts(path,'native',[self.session],expected_file=(0,0))
        rows=path.read_text().splitlines();path.write_text('\n'.join(rows[:-1])+'\n')
        with self.assertRaises(ValueError):native_transcripts(path,'native',[self.session],expected_file=(info.st_dev,info.st_ino))

    def test_native_recovery_refuses_fifo_without_waiting_for_writer(self):
        path=self.root/'fifo';os.mkfifo(path);info=path.stat()
        script=('from dashboard.codex_voice_history import native_transcripts; '
            +f'native_transcripts({str(path)!r},"native",[{self.session!r}],expected_file=({info.st_dev},{info.st_ino}))')
        result=subprocess.run([sys.executable,'-c',script],capture_output=True,timeout=2)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'Native history changed before recovery',result.stderr)

    def test_native_source_recovery_cannot_rewrite_existing_words(self):
        self.history.item(self.visit,100,'a'*64,{'id':'correction','type':'transcriptSegment','role':'user',
            'text':'Different retained words','realtimeSessionId':self.session})
        path=self.native_fixture();info=path.stat()
        sources=native_transcripts(path,'native',[self.session],expected_file=(info.st_dev,info.st_ino))
        with self.assertRaisesRegex(ValueError,'differs from canonical'):
            self.history.reconcile(100,self.frozen,sources)
        self.assertFalse(self.history.read(self.visit,100,'a'*64)['transcript_complete'])

    def test_provider_recovery_rechecks_owner_and_confines_native_root(self):
        path=self.native_fixture();db=sqlite3.connect(self.root/'native'/'state_5.sqlite')
        db.execute('CREATE TABLE threads(id TEXT,rollout_path TEXT,archived INTEGER)')
        db.execute('INSERT INTO threads VALUES(?,?,0)',('native',str(path)));db.commit();db.close()
        provider=object.__new__(Provider);provider.native_home=self.root/'native'
        provider.codex_voice_binding=Mock(return_value=self.frozen)
        source=provider.codex_voice_transcripts(self.frozen,[self.session])
        self.assertEqual(source[self.session]['items'][0]['text'],'Use hojasol')
        provider.codex_voice_binding.side_effect=[self.frozen,{**self.frozen,'native_thread':'changed'}]
        with self.assertRaises(ProviderUnavailable):provider.codex_voice_transcripts(self.frozen,[self.session])

    def test_restore_does_not_cross_binding_human_or_native_owner(self):
        self.history.item(self.visit,100,'a'*64,{'id':'source','type':'transcriptSegment','role':'user',
            'text':'Owned word','realtimeSessionId':self.session})
        for human,frozen in ((101,self.frozen),(100,{**self.frozen,'binding':'b'*64}),
                (100,{**self.frozen,'entry_binding':[100,100,8,'native']}),
                (100,{**self.frozen,'native_thread':'another'})):
            self.assertEqual(self.history.continuation(human,frozen)['items'],[])


if __name__=='__main__':unittest.main()
