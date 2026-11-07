"""Account/CSRF-owned A/B requests; same workshop, voice fence and speech cache."""
import asyncio
import base64
import copy
import hashlib
import json
import math
from pathlib import Path

from anyio import CancelScope
from fastapi import HTTPException,Request
from scripts import speech_render as speech
from .codex_voice import AvatarVoiceLease,CodexVoiceUnavailable
from .voice_admission import admit_voice,hold_voice_task,VoiceAdmissionError
from .provider import ProviderUnavailable
from .voice_studio import configured_profiles
from .voice_studio_render import PreviewRunner,PreviewUnavailable

PATH='/api/interaction/avatars/voice/previews'


class PreviewService:
    def __init__(self,app,config,provider,store):
        self.app,self.config,self.provider,self.store=app,config,provider,store
        self.running={}

    def receiving(self):
        profiles=configured_profiles(self.config)
        capacity=getattr(self.app.state,'voice_preview_capacity',None)
        if not profiles or capacity is None:raise ValueError('Voice previews are not configured')
        binding=self.config['speech_openai']['binding'];raw=speech.private_bytes(binding,16384)
        base=speech.route(binding)
        if base['provider']!='openai-realtime':raise ValueError('Select the existing OpenAI speech cache')
        key=self.config['openai_live']['api_key_file']
        if not isinstance(key,str) or not Path(key).is_absolute():raise ValueError('Select the configured project access')
        fingerprint=speech.sha(speech.canonical([speech.sha(raw),key,profiles]))
        return base,key,profiles,capacity,fingerprint

    def available(self,human):
        if human!=getattr(self.provider,'human',None):return False
        try:self.receiving();return True
        except (OSError,ValueError,KeyError,TypeError,speech.RenderError):return False

    def plan(self,human,row,slot):
        base,key,profiles,_,fingerprint=self.receiving()
        if row.get('receiving_fingerprint')!=fingerprint:raise ValueError('Preview receiving configuration changed; the batch is kept')
        selected=row['choices'][slot]
        if selected['profile'] not in profiles:raise ValueError('This preview voice is not configured')
        route={'schema':speech.SCHEMA,'provider':'openai-live','model':selected['profile']['model'],
            'voice':selected['profile']['voice'],'language':base['language'],'credential_file':key,
            'cache_root':base['cache_root'],'timeout_seconds':30,
            'instruction':base.get('instruction','')+'\n'+selected['delivery'],
            'audio_retention_seconds':base.get('audio_retention_seconds',3600),
            'audio_cache_max_bytes':base.get('audio_cache_max_bytes',256*1024*1024)}
        scope='voice-studio:'+speech.sha(speech.canonical([human,row['id'],row['generation'],selected['sha256']]))
        request={'scope':scope,'text':row['passage']};_,_,ident=speech.render_plan(route,request)
        return route,request,ident

    def prepare(self,human,body):
        if not self.available(human):raise ValueError('Voice previews are not available for this account')
        *_,profiles,capacity,fingerprint=self.receiving()
        if body['profile'] not in profiles:raise ValueError('Voice is not configured for this account')
        def planner(row):return {slot:self.plan(human,row,slot)[2] for slot in ('A','B')}
        return self.store.preview_prepare(human,body['id'],body['profile'],body['delivery'],
            body['voice_generation'],body['generation'],planner,receiving_fingerprint=fingerprint)

    def observed(self,human,row,slot):
        route,request,ident=self.plan(human,row,slot)
        if row['renders'][slot]['id']!=ident:raise ValueError('Frozen preview render identity changed')
        job=Path(route['cache_root'])/ident;path=job/'state.json'
        if not path.exists() and not path.is_symlink():return None
        state=json.loads(speech.private_bytes(path,32768));provider=state.get('provider_receipt',{})
        if (state.get('identity_sha256')!=ident or state.get('provider')!='openai-live'
                or state.get('voice')!=route['voice'] or state.get('language')!=route['language']
                or state.get('text_sha256')!=speech.sha(request['text'].encode())):
            raise ValueError('Preview source proof changed')
        seconds=provider.get('usage',{}).get('seconds')
        finalized=provider.get('finalized') is True and provider.get('stage')=='session_closed' and provider.get('model')==route['model'] and isinstance(provider.get('session_id'),str) and type(seconds) in (int,float) and math.isfinite(seconds) and seconds>=0
        receipt={'render_id':ident,'provider_receipt':{key:copy.deepcopy(provider[key]) for key in (
            'model','session_id','usage','reason','finalized','first_pcm_millis','generation_millis',
            'audio_millis','passage_match','hearing','live_conversation_latency') if key in provider}}
        if state.get('phase')=='rendered' and finalized:
            audio=job/'audio.wav';data=speech.private_bytes(audio,speech.MAX_AUDIO);info=speech.audio_info(data)
            if speech.sha(data)!=state.get('audio_sha256') or info!=state.get('format') or info['audio_millis']>30000:
                raise ValueError('Cached preview audio changed')
            receipt.update(audio_sha256=state['audio_sha256'],format=info,voice=route['voice'],language=route['language'])
            return {'state':'rendered','receipt':receipt}
        if finalized:return {'state':'cancelled_verified','receipt':receipt}
        return None

    def reconcile(self,human,row):
        if row['phase']=='retiring':return row
        for slot in ('A','B'):
            current=row['renders'][slot]
            if current['state'] in ('intent','cancel_requested','unconfirmed'):
                outcome=self.observed(human,row,slot)
                if outcome is not None:
                    row=self.store.preview_observe(human,row['id'],row['generation'],slot,current['id'],outcome)
        return row

    def snapshot(self,human):
        state=self.store.preview_snapshot(human)
        for row in state['batches']:
            try:self.reconcile(human,row)
            except (OSError,ValueError,KeyError,TypeError,speech.RenderError):pass
        return self.store.preview_snapshot(human)

    def audio(self,human,row,slot):
        if row['renders'][slot]['state']!='rendered':return None
        route,_,ident=self.plan(human,row,slot)
        data=speech.private_bytes(Path(route['cache_root'])/ident/'audio.wav',speech.MAX_AUDIO)
        proof=row['renders'][slot]['outcome']['receipt']
        if speech.sha(data)!=proof.get('audio_sha256') or speech.audio_info(data)!=proof.get('format'):
            raise ValueError('Recorded preview needs review')
        return {'mime':'audio/wav','data':base64.b64encode(data).decode(),'playback':'not_observed'}

    def retire(self,human,body):
        def remove(row):
            seen=set()
            for slot in ('A','B'):
                route,_,ident=self.plan(human,row,slot)
                if ident in seen:continue
                seen.add(ident);render=row['renders'][slot]
                outcome=render.get('outcome',{'state':'prepared','receipt':{}})
                speech.retire_preview_job(route,ident,outcome)
        return self.store.preview_retire(human,body['id'],body['batch_generation'],body['generation'],remove)

    async def cancel(self,human,ident,generation):
        row=await asyncio.to_thread(self.store.preview_cancel,human,ident,generation)
        for key,value in list(self.running.items()):
            if key[:3]==(human,ident,generation):value.set()
        return row

    async def render(self,request,human,body,owner):
        ident,generation,slot=body['id'],body['batch_generation'],body['slot']
        row=await asyncio.to_thread(self.store.preview_get,human,ident,generation)
        if not self.available(human):raise ValueError('Voice previews are not available for this account')
        row=await asyncio.to_thread(self.reconcile,human,row)
        if row['phase']=='retiring':raise ValueError('Preview retirement needs completion')
        if row['renders'].get(slot,{}).get('state')=='rendered':
            return {'batch':row,'audio':await asyncio.to_thread(self.audio,human,row,slot)}
        if row['renders'].get(slot,{}).get('state')!='prepared':return {'batch':row,'audio':None}
        route,payload,render_id=self.plan(human,row,slot)
        if render_id!=row['renders'][slot]['id']:raise ValueError('Preview source identity changed')
        caps=await asyncio.to_thread(self.provider.presentation,'input voice capabilities')
        frozen=await asyncio.to_thread(self.provider.public_live_binding,caps.get('binding'))
        if frozen['entry_binding'][0]!=human:raise ValueError('Select this account’s own voice access')
        admit_voice(request.scope)
        lease=AvatarVoiceLease(self.app.state.voice_active,human,frozen['binding'],frozen['native_thread'])
        stop=asyncio.Event();key=(human,ident,generation,slot);worker=watcher=None
        try:
            await owner(request,True)
            row,fresh=await asyncio.to_thread(self.store.preview_start,human,ident,generation,slot)
            if not fresh:return {'batch':row,'audio':None}
            self.running[key]=stop
            if (await asyncio.to_thread(self.store.preview_get,human,ident,generation))['renders'][slot]['state']=='cancel_requested':stop.set()
            capacity=self.receiving()[3]
            worker=asyncio.create_task(PreviewRunner(capacity).run(route,payload,stop));hold_voice_task(request.scope,worker)
            async def disconnected():
                while not worker.done():
                    if await request.is_disconnected():stop.set();return
                    await asyncio.sleep(.1)
            watcher=asyncio.create_task(disconnected())
            try:await asyncio.shield(worker)
            except PreviewUnavailable as error:
                if not error.attempted:
                    row=await asyncio.to_thread(self.store.preview_observe,human,ident,generation,slot,render_id,
                        {'state':'not_started','receipt':{'provider_attempted':False,'reason':str(error)}})
            except (OSError,ValueError,KeyError,TypeError,speech.RenderError):pass
            row=await asyncio.to_thread(self.reconcile,human,row)
            if row['renders'][slot]['state'] in ('intent','cancel_requested'):
                row=await asyncio.to_thread(self.store.preview_observe,human,ident,generation,slot,render_id,
                    {'state':'unconfirmed','receipt':{'automatic_retry':False}})
            await owner(request,True)
            audio=await asyncio.to_thread(self.audio,human,row,slot) if row['renders'][slot]['state']=='rendered' else None
            return {'batch':row,'audio':audio}
        finally:
            with CancelScope(shield=True):
                stop.set()
                if worker is not None:
                    try:await asyncio.wait_for(asyncio.shield(worker),7)
                    except BaseException:
                        if not worker.done():worker.cancel()
                        try:await worker
                        except BaseException:pass
                if watcher is not None:
                    watcher.cancel()
                    try:await watcher
                    except BaseException:pass
                self.running.pop(key,None);lease.release()


