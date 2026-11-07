"""Source-window selection: exact live input, no output promotion or second ASR."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from dashboard.openai_live_window import freeze_input_window
from dashboard.openai_live_seals import request_seal,accept_seal
import dashboard_openai_live_native_backend as fixtures


class Window(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.Backend('test_whole_source_to_native_and_current_result_once')
        self.f.setUp();self.addCleanup(self.f.doCleanups);self.f.ready()

    def freeze(self):
        f=self.f
        return freeze_input_window(f.visits,f.ident,100,f.owner,f.delegation)

    def event(self,kind,ident,text):
        f=self.f
        f.visits.event(f.ident,100,f.owner,{'type':kind,'event_id':ident,
            'delta':text,'start_ms':1.5,'end_ms':2.5})

    def test_window_excludes_assistant_language_and_freezes_exact_source(self):
        self.event('session.output_transcript.delta','out','Never promote this output.')
        first=self.freeze();self.assertEqual(first['text'],'Usá el nombre corregido: Río Cobre.')
        self.assertEqual(first['proof']['input_events'],1)
        self.event('session.input_transcript.delta','late',' A later correction.')
        self.assertEqual(self.freeze(),first,'Late input cannot rewrite an already frozen intent')
        self.assertEqual(self.f.asr,[]);self.assertEqual(self.f.imports,[])

    def test_next_window_preserves_late_input_without_repeating_old_language(self):
        f=self.f;first=self.freeze()
        self.event('session.input_transcript.delta','late','A later correction.')
        f.visits.recording(f.ident,100,f.owner['binding'],1,f.audio,f.provider)
        f.delegation='second'
        f.visits.event(f.ident,100,f.owner,{'type':'session.delegation.created','event_id':'second-request',
            'delegation':{'id':f.delegation,'target':'client'}})
        seal=request_seal(f.visits,f.ident,100,f.owner,f.delegation,f.provider)
        accept_seal(f.visits,f.ident,100,f.owner,{'type':'source_sealed','request':seal['request'],
            'through_ordinal':2,'capture_bytes':2*(len(f.audio)-44)},f.provider)
        second=self.freeze();self.assertEqual(second['text'],'A later correction.')
        self.assertEqual(second['proof']['journal_from'],first['proof']['journal_after'])
        self.assertEqual(f.asr,[])

    def test_missing_input_is_held_without_recognition_or_work(self):
        f=self.f
        # A separately prepared exact journal with no human input deltas.
        path=f.visits.root/(f.ident+'.events');rows=path.read_bytes().splitlines(keepends=True)
        path.write_bytes(b''.join(row for row in rows if b'session.input_transcript.delta' not in row))
        with self.assertRaisesRegex(ValueError,'No retained Live input language'):self.freeze()
        self.assertEqual(f.asr,[]);self.assertEqual(f.imports,[]);self.assertEqual(f.writes,[])
        self.assertNotIn('live_window',f.visits.read(f.ident,100,f.owner)['delegations'][f.delegation])
