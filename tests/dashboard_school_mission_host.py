"""Concrete retained-selection authority; no injected accepting resolver."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.school_mission_host import resolve_selected


class Selection(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.id=str(uuid.uuid4())
        self.tools=self.root/'bindings.json'
        self.tools.write_text(json.dumps({'learner_id':'synthetic-learner','companion_ref':'synthetic-being'}));self.tools.chmod(0o600)
        self.context={'request_id':self.id,'mission_id':'ascii','space_ref':'synthetic-app','learner_id':'synthetic-learner','daimon_ref':'synthetic-being'}
        self.value=dict(schema='school-creativity.app-selection/v1',active=True,actor=100,human_ref='human:synthetic:own',application_id='synthetic-app',tool_bindings=str(self.tools),request=self.context)
        self.path=self.root/'selected.json'
        self.config=dict(application_id='synthetic-app',shared_auth={'human_ref':'human:synthetic:own'},school_mission={'selection':str(self.path)})
        self.write(self.value)
        class Provider:
            human=100
            def authorized(self,actor):return actor==100
        self.provider=Provider()

    def write(self,value):
        raw=json.dumps(value).encode();self.path.write_bytes(raw);self.path.chmod(0o600)
        self.config['school_mission']['selection_sha256']=hashlib.sha256(raw).hexdigest()

    def test_exact_owner_application_human_and_request_are_required(self):
        self.assertEqual(resolve_selected(self.config,self.provider,100,self.id),self.context)
        for actor,request in ((200,self.id),(100,str(uuid.uuid4()))):
            with self.assertRaises(KeyError):resolve_selected(self.config,self.provider,actor,request)
        for key,value in (('human_ref','human:synthetic:foreign'),('application_id','other-app'),('active',False)):
            self.write({**self.value,key:value})
            with self.assertRaises(KeyError):resolve_selected(self.config,self.provider,100,self.id)
        self.write(self.value)
        self.provider.authorized=lambda actor:False
        with self.assertRaises(KeyError):resolve_selected(self.config,self.provider,100,self.id)

    def test_changed_selection_and_mismatched_companion_fail_without_replacing_work(self):
        original=self.path.read_bytes();self.path.write_bytes(original+b' ')
        with self.assertRaises(ValueError):resolve_selected(self.config,self.provider,100,self.id)
        self.write(self.value)
        self.tools.write_text(json.dumps({'learner_id':'synthetic-learner','companion_ref':'other-being'}))
        with self.assertRaises(ValueError):resolve_selected(self.config,self.provider,100,self.id)
        self.assertEqual(self.path.read_bytes(),original)


if __name__=='__main__':unittest.main()
