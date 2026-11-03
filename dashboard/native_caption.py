"""Transient generated PCM for future missing-caption recovery.

This owns no provider, task, file, ingress or retry. The voice owner must finish
the derived-caption/outbox lifecycle before enabling it in native_voice.
"""
import hashlib
import uuid


class CaptionAudio:
    # Same logical output allowance as native voice; one recoverable clip also
    # fits the existing file-ASR adapter's120-second duration limit.
    max_dialogue_bytes = 300 * 48000
    max_clip_bytes = 120 * 48000
    max_utterances = 4096

    def __init__(self):
        self.total_bytes = 0
        self.sources = set()
        self.source = None
        self.audio = bytearray()
        self.digest = None
        self.generated_bytes = 0
        self.caption_present = False
        self.oversized = False
        self.closed = False

    def begin(self, source):
        if (self.closed or self.source is not None or not isinstance(source, str)
                or str(uuid.UUID(source)) != source or source in self.sources
                or len(self.sources) >= self.max_utterances):
            raise ValueError('Select one new bounded assistant utterance')
        self.sources.add(source)
        self.source = source
        self.digest = hashlib.sha256()

    def append(self, pcm):
        if (self.closed or self.source is None or not isinstance(pcm, bytes)
                or not pcm or len(pcm) % 2
                or self.total_bytes + len(pcm) > self.max_dialogue_bytes):
            raise ValueError('Provide bounded generated PCM for the open utterance')
        self.total_bytes += len(pcm)
        self.generated_bytes += len(pcm)
        self.digest.update(pcm)
        if self.generated_bytes > self.max_clip_bytes:
            self.oversized = True
            self.audio.clear()  # Never return a silently truncated ASR clip.
        elif not self.caption_present:
            self.audio.extend(pcm)

    def caption(self, text):
        if self.closed or self.source is None or not isinstance(text, str) or '\0' in text:
            raise ValueError('Select output text for the open assistant utterance')
        if text:
            self.caption_present = True
            self.audio.clear()

    def finish(self):
        if self.closed or self.source is None:
            raise ValueError('Finish one open assistant utterance')
        state = ('caption_present' if self.caption_present else
                 'audio_exceeds_asr_limit' if self.oversized else
                 'missing_caption' if self.generated_bytes else 'no_audio')
        evidence = {'source': self.source, 'pcm_sha256': self.digest.hexdigest(),
                    'generated_bytes': self.generated_bytes, 'state': state}
        # Transfer ownership without another complete PCM copy. The caller must
        # consume or clear this buffer; it has no durable retention receipt.
        pcm = self.audio if state == 'missing_caption' else None
        self.audio = bytearray()
        self.source = self.digest = None
        self.generated_bytes = 0
        self.caption_present = self.oversized = False
        return evidence, pcm

    def close(self):
        self.audio.clear()
        self.source = self.digest = None
        self.closed = True

