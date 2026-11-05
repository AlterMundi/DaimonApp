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
  createDataChannel(label){this.channel={label,closed:false,close(){this.closed=true;}};return this.channel;}
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
 assert.equal(peers[0].channel.label,'oai-events');assert(peers[0].channel.closed);
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
(async()=>{await fixture();await historyFixture();})().catch(error=>{console.error(error);process.exitCode=1;});
