"""Native voice original retention/restart; no ASR, native input or inference."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.codex_voice_history import CodexVoiceHistory
from dashboard.live_transcription import wav_bytes
from dashboard.media_retention import RetentionUnavailable
from dashboard.provider import Provider


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


if __name__=='__main__':unittest.main()
