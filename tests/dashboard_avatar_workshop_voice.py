"""Real atomic actor storage, without browser, provider calls or new stores."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.avatar_workshop import AvatarWorkshop,WorkshopConflict


class VoiceRevisions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=AvatarWorkshop(self.temp.name)
        self.profile={'provider':'openai','api':'gpt-live','model':'gpt-live-1','voice':'cedar'}
        self.ident=str(uuid.uuid4())

    def save(self,ident=None,parent=None,generation=0,delivery='Warm, with clear pauses.',human=100):
        return self.store.voice_save(human,ident or self.ident,self.profile,delivery,parent,generation)

    def test_save_reload_use_and_lost_ack_keep_visual_and_frozen_voice(self):
        before=self.store.snapshot(100);saved=self.save();self.assertIsNone(saved['active'])
        self.assertEqual(before,self.store.snapshot(100))
        loaded=AvatarWorkshop(self.temp.name)
        self.assertEqual(loaded.voice_snapshot(100),saved)
        self.assertEqual(self.save(),saved)
        selected=loaded.voice_select(100,self.ident,1,[self.profile])
        frozen=loaded.voice_for_conversation(100,[self.profile])
        other=str(uuid.uuid4());loaded.voice_save(100,other,self.profile,'Neutral.',self.ident,2)
        loaded.voice_select(100,other,3,[self.profile])
        self.assertEqual(frozen['id'],self.ident)
        self.assertEqual(frozen['delivery'],'Warm, with clear pauses.')
        self.assertEqual(selected['active'],self.ident)
        self.assertEqual(loaded.voice_for_conversation(100,[self.profile])['id'],other)
        self.assertEqual(before,loaded.snapshot(100))
        self.assertEqual(len(list(Path(self.temp.name).glob('**/*.json'))),1)

    def test_stale_immutable_foreign_and_incompatible_actions_preserve_current(self):
        self.save();self.store.voice_select(100,self.ident,1,[self.profile]);before=self.store.voice_snapshot(100)
        with self.assertRaises(WorkshopConflict):self.save(delivery='Replacement')
        with self.assertRaises(WorkshopConflict):self.store.voice_select(100,self.ident,1,[self.profile])
        with self.assertRaises(KeyError):self.store.voice_select(101,self.ident,0,[self.profile])
        with self.assertRaises(ValueError):self.store.voice_select(100,self.ident,2,[])
        with self.assertRaises(ValueError):self.store.voice_for_conversation(100,[])
        self.assertEqual(before,self.store.voice_snapshot(100))
        self.assertEqual(self.store.voice_snapshot(101)['versions'],[])

    def test_invalid_delivery_and_profile_never_write(self):
        for text in ['x'*1025,'unsafe\0text',False]:
            with self.assertRaises(ValueError):self.save(delivery=text)
        bad=copy.deepcopy(self.profile);bad['voice']='https://untrusted.example/voice'
        with self.assertRaises(ValueError):self.store.voice_save(100,self.ident,bad,'',None,0)
        self.assertEqual(self.store.voice_snapshot(100)['versions'],[])

    def test_same_existing_quota_and_failed_commit_keep_previous_selection(self):
        self.store.max_versions=1;self.save();before=self.store.voice_snapshot(100)
        with self.assertRaises(ValueError):self.save(ident=str(uuid.uuid4()),generation=1)
        self.store.max_total_bytes=8
        with self.assertRaises(ValueError):self.store.voice_select(100,self.ident,1,[self.profile])
        self.store.max_total_bytes=32*1024*1024
        self.assertEqual(before,self.store.voice_snapshot(100))

if __name__=='__main__':unittest.main()
