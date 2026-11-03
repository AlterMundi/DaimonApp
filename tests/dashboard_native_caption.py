"""Missing-caption PCM eligibility and cleanup, without providers or devices."""
import hashlib
from pathlib import Path
import sys
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.native_caption import CaptionAudio


class Audio(unittest.TestCase):
    def begin(self, capture):
        source = str(uuid.uuid4())
        capture.begin(source)
        return source

    def test_missing_caption_preserves_exact_audio_and_parent_not_a_transcript(self):
        capture = CaptionAudio(); source = self.begin(capture)
        chunks = [b'\x01\x00' * 320, b'\x02\x00' * 160]
        for chunk in chunks: capture.append(chunk)
        capture.caption('')  # Empty provider metadata does not confirm language.
        evidence, pcm = capture.finish()
        self.assertEqual(bytes(pcm), b''.join(chunks))
        self.assertEqual(evidence, {'source':source, 'state':'missing_caption',
            'generated_bytes':960, 'pcm_sha256':hashlib.sha256(bytes(pcm)).hexdigest()})
        self.assertEqual(len(capture.audio), 0)
        with self.assertRaises(ValueError): capture.begin(source)
        with self.assertRaises(ValueError): capture.finish()
        pcm.clear()  # The finite recovery caller owns retirement after transfer.

    def test_text_before_or_after_audio_releases_media_but_keeps_exact_digest(self):
        for before in (True, False):
            capture = CaptionAudio(); self.begin(capture)
            if before: capture.caption('Known output')
            capture.append(b'\x03\x00' * 64)
            if not before: capture.caption('Known output')
            self.assertEqual(len(capture.audio), 0)
            capture.append(b'\x04\x00' * 64)
            evidence, pcm = capture.finish()
            self.assertIsNone(pcm)
            self.assertEqual(evidence['state'], 'caption_present')
            self.assertEqual(evidence['generated_bytes'], 256)
            self.assertEqual(evidence['pcm_sha256'], hashlib.sha256(b'\x03\x00'*64+b'\x04\x00'*64).hexdigest())

    def test_overlong_audio_is_unrecoverable_not_a_partial_clip(self):
        capture = CaptionAudio(); capture.max_clip_bytes = 8
        self.begin(capture); capture.append(b'\x00\x00' * 4)
        self.assertEqual(len(capture.audio), 8)
        capture.append(b'\x01\x00')
        evidence, pcm = capture.finish()
        self.assertIsNone(pcm)
        self.assertEqual(evidence['state'], 'audio_exceeds_asr_limit')
        self.assertEqual(evidence['generated_bytes'], 10)

    def test_dialogue_budget_survives_utterance_retirement_and_invalid_input(self):
        capture = CaptionAudio(); capture.max_dialogue_bytes = 8
        self.begin(capture); capture.append(b'\0' * 6); capture.caption('Text'); capture.finish()
        self.begin(capture)
        for invalid in (b'', b'x', bytearray(b'xx'), b'\0' * 4):
            with self.assertRaises(ValueError): capture.append(invalid)
        self.assertEqual(capture.total_bytes, 6)
        capture.append(b'\0\0'); capture.finish()
        self.begin(capture)
        with self.assertRaises(ValueError): capture.append(b'\0\0')

    def test_close_releases_incomplete_audio_and_prevents_reuse(self):
        capture = CaptionAudio(); self.begin(capture); capture.append(b'\0\0')
        capture.close(); capture.close()
        self.assertEqual(len(capture.audio), 0)
        for operation in (lambda: capture.begin(str(uuid.uuid4())),
                          lambda: capture.append(b'\0\0'),
                          lambda: capture.caption('Late text'), capture.finish):
            with self.assertRaises(ValueError): operation()


if __name__ == '__main__': unittest.main()
