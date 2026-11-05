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
from dashboard.codex_voice_history import CodexVoiceHistory, native_transcripts, native_memory_proof
from dashboard.live_transcription import wav_bytes
from dashboard.media_retention import RetentionUnavailable
from dashboard.provider import Provider, ProviderUnavailable


class History(unittest.TestCase):
    def test_pending_source_and_lost_offer_ack_survive_replacement_without_replay(self):
        self.history.retain_work(self.visit,100,'a'*64,['task'])
        self.assertEqual(self.history.pending_work(100,self.frozen),['task'])
        replacement=str(uuid.uuid4());self.history.open(replacement,100,self.frozen,str(uuid.uuid4()))
        result={'thread':'native','turn':'task','item':'final','revision':'a'*64}
        self.assertTrue(self.history.claim_result(replacement,100,self.frozen,result))
        third=str(uuid.uuid4());self.history.open(third,100,self.frozen,str(uuid.uuid4()))
        self.assertEqual(self.history.pending_work(100,self.frozen),[])
        self.assertFalse(self.history.claim_result(third,100,self.frozen,result),'A lost ACK must not repeat speech')
        value=self.history.read(replacement,100,'a'*64)
        self.assertEqual(value['result_offers'][0]['state'],'pending')
        self.assertNotIn('text',value['result_offers'][0],'The ledger keeps source references, not result copies')
        with self.assertRaises(ValueError):self.history.claim_result(third,100,{**self.frozen,'native_thread':'foreign'},result)
    def test_unsuccessful_tasks_stop_pending_growth_without_a_success_offer(self):
        self.history.retain_work(self.visit,100,'a'*64,['failed','still-running'])
        self.history.finish_work(self.visit,100,'a'*64,'failed','interrupted')
        self.assertEqual(self.history.pending_work(100,self.frozen),['still-running'])
        self.assertNotIn('result_offers',self.history.read(self.visit,100,'a'*64))
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
    def test_memory_catalog_scopes_sources_and_never_copies_transcripts(self):
        item={'id':'remembered','type':'transcriptSegment','role':'user','text':'Actual retained correction',
              'realtimeSessionId':self.session}
        self.history.item(self.visit,100,'a'*64,item)
        initial=self.history.memory_context(100,self.frozen)
        self.assertIn('Avatar backing policy:',initial)
        self.assertIn('No completed voice source is indexed yet',initial)
        initial_index=json.loads(next((self.history.root/'memory').glob('*.json')).read_text())
        self.assertEqual(initial_index['visits'],[])
        self.assertNotIn('latest_completed_visit',initial_index)
        self.assertNotIn('Actual retained correction',initial)
        self.assertLess(len(initial.encode()),2048)
        self.history.complete_transcript(self.visit,100,'a'*64)
        foreign=str(uuid.uuid4())
        self.history.open(foreign,101,{**self.frozen,'entry_binding':[101,101,9,'other']},str(uuid.uuid4()))
        self.history.complete_transcript(foreign,101,'a'*64)
        context=self.history.memory_context(100,self.frozen)
        index=list((self.history.root/'memory').glob('*.json'));self.assertEqual(len(index),1)
        value=json.loads(index[0].read_text())
        self.assertEqual([row['id']for row in value['visits']],[self.visit])
        self.assertEqual(value['source_root'],str(self.history.root.resolve()))
        self.assertIn(str(index[0]),context)
        self.assertNotIn('Actual retained correction',index[0].read_text()+context)
        self.assertNotIn(foreign,index[0].read_text()+context)
        self.assertLess(len(context.encode()),2048)
        self.assertEqual(self.history.memory_context(100,self.frozen),context)
        self.assertEqual(len(list((self.history.root/'memory').glob('*.json'))),1)
        self.assertEqual(len(self.history.list(100,'a'*64)),1)

    def test_previous_visit_reference_advances_only_for_completed_owned_speech(self):
        def speech(visit,generation,text):
            self.history.item(visit,100,'a'*64,{'id':str(uuid.uuid4()),'type':'transcriptSegment',
                'role':'user','text':text,'realtimeSessionId':generation})
        speech(self.visit,self.session,'First source')
        self.history.complete_transcript(self.visit,100,'a'*64)
        first=self.history.memory_context(100,self.frozen)
        self.assertIn('latest completed voice source is visit '+self.visit,first)
        empty=str(uuid.uuid4())
        self.history.open(empty,100,self.frozen,str(uuid.uuid4()))
        self.history.complete_transcript(empty,100,'a'*64)
        self.assertEqual(self.history.memory_context(100,self.frozen),first,
            'An empty reconnect must not move the historical speech reference')
        successor=str(uuid.uuid4());generation=str(uuid.uuid4())
        self.history.open(successor,100,self.frozen,generation)
        speech(successor,generation,'Second source')
        self.assertEqual(self.history.memory_context(100,self.frozen),first,
            'Unconfirmed speech must not advance the completed-source reference')
        self.history.complete_transcript(successor,100,'a'*64)
        second=self.history.memory_context(100,self.frozen)
        self.assertNotEqual(second,first)
        self.assertIn('latest completed voice source is visit '+successor,second)
        catalog=json.loads(next((self.history.root/'memory').glob('*.json')).read_text())
        self.assertEqual(catalog['latest_completed_visit'],successor)
        self.assertEqual([v['id']for v in catalog['visits']],[self.visit,successor])
        self.assertLess(len(second.encode()),2048)
        self.assertEqual(self.history.memory_context(100,self.frozen),second,
            'An unchanged source reference must still deduplicate across reconnects')

    def test_memory_catalog_contains_all512_sources_and_refuses_unsafe_destination(self):
        # Assemble the already bounded store directly; avoid512 fsyncs for a
        # catalog check. Real source admission/restart is covered separately.
        sample=self.history.read(self.visit,100,'a'*64)
        sample.update(transcript_complete=True,items=[{'id':'word','role':'user','text':'source'}])
        for sequence in range(512):
            ident=self.visit if sequence==0 else str(uuid.uuid4())
            value={**sample,'id':ident,'sequence':sequence+1}
            path=self.history.root/(ident+'.json');path.write_text(json.dumps(value));path.chmod(0o600)
        self.history.memory_context(100,self.frozen)
        path=next((self.history.root/'memory').glob('*.json'))
        self.assertEqual(len(json.loads(path.read_text())['visits']),512)
        self.assertLess(path.stat().st_size,65536)
        original=self.history.root/(self.visit+'.json');before=original.read_bytes()
        path.unlink();path.symlink_to(original)
        with self.assertRaises((OSError,ValueError)):self.history.memory_context(100,self.frozen)
        self.assertEqual(original.read_bytes(),before)

    def test_memory_catalog_accepts_reconciled_legacy_record_without_sequence(self):
        from dashboard.private_state import write_json
        record=self.history.read(self.visit,100,'a'*64);record.pop('sequence')
        write_json(self.history.root/(self.visit+'.json'),record)
        self.history.reconcile(100,self.frozen,{self.session:{'items':[
            {'id':'legacy','role':'user','text':'Retained legacy source'}],'source_sha256':'c'*64}})
        self.assertIsNotNone(self.history.memory_context(100,self.frozen))
        path=next((self.history.root/'memory').glob('*.json'))
        self.assertEqual(json.loads(path.read_text())['visits'][0]['sequence'],0)

    def test_memory_context_deduplicates_reconnects_and_lost_ack_with_native_proof(self):
        self.history.item(self.visit,100,'a'*64,{'id':'source','type':'transcriptSegment',
            'role':'user','text':'Old source','realtimeSessionId':self.session})
        self.history.complete_transcript(self.visit,100,'a'*64)
        context=self.history.memory_context(100,self.frozen)
        native=self.root/'native.jsonl'
        def append(value):
            with native.open('a')as stream:stream.write(json.dumps(value)+'\n')
        append({'type':'session_meta','payload':{'id':'native'}})
        def observe(owner,text,checkpoint=None):
            info=native.stat()
            return native_memory_proof(native,'native',text,checkpoint,expected_file=(info.st_dev,info.st_ino))
        provider=Mock();provider.codex_voice_memory.side_effect=observe
        def inject(text):
            append({'type':'response_item','payload':{'type':'message','role':'developer',
                'content':[{'type':'input_text','text':text}]}})
            raise OSError('Native saved context; ACK was lost')
        first=Mock();first.remember.side_effect=inject
        with self.assertRaises(OSError):self.history.remember(100,self.frozen,context,first,provider)
        self.history=CodexVoiceHistory(self.history.root)
        self.assertEqual(self.history.memory_context(100,self.frozen),context)
        successor=Mock()
        for _ in range(3):
            self.assertEqual(self.history.remember(100,self.frozen,context,successor,provider),'confirmed')
        self.assertEqual(first.remember.call_count,1);successor.remember.assert_not_called()
        # A native compaction explicitly removed this confirmed context. Its
        # successor receives one fresh context, not a replay of uncertain work.
        append({'type':'compacted','payload':{'replacement_history':[]}})
        def admit(text):append({'type':'response_item','payload':{'type':'message','role':'developer',
            'content':[{'type':'input_text','text':text}]}})
        successor.remember.side_effect=admit
        self.assertEqual(self.history.remember(100,self.frozen,context,successor,provider),'confirmed')
        self.assertEqual(self.history.remember(100,self.frozen,context,successor,provider),'confirmed')
        self.assertEqual(successor.remember.call_count,1)
        latest=str(uuid.uuid4());generation=str(uuid.uuid4())
        self.history.open(latest,100,self.frozen,generation)
        self.history.item(latest,100,'a'*64,{'id':'later','type':'transcriptSegment',
            'role':'user','text':'Later completed speech','realtimeSessionId':generation})
        self.history.complete_transcript(latest,100,'a'*64)
        changed=self.history.memory_context(100,self.frozen)
        self.assertNotEqual(changed,context)
        self.assertEqual(self.history.remember(100,self.frozen,changed,successor,provider),'confirmed')
        self.assertEqual(successor.remember.call_count,2,'A changed latest source needs one new contextual reference')
        self.assertEqual(self.history.remember(100,self.frozen,changed,successor,provider),'confirmed')
        self.assertEqual(successor.remember.call_count,2,'Empty reconnects must not repeat that update')

    def test_queued_or_missing_memory_write_is_not_repeated_on_new_connection(self):
        self.history.item(self.visit,100,'a'*64,{'id':'source','type':'transcriptSegment',
            'role':'user','text':'Old source','realtimeSessionId':self.session})
        self.history.complete_transcript(self.visit,100,'a'*64)
        context=self.history.memory_context(100,self.frozen)
        provider=Mock();provider.codex_voice_memory.return_value={
            'file':[1,1],'offset':100,'found':False,'compacted':False}
        first=Mock();second=Mock()
        self.assertEqual(self.history.remember(100,self.frozen,context,first,provider),'pending')
        self.history=CodexVoiceHistory(self.history.root)
        self.history.memory_context(100,self.frozen)
        self.assertEqual(self.history.remember(100,self.frozen,context,second,provider),'pending')
        self.assertEqual(first.remember.call_count,1);second.remember.assert_not_called()

    def test_native_memory_proof_rejects_forged_role_wrong_thread_and_truncation(self):
        path=self.root/'proof.jsonl';text='Owner memory location'
        def line(value):return json.dumps(value)+'\n'
        header=line({'type':'session_meta','payload':{'id':'native'}})
        message={'type':'message','role':'user','content':[{'type':'input_text','text':text}]}
        path.write_text(header+line({'type':'response_item','payload':message}))
        info=path.stat();file=(info.st_dev,info.st_ino)
        proof=native_memory_proof(path,'native',text,None,expected_file=file)
        self.assertFalse(proof['found'])
        with self.assertRaises(ValueError):native_memory_proof(path,'foreign',text,None,expected_file=file)
        path.write_text(header)
        with self.assertRaises(ValueError):native_memory_proof(path,'native',text,proof,expected_file=file)

    def test_pending_proof_advances_across_more_than_four_mib_without_reinjection(self):
        self.history.item(self.visit,100,'a'*64,{'id':'source','type':'transcriptSegment',
            'role':'user','text':'Old source','realtimeSessionId':self.session})
        self.history.complete_transcript(self.visit,100,'a'*64)
        context=self.history.memory_context(100,self.frozen)
        native=self.root/'native.jsonl'
        native.write_text(json.dumps({'type':'session_meta','payload':{'id':'native'}})+'\n')
        def observe(owner,text,checkpoint=None):
            info=native.stat()
            return native_memory_proof(native,'native',text,checkpoint,expected_file=(info.st_dev,info.st_ino))
        provider=Mock();provider.codex_voice_memory.side_effect=observe
        voice=Mock()
        self.assertEqual(self.history.remember(100,self.frozen,context,voice,provider),'pending')
        for _ in range(5):
            with native.open('a')as stream:stream.write(json.dumps({'type':'unrelated','payload':'x'*1024*1024})+'\n')
            self.assertEqual(self.history.remember(100,self.frozen,context,Mock(),provider),'pending')
        catalog=json.loads(self.history._memory_path(100,self.frozen).read_text())
        self.assertGreater(catalog['native_context']['proof']['offset'],4*1024*1024)
        self.assertEqual(voice.remember.call_count,1)
        # A disconnected interval may itself exceed the observation bound.
        # Keep the uncertainty, advance a bounded observation, and keep voice
        # available without replaying the unconfirmed context operation.
        with native.open('a')as stream:
            for _ in range(5):stream.write(json.dumps({'type':'unrelated','payload':'x'*1024*1024})+'\n')
        successor=Mock()
        self.assertEqual(self.history.remember(100,self.frozen,context,successor,provider),'pending')
        successor.remember.assert_not_called()
        catalog=json.loads(self.history._memory_path(100,self.frozen).read_text())
        self.assertTrue(catalog['native_context']['proof']['gap'])
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
