/* Shipped shell/assets in Chromium with synthetic API fixtures only.
 * Output <=4MiB, one temporary HTTP server/browser, no provider/native calls. */
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const output=process.env.QUALIFICATION_OUTPUT;assert(output&&path.isAbsolute(output)&&!fs.existsSync(output));fs.mkdirSync(output,{mode:0o700});
const codexCase=process.env.QUALIFICATION_CODEX==='1';let uploadFailed=false;const voiceUploads=[];
const publicRoot=path.resolve('dashboard/web'),binding='a'.repeat(64),revision='b'.repeat(64),posts=[],errors=[],sockets=new Set();
const ref=n=>({source:`session:${n}`,revision});
const sessions=[{id:'1'.repeat(24),title:'Materials · Results ready for a closer look',audio_key:'100:7',destination:ref(7),latest_reply:{...ref(7),source:'session:7/42'},fresh:true,execution:'idle',goal_state:'absent',result_available:true},
{id:'2'.repeat(24),title:'Garden · Waiting for your choice',audio_key:'100:8',destination:ref(8),latest_reply:{...ref(8),source:'session:8/43'},fresh:true,human_action_pending:true,execution:'working',goal_state:'blocked'},
{id:'3'.repeat(24),title:'Conversation',audio_key:'100:1',destination:null,is_entry:true,fresh:true,execution:'working',goal_state:'active'}];
for(const row of sessions)row.last_activity_at=Date.now()/1000;
sessions.push({id:'4'.repeat(24),title:'Old inactive session',last_activity_at:Date.now()/1000-172800,fresh:false,execution:'idle',goal_state:'absent'});
const originals=[];let seen=0,workspaceAllowed=true;
const sources=Array.from({length:30},(_,i)=>({id:`native:${i+1}`,kind:'integrator_answer',revision,preview:`A small observation ${i+1}. `+'A retained synthetic conversation gives this reading area enough room to scroll naturally. '.repeat(8),observed_at:new Date(1704067200000+i*1000).toISOString()}));
sources[29]={...sources[29],kind:'worker_result',label:'Materials',target:{chat_id:100,thread_id:7},preview:'A synthetic worker result for the shared title controls.',current:true,native_binding_current:true,completed:true};
const base=()=>({binding,csrf:'fixture-csrf',items:[],cursor:0,newest:0,more:false});
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://fixture.invalid');
 const json=(v,status=200)=>{res.writeHead(status,{'content-type':'application/json','cache-control':'no-store'});res.end(JSON.stringify(v));};
 try{
 if(url.pathname.startsWith('/api/')){
  const route=url.pathname.slice(5);
  if(route==='interaction/voice/codex/visits')return json({visits:[],more:false});
  if(route.startsWith('interaction/voice/codex/visits/')&&req.method==='POST'){
   const chunks=[];for await(const chunk of req)chunks.push(chunk);const raw=Buffer.concat(chunks);
   const parts=route.split('/'),visit=parts[4],ordinal=Number(parts[6]);
   voiceUploads.push({visit,ordinal,bytes:raw.length,sha:require('node:crypto').createHash('sha256').update(raw).digest('hex')});
   if(!uploadFailed){uploadFailed=true;return json({detail:'Synthetic first receipt unavailable'},503);}
   return json({visit,binding,recording:{ordinal,audio_sha256:voiceUploads.at(-1).sha,audio_bytes:raw.length,native_replay:'never'}});
  }
  if(route==='interaction/access')return json({csrf:'fixture-csrf',label:'Synthetic operator'});
  if(route==='interaction/sessions')return workspaceAllowed?json({schema:'daimon.session-workspace/v1',sessions}):json({detail:'Workspace grant revoked'},403);
  if(route.startsWith('interaction/sessions/')){
   const technical=url.searchParams.get('technical')==='true',after=url.searchParams.has('after');
   return json({schema:'daimon.session-view/v1',revision:'c'.repeat(64),before:50,after:250,has_earlier:false,more:false,
    items:after?[]:[{id:'message',kind:'message',role:'user',text:'Show me what we discovered.',position:50,next_position:100},
     {id:'response',kind:'message',role:'assistant',text:'The first prototype is ready. Let us look together.',position:100,next_position:150},
     ...(technical?[{id:'tool',kind:'tool_call',name:'inspect_result',text:'{"result":"prototype"}',position:150,next_position:200},
      {id:'summary',kind:'reasoning_summary',role:'assistant',text:'Compare the measured result with our original question.',position:200,next_position:250}]:[])]});
  }
  if(route==='interaction/inputs'&&req.method==='POST'){
   let raw='';for await(const block of req)raw+=block;const body=JSON.parse(raw);posts.push(body);
   const value={...body,phase:body.reply?'routed':'accepted',sequence:++seen,received_at:new Date().toISOString(),...(body.reply?{routing:{phase:'accepted',label:'Materials',target:{thread_id:7},instruction:'fixture-instruction'}}:{})};originals.push(value);return json(value);
  }
  if(route==='interaction/inputs')return json({...base(),items:originals,cursor:seen,newest:seen});
  if(route==='interaction')return json({...base(),items:sources,cursor:{delivery:0,native:30,matrix:0},newest:{delivery:0,native:30,matrix:0},can_converse_codex:codexCase,can_reply_updates:true,can_listen:false,can_speak:false,activity:{connected:true,sessions:[],observed_at:Date.now()/1000},goal_controls:{items:[],more:false}});
  if(route==='interaction/part')return json({text:sources.find(v=>v.id===url.searchParams.get('source'))?.preview||'Synthetic text',next_offset:null});
  if(route==='interaction/sonic')return json({configured:false,connected:true,sources:[]});
  if(route==='interaction/alerts')return json({state:'available',producers:[],incidents:[],csrf:'fixture-csrf'});
  if(route==='interaction/events'){res.writeHead(200,{'content-type':'text/event-stream'});res.write(': synthetic fixture\n\n');return;}
  if(route.startsWith('interaction/inputs/'))return json({schema:'telecodex.conversation-trace/v1',routes:[],text:'Exact synthetic input',read_only:true});
  return json({...base(),schema:route==='interaction/telegram-inputs'?'telecodex.telegram-input-list/v1':undefined});
 }
 const name=url.pathname.startsWith('/assets/')?path.basename(url.pathname):'index.html';
 const file=path.join(publicRoot,name);if(!fs.existsSync(file)){res.writeHead(404);return res.end();}
 let body=fs.readFileSync(file);
 if(name==='index.html')body=body.toString().replace('<html lang="en">','<html lang="en" data-shared-auth="true">').replace('    <script src="https://telegram.org/js/telegram-web-app.js" defer></script>','');
 res.writeHead(200,{'content-type':name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':name.endsWith('.woff2')?'font/woff2':'text/html'});res.end(body);
 }catch(error){errors.push(String(error));res.writeHead(500);res.end('Fixture error');}
});
server.on('connection',socket=>{sockets.add(socket);socket.on('close',()=>sockets.delete(socket));});
(async()=>{let browser;const report={state:'started',source:'shipped source assets with synthetic HTTP fixtures; no native/provider/audio hearing claim'};
 try{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin=`http://127.0.0.1:${server.address().port}`;
 browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--mute-audio','--autoplay-policy=no-user-gesture-required','--disk-cache-size=1048576','--media-cache-size=1048576']});
 const context=await browser.newContext({viewport:{width:1280,height:800}});await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
 await context.addInitScript(()=>{
  let original;window.workspaceFixture={};Object.defineProperty(window,'VoiceInput',{configurable:true,get:()=>original,set(value){original={...value,mount(hooks){window.workspaceFixture.microphone=hooks;return value.mount(hooks);}};}});
 });
 if(codexCase)await context.addInitScript(()=>{
  const actualSocket=window.WebSocket,ActualContext=window.AudioContext;
  const fixture=window.codexFixture={opens:0,contexts:[],peers:[]};
  window.AudioContext=class extends ActualContext{constructor(...args){super(...args);fixture.contexts.push(this);}};
  navigator.mediaDevices.getUserMedia=async()=>{
   const ctx=new window.AudioContext(),source=ctx.createOscillator(),gain=ctx.createGain(),dest=ctx.createMediaStreamDestination();
   gain.gain.value=.04;source.connect(gain);gain.connect(dest);source.start();await ctx.resume();
   const track=dest.stream.getAudioTracks()[0],stop=track.stop.bind(track);track.stop=()=>{stop();source.stop();void ctx.close();};return dest.stream;
  };
  window.RTCPeerConnection=class{
   constructor(){this.connectionState='new';fixture.peers.push(this);}addTrack(){}
   createDataChannel(label){if(label!=='oai-events')throw Error('Unexpected native channel');return {close(){}};}
   async createOffer(){return {type:'offer',sdp:'v=0 synthetic-offer'};}
   async setLocalDescription(value){this.localDescription=value;}
   async setRemoteDescription(value){if(value.sdp!=='v=0 synthetic-answer')throw Error('Unexpected answer');this.connectionState='connected';this.onconnectionstatechange();}
   close(){this.connectionState='closed';this.onconnectionstatechange?.();}
  };
  window.WebSocket=class{
   static OPEN=1;constructor(url){if(!String(url).endsWith('/voice/codex'))return new actualSocket(url);fixture.opens++;this.readyState=1;queueMicrotask(()=>this.onopen());}
   send(raw){const value=JSON.parse(raw),emit=value=>queueMicrotask(()=>this.onmessage({data:JSON.stringify(value)}));
    if(value.binding){this.visit=value.id;emit({type:'prepared',id:this.visit,session_seconds:600});}
    if(value.type==='offer'){emit({type:'answer',id:this.visit,sdp:'v=0 synthetic-answer'});emit({type:'transcript',id:this.visit,item:{id:'source-1',role:'assistant',text:'A synthetic native voice reply.'}});}
    if(value.type==='close')emit({type:'closed',id:this.visit,confirmed:true});
   }
   close(){this.readyState=3;queueMicrotask(()=>this.onclose?.());}
  };
 });
 const page=await context.newPage();page.on('pageerror',error=>errors.push(String(error)));
 await page.goto(origin+'/?view=conversation&client=standalone',{waitUntil:'load'});
 await page.locator('.session-workspace-toolbar').waitFor({state:'visible',timeout:12000});
 if(codexCase){
  await page.locator('#conversation-voice-choice').waitFor({state:'visible'});
  assert.equal(await page.locator('#conversation-voice-engine').inputValue(),'provider','OpenAI never replaces the default');
  assert.equal(await page.evaluate(()=>codexFixture.opens),0);
  await page.locator('#conversation-voice-engine').selectOption('codex');
  await page.locator('#conversation-companion pre').click();
  await page.waitForFunction(()=>document.querySelector('.voice-mode-state').textContent==='Listening',null,{timeout:10000});
  assert(await page.locator('#conversation-voice-engine').isDisabled());
  await page.locator('#conversation-voice-engine').evaluate(select=>{select.value='provider';select.dispatchEvent(new Event('change'));});
  assert.equal(await page.locator('#conversation-voice-engine').inputValue(),'codex','Active mode stays frozen');
  await page.screenshot({path:path.join(output,'codex-desktop-voice.png')});
  await page.setViewportSize({width:390,height:844});await page.waitForTimeout(450);
  await page.screenshot({path:path.join(output,'codex-mobile-voice.png')});
  await page.getByRole('button',{name:'Back to conversation',exact:true}).click();
  await page.waitForFunction(()=>codexFixture.contexts.every(ctx=>ctx.state==='closed')&&codexFixture.peers.every(peer=>peer.connectionState==='closed'),null,{timeout:10000});
  await page.locator('#conversation-codex-recovery').waitFor({state:'visible'});
  await page.locator('#conversation-codex-recovery summary').click();
  await page.screenshot({path:path.join(output,'codex-mobile-recovery.png')});
  await page.getByRole('button',{name:'Retry saving',exact:true}).click();
  await page.locator('#conversation-codex-recovery').waitFor({state:'hidden'});
  assert.equal(voiceUploads.length,2);assert.deepEqual(voiceUploads[0],voiceUploads[1],'Retry retains the exact original and visit');
  assert.equal(posts.length,0,'Native original recovery never uses ordinary Send');
  assert.equal(await page.evaluate(()=>codexFixture.opens),1,'Recovery does not reopen or replay voice');
  assert.equal(await page.evaluate(()=>new Promise((resolve,reject)=>{const r=indexedDB.open('daimon-voice-recovery',1);r.onsuccess=()=>{const db=r.result,tx=db.transaction('capture','readonly'),q=tx.objectStore('capture').get('pending');q.onsuccess=()=>{resolve(q.result===undefined);db.close();};q.onerror=reject;};r.onerror=reject;})),true);
  await page.locator('#conversation-voice-engine').selectOption('provider');
  assert.equal(await page.evaluate(()=>codexFixture.opens),1);
  assert.equal(errors.length,0,errors.join('\n'));
  report.state='qualified-codex-synthetic-browser';report.voiceUploads=voiceUploads;report.viewports=['1280x800','390x844'];
 }else{
 assert.equal(await page.getByRole('button',{name:'Show routing map',exact:true}).count(),0,'Messages have no routing-map shortcut');
 await page.getByRole('button',{name:'Under the hood',exact:true}).click();
 await page.locator('#conversation-flow > summary').click();
 assert(await page.locator('#routing-graph-viewport').isVisible(),'Routing map remains under the hood');
 await page.getByRole('button',{name:'Under the hood',exact:true}).click();
 await page.getByRole('button',{name:'Show sessions',exact:true}).click();
 async function bottomMenu(){
  const rect=async selector=>page.locator(selector).evaluate(node=>{const r=node.getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right};});
  const bar=await rect('.session-workspace-toolbar'),body=await rect('.session-workspace-body'),menu=await rect('.session-rail'),input=await rect('#conversation-dock');
  assert(body.bottom<=bar.top+1,'Destination toolbar follows the reading area');
  assert(bar.bottom<=input.top+1,'Destination toolbar sits above the input');
  assert(menu.bottom<=bar.top+1&&menu.top>=body.top-1,'Sessions expand upward inside the reading area');
  assert(menu.left>=0&&menu.right<=await page.evaluate(()=>innerWidth),'Session menu stays inside viewport');
 }
 await bottomMenu();
 async function compactControls(){
  const rows=await page.locator('.session-row').evaluateAll(nodes=>nodes.map(row=>{
   const buttons=[...row.querySelectorAll('.session-row-actions button')];
   return buttons.map(button=>{const r=button.getBoundingClientRect(),svg=button.querySelector('svg');return {top:r.top,width:r.width,height:r.height,icon:svg?.getBoundingClientRect().width,label:button.getAttribute('aria-label')};});
  }));
  for(const buttons of rows){
   assert.equal(buttons.length,4,'Every row retains reply, pin, mute and solo');
   for(const control of buttons){
    assert.equal(control.top,buttons[0].top,'All four controls share one compact line');
    assert(control.width>=24&&control.width<=32&&control.height>=24&&control.height<=32,'Compact controls retain usable targets');
    if(control.icon)assert(control.icon<=18,'Icons match the small audio-control scale');
    assert(control.label,'Compact icon actions retain accessible names');
   }
  }
 }
 await compactControls();
 const workerCard=page.locator('#conversation-timeline article[data-source-id="native:30"]');
 const titlePin=workerCard.locator('.session-title-pin'),titleMute=workerCard.locator('.session-audio-mute'),titleSolo=workerCard.locator('.session-audio-solo');
 const menuMaterial=page.locator('.session-row').filter({has:page.getByRole('button',{name:sessions[0].title,exact:true})});
 assert(await titlePin.isVisible()&&await titleMute.isVisible()&&await titleSolo.isVisible(),'Update title retains compact pin, Mute and Solo');
 await page.getByRole('button',{name:'Hide sessions',exact:true}).click();
 await page.locator('#conversation-message').fill('Title controls preserve my draft.');
 await titlePin.click();assert.equal(await titlePin.getAttribute('aria-pressed'),'true');
 assert.equal(await page.evaluate(()=>workspaceFixture.microphone.getReply().reference.source),'session:7');
 assert.equal(await page.getByRole('button',{name:'Send to the conversation',exact:true}).getAttribute('aria-pressed'),'true');
 await page.getByRole('button',{name:'Show sessions',exact:true}).click();
 assert.equal(await menuMaterial.getByRole('button',{name:'Pin as the input destination',exact:true}).getAttribute('aria-pressed'),'true','Title pin updates the menu');
 await menuMaterial.getByRole('button',{name:'Pin as the input destination',exact:true}).click();
 assert.equal(await titlePin.getAttribute('aria-pressed'),'false','Menu unpin updates the title');
 await titleMute.click();await page.getByRole('button',{name:'Show sessions',exact:true}).click();
 assert.equal(await menuMaterial.getByRole('button',{name:`Unmute ${sessions[0].title}`,exact:true}).getAttribute('aria-pressed'),'true','Title Mute updates the menu');
 await menuMaterial.getByRole('button',{name:`Unmute ${sessions[0].title}`,exact:true}).click();
 assert.equal(await titleMute.getAttribute('aria-pressed'),'false','Menu Mute updates the title');
 await page.getByRole('button',{name:'Hide sessions',exact:true}).click();await titleSolo.click();
 await page.getByRole('button',{name:'Show sessions',exact:true}).click();
 assert.equal(await menuMaterial.getByRole('button',{name:`Remove solo from ${sessions[0].title}`,exact:true}).getAttribute('aria-pressed'),'true','Title Solo updates the menu');
 await menuMaterial.getByRole('button',{name:`Remove solo from ${sessions[0].title}`,exact:true}).click();
 assert.equal(await titleSolo.getAttribute('aria-pressed'),'false','Menu Solo updates the title');
 await menuMaterial.getByRole('button',{name:'Pin as the input destination',exact:true}).click();
 assert.equal(await titlePin.getAttribute('aria-pressed'),'true','Menu pin updates the title');
 await page.getByRole('button',{name:'Send to the conversation',exact:true}).click();
 assert.equal(await titlePin.getAttribute('aria-pressed'),'false','Destination unpin updates title and menu');
 assert.equal(await page.locator('#conversation-message').inputValue(),'Title controls preserve my draft.');
 await page.screenshot({path:path.join(output,'desktop-title-controls.png')});
 await page.setViewportSize({width:390,height:844});await workerCard.scrollIntoViewIfNeeded();
 await page.screenshot({path:path.join(output,'mobile-title-controls.png')});
 await page.setViewportSize({width:1280,height:800});
 await page.getByRole('button',{name:'Show sessions',exact:true}).click();
 assert.equal(await page.getByRole('button',{name:'Old inactive session',exact:true}).count(),0);
 assert.deepEqual(await page.locator('.session-name').allTextContents(),[sessions[1].title,sessions[2].title,sessions[0].title]);
 await page.locator('.session-row').filter({has:page.getByRole('button',{name:sessions[0].title,exact:true})}).getByRole('button',{name:'Pin as the input destination',exact:true}).click();
 assert.equal(await page.locator('.session-rail').isVisible(),false,'Pin collapses the menu');
 assert(await page.getByRole('button',{name:'Show sessions',exact:true}).evaluate(button=>button===document.activeElement),'Pin returns focus to the toggle');
 await page.getByRole('button',{name:'Show sessions',exact:true}).click();
 await page.locator('#conversation-message').fill('Keep this draft while I look around.');
 assert.equal(await page.evaluate(()=>workspaceFixture.microphone.getReply().reference.source),'session:7');
 await page.getByRole('button',{name:sessions[1].title,exact:true}).click();
 await page.locator('.session-message').first().waitFor();
 assert.equal(await page.evaluate(()=>workspaceFixture.microphone.getReply().reference.source),'session:8');
 assert.equal(await page.locator('#conversation-message').inputValue(),'Keep this draft while I look around.');
 await page.getByRole('button',{name:'Show tools and exposed reasoning summaries'}).click();
 await page.getByText('>_ inspect_result',{exact:true}).waitFor();
 assert(await page.getByText('Reasoning summary',{exact:true}).isVisible());
 await page.screenshot({path:path.join(output,'desktop-technical.png')});
 await page.getByRole('button',{name:'Back to the conversation',exact:true}).click();
 assert.equal(await page.evaluate(()=>workspaceFixture.microphone.getReply().reference.source),'session:7');
 await page.locator('#conversation-send').click();await page.waitForFunction(()=>document.querySelector('#conversation-message').value==='');
 assert.equal(posts.at(-1).reply.source,'session:7');assert.equal(posts.at(-1).text,'Keep this draft while I look around.');
 assert.equal(await page.locator('#conversation-timeline .routing-trace').count(),0,'Conversation messages have no routing-path disclosure');
 assert(await page.locator('#conversation-diagnostics #conversation-inputs .routing-trace').count()>0,'Routing evidence remains under the hood');
 await page.getByRole('button',{name:'Show sessions',exact:true}).click();
 await page.locator('.session-row').filter({has:page.getByRole('button',{name:sessions[0].title,exact:true})}).getByRole('button',{name:'Reply to the latest message',exact:true}).click();
 assert.equal(await page.locator('.session-rail').isVisible(),false,'Reply collapses the menu');
 assert(await page.locator('#conversation-message').evaluate(input=>input===document.activeElement),'Reply focuses the composer');
 await page.locator('#conversation-message').fill('About that exact result.');await page.locator('#conversation-send').click();
 await page.waitForFunction(()=>document.querySelector('#conversation-message').value==='');assert.equal(posts.at(-1).reply.source,'session:7/42');
 await page.getByRole('button',{name:'Show sessions',exact:true}).click();
 await page.getByRole('button',{name:`Mute ${sessions[0].title}`,exact:true}).click();
 assert(await page.locator('.session-rail').isVisible(),'Mute keeps the menu open');
 assert.equal(await page.getByRole('button',{name:`Unmute ${sessions[0].title}`,exact:true}).getAttribute('aria-pressed'),'true');
 await page.getByRole('button',{name:`Solo ${sessions[0].title}`,exact:true}).click();
 assert(await page.locator('.session-rail').isVisible(),'Solo keeps the menu open');
 assert.equal(await page.getByRole('button',{name:`Remove solo from ${sessions[0].title}`,exact:true}).getAttribute('aria-pressed'),'true');
 async function resetInHeader(){
  const reset=page.locator('.session-rail-header .session-workspace-reset');assert(await reset.isVisible(),'Reset is in the expanded menu header');
  assert.equal(await page.locator('.session-workspace-toolbar .session-workspace-reset').count(),0,'Collapsed toolbar has no audio reset');
  const box=await reset.boundingBox(),controls=await page.locator('.session-row-actions').first().boundingBox();
  assert(Math.abs(box.x-controls.x)<=1&&Math.abs(box.width-controls.width)<=1&&box.y+box.height<=controls.y,`Reset aligns above the controls column: ${JSON.stringify({box,controls})}`);
 }
 await resetInHeader();await page.screenshot({path:path.join(output,'desktop-audio-reset.png')});
 await page.getByRole('button',{name:'Hear all sessions: clear mute and solo',exact:true}).click();
 assert.equal(await page.locator('.session-workspace-reset').isVisible(),false,'Reset hides when filters clear');
 assert(await page.locator('.session-rail').isVisible(),'Reset keeps the menu open');
 await page.screenshot({path:path.join(output,'desktop-sessions.png')});
 await page.setViewportSize({width:390,height:844});
 await page.locator('#conversation-message').fill('My draft stays here.');await page.screenshot({path:path.join(output,'mobile-sessions.png')});
 await bottomMenu();
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'No horizontal page overflow');
 const layout=await page.locator('.session-row').first().evaluate(row=>{
  const rect=selector=>{const r=row.querySelector(selector).getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom};};
  return {name:rect('.session-name'),actions:rect('.session-row-actions'),state:rect('.session-row-state')};
 });
 assert(layout.actions.x>=layout.name.right-1,'Controls sit to the right of the title');
 assert(layout.state.y>=Math.max(layout.name.bottom,layout.actions.bottom)-1,'Status sits below title and controls');
 assert((await page.getByRole('button',{name:`Mute ${sessions[0].title}`,exact:true}).innerHTML()).includes('M11 5 6 9H3'),'Canonical speaker mute icon');
 await compactControls();
 await page.getByRole('button',{name:`Mute ${sessions[0].title}`,exact:true}).click();await resetInHeader();
 await page.screenshot({path:path.join(output,'mobile-audio-reset.png')});
 await page.getByRole('button',{name:'Hear all sessions: clear mute and solo',exact:true}).click();
 await page.locator('.session-row').filter({has:page.getByRole('button',{name:sessions[0].title,exact:true})}).getByRole('button',{name:'Reply to the latest message',exact:true}).click();
 assert.equal(await page.locator('.session-rail').isVisible(),false,'Mobile reply collapses the menu');
 assert(await page.locator('#conversation-message').evaluate(input=>input===document.activeElement),'Mobile reply focuses the composer');
 await page.getByRole('button',{name:'Show sessions',exact:true}).click();
 await page.locator('.session-row').filter({has:page.getByRole('button',{name:sessions[1].title,exact:true})}).getByRole('button',{name:'Pin as the input destination',exact:true}).click();
 assert.equal(await page.locator('.session-rail').isVisible(),false,'Mobile pin collapses the menu');
 assert(await page.getByRole('button',{name:'Show sessions',exact:true}).evaluate(button=>button===document.activeElement),'Mobile pin focuses the toggle');
 assert.equal(await page.evaluate(()=>workspaceFixture.microphone.getReply().reference.source),'session:8');
 assert.equal(await page.locator('#conversation-message').inputValue(),'My draft stays here.','Mobile pin/reply preserve draft');
 await page.getByRole('button',{name:'Show sessions',exact:true}).click();
 await page.locator('.session-row').filter({has:page.getByRole('button',{name:sessions[0].title,exact:true})}).getByRole('button',{name:'Pin as the input destination',exact:true}).click();
 await page.getByRole('button',{name:'Show sessions',exact:true}).click();

 await page.setViewportSize({width:320,height:740});await bottomMenu();await compactControls();
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'No horizontal overflow at 320px');
 const focused=page.locator('.session-row-actions button').first();await page.locator('.session-name').first().focus();await page.keyboard.press('Tab');
 assert(await focused.evaluate(button=>button.matches(':focus-visible')&&getComputedStyle(button).outlineStyle!=='none'),'Keyboard focus remains visible on compact controls');
 await page.screenshot({path:path.join(output,'narrow-sessions.png')});
 await page.setViewportSize({width:390,height:844});


 await page.getByRole('button',{name:'Hide sessions',exact:true}).click();
 const timeline=page.locator('#conversation-timeline');await timeline.evaluate(node=>{node.scrollTop=0;});await page.waitForTimeout(100);
 assert.equal(await page.locator('body').evaluate(body=>body.classList.contains('conversation-header-compact')),false,'Programmatic positioning does not compact header');
 await page.locator('#conversation-presence').evaluate(node=>{node.hidden=false;node.textContent='Pending work';});
 await timeline.hover();await page.mouse.wheel(0,900);await page.waitForTimeout(150);
 assert(await page.locator('body').evaluate(body=>body.classList.contains('conversation-header-compact')),'User forward scroll compacts header');
 assert.equal(await page.locator('#conversation-presence').isVisible(),false,'Compact header hides the pending line');
 const identity=await page.locator('header .companion-name').boundingBox(),header=await page.locator('header').boundingBox();
 assert(identity.y>=header.y&&identity.y+identity.height<=header.y+header.height,'Compact identity remains fully visible');
 await page.screenshot({path:path.join(output,'mobile-compact.png')});
 await page.mouse.wheel(0,-300);await page.waitForTimeout(150);
 assert.equal(await page.locator('body').evaluate(body=>body.classList.contains('conversation-header-compact')),false,'Reverse scroll restores header');
 assert(await page.locator('#conversation-presence').isVisible(),'Reverse scroll restores the pending line');
 await page.screenshot({path:path.join(output,'mobile-conversation.png')});
 assert.equal(await page.locator('#conversation-message').inputValue(),'My draft stays here.');
 workspaceAllowed=false;await page.locator('#conversation-refresh').evaluate(button=>button.click());
 await page.getByText('Session workspace access is unavailable. Return the input to the conversation, or restore access.',{exact:true}).waitFor();
 assert(await page.locator('#conversation-timeline').isVisible());assert(await titlePin.isDisabled(),'Grant loss disables update-title pin');assert(await page.locator('#conversation-account').isVisible(),'Workspace denial is not a global sign-out');
 assert.equal(await page.locator('#conversation-message').inputValue(),'My draft stays here.');
 await page.getByRole('button',{name:'Send to the conversation',exact:true}).click();assert.equal(errors.length,0,errors.join('\n'));
 report.state='qualified-synthetic-browser';report.posts=posts.map(v=>({text:v.text,reply:v.reply}));report.viewports=['1280x800','390x844','320x740'];report.errors=errors;
 }
 }finally{
 if(browser)await browser.close();for(const socket of sockets)socket.destroy();await new Promise(resolve=>server.close(resolve));
 report.errors=errors;fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(report,null,2));
 const bytes=fs.readdirSync(output).reduce((n,file)=>n+fs.statSync(path.join(output,file)).size,0);assert(bytes<=4*1024*1024);console.log(JSON.stringify({state:report.state,retained_bytes:bytes,errors}));
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
