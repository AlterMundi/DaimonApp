/* Shipped shell/assets in Chromium with synthetic API fixtures only.
 * Output <=4MiB, one temporary HTTP server/browser, no provider/native calls. */
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const output=process.env.QUALIFICATION_OUTPUT;assert(output&&path.isAbsolute(output)&&!fs.existsSync(output));fs.mkdirSync(output,{mode:0o700});
const avatarPath=process.env.QUALIFICATION_AVATAR_RECORD;
let avatarRecord;
if(avatarPath){assert(path.isAbsolute(avatarPath));const bytes=fs.readFileSync(avatarPath);assert(bytes.length<=1048576);avatarRecord=JSON.parse(bytes);assert(/^[a-f0-9-]{36}$/.test(avatarRecord.id)&&avatarRecord.design);}
const avatarEntrySelector=avatarRecord?'#conversation-companion .avatar-surface':'#conversation-companion pre';
const imageCase=process.env.QUALIFICATION_IMAGE_PREVIEW==='1';let imageAccess=true;
const imageBytes=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jGQAAAABJRU5ErkJggg==','base64');
const imageArtifact={id:'12345678-1234-5678-9876-123456789abc',name:'drawing.png',sha256:require('node:crypto').createHash('sha256').update(imageBytes).digest('hex'),bytes:imageBytes.length,available:true};
const unifiedAttentionCase=process.env.QUALIFICATION_UNIFIED_ATTENTION==='1';
const reconnectCase=process.env.QUALIFICATION_SESSION_RECONNECT==='1';let workspaceOutage=false;
const hudCase=imageCase||process.env.QUALIFICATION_HUD==='1',authoredCase=hudCase||reconnectCase||process.env.QUALIFICATION_AUTHORED==='1';
const appearanceCase=process.env.QUALIFICATION_APPEARANCE==='1';
const countdownCase=process.env.QUALIFICATION_COUNTDOWN==='1';
const authCase=process.env.QUALIFICATION_AUTH==='1';let authDenied=false,readRejections=0,accessReads=0,writeRejected=false;
const publicDefaultCase=process.env.QUALIFICATION_PUBLIC_DEFAULT==='1';
const reloadCase=process.env.QUALIFICATION_RELOAD==='1',publicCase=publicDefaultCase||process.env.QUALIFICATION_PUBLIC_LIVE==='1';let prefixSupport=false;
const nativeDecisionCase=process.env.QUALIFICATION_HOME_DECISIONS;let nativeDecisionGranted=nativeDecisionCase==='allowed';const nativeDecisionPosts=[];
const avatarSpeechCase=process.env.QUALIFICATION_AVATAR_SPEECH==='1';
const codexActivityCase=avatarSpeechCase||process.env.QUALIFICATION_CODEX_ACTIVITY==='1';
const codexCase=codexActivityCase||process.env.QUALIFICATION_CODEX==='1',listenCase=process.env.QUALIFICATION_LISTEN==='1';let uploadFailed=false,pendingQuestion=unifiedAttentionCase||hudCase||!!nativeDecisionCase,questionPosts=0;const voiceUploads=[];
const publicRoot=path.resolve('dashboard/web'),binding='a'.repeat(64),revision='b'.repeat(64),posts=[],errors=[],sockets=new Set();
const ref=n=>({source:`session:${n}`,revision});
const sessions=[{id:'1'.repeat(24),title:'Materials · Results ready for a closer look',audio_key:'100:7',destination:ref(7),latest_reply:{...ref(7),source:'session:7/42'},fresh:true,execution:'idle',goal_state:'absent',result_available:true},
{id:'2'.repeat(24),title:'Garden · Waiting for your choice',audio_key:'100:8',destination:ref(8),latest_reply:{...ref(8),source:'session:8/43'},fresh:true,human_action_pending:true,execution:'working',goal_state:'blocked'},
{id:'3'.repeat(24),title:'Conversation',audio_key:'100:1',destination:null,is_entry:true,fresh:true,execution:'working',goal_state:'active'}];
for(const row of sessions)row.last_activity_at=Date.now()/1000;
sessions.push({id:'4'.repeat(24),title:'Old inactive session',last_activity_at:Date.now()/1000-172800,fresh:false,execution:'idle',goal_state:'absent'});
const originals=[];let seen=0,workspaceAllowed=true;
let nativeDecisionResolved=false;
const question=()=>({id:'9'.repeat(32),sequence:1,binding,revision:'d'.repeat(64),capture_version:'e'.repeat(64),created_at:'2026-11-08T10:00:00Z',state:'pending',kind:'question',actionable:true,title:'Choose a place',label:'Conversation',preview:'Where should we meet?',body:'Where should we meet: in the garden or in the workshop?',offset:0,next_offset:null,choices:[],allows_text:true,can_cancel:false,question_index:0,question_total:1,...(nativeDecisionCase?{state:nativeDecisionResolved?'answered':'pending',actionable:!nativeDecisionResolved,kind:'approval',title:'Synthetic native operation',preview:'Review the selected operation.',body:'Allow this synthetic tool operation once?',choices:[{label:'Allow once',action:{kind:'approval',choice:'a'}}],allows_text:false,can_cancel:true}:{})});
const sources=Array.from({length:30},(_,i)=>({id:`native:${i+1}`,kind:'integrator_answer',revision,preview:`A small observation ${i+1}. `+'A retained synthetic conversation gives this reading area enough room to scroll naturally. '.repeat(8),observed_at:new Date(1704067200000+i*1000).toISOString()}));
sources[29]={...sources[29],kind:'worker_result',label:'Materials',target:{chat_id:100,thread_id:7},preview:'A synthetic worker result for the shared title controls.',current:true,native_binding_current:true,completed:true};
if(hudCase){sources.splice(0,29);sources[0]={...sources[0],kind:'integrator_answer',preview:'Let us explore this idea together.\n\nWe can open the result and keep creating.',text_characters:85};}
if(imageCase)sources[0].artifacts=[imageArtifact];
const base=()=>({binding,csrf:'fixture-csrf',items:[],cursor:0,newest:0,more:false});
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://fixture.invalid');
 const json=(v,status=200)=>{res.writeHead(status,{'content-type':'application/json','cache-control':'no-store'});res.end(JSON.stringify(v));};
 try{
 if(url.pathname.startsWith('/api/')){
  const route=url.pathname.slice(5);
  if(avatarRecord&&route==='interaction/avatars'&&req.method==='GET')return json({generation:1,active:avatarRecord.id,editing:avatarRecord.id,versions:[]});
  if(avatarRecord&&route==='interaction/avatars/'+avatarRecord.id&&req.method==='GET')return json(avatarRecord);

  if(imageCase&&route==='interaction/artifacts/'+imageArtifact.id){res.writeHead(200,{'content-type':'application/octet-stream','X-Artifact-Sha256':imageArtifact.sha256});res.end(imageBytes);return;}
  if(route==='interaction/voice/gpt-live/visits'){
   const older=url.searchParams.has('before');
   return json({visits:publicCase?[{id:older?'22222222-2222-4222-8222-222222222222':'11111111-1111-4111-8111-111111111111',created_at:1704067000-(older?10:0),state:'created'}]:[],more:publicCase&&!older,before:publicCase&&!older?'11111111-1111-4111-8111-111111111111':null});
  }
  if(route.startsWith('interaction/voice/gpt-live/visits/')&&route.endsWith('/events')){
   const older=route.includes('22222222-2222-4222-8222-222222222222');
   return json({items:(older?['Una respuesta anterior.']:['Una corrección',' guardada.']).map((delta,i)=>({event_id:'retained-'+i,event:{event_id:'retained-'+i,type:'session.output_transcript.delta',delta}})),after:200,revision:'retained-source',more:false});
  }
  if(route==='interaction/voice/codex/visits'){
   if(!codexCase)return json({visits:[],more:false,before:null});
   const older=url.searchParams.has('before'),cursor='12345678-1234-4234-8234-123456789012';
   if(older)assert.equal(url.searchParams.get('before'),cursor);
   return json({visits:Array.from({length:older?2:8},(_,i)=>({id:`retained-${older?'older':'recent'}-${i}`,created_at:1704067100-i*10,items:[
    {id:`retained-source-${i}`,role:i%2?'assistant':'user',text:`${older?'Earlier retained':'Recent retained'} voice source ${i}`,observed_at:1704067100-i*10}]})),more:!older,before:older?null:cursor});
  }
  if(reloadCase&&route.startsWith('interaction/voice/codex/visits/')&&req.method==='GET')return json({state:'closed',...(prefixSupport?{capture_prefix_retention:'v1'}:{})});
  if(route.endsWith('/capture/ended')&&route.startsWith('interaction/voice/codex/visits/')&&req.method==='POST')return json({capture:'ended'});
  if((route.startsWith('interaction/voice/codex/visits/')||route.startsWith('interaction/voice/gpt-live/visits/'))&&req.method==='POST'){
   const chunks=[];for await(const chunk of req)chunks.push(chunk);const raw=Buffer.concat(chunks);
   const parts=route.split('/'),visit=parts[4],ordinal=Number(parts[6]);
   if(reloadCase)fs.writeFileSync(path.join(output,'tone-original-'+voiceUploads.length+'.wav'),raw,{flag:'wx'});
   voiceUploads.push({visit,ordinal,bytes:raw.length,sha:require('node:crypto').createHash('sha256').update(raw).digest('hex')});
   if(!uploadFailed){uploadFailed=true;return json({detail:'Synthetic first receipt unavailable'},503);}
   return json({visit,binding,recording:{ordinal,audio_sha256:voiceUploads.at(-1).sha,audio_bytes:raw.length,...(publicCase?{work_replay:'never'}:{native_replay:'never'}),...(req.headers['x-voice-capture-stop']?{capture_stop:req.headers['x-voice-capture-stop']}:{})}});
  }
  if(route==='interaction/internal')return json({...base(),items:unifiedAttentionCase?[{...question(),id:'8'.repeat(32),created_at:'2026-11-09T10:00:00Z',label:'Workshop',title:'A routed decision',preview:'Choose the next workshop step.'}]:[],cursor:unifiedAttentionCase?1:0,newest:unifiedAttentionCase?1:0});
  if(route.startsWith('interaction/internal/requests/'))return json({...question(),id:'8'.repeat(32),label:'Workshop',title:'A routed decision',body:'Choose the next workshop step.'});
  if(route==='interaction/requests')return json({...base(),items:pendingQuestion?[question()]:[],cursor:pendingQuestion?1:0,newest:pendingQuestion?1:0});
  if(route.startsWith('interaction/requests/')){
   if(req.method==='POST'){
    if(nativeDecisionCase){if(!nativeDecisionGranted)return json({detail:'Conversation-only grant'},403);let raw='';for await(const part of req)raw+=part;nativeDecisionPosts.push(JSON.parse(raw));nativeDecisionResolved=true;return json({id:question().id,binding,revision:'d'.repeat(64),recorded:true});}
    questionPosts++;
   }return json(question());
  }
  if(route==='interaction/access'){accessReads++;return authDenied?json({detail:'Expired'},401):json({csrf:'fixture-csrf',label:'Synthetic operator'});}
  if(route==='interaction' && readRejections>0 && (!authCase||url.searchParams.get('qualification')==='auth')){readRejections--;return json({detail:'Synthetic access rejection'},401);}
  if(route==='interaction/sessions'&&workspaceOutage)return json({detail:'Synthetic transient status outage'},503);
  if(route==='interaction/sessions')return workspaceAllowed?json({schema:'daimon.session-workspace/v1',sessions}):json({detail:'Workspace grant revoked'},403);
  if(route.startsWith('interaction/sessions/')){
   const technical=url.searchParams.get('technical')==='true',after=url.searchParams.has('after');
   return json({schema:'daimon.session-view/v1',revision:'c'.repeat(64),before:50,after:250,has_earlier:false,more:false,
    items:after?[]:[...(technical?[{id:'message',kind:'message',role:'user',text:'Show me what we discovered.',position:50,next_position:100}]:[]),
     {id:'response',kind:'message',role:'assistant',text:'The first prototype is ready. Let us look together.',position:100,next_position:150},
     ...(technical?[{id:'tool',kind:'tool_call',name:'inspect_result',text:'{"result":"prototype"}',position:150,next_position:200},
      {id:'summary',kind:'reasoning_summary',role:'assistant',text:'Compare the measured result with our original question.',position:200,next_position:250}]:[])]});
  }
  if(route==='interaction/inputs'&&req.method==='POST'){
   let raw='';for await(const block of req)raw+=block;const body=JSON.parse(raw);posts.push(body);
   const value={...body,phase:body.reply?'routed':'accepted',sequence:++seen,received_at:new Date().toISOString(),...(body.reply?{routing:{phase:'accepted',label:'Materials',target:{thread_id:7},instruction:'fixture-instruction'}}:{})};originals.push(value);return writeRejected?json({detail:"Synthetic lost authorization response"},401):json(value);
  }
  if(route==='interaction/inputs')return json({...base(),items:originals,cursor:seen,newest:seen});
  if(route==='interaction')return json({...base(),items:sources,cursor:{delivery:0,native:30,matrix:0},newest:{delivery:0,native:30,matrix:0},can_converse_codex:codexCase,can_converse_public_live:publicCase,can_converse_public_live_native:publicDefaultCase,avatar_voice_default:publicDefaultCase?'gpt-live-native':null,can_reply_updates:true,can_decide_requests:nativeDecisionGranted,can_download_files:appearanceCase||imageCase&&imageAccess,can_listen:listenCase,can_speak:countdownCase||hudCase||publicDefaultCase,activity:{connected:true,sessions:[],observed_at:Date.now()/1000},goal_controls:{items:[],more:false}});
  if(route==='interaction/part')return json({text:sources.find(v=>v.id===url.searchParams.get('source'))?.preview||'Synthetic text',next_offset:null});
  if(route==='interaction/audio')return json({detail:'Synthetic read-aloud unavailable; no provider called'},503);
  if(route==='interaction/sonic')return json({configured:false,connected:true,sources:[]});
  if(route==='interaction/alerts')return json({state:'available',producers:[],incidents:[],csrf:'fixture-csrf'});
  if(route==='interaction/events'){res.writeHead(200,{'content-type':'text/event-stream'});res.write(': synthetic fixture\n\n');return;}
  if(route.startsWith('interaction/inputs/'))return json({schema:'telecodex.conversation-trace/v1',routes:[],text:'Exact synthetic input',read_only:true});
  return json({...base(),schema:route==='interaction/telegram-inputs'?'telecodex.telegram-input-list/v1':undefined});
 }
 const name=url.pathname.startsWith('/assets/avatar-workshop/')?url.pathname.slice('/assets/'.length):url.pathname.startsWith('/assets/')?path.basename(url.pathname):'index.html';
 const file=path.resolve(publicRoot,name);if(!file.startsWith(publicRoot+path.sep)){res.writeHead(404);return res.end();}if(!fs.existsSync(file)){res.writeHead(404);return res.end();}
 let body=fs.readFileSync(file);
 if(name==='index.html')body=body.toString().replace('<html lang="en">','<html lang="en" data-shared-auth="true"'+(authoredCase?' data-style-policy="authored"':'')+'>').replace('    <script src="https://telegram.org/js/telegram-web-app.js" defer></script>','');
 if(name==='index.html'&&appearanceCase)body=body.toString().replace('</head>','<style>:root{--dm-background:#ffffff;--dm-surface:#ffffff;--dm-text:#111111;--dm-accent:#176241}</style></head>');
 if(name==='index.html'&&hudCase)body=body.toString().replace('<body>','<body class="conversation-mode standalone-conversation">').replace('<div id="client-build" hidden></div>','<div id="client-build" aria-label="Client version fixture">ui <code>fixture-version</code></div>');
 res.writeHead(200,{'content-type':(name.endsWith('.js')||name.endsWith('.mjs'))?'application/javascript':name.endsWith('.json')?'application/json':name.endsWith('.ttf')?'font/ttf':name.endsWith('.css')?'text/css':name.endsWith('.woff2')?'font/woff2':'text/html'});res.end(body);
 }catch(error){errors.push(String(error));res.writeHead(500);res.end('Fixture error');}
});
server.on('connection',socket=>{sockets.add(socket);socket.on('close',()=>sockets.delete(socket));});
(async()=>{let browser;const report={state:'started',source:'shipped source assets with synthetic HTTP fixtures; no native/provider/audio hearing claim'};
 try{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin=`http://127.0.0.1:${server.address().port}`;
 browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--mute-audio','--autoplay-policy=no-user-gesture-required','--disk-cache-size=1048576','--media-cache-size=1048576']});
 const context=await browser.newContext({viewport:{width:1280,height:800}});await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
 if(hudCase){
  const cold=await context.newPage();await cold.route('**/*.js',route=>route.abort());
  await cold.goto(origin+'/?view=conversation&client=standalone');
  assert.equal(await cold.locator('#client-build').isVisible(),false,'The first render keeps debugging inside closed technical details even when scripts fail');
  await cold.close();
 }
 await context.addInitScript(()=>{
  let original;window.workspaceFixture={};Object.defineProperty(window,'VoiceInput',{configurable:true,get:()=>original,set(value){original={...value,mount(hooks){window.workspaceFixture.microphone=hooks;return value.mount(hooks);}};}});
 });
 if(unifiedAttentionCase)await context.addInitScript(()=>{
  const controls=[];window.pendingFixture=controls;let original;
  Object.defineProperty(window,'RequestControls',{configurable:true,get:()=>original,set(value){original={...value,mount(options){const result=value.mount(options);controls.push(result);return result;}};}});
 });
 if(countdownCase)await context.addInitScript(()=>{
  const ActualContext=window.AudioContext,now=performance.now.bind(performance);
  const fixture=window.countdownFixture={offset:0,tones:[],contexts:[],peak:0};
  performance.now=()=>fixture.offset;
  window.AudioContext=class extends ActualContext{
   constructor(...args){super(...args);fixture.contexts.push(this);this.analyser=this.createAnalyser();this.samples=new Float32Array(this.analyser.fftSize);}
   createGain(){const gain=super.createGain(),connect=gain.connect.bind(gain);gain.connect=target=>{if(target===this.destination){connect(this.analyser);setTimeout(()=>{this.analyser.getFloatTimeDomainData(this.samples);fixture.peak=Math.max(fixture.peak,...this.samples.map(Math.abs));},45);}return connect(target);};return gain;}
   createOscillator(){const tone=super.createOscillator(),start=tone.start.bind(tone),set=tone.frequency.setValueAtTime.bind(tone.frequency);tone.frequency.setValueAtTime=(hz,...args)=>{tone.fixtureFrequency=hz;return set(hz,...args);};tone.start=(...args)=>{fixture.tones.push(tone.fixtureFrequency);return start(...args);};return tone;}
  };
  // Empty synthetic tracks are sufficient for the recorder fixture: no physical
  // microphone, speech recognition, network upload or provider is used.
  navigator.mediaDevices.getUserMedia=async()=>new MediaStream();
  window.MediaRecorder=class{static isTypeSupported(){return true;}constructor(){this.state='inactive';this.events={};}addEventListener(n,f){this.events[n]=f;}start(){this.state='recording';}stop(){this.state='inactive';}};
 });
 if(codexCase||publicCase)await context.addInitScript(({publicCase,codexActivityCase})=>{
  const actualSocket=window.WebSocket,ActualContext=window.AudioContext;
  const fixture=window.codexFixture={opens:0,contexts:[],peers:[],captureBytes:0,audioRequests:0,audioRequestedWhileNativeOpen:false};
  if(codexActivityCase)for(const name of [publicCase?'PublicLiveConversation':'CodexConversation']){let original;Object.defineProperty(window,name,{configurable:true,get:()=>original,set(value){original={...value,create(options){const engine=value.create({...options,onState:state=>{(fixture.outputLevels??=[]).push(state.outputLevel);options.onState?.(state);}});fixture.engine=engine;return engine;}};}});}

  let captureModule;Object.defineProperty(window,'StreamingVoice',{configurable:true,get:()=>captureModule,set(value){captureModule={...value,async openCapture(...args){const c=await value.openCapture(...args);c.subscribe(e=>{if(e.pcm)fixture.captureBytes+=e.pcm.byteLength;});return c;}};}});
  const actualFetch=window.fetch.bind(window);window.fetch=(url,...args)=>{if(String(url).endsWith('api/interaction/audio')){fixture.audioRequests++;fixture.audioRequestedWhileNativeOpen ||= fixture.peers.some(peer=>peer.connectionState!=='closed')||fixture.contexts.some(ctx=>ctx.state!=='closed');}return actualFetch(url,...args);};
  window.AudioContext=class extends ActualContext{constructor(...args){super(...args);fixture.contexts.push(this);}};
  navigator.mediaDevices.getUserMedia=async()=>{
   const ctx=new window.AudioContext(),source=ctx.createOscillator(),gain=ctx.createGain(),dest=ctx.createMediaStreamDestination();
   gain.gain.value=.04;source.connect(gain);gain.connect(dest);source.start();await ctx.resume();
   const track=dest.stream.getAudioTracks()[0],stop=track.stop.bind(track);track.stop=()=>{stop();source.stop();void ctx.close();};return dest.stream;
  };
  window.RTCPeerConnection=class{
   constructor(){this.connectionState='new';this.iceGatheringState='complete';fixture.peers.push(this);}addTrack(){}
   createDataChannel(label){if(label!=='oai-events')throw Error('Unexpected native channel');return this.channel={close(){}};}
   async createOffer(){return {type:'offer',sdp:'v=0 synthetic-offer'};}
   async setLocalDescription(value){this.localDescription=value;}
   async setRemoteDescription(value){if(value.sdp!=='v=0 synthetic-answer')throw Error('Unexpected answer');this.connectionState='connected';this.onconnectionstatechange();if(publicCase)this.channel.onmessage({data:JSON.stringify({type:'session.started',session:{id:'live_opaque/provider:42'}})});
    if(codexActivityCase){const ctx=new window.AudioContext({sampleRate:24000}),source=ctx.createOscillator(),gain=ctx.createGain(),dest=ctx.createMediaStreamDestination();source.frequency.value=660;gain.gain.value=.12;source.connect(gain);gain.connect(dest);source.start();await ctx.resume();this.output=fixture.remoteOutput={ctx,source,gain,stream:dest.stream};this.ontrack({streams:[dest.stream]});}
   }
   close(){this.connectionState='closed';if(this.output){this.output.source.stop();for(const track of this.output.stream.getTracks())track.stop();void this.output.ctx.close();}this.onconnectionstatechange?.();}
  };
  window.WebSocket=class{
   static OPEN=1;constructor(url){if(!String(url).endsWith(publicCase?'/voice/gpt-live':'/voice/codex'))return new actualSocket(url);fixture.opens++;this.readyState=1;queueMicrotask(()=>this.onopen());}
   send(raw){const value=JSON.parse(raw),emit=value=>queueMicrotask(()=>this.onmessage({data:JSON.stringify(value)}));
    if(value.binding){this.visit=value.id;emit(publicCase?{type:'prepared',id:this.visit,admission:{id:this.visit,remaining_seconds:600,max_input_pcm_bytes:600*32000}}:{type:'prepared',id:this.visit,session_seconds:600,logical_visit:'v1',admission:null});}
    if(value.type==='capture')emit({type:'capture_ready',id:this.visit,admission:{id:this.visit,remaining_seconds:600,expires:Date.now()/1000+600,max_input_pcm_bytes:600*32000,generation:0}});
    if(value.type==='offer'){
     emit({type:'answer',id:this.visit,sdp:'v=0 synthetic-answer',...(publicCase?{session:'live_opaque/provider:42'}:{})});
     if(publicCase){
      emit({type:'provider_event',event:{type:'session.input_transcript.delta',event_id:'speech-1',delta:'  Mi corrección.'}});
      emit({type:'provider_event',event:{type:'session.output_transcript.delta',event_id:'speech-2',delta:'Conservo '}});
      emit({type:'provider_event',event:{type:'session.output_transcript.delta',event_id:'speech-3',delta:'tu corrección.'}});
     }else emit({type:'transcript',id:this.visit,item:{id:'source-1',role:'assistant',text:'A synthetic native voice reply.'}});
    }
    if(value.type==='close')emit({type:'closed',id:this.visit,confirmed:true});
   }
   close(){this.readyState=3;queueMicrotask(()=>this.onclose?.());}
  };
 },{publicCase,codexActivityCase});
 if(avatarSpeechCase)await context.addInitScript(()=>{
  let original;window.avatarSpeechLevels=[];Object.defineProperty(window,'AvatarWorkshopUI',{configurable:true,get:()=>original,set(value){original={...value,mount(options){const ui=value.mount(options);return {...ui,speechLevel(level){const canvas=document.querySelector('.avatar-surface canvas'),before=canvas?.toDataURL();ui.speechLevel(level);avatarSpeechLevels.push({level,changed:!!canvas&&before!==canvas.toDataURL()});if(avatarSpeechLevels.length>32)avatarSpeechLevels.shift();}};}};}});
 });
 if(hudCase)await context.addInitScript(()=>{
  let module;Object.defineProperty(window,'PublicLiveConversation',{configurable:true,get:()=>module,set(value){module={...value,create(options){window.hudRecovery=options.onRecovery;return value.create(options);}};}});
 });
 if(reconnectCase)await context.addInitScript(()=>{
  let source;Object.defineProperty(window,'SessionWorkspace',{configurable:true,get:()=>source,set(value){source={...value,mount(options){const control=value.mount(options);window.workspaceFixture.workspace=control;return control;}};}});
 });
 let selectedAvatarCanvas;const page=await context.newPage();page.on('pageerror',error=>errors.push(String(error)));
 await page.goto(origin+'/?view=conversation&client=standalone',{waitUntil:'load'});
 if(avatarRecord){await page.waitForFunction(()=>document.querySelector('.avatar-surface')?.dataset.avatarState==='custom');selectedAvatarCanvas=await page.locator('.avatar-surface canvas').elementHandle();assert.equal(await page.locator('.avatar-surface canvas').count(),1);report.avatar={id:avatarRecord.id,sha256:avatarRecord.sha256,name:avatarRecord.name,evidence:'Retained selected artwork rendered with synthetic API ownership; no selection/save or hearing claim'};}
 if(process.env.QUALIFICATION_COMPACT_AVATAR_HEADER==='1'){
  await page.waitForFunction(()=>authenticated&&sharedConversationConnected);
  assert.equal(await page.locator('#conversation-presence,.companion-status-track,.companion-caption,.companion-phases').count(),0,'Caption lane and its status/background container are absent');
  for(const [width,height] of [[1280,800],[390,844],[390,420]]){
   await page.setViewportSize({width,height});await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
   const layout=await page.evaluate(()=>{const header=document.querySelector('header'),companion=document.querySelector('#conversation-companion'),frame=companion.querySelector('.avatar-frame');return {header:header.getBoundingClientRect().top,portrait:frame.getBoundingClientRect().top,padding:getComputedStyle(companion).paddingTop,hidden:getComputedStyle(frame).display==='none'};});
   assert.equal(layout.padding,'0px','Avatar reserves no top strip');if(!layout.hidden)assert(Math.abs(layout.portrait-layout.header)<=1,'Avatar starts at the top header edge');
   await page.screenshot({path:path.join(output,`avatar-top-${width}x${height}.png`)});
  }
  assert.equal(posts.length,0);assert.equal(questionPosts,0);assert.equal(errors.length,0);report.state='qualified-no-presence-strip-avatar-top';return;
 }

 async function appearanceTransition(stage){
  if(!appearanceCase)return;
  const snapshot=()=>page.evaluate(()=>{const input=document.querySelector('#conversation-message');return {draft:input.value,start:input.selectionStart,end:input.selectionEnd,focus:document.activeElement.id,files:document.querySelector('#conversation-files-list').innerHTML,target:workspaceFixture.microphone.getReply(),recording:document.querySelector('#conversation-voice-remaining').hidden,contexts:window.countdownFixture?.contexts.length||0};});
  const before=await snapshot();
  for(const palette of [{background:'#090e17',surface:'#111925',text:'#f5f0e6',accent:'#87d7ee'},{background:'#ffffff',surface:'#ffffff',text:'#111111',accent:'#176241'}]){
   await page.evaluate(p=>{for(const [k,v]of Object.entries(p))document.documentElement.style.setProperty('--dm-'+k,v);window.dispatchEvent(new Event('home-style:resolved'));},palette);
   assert.deepEqual(await snapshot(),before,'Appearance preserves controller-owned state during '+stage);
   assert.equal(await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--dm-ui-text').trim()),authoredCase?'':palette.text,'Selected authored policy or inherited roles are respected');
  }
  (report.appearanceTransitions??=[]).push(stage);
 }
 if(unifiedAttentionCase){
  await page.getByRole('button',{name:'For you · 2 pending requests',exact:true}).waitFor();
  assert.equal(await page.locator('.pending-carousel').count(),0,'No rotating pending line remains');
  assert.equal(await page.locator('dialog.pending-panel').count(),1,'All pending sources use one For you panel');
  await page.locator('#conversation-message').fill('Keep my unsent conversation draft.');
  await page.getByRole('button',{name:'For you · 2 pending requests',exact:true}).click();
  const panel=page.getByRole('dialog',{name:'For you',exact:true});
  assert.match(await panel.locator('.for-you-items').textContent(),/Choose a place/);
  assert.match(await panel.locator('.for-you-items>*').first().textContent(),/A routed decision/,'Newer routed pending work precedes older conversation work');
  assert.match(await panel.textContent(),/A routed decision/);
  const internal=panel.locator('.for-you-items button').filter({hasText:'Read request'}).first();
  if(await internal.count())await internal.click();
  await panel.getByRole('button',{name:'Close',exact:true}).click();
  assert.equal(await page.locator('#conversation-message').inputValue(),'Keep my unsent conversation draft.');
  assert.equal(await page.getByRole('button',{name:'For you · 2 pending requests',exact:true}).evaluate(e=>document.activeElement===e),true);
  assert.equal(posts.length,0);assert.equal(questionPosts,0,'Opening pending work never answers it');
  await page.evaluate(()=>{for(const control of pendingFixture)control.reset();});
  await page.getByRole('button',{name:'For you · 0 pending requests',exact:true}).waitFor();
  assert.equal(await page.locator('.for-you-items>*').count(),0,'Account reset removes cards moved from both scoped readers');
  report.state='qualified-unified-for-you';await page.screenshot({path:path.join(output,'for-you-closed.png')});return;
 }
 if(reconnectCase){
  await page.waitForFunction(()=>authenticated&&sharedConversationConnected&&workspaceFixture.workspace?.active);
  await page.evaluate(()=>{clearInterval(timer);liveConversation?.stop();});
  for(const size of [{width:390,height:844},{width:375,height:430}]){
   await page.setViewportSize(size);await page.locator('#conversation-message').fill('Keep this draft across a normal reconnection.');
   const baseline=await page.locator('#conversation-message').boundingBox();
   workspaceOutage=true;await page.evaluate(b=>workspaceFixture.workspace.refresh(b),'a'.repeat(64));
   assert.equal(await page.locator('.session-workspace-status').textContent(),'');
   assert.equal(await page.getByRole('button',{name:'Retry session status',exact:true}).isVisible(),false);
   workspaceOutage=false;await page.evaluate(b=>workspaceFixture.workspace.refresh(b),'a'.repeat(64));
   workspaceOutage=true;await page.evaluate(b=>workspaceFixture.workspace.refresh(b),'a'.repeat(64));
   await page.waitForTimeout(8150);
   const notice=page.locator('#conversation-compose-notices');
   assert.equal(await notice.isVisible(),true,'Persistent failure uses the existing notice icon');
   assert.equal(await page.getByRole('button',{name:'Retry session status',exact:true}).isVisible(),false,'Failure text stays folded in the notice panel');
   await notice.locator(':scope>summary').click();
   await page.getByRole('button',{name:'Retry session status',exact:true}).waitFor({state:'visible'});
   const status=page.locator('.session-workspace-status');
   assert.equal(await status.evaluate(e=>!!e.closest('.composer-notice-panel')),true);
   assert.deepEqual(await page.locator('#conversation-message').boundingBox(),baseline,'Notice never moves or resizes the writing field');
   await page.screenshot({path:path.join(output,'persistent-status-'+size.height+'.png')});
   workspaceOutage=false;await page.evaluate(b=>workspaceFixture.workspace.refresh(b),'a'.repeat(64));
   assert.equal(await status.textContent(),'');assert.equal(await notice.isVisible(),false);
   assert.equal(await page.locator('#conversation-message').inputValue(),'Keep this draft across a normal reconnection.');
   // An open empty notice is harmless, but reset it for the next viewport.
   await notice.evaluate(e=>e.open=false);
  }
  assert.equal(posts.length,0);assert.equal(voiceUploads.length,0);assert.deepEqual(errors,[]);
  report.state='qualified-quiet-reconnect-persistent-status-popover';report.notice_grace_ms=8000;report.viewports=['390x844','375x430'];return;
 }
 if(appearanceCase){
  await page.waitForFunction(()=>authenticated&&sharedConversationConnected);
  await page.locator('#conversation-message').fill('A draft and attachment kept while appearance changes.');
  await page.locator('#conversation-visual>summary').click();
  await page.locator('#conversation-files').setInputFiles({name:'appearance-fixture.txt',mimeType:'text/plain',buffer:Buffer.from('An offline synthetic file, never uploaded.')});
  await page.locator('#conversation-files-list button[aria-label="Remove appearance-fixture.txt"]').waitFor({state:'attached'});
  await appearanceTransition('draft and prepared original file');
  // File preparation is qualified without an upload. The separate recorder
  // fixture has no file-upload API and must start with no selected attachment.
  if(countdownCase)await page.locator('#conversation-files-list button[aria-label="Remove appearance-fixture.txt"]').click();
  await page.locator('#conversation-visual>summary').click();
 }
 if(nativeDecisionCase){
  assert(['allowed','limited'].includes(nativeDecisionCase));
  await page.waitForFunction(()=>authenticated&&sharedConversationConnected);
  await page.setViewportSize({width:320,height:740});
  await page.locator('#conversation-message').fill('Keep my draft while I review this decision.');
  await page.getByRole('button',{name:'For you · 1 pending requests',exact:true}).click();
  const panel=page.getByRole('dialog',{name:'For you',exact:true});
  await panel.getByRole('button',{name:'Read request',exact:true}).click();
  await panel.getByText('Allow this synthetic tool operation once?',{exact:true}).waitFor();
  const approve=panel.getByRole('button',{name:'Allow once',exact:true,includeHidden:true});
  if(nativeDecisionGranted){
   assert(await approve.isEnabled());nativeDecisionGranted=false;
   await page.waitForFunction(()=>!document.querySelector('#conversation-refresh').disabled);await page.locator('#conversation-refresh').evaluate(node=>node.click());
   await page.waitForFunction(()=>[...document.querySelectorAll('#conversation-request-cards button')].find(v=>v.textContent==='Allow once')?.disabled===true);
   nativeDecisionGranted=true;await page.waitForFunction(()=>!document.querySelector('#conversation-refresh').disabled);await page.locator('#conversation-refresh').evaluate(node=>node.click());
   await approve.waitFor({state:'visible'});await page.waitForFunction(()=>[...document.querySelectorAll('#conversation-request-cards button')].find(v=>v.textContent==='Allow once')?.disabled===false);
   await approve.click();await page.waitForFunction(()=>document.body.textContent.includes('Decision recorded. Work may continue.'));
   assert.deepEqual(nativeDecisionPosts,[{binding,revision:'d'.repeat(64),action:{kind:'approval',choice:'a'}}]);
  }else{
   assert.equal(await approve.isVisible(),false);assert.equal(await panel.getByRole('button',{name:'Cancel this turn',exact:true}).isVisible(),false);
   assert.equal(nativeDecisionPosts.length,0);
  }
  await page.screenshot({path:path.join(output,'home-decisions-320.png')});
  if(await panel.isVisible())await panel.getByRole('button',{name:'Close',exact:true}).click();
  assert.equal(await page.locator('#conversation-message').inputValue(),'Keep my draft while I review this decision.');assert.equal(posts.length,0);assert.equal(errors.length,0,errors.join('\n'));
  report.state='qualified-shared-home-decision-'+nativeDecisionCase;report.decisions=nativeDecisionPosts;report.existingDraft='preserved';return;
 }
 if(publicDefaultCase){
  await page.waitForFunction(()=>authenticated&&sharedConversationConnected);
  await page.evaluate(()=>clearInterval(timer));
  const engine=page.locator('#conversation-voice-engine'),draft=page.locator('#conversation-message');
  assert.equal(await engine.inputValue(),'gpt-live-native','Explicit native Avatar default does not require another TTS route');
  await draft.fill('Preserve my draft when I choose a voice mode.');
  await engine.evaluate(el=>{el.value='provider';el.dispatchEvent(new Event('change'));});
  await page.evaluate(()=>conversationView.refresh());
  assert.equal(await engine.inputValue(),'provider','A later refresh cannot replace the selected page mode');
  assert.equal(await draft.inputValue(),'Preserve my draft when I choose a voice mode.');
  assert.equal(posts.length,0);assert.equal(voiceUploads.length,0);assert.equal(errors.length,0,errors.join('\n'));
  report.state='qualified-explicit-native-avatar-default';return;
 }
 if(imageCase){
  await page.waitForFunction(()=>authenticated&&sharedConversationConnected);await page.evaluate(()=>clearInterval(timer));
  await page.setViewportSize({width:320,height:640});await page.locator('#conversation-message').fill('Keep this draft while viewing the image.');
  await page.getByRole('button',{name:'View image',exact:true}).click();
  const image=page.locator('.artifact-image-preview');await image.waitFor();await image.evaluate(el=>el.decode());
  assert.equal(await image.evaluate(el=>el.naturalWidth),1);assert.equal(await image.getAttribute('alt'),'drawing.png');
  const rect=await image.boundingBox();assert(rect.x>=0&&rect.x+rect.width<=320);
  assert.equal(await page.locator('#conversation-message').inputValue(),'Keep this draft while viewing the image.');
  await page.screenshot({path:path.join(output,'conversation-image-320.png')});
  imageAccess=false;await page.evaluate(()=>conversationView.refresh());assert.equal(await image.count(),0);
  assert.equal(posts.length,0);assert.equal(voiceUploads.length,0);assert.equal(errors.length,0,errors.join('\n'));
  report.state='qualified-hash-verified-image-in-original-reply';report.draft='preserved';report.grant_revocation='preview_removed';return;
 }
 if(process.env.QUALIFICATION_REPLY==='1'){
  await page.waitForFunction(()=>authenticated&&sharedConversationConnected);
  await page.evaluate(()=>clearInterval(timer));
  const draft=page.locator('#conversation-message'),focus=page.locator('#conversation-focus');
  await draft.fill('Preserve this draft while replying.');
  await page.getByRole('button',{name:'Reply to this message',exact:true}).first().click();
  await focus.waitFor({state:'visible'});
  const reference=await page.evaluate(()=>workspaceFixture.microphone.getReply());
  assert(reference?.reference?.source,'Reply retains its actual source');
  report.replyGeometry=[];
  await page.addStyleTag({content:"*,*::before,*::after{transition:none!important;animation:none!important}"});
  for(const [width,height] of [[390,430],[320,450],[390,844],[1280,800]]){
   await page.setViewportSize({width,height});await draft.focus();await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   const context=await focus.boundingBox(),input=await draft.boundingBox(),send=await page.locator('#conversation-send').boundingBox();
   assert(context.height<=48,'Reply context keeps a single touch-sized row above the writing field');
   assert(context.y+context.height<=input.y+1,'Reply context must end above the writing field');
   assert(input.y+input.height<=send.y+1,'Writing field must end above composer actions: '+JSON.stringify({context,input,send}));
   assert(input.x>=0&&input.x+input.width<=width&&send.y+send.height<=height,'Composer stays inside the keyboard-sized viewport: '+JSON.stringify({width,height,input,send}));
   assert.equal(await draft.inputValue(),'Preserve this draft while replying.');
   assert.deepEqual(await page.evaluate(()=>workspaceFixture.microphone.getReply()),reference);
   report.replyGeometry.push({width,height,context,input,send});
   await page.screenshot({path:path.join(output,`reply-${width}x${height}.png`)});
  }
  await page.locator('#conversation-focus-clear').click();
  assert.equal(await draft.inputValue(),'Preserve this draft while replying.');
  assert.equal(await page.evaluate(()=>workspaceFixture.microphone.getReply()),undefined);
  await draft.evaluate(input=>input.setSelectionRange(4,9));
  await page.evaluate(binding=>workspaceFixture.microphone.onTranscript({id:'synthetic-preview',binding,active:true,text:'Palabras de la captura en curso'}),binding);
  assert.equal(await draft.inputValue(),'Palabras de la captura en curso');assert(await draft.evaluate(input=>input.readOnly));
  await page.evaluate(binding=>workspaceFixture.microphone.onTranscript({id:'synthetic-preview',binding,active:false}),binding);
  assert.equal(await draft.inputValue(),'Preserve this draft while replying.');
  assert.deepEqual(await draft.evaluate(input=>[input.selectionStart,input.selectionEnd,input.readOnly]),[4,9,false]);
  assert.equal(posts.length,0);assert.equal(voiceUploads.length,0);assert.equal(errors.length,0,errors.join('\n'));
  report.state='qualified-reply-composer-layout';return;
 }
 if(hudCase){
  await page.waitForFunction(()=>authenticated&&sharedConversationConnected);
  assert.equal(await page.locator('#client-build').isVisible(),false,'Build diagnostics stay out of the ordinary conversation');
  await page.evaluate(()=>clearInterval(timer));
  await page.locator('#conversation-message').fill('Explore this idea together.');
  await page.waitForFunction(()=>typeof hudRecovery==='function');
  const composerBeforeRecovery=await page.locator('#conversation-compose').boundingBox();
  await page.evaluate(binding=>hudRecovery(Array.from({length:3},(_,ordinal)=>({binding,ordinal,voice_visit:'11111111-1111-4111-8111-111111111111',blob:new Blob([new Uint8Array(32044)],{type:'audio/wav'})}))),binding);
  assert.equal((await page.locator('#conversation-compose').boundingBox()).height,composerBeforeRecovery.height,'Three retained recordings cannot expand the input');
  assert.equal(await page.locator('#conversation-compose>#conversation-public-live-recovery').count(),0,'Recovery belongs inside the shared notice popover');
  const layouts=[];
  for(const [width,height] of [[375,812],[320,740],[430,932],[1280,800],[375,430]]){
   await page.setViewportSize({width,height});await page.waitForTimeout(120);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'No horizontal overflow at '+width);
   for(const selector of ['#conversation-message','#conversation-send','#conversation-visual>summary']){
    const box=await page.locator(selector).boundingBox();assert(box&&box.width>0&&box.x>=0&&box.x+box.width<=width,selector+' is reachable at '+width);
    assert(box.y>=0&&box.y+box.height<=height,selector+' fits keyboard viewport');
   }
   await page.locator('#conversation-message').focus();
   assert(await page.locator('#conversation-message').evaluate(el=>{const s=getComputedStyle(el);return s.outlineStyle!=='none'||s.boxShadow!=='none';}),'Writing focus has a visible indicator');
   await page.locator('#conversation-visual>summary').click();
   assert(await page.locator('#conversation-attachment-sheet').isVisible(),'Attachments stay available');
   await page.locator('#conversation-visual>summary').click();
   const inputBefore=await page.locator('#conversation-message').boundingBox(),composeBefore=await page.locator('#conversation-compose').boundingBox();
   assert(inputBefore.width>=composeBefore.width-32,'The writing line spans the composer instead of sitting between attachment and microphone');
   const attachment=await page.locator('#conversation-visual>summary').boundingBox();
   assert(attachment.y>=inputBefore.y+inputBefore.height-1,'Attachment controls sit below the writing line');
   const toolbar=await page.locator('#conversation-compose-bar>.session-workspace-toolbar').boundingBox();
   const notice=await page.locator('#conversation-compose-bar>#conversation-compose-notices').boundingBox();
   assert(toolbar&&notice&&Math.abs((toolbar.y+toolbar.height/2)-(notice.y+notice.height/2))<2,'Sessions, destination and notices share one row');
   assert(toolbar.y+toolbar.height<=composeBefore.y,'The destination row sits above the input');
   const menu=page.getByRole('button',{name:'Show sessions',exact:true});
   await menu.click();assert(await page.getByRole('complementary',{name:'Your sessions'}).isVisible());
   await page.getByRole('button',{name:'Hide sessions',exact:true}).click();

   await page.evaluate(()=>{const message=document.querySelector('#conversation-send-state');message.dataset.attention='true';message.textContent='A retained recording needs review. '.repeat(18);});
   const notices=page.locator('#conversation-compose-notices');
   assert(await notices.locator(':scope>summary').isVisible(),'A minimal notice indicator is available');
   assert.equal((await page.locator('#conversation-compose').boundingBox()).height,composeBefore.height,'Long notices never expand the composer');
   assert.equal((await page.locator('#conversation-message').boundingBox()).height,inputBefore.height);
   await notices.locator(':scope>summary').click();
   const recovery=page.locator('#conversation-public-live-recovery');
   assert(await recovery.getByText('3 audio copies to review',{exact:true}).isVisible());
   if(!await recovery.evaluate(el=>el.open))await recovery.locator(':scope>summary').click();
   assert(await recovery.getByRole('button',{name:'Download copy',exact:true}).first().isVisible());
   assert(await recovery.getByText(/This does not repeat your messages/).isVisible());
   const popup=await notices.locator('.composer-notice-panel').boundingBox();
   assert(popup&&popup.y+popup.height<=inputBefore.y,'Notice opens upward outside the text input');
   assert(popup.x>=0&&popup.x+popup.width<=width,'Notice fits the phone viewport');
   assert.equal(await page.locator('#conversation-message').inputValue(),'Explore this idea together.');
   await page.screenshot({path:path.join(output,`hud-notice-${width}-${height}.png`)});
   await notices.locator(':scope>summary').click();
   await page.evaluate(()=>{const message=document.querySelector('#conversation-send-state');message.textContent='';delete message.dataset.attention;});
   await page.screenshot({path:path.join(output,`hud-${width}-${height}.png`)});
   if(width===375&&height===812){
    const inspect=page.getByRole('button',{name:'Under the hood',exact:true});
    await inspect.click();assert(await page.getByRole('region',{name:'Under the hood',exact:true}).isVisible());
    assert(await page.locator('#client-build').isVisible(),'Client version remains available in the explicit technical area');
    await page.screenshot({path:path.join(output,'hud-inspector.png')});await inspect.click();
    assert.equal(await page.locator('#client-build').isVisible(),false,'Closing technical details removes build diagnostics from view');
    await page.getByRole('button',{name:/^Open alerts/}).click();
    const alerts=await page.locator('#operations').boundingBox();
    assert(alerts&&alerts.x>=0&&alerts.x+alerts.width<=width&&alerts.y+alerts.height<=height,'Alerts panel fits the phone');
    await page.screenshot({path:path.join(output,'hud-alerts.png')});await page.locator('#conversation-alerts-close').click();
   }
   layouts.push({width,height});
  }
  assert.equal(await page.locator('#conversation-message').inputValue(),'Explore this idea together.');
  assert.equal(posts.length,0);assert.equal(voiceUploads.length,0);
  report.state='qualified-authored-hud-layouts';report.layouts=layouts;return;
 }
 if(countdownCase){
  page.on('dialog',dialog=>dialog.accept());
  await page.waitForFunction(()=>authenticated&&sharedConversationConnected);
  await page.locator('#conversation-talk').click();
  await page.locator('#conversation-voice-remaining').waitFor({state:'visible'});
  await appearanceTransition('active bounded synthetic recording');
  if(authoredCase){
   await page.setViewportSize({width:320,height:740});
   for(const selector of ['#conversation-send','#conversation-voice-discard','#conversation-voice-remaining']){
    const box=await page.locator(selector).boundingBox();assert(box&&box.x>=0&&box.x+box.width<=320,selector+' remains visible while recording');
   }
   await page.screenshot({path:path.join(output,'hud-recording.png')});
  }
  for(const offset of [110000,115000,117000,118000,119000]){
   await page.evaluate(value=>{window.countdownFixture.offset=value;},offset);
   await page.waitForTimeout(1050);
  }
  const measured=await page.evaluate(()=>({tones:window.countdownFixture.tones,peak:window.countdownFixture.peak}));
  assert.deepEqual(measured.tones,[808,1010,1212,1212,1212]);assert(measured.peak>0,'The actual WebAudio graph emits a nonzero warning signal');
  await page.locator('#conversation-voice-discard').click();
  await page.waitForFunction(()=>window.countdownFixture.contexts.every(c=>c.state==='closed'));
  assert.equal(posts.length,0);assert.equal(voiceUploads.length,0);
  report.state='qualified-recording-countdown-cues';report.measured=measured;return;
 }
 if(authCase){
  await page.locator('#conversation-message').fill('Keep my unsent draft.');
  await page.waitForFunction(()=>authenticated && sharedConversationConnected);
  await page.evaluate(()=>clearInterval(timer));
  const before=accessReads;readRejections=1;
  await page.evaluate(()=>api('interaction?qualification=auth'));
  assert(accessReads>before,'A rejected read revalidates the existing session');
  assert.equal(await page.locator('#feedback').innerText(),'');
  assert.equal(await page.locator('#conversation-message').inputValue(),'Keep my unsent draft.');
  readRejections=2;assert.equal(await page.evaluate(()=>api('interaction?qualification=auth').catch(e=>e.status)),503);
  assert.equal(await page.locator('#feedback').innerText(),'','A scoped rejection with valid identity cannot sign out the whole app');
  authDenied=true;readRejections=1;await page.evaluate(()=>api('interaction?qualification=auth').catch(()=>conversationView.unauthenticated()));
  await page.getByRole('button',{name:'Sign in',exact:true}).waitFor();
  authDenied=false;await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
  await page.waitForFunction(()=>!document.querySelector('#feedback').textContent);
  assert.equal(await page.locator('#conversation-message').inputValue(),'Keep my unsent draft.');
  assert.equal(posts.length,0);assert.equal(voiceUploads.length,0);
  writeRejected=true;const beforeWrite=accessReads;
  assert.equal(await page.evaluate(()=>api('interaction/inputs',{id:'once',text:'Only one write'}).catch(e=>e.status)),401);
  assert.equal(posts.length,1);assert.equal(accessReads,beforeWrite,'Writes are never repeated or silently reauthenticated');
  report.state='qualified-shared-session-recovery';report.accessReads=accessReads;return;
 }

 await page.locator('.session-workspace-toolbar').waitFor({state:'visible',timeout:12000});
 assert.equal(await page.locator('#conversation-compose #conversation-voice-engine').count(),0,'Voice engine is not an ordinary composer control');
 assert.equal(await page.locator('#conversation-diagnostics #conversation-voice-engine').count(),1,'Development voice selection lives under the hood');
 async function selectEngine(value){
  await page.getByRole('button',{name:'Under the hood',exact:true}).click();
  await page.locator('#conversation-voice-engine').selectOption(value);
  await page.getByRole('button',{name:'Under the hood',exact:true}).click();
 }

 if(avatarSpeechCase){
  assert(avatarRecord?.design?.avatarModel?.nodes.some(n=>n.id==='anchor-mouth'),'Use the retained selected mouth-enabled artwork');
  await page.setViewportSize({width:390,height:844});
  await page.locator('#conversation-message').fill('Keep this draft while the avatar speaks.');
  await selectEngine(publicCase?'gpt-live':'codex');await page.locator(avatarEntrySelector).click();
  await page.waitForFunction(()=>document.querySelector('.voice-mode-state').textContent==='Listening');
  await page.waitForFunction(()=>codexFixture.outputLevels?.at(-1)>0);
  assert(await page.evaluate(()=>avatarSpeechLevels.some(v=>v.level>0&&v.changed)),'Decoded playback must reach and repaint the selected mouth-enabled avatar');
  await page.evaluate(()=>{codexFixture.remoteOutput.gain.gain.value=0;});await page.waitForFunction(()=>codexFixture.outputLevels.at(-1)===0);
  assert.equal(await page.evaluate(()=>avatarSpeechLevels.at(-1)?.level),0,'Remote silence restores the selected jaw');
  await page.evaluate(()=>{codexFixture.remoteOutput.gain.gain.value=.12;});await page.waitForFunction(()=>codexFixture.outputLevels.at(-1)>0);
  await page.evaluate(()=>codexFixture.engine.pause());assert.equal(await page.evaluate(()=>avatarSpeechLevels.at(-1)?.level),0,'Paused output cannot move the jaw');
  await page.evaluate(()=>codexFixture.engine.resume());await page.waitForFunction(()=>codexFixture.outputLevels.at(-1)>0);
  await page.getByRole('button',{name:'Back to conversation',exact:true}).click();
  await page.waitForFunction(()=>!codexFixture.engine.active&&codexFixture.contexts.every(c=>c.state==='closed'));
  assert.equal(await page.evaluate(()=>avatarSpeechLevels.at(-1)?.level),0,'Leaving Avatar clears live mouth activity');
  assert.equal(await page.locator('#conversation-message').inputValue(),'Keep this draft while the avatar speaks.');
  assert.equal(await page.evaluate(()=>codexFixture.opens),1);assert.equal(posts.length,0);assert.equal(errors.length,0,errors.join('\n'));
  report.state='qualified-decoded-output-to-selected-avatar';report.engine=publicCase?'gpt-live':'codex';report.output='Synthetic660Hz remote track through actual decoded-output worklet, engine state, mounted Conversation and same selected Canvas; silence/pause/exit restore zero. Amplitude animation only, no phoneme or physical hearing proof.';return;
 }

 if(publicCase){
  await page.locator('#conversation-timeline').getByText('Una corrección guardada.',{exact:true}).waitFor();
  assert.equal(await page.locator('#conversation-timeline .timeline-history').count(),0,'Voice history tools do not occupy the current reading area');
  await page.getByRole('button',{name:'Under the hood',exact:true}).click();
  await page.getByRole('button',{name:'Earlier voice conversation',exact:true}).click();
  await page.getByRole('button',{name:'Under the hood',exact:true}).click();
  await page.locator('#conversation-timeline').getByText('Una respuesta anterior.',{exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>codexFixture.opens),0,'Reading source history never opens voice');
  assert.equal(await page.locator('#conversation-voice-engine').inputValue(),'provider','Public Live never replaces the default');
  await page.locator('#conversation-message').fill('Keep this draft while I compare voices.');
  await selectEngine('gpt-live');await page.locator(avatarEntrySelector).click();
  await page.waitForFunction(()=>document.querySelector('.voice-mode-state').textContent==='Listening');
  assert(await page.locator('#conversation-voice-engine').isDisabled());
  await page.locator('#conversation-voice-engine').evaluate(select=>{select.value='provider';select.dispatchEvent(new Event('change'));});
  assert.equal(await page.locator('#conversation-voice-engine').inputValue(),'gpt-live','A running public visit is frozen');
  await page.waitForFunction(()=>codexFixture.captureBytes>64000);
  await page.screenshot({path:path.join(output,'public-live-desktop.png')});
  if(avatarRecord){
   report.avatar.layouts=[];
   for(const [width,height] of [[390,844],[320,450]]){
    await page.setViewportSize({width,height});
    const layout=await page.evaluate(()=>{
     const box=selector=>{const r=document.querySelector(selector).getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
     return {portrait:box('.voice-mode-portrait'),canvas:box('.voice-mode-portrait canvas'),status:box('.voice-mode-state'),controls:box('.voice-mode-controls'),viewport:{width:innerWidth,height:innerHeight}};
    });
    assert(layout.canvas.width>0&&layout.canvas.height>0);assert(layout.portrait.bottom<=layout.status.top+1);assert(layout.controls.bottom<=height+1);assert(layout.controls.left>=0&&layout.controls.right<=width+1);
    assert.equal(await page.locator('.voice-mode canvas').count(),1,'Same selected canvas enters full-screen voice');
    assert(await selectedAvatarCanvas.evaluate(c=>document.querySelector('.voice-mode canvas')===c));report.avatar.layouts.push(layout);
    await page.screenshot({path:path.join(output,`public-live-selected-${width}x${height}.png`)});
   }
  }
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('button',{name:'Back to conversation',exact:true}).click();
  await page.waitForFunction(()=>codexFixture.contexts.every(ctx=>ctx.state==='closed')&&codexFixture.peers.every(peer=>peer.connectionState==='closed'));
  await page.locator('#conversation-timeline').getByText('Conservo tu corrección.',{exact:true}).waitFor();
  assert.equal(await page.locator('#conversation-message').inputValue(),'Keep this draft while I compare voices.');
  if(avatarRecord){assert.equal(await page.locator('#conversation-companion .avatar-surface canvas').count(),1,'Back restores the same selected artwork');assert(await selectedAvatarCanvas.evaluate(c=>document.querySelector('#conversation-companion canvas')===c));}
  await page.locator('#conversation-compose-notices>summary').click();const panel=page.locator('#conversation-public-live-recovery');await panel.waitFor({state:'visible'});await panel.locator('summary').click();
  await page.screenshot({path:path.join(output,'public-live-mobile-recovery.png')});
  await panel.getByRole('button',{name:'Try saving audio',exact:true}).click();await panel.waitFor({state:'hidden'});
  assert.equal(voiceUploads.length,2);assert.deepEqual(voiceUploads[0],voiceUploads[1],'Public original retry preserves exact bytes and visit');
  assert.equal(posts.length,0,'Public media and original recovery never submit ordinary native work');
  assert.equal(await page.evaluate(()=>codexFixture.opens),1);
  report.state='qualified-public-live-synthetic-browser';report.voiceUploads=voiceUploads;report.ordinaryInputs=posts.length;
  report.viewports=avatarRecord?['1280x800','390x844','320x450']:['1280x800','390x844'];
 }else if(codexCase&&reloadCase){
  await selectEngine('codex');await page.locator(avatarEntrySelector).click();
  await page.waitForFunction(()=>document.querySelector('.voice-mode-state').textContent==='Listening');await page.waitForTimeout(3500);
  const before=await page.evaluate(()=>codexFixture.captureBytes);assert(before>32000);
  const locked=await page.evaluate(async()=>{const row=(await VoiceInput.recoveryStore('codex_voice').list())[0];return navigator.locks.request('daimon-native-voice:'+row.codex_visit,{ifAvailable:true},lock=>lock===null);});
  assert(locked,'The real browser lock remains held while microphone capture owns its fragments');
  assert.equal(voiceUploads.length,0,'Only local fragments persist before normal original sealing');
  await page.reload({waitUntil:'load'});await page.locator('.session-workspace-toolbar').waitFor({state:'visible'});
  await page.locator('#conversation-compose-notices>summary').click();const panel=page.locator('#conversation-codex-recovery');await panel.waitFor({state:'visible'});await panel.locator('summary').click();
  await page.getByText(/Recovered audio prefix/).waitFor({state:'visible'});
  assert.equal(await page.evaluate(()=>codexFixture.opens),0,'Reload does not reopen the microphone');
  const recovered=await page.evaluate(async()=>{const rows=await VoiceInput.recoveryStore('codex_voice').list();return {count:rows.length,bytes:rows.reduce((n,v)=>n+v.blob.size-44,0),fragments:rows.every(v=>v.native_fragment===true)};});
  assert(recovered.fragments&&recovered.bytes>=32000&&recovered.bytes<=before,'Retain the exact committed prefix, never claim a missing tail');
  assert(await page.evaluate(async()=>{const row=(await VoiceInput.recoveryStore('codex_voice').list())[0];return navigator.locks.request('daimon-native-voice:'+row.codex_visit,{ifAvailable:true},lock=>!!lock);}), 'Reload releases the old page capture lock');
  await panel.getByRole('button',{name:'Try saving audio',exact:true}).click();
  await page.getByText(/Recovered audio prefix not confirmed/).waitFor();
  assert.equal(voiceUploads.length,0,'Old backend capability refuses prefix upload before any external write');
  prefixSupport=true;await panel.getByRole('button',{name:'Try saving audio',exact:true}).click();
  await page.getByText(/Recovered audio prefix not confirmed/).waitFor();
  await page.waitForFunction(async()=>{const v=await VoiceInput.recoveryStore('codex_voice').list();return v.length===1&&v[0].captureStop==='interrupted_prefix'&&!v[0].native_fragment;});
  await panel.getByRole('button',{name:'Try saving audio',exact:true}).click();await panel.waitFor({state:'hidden'});
  assert.equal(voiceUploads.length,2);assert.deepEqual(voiceUploads[0],voiceUploads[1],'Explicit retry saves identical prefix bytes/visit/ordinal');
  assert.equal(posts.length,0);assert.equal(await page.evaluate(()=>codexFixture.opens),0);
  report.state='qualified-native-reload-prefix-recovery';report.beforePCM=before;report.recovered=recovered;report.voiceUploads=voiceUploads;report.ordinaryInputs=posts.length;
 }else if(codexCase){
  await page.getByRole('button',{name:'Under the hood',exact:true}).click();
  await page.locator('#conversation-voice-choice').waitFor({state:'visible'});
  await page.getByRole('button',{name:'Under the hood',exact:true}).click();
  assert.equal(await page.locator('#conversation-voice-engine').inputValue(),'provider','OpenAI never replaces the default');
  assert.equal(await page.evaluate(()=>codexFixture.opens),0);
  await page.locator('#conversation-message').fill('My draft survives voice history reading.');
  await page.screenshot({path:path.join(output,'codex-history-desktop.png')});
  assert.equal(await page.locator('#conversation-timeline .timeline-history').count(),0,'Voice history tools do not occupy the current reading area');
  await page.getByRole('button',{name:'Under the hood',exact:true}).click();
  await page.getByRole('button',{name:'Earlier voice conversation',exact:true}).click();
  await page.getByRole('button',{name:'Under the hood',exact:true}).click();
  await page.getByText('Earlier retained voice source 1',{exact:true}).waitFor({state:'visible'});
  assert.equal(await page.getByRole('button',{name:'Earlier voice conversation',exact:true}).isVisible(),false);
  assert.equal(await page.evaluate(()=>codexFixture.opens),0,'History reading opens no voice connection');
  assert.equal(posts.length,0,'History reading admits no new input');
  assert.equal(await page.locator('#conversation-message').inputValue(),'My draft survives voice history reading.');
  await page.locator('#conversation-message').fill('');
  await page.locator('#conversation-message').fill('My unsent draft stays while I review the question.');
  await selectEngine('codex');
  await page.locator(avatarEntrySelector).click();
  await page.waitForFunction(()=>document.querySelector('.voice-mode-state').textContent==='Listening',null,{timeout:10000});
  if(codexActivityCase){
   await page.waitForFunction(()=>codexFixture.outputLevels?.at(-1)>0);
   await page.evaluate(()=>{codexFixture.remoteOutput.gain.gain.value=0;});await page.waitForFunction(()=>codexFixture.outputLevels.at(-1)===0);
   assert(await page.evaluate(()=>codexFixture.captureBytes>0),'Input capture remains active while silent remote output leaves the mouth still');
   await page.evaluate(()=>{codexFixture.remoteOutput.gain.gain.value=.12;});await page.waitForFunction(()=>codexFixture.outputLevels.at(-1)>0);
   await page.evaluate(()=>codexFixture.engine.pause());await page.waitForFunction(()=>codexFixture.outputLevels.at(-1)===0);
   await page.evaluate(()=>codexFixture.engine.resume());await page.waitForFunction(()=>codexFixture.outputLevels.at(-1)>0);
   report.remoteOutputActivity='Actual660Hz remote track → existing outputless worklet → native engine state; silence and pause suppress while input capture continues';
  }

  assert(await page.locator('#conversation-voice-engine').isDisabled());
  await page.locator('#conversation-voice-engine').evaluate(select=>{select.value='provider';select.dispatchEvent(new Event('change'));});
  assert.equal(await page.locator('#conversation-voice-engine').inputValue(),'codex','Active mode stays frozen');
  await page.screenshot({path:path.join(output,'codex-desktop-voice.png')});
  pendingQuestion=true;await page.evaluate(()=>document.querySelector('#conversation-refresh').click());
  const voiceReview=page.locator('.voice-mode').getByRole('button',{name:'For you · 1 pending requests',exact:true});
  await voiceReview.waitFor({state:'visible'});await voiceReview.click();
  const pendingPanel=page.getByRole('dialog',{name:'For you',exact:true});await pendingPanel.waitFor({state:'visible'});
  await pendingPanel.getByRole('button',{name:'Read request',exact:true}).click();
  await pendingPanel.getByText('Where should we meet: in the garden or in the workshop?',{exact:true}).waitFor();
  assert(await page.locator('.voice-mode').isVisible(),'Review overlays Avatar without closing its microphone');
  assert.equal(await page.evaluate(()=>codexFixture.peers.every(peer=>peer.connectionState==='connected')),true);
  assert.equal(posts.length,0);assert.equal(questionPosts,0,'Review is not an approval or answer');
  await page.screenshot({path:path.join(output,'codex-desktop-attention.png')});
  await pendingPanel.getByRole('button',{name:'Close',exact:true}).click();
  assert(await voiceReview.evaluate(button=>button===document.activeElement),'Closing review returns keyboard focus to Avatar');

  await page.setViewportSize({width:390,height:844});await page.waitForTimeout(450);
  await page.screenshot({path:path.join(output,'codex-mobile-voice.png')});
  await voiceReview.click();
  await pendingPanel.getByRole('button',{name:'Answer in conversation',exact:true}).waitFor({state:'visible'});
  await page.screenshot({path:path.join(output,'codex-mobile-attention.png')});
  if(listenCase){
   assert.equal(await page.evaluate(()=>codexFixture.audioRequests),0,'No ordinary question audio starts over active native voice');
   await pendingPanel.getByRole('button',{name:'Listen to question',exact:true}).click();
   await page.waitForFunction(()=>codexFixture.audioRequests===1);
   assert.equal(await page.evaluate(()=>codexFixture.audioRequestedWhileNativeOpen),false,'Explicit question reading must wait for native media closure');
   assert.equal(await page.locator('.voice-mode').isVisible(),false);
  }
  await pendingPanel.getByRole('button',{name:'Answer in conversation',exact:true}).click();
  assert.equal(await page.locator('.voice-mode').isVisible(),false,'Explicit written reply returns from Avatar');
  assert.equal(await page.locator('#conversation-message').inputValue(),'My unsent draft stays while I review the question.');
  assert.equal(await page.evaluate(()=>workspaceFixture.microphone.getReply().reference.source),'request:'+'9'.repeat(32));
  assert.equal(await page.evaluate(()=>workspaceFixture.microphone.getReply().reference.revision),'d'.repeat(64));
  assert.equal(posts.length,0);assert.equal(questionPosts,0,'Choosing a written reply still requires explicit Send');

  await page.waitForFunction(()=>codexFixture.contexts.every(ctx=>ctx.state==='closed')&&codexFixture.peers.every(peer=>peer.connectionState==='closed'),null,{timeout:10000});
  await page.locator('#conversation-compose-notices>summary').click();
  await page.locator('#conversation-codex-recovery').waitFor({state:'visible'});
  await page.locator('#conversation-codex-recovery summary').click();
  await page.screenshot({path:path.join(output,'codex-mobile-recovery.png')});
  await page.getByRole('button',{name:'Try saving audio',exact:true}).click();
  await page.locator('#conversation-codex-recovery').waitFor({state:'hidden'});
  assert.equal(voiceUploads.length,2);assert.deepEqual(voiceUploads[0],voiceUploads[1],'Retry retains the exact original and visit');
  assert.equal(posts.length,0,'Native original recovery never uses ordinary Send');
  assert.equal(await page.evaluate(()=>codexFixture.opens),1,'Recovery does not reopen or replay voice');
  assert.equal(await page.evaluate(()=>new Promise((resolve,reject)=>{const r=indexedDB.open('daimon-voice-recovery',1);r.onsuccess=()=>{const db=r.result,tx=db.transaction('capture','readonly'),q=tx.objectStore('capture').get('pending');q.onsuccess=()=>{resolve(q.result===undefined);db.close();};q.onerror=reject;};r.onerror=reject;})),true);
  await selectEngine('provider');
  assert.equal(await page.evaluate(()=>codexFixture.opens),1);
  assert.equal(errors.length,0,errors.join('\n'));
  report.state='qualified-codex-synthetic-browser';report.voiceUploads=voiceUploads;report.attention={reviewKeptCapture:true,exactQuestionReply:true,unsentDraftPreserved:true,decisionPosts:questionPosts,...(listenCase?{listenAfterClosure:true}:{} )};report.viewports=['1280x800','390x844'];
 }else{
 assert.equal(await page.getByRole('button',{name:'Show routing map',exact:true}).count(),0,'Messages have no routing-map shortcut');
 await page.getByRole('button',{name:'Under the hood',exact:true}).click();
 await page.locator('#conversation-flow > summary').click();
 assert(await page.locator('#routing-graph-viewport').isVisible(),'Routing map remains under the hood');
 await page.getByRole('button',{name:'Under the hood',exact:true}).click();
 await page.getByRole('button',{name:'Show sessions',exact:true}).click();
 async function bottomMenu(){
  const rect=async selector=>page.locator(selector).evaluate(node=>{const r=node.getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right};});
  const bar=await rect('.session-workspace-toolbar'),body=await rect('.session-workspace-body'),menu=await rect('.session-rail'),input=await rect('#conversation-compose');
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
    assert(authoredCase ? control.width>=44&&control.width<=48&&control.height>=44&&control.height<=48 : control.width>=24&&control.width<=32&&control.height>=24&&control.height<=32,'Controls retain the selected authored touch targets or compact inherited targets');
    if(control.icon)assert(control.icon<=18,'Icons match the small audio-control scale');
    assert(control.label,'Compact icon actions retain accessible names');
   }
  }
 }
 await compactControls();
 // A long menu scrolls its contents while the authored frame remains stationary.
 await page.evaluate(()=>{const list=document.querySelector('.session-rail-scroll');const row=list.querySelector('.session-row');for(let i=0;i<30;i++){const copy=row.cloneNode(true);copy.dataset.backgroundFixture='1';list.append(copy);}});
 const railBackground=await page.evaluate(()=>{const rail=document.querySelector('.session-rail'),scroll=rail.querySelector('.session-rail-scroll');const before=rail.getBoundingClientRect();scroll.scrollTop=scroll.scrollHeight;return {overflow:scroll.scrollHeight>scroll.clientHeight,scrolled:scroll.scrollTop>0,railScroll:rail.scrollTop,height:before.height,after:rail.getBoundingClientRect().height,scrollBottom:scroll.getBoundingClientRect().bottom,railBottom:before.bottom};});
 assert(railBackground.overflow&&railBackground.scrolled,'Long session contents remain scrollable');
 assert.equal(railBackground.railScroll,0,'Panel background never scrolls away from its viewport');
 assert.equal(railBackground.height,railBackground.after,'Scrolling does not resize the frame');
 assert(railBackground.scrollBottom<=railBackground.railBottom,'List stays inside the full background');
 await page.screenshot({path:path.join(output,'sessions-long-background.png')});
 if(process.env.QUALIFICATION_SESSION_BACKGROUND==='1'){
  for(const [width,height] of [[390,844],[390,420],[320,400]]){
   await page.setViewportSize({width,height});await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));await bottomMenu();
   const bounds=await page.locator('.session-rail-scroll').evaluate(n=>{n.scrollTop=n.scrollHeight;const frame=n.parentElement;return {scroll:n.scrollTop,overflow:n.scrollHeight>n.clientHeight,frameScroll:frame.scrollTop,bottom:n.getBoundingClientRect().bottom,frameBottom:frame.getBoundingClientRect().bottom};});
   assert(bounds.overflow&&bounds.scroll>0);assert.equal(bounds.frameScroll,0);assert(bounds.bottom<=bounds.frameBottom);
   await page.screenshot({path:path.join(output,`sessions-long-${width}x${height}.png`)});
  }
  assert.equal(posts.length,0);assert.equal(errors.length,0);report.state='qualified-long-session-background';return;
 }
 await page.evaluate(()=>{document.querySelectorAll('[data-background-fixture]').forEach(n=>n.remove());document.querySelector('.session-rail-scroll').scrollTop=0;});
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
 assert.deepEqual(await page.locator('.session-name').allTextContents(),['Daimon',sessions[1].title,sessions[0].title]);
 await page.locator('.session-row').filter({has:page.getByRole('button',{name:sessions[0].title,exact:true})}).getByRole('button',{name:'Pin as the input destination',exact:true}).click();
 assert.equal(await page.locator('.session-rail').isVisible(),false,'Pin collapses the menu');
 assert(await page.getByRole('button',{name:'Show sessions',exact:true}).evaluate(button=>button===document.activeElement),'Pin returns focus to the toggle');
 await page.getByRole('button',{name:'Show sessions',exact:true}).click();
 await page.locator('#conversation-message').fill('Keep this draft while I look around.');
 assert.equal(await page.evaluate(()=>workspaceFixture.microphone.getReply().reference.source),'session:7');
 await page.locator('#conversation-timeline').evaluate(node=>{node.scrollTop=400;});await page.waitForTimeout(150);const readingBefore=await page.locator('#conversation-timeline').evaluate(node=>node.scrollTop);assert(readingBefore>100);
 await page.getByRole('button',{name:sessions[1].title,exact:true}).click();
 await page.locator('.session-message').first().waitFor();
 assert.equal(await page.evaluate(()=>workspaceFixture.microphone.getReply().reference.source),'session:8');
 assert.equal(await page.locator('#conversation-message').inputValue(),'Keep this draft while I look around.');
 assert.equal(await page.getByText('Show me what we discovered.',{exact:true}).count(),0);
 await page.getByRole('button',{name:'Show session detail and tools'}).click();
 await page.getByText('Show me what we discovered.',{exact:true}).waitFor();
 await page.getByText('>_ inspect_result',{exact:true}).waitFor();
 assert(await page.getByText('Reasoning summary',{exact:true}).isVisible());
 await page.screenshot({path:path.join(output,'desktop-technical.png')});
 await page.getByRole('button',{name:'Show session replies'}).click();
 await page.waitForFunction(()=>!document.querySelector('.session-messages').textContent.includes('Show me what we discovered.'));
 assert.equal(await page.locator('#conversation-message').inputValue(),'Keep this draft while I look around.');
 assert.equal(await page.evaluate(()=>workspaceFixture.microphone.getReply().reference.source),'session:8');
 await page.getByRole('button',{name:'Back to the conversation',exact:true}).click();
 assert.equal(await page.locator('#conversation-timeline').evaluate(node=>node.scrollTop),readingBefore,'Back restores the exact previous reading position');
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
 const focused=page.locator('.session-row-actions button:enabled').first();await page.locator('.session-name').first().focus();await page.keyboard.press('Tab');
 assert(await focused.evaluate(button=>button.matches(':focus-visible')&&getComputedStyle(button).outlineStyle!=='none'),'Keyboard focus remains visible on compact controls');
 await page.screenshot({path:path.join(output,'narrow-sessions.png')});
 await page.setViewportSize({width:390,height:844});


 await page.getByRole('button',{name:'Hide sessions',exact:true}).click();
 // Exercise the shipped shell at phone widths, not a DOM-only scroll stub.
 for(const width of [390,320]){
  await page.setViewportSize({width,height:844});
  const draft=await page.locator('#conversation-message').inputValue(),target=await page.evaluate(()=>workspaceFixture.microphone.getReply());
  await page.locator('#conversation-timeline').evaluate(node=>{node.scrollTop=400;});await page.waitForTimeout(150);
  const before=await page.locator('#conversation-timeline').evaluate(node=>node.scrollTop);assert(before>100);
  await page.getByRole('button',{name:'Show sessions',exact:true}).click();await page.getByRole('button',{name:sessions[1].title,exact:true}).click();await page.locator('.session-message').first().waitFor();
  await page.getByRole('button',{name:'Show session detail and tools'}).click();await page.getByText('>_ inspect_result',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Back to the conversation',exact:true}).click();
  assert.equal(await page.locator('#conversation-timeline').evaluate(node=>node.scrollTop),before,'Phone Back preserves reading position');
  assert.equal(await page.locator('#conversation-message').inputValue(),draft);const restoredTarget=await page.evaluate(()=>workspaceFixture.microphone.getReply());assert.deepEqual(restoredTarget.reference,target.reference,'Phone Back restores the exact prior destination');assert(restoredTarget.version>target.version,'Navigation retains a fresh input-admission epoch, never reuses an old capture generation');
 }
 await page.setViewportSize({width:390,height:844});
 const timeline=page.locator('#conversation-timeline');await timeline.evaluate(node=>{node.scrollTop=0;});await page.waitForTimeout(100);
 assert.equal(await page.locator('body').evaluate(body=>body.classList.contains('conversation-header-compact')),false,'Programmatic positioning does not compact header');
 assert.equal(await page.locator('#conversation-presence').count(),0,'Obsolete presence lane is removed');
 await timeline.hover();await page.mouse.wheel(0,900);await page.waitForTimeout(150);
 assert.equal(await page.locator('body').evaluate(body=>body.classList.contains('conversation-header-compact')),false,'Forward scrolling keeps the full header during the redesign');
 assert.equal(await page.locator('#conversation-presence').count(),0,'Compact header does not recreate the removed lane');
 const identity=await page.locator('header .companion-name').boundingBox(),header=await page.locator('header').boundingBox();
 assert(identity.y>=header.y&&identity.y+identity.height<=header.y+header.height,'Expanded identity remains fully visible');
 await page.screenshot({path:path.join(output,'mobile-expanded.png')});
 await page.mouse.wheel(0,-300);await page.waitForTimeout(150);
 assert.equal(await page.locator('body').evaluate(body=>body.classList.contains('conversation-header-compact')),false,'Reverse scroll restores header');
 assert.equal(await page.locator('#conversation-presence').count(),0,'Reverse scroll does not restore the removed lane');
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
 if(nativeDecisionCase&&browser){report.decisions=nativeDecisionPosts;const page=browser.contexts()[0]?.pages()[0];if(page)report.decisionText=await page.locator('#conversation-attention').textContent().catch(()=>null);}
 if(browser)await browser.close();for(const socket of sockets)socket.destroy();await new Promise(resolve=>server.close(resolve));
 report.errors=errors;fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(report,null,2));
 const bytes=fs.readdirSync(output).reduce((n,file)=>n+fs.statSync(path.join(output,file)).size,0);assert(bytes<=4*1024*1024);console.log(JSON.stringify({state:report.state,retained_bytes:bytes,errors}));
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
