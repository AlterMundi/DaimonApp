"""Real iframe/canonical shell/modules with synthetic IO, no real media/providers."""
import argparse,json,re,threading,mimetypes,uuid
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from playwright.sync_api import sync_playwright
parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
web=Path(__file__).resolve().parents[1]/'dashboard/web';binding='b'*64;actor='human:fixture:one';posts=[]
draft={'revision':0,'text':''};draft_lock=threading.Lock()
class Child(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_GET(self):
  if self.path.split('?',1)[0]=='/':
   s=(web/'index.html').read_text();s=re.sub(r'\s*<script src="(?:https://telegram.org[^"\n]*|assets/app.js)" defer></script>','',s)
   if 'surface=holodeck' in self.path:s=s.replace('<html lang="en">','<html lang="en" data-surface-parent="'+parent_origin+'" data-surface-visit="'+visit+'">')
   s=s.replace('<body>','<body class="conversation-mode standalone-conversation conversation-surface">').replace('<section id="conversation" hidden','<section id="conversation"')
   data=s.encode();mime='text/html'
  elif self.path.startswith('/assets/'):
   p=web/self.path.split('?',1)[0].removeprefix('/assets/');data=p.read_bytes();mime=mimetypes.guess_type(p)[0] or 'application/octet-stream'
  elif self.path=='/fixture-draft':
   with draft_lock:data=json.dumps(draft).encode()
   mime='application/json'
  else:self.send_error(404);return
  self.send_response(200);self.send_header('Content-Type',mime);self.end_headers();self.wfile.write(data)
 def do_POST(self):
  body=self.rfile.read(int(self.headers['Content-Length']));result={}
  if self.path.endswith('/files'):
   from urllib.parse import unquote
   result=json.loads(unquote(self.headers['X-File-Reference']))
  elif self.path=='/fixture-draft':
   incoming=json.loads(body)
   with draft_lock:
    if incoming['revision']==draft['revision']:
     draft.update(revision=draft['revision']+1,text=incoming['text'])
    result=dict(draft)
  elif '/voice' in self.path:
   from urllib.parse import unquote
   result={'id':self.headers['X-Input-Id'],'binding':binding,'phase':'accepted','voice':{'audio_sha256':self.headers['X-Audio-Sha256']},'files':json.loads(unquote(self.headers.get('X-File-References','[]')))};posts.append(result)
  else:self.send_error(404);return
  data=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data)
