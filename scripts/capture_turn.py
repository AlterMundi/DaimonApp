"""Finite PCM activity/turn-analysis worker; never transcribes or admits input.

Silero's documented ONNX state interface is adapted from the MIT-licensed
snakers4/silero-vad repository; see docs/silero-vad-LICENSE.txt.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import resource
import signal
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.turn_end import MODEL_SHA256, SmartTurn, TurnEndUnavailable

VAD_SHA256 = '7ed98ddbad84ccac4cd0aeb3099049280713df825c610a8ed34543318f1b2c49'
VAD_BYTES = 1289603
SCHEMA = 'telecodex.turn-activity/v1'


def analysis_budget(*,continuous=False,session_seconds=None):
    """One finite worker budget; longer capture never enlarges resident state.

    Ordinary capture and omitted continuous duration keep their exact existing
    byte/analysis/CPU/wall limits. Only the native continuous owner may select
    an extended duration, and must verify the worker's ready acknowledgment.
    """
    if type(continuous) is not bool:
        raise ValueError('Select explicit continuous analysis')
    if session_seconds is not None and (not continuous or type(session_seconds) is not int
                                       or not 300<=session_seconds<=1800):
        raise ValueError('Select a continuous analysis duration from300to1800seconds')
    seconds=(300 if continuous else 120) if session_seconds is None else session_seconds
    analyses=(90*seconds+299)//300 if continuous else 30
    cpu=(seconds+1)//2 if continuous else 60
    # Preserve the default wire/runtime contract. Extended workers allow the
    # parent's30s readiness deadline plus5s cleanup beyond the selected session.
    wall=seconds+(35 if seconds>300 else 5) if continuous else 145
    return seconds,analyses,cpu,wall


class Activity:
    """One capture's recurrent state; at most120s PCM and thirty turn scores."""
    def __init__(self, vad_path, turn_path, *, continuous=False, silence_end_millis=0,session_seconds=None):
        seconds,analyses,_,_=analysis_budget(continuous=continuous,session_seconds=session_seconds)
        if type(silence_end_millis) is not int or silence_end_millis not in (0,1600):
            raise ValueError('Select disabled or native1600ms acoustic silence')
        self.silence_end_millis=silence_end_millis
        self.endpoint_generation=0
        with Path(vad_path).open('rb') as source:
            model = source.read(VAD_BYTES + 1)
        if len(model) != VAD_BYTES or hashlib.sha256(model).hexdigest() != VAD_SHA256:
            raise ValueError('Expected the pinned Silero16k ONNX model')
        import numpy as np
        import onnxruntime as ort
        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.inter_op_num_threads = options.intra_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self._session = ort.InferenceSession(model, sess_options=options, providers=['CPUExecutionProvider'])
        self._np = np
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, 64), dtype=np.float32)
        self._rate = np.array(16000, dtype=np.int64)
        self.turn = SmartTurn(turn_path)
        self.pending = bytearray()
        self.tail = bytearray()
        self.bytes = self.frames = self.generation = self.positive = self.quiet = self.analyses = 0
        self.speaking = self.speech_seen = False
        self.pending_onset = False
        self.scored_generation = self.confirmed_generation = 0
        self.max_bytes = seconds * 32000
        self.max_analyses = analyses
        self.endpoints = []

    def _probability(self, frame):
        np = self._np
        audio = np.frombuffer(frame, dtype='<i2').astype(np.float32).reshape(1, 512) / 32768
        joined = np.concatenate((self._context, audio), axis=1)
        output, self._state = self._session.run(None, {'input': joined, 'state': self._state, 'sr': self._rate})
        self._context = joined[:, -64:]
        probability = float(output.reshape(-1)[0])
        if not 0 <= probability <= 1:
            raise ValueError('Invalid speech probability')
        return probability

    def feed(self, data, *, analyze=True):
        if type(analyze) is not bool:
            raise ValueError("Analysis selection must be boolean")
        if not isinstance(data, bytes) or not data or len(data) % 2 or len(data) > 32000 or self.bytes + len(data) > self.max_bytes:
            raise ValueError('PCM chunk outside capture bounds')
        self.bytes += len(data)
        self.pending.extend(data)
        self.tail.extend(data)
        del self.tail[:-256000]
        onset = None
        while len(self.pending) >= 1024:
            frame = bytes(self.pending[:1024]);del self.pending[:1024]
            self.frames += 1
            if self._probability(frame) >= .5:
                if not self.speaking:
                    self.pending_onset = True
                self.positive += 1
                if self.speaking or self.positive >= 3:
                    self.speaking = True
                    self.quiet = 0
                else:
                    # Once speech has ended, an unconfirmed candidate cannot
                    # restart it or erase the elapsed non-speech interval.
                    self.quiet += 1
                if self.positive >= 3:
                    self.speech_seen = True
                    if self.pending_onset:
                        # A provisional noise spike cannot supersede the open
                        # confirmed phrase and disable both endpoint paths.
                        self.generation += 1
                        self.confirmed_generation = self.generation
                        self.pending_onset = False
                        onset = {'generation': self.generation, 'audio_bytes': self.frames * 1024}
            else:
                self.positive = 0
                self.quiet += 1
                if self.quiet >= 7:
                    self.speaking = False
                    self.pending_onset = False
        result = {'schema': SCHEMA, 'type': 'activity', 'generation': self.generation,
                  'speaking': self.speaking, 'speech_seen': self.speech_seen, 'audio_bytes': self.bytes}
        if onset is not None:
            result['onset'] = onset
        if analyze and self.confirmed_generation == self.generation and self.speech_seen and not self.speaking and not self.positive and self.generation != self.scored_generation:
            if self.analyses >= self.max_analyses:
                raise TurnEndUnavailable('Turn-analysis capture budget reached')
            self.scored_generation = self.generation
            self.analyses += 1
            score = self.turn.predict(bytes(self.tail), speech_present=True)
            if score['candidate_complete']:
                result['endpoint'] = {'generation': self.generation, 'audio_bytes': self.bytes,
                                      'probability': score['probability'], 'authority': 'analysis_only'}
                self.endpoints.append((self.generation, self.bytes))
                del self.endpoints[:-2]
                self.endpoint_generation=self.generation
        if (analyze and self.silence_end_millis and self.speech_seen and not self.speaking and not self.positive
                and self.confirmed_generation==self.generation
                and self.endpoint_generation!=self.generation
                and self.quiet*32>=self.silence_end_millis):
            result['endpoint']={'generation':self.generation,'audio_bytes':self.bytes,
                                'authority':'acoustic_silence','silence_millis':self.quiet*32}
            self.endpoint_generation=self.generation
            self.endpoints.append((self.generation,self.bytes));del self.endpoints[:-2]
        return result


    def boundary(self, generation, audio_bytes):
        """Retire scored history, retaining any later PCM and warm VAD state."""
        if (type(generation) is not int or type(audio_bytes) is not int
                or (generation, audio_bytes) not in self.endpoints):
            raise ValueError('Only the exact emitted endpoint can retire history')
        start = self.bytes - len(self.tail)
        del self.tail[:max(0, audio_bytes - start)]
        self.endpoints = [(g, b) for g, b in self.endpoints if b > audio_bytes]
        return {'schema': SCHEMA, 'type': 'boundary',
                'generation': generation, 'audio_bytes': audio_bytes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vad-model', type=Path, required=True)
    parser.add_argument('--turn-model', type=Path, required=True)
    parser.add_argument('--continuous', action='store_true', help='One explicit foreground session, at most five minutes')
    parser.add_argument('--session-seconds',type=int,
                        help='Continuous native analysis only: explicit finite300..1800second session')
    parser.add_argument('--silence-end-millis', type=int, choices=(0,1600), default=0,
                        help='Native speech only: close after confirmed speech and this acoustic silence')
    args = parser.parse_args()
    try:seconds,_,cpu,wall=analysis_budget(continuous=args.continuous,session_seconds=args.session_seconds)
    except ValueError as error:parser.error(str(error))
    # This owns only the optional analysis child, never native conversations.
    resource.setrlimit(resource.RLIMIT_CPU, (cpu,cpu+5))
    signal.alarm(wall)
    try:
        analyzer = Activity(args.vad_model, args.turn_model, continuous=args.continuous,silence_end_millis=args.silence_end_millis,
                            session_seconds=args.session_seconds)
        print(json.dumps({'schema': SCHEMA, 'type': 'ready', 'vad_sha256': VAD_SHA256, 'turn_sha256': MODEL_SHA256, **({'continuous': True} if args.continuous else {}),**({'silence_end_millis':args.silence_end_millis} if args.silence_end_millis else {}),**({'session_seconds':seconds} if seconds>300 else {})}), flush=True)
        while True:
            raw = sys.stdin.buffer.readline(45001)
            if not raw:
                break
            if len(raw) > 45000:
                raise ValueError('Analysis command exceeds bound')
            value = json.loads(raw)
            if args.continuous and isinstance(value, dict) and set(value) == {'boundary'}:
                boundary = value['boundary']
                if not isinstance(boundary, dict) or set(boundary) != {'generation', 'audio_bytes'}:
                    raise ValueError('Expected one exact history boundary')
                print(json.dumps(analyzer.boundary(**boundary)), flush=True)
                continue
            if (not isinstance(value, dict) or set(value) not in ({'pcm'}, {'pcm', 'defer'})
                    or not isinstance(value['pcm'], str) or type(value.get('defer', False)) is not bool):
                raise ValueError('Expected one PCM command')
            data = base64.b64decode(value['pcm'], validate=True)
            print(json.dumps(analyzer.feed(data, analyze=not value.get('defer', False))), flush=True)
    except (ValueError, OSError, TurnEndUnavailable, ImportError):
        print(json.dumps({'schema': SCHEMA, 'type': 'unavailable'}), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
