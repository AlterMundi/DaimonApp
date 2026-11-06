"""Native original chronology, exact ownership and lost-ack preservation; no models."""
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import dashboard_openai_live as fixtures
from dashboard.live_transcription import wav_bytes
from dashboard.openai_live_originals import enroll_original
from dashboard.openai_live_visits import LiveCreations
from dashboard.provider import Provider, ProviderUnavailable


class Originals(unittest.TestCase):
    setUp=fixtures.DurableCreation.setUp
    create=fixtures.DurableCreation.create
    client=fixtures.DurableCreation.client
    success=fixtures.DurableCreation.success

    def prepare(self):
        self.visits.prepare(self.ident,100,self.owner);self.create()
        test=self
        class Owner:
            receiver={'db_path':str(Path(test.tmp.name)/'native.sqlite')}
            media_retention=None
            retained={}
            submissions=0
            allowed=True
            retain_voice_capture=staticmethod(Provider.retain_voice_capture)
            def authorized(self,human):return self.allowed and human==100
            def public_live_binding(self,binding):return dict(test.owner)
            def conversation_voice_submit(self,metadata,data,**options):
                assert options=={'foreground_dialogue':test.ident,'defer_foreground':True}
                assert not any(k in metadata for k in ('text','formulation','transcription'))
                self.submissions+=1
                self.retained[metadata['id']]={'id':metadata['id'],'entry_binding':test.owner['entry_binding'],
                    'foreground_dialogue':test.ident,'voice':{'audio_sha256':hashlib.sha256(data).hexdigest()},
                    'phase':'foreground_captured','native_acceptance':'not_requested'}
                return self.retained[metadata['id']]
            def conversation_input_status(self,ident):return self.retained[ident]
        self.provider=Owner()
        self.audio=wav_bytes(b'\0\0'*3200)
        self.receipt=self.visits.recording(self.ident,100,self.owner['binding'],0,self.audio,self.provider)

    def enroll(self,history=None):
        return enroll_original(history or self.visits,self.ident,100,self.owner,0,self.provider)

    def test_exact_original_once_without_text_or_work(self):
        self.prepare();result=self.enroll()
        self.assertEqual(result['state'],'observed');self.assertFalse(result['work_admitted'])
        self.assertEqual(result['id'],self.receipt['id']);self.assertEqual(self.provider.submissions,1)
        self.assertEqual(self.enroll(),result);self.assertEqual(self.provider.submissions,1)
        self.assertEqual(Path(str(self.provider.receiver['db_path'])+'.voice',result['id']).read_bytes(),self.audio)

    def test_lost_ack_reads_same_identity_without_resubmission(self):
        self.prepare();submit=self.provider.conversation_voice_submit
        def lost(*args,**kwargs):submit(*args,**kwargs);raise ProviderUnavailable()
        self.provider.conversation_voice_submit=lost
        self.assertEqual(self.enroll()['state'],'unconfirmed')
        self.assertEqual(self.enroll()['state'],'observed');self.assertEqual(self.provider.submissions,1)

    def test_unknown_intent_is_not_permission_to_send(self):
        self.prepare()
        self.provider.conversation_voice_submit=lambda *args,**kwargs:(_ for _ in ()).throw(ProviderUnavailable())
        self.provider.conversation_input_status=lambda ident:(_ for _ in ()).throw(ProviderUnavailable())
        self.assertEqual(self.enroll()['state'],'unconfirmed')
        self.assertEqual(self.enroll()['state'],'unconfirmed');self.assertEqual(self.provider.submissions,0)
        restarted=LiveCreations(self.root)
        self.assertEqual(self.enroll(restarted)['state'],'unconfirmed');self.assertEqual(self.provider.submissions,0)

    def test_restart_never_backfills_unattempted_recordings(self):
        self.prepare()
        with self.assertRaises(ValueError):self.enroll(LiveCreations(self.root))
        self.assertEqual(self.provider.submissions,0)

    def test_actor_replacement_and_changed_original_refuse(self):
        self.prepare();self.provider.allowed=False
        with self.assertRaises(ProviderUnavailable):self.enroll()
        self.provider.allowed=True
        path=Path(str(self.provider.receiver['db_path'])+'.voice',self.receipt['id']);path.write_bytes(wav_bytes(b'\1\0'*3200))
        with self.assertRaises(ValueError):self.enroll()
        self.assertEqual(self.provider.submissions,0)

    def test_interrupted_prefix_is_review_not_native_input(self):
        self.prepare()
        from dashboard.codex_voice_history import history_lock
        with history_lock(self.root/'.lock'):
            value=self.visits.read(self.ident,100,self.owner);value['recordings'][0]['capture_stop']='interrupted_prefix';self.visits._write(value)
        self.assertEqual(self.enroll()['state'],'review_required');self.assertEqual(self.provider.submissions,0)


if __name__=='__main__':unittest.main()
