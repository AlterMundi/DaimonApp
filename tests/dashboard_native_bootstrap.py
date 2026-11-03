"""Full shipped shell/bootstrap/cookie/voice owner; synthetic transport peers only."""
import argparse, asyncio, hashlib, json, os, queue, socket, struct, subprocess, sys, tempfile, threading, time, contextvars
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True
repo=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out',type=Path,required=True,help='New absolute output directory, bounded to4MiB')
parser.add_argument('--runtime',type=Path,help='Selected immutable app bundle; defaults to this checkout')
parser.add_argument('--case',choices=('baseline','paced'),default='baseline')
parser.add_argument('--activity-mode',choices=('manual','automatic'),default='manual')
parser.add_argument('--session-seconds',type=int,choices=(300,600),default=300)
args=parser.parse_args()
if args.activity_mode!='manual' and args.session_seconds!=300:parser.error('Extended fixture selects manual activity')
runtime=(args.runtime or repo).resolve();assert (runtime/'dashboard/app.py').is_file()
assert args.out.is_absolute() and not args.out.exists();args.out.mkdir(parents=True,mode=0o700)
identity_delay=.03 if args.case=='paced' else 0
sys.path[:0]=[str(runtime),str(repo/'tests')]
import uvicorn
from fastapi.responses import JSONResponse,Response
from dashboard.app import create_app
from dashboard.provider import ProviderUnavailable
from dashboard_native_voice import Owner,Stream
from dashboard.sonic import descriptor
from dashboard.home_auth import HomeAuth
from dashboard.native_voice import install as original_install
identity_path=contextvars.ContextVar('fixture_identity_path',default='unknown')
original_authenticate=HomeAuth.authenticate
def counted_authenticate(self,request):
 token=identity_path.set(request.url.path)
 try:return original_authenticate(self,request)
 finally:identity_path.reset(token)
def counted_install(app,config,provider,origins,bind_voice,detector_command,active):
 async def bind(*args):
  session,recheck,actor=await bind_voice(*args)
  async def counted_actor():
   task=asyncio.current_task();name=task.get_name() if task else 'unknown';name=name if name.startswith('native-') else 'native-input';state['actor_checks'][name]=state['actor_checks'].get(name,0)+1;return await actor()
  counted_actor.snapshot=actor.snapshot
  return session,recheck,counted_actor
 return original_install(app,config,provider,origins,bind,detector_command,active)
