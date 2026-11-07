"""Mounted owner/CSRF/voice fence/cache/retirement, with no provider calls."""
import asyncio
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import uuid
import wave
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from dashboard.avatar_workshop_api import install
from dashboard.voice_studio_preview_api import PATH
from dashboard.voice_studio_render import PreviewUnavailable
from dashboard.provider import ProviderUnavailable
from dashboard.voice_admission import VoiceAdmission,VoiceAdmissionMiddleware,maintenance_guard
from scripts import speech_render as speech


class Mounted(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.key=self.root/'key';self.key.write_text('sk-synthetic-not-used');self.key.chmod(0o600)
        self.binding=self.root/'speech.json';self.binding.write_text(json.dumps({'schema':speech.SCHEMA,
            'provider':'openai-realtime','model':'gpt-realtime-2.1-mini','voice':'cedar','language':'es-AR',
            'cache_root':str(self.root/'cache'),'credential_file':str(self.key)}));self.binding.chmod(0o600)
        self.config={'state_dir':str(self.root/'state'),'speech_openai':{'binding':str(self.binding)},
            'openai_live':{'enabled':True,'api_key_file':str(self.key),'session_options':{'audio':{'output':{'voice':'cedar'}}}}}
        test=self
        class Owner:
            human=100
            def authorized(self,human):return human in (100,200) and test.allowed
            def presentation(self,*args):return {'binding':'a'*64}
            def public_live_binding(self,binding):return {'binding':binding,'native_thread':'synthetic-thread',
                'entry_binding':[100,{'chat_id':100,'thread_id':1},1,'synthetic-thread']}
        async def owner(request):
            actor=request.headers.get('authorization')
            if actor not in ('actor100','actor200','monitor'):raise HTTPException(401,'Synthetic sign in required')
            return {'human':200 if actor=='actor200' else 100,'csrf':'fresh',
                'scope':'monitor_readonly' if actor=='monitor' else 'interaction_only'}
        self.allowed=True;self.app=FastAPI();self.app.state.voice_active=set();self.app.state.voice_preview_capacity=asyncio.Semaphore(2)
        self.app.add_middleware(VoiceAdmissionMiddleware,admission=VoiceAdmission(self.config['state_dir']))
        self.store=install(self.app,self.config,Owner(),owner,['https://example.test'])
        self.client=TestClient(self.app,base_url='https://example.test');self.addCleanup(self.client.close)
        self.headers={'authorization':'actor100','origin':'https://example.test','x-dashboard-csrf':'fresh'}
        self.profile={'provider':'openai','api':'gpt-live','model':'gpt-live-1','voice':'cedar'}
        self.calls=[];self.mode='rendered';self.started=threading.Event()
        async def run(runner,route,request,stop):
            self.calls.append(request);self.started.set()
            if self.mode=='unknown':raise PreviewUnavailable('Synthetic unknown attempt')
            if self.mode=='wait':await stop.wait()
            result=self.cached(route,request,cancelled=self.mode=='wait')
            if self.mode=='wait':raise PreviewUnavailable('Synthetic cancellation')
            if self.mode=='lost':raise PreviewUnavailable('Synthetic lost process response')
            return result
        patched=patch('dashboard.voice_studio_preview_api.PreviewRunner.run',new=run);patched.start();self.addCleanup(patched.stop)
    def cached(self,route,request,*,cancelled=False):
        config,_,ident=speech.render_plan(route,request);job=speech.directory(speech.directory(config['cache_root'])/ident)
        output=io.BytesIO()
        with wave.open(output,'wb') as wav:wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(b'\1\0'*2400)
        data=output.getvalue();state={'schema':'telecodex.speech-render/v1','identity_sha256':ident,
            'provider':'openai-live','voice':route['voice'],'language':route['language'],'text_sha256':speech.sha(request['text'].encode()),
            'phase':'unconfirmed' if cancelled else 'rendered','provider_receipt':{'stage':'session_closed','model':'gpt-live-1',
                'session_id':'synthetic-session','usage':{'seconds':2},'finalized':True,'hearing':'not_observed','passage_match':True}}
        if not cancelled:
            speech.atomic(job/'audio.wav',data);state.update(audio_sha256=speech.sha(data),format=speech.audio_info(data),audio_bytes=len(data))
        speech.atomic(job/'state.json',speech.canonical(state))
        return (data,speech.result(state,job/'audio.wav',False)) if not cancelled else (None,None)
    def post(self,body,headers=None):return self.client.post(PATH,json=body,headers=headers or self.headers)
    def prepare(self):
        response=self.post({'action':'prepare','id':str(uuid.uuid4()),'profile':self.profile,'delivery':'Warm.',
            'voice_generation':0,'generation':self.store.preview_snapshot(100)['generation']})
        self.assertEqual(response.status_code,200,response.text);return response.json()
    def body(self,row,action='render',slot='A'):
        return {'action':action,'id':row['id'],'batch_generation':row['generation'],**({'slot':slot} if action=='render' else {})}
    def test_exact_source_cache_once_actor_csrf_and_known_retirement(self):
        row=self.prepare();body=self.body(row)
        self.assertEqual(self.post(body,{'authorization':'actor100'}).status_code,403)
        self.assertEqual(self.post(body,{**self.headers,'authorization':'actor200'}).status_code,404)
        first=self.post(body);self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(base64.b64decode(first.json()['audio']['data'])[:4],b'RIFF')
        self.assertEqual(len(self.calls),1);self.assertEqual(self.post(body).json()['audio'],first.json()['audio'])
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.client.get(PATH,headers={'authorization':'monitor'}).status_code,403)
        self.assertEqual(self.store.preview_snapshot(200)['batches'],[])
        self.assertIsNone(self.store.snapshot(100)['active']);self.assertIsNone(self.store.voice_snapshot(100)['active'])
        retired=self.post({**self.body(row,'retire'),'generation':1})
        self.assertEqual(retired.status_code,200,retired.text);self.assertEqual(retired.json()['batches'],[])
        self.assertEqual(self.post(body).status_code,404);self.assertEqual(len(self.calls),1)
    def test_maintenance_and_active_capture_refuse_before_attempt(self):
        row=self.prepare()
        with maintenance_guard(self.config['state_dir']):self.assertEqual(self.post(self.body(row)).status_code,409)
        self.app.state.voice_active.add(100)
        self.assertEqual(self.post(self.body(row)).status_code,409)
        self.app.state.voice_active.clear()
        self.assertEqual(self.store.preview_get(100,row['id'],row['generation'])['renders']['A']['state'],'prepared')
        self.assertEqual(self.calls,[])
    def test_unknown_and_lost_response_observe_without_provider_replay(self):
        row=self.prepare();self.mode='unknown';first=self.post(self.body(row))
        self.assertEqual(first.status_code,200,first.text);self.assertEqual(first.json()['batch']['renders']['A']['state'],'unconfirmed')
        self.assertEqual(self.post(self.body(row)).json()['audio'],None);self.assertEqual(len(self.calls),1)
        self.assertEqual(self.post({**self.body(row,'retire'),'generation':1}).status_code,400)
        self.mode='lost';second=self.prepare();result=self.post(self.body(second))
        self.assertEqual(result.status_code,200,result.text);self.assertIsNotNone(result.json()['audio'])
        self.assertEqual(len(self.calls),2);self.post(self.body(second));self.assertEqual(len(self.calls),2)
    def test_config_change_keeps_unattempted_batch_and_no_reroute(self):
        row=self.prepare();value=json.loads(self.binding.read_text());value['audio_retention_seconds']=600
        self.binding.write_text(json.dumps(value))
        self.assertEqual(self.post(self.body(row)).status_code,400)
        self.assertEqual(self.store.preview_get(100,row['id'],row['generation'])['renders']['A']['state'],'prepared')
        self.assertEqual(self.calls,[])
    def test_native_binding_unavailable_keeps_prepared_attempt(self):
        row=self.prepare()
        with patch.object(self.app.state.voice_previews.provider,'presentation',side_effect=ProviderUnavailable('Synthetic unavailable')):
            response=self.post(self.body(row))
        self.assertEqual(response.status_code,503,response.text)
        self.assertEqual(self.store.preview_get(100,row['id'],row['generation'])['renders']['A']['state'],'prepared')
        self.assertEqual(self.calls,[]);self.assertFalse(self.app.state.voice_active)
    def test_cancel_only_owned_attempt_and_retire_after_confirmed_close(self):
        row=self.prepare();self.mode='wait';results=[]
        thread=threading.Thread(target=lambda:results.append(self.post(self.body(row))),daemon=True);thread.start()
        self.assertTrue(self.started.wait(3));cancel=self.post(self.body(row,'cancel'))
        self.assertEqual(cancel.status_code,200,cancel.text);thread.join(timeout=3);self.assertFalse(thread.is_alive())
        self.assertEqual(results[0].status_code,200,results[0].text)
        final=self.store.preview_get(100,row['id'],row['generation'])
        self.assertEqual(final['renders']['A']['state'],'cancelled_verified');self.assertEqual(final['renders']['B']['state'],'not_started')
        self.assertFalse(self.app.state.voice_active)
        retired=self.post({**self.body(row,'retire'),'generation':1});self.assertEqual(retired.status_code,200,retired.text)
        self.assertEqual(len(self.calls),1)

if __name__=='__main__':unittest.main()
