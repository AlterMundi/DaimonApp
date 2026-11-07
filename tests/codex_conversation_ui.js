// Native browser control/capture with synthetic RTC/microphone; zero inference.
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto').webcrypto;
const source=fs.readFileSync('dashboard/web/codex-conversation.js','utf8');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function locks(){const held=new Set();return {async request(name,_options,run){if(held.has(name))return run(null);held.add(name);try{return await run({name});}finally{held.delete(name);}}};}
async function fixture(){
 const records=[],requests=[],sockets=[],peers=[],states=[];let listener,recoveryValues=[],failUpload=false,stops=0;
 const binding='a'.repeat(64),media={getTracks:()=>[{stop(){stops++;}}],getAudioTracks:()=>[{}]};
 const navigator={locks:locks(),mediaDevices:{getUserMedia:async()=>media}};
 class Socket{
  static OPEN=1;constructor(){sockets.push(this);this.readyState=1;this.sent=[];queueMicrotask(()=>this.onopen());}
  send(raw){const v=JSON.parse(raw);this.sent.push(v);
   if(v.binding)queueMicrotask(()=>this.onmessage({data:JSON.stringify({type:'prepared',id:v.id,session_seconds:600,logical_visit:'v1',admission:null})}));
   if(v.type==='capture')queueMicrotask(()=>this.onmessage({data:JSON.stringify({type:'capture_ready',id:this.sent[0].id,admission:{id:this.sent[0].id,expires:600,remaining_seconds:600,max_input_pcm_bytes:600*32000,generation:0}})}));
   if(v.type==='offer')queueMicrotask(()=>this.onmessage({data:JSON.stringify({type:'answer',id:this.sent[0].id,sdp:'v=0 synthetic-answer'})}));
   if(v.type==='close')queueMicrotask(()=>this.onmessage({data:JSON.stringify({type:'closed',id:this.sent[0].id,confirmed:true})}));
  }
  close(){this.readyState=3;queueMicrotask(()=>this.onclose?.());}
 }
 class Peer{
  constructor(){peers.push(this);this.connectionState='new';}
  createDataChannel(label){this.channel={label,closed:false,close(){this.closed=true;}};return this.channel;}
  addTrack(){}async createOffer(){return {type:'offer',sdp:'v=0 synthetic-offer'};}
  async setLocalDescription(v){this.localDescription=v;}
  async setRemoteDescription(v){assert.equal(v.type,'answer');this.connectionState='connected';this.onconnectionstatechange();}
  close(){this.connectionState='closed';this.onconnectionstatechange?.();}
 }
 class Audio{play(){return Promise.resolve();}pause(){}}
 const store={list:async()=>[...records],put:async v=>{records.push(v);},sealNative:async(v,refs)=>{for(const ref of refs){const i=records.indexOf(ref);assert(i>=0);records.splice(i,1);}records.push(v);},remove:async v=>{const i=records.findIndex(r=>r.id===v.id);if(i>=0)records.splice(i,1);}};
 const window={RTCPeerConnection:Peer,indexedDB:{},location:{href:'https://example.test/interaction/'},
  VoiceInput:{recoveryStore:key=>{assert.equal(key,'codex_voice');return store;}},StreamingVoice:{supported:()=>true,
   wav(parts){return new Blob([new Uint8Array(44),...parts],{type:'audio/wav'});},
   openCapture:async()=>({subscribe(fn){listener=fn;return ()=>{};},start(){},finish(){listener({finished:true});},close(){}})}};
 async function fetch(url,options){
  requests.push({url:String(url),options});
  if(String(url).endsWith('/capture/ended'))return {ok:true,json:async()=>({capture:'ended'})};
  if(failUpload)return {ok:false};
  const original=records.find(r=>r.codex_visit&&String(url).endsWith('/recordings/'+r.ordinal));assert(original);
  return {ok:true,json:async()=>({visit:original.codex_visit,binding,recording:{
   ordinal:original.ordinal,audio_sha256:original.audio_sha256,audio_bytes:original.blob.size,native_replay:'never'}})};
 }
 const api=new Function('window','navigator','document','crypto','WebSocket','RTCPeerConnection','Audio','fetch',source+';return window.CodexConversation;')(
  window,navigator,{hidden:false},crypto,Socket,Peer,Audio,fetch);
 const engine=api.create({headers:()=>({'x-dashboard-csrf':'action'}),getBinding:()=>binding,
  onState:v=>states.push(v),onRecovery:v=>recoveryValues=v});
 assert.equal(await engine.start(),true);assert.equal(engine.active,true);
 listener({pcm:new Uint8Array(32000).buffer});listener({pcm:new Uint8Array(32000).buffer});
 await engine.hold();assert.equal(engine.active,false);assert.equal(records.length,0);
 assert.equal(requests.filter(r=>r.url.includes('/recordings/')).length,1);assert(requests[0].url.includes('/voice/codex/visits/'));
 assert(requests.filter(r=>r.url.includes('/recordings/')).every(r=>r.options.signal===undefined),
  'Native original uploads have no application lifetime abort; read/control requests retain their clocks');
 assert(!requests.some(r=>/transcrib|\/inputs/.test(r.url)));
 assert.deepEqual(sockets[0].sent.map(v=>v.type||'binding'),['binding','capture','offer','ready','close']);
 assert.equal(peers[0].connectionState,'closed');assert(stops>0);
 assert.equal(peers[0].channel.label,'oai-events');assert(peers[0].channel.closed);
 failUpload=true;assert.equal(await engine.start(),true);listener({pcm:new Uint8Array(32000).buffer});
 await engine.hold();assert.equal(records.length,1);assert.equal(recoveryValues.length,1);
 const original=records[0],digest=original.audio_sha256;
 assert.equal(engine.originals.length,0,'Native recordings must never enter ordinary Send recovery');
 failUpload=false;await engine.retry(original);
 assert.equal(records.length,0);assert.equal(original.audio_sha256,digest);
 assert.equal(requests.filter(r=>r.url.includes('/recordings/')).length,3);assert.equal(sockets.length,2,'Original retry opened another voice visit');
 const prefix={...original,captureStop:'interrupted_prefix'},stalePrefix={...prefix,native_fragments:[{id:'stale-fragment'}]};
 records.push({...prefix,ordinal:prefix.ordinal+1});
 await assert.rejects(engine.discard(stalePrefix),/Recovered original changed/);assert.equal(records.length,1);
 records[0]=prefix;await engine.discard(stalePrefix);assert.equal(records.length,0,'Discard after an uncertain prefix save removes only the identical sealed original');
 assert(states.some(v=>v.pending));await sleep(0);
 assert.equal(engine.active,false,'Retired socket callback revived the visit');
 const nativeMicrophone=navigator.mediaDevices.getUserMedia;
 for(const name of ['NotAllowedError','NotReadableError','NotFoundError']){
  navigator.mediaDevices.getUserMedia=async()=>{throw Object.assign(Error('private device payload'),{name});};
  assert.equal(await engine.start(),false);
  const failure=sockets.at(-1).sent.find(v=>v.type==='startup_failed');
  assert.deepEqual(failure,{type:'startup_failed',stage:'microphone',reason:name});
  assert(!sockets.at(-1).sent.some(v=>v.type==='offer'));
  assert(!states.at(-1).message.includes('private device payload'));
  assert.match(states.at(-1).message,/microphone/i);
 }
 navigator.mediaDevices.getUserMedia=nativeMicrophone;
 let resolvePermission,oldStops=0;
 navigator.mediaDevices.getUserMedia=()=>new Promise(resolve=>{resolvePermission=resolve;});
 const retiredStart=engine.start();
 while(!resolvePermission)await sleep(1);
 await engine.hold();
 navigator.mediaDevices.getUserMedia=async()=>media;
 assert.equal(await engine.start(),true);const currentPeer=peers.at(-1);
 resolvePermission({getTracks:()=>[{stop(){oldStops++;}}]});
 assert.equal(await retiredStart,false);assert.equal(oldStops,1);
 assert.equal(engine.active,true,'Late old permission must not close the newer voice visit');
 assert.equal(currentPeer.connectionState,'connected');await engine.hold();
 let resolveRecovery;const ordinaryList=store.list,beforeSockets=sockets.length;
 store.list=()=>new Promise(resolve=>{resolveRecovery=resolve;});
 const retiredRecovery=engine.start();while(!resolveRecovery)await sleep(1);
 await engine.hold();store.list=ordinaryList;
 assert.equal(await engine.start(),true);const retainedPeer=peers.at(-1);
 resolveRecovery([]);assert.equal(await retiredRecovery,false);
 assert.equal(sockets.length,beforeSockets+1,'Retired recovery read cannot overwrite the new socket');
 assert.equal(engine.active,true);assert.equal(retainedPeer.connectionState,'connected');await engine.hold();
 console.log('Native WebRTC capture: separate durable recovery, exact original retry without ASR/work replay, explicit closure and retired callback fences passed.');
}
async function captureDeadlineFixture(){
 let now=0,listener,expired=false,finished=false,put;const timers=new Set(),sockets=[];
 const setTimer=(fn,ms)=>{const timer={fn,at:now+ms};timers.add(timer);return timer;};
 const clearTimer=timer=>timers.delete(timer);
 const binding='c'.repeat(64),media={getTracks:()=>[{stop(){}}],getAudioTracks:()=>[{}]};
 class Socket{
  static OPEN=1;constructor(){sockets.push(this);this.readyState=1;queueMicrotask(()=>this.onopen());}
  send(raw){const v=JSON.parse(raw);if(v.binding){this.id=v.id;queueMicrotask(()=>this.onmessage({data:JSON.stringify({type:'prepared',id:v.id,session_seconds:600,logical_visit:'v1',admission:null})}));}
   if(v.type==='capture')queueMicrotask(()=>this.onmessage({data:JSON.stringify({type:'capture_ready',id:this.id,admission:{id:this.id,expires:600,remaining_seconds:600,max_input_pcm_bytes:600*32000,generation:0}})}));
   if(v.type==='offer')queueMicrotask(()=>this.onmessage({data:JSON.stringify({type:'answer',id:this.id,sdp:'v=0 answer'})}));
   if(v.type==='close')queueMicrotask(()=>this.onmessage({data:JSON.stringify({type:'closed',id:this.id,confirmed:true})}));}
  close(){this.readyState=3;queueMicrotask(()=>this.onclose?.());}
 }
 class Peer{
  createDataChannel(){return {close(){}};}addTrack(){}
  async createOffer(){return {type:'offer',sdp:'v=0 offer'};}async setLocalDescription(v){this.localDescription=v;}
  async setRemoteDescription(){now+=7000;this.connectionState='connected';this.onconnectionstatechange();}
  close(){this.connectionState='closed';this.onconnectionstatechange?.();}
 }
 const store={list:async()=>[],put:async v=>{put=v;},sealNative:async v=>{put=v;},remove:async()=>{}};
 const window={location:{href:'https://example.test/interaction/'},RTCPeerConnection:Peer,indexedDB:{},
  VoiceInput:{recoveryStore:()=>store},StreamingVoice:{supported:()=>true,wav:parts=>new Blob([new Uint8Array(44),...parts]),
   openCapture:async()=>{let deadline;return {subscribe(fn){listener=fn;return ()=>{};},
    start(){deadline=setTimer(()=>{expired=true;listener({captureError:'session_limit'});},600000);},
    finish(){if(!expired){finished=true;listener({finished:true});}},close(){clearTimer(deadline);}};}}};
 async function fetch(url,options){if(String(url).endsWith('/capture/ended'))return {ok:true,json:async()=>({capture:'ended'})};return {ok:true,json:async()=>({visit:put.codex_visit,binding,
  recording:{ordinal:put.ordinal,audio_sha256:put.audio_sha256,audio_bytes:options.body.size,native_replay:'never'}})};}
 const api=new Function('window','navigator','document','crypto','WebSocket','RTCPeerConnection','Audio','fetch','setTimeout','clearTimeout',source+';return window.CodexConversation;')(
  window,{locks:locks(),mediaDevices:{getUserMedia:async()=>media}},{hidden:false},crypto,Socket,Peer,class{pause(){}},fetch,setTimer,clearTimer);
 const engine=api.create({headers:()=>({'x-dashboard-csrf':'action'}),getBinding:()=>binding});
 assert.equal(await engine.start(),true);listener({pcm:new Uint8Array(32000).buffer});
 // Seven seconds of SDP negotiation must not move the capture budget's deadline.
 now=599000;for(const timer of [...timers].sort((a,b)=>a.at-b.at))if(timer.at<=now&&timers.delete(timer))timer.fn();
 for(let n=0;n<50&&engine.active;n++)await sleep(2);
 assert.equal(engine.active,false,'Planned closure must precede the worklet limit even after slow SDP');
 assert.equal(expired,false);assert.equal(finished,true,'Capture must flush before its own deadline');
 assert.equal(put.captureStop,undefined,'A planned stop must not manufacture an unconfirmed tail');
 console.log('Native capture budget: delayed SDP cannot defer planned closure past the recorder deadline.');
}
async function historyFixture(){
 let binding='a'.repeat(64),failOlder=true,delayed,delay=false;const calls=[],items=[],states=[];
 const cursor='12345678-1234-4234-8234-123456789012';
 const window={location:{href:'https://example.test/interaction/'},VoiceInput:{recoveryStore:()=>({list:async()=>[]})}};
 async function fetch(url){
  const parsed=new URL(url);calls.push(parsed);assert(parsed.pathname.endsWith('/voice/codex/visits'));
  if(delay)await new Promise(resolve=>{delayed=resolve;});
  if(parsed.searchParams.has('before')){
   assert.equal(parsed.searchParams.get('before'),cursor);
   if(failOlder){failOlder=false;return {ok:false};}
   return {ok:true,json:async()=>({visits:[{id:'old',items:[{id:'old-item',text:'Earlier correction'}]}],more:false,before:null})};
  }
  return {ok:true,json:async()=>({visits:[{id:'recent',items:[{id:'recent-item',text:'Recent conversation'}]}],more:true,before:cursor})};
 }
 const unexpected=()=>{throw Error('Reading history must not open voice or capture');};
 const api=new Function('window','navigator','document','crypto','WebSocket','RTCPeerConnection','Audio','fetch',source+';return window.CodexConversation;')(
  window,{mediaDevices:{getUserMedia:unexpected}},{hidden:false},crypto,unexpected,unexpected,unexpected,fetch);
 const engine=api.create({headers:()=>({}),getBinding:()=>binding,onItem:v=>items.push(v),onHistory:v=>states.push(v)});
 await engine.restoreHistory();assert.deepEqual(items.map(v=>v.item.text),['Recent conversation']);
 await assert.rejects(engine.restoreHistory(true));assert.equal(states.at(-1).error,true);assert.equal(states.at(-1).older,true);
 await engine.restoreHistory(true);assert.deepEqual(items.map(v=>v.item.text),['Recent conversation','Earlier correction']);
 assert.equal(states.at(-1).more,false);await engine.restoreHistory(true);assert.equal(calls.length,3);
 const next=api.create({headers:()=>({}),getBinding:()=>binding,onItem:v=>items.push(v)});
 delay=true;const pending=next.restoreHistory();while(!delayed)await sleep(1);binding='b'.repeat(64);delayed();
 await assert.rejects(pending);assert.equal(items.length,2,'Late old-binding history must not enter the new conversation');
 delayed=undefined;const sameBinding=next.restoreHistory();while(!delayed)await sleep(1);next.resetHistory();delayed();
 await assert.rejects(sameBinding);assert.equal(items.length,2,'Invalidated same-binding history must not repopulate a reset view');
 delay=false;await next.restoreHistory();assert.equal(items.length,3,'Reset cache permits the current history to load again');
 assert(!calls.some(v=>/transcrib|inputs/.test(v.pathname)));
 console.log('Voice history paging: retry preserves cursor, exhausted pages stop, stale bindings cannot publish, zero capture/work.');
}
async function renewalFixture(){
 let now=0,listener,captureCount=0,permissions=0,stops=0,finishes=0,root,rootStarted=0,defer=false,deliver,changeBudget=false;
 const timers=new Set(),sockets=[],peers=[],records=[],uploads=[],states=[],audio=[];
 const setTimer=(fn,ms)=>{const timer={fn,at:now+ms};timers.add(timer);return timer;};
 const clearTimer=timer=>timers.delete(timer);
 const DateClock={now:()=>now};
 const binding='d'.repeat(64),media={getTracks:()=>[{stop(){stops++;}}],getAudioTracks:()=>[{}]};
 const admission=generation=>({id:root,expires:(rootStarted+600000)/1000,remaining_seconds:600-(now-rootStarted)/1000,max_input_pcm_bytes:600*32000,generation});
 class Socket{
  static OPEN=1;
  constructor(){sockets.push(this);this.readyState=1;this.sent=[];queueMicrotask(()=>this.onopen());}
  send(raw){const value=JSON.parse(raw);this.sent.push(value);
   if(value.binding){
    this.id=value.id;this.generation=value.predecessor?sockets[sockets.indexOf(this)-1].generation+1:0;if(!this.generation){root=this.id;rootStarted=now;}
    assert.equal(value.logical_visit,true);
    if(this.generation)assert.equal(value.predecessor,sockets[sockets.indexOf(this)-1].id);
    let current=this.generation?admission(this.generation):null;if(changeBudget&&current){current={...current,max_input_pcm_bytes:current.max_input_pcm_bytes+32000};changeBudget=false;}
    const send=()=>this.onmessage({data:JSON.stringify({type:'prepared',id:this.id,session_seconds:600,logical_visit:'v1',admission:current})});
    if(defer){defer=false;deliver=send;}else queueMicrotask(send);
   }
   if(value.type==='capture'){
    assert.equal(this.generation,0,'Physical renewal must not obtain another microphone admission');
    queueMicrotask(()=>this.onmessage({data:JSON.stringify({type:'capture_ready',id:this.id,admission:admission(0)})}));
   }
   if(value.type==='offer')queueMicrotask(()=>this.onmessage({data:JSON.stringify({type:'answer',id:this.id,sdp:'v=0 answer'})}));
   if(value.type==='renew')queueMicrotask(()=>this.onmessage({data:JSON.stringify({type:'closed',id:this.id,confirmed:true,successor_ready:true,reason:'media_replacement'})}));
   if(value.type==='close')queueMicrotask(()=>this.onmessage({data:JSON.stringify({type:'closed',id:this.id,confirmed:true,successor_ready:true,reason:'requested'})}));
  }
  close(){this.readyState=3;queueMicrotask(()=>this.onclose?.());}
 }
 class Peer{
  constructor(){peers.push(this);sockets.at(-1).peer=this;this.connectionState='new';}
  createDataChannel(){return {close(){}};}addTrack(track,stream){assert.equal(stream,media);}
  async createOffer(){return {type:'offer',sdp:'v=0 offer'};}async setLocalDescription(value){this.localDescription=value;}
  async setRemoteDescription(){this.connectionState='connected';this.onconnectionstatechange();this.ontrack({streams:[{peer:this}]});}
  close(){this.connectionState='closed';this.onconnectionstatechange?.();}
 }
 class Audio{constructor(){audio.push(this);this.plays=0;}play(){this.plays++;return Promise.resolve();}pause(){}}
 const store={list:async()=>[...records],put:async value=>{records.push(value);},
  sealNative:async(value,fragments)=>{for(const fragment of fragments){const i=records.indexOf(fragment);assert(i>=0);records.splice(i,1);}records.push(value);},
  remove:async value=>{records.splice(records.indexOf(value),1);}};
 const window={location:{href:'https://example.test/interaction/'},RTCPeerConnection:Peer,indexedDB:{},
  VoiceInput:{recoveryStore:()=>store},StreamingVoice:{supported:()=>true,wav:parts=>new Blob([new Uint8Array(44),...parts]),
   openCapture:async stream=>{assert.equal(stream,media);captureCount++;return {subscribe(fn){listener=fn;return ()=>{};},start(){},finish(){finishes++;listener({finished:true});},close(){}};}}};
 async function fetch(url,options){
  if(String(url).endsWith('/capture/ended'))return {ok:true,json:async()=>({capture:'ended'})};
  const original=records.find(value=>String(url).endsWith('/recordings/'+value.ordinal));assert(original);
  assert.equal(original.codex_visit,root,'All physical generations share the original capture owner');uploads.push(original);
  return {ok:true,json:async()=>({visit:root,binding,recording:{ordinal:original.ordinal,audio_sha256:original.audio_sha256,audio_bytes:original.blob.size,native_replay:'never'}})};
 }
 const api=new Function('window','navigator','document','crypto','WebSocket','RTCPeerConnection','Audio','fetch','setTimeout','clearTimeout','Date',source+';return window.CodexConversation;')(
  window,{locks:locks(),mediaDevices:{getUserMedia:async()=>{permissions++;return media;}}},{hidden:false},crypto,Socket,Peer,Audio,fetch,setTimer,clearTimer,DateClock);
 const engine=api.create({headers:()=>({'x-dashboard-csrf':'action'}),getBinding:()=>binding,onState:value=>states.push(value)});
 async function until(test){for(let n=0;n<200&&!test();n++)await sleep(1);assert(test(),'Synthetic continuation did not settle');await sleep(2);}
 function frame(value){listener({pcm:new Uint8Array(32000).fill(value).buffer});}
 function terminal(socket,ready=true){
  const peer=socket.peer;peer.connectionState='disconnected';peer.onconnectionstatechange();
  socket.onmessage({data:JSON.stringify({type:'closed',id:socket.id,confirmed:true,successor_ready:ready,reason:'native_transport_closed'})});
 }
 assert.equal(await engine.start(),true);frame(1);assert.equal(audio[0].plays,1);
 now=50000;defer=true;terminal(sockets[0]);await until(()=>!!deliver);
 frame(2);assert.equal(stops,0);assert.equal(captureCount,1);
 engine.pause();deliver();deliver=undefined;await until(()=>peers.length===2&&peers[1].connectionState==='connected');
 assert.equal(engine.paused,true);assert.equal(audio[1].plays,0,'Renewal must not override an explicit playback pause');
 engine.resume();assert.equal(audio[1].plays,1);frame(3);
 now=100000;peers[1].connectionState='disconnected';peers[1].onconnectionstatechange();
 now=104000;for(const timer of [...timers])if(timer.at<=now&&timers.delete(timer))timer.fn();
 await until(()=>peers.length===3&&peers[2].connectionState==='connected');frame(4);
 assert.equal(sockets[1].sent.filter(value=>value.type==='renew').length,1,'A failed peer requests one owned native cleanup');
 assert.equal(permissions,1);assert.equal(captureCount,1);assert.equal(stops,0);assert.equal(finishes,0);
 assert.equal(sockets.length,3);assert.equal(sockets.flatMap(socket=>socket.sent).filter(value=>value.type==='capture').length,1);
 // An old physical socket must not retire or speak into its successor.
 sockets[0].onclose();assert.equal(engine.active,true);assert.equal(stops,0);
 now=599000;for(const timer of [...timers])if(timer.at<=now&&timers.delete(timer))timer.fn();
 await until(()=>!engine.active);
 assert.equal(stops,1);assert.equal(finishes,1);assert.equal(records.length,0);
 assert.equal(uploads.length,1);assert.equal(uploads[0].blob.size,4*32000+44);
 const pcm=new Uint8Array(await uploads[0].blob.slice(44).arrayBuffer());
 for(let n=0;n<4;n++)assert(pcm.subarray(n*32000,(n+1)*32000).every(value=>value===n+1),'Capture lost or duplicated a physical-generation/setup-gap frame');
 assert(states.some(value=>value.message?.includes('Reconnecting voice')));
 console.log('Automatic physical renewal: two replacements, one permission/recorder/deadline/PCM owner, retained setup-gap bytes, pause and retired-callback fences passed.');
 // A close observation without settled readiness is not permission to retry.
 now=600000;assert.equal(await engine.start(),true);const count=sockets.length;
 terminal(sockets.at(-1),false);await until(()=>!engine.active);
 assert.equal(sockets.length,count,'Unconfirmed successor readiness must not open another provider connection');
 console.log('Automatic renewal refuses a terminal close without settled successor readiness.');
 assert.equal(await engine.start(),true);defer=true;terminal(sockets.at(-1));await until(()=>!!deliver);
 const late=deliver;deliver=undefined;await engine.hold();
 assert.equal(engine.active,false);assert.equal(await engine.start(),true);const newest=peers.at(-1);
 late();await sleep(2);assert.equal(engine.active,true);assert.equal(newest.connectionState,'connected');await engine.hold();
 assert.equal(await engine.start(),true);changeBudget=true;terminal(sockets.at(-1));await until(()=>!engine.active);
 assert.equal(sockets.at(-1).sent.some(value=>value.type==='offer'),false,'Changed PCM allowance must fail before another native start');
 console.log('Automatic renewal cancellation and changed-admission fences preserve the next explicit microphone visit.');

}

(async()=>{await fixture();await captureDeadlineFixture();await historyFixture();await renewalFixture();})().catch(error=>{console.error(error);process.exitCode=1;});
