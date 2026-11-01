"""Exact acoustic span/provider correlation with no ASR, Sol, hardware or network."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.native_acoustic import NativeAcousticSession
from dashboard.native_foreground import ForegroundUnavailable


class Stream:
    def __init__(self):self.events=[]
    def activity_start(self):self.events.append(('start',))
    def append(self,pcm):self.events.append(('pcm',pcm))
    def activity_end(self):self.events.append(('end',))


class Bridge:
    def __init__(self):self.stream=Stream();self.captures=[];self.transcripts=[]
    def capture(self,*args):self.captures.append(args)
    def transcript(self,*args):self.transcripts.append(args)


class Detector:
    def __init__(self):self.frames=[];self.boundaries=[]
    async def feed(self,pcm):self.frames.append(pcm)
    async def boundary(self,value):self.boundaries.append(value)


class Acoustic(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bridge=Bridge();self.detector=Detector();self.events=[]
        async def notify(value):self.events.append(value)
        self.session=NativeAcousticSession(self.bridge,self.detector,{'a'*32:'b'*64},notify)
    def activity(self,end,generation=1,*,onset=None,endpoint=False):
        value={'type':'activity','audio_bytes':end,'generation':generation,'speaking':not endpoint}
        if onset:value['onset']={'audio_bytes':onset,'generation':generation}
        if endpoint:value['endpoint']={'audio_bytes':end,'generation':generation,'probability':.9,'authority':'analysis_only'}
        return value
    async def ack(self,kind,offset):
        await self.session.provider_event({'type':'voice_activity','activity':kind,'audio_offset':offset,
                                           'source':'provider_manual_activity_ack'})
    async def first(self):
        await self.session.feed(b'\1\0'*1600)
        await self.session.activity(self.activity(3200,onset=3072))
        await self.ack('ACTIVITY_START','0s')
        await self.session.feed(b'\0\0'*1600)
        await self.session.activity(self.activity(6400,endpoint=True))
    async def test_first_local_marker_freezes_each_phrase_question_scope(self):
        selected={'c'*32:'d'*64}
        await self.session.marker(640,selected)
        selected['c'*32]='e'*64
        await self.first()
        self.assertEqual(self.bridge.captures[0][2],{'c'*32:'d'*64})
        with self.assertRaises(ForegroundUnavailable):await self.session.marker(640,{})

    async def test_endpoint_ends_native_audio_before_transcript_or_integrator(self):
        await self.first()
        self.assertEqual([v[0] for v in self.bridge.stream.events],['start','pcm','pcm','end'])
        self.assertEqual(self.bridge.transcripts,[])
        self.assertEqual(self.bridge.captures[0][1],b'\1\0'*1600+b'\0\0'*1600)
        self.assertEqual(self.events[-1]['type'],'phrase_end')
        self.assertEqual(self.detector.boundaries,[{'generation':1,'audio_bytes':6400}])
        await self.session.provider_event({'type':'input_transcript','text':'Hello'})
        self.assertEqual(self.bridge.transcripts,[])
        await self.ack('ACTIVITY_END','0.2s')
        self.assertEqual(self.bridge.transcripts,[(self.bridge.captures[0][0],'Hello')])
    async def test_early_noninterim_text_is_not_committed_as_a_whole_original(self):
        await self.session.feed(b'\1\0'*1600)
        await self.session.activity(self.activity(3200,onset=3072))
        await self.ack('ACTIVITY_START','0s')
        with self.assertRaises(ForegroundUnavailable):
            await self.session.provider_event({'type':'input_transcript','text':'Unexpected early segment'})
        await self.session.close()
        self.assertEqual(self.bridge.transcripts,[])
        self.assertEqual(self.bridge.captures[0][1],b'\1\0'*1600)

    async def test_owned_acoustic_silence_ends_native_activity_without_a_semantic_claim(self):
        await self.session.feed(b'\1\0'*1600)
        await self.session.activity(self.activity(3200,onset=3072))
        await self.ack('ACTIVITY_START','0s')
        await self.session.feed(b'\0\0'*1600)
        value=self.activity(6400)
        value.update(speaking=False,endpoint={'generation':1,'audio_bytes':6400,
                                            'authority':'acoustic_silence','silence_millis':1600})
        await self.session.activity(value)
        self.assertEqual(self.bridge.stream.events[-1],('end',))
        self.assertEqual(len(self.bridge.captures),1)
        self.assertEqual(self.bridge.transcripts,[],'A silence boundary is not a transcript or admission')

    async def test_end_ack_before_transcript_has_the_same_source(self):
        await self.first();await self.ack('ACTIVITY_END','0.2s')
        self.assertEqual(self.bridge.transcripts,[])
        await self.session.provider_event({'type':'input_transcript','text':'Original'})
        self.assertEqual(self.bridge.transcripts[0][0],self.bridge.captures[0][0])
    async def test_fragmented_transcript_waits_for_explicit_end_and_matching_audio_ack(self):
        await self.first()
        await self.session.provider_event({'type':'input_transcript','text':'First part ','finished':False})
        await self.ack('ACTIVITY_END','0.2s')
        self.assertEqual(self.bridge.transcripts,[],'Audio end alone cannot commit a partial transcript')
        await self.session.provider_event({'type':'input_transcript','text':'and the rest.','finished':False})
        self.assertEqual(self.events[-1]['text'],'First part and the rest.')
        self.assertEqual(self.bridge.transcripts,[])
        await self.session.provider_event({'type':'input_transcript','text':'','finished':True})
        self.assertEqual(self.bridge.transcripts,[(self.bridge.captures[0][0],'First part and the rest.')])
    async def test_explicit_fragments_can_arrive_while_captured_speech_is_still_open(self):
        await self.session.feed(b'\1\0'*1600)
        await self.session.activity(self.activity(3200,onset=3072));await self.ack('ACTIVITY_START','0s')
        await self.session.provider_event({'type':'input_transcript','text':'Early ','finished':False})
        self.assertEqual(self.bridge.transcripts,[])
        await self.session.feed(b'\0\0'*1600);await self.session.activity(self.activity(6400,endpoint=True))
        await self.session.provider_event({'type':'input_transcript','text':'ending.','finished':True})
        self.assertEqual(self.bridge.transcripts,[])
        await self.ack('ACTIVITY_END','0.2s')
        self.assertEqual(self.bridge.transcripts[0][1],'Early ending.')
    async def test_fragmented_transcript_cannot_finish_on_an_unmarked_fragment_or_exceed_bound(self):
        await self.first()
        await self.session.provider_event({'type':'input_transcript','text':'Partial','finished':False})
        with self.assertRaises(ForegroundUnavailable):
            await self.session.provider_event({'type':'input_transcript','text':'not a final signal'})
        with self.assertRaises(ForegroundUnavailable):
            await self.session.provider_event({'type':'input_transcript','text':'x'*16000,'finished':False})
        self.assertEqual(self.bridge.transcripts,[])
    async def test_next_phrase_is_retained_in_order_while_prior_transcript_is_pending(self):
        await self.first()
        await self.session.feed(b'\2\0'*1600)
        await self.session.activity(self.activity(9600,2,onset=9472))
        await self.session.feed(b'\0\0'*1600)
        await self.session.activity(self.activity(12800,2,endpoint=True))
        self.assertEqual(len(self.bridge.captures),2)
        self.assertEqual(sum(v[0]=='start' for v in self.bridge.stream.events),1)
        await self.ack('ACTIVITY_END','0.2s')
        await self.session.provider_event({'type':'input_transcript','text':'First'})
        self.assertEqual(sum(v[0]=='start' for v in self.bridge.stream.events),2)
        await self.ack('ACTIVITY_START','0.2s')
        await self.session.provider_event({'type':'input_transcript','text':'Second'})
        await self.ack('ACTIVITY_END','0.4s')
        self.assertEqual([v[1] for v in self.bridge.transcripts],['First','Second'])
        self.assertEqual(self.bridge.captures[1][1],b'\2\0'*1600+b'\0\0'*1600)
    async def test_caption_and_output_completion_do_not_finalize_a_source(self):
        await self.first()
        for kind in ('input_caption','output_transcript','generation_complete','turn_complete'):
            await self.session.provider_event({'type':kind,'text':'Not a human final'})
        self.assertEqual(self.bridge.transcripts,[])
    async def test_wrong_audio_offset_is_not_attached_to_human_source(self):
        await self.first()
        with self.assertRaises(ForegroundUnavailable):await self.ack('ACTIVITY_END','3s')
        self.assertEqual(self.bridge.transcripts,[])
    async def test_analysis_cannot_send_audio_it_has_not_observed(self):
        await self.session.feed(b'\1\0'*3200)
        await self.session.activity(self.activity(3200,onset=3072))
        self.assertEqual(self.bridge.stream.events[-1],('pcm',b'\1\0'*1600))
        with self.assertRaises(ForegroundUnavailable):
            await self.session.activity(self.activity(6402))
    async def test_close_keeps_unanalyzed_tail_and_never_delegates(self):
        await self.session.feed(b'\1\0'*3200)
        await self.session.activity(self.activity(3200,onset=3072))
        await self.session.close()
        self.assertEqual(self.bridge.captures[0][1],b'\1\0'*3200)
        self.assertEqual(self.bridge.transcripts,[]);self.assertEqual(self.session.pcm,b'')
    async def test_falling_analysis_and_activity_queue_have_bounds(self):
        self.session.max_backlog=2
        with self.assertRaises(ForegroundUnavailable):await self.session.feed(b'\0'*4)
        self.assertEqual(self.detector.frames,[])


if __name__=='__main__':unittest.main()
