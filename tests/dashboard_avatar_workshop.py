"""Actual pinned workshop validator and durable App state; no browser/provider."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.avatar_workshop import AvatarWorkshop,validate_design


class Workshop(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=AvatarWorkshop(self.root)
        self.vendor=Path(__file__).resolve().parents[1]/'dashboard/web/avatar-workshop'
        module=(self.vendor/'experiments/school-avatar-quest/model.mjs').as_uri()
        self.design=json.loads(subprocess.check_output(['node','--input-type=module','-e',
            'import {fresh} from '+json.dumps(module)+'; console.log(JSON.stringify(fresh()));'],timeout=4))
        self.ident=str(uuid.uuid4())

    def save(self,ident=None,design=None,parent=None,expected=0,human=100):
        return self.store.save(human,ident or self.ident,design or self.design,parent,expected)

    def test_current_color_and_acting_semantics_survive_account_roundtrip(self):
        d=copy.deepcopy(self.design)
        d['bodyColors']={body:'#2266ee' for body in ('pocket-dragon','modular-bot','moon-visitor','cloud-axolotl','comet-fox','little-mushroom')}
        g=d['gestures'][0];g.update(cue='sleep',performance='accessory/v1')
        g['props']=[{'id':'pillow','color':'#b185dc','side':'left','size':1.25}]
        self.save(design=d)
        actual=AvatarWorkshop(self.root).get(100,self.ident)['design']
        self.assertEqual(actual['bodyColors'],d['bodyColors'])
        self.assertEqual(actual['gestures'][0]['props'],g['props'])
        self.assertEqual(actual['gestures'][0]['performance'],'accessory/v1')
        self.assertEqual(actual['gestures'][0]['cue'],'sleep')
        bad=copy.deepcopy(d);bad['bodyColors']['custom-model']='#ff0000'
        with self.assertRaises(ValueError):validate_design(bad)

    def test_visual_and_voice_share_one_document_and_capacity_without_pointer_changes(self):
        visual=self.save()
        profile={'provider':'openai','api':'gpt-live','model':'gpt-live-1','voice':'cedar'}
        voice=str(uuid.uuid4())
        self.store.voice_save(100,voice,profile,'Warm.',None,0)
        selected=self.store.voice_select(100,voice,1,[profile])
        self.assertEqual(visual,self.store.snapshot(100))
        self.store.select(100,self.ident,1,activate=True)
        self.assertEqual(selected,self.store.voice_snapshot(100))
        self.store.max_versions=2
        with self.assertRaises(ValueError):self.save(ident=str(uuid.uuid4()),expected=2)
        self.assertEqual(self.store.voice_snapshot(100),selected)
        self.assertEqual(self.store.snapshot(100)['active'],self.ident)

    def test_catalogue_save_reload_select_and_use_preserve_previous_avatar(self):
        saved=self.save();self.assertIsNone(saved['active']);self.assertEqual(saved['editing'],self.ident)
        first=AvatarWorkshop(self.root).get(100,self.ident)
        self.assertEqual(first['design']['body'],'modular-bot')
        self.assertEqual(first['sha256'],validate_design(self.design)[1])
        used=self.store.select(100,self.ident,1,activate=True);self.assertEqual(used['active'],self.ident)
        changed=copy.deepcopy(self.design);changed['name']='Second version'
        second=str(uuid.uuid4());preview=self.save(second,changed,self.ident,2)
        self.assertEqual(preview['active'],self.ident);self.assertEqual(preview['editing'],second)
        cancelled=self.store.select(100,self.ident,3)
        self.assertEqual(cancelled['active'],self.ident);self.assertEqual(cancelled['editing'],self.ident)
        self.assertEqual(self.store.get(100,self.ident),first,'Editing never mutates the previous version')

    def test_layered_model_validator_and_durable_revision(self):
        script=Path(__file__).with_name('avatar_layer_model.mjs')
        subprocess.run(['node',str(script)],check=True,timeout=4)
        module=script.as_uri()
        layered=json.loads(subprocess.check_output(['node','--input-type=module','-e',
            'import {fixture} from '+json.dumps(module)+'; console.log(JSON.stringify(fixture));'],timeout=4).decode().splitlines()[-1])
        d=copy.deepcopy(self.design);d.update(avatarModel=layered,body='custom-model',characterStyle='model/v1',image=None)
        self.save(design=d)
        actual=AvatarWorkshop(self.root).get(100,self.ident)
        self.assertEqual(actual['design']['avatarModel']['schema'],'ascii-avatar-model/v2')
        self.assertEqual(actual['sha256'],validate_design(d)[1])
        self.assertIsNone(self.store.snapshot(100)['active'])
        with self.assertRaises(KeyError):self.store.get(200,self.ident)

    def test_custom_firefly_model_uses_same_original_validator_and_hash(self):
        model=json.loads((self.vendor/'skills/ascii-avatar-author/assets/example.avatar.json').read_text())
        d=copy.deepcopy(self.design);d.update(avatarModel=model,body='custom-model',characterStyle='model/v1',image=None)
        self.save(design=d)
        actual=self.store.get(100,self.ident)
        self.assertEqual(actual['design']['avatarModel']['schema'],'ascii-avatar-model/v1')
        self.assertEqual(actual['sha256'],validate_design(d)[1])
        invalid=copy.deepcopy(d);invalid['avatarModel']['nodes']*=65
        with self.assertRaises(ValueError):validate_design(invalid)

    def test_actor_isolation_covers_reads_parents_and_activation(self):
        self.save()
        self.assertEqual(self.store.snapshot(200)['versions'],[])
        with self.assertRaises(KeyError):self.store.get(200,self.ident)
        with self.assertRaises(KeyError):self.store.select(200,self.ident,0,activate=True)
        with self.assertRaises(KeyError):self.save(str(uuid.uuid4()),parent=self.ident,human=200)
        self.assertEqual(self.store.snapshot(200)['generation'],0)

    def test_lost_save_ack_never_duplicates_or_overwrites_later_selection(self):
        self.save();self.store.select(100,self.ident,1,activate=True)
        self.assertEqual(self.save()['generation'],2)
        self.assertEqual(len(self.store.snapshot(100)['versions']),1)
        changed=copy.deepcopy(self.design);changed['name']='Overwrite'
        with self.assertRaises(ValueError):self.save(design=changed,expected=2)
        with self.assertRaises(ValueError):self.store.select(100,self.ident,1)
        self.assertEqual(self.store.snapshot(100)['generation'],2)

    def test_capacity_refuses_without_removing_versions_or_changing_active(self):
        self.save();self.store.select(100,self.ident,1,activate=True)
        before=self.store.snapshot(100);self.store.max_versions=1
        with self.assertRaises(ValueError):self.save(str(uuid.uuid4()),parent=self.ident,expected=2)
        self.assertEqual(self.store.snapshot(100),before)
        self.store.max_versions=32;self.store.max_total_bytes=1
        with self.assertRaises(ValueError):self.save(str(uuid.uuid4()),parent=self.ident,expected=2)
        self.assertEqual(self.store.snapshot(100),before)

    def test_parent_design_identity_and_invalid_import_do_not_change_state(self):
        self.save();before=self.store.snapshot(100)
        d=copy.deepcopy(self.design);d['artId']=str(uuid.uuid4())
        with self.assertRaises(ValueError):self.save(str(uuid.uuid4()),d,self.ident,1)
        with self.assertRaises(ValueError):validate_design({'schema':'not-an-avatar'})
        self.assertEqual(self.store.snapshot(100),before)

    def test_private_state_symlink_is_refused_without_following(self):
        foreign=self.root/'foreign.json';foreign.write_text('{}')
        (self.store.root/'100.json').symlink_to(foreign)
        from scripts.speech_render import RenderError
        with self.assertRaises((ValueError,RenderError,OSError)):self.store.snapshot(100)
        self.assertEqual(foreign.read_text(),'{}')


if __name__=='__main__':unittest.main()
