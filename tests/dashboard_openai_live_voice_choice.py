"""Frozen logical voice selection across real visit journals; no provider calls."""
import copy
from pathlib import Path
import sys
import unittest
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from dashboard.avatar_workshop import AvatarWorkshop
from dashboard.voice_studio import choice,apply_choice,configured_profiles
import dashboard_openai_live as fixtures


class Choices(unittest.TestCase):
    setUp=fixtures.DurableCreation.setUp
    create=fixtures.DurableCreation.create
    closed=fixtures.DurableCreation.closed
    client=fixtures.DurableCreation.client
    success=fixtures.DurableCreation.success

    def test_repeated_physical_successors_keep_a_until_a_new_logical_start(self):
        profile={'provider':'openai','api':'gpt-live','model':'gpt-live-1','voice':'cedar'}
        self.spec['audio']={'output':{'voice':'cedar'}}
        store=AvatarWorkshop(Path(self.tmp.name)/'app-state');a=str(uuid.uuid4());b=str(uuid.uuid4())
        store.voice_save(100,a,profile,'Warm.',None,0);store.voice_select(100,a,1,[profile])
        first=choice(store.voice_for_conversation(100,[profile]),profile)
        self.visits.prepare(self.ident,100,self.owner,backend_mode='native',voice_choice=first)
        self.create();self.closed(usage=1)
        store.voice_save(100,b,profile,'Neutral.',a,2);store.voice_select(100,b,3,[profile])
        previous=self.ident
        for _ in range(3):
            ident=str(uuid.uuid4())
            prepared=self.visits.prepare(ident,100,self.owner,backend_mode='native',
                voice_choice=choice(None,profile),voice_continuation=previous)
            self.assertEqual(prepared['voice_choice'],first)
            self.assertTrue(apply_choice(self.spec,prepared['voice_choice'])['instructions'].endswith('Warm.'))
            self.create(ident=ident);self.closed(ident,usage=1)
            retained=self.visits.read(ident,100,self.owner)
            self.assertEqual(retained['voice_continuation_from'],previous)
            self.assertNotIn('voice_continuation_from',retained['voice_choice'])
            previous=ident
        new=choice(store.voice_for_conversation(100,[profile]),profile)
        self.assertEqual(new['revision'],b)
        prepared=self.visits.prepare(str(uuid.uuid4()),100,self.owner,backend_mode='native',voice_choice=new)
        self.assertEqual(prepared['voice_choice']['delivery'],'Neutral.')
        self.assertEqual(len(self.calls),4)

    def test_foreign_binding_and_corrupt_or_incompatible_choices_refuse(self):
        profile={'provider':'openai','api':'gpt-live','model':'gpt-live-1','voice':'cedar'}
        frozen=choice(None,profile)
        self.visits.prepare(self.ident,100,self.owner,backend_mode='native',voice_choice=frozen)
        self.create();self.closed(usage=1)
        changed=copy.deepcopy(self.owner);changed['binding']='b'*64
        with self.assertRaises(ValueError):self.visits.prepare(str(uuid.uuid4()),100,changed,backend_mode='native',voice_choice=frozen,voice_continuation=self.ident)
        corrupted=copy.deepcopy(frozen);corrupted['delivery']='Replacement'
        with self.assertRaises(ValueError):self.visits.prepare(str(uuid.uuid4()),100,self.owner,backend_mode='native',voice_choice=corrupted)
        with self.assertRaises(ValueError):apply_choice(self.spec,frozen)
        self.assertEqual(len(self.calls),1)

    def test_catalogue_only_reports_current_explicit_configuration(self):
        self.assertEqual(configured_profiles({}),[])
        config={'openai_live':{'enabled':True,'session_options':{'audio':{'output':{'voice':'cedar'}}}}}
        self.assertEqual(configured_profiles(config),[{'provider':'openai','api':'gpt-live','model':'gpt-live-1','voice':'cedar'}])
        config['voice_studio']={'voices':['marin']}
        profiles=configured_profiles(config);self.assertEqual([p['voice'] for p in profiles],['cedar','marin'])
        selected=choice(None,profiles[1])
        spec={**self.spec,'audio':{'output':{'voice':'cedar'}}}
        self.assertEqual(apply_choice(spec,selected,profiles)['audio']['output']['voice'],'marin')
        self.assertEqual(spec['audio']['output']['voice'],'cedar')
        with self.assertRaises(ValueError):apply_choice(spec,selected,profiles[:1])
        config['openai_live']['enabled']=False
        self.assertEqual(configured_profiles(config),[])

if __name__=='__main__':unittest.main()
