// Public Live WebRTC lifecycle/capture races, no provider or device access.
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto').webcrypto;
const source=fs.readFileSync('dashboard/web/openai-live.js','utf8');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(test){for(let i=0;i<1000;i++){if(test())return;await sleep(1);}throw Error('Fixture did not reach its expected boundary');}
function locks(){const held=new Set();return {async request(name,options,run){if(held.has(name))return run(null);held.add(name);try{return await run({name});}finally{held.delete(name);}}};}
function fixture({nativeChoice=false,modeMismatch=false,reviewFirst=false,deferClose=false,nativeOutput=false,usageFailure=false,continuous=false,deferRenewalReady=false}={}){
 const timers=[];
 const records=[],requests=[],sockets=[],peers=[],states=[],items=[],order=[],historyStates=[],audios=[],usage=[],networkClocks=[];let readHistory=async()=>({visits:[],more:false,before:null});let selectedBinding;
 const binding='a'.repeat(64);let listener,permission=0,stops=0,recorderCloses=0,failUpload=false,beforeUpload=async()=>{},captureBytes=0,boundaryTail=0,selectedBackend=nativeChoice?'native':undefined;
 const media={getTracks:()=>[{stop(){stops++;}}],getAudioTracks:()=>[{}]};
 const navigator={locks:locks(),mediaDevices:{getUserMedia:async()=>{permission++;order.push('permission');return media;}}};
 class Socket{
  static OPEN=1;
  constructor(){this.readyState=1;this.sent=[];sockets.push(this);queueMicrotask(()=>this.onopen());}
  send(raw){const value=JSON.parse(raw);this.sent.push(value);const emit=value=>queueMicrotask(()=>this.onmessage({data:JSON.stringify(value)}));
   if(value.binding){this.id=value.id;order.push('admission');
    if(reviewFirst&&sockets.length===1){emit({type:'unconfirmed',id:this.id,message:'Tap Reconnect voice. Final usage unconfirmed.',
      replacement:{id:'12345678-1234-4234-8234-123456789abc',revision:'b'.repeat(64)}});return;}
    emit({type:'prepared',id:this.id,mode:!modeMismatch&&value.backend==='native'?'public_live_native_comparison':'public_live_responses_comparison',admission:{id:this.id,remaining_seconds:600,max_input_pcm_bytes:600*32000,continuous_renewal:continuous}});}
   if(value.type==='offer'){order.push('offer');this.offered=true;emit({type:'answer',id:this.id,session:'live/provider:42',sdp:'v=0 answer'});}
   if(value.type==='close'&&!deferClose){
    const renewal=value.reason==='transport_renewal';
    emit({type:this.offered?'closed':'unconfirmed',id:this.id,renewal_pending:renewal});
    if(renewal&&!deferRenewalReady)emit({type:'successor_ready',id:this.id,renewal:{id:this.id,token:'12345678-1234-4234-8234-123456789abc'}});
   }
  }
  close(){this.readyState=3;queueMicrotask(()=>this.onclose?.());}
 }
 class Peer{
  constructor(){this.connectionState='new';this.iceGatheringState='gathering';this.listeners=new Map();peers.push(this);}
  createDataChannel(label){assert.equal(label,'oai-events');order.push('data-channel');return this.channel={close(){}};}
  addTrack(){}async createOffer(){order.push('create-offer');assert.equal(typeof this.channel.onmessage,'function');return {type:'offer',sdp:'v=0 incomplete ICE'};}
  async setLocalDescription(value){this.localDescription=value;}
  addEventListener(name,run){this.listeners.set(name,run);}removeEventListener(name){this.listeners.delete(name);}
  ice(){this.iceGatheringState='complete';this.localDescription.sdp='v=0 gathered ICE';order.push('ice-complete');this.listeners.get('icegatheringstatechange')?.();}
  async setRemoteDescription(value){assert.equal(value.sdp,'v=0 answer');this.connectionState='connected';this.onconnectionstatechange();}
  started(){this.channel.onmessage({data:JSON.stringify({type:'session.started',session:{id:'live/provider:42'}})});}
  close(){this.connectionState='closed';this.onconnectionstatechange?.();}
 }
 const store={list:async()=>[...records],put:async v=>{records.push(v);},
  sealNative:async(v,refs)=>{for(const ref of refs){const index=records.findIndex(x=>x.id===ref.id);assert(index>=0);records.splice(index,1);}records.push(v);},
  discardNative:async refs=>{for(const ref of refs){const index=records.findIndex(x=>x.id===ref.id);assert(index>=0);records.splice(index,1);}},
  remove:async v=>{const index=records.findIndex(x=>x.id===v.id);if(index>=0)records.splice(index,1);}};
 const window={RTCPeerConnection:Peer,indexedDB:{},location:{href:'https://example.test/interaction/'},
  VoiceInput:{recoveryStore:key=>{assert.equal(key,'codex_voice');return store;}},StreamingVoice:{supported:()=>true,
   wav:parts=>new Blob([new Uint8Array(44),...parts],{type:'audio/wav'}),
   openCapture:async()=>{captureBytes=0;return {subscribe(fn){listener=fn;return ()=>{};},start(){order.push('recorder');},
    boundary(token){queueMicrotask(()=>{
     if(boundaryTail){const size=boundaryTail;boundaryTail=0;captureBytes+=size;listener({pcm:new Uint8Array(size).buffer});}
     listener({boundary:token,totalBytes:captureBytes});
    });},finish(){listener({finished:true});},close(){recorderCloses++;}};}}};
 const nativeOutputs=[],observers=[];
 window.WebRtcNativeAudio={observe:async(stream,options)=>{const observer={options,closed:0,close(){this.closed++;}};observers.push(observer);return observer;}};
 if(nativeOutput){
  window.NativeSpeechAudio={webrtcPcm:true};
  window.WebRtcNativeAudio={supported:()=>true,open:async options=>{
   assert.equal(options.sessionSeconds,600);order.push('native-ready');
   const output={closed:0,streams:[],close(){this.closed++;},attach(stream){this.streams.push(stream);},setEnabled(){},pause(){},resume(){}};
   output.activity=options.onActivity;nativeOutputs.push(output);return output;
  }};
 }
 async function fetch(url,options){
  if(!options.body)return readHistory(String(url),options);
  requests.push({url:String(url),sha:await crypto.subtle.digest('SHA-256',await options.body.arrayBuffer()),bytes:options.body.size});
  let aborted;
  try{await Promise.race([beforeUpload(),new Promise((resolve,reject)=>{
   aborted=()=>reject(Error('Upload clock expired'));options.signal?.addEventListener('abort',aborted,{once:true});
  })]);}finally{options.signal?.removeEventListener('abort',aborted);}
  if(failUpload)return {ok:false};
  const original=records.find(v=>v.engine==='gpt-live'&&!v.native_fragment&&String(url).endsWith('/recordings/'+v.ordinal));assert(original);
  return {ok:true,json:async()=>({visit:original.voice_visit,binding,recording:{ordinal:original.ordinal,
   audio_sha256:original.audio_sha256,audio_bytes:original.blob.size,work_replay:'never',...(options.headers['x-voice-capture-stop']?{capture_stop:'interrupted_prefix'}:{})}})};
 }
 const api=new Function('window','navigator','document','crypto','WebSocket','RTCPeerConnection','Audio','fetch','AbortSignal','setTimeout',source+';return window.PublicLiveConversation;')(
  window,navigator,{hidden:false},crypto,Socket,Peer,class{constructor(){this.paused=true;audios.push(this);}play(){this.paused=false;return Promise.resolve();}pause(){this.paused=true;}},fetch,
  {timeout(ms){const controller=new AbortController();networkClocks.push({ms,controller});return controller.signal;}},
  (run,ms)=>{if(continuous&&ms>470000&&ms<490000)timers.push(run);return setTimeout(run,ms);});
 let recovered=[];const engine=api.create({headers:()=>({'X-Dashboard-CSRF':'action'}),getBinding:()=>selectedBinding||binding,getBackend:()=>selectedBackend,onHistory:value=>historyStates.push(value),
  onState:value=>states.push(value),onItem:value=>items.push(value),onUsage:value=>{usage.push(value);if(usageFailure)throw Error('Diagnostic failed');},onRecovery:value=>{recovered=value;}});
 async function start(){
  const started=engine.start();await until(()=>peers.at(-1)?.listeners.has('icegatheringstatechange'));
  peers.at(-1).ice();await until(()=>peers.at(-1).connectionState==='connected');peers.at(-1).started();assert.equal(await started,true);
 }
 return {engine,start,renew:()=>{assert(timers.length);timers.at(-1)();},store,records,requests,sockets,peers,states,items,order,window,navigator,media,historyStates,audios,nativeOutputs,usage,observers,
  history:run=>{readHistory=run;},binding:value=>{selectedBinding=value;},backend:value=>{selectedBackend=value;},uploads:run=>{beforeUpload=run;},
  pcm:()=>{captureBytes+=32000;listener({pcm:new Uint8Array(32000).buffer});},boundaryTail:size=>{boundaryTail=size;},recovered:()=>recovered,fail:value=>{failUpload=value;},
  expireNetworkClocks:()=>{for(const clock of networkClocks)clock.controller.abort();},
  permission:()=>permission,stops:()=>stops,recorderCloses:()=>recorderCloses};
}
(async()=>{
 // A transport handover retains one microphone/lock and never replays
 // retained closing speech into the successor. Source IDs stay per visit.
 const renewal=fixture({nativeChoice:true,continuous:true});await renewal.start();
 try{
  renewal.pcm();renewal.renew();
  await until(()=>renewal.peers[1]?.listeners.has('icegatheringstatechange'));
  assert.equal(renewal.permission(),1);assert.equal(renewal.stops(),0);
  assert.equal(renewal.recorderCloses(),1);
  const first=renewal.sockets[0],second=renewal.sockets[1];
  assert.equal(first.sent.filter(v=>v.type==='close').length,1);
  assert.equal(first.sent.at(-1).reason,'transport_renewal');
  assert.equal(second.sent[0].renewal.id,first.id);
  assert.equal(second.sent[0].voice_continuation,first.id);
  assert.notEqual(second.id,first.id);
  assert.equal(second.sent.filter(v=>v.type==='offer').length,0,'No replayed media or work before its own SDP');
  renewal.peers[1].ice();await until(()=>renewal.states.at(-1).active);
  await until(()=>renewal.requests.length===1);
  assert(renewal.requests[0].url.includes(first.id));
  await renewal.engine.hold();assert.equal(renewal.stops(),1);assert.equal(renewal.sockets.length,2);
 }finally{await renewal.engine.hold();}
 const stopRenewal=fixture({nativeChoice:true,continuous:true,deferRenewalReady:true});await stopRenewal.start();
 stopRenewal.renew();await until(()=>stopRenewal.sockets[0].sent.some(v=>v.reason==='transport_renewal'));
 const stopped=stopRenewal.engine.hold();
 stopRenewal.sockets[0].onmessage({data:JSON.stringify({type:'successor_ready',id:stopRenewal.sockets[0].id,
  renewal:{id:stopRenewal.sockets[0].id,token:'12345678-1234-4234-8234-123456789abc'}})});
 await stopped;await sleep(5);assert.equal(stopRenewal.sockets.length,1,'Stop wins over late successor readiness');
 assert.equal(stopRenewal.stops(),1);
 // A real WebRTC creation has already started the provider. The optional
 // frontend data channel need not repeat a WebSocket startup event.
 const httpStarted=fixture(),httpStarting=httpStarted.engine.start();
 await until(()=>httpStarted.peers[0]?.listeners.has('icegatheringstatechange'));
 httpStarted.peers[0].ice();await until(()=>httpStarted.peers[0].connectionState==='connected');
 try{
  assert(httpStarted.states.at(-1).active&&!httpStarted.states.at(-1).starting,
   'Confirmed HTTP creation plus connected WebRTC must not wait for an optional session.started event');
  assert.equal(await httpStarting,true);assert.equal(httpStarted.sockets.length,1);
 }finally{await httpStarted.engine.hold();await httpStarting;}
 const playback=fixture();await playback.start();
 try{
  playback.peers[0].ontrack({streams:[{}]});await until(()=>playback.observers.length);
  const observation=playback.observers[0];assert.equal(playback.states.at(-1).playback,'idle','Opening a continuous audio stream is not speech');
  observation.options.onActivity(.2);assert.equal(playback.states.at(-1).playback,'playing');assert.equal(playback.states.at(-1).outputLevel,1);
  playback.engine.pause();assert.equal(playback.states.at(-1).outputLevel,0);assert.equal(playback.states.at(-1).playback,'paused');
  observation.options.onActivity(.2);assert.equal(playback.states.at(-1).outputLevel,0);
  playback.engine.resume();observation.options.onActivity(.1);assert.equal(playback.states.at(-1).playback,'playing');
  playback.engine.setEnabled(false);assert.equal(playback.states.at(-1).outputLevel,0);observation.options.onActivity(.2);assert.equal(playback.states.at(-1).playback,'idle');
  playback.engine.setEnabled(true);observation.options.onActivity(0);assert.equal(playback.states.at(-1).playback,'idle','Silence never becomes speaking from a transcript');
  await playback.engine.hold();assert.equal(observation.closed,1);const states=playback.states.length;observation.options.onActivity(.2);assert.equal(playback.states.length,states,'Late old output cannot animate a closed/replaced voice visit');
 }finally{await playback.engine.hold();}
 const slow=fixture();await slow.start();let releaseSlow;
 slow.uploads(()=>new Promise(resolve=>{releaseSlow=resolve;}));slow.pcm();
 const slowRequest=crypto.randomUUID();slow.sockets[0].onmessage({data:JSON.stringify({
  type:'source_seal_requested',visit:slow.sockets[0].id,binding:'a'.repeat(64),request:slowRequest})});
 await until(()=>releaseSlow);
 try{
  slow.expireNetworkClocks();await sleep(5);
  assert(slow.engine.active,'A healthy slow upload must not end voice when an application request clock expires');
  assert(!slow.sockets[0].sent.some(v=>v.type==='source_sealed'),'Only confirmed original bytes seal a source');
  releaseSlow();await until(()=>slow.sockets[0].sent.some(v=>v.type==='source_sealed'));
  assert.equal(slow.requests.length,1,'Waiting never creates a second upload or voice call');
  assert.equal(slow.sockets.length,1);assert.equal(slow.recovered().length,0);
 }finally{releaseSlow();await slow.engine.hold();}
 const optional=fixture();await optional.start();
 optional.sockets[0].onmessage({data:JSON.stringify({type:'notice',code:'native_results_unavailable'})});
 assert(optional.engine.active,'Earlier work failure cannot end the current voice');
 optional.pcm();await optional.engine.hold();
 assert.equal(optional.sockets[0].sent.find(v=>v.type==='close').reason,'explicit_stop');
 const transient=fixture();await transient.start();
 try{
  transient.peers[0].connectionState='disconnected';transient.peers[0].onconnectionstatechange();
  assert(transient.engine.active,'Temporary WebRTC disconnection must allow the same transport to recover');
  assert.match(transient.states.at(-1).message,/reconnect/i);
  assert(!transient.sockets[0].sent.some(v=>v.type==='close'));
  transient.peers[0].connectionState='connected';transient.peers[0].onconnectionstatechange();
  assert.equal(transient.states.at(-1).message,'Listening');assert.equal(transient.sockets.length,1);
  assert.equal(transient.permission(),1,'Transport recovery does not reopen the microphone');
  transient.peers[0].connectionState='failed';transient.peers[0].onconnectionstatechange();
  await until(()=>!transient.engine.active);assert.equal(transient.stops(),1);assert.equal(transient.sockets[0].sent.find(v=>v.type==='close').reason,'transport_failed');
 }finally{await transient.engine.hold();}
 const diagnosticFailure=fixture({usageFailure:true});await diagnosticFailure.start();await diagnosticFailure.engine.hold();
 assert(!diagnosticFailure.engine.active,'A diagnostic callback failure cannot break voice cleanup');
 const metered=fixture({nativeChoice:true});await metered.start();
 assert.equal(metered.usage.at(-1).backend,'native');
 metered.sockets[0].onmessage({data:JSON.stringify({type:'provider_event',event:{type:'session.usage.updated',usage:{seconds:58}}})});
 assert.equal(metered.usage.at(-1).usage.seconds,58);
 metered.sockets[0].onmessage({data:JSON.stringify({type:'closed',id:metered.sockets[0].id,finalization:{voice_usage_confirmed:true,usage_seconds:71}})});
 await until(()=>!metered.engine.active);
 assert(metered.usage.some(v=>v.finalization?.usage_seconds===71));
 assert.equal(metered.usage.at(-1).closed,true);
 assert(metered.usage.every(v=>v.binding==='a'.repeat(64)&&v.visit===metered.sockets[0].id));
 const android=fixture({nativeOutput:true,deferClose:true});await android.start();
 assert(android.order.indexOf('native-ready')<android.order.indexOf('permission'));
 assert.equal(android.audios.length,0,'Native output never creates a second HTML Audio owner');
 const remote={id:'remote-native-output'};android.peers[0].ontrack({streams:[remote]});
 assert.deepEqual(android.nativeOutputs[0].streams,[remote]);
 const nativeClosing=android.engine.hold();
 await until(()=>android.sockets[0].sent.some(v=>v.type==='close'));
 assert.equal(android.nativeOutputs[0].closed,1,'Hold releases native output before provider final usage');
 android.sockets[0].onmessage({data:JSON.stringify({type:'closed',id:android.sockets[0].id})});await nativeClosing;
 const failedOutput=fixture({nativeOutput:true});
 failedOutput.window.WebRtcNativeAudio.open=async()=>{throw Error('Native focus unavailable');};
 assert.equal(await failedOutput.engine.start(),false);assert.equal(failedOutput.permission(),0);
 assert.equal(failedOutput.audios.length,0);assert.equal(failedOutput.peers.length,0);
 const lateOutput=fixture({nativeOutput:true});let releaseOutput,outputSignal;
 lateOutput.window.WebRtcNativeAudio.open=options=>{outputSignal=options.signal;return new Promise(resolve=>{releaseOutput=resolve;});};
 const lateStarting=lateOutput.engine.start();await until(()=>releaseOutput);await lateOutput.engine.hold();
 assert.equal(outputSignal.aborted,true,'Hold also cancels the unresolved native preparation owner');
 assert.equal(await lateStarting,false);let lateCloses=0;
 releaseOutput({close(){lateCloses++;}});await until(()=>lateCloses===1);
 assert.equal(lateOutput.permission(),0);assert.equal(lateOutput.audios.length,0);
 const draining=fixture({deferClose:true});await draining.start();
 draining.peers[0].ontrack({streams:[{id:'owned-provider-audio'}]});
 assert.equal(draining.audios[0].paused,false);
 const closing=draining.engine.hold('Background pause');
 await until(()=>draining.sockets[0].sent.some(v=>v.type==='close'));
 try{
  assert.equal(draining.audios[0].paused,true,'Owned output must stop while final usage is still draining');
  assert.equal(draining.audios[0].srcObject,null,'Release local audio routing without closing provider transport early');
  assert.equal(draining.sockets[0].readyState,1,'Keep the source receiver for session.closed');
  await draining.engine.hold();assert.equal(draining.sockets[0].sent.filter(v=>v.type==='close').length,1,'Repeated lifecycle signals share one close intent');
 }finally{draining.sockets[0].onmessage({data:JSON.stringify({type:'closed',id:draining.sockets[0].id})});await closing;}
 const reconnect=fixture({nativeChoice:true,reviewFirst:true});
 assert.equal(await reconnect.engine.start(),false);await until(()=>!reconnect.engine.active);
 assert.equal(reconnect.permission(),0,'A review offer does not request microphone permission');
 assert.equal(reconnect.sockets.length,1,'No automatic replacement or retry');
 assert.match(reconnect.states.at(-1).message,/Final usage unconfirmed/);
 await reconnect.start();
 assert.deepEqual(reconnect.sockets[1].sent[0].replacement,{id:'12345678-1234-4234-8234-123456789abc',revision:'b'.repeat(64)});
 await reconnect.engine.hold();
 const native=fixture({nativeChoice:true}),nativeStart=native.engine.start();native.backend(undefined);
 await until(()=>native.peers[0]?.listeners.has('icegatheringstatechange'));
 assert.equal(native.sockets[0].sent[0].backend,'native','The native choice freezes before admission/permission');
 native.peers[0].ice();await until(()=>native.peers[0].connectionState==='connected');native.peers[0].started();
 assert.equal(await nativeStart,true);await native.engine.hold();
 const mismatch=fixture({nativeChoice:true,modeMismatch:true});
 assert.equal(await mismatch.engine.start(),false);assert.equal(mismatch.permission(),0,'Never fall back or open the mic after a changed backend admission');
 const f=fixture(),starting=f.engine.start();
 await until(()=>f.peers[0]?.listeners.has('icegatheringstatechange'));
 assert(f.order.indexOf('admission')<f.order.indexOf('permission'));
 assert(f.order.indexOf('recorder')<f.order.indexOf('create-offer'));
 assert(!f.sockets[0].sent.some(v=>v.type==='offer'),'No incomplete ICE offer is sent');
 f.peers[0].ice();await until(()=>f.peers[0].connectionState==='connected');
 assert(f.states.at(-1).active&&!f.states.at(-1).starting,'Validated HTTP creation starts WebRTC without another startup event');
 f.peers[0].started();assert.equal(await starting,true);
 assert.equal(f.sockets[0].sent.find(v=>v.type==='offer').sdp,'v=0 gathered ICE');
 f.records.push({id:'native-original',engine:'codex',codex_visit:'native',blob:new Blob(['native original']),binding:'a'.repeat(64)});
 f.fail(true);f.pcm();await f.engine.hold();await until(()=>f.requests.length===1);
 assert.equal(f.states.at(-1).message,'Voice ended.','A confirmed close must not stay labeled Finishing');
 assert.equal(f.recovered().length,1);const original=f.recovered()[0];assert.equal(original.engine,'gpt-live');
 f.fail(false);await f.engine.retry(original);
 assert.deepEqual(f.requests[0],f.requests[1],'Explicit retry retains the identical public original');
 assert.equal(f.records.length,1);assert.equal(f.records[0].id,'native-original','Public recovery never consumes native originals');
 assert(!f.sockets.flatMap(s=>s.sent).some(v=>['session.start','response.create'].includes(v.type)));
 const oldSocket=f.sockets[0];await f.start();oldSocket.onclose();assert(f.engine.active,'Retired socket cannot close the current visit');await f.engine.hold();

 // The first seal fixes exact frames before awaiting uploads. Later microphone
 // frames keep recording; duplicate control cannot move the boundary or upload
 // another original. This is a raw prefix, never a completed speech/work claim.
 const sealed=fixture();await sealed.start();let releaseUpload;
 sealed.uploads(()=>new Promise(resolve=>{releaseUpload=resolve;}));sealed.pcm();sealed.boundaryTail(1000);
 const firstSeal=crypto.randomUUID(),sealSocket=sealed.sockets[0];
 const sealEvent=request=>sealSocket.onmessage({data:JSON.stringify({type:'source_seal_requested',
  visit:sealSocket.id,binding:'a'.repeat(64),request,delegation:'trusted-client-task'})});
 const acknowledgments=()=>sealSocket.sent.filter(row=>row.type==='source_sealed');
 sealEvent(firstSeal);await until(()=>releaseUpload);sealed.pcm();releaseUpload();
 await until(()=>acknowledgments().length===1);
 assert.deepEqual(acknowledgments()[0],{type:'source_sealed',request:firstSeal,through_ordinal:1,capture_bytes:33000});
 assert(sealed.engine.active);assert.equal(sealed.requests.length,1);assert.equal(sealed.requests[0].bytes,33044,'Worklet tail must be included before sealing');
 sealEvent(firstSeal);await until(()=>acknowledgments().length===2);
 assert.deepEqual(acknowledgments()[1],acknowledgments()[0]);assert.equal(sealed.requests.length,1);
 sealed.uploads(async()=>{});sealEvent(crypto.randomUUID());await until(()=>acknowledgments().length===3);
 assert.equal(acknowledgments()[2].through_ordinal,2);assert.equal(acknowledgments()[2].capture_bytes,65000);
 assert.equal(sealed.requests.length,2);await sealed.engine.hold();

 const missing=fixture();await missing.start();missing.fail(true);missing.pcm();
 missing.sockets[0].onmessage({data:JSON.stringify({type:'source_seal_requested',visit:missing.sockets[0].id,
  binding:'a'.repeat(64),request:crypto.randomUUID(),delegation:'trusted-client-task'})});
 await until(()=>!missing.engine.active);
 assert(!missing.sockets[0].sent.some(row=>row.type==='source_sealed'));
 assert.equal(missing.recovered().length,1);assert.equal(missing.requests.length,1,'Failed originals are never uploaded again by source sealing');

 const changedSource=fixture();await changedSource.start();let releaseChanged;
 changedSource.uploads(()=>new Promise(resolve=>{releaseChanged=resolve;}));changedSource.pcm();
 changedSource.sockets[0].onmessage({data:JSON.stringify({type:'source_seal_requested',
  visit:changedSource.sockets[0].id,binding:'a'.repeat(64),request:crypto.randomUUID()})});
 await until(()=>releaseChanged);changedSource.binding('b'.repeat(64));releaseChanged();
 await until(()=>!changedSource.engine.active);
 assert(!changedSource.sockets[0].sent.some(row=>row.type==='source_sealed'),'A late upload cannot acknowledge another conversation');

 const empty=fixture();await empty.start();empty.sockets[0].onmessage({data:JSON.stringify({
  type:'source_seal_requested',visit:empty.sockets[0].id,binding:'a'.repeat(64),request:crypto.randomUUID()})});
 await until(()=>empty.sockets[0].sent.some(row=>row.type==='source_sealed'));
 assert.equal(empty.sockets[0].sent.find(row=>row.type==='source_sealed').capture_bytes,0);
 assert.equal(empty.requests.length,0);await empty.engine.hold();

 const permission=fixture();let resolvePermission;
 permission.navigator.mediaDevices.getUserMedia=()=>new Promise(resolve=>{resolvePermission=resolve;});
 const retired=permission.engine.start();await until(()=>resolvePermission);await permission.engine.hold();
 assert.equal(await retired,false);assert.equal(await permission.engine.start(),false,'No second permission request while the first is unresolved');
 resolvePermission(permission.media);await until(()=>permission.stops()===1);assert(!permission.sockets[0].sent.some(v=>v.type==='offer'));
 permission.navigator.mediaDevices.getUserMedia=async()=>permission.media;await permission.start();await permission.engine.hold();

 const recorder=fixture();let resolveRecorder;const open=recorder.window.StreamingVoice.openCapture;
 recorder.window.StreamingVoice.openCapture=()=>new Promise(resolve=>{resolveRecorder=resolve;});
 const retiredRecorder=recorder.engine.start();await until(()=>resolveRecorder);await recorder.engine.hold();assert.equal(await retiredRecorder,false);
 let lateClosed=0;resolveRecorder({close(){lateClosed++;}});await until(()=>lateClosed===1);
 recorder.window.StreamingVoice.openCapture=open;await recorder.start();await recorder.engine.hold();

 const ice=fixture(),retiredIce=ice.engine.start();await until(()=>ice.peers[0]?.listeners.has('icegatheringstatechange'));
 await ice.engine.hold();assert.equal(await retiredIce,false);assert.equal(ice.peers[0].listeners.size,0,'Retired ICE listener is removed');
 assert(!ice.sockets[0].sent.some(v=>v.type==='offer'));
 const history=fixture(),id=crypto.randomUUID(),olderId=crypto.randomUUID();let fail=true,reads=0;
 const first={event_id:'one',event:{event_id:'one',type:'session.input_transcript.delta',delta:'Mi corrección'}},
  second={event_id:'two',event:{event_id:'two',type:'session.output_transcript.delta',delta:'Confirmado.'}};
 history.history(async url=>{reads++;
  if(url.endsWith('/visits'))return {ok:true,json:async()=>({visits:[{id,created_at:1,state:'created'}],more:true,before:id})};
  if(url.includes('?before='))return {ok:true,json:async()=>({visits:[{id:olderId,created_at:0,state:'closed'}],more:false,before:null})};
  if(url.includes(olderId))return {ok:true,json:async()=>({items:[],after:0,revision:null,more:false})};
  if(url.includes('after=0'))return {ok:true,json:async()=>({items:[first],after:100,revision:'source',more:true})};
  if(fail)return {ok:false};
  return {ok:true,json:async()=>({items:[second],after:200,revision:'source',more:false})};
 });
 await assert.rejects(history.engine.restoreHistory());assert.equal(history.items.length,1);
 const afterFailure=reads;await history.engine.restoreHistory();assert.equal(reads,afterFailure,'Presence does not loop a failed source read');
 fail=false;await history.engine.restoreHistory(false,true);assert.deepEqual(history.items.map(v=>v.item.event_id),['one','two']);
 assert.equal(history.items[1].source_order,1);assert(history.items.every(v=>v.history));
 const beforeReads=reads;await history.engine.restoreHistory();assert.equal(reads,beforeReads,'Presence refresh does not rescan sources');
 await history.engine.restoreHistory(true);assert.equal(history.historyStates.at(-1).more,false);
 assert.equal(history.permission(),0);assert.equal(history.sockets.length,0);assert.equal(history.requests.length,0);
 history.engine.resetHistory();let finish;
 history.history(()=>new Promise(resolve=>{finish=resolve;}));const pending=history.engine.restoreHistory();await until(()=>finish);
 history.binding('b'.repeat(64));finish({ok:true,json:async()=>({visits:[{id,created_at:1}],more:false})});
 await assert.rejects(pending);assert.equal(history.items.length,2,'Changed binding cannot publish stale history');
 console.log('Public Live: admission/ICE/started ordering, exact original recovery, source sealing with later frames/duplicate control/missing uploads/empty prefix/changed owner, engine isolation/retirement fences and paged history passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
