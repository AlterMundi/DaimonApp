// Native browser control/capture with synthetic RTC/microphone; zero inference.
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto').webcrypto;
const source=fs.readFileSync('dashboard/web/codex-conversation.js','utf8');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function fixture(){
 const records=[],requests=[],sockets=[],peers=[],states=[];let listener,recoveryValues=[],failUpload=false,stops=0;
 const binding='a'.repeat(64),media={getTracks:()=>[{stop(){stops++;}}],getAudioTracks:()=>[{}]};
 const navigator={mediaDevices:{getUserMedia:async()=>media}};
 class Socket{
  static OPEN=1;constructor(){sockets.push(this);this.readyState=1;this.sent=[];queueMicrotask(()=>this.onopen());}
  send(raw){const v=JSON.parse(raw);this.sent.push(v);
   if(v.binding)queueMicrotask(()=>this.onmessage({data:JSON.stringify({type:'prepared',id:v.id,session_seconds:600})}));
   if(v.type==='offer')queueMicrotask(()=>this.onmessage({data:JSON.stringify({type:'answer',id:this.sent[0].id,sdp:'v=0 synthetic-answer'})}));
   if(v.type==='close')queueMicrotask(()=>this.onmessage({data:JSON.stringify({type:'closed',id:this.sent[0].id,confirmed:true})}));
  }
  close(){this.readyState=3;queueMicrotask(()=>this.onclose?.());}
 }
 class Peer{
  constructor(){peers.push(this);this.connectionState='new';}
  addTrack(){}async createOffer(){return {type:'offer',sdp:'v=0 synthetic-offer'};}
  async setLocalDescription(v){this.localDescription=v;}
  async setRemoteDescription(v){assert.equal(v.type,'answer');this.connectionState='connected';this.onconnectionstatechange();}
  close(){this.connectionState='closed';this.onconnectionstatechange?.();}
 }
 class Audio{play(){return Promise.resolve();}pause(){}}
 const store={list:async()=>[...records],put:async v=>{records.push(v);},remove:async v=>{const i=records.findIndex(r=>r.id===v.id);if(i>=0)records.splice(i,1);}};
 const window={RTCPeerConnection:Peer,indexedDB:{},location:{href:'https://example.test/interaction/'},
  VoiceInput:{recoveryStore:key=>{assert.equal(key,'codex_voice');return store;}},StreamingVoice:{supported:()=>true,
   wav(parts){return new Blob([new Uint8Array(44),...parts],{type:'audio/wav'});},
   openCapture:async()=>({subscribe(fn){listener=fn;return ()=>{};},start(){},finish(){listener({finished:true});},close(){}})}};
 async function fetch(url,options){
  requests.push({url:String(url),options});
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
 assert.equal(requests.length,1);assert(requests[0].url.includes('/voice/codex/visits/'));
 assert(!requests.some(r=>/transcrib|\/inputs/.test(r.url)));
 assert.deepEqual(sockets[0].sent.map(v=>v.type||'binding'),['binding','offer','close']);
 assert.equal(peers[0].connectionState,'closed');assert(stops>0);
 failUpload=true;assert.equal(await engine.start(),true);listener({pcm:new Uint8Array(32000).buffer});
 await engine.hold();assert.equal(records.length,1);assert.equal(recoveryValues.length,1);
 const original=records[0],digest=original.audio_sha256;
 assert.equal(engine.originals.length,0,'Native recordings must never enter ordinary Send recovery');
 failUpload=false;await engine.retry(original);
 assert.equal(records.length,0);assert.equal(original.audio_sha256,digest);
 assert.equal(requests.length,3);assert.equal(sockets.length,2,'Original retry opened another voice visit');
 assert(states.some(v=>v.pending));await sleep(0);
 assert.equal(engine.active,false,'Retired socket callback revived the visit');
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
fixture().catch(error=>{console.error(error);process.exitCode=1;});
