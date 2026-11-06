// Public Live WebRTC lifecycle/capture races, no provider or device access.
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto').webcrypto;
const source=fs.readFileSync('dashboard/web/openai-live.js','utf8');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(test){for(let i=0;i<1000;i++){if(test())return;await sleep(1);}throw Error('Fixture did not reach its expected boundary');}
function locks(){const held=new Set();return {async request(name,options,run){if(held.has(name))return run(null);held.add(name);try{return await run({name});}finally{held.delete(name);}}};}
function fixture({nativeChoice=false,modeMismatch=false,reviewFirst=false}={}){
 const records=[],requests=[],sockets=[],peers=[],states=[],items=[],order=[],historyStates=[];let readHistory=async()=>({visits:[],more:false,before:null});let selectedBinding;
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
    emit({type:'prepared',id:this.id,mode:!modeMismatch&&value.backend==='native'?'public_live_native_comparison':'public_live_responses_comparison',admission:{id:this.id,remaining_seconds:600,max_input_pcm_bytes:600*32000}});}
   if(value.type==='offer'){order.push('offer');this.offered=true;emit({type:'answer',id:this.id,session:'live/provider:42',sdp:'v=0 answer'});}
   if(value.type==='close')emit({type:this.offered?'closed':'unconfirmed',id:this.id});
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
 async function fetch(url,options){
  if(!options.body)return readHistory(String(url),options);
  requests.push({url:String(url),sha:await crypto.subtle.digest('SHA-256',await options.body.arrayBuffer()),bytes:options.body.size});
  await beforeUpload();
  if(failUpload)return {ok:false};
  const original=records.find(v=>v.engine==='gpt-live'&&!v.native_fragment&&String(url).endsWith('/recordings/'+v.ordinal));assert(original);
  return {ok:true,json:async()=>({visit:original.voice_visit,binding,recording:{ordinal:original.ordinal,
   audio_sha256:original.audio_sha256,audio_bytes:original.blob.size,work_replay:'never',...(options.headers['x-voice-capture-stop']?{capture_stop:'interrupted_prefix'}:{})}})};
 }
 const api=new Function('window','navigator','document','crypto','WebSocket','RTCPeerConnection','Audio','fetch',source+';return window.PublicLiveConversation;')(
  window,navigator,{hidden:false},crypto,Socket,Peer,class{play(){return Promise.resolve();}pause(){}},fetch);
 let recovered=[];const engine=api.create({headers:()=>({'X-Dashboard-CSRF':'action'}),getBinding:()=>selectedBinding||binding,getBackend:()=>selectedBackend,onHistory:value=>historyStates.push(value),
  onState:value=>states.push(value),onItem:value=>items.push(value),onRecovery:value=>{recovered=value;}});
 async function start(){
  const started=engine.start();await until(()=>peers.at(-1)?.listeners.has('icegatheringstatechange'));
  peers.at(-1).ice();await until(()=>peers.at(-1).connectionState==='connected');peers.at(-1).started();assert.equal(await started,true);
 }
 return {engine,start,store,records,requests,sockets,peers,states,items,order,window,navigator,media,historyStates,
  history:run=>{readHistory=run;},binding:value=>{selectedBinding=value;},backend:value=>{selectedBackend=value;},uploads:run=>{beforeUpload=run;},
  pcm:()=>{captureBytes+=32000;listener({pcm:new Uint8Array(32000).buffer});},boundaryTail:size=>{boundaryTail=size;},recovered:()=>recovered,fail:value=>{failUpload=value;},
  permission:()=>permission,stops:()=>stops,recorderCloses:()=>recorderCloses};
}
(async()=>{
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
 assert(f.states.at(-1).starting,'A connected peer is not session.started');
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