class Parent(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_GET(self):
  data=('''<!doctype html><style>body{margin:0}iframe{width:100%;height:700px;border:0}</style><iframe allow="microphone" src="'''+child_origin+'''/?view=conversation&client=standalone&surface=holodeck"></iframe><script>
  window.messages=[];addEventListener('message',e=>{const f=document.querySelector('iframe');if(e.source!==f.contentWindow||e.origin!=='''+json.dumps(child_origin)+''')return;const d=e.data;messages.push(d);if(d.type==='ready')f.contentWindow.postMessage({...d,type:'connect'},e.origin);if(d.type==='prepare')f.contentWindow.postMessage({...d,type:'prepared',file:{file_id:crypto.randomUUID(),sha256:'a'.repeat(64),name:'holodeck-situation.json',mime:'application/json',size:64}},e.origin);});</script>''').encode()
  self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(data)
child=ThreadingHTTPServer(('127.0.0.1',0),Child);parent=ThreadingHTTPServer(('127.0.0.1',0),Parent)
child_origin='http://127.0.0.1:'+str(child.server_port);parent_origin='http://127.0.0.1:'+str(parent.server_port)
visit=str(uuid.uuid4());results=[]
for server in (child,parent):threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with sync_playwright() as pw:
  browser=pw.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
  try:
   for width in (1280,375):
    page=browser.new_page(viewport={'width':width,'height':800});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(parent_origin);frame=page.frames[1];frame.wait_for_function('!!window.Conversation')
    mount='''()=>{
      window.fixtureInputs=[];window.mediaRequests=0;const originalFetch=window.fetch;window.fetch=(route,opts)=>{if(String(route).endsWith('/files'))parent.postMessage({fixture:'file-start'},document.documentElement.dataset.surfaceParent);return originalFetch(route,opts);};
      window.AudioContext=class{resume(){return Promise.resolve()}close(){return Promise.resolve()}};
      window.MediaRecorder=class extends EventTarget{static isTypeSupported(){return true}constructor(){super();this.state='inactive';this.mimeType='audio/webm'}start(){this.state='recording'}stop(){if(this.state==='inactive')return;this.state='inactive';queueMicrotask(()=>{this.dispatchEvent(Object.assign(new Event('dataavailable'),{data:new Blob(['synthetic original audio'])}));this.dispatchEvent(new Event('stop'));})}};
      Object.defineProperty(navigator,'mediaDevices',{value:{getUserMedia:async()=>{mediaRequests++;return{getTracks:()=>[{stop(){}}]}}}});
      const draftRead=async body=>await (await originalFetch('/fixture-draft',body?{method:'POST',body:JSON.stringify(body)}:undefined)).json();
      const entry_binding=[100,{chat_id:100,thread_id:3},28,'native-fixture'];
      const api=async(route,body)=>{
        if(route==='interaction/draft')return draftRead(body);
        if(route==='interaction/inputs'&&body){
          const {binding,...original}=body;
          const receipt={...original,entry_binding,phase:'accepted'};
          fixtureInputs.push(receipt);
          if(window.fixtureLoseAck)throw Error('Controlled lost acknowledgement');
          return receipt;
        }
        if(route.startsWith('interaction/inputs?'))return{binding:'b'.repeat(64),entry_binding,csrf:'fixture',more:false,
          items:fixtureInputs.map(({entry_binding,...receipt},index)=>({...receipt,sequence:index+1,native_binding_current:true})),
          ...(route.includes('draft=text')?{conversation_draft:{...await draftRead(),owner:'a'.repeat(64)}}:{})};
        return{binding:'b'.repeat(64),csrf:'fixture',items:[],newest:{delivery:0,native:0},more:false,can_speak:true,can_download_files:true,goal_controls:[]};
      };
      window.fixtureUI=Conversation.mount({api,headers:()=>({'X-Dashboard-CSRF':'fixture'}),setCsrf(){},modeChanged(){},standalone:true});fixtureUI.identity('human:fixture:one');fixtureUI.authenticated();return fixtureUI.refresh();
    }'''
    with draft_lock:draft.update(revision=draft['revision']+1,text='')
    frame.evaluate(mount)
    field=frame.locator('#conversation-message')
    # Reload the world before the debounce timer can write to the server.
    page.route('**/fixture-draft',lambda route:route.abort() if route.request.method=='POST' else route.continue_())
    frame.locator('#conversation-message').fill('Draft before reload ñ 🧭')
    page.reload();page.unroute('**/fixture-draft')
    frame=page.frames[1];frame.wait_for_function('!!window.Conversation')
    with page.expect_response(lambda response:response.url.endswith('/fixture-draft') and response.request.method=='POST',timeout=5000) as synced:
     frame.evaluate(mount)
     field=frame.locator('#conversation-message');assert field.input_value()=='Draft before reload ñ 🧭'
     assert frame.evaluate('fixtureInputs.length')==0
    assert synced.value.json()['text']=='Draft before reload ñ 🧭'
    other=browser.new_page(viewport={'width':width,'height':800});other.goto(child_origin+'/?view=conversation&client=standalone')
    other.wait_for_function('!!window.Conversation');other.evaluate(mount)
    assert other.locator('#conversation-message').input_value()=='Draft before reload ñ 🧭'
    assert other.evaluate('fixtureInputs.length')==0
    page.route('**/fixture-draft',lambda route:route.abort() if route.request.method=='POST' else route.continue_())
    field.fill('First client edits')
    with other.expect_response(lambda response:response.url.endswith('/fixture-draft') and response.request.method=='POST',timeout=5000) as changed:
     other.locator('#conversation-message').fill('Other client edits')
    assert changed.value.json()['text']=='Other client edits'
    frame.evaluate('fixtureUI.refresh(true)')
    frame.get_by_text('Another device changed this draft.').wait_for()
    assert field.input_value()=='First client edits'
    frame.get_by_role('button',name='Use other draft').click()
    assert field.input_value()=='Other client edits'
    page.unroute('**/fixture-draft')
    other.close()
    page.wait_for_function("messages.some(m=>m.type==='ready')",timeout=5000)
    frame.locator('#conversation-files').set_input_files({'name':'fixture.txt','mimeType':'text/plain','buffer':b'synthetic attached original'});frame.wait_for_function("document.querySelector('#conversation-files-state').textContent.includes('selected')");frame.locator('#conversation-message').fill('Exact fixture human words');frame.locator('#conversation-compose').evaluate('(form)=>form.requestSubmit()')
    frame.wait_for_function('fixtureInputs.length===1')
    original=frame.evaluate('fixtureInputs[0]');assert original['text']=='Exact fixture human words' and len(original['files'])==2 and original['files'][0]['name']=='fixture.txt'
    assert page.evaluate("messages.filter(m=>m.type==='prepare')[0].id")==original['id']
    assert page.evaluate("messages.findIndex(m=>m.type==='prepare')<messages.findIndex(m=>m.fixture==='file-start')"),'Context must precede the canonical text attachment upload'
    frame.wait_for_function("document.querySelector('#conversation-message').value==='' && !document.querySelector('#conversation-send').disabled")
    assert not frame.get_by_text('This message may already have been sent.').is_visible()
    frame.evaluate('window.fixtureLoseAck=true')
    field.fill('Kept while acknowledgement is missing');frame.locator('#conversation-compose').evaluate('(form)=>form.requestSubmit()')
    frame.get_by_text('This message may already have been sent.').wait_for()
    assert field.input_value()=='Kept while acknowledgement is missing'
    frame.evaluate('fixtureUI.refresh(true)')
    frame.wait_for_function("document.querySelector('#conversation-message').value==='' && !document.querySelector('#conversation-send').disabled")
    assert frame.evaluate('fixtureInputs.length')==2
    assert not frame.get_by_text('This message may already have been sent.').is_visible()
    prior_messages=page.evaluate('messages.length');frame.locator('#conversation-files').set_input_files({'name':'voice-notes.txt','mimeType':'text/plain','buffer':b'synthetic voice attachment'});frame.wait_for_function("document.querySelector('#conversation-files-state').textContent.includes('selected')");frame.locator('#conversation-talk').click();frame.wait_for_function('mediaRequests===1')
    frame.locator('#conversation-send').click();page.wait_for_function("messages.some(m=>m.type==='status'&&m.phase==='accepted'&&m.id===messages.filter(p=>p.type==='prepare').at(-1).id)",timeout=5000)
    assert posts and posts[-1]['files'][-1]['name']=='holodeck-situation.json'
    assert page.evaluate("messages.filter(m=>m.type==='prepare').at(-1).id")==posts[-1]['id']
    assert page.evaluate("n=>{const part=messages.slice(n);return part.findIndex(m=>m.type==='prepare')<part.findIndex(m=>m.fixture==='file-start');}",prior_messages),'Context must precede the canonical audio attachment upload'
    geometry=frame.locator('#conversation-compose').bounding_box();assert geometry['width']<=width and geometry['y']+geometry['height']<=701,geometry
    assert not errors,errors
    assert page.evaluate("!JSON.stringify(messages).includes('Draft before reload')")
    results.append({'width':width,'text_original_id':original['id'],'synthetic_audio_original_id':posts[-1]['id'],'composer_visible':True,'draft_reloaded_and_synced':True,'private_payload_to_parent':False});page.close()
  finally:browser.close()
finally:
 for server in (child,parent):server.shutdown();server.server_close()
args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps({'scope':'Synthetic controlled IO in real cross-origin iframe; no physical capture/auth/hearing acceptance','cases':results},indent=2));print(json.dumps({'passed':len(results)}))
