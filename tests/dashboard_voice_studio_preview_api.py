"""Mounted owner/CSRF/voice fence/cache/retirement, with no provider calls."""
import asyncio
import base64
import copy
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
    def test_retained_audio_is_read_only_and_actor_bound(self):
        row=self.prepare();body={**self.body(row),'action':'audio'}
        before=self.store.preview_snapshot(100)
        self.assertIsNone(self.post(body).json()['audio'])
        self.assertEqual(self.store.preview_snapshot(100),before)
        self.assertEqual(self.calls,[],'A prepared row cannot generate through audio reads')
        rendered=self.post(self.body(row)).json()
        self.assertEqual(len(self.calls),1)
        before=self.store.preview_snapshot(100)
        self.assertEqual(self.post(body).json()['audio'],rendered['audio'])
        self.assertEqual(self.store.preview_snapshot(100),before)
        for headers,code in (({},401),({'authorization':'monitor'},403),
                ({**self.headers,'authorization':'actor200'},404),({'authorization':'actor100'},403)):
            response=self.client.post(PATH,json=body,headers=headers)
            self.assertEqual(response.status_code,code,response.text)
        self.assertEqual(self.post({**body,'id':str(uuid.uuid4())}).status_code,404)
        self.assertEqual(self.post({**body,'batch_generation':row['generation']+1}).status_code,404)
        route,_,ident=self.app.state.voice_previews.plan(100,rendered['batch'],'A')
        (Path(route['cache_root'])/ident/'audio.wav').unlink()
        self.assertEqual(self.post(body).status_code,503,'Expired audio is never regenerated')
        self.assertEqual(len(self.calls),1)
        self.allowed=False
        self.assertEqual(self.post(body).status_code,403)

    def test_expired_audio_is_read_only_and_never_offered_as_playable(self):
        row=self.prepare();rendered=self.post(self.body(row)).json()
        service=self.app.state.voice_previews
        route,_,ident=service.plan(100,rendered['batch'],'A')
        job=Path(route['cache_root'])/ident;path=job/'state.json'
        state=json.loads(path.read_text());state.update(created_at=1000,last_used_at=1000)
        speech.atomic(path,speech.canonical(state))
        before=self.store.preview_snapshot(100)
        speech._prune_audio(route,now=5000)
        self.assertEqual(json.loads(path.read_text())['phase'],'audio_expired')
        self.assertFalse((job/'audio.wav').exists())
        response=self.client.get(PATH,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        shown=response.json()['batches'][0]['renders']['A']
        self.assertEqual(shown['state'],'rendered','Historical generation receipt stays intact')
        self.assertEqual(shown.get('audio_state'),'expired')
        for action in ('audio','render'):
            result=self.post({**self.body(row),'action':action})
            self.assertEqual(result.status_code,200,result.text)
            self.assertIsNone(result.json()['audio'])
            self.assertEqual(result.json()['audio_state'],'expired')
        self.assertEqual(self.store.preview_snapshot(100),before)
        self.assertEqual(len(self.calls),1,'Expiry cannot regenerate or refund a sample')
        # An altered cache receipt cannot masquerade as confirmed expiry.
        state=json.loads(path.read_text());state['audio_sha256']='0'*64
        speech.atomic(path,speech.canonical(state))
        shown=self.client.get(PATH,headers=self.headers).json()['batches'][0]['renders']['A']
        self.assertNotIn('audio_state',shown)
        self.assertEqual(self.post({**self.body(row),'action':'audio'}).status_code,503)
        self.assertEqual(self.store.preview_snapshot(100),before)
        self.assertEqual(len(self.calls),1)

    def test_expiry_between_history_and_audio_read_is_not_a_new_attempt(self):
        row=self.prepare();self.post(self.body(row));service=self.app.state.voice_previews
        route,_,ident=service.plan(100,row,'A');job=Path(route['cache_root'])/ident
        path=job/'state.json';state=json.loads(path.read_text());state.update(created_at=1000,last_used_at=1000)
        speech.atomic(path,speech.canonical(state));before=self.store.preview_snapshot(100)
        read=service.audio
        def expire_then_read(*args):
            speech._prune_audio(route,now=5000)
            return read(*args)
        with patch.object(service,'audio',side_effect=expire_then_read):
            response=self.post({**self.body(row),'action':'audio'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['audio_state'],'expired')
        self.assertIsNone(response.json()['audio'])
        self.assertEqual(self.store.preview_snapshot(100),before)
        self.assertEqual(len(self.calls),1)

    def test_retained_unknown_and_access_revocation_do_not_start_or_leak(self):
        row=self.prepare();self.mode='unknown';self.post(self.body(row))
        self.assertEqual(len(self.calls),1)
        before=self.store.preview_snapshot(100)
        body={**self.body(row),'action':'audio'}
        self.assertIsNone(self.post(body).json()['audio'])
        self.assertEqual(self.store.preview_snapshot(100),before)
        self.assertEqual(len(self.calls),1)
        service=self.app.state.voice_previews
        original=service.audio
        def revoked(*args):
            value=original(*args);self.allowed=False;return value
        with patch.object(service,'audio',side_effect=revoked):
            self.assertEqual(self.post(body).status_code,403)
        self.assertEqual(len(self.calls),1)

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
    def test_one_play_freezes_own_text_and_selected_voice_without_comparison(self):
        self.config['voice_studio']={'voices':['cedar','marin']}
        profile={**self.profile,'voice':'marin'}
        request={'action':'prepare_sample','id':str(uuid.uuid4()),'profile':profile,'delivery':'Warm.',
                 'voice_generation':0,'generation':0,'passage':'¡Hola! ¿Qué vamos a descubrir hoy?'}
        reply=self.post(request);self.assertEqual(reply.status_code,200,reply.text);row=reply.json()
        self.assertEqual(set(row['renders']),{'sample'});self.assertEqual(row['passage'],request['passage'])
        self.assertEqual(self.post(request).json(),row)
        changed={**request,'passage':'Different text'};self.assertEqual(self.post(changed).status_code,409)
        body=self.body(row,slot='sample');reply=self.post(body);self.assertEqual(reply.status_code,200,reply.text)
        self.assertEqual(reply.json()['batch']['renders']['sample']['state'],'rendered')
        self.assertEqual(self.calls[0]['text'],request['passage'])
        self.assertEqual(self.post(body).json()['audio'],reply.json()['audio']);self.assertEqual(len(self.calls),1)
        self.assertIsNone(self.store.voice_snapshot(100)['active'])
        self.assertEqual(self.post({**self.body(row,'retire'),'generation':1}).status_code,200)
    def test_custom_text_bounds_reject_before_allocation_or_worker(self):
        for text in ('','word '*41,'x'*1025,'\0',None):
            request={'action':'prepare_sample','id':str(uuid.uuid4()),'profile':self.profile,'delivery':'',
                     'voice_generation':0,'generation':0,'passage':text}
            self.assertEqual(self.post(request).status_code,400)
        self.assertEqual(self.store.preview_snapshot(100)['batches'],[]);self.assertEqual(self.calls,[])
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
    def test_unknown_preview_diagnostic_readback_never_regenerates_or_retires(self):
        row=self.prepare();service=self.app.state.voice_previews
        route,request,ident=service.plan(100,row,'A')
        self.store.preview_start(100,row['id'],row['generation'],'A')
        state={'schema':'telecodex.speech-render/v1','identity_sha256':ident,
            'phase':'unconfirmed','provider':'openai-live','voice':route['voice'],
            'language':route['language'],'text_sha256':speech.sha(request['text'].encode()),
            'provider_receipt':{'stage':'transport_released','finalized':False,
                'diagnostic':{'failure_code':'audition-provider-error','provider_error_code':'invalid_value',
                              'message':'sk-private must not be exposed'}}}
        job=speech.directory(Path(route['cache_root'])/ident)
        speech.atomic(job/'state.json',speech.canonical(state))
        result=self.post(self.body(row));self.assertEqual(result.status_code,200,result.text)
        render=result.json()['batch']['renders']['A']
        self.assertEqual(render['state'],'unconfirmed');self.assertIsNone(result.json()['audio'])
        self.assertEqual(render['outcome']['receipt']['diagnostic'],
            {'failure_code':'audition-provider-error','provider_error_code':'invalid_value'})
        self.assertNotIn('sk-private',result.text)
        self.assertEqual(self.post(self.body(row)).status_code,200)
        self.assertEqual(self.post({**self.body(row,'retire'),'generation':1}).status_code,400)
        self.assertEqual(self.calls,[]);self.assertTrue((job/'state.json').exists())
    def test_start_model_rejection_frees_only_a_known_request_without_replay(self):
        rows=[self.prepare() for _ in range(4)];service=self.app.state.voice_previews
        original_jobs=[]
        for index,row in enumerate(rows):
            route,request,ident=service.plan(100,row,'A')
            self.store.preview_start(100,row['id'],row['generation'],'A')
            state={'schema':'telecodex.speech-render/v1','identity_sha256':ident,
                'phase':'unconfirmed','provider':'openai-live','voice':route['voice'],
                'language':route['language'],'text_sha256':speech.sha(request['text'].encode()),
                'provider_receipt':{'stage':'transport_released','finalized':False,'session_id':None}}
            if index==1:state['provider_receipt']['diagnostic']={
                'failure_code':'audition-provider-error','provider_error_code':'model_not_found',
                'message':'sk-private not for the client'}
            job=speech.directory(Path(route['cache_root'])/ident)
            speech.atomic(job/'state.json',speech.canonical(state));original_jobs.append(job)
        snapshot=self.client.get(PATH,headers=self.headers);self.assertEqual(snapshot.status_code,200)
        known=snapshot.json()['batches'][1];render=known['renders']['A']
        self.assertEqual(render['state'],'rejected_before_start')
        self.assertEqual(render['outcome']['receipt']['finalization'],'not_observed')
        self.assertEqual(render['outcome']['receipt']['accounting'],'not_refunded')
        self.assertNotIn('sk-private',snapshot.text)
        self.assertIsNone(service.audio(100,known,'A'))
        unknown=self.store.preview_get(100,rows[0]['id'],rows[0]['generation'])
        self.assertEqual(self.post({**self.body(rows[0],'retire'),'generation':4}).status_code,400)
        denied=self.post({'action':'prepare','id':str(uuid.uuid4()),'profile':self.profile,
            'delivery':'Warm.','voice_generation':0,'generation':4})
        self.assertEqual(denied.status_code,400,'The four-batch bound is unchanged')
        known_route,known_request,known_id=service.plan(100,known,'A')
        state_path=original_jobs[1]/'state.json';original_state=state_path.read_bytes()
        changed=json.loads(original_state);changed['last_used_at']=123
        speech.atomic(state_path,speech.canonical(changed))
        with self.assertRaisesRegex(speech.RenderError,'uncertain-preview-is-kept'):
            speech.retire_preview_job(known_route,known_id,render['outcome'])
        self.assertTrue(state_path.exists(),'A changed proof is never cleaned up')
        speech.atomic(state_path,original_state)
        audio=original_jobs[1]/'audio.wav';speech.atomic(audio,b'Unexpected bytes')
        with self.assertRaisesRegex(speech.RenderError,'uncertain-preview-is-kept'):
            speech.retire_preview_job(known_route,known_id,render['outcome'])
        self.assertTrue(audio.exists());audio.unlink()
        # A later finalized render must not bypass an older rejection's exact
        # state hash/no-audio proof, even though normal rendered retirement works.
        self.cached(known_route,known_request)
        later_state=state_path.read_bytes();later_audio=audio.read_bytes()
        with self.assertRaisesRegex(speech.RenderError,'uncertain-preview-is-kept'):
            speech.retire_preview_job(known_route,known_id,render['outcome'])
        self.assertEqual(state_path.read_bytes(),later_state)
        self.assertEqual(audio.read_bytes(),later_audio)
        audio.unlink();speech.atomic(state_path,original_state)
        retired=self.post({**self.body(known,'retire'),'generation':4})
        self.assertEqual(retired.status_code,200,retired.text)
        self.assertFalse(original_jobs[1].exists())
        self.assertEqual(self.store.preview_get(100,rows[0]['id'],rows[0]['generation']),unknown)
        self.assertTrue((original_jobs[0]/'state.json').exists())
        self.prepare();self.assertEqual(len(self.store.preview_snapshot(100)['batches']),4)
        self.assertEqual(self.calls,[],'Reconciliation/retirement never invokes a provider')

    def test_model_diagnostic_without_exact_start_proof_stays_unknown(self):
        state={'schema':'telecodex.speech-render/v1','provider':'openai-live','phase':'unconfirmed',
            'provider_receipt':{'stage':'transport_released','finalized':False,'session_id':None,
                'diagnostic':{'failure_code':'audition-provider-error','provider_error_code':'model_not_found'}}}
        self.assertTrue(speech.preview_start_rejection(state))
        changes=[('session_id','started'),('stage','session_started'),('finalized',True)]
        for key,value in changes:
            copy_state=copy.deepcopy(state);copy_state['provider_receipt'][key]=value
            self.assertFalse(speech.preview_start_rejection(copy_state))
        for key in ('provider_error_code','failure_code'):
            copy_state=copy.deepcopy(state);del copy_state['provider_receipt']['diagnostic'][key]
            self.assertFalse(speech.preview_start_rejection(copy_state))
        copy_state=copy.deepcopy(state);copy_state['audio_sha256']='a'*64
        self.assertFalse(speech.preview_start_rejection(copy_state))

    def test_closed_failed_preview_keeps_sanitized_cause_without_audio(self):
        row=self.prepare();service=self.app.state.voice_previews;route,request,ident=service.plan(100,row,'A')
        self.store.preview_start(100,row['id'],row['generation'],'A');self.cached(route,request,cancelled=True)
        job=Path(route['cache_root'])/ident;state=json.loads((job/'state.json').read_bytes())
        state['provider_receipt']['diagnostic']={'failure_code':'audition-event-mismatch','message':'sk-private ignored'}
        speech.atomic(job/'state.json',speech.canonical(state))
        response=self.post(self.body(row));self.assertEqual(response.status_code,200,response.text)
        result=response.json();self.assertIsNone(result['audio']);render=result['batch']['renders']['A']
        self.assertEqual(render['state'],'cancelled_verified')
        self.assertEqual(render['outcome']['receipt']['diagnostic'],{'failure_code':'audition-event-mismatch'})
        self.assertNotIn('sk-private',response.text);self.assertEqual(self.calls,[])

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
