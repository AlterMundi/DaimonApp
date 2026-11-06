"""Completed acoustic derivatives enter the native journal once; no real models."""
import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from dashboard.openai_live_transcription import commit_interpretation
from dashboard.openai_live_visits import LiveCreations
from dashboard.provider import ProviderUnavailable
import dashboard_openai_live_transcription as fixtures

class NativeCommit(unittest.TestCase):
    setUp=fixtures.Interpretation.setUp
    create=fixtures.Interpretation.create
    client=fixtures.Interpretation.client
    success=fixtures.Interpretation.success
    prepare=fixtures.Interpretation.prepare
    enroll=fixtures.Interpretation.enroll
    ready=fixtures.Interpretation.ready
    recognizer=fixtures.Interpretation.recognizer
    run_original=fixtures.Interpretation.run_original

    def setup_commit(self):
        self.ready();self.interpretation=self.run_original();self.native_writes=[]
        def write(body):
            self.native_writes.append(dict(body))
            original=self.provider.retained[body['id']]
            original.update(phase='foreground',text=body['text'])
            original['voice']['transcription']={
                'actual_transcriber':body['model'],'capture_id':body['id'],
                'audio_sha256':body['audio_sha256'],'audio_millis':body['audio_millis'],
                'transcription_millis':body['transcription_millis']}
            return copy.deepcopy(original)
        self.provider.conversation_foreground_interpret=write

    def commit(self,history=None):
        return commit_interpretation(history or self.visits,self.ident,100,self.owner,0,self.provider)

    def test_exact_completed_derivative_once_and_restart_cache(self):
        self.setup_commit();result=self.commit()
        self.assertEqual(result['state'],'observed');self.assertFalse(result['work_admitted'])
        self.assertEqual(result['capture_id'],self.receipt['id'])
        self.assertEqual(self.native_writes[0]['text'],self.interpretation['text'])
        self.assertEqual(self.native_writes[0]['audio_sha256'],self.receipt['audio_sha256'])
        self.assertEqual(self.commit(LiveCreations(self.root)),result)
        self.assertEqual(len(self.native_writes),1);self.assertEqual(len(self.sent),1)
        slot=self.visits.read(self.ident,100,self.owner)['native_originals']['0']
        self.assertNotIn('native_commit_reserve',slot)
        self.assertNotIn('native_commit',self.enroll())

    def test_lost_ack_only_reads_same_native_original_after_restart(self):
        self.setup_commit();write=self.provider.conversation_foreground_interpret
        def lost(body):write(body);raise ProviderUnavailable('Synthetic lost native acknowledgement')
        self.provider.conversation_foreground_interpret=lost
        self.assertEqual(self.commit()['state'],'unconfirmed')
        self.assertEqual(self.commit(LiveCreations(self.root))['state'],'observed')
        self.assertEqual(len(self.native_writes),1);self.assertEqual(len(self.sent),1)

    def test_unknown_intent_is_not_another_write_or_asr(self):
        self.setup_commit()
        def unknown(body):self.native_writes.append(dict(body));raise ProviderUnavailable()
        self.provider.conversation_foreground_interpret=unknown
        self.assertEqual(self.commit()['state'],'unconfirmed')
        self.assertEqual(self.commit(LiveCreations(self.root))['state'],'unconfirmed')
        self.assertEqual(self.commit()['state'],'unconfirmed')
        self.assertEqual(len(self.native_writes),1);self.assertEqual(len(self.sent),1)
        self.assertEqual(len(self.visits.read(self.ident,100,self.owner)['native_originals']['0']['native_commit_reserve']),1024)

    def test_revocation_after_write_preserves_receipt_but_not_exposure(self):
        self.setup_commit();write=self.provider.conversation_foreground_interpret
        def revoke(body):result=write(body);self.provider.allowed=False;return result
        self.provider.conversation_foreground_interpret=revoke
        with self.assertRaises(ProviderUnavailable):self.commit()
        self.assertEqual(self.visits.read(self.ident,100,self.owner)['native_originals']['0']['native_commit']['state'],'observed')
        self.provider.allowed=True
        self.assertEqual(self.commit()['state'],'observed');self.assertEqual(len(self.native_writes),1)

    def test_uncompleted_different_native_proof_and_older_reader_refuse(self):
        self.setup_commit()
        self.provider.presentation=lambda command:{'binding':self.owner['binding']}
        with self.assertRaises(ValueError):self.commit()
        self.assertEqual(self.native_writes,[])
        native=self.provider.retained[self.receipt['id']]
        native['voice']['transcription']={'actual_transcriber':'different-recognizer'};native['phase']='foreground'
        with self.assertRaises(ValueError):self.commit()
        self.assertEqual(self.native_writes,[])
        native['voice']['transcription']=None;native['phase']='foreground_captured'
        value=self.visits.read(self.ident,100,self.owner)
        value['native_originals']['0']['interpretation']['state']='intent';self.visits._write(value)
        with self.assertRaises(ValueError):self.commit()
        self.assertEqual(self.native_writes,[])

    def test_receipt_space_reserved_before_native_write(self):
        self.setup_commit()
        value=self.visits.read(self.ident,100,self.owner)
        self.visits.max_record_bytes=len(json.dumps(value).encode())+100
        with self.assertRaises(ValueError):self.commit()
        self.assertEqual(self.native_writes,[])
        self.assertNotIn('native_commit',self.visits.read(self.ident,100,self.owner)['native_originals']['0'])

    def test_completed_derivative_can_finish_known_unattempted_commit_after_restart(self):
        self.setup_commit()
        self.assertEqual(self.commit(LiveCreations(self.root))['state'],'observed')
        self.assertEqual(len(self.native_writes),1);self.assertEqual(len(self.sent),1)

if __name__=='__main__':unittest.main()