op=args.out;assert not (op/'intent.json').exists()
state={'state':'prepared','scope':'Full actual index/app.js/modules, standalone shared cookie/CSRF bootstrap, SSE refresh and native voice owner. Synthetic identity/provider/detector/MediaStream only; no real native/model/human/hardware capture.','bounds':'One isolated HTTPS listener/browser;<=75s browser/100s server,<=4MiB retained metadata/screenshots. Ephemeral key/profile/cache/SQLite removed after closure. No production selector/config changes or recurring attention.','source':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),'http':{},'identity_checks':0,'faults':0,'provider_opened':0,'provider_closed':0,'events':{},'actor_checks':{},'identity_paths':{},'conditions':{'session_seconds':args.session_seconds,'activity_mode':args.activity_mode,'identity_delay_ms':round(identity_delay*1000),'output_pcm_frame_ms':20 if args.case=='paced' else 1000}}
state['qualifier_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
state['browser_driver_sha256']=hashlib.sha256((repo/'tests/dashboard_native_bootstrap_browser.js').read_bytes()).hexdigest()
state['runtime_application_files']={str(p.relative_to(runtime)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (runtime/'dashboard').rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
def save():
 raw=json.dumps(state,indent=2);assert len(raw)<1024*1024;p=op/'operation.next';p.write_text(raw+'\n');p.replace(op/'operation.json')
(op/'intent.json').write_text(json.dumps(state,indent=2)+'\n');save()
class FullOwner(Owner):
 def presentation_list(self,*a):
  v=super().presentation_list(*a)
  return {**v,'schema':'telecodex.presentation-list/v1','entry_binding':[100],
          'activity':{'connected':True,'sessions':[],'observed_at':time.time()},'goal_controls':{'items':[],'more':False}}
 def conversation_inputs(self,before=0,direction='before'):
  return {'binding':self.binding,'items':[],'cursor':0,'newest':0,'more':False}
 def conversation_telegram_inputs(self,*a):return {**self.conversation_inputs(),'schema':'telecodex.telegram-input-list/v1'}
 def conversation_tasks(self,*a):return self.conversation_inputs()
 def goal_controls(self,*a):return self.conversation_inputs()
 def internal_pending(self,*a):return self.conversation_inputs()
 def sonic_activity(self):return {**descriptor({}),'configured':False,'connected':True,'sources':[]}
 def conversation_foreground_delegate(self,*a):raise AssertionError('No native work permitted in this synthetic bootstrap qualification')
class FullStream(Stream):
 def __init__(self,*a,**kw):
  super().__init__(*a,**kw);state['provider_opened']+=1;self.input_bytes=0
  self.activity_mode=kw['activity_mode'];self.speaking=False;self.quiet=0
 def append(self,pcm):
  super().append(pcm);self.input_bytes=self.total
  if self.activity_mode!='automatic':return
  # Synthetic provider boundaries on the raw timeline, not a production VAD.
  hot=max(abs(x) for x in struct.unpack('<'+'h'*(len(pcm)//2),pcm))>100
  if hot:
   self.quiet=0
   if not self.speaking:
    self.speaking=True;self.input_active=True
    self.queue.put([{'type':'voice_activity','activity':'ACTIVITY_START',
     'audio_offset':f'{(self.total-len(pcm))/32000:.9f}s','source':'provider_automatic_activity'}])
  elif self.speaking:
   self.quiet+=len(pcm)
   if self.quiet>=22400:
    self.speaking=False;self.activity_end()
 def activity_start(self):self.input_active=True;super().activity_start()
 def activity_end(self):
  self.input_active=False;self.response_pending=True
  pcm=b''.join(struct.pack('<h',int(3000*__import__('math').sin(i*2*__import__('math').pi*220/24000))) for i in range(24000))
  self.queue.put([{'type':'input_transcript','text':'Synthetic captured phrase.'},
    {'type':'voice_activity','activity':'ACTIVITY_END','audio_offset':f'{self.total/32000:.9f}s','source':'provider_manual_activity_ack' if self.activity_mode=='manual' else 'provider_automatic_activity'}])
  def produce():
   frame=960 if args.case=='paced' else len(pcm)
   for offset in range(0,len(pcm),frame):
    if self.closed:return
    self.queue.put([{'type':'audio','pcm':pcm[offset:offset+frame],'sample_rate':24000}]);time.sleep(.02 if args.case=='paced' else 0)
   if not self.closed:self.queue.put([{'type':'output_transcript','text':'Synthetic native response.'},{'type':'turn_complete'}])
  thread=threading.Thread(target=produce,daemon=True);self.producers=getattr(self,'producers',[])+[thread];thread.start()
 def receive(self):
  values=super().receive()
  if any(v['type']=='turn_complete' for v in values):self.response_pending=False
  return values
 def close(self):
  if not self.closed:state['provider_closed']+=1
  super().close()
  for thread in getattr(self,"producers",[]):thread.join(timeout=2);assert not thread.is_alive()
class FullDetector:
 @classmethod
 async def open(cls,*a,**kw):
  assert args.activity_mode=='manual','Automatic mode must not open the CPU detector'
  return cls()
 def __init__(self):self.queue=asyncio.Queue();self.total=0;self.generation=0;self.speaking=False;self.quiet=0;self.closed=False
 async def feed(self,pcm):
  self.total+=len(pcm);hot=max(abs(x) for x in struct.unpack('<'+'h'*(len(pcm)//2),pcm))>100
  value={'type':'activity','audio_bytes':self.total,'generation':self.generation,'speaking':self.speaking,'speech_seen':bool(self.generation)}
  if hot:
   self.quiet=0
   if not self.speaking:
    self.speaking=True;self.generation+=1;value['onset']={'audio_bytes':self.total,'generation':self.generation}
  elif self.speaking:
   self.quiet+=len(pcm)
   if self.quiet>=51200:
    self.speaking=False;value['endpoint']={'audio_bytes':self.total,'generation':self.generation,'authority':'acoustic_silence','silence_millis':1600}
  value.update(generation=self.generation,speaking=self.speaking);await self.queue.put(value)
 async def receive(self):return await self.queue.get()
 async def boundary(self,v):await self.queue.put({'type':'boundary',**v})
 async def close(self):self.closed=True
server=thread=node=None
try:
 with tempfile.TemporaryDirectory(prefix='ephemeral-',dir=op) as tmp:
  root=Path(tmp);owner=FullOwner(root);sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];origin=f'https://127.0.0.1:{port}';fault={'metadata':False};api_reads=[]
  config={'state_dir':str(root/'web'),'origin':origin,'prefix':'/interaction','bot_id':123,'daimon_name':'Synthetic fixture',
   'shared_auth':{'enabled':True,'home_origin':origin,'entry_path':'/interaction/'},
   'streaming_transcription':{'enabled':True,'provider':'gemini','mode':'prepared','native_dialogue':True,'native_activity_mode':args.activity_mode,'endpoint':'wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent','credential_file':str(root/'synthetic-key'),'cache_root':str(root/'prepared'),'turn_detection':{'enabled':True,'continuous':True,'command':['/synthetic/python','capture-turn']}}}
  if args.session_seconds>300:config['streaming_transcription']['native_session_seconds']=args.session_seconds
  with patch('dashboard.native_voice.install',side_effect=counted_install):app=create_app(config,owner,lambda raw,bot:int(raw))
  def identity(home,token):
   assert home==origin and token=='s'*43;state['identity_checks']+=1;name=identity_path.get();state['identity_paths'][name]=state['identity_paths'].get(name,0)+1;time.sleep(identity_delay)
   return {'contract':'dm.home-session/v1','origin':origin,'actor':{'kind':'human','ref':'human:telegram:100','name':'Synthetic operator'},'expires':int(time.time())+300}
  async def gateway(scope,receive,send):
   if scope['type'] in ('http','websocket'):
    path=scope['path']
    if path=='/access-client.js':
     await Response('window.DaimonHomeAccess={createClient(){throw Error("Unexpected sign-in in cookie fixture");}}',media_type='application/javascript')(scope,receive,send);return
    if path=='/fixture/control':
     body=await receive();v=json.loads(body.get('body',b'{}'));assert set(v)<={'fail_metadata','invalidate'}
     if v.get('fail_metadata'):fault['metadata']=True
     if v.get('invalidate'):(root/'native.sqlite3').write_bytes(b'')
     await JSONResponse({'ok':True})(scope,receive,send);return
    if not path.startswith('/interaction/'):
     await JSONResponse({'detail':'Fixture route unavailable'},status_code=404)(scope,receive,send);return
    scope={**scope,'path':path[len('/interaction'):],'raw_path':scope['raw_path'][len('/interaction'):],'root_path':''}
    if scope['type']=='http' and scope['path']=='/api/interaction' and fault['metadata']:
     fault['metadata']=False;state['faults']+=1;save();await JSONResponse({'detail':'Synthetic transient metadata read'},status_code=503)(scope,receive,send);return
   async def observed(message):
    if scope['type']=='http' and message['type']=='http.response.start':
     key=f"{scope['path']}:{message['status']}";state['http'][key]=state['http'].get(key,0)+1
    if scope['type']=='websocket' and message['type']=='websocket.send' and message.get('text'):
     kind=json.loads(message['text']).get('type');state['events'][kind]=state['events'].get(kind,0)+1
    await send(message)
   await app(scope,receive,observed)
  key=root/'tls.key';cert=root/'tls.crt';subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=8)
  server=uvicorn.Server(uvicorn.Config(gateway,host='127.0.0.1',port=port,ssl_keyfile=str(key),ssl_certfile=str(cert),log_level='warning',timeout_graceful_shutdown=5))
  with patch('dashboard.native_voice.NativeDialogue',FullStream),patch('dashboard.native_voice.Detector',FullDetector),patch('dashboard.home_auth.identity_response',side_effect=identity),patch.object(HomeAuth,'authenticate',counted_authenticate):
   thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start();deadline=time.monotonic()+10
   while not server.started:assert thread.is_alive() and time.monotonic()<deadline;time.sleep(.05)
   state['state']='full-bootstrap-browser-running';save()
   node=subprocess.Popen(['node',str(repo/'tests/dashboard_native_bootstrap_browser.js')],env={**os.environ,'FIXTURE_ORIGIN':origin,'QUALIFICATION_OUTPUT':str(op),'QUALIFICATION_SECONDS':str(args.session_seconds)},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
   out,err=node.communicate(timeout=75);(op/'browser-run.log').write_text(out+'\n'+err);assert node.returncode==0,'Inspect retained full-bootstrap browser outcome'
  server.should_exit=True;thread.join(timeout=8);assert not thread.is_alive()
  state['originals']=[{'id':v['id'],'phase':v['phase'],'audio_sha256':v['voice']['audio_sha256']} for v in owner.inputs.values()];state['history']=[{k:v[k] for k in ('id','generated_bytes','played_bytes','closed')} for v in app.state.native_history.page(100,binding=owner.binding)['items']];state['delegations']=len(owner.delegations)
  browser=json.loads((op/'browser.json').read_text());assert sorted((v['id'],v['audio_sha256']) for v in state['originals'])==sorted((v['id'],v['sha256']) for v in browser['before']['retained'])
  assert len(state['originals'])==len(state['history'])==3 and all(v['phase']=='foreground' for v in state['originals'])
  assert all(v['closed'] and v['generated_bytes']==v['played_bytes']==48000 for v in state['history'])
  assert state['provider_opened']==state['provider_closed']==1 and state['delegations']==0
  state['state']='full-bootstrap-synthetic-journey-observed';save()
finally:
 if node and node.poll() is None:node.terminate();node.wait(timeout=5)
 if server:server.should_exit=True
 if thread:thread.join(timeout=8)
 state['server_closed']=thread is None or not thread.is_alive();state['temporary_files_removed']=not any(p.is_dir() for p in op.glob('ephemeral-*'));save()

assert state["server_closed"] and state["temporary_files_removed"]
state["retained_bytes"]=sum(p.stat().st_size for p in op.rglob("*") if p.is_file());assert state["retained_bytes"]<4*1024*1024;save()
print(json.dumps({k:state[k] for k in ("state","conditions","identity_checks","provider_opened","provider_closed","retained_bytes")}))