def install(app,config,provider,store,owner,call):
    service=PreviewService(app,config,provider,store);app.state.voice_previews=service
    @app.get(PATH)
    async def previews(request:Request):return await call(request,service.snapshot)
    @app.post(PATH)
    async def preview_action(request:Request):
        human=await owner(request,True);raw=bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw)>8192:raise HTTPException(413,'Preview action exceeds 8KiB')
        try:body=json.loads(raw)
        except ValueError:raise HTTPException(400,'Select one preview action') from None
        if not isinstance(body,dict):raise HTTPException(400,'Select one preview action')
        action=body.get('action')
        try:
            if action=='prepare' and set(body)=={'action','id','profile','delivery','voice_generation','generation'}:
                return await call(request,service.prepare,body,write=True)
            if action in ('render','cancel') and set(body)==({'action','id','batch_generation','slot'} if action=='render' else {'action','id','batch_generation'}):
                if action=='render' and body['slot'] not in ('A','B'):raise ValueError('Select preview A or B')
                if action=='cancel':value=await service.cancel(human,body['id'],body['batch_generation'])
                else:value=await service.render(request,human,body,owner)
                await owner(request,True);return value
            if action=='retire' and set(body)=={'action','id','batch_generation','generation'}:
                return await call(request,service.retire,body,write=True)
        except (VoiceAdmissionError,CodexVoiceUnavailable) as error:raise HTTPException(409,str(error)) from None
        except KeyError:raise HTTPException(404,'Preview unavailable for this account') from None
        except (ValueError,TypeError) as error:raise HTTPException(400,str(error)) from None
        except (OSError,speech.RenderError,ProviderUnavailable):raise HTTPException(503,'Preview needs review; no automatic retry') from None
        raise HTTPException(400,'Select Prepare, Generate, Stop or Retire preview')
    return service
