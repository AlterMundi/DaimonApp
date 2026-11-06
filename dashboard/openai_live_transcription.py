"""One source-bound OpenAI interpretation; no fallback or native work dispatch."""
import hashlib
import json
from pathlib import Path
import threading
import time

import httpx

from .codex_voice_history import history_lock
from .openai_live import OpenAILive
from .provider import ProviderUnavailable
from scripts.speech_render import private_bytes


class InterpretationUnavailable(Exception):
    def __init__(self, outcome='unconfirmed', status=None):
        self.outcome, self.status = outcome, status
        super().__init__('Original audio interpretation '+outcome)


class OriginalTranscription:
    model = 'gpt-transcribe'
    endpoint = 'https://api.openai.com/v1/audio/transcriptions'

    def __init__(self, key_file, *, transport=None):
        # Reuse the approved custody reader. Fail before an intent/billable call.
        self._key = OpenAILive(key_file)._project_key()
        self._transport = transport
        self._attempted = False
        self._guard = threading.Lock()

    def transcribe(self, data):
        from .live_transcription import wav_bytes
        if (not isinstance(data, bytes) or not 44 < len(data) <= 120*32000+44
                or (len(data)-44)%2 or wav_bytes(data[44:]) != data):
            raise ValueError('Interpret one exact bounded canonical WAV')
        with self._guard:
            if self._attempted:raise InterpretationUnavailable('already_attempted')
            self._attempted = True
        try:
            deadline=time.monotonic()+30
            with httpx.Client(transport=self._transport,follow_redirects=False,trust_env=False,
                              timeout=httpx.Timeout(20,connect=5,write=10,pool=5)) as client:
                with client.stream('POST',self.endpoint,
                        headers={'Authorization':'Bearer '+self._key},
                        data={'model':self.model},files={'file':('original.wav',data,'audio/wav')}) as response:
                    if response.status_code != 200:
                        rejected=400<=response.status_code<500 and response.status_code!=408
                        raise InterpretationUnavailable('rejected' if rejected else 'unconfirmed',response.status_code)
                    raw=bytearray()
                    for part in response.iter_bytes():
                        if time.monotonic()>deadline or len(raw)+len(part)>65536:
                            raise InterpretationUnavailable()
                        raw.extend(part)
            text=json.loads(raw).get('text')
            if not isinstance(text,str) or not text.strip() or '\0' in text or len(json.dumps(text,ensure_ascii=False).encode())>16000:
                raise InterpretationUnavailable()
            return text.strip()
        except (httpx.HTTPError,OSError,ValueError,TypeError,AttributeError):
            raise InterpretationUnavailable() from None


def interpret_original(history,ident,human,owner,ordinal,provider,recognizer=None):
    """Explicit server call only; use the existing visit receipt and quotas.

    The completed interpretation is a machine derivative of retained audio,
    never a verified human quotation or permission for another work dispatch.
    """
    if (type(ordinal) is not int or not 0<=ordinal<32
            or recognizer is not None and recognizer.model!='gpt-transcribe'):
        raise ValueError('Select one bounded OpenAI original interpretation')
    def authorize():
        if not provider.authorized(human) or provider.public_live_binding(owner['binding'])!=owner:
            raise ProviderUnavailable('Original interpretation owner changed')
    def original(value):
        receipt=next((r for r in value['recordings'] if r['ordinal']==ordinal),None)
        slot=value.get('native_originals',{}).get(str(ordinal))
        if (receipt is None or receipt.get('capture_stop') or not slot or slot['state']!='observed'
                or slot['id']!=receipt['id'] or slot['audio_sha256']!=receipt['audio_sha256']):
            raise ValueError('Reserve the complete exact native acoustic original first')
        return receipt,slot
    authorize()
    with history_lock(history.root/'.lock'):
        value=history.read(ident,human,owner);receipt,slot=original(value)
        if 'interpretation' in slot:return dict(slot['interpretation'])
        if value.get('admission',{}).get('epoch')!=history.epoch:
            raise ValueError('Restart cannot start interpretation of an old original')
    if recognizer is None:
        raise ValueError('No retained interpretation; select configured OpenAI access before a new request')
    canonical=provider.conversation_input_status(receipt['id'])
    if (canonical.get('id')!=receipt['id'] or canonical.get('entry_binding')!=owner['entry_binding']
            or canonical.get('foreground_dialogue')!=ident
            or canonical.get('phase')!='foreground_captured'
            or canonical.get('voice',{}).get('audio_sha256')!=receipt['audio_sha256']
            or canonical.get('voice',{}).get('transcription')):
        raise ValueError('Native original already interpreted or changed; no new ASR requested')
    data=private_bytes(Path(str(provider.receiver['db_path'])+'.voice')/receipt['id'],120*32000+44)
    if len(data)!=receipt['audio_bytes'] or hashlib.sha256(data).hexdigest()!=receipt['audio_sha256']:
        raise ValueError('Original changed before interpretation')
    authorize()
    with history_lock(history.root/'.lock'):
        value=history.read(ident,human,owner);receipt,slot=original(value)
        if 'interpretation' in slot:return dict(slot['interpretation'])
        if sum('interpretation' in s for s in value['native_originals'].values())>=16:
            raise ValueError('Public native interpretation attempt limit reached')
        # Reserve actual record bytes before the paid call; concurrent source
        # events cannot consume the space needed to retain its bounded result.
        slot['interpretation_reserve']=' '*20000
        slot['interpretation']={'state':'intent','model':recognizer.model,
            'capture_id':receipt['id'],'audio_sha256':receipt['audio_sha256'],'work_admitted':False,
            'meaning':'Request intent retained; completion is unconfirmed. Never retry automatically.'}
        history._write(value)
    try:
        text=recognizer.transcribe(data)
        if not isinstance(text,str) or not text.strip() or '\0' in text or len(json.dumps(text,ensure_ascii=False).encode())>16000:
            raise InterpretationUnavailable()
        result={'state':'completed','model':recognizer.model,'text':text.strip(),
                'capture_id':receipt['id'],'audio_sha256':receipt['audio_sha256'],
                'audio_millis':(len(data)-44)*1000//32000,'work_admitted':False,
                'meaning':'Machine interpretation of this exact acoustic original; not verified written human speech or work authority.'}
    except (InterpretationUnavailable,OSError,ValueError) as error:
        result={'state':getattr(error,'outcome','unconfirmed'),'model':recognizer.model,
                'capture_id':receipt['id'],'audio_sha256':receipt['audio_sha256'],'work_admitted':False}
        status=getattr(error,'status',None)
        if type(status) is int:result['status']=status
    # Preserve a paid result under its frozen original even if its viewer was
    # revoked during HTTP. Recheck before exposing or using it for native work.
    with history_lock(history.root/'.lock'):
        value=history.read(ident,human,owner);receipt,slot=original(value)
        if slot.get('interpretation',{}).get('state')!='intent':
            raise ValueError('Original interpretation intent changed')
        slot.pop('interpretation_reserve',None)
        slot['interpretation']=result;history._write(value)
    authorize()
    return dict(result)
