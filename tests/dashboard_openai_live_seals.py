"""Exact raw capture boundaries, trusted delegation and no inference/work."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from dashboard.openai_live_seals import request_seal, accept_seal
from dashboard.openai_live_visits import LiveCreations
from dashboard.provider import ProviderUnavailable
import dashboard_openai_live_originals as fixtures


class Seals(unittest.TestCase):
    setUp=fixtures.Originals.setUp
    create=fixtures.Originals.create
    client=fixtures.Originals.client
    success=fixtures.Originals.success
    prepare=fixtures.Originals.prepare

    def ready(self):
        self.prepare();self.observe('work-1')

    def observe(self, delegation, target='client'):
        self.visits.event(self.ident,100,self.owner,{'type':'session.delegation.created',
            'event_id':'event-'+delegation,'offset_ms':200,
            'delegation':{'id':delegation,'target':target}})

    def request(self, delegation='work-1', history=None):
        return request_seal(history or self.visits,self.ident,100,self.owner,delegation,self.provider)

    def accept(self, command, through=1, count=6400, history=None, **extra):
        return accept_seal(history or self.visits,self.ident,100,self.owner,
            {'type':'source_sealed','request':command['request'],
             'through_ordinal':through,'capture_bytes':count,**extra},self.provider)

    def test_one_exact_capture_boundary_no_copy_interpretation_or_work(self):
        self.ready();command=self.request()
        self.assertEqual(command['visit'],self.ident);self.assertEqual(command['binding'],self.owner['binding'])
        self.assertIsNone(self.request())
        result=self.accept(command)
        self.assertEqual(result['state'],'sealed');self.assertFalse(result['work_admitted'])
        self.assertEqual(result['recordings'],[{key:self.receipt[key] for key in ('ordinal','id','audio_sha256','audio_bytes')}])
        self.assertEqual(self.accept(command),result)
        self.assertEqual(self.provider.submissions,0)
        value=self.visits.read(self.ident,100,self.owner)
        self.assertNotIn('native_originals',value)
        self.assertNotIn('source_seal_reserve',value['delegations']['work-1'])

    def test_only_trusted_client_delegations_can_request_and_cannot_accept_text(self):
        self.ready()
        with self.assertRaises(ValueError):self.request('a-transcript-fragment')
        self.observe('responses','responses')
        with self.assertRaises(ValueError):self.request('responses')
        command=self.request()
        with self.assertRaises(ValueError):self.accept(command,text='Synthetic human words')
        with self.assertRaises(ValueError):self.accept(command,through=True)
        with self.assertRaises(ValueError):self.accept({'request':'another-request'})

    def test_missing_upload_and_byte_mismatch_preserve_pending_request(self):
        self.ready();command=self.request()
        with self.assertRaises(ValueError):self.accept(command,through=2,count=12800)
        with self.assertRaises(ValueError):self.accept(command,count=6402)
        value=self.visits.read(self.ident,100,self.owner)
        self.assertEqual(value['delegations']['work-1']['source_seal']['state'],'requested')
        self.visits.recording(self.ident,100,self.owner['binding'],1,self.audio,self.provider)
        self.assertEqual(self.accept(command,through=2,count=12800)['through_ordinal'],2)

    def test_later_frames_and_delegations_do_not_change_an_existing_boundary(self):
        self.ready();command=self.request();self.observe('work-2')
        self.assertIsNone(self.request('work-2'))
        first=self.accept(command)
        next_command=self.request('work-2')
        self.visits.recording(self.ident,100,self.owner['binding'],1,self.audio,self.provider)
        self.visits.recording(self.ident,100,self.owner['binding'],2,self.audio,self.provider)
        second=self.accept(next_command,through=3,count=19200)
        self.assertEqual([r['ordinal'] for r in second['recordings']],[1,2])
        self.assertEqual(self.accept(command),first)
        with self.assertRaises(ValueError):self.accept(command,through=3,count=19200)
        self.observe('empty')
        empty=self.accept(self.request('empty'),through=3,count=19200)
        self.assertEqual(empty['state'],'empty');self.assertEqual(empty['recordings'],[])

    def test_restart_cannot_request_or_accept_unconfirmed_capture(self):
        self.ready();command=self.request();restarted=LiveCreations(self.root)
        self.assertIsNone(self.request(history=restarted))  # No second request.
        with self.assertRaises(ValueError):self.accept(command,history=restarted)
        self.accept(command)
        self.assertEqual(self.accept(command,history=restarted)['state'],'sealed')

    def test_prefix_or_ended_capture_cannot_be_sealed_as_a_new_complete_prefix(self):
        self.ready();command=self.request()
        value=self.visits.read(self.ident,100,self.owner)
        value['recordings'][0]['capture_stop']='interrupted_prefix';self.visits._write(value)
        with self.assertRaises(ValueError):self.accept(command)
        self.visits.end_capture(self.ident,100,self.owner['binding'])
        with self.assertRaises(ValueError):self.accept(command)

    def test_revoked_viewer_cannot_observe_or_start_seals(self):
        self.ready();command=self.request();self.accept(command)
        self.provider.allowed=False
        with self.assertRaises(ProviderUnavailable):self.request()
        with self.assertRaises(ProviderUnavailable):self.accept(command)

    def test_receipt_space_is_reserved_before_a_capture_control_request(self):
        self.ready();value=self.visits.read(self.ident,100,self.owner)
        self.visits.max_record_bytes=len(json.dumps(value).encode())+100
        with self.assertRaises(ValueError):self.request()
        self.assertNotIn('source_seal',self.visits.read(self.ident,100,self.owner)['delegations']['work-1'])


if __name__=='__main__':unittest.main()
