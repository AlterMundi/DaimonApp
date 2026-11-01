// Mounted avatar engine with synthetic PCM/devices: no browser microphone/model.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),crypto=require('node:crypto').webcrypto;
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const until=async f=>{for(let i=0;i<100;i++){if(f())return;await tick();}throw Error('Expected native voice transition');};
function boot(){
  const sockets=[],contexts=[],sources=[],retained=[],released=[],reviews=[],states=[],handoffs=[],timers=[];let permissionCalls=0,questions={old:'v1'},listener;
  class Socket{
    static OPEN=1;
    constructor(){this.readyState=1;this.sent=[];this.bufferedAmount=0;sockets.push(this);queueMicrotask(()=>this.onopen?.());}
    send(value){this.sent.push(typeof value==='string'?JSON.parse(value):value);}
    push(value){this.onmessage({data:JSON.stringify(value)});}
    close(){this.readyState=3;queueMicrotask(()=>this.onclose?.());}
  }
  class Context{
    constructor(){this.currentTime=0;this.state='running';this.destination={};this.nodes=[];contexts.push(this);}
    resume(){this.state='running';return Promise.resolve();}suspend(){this.state='suspended';return Promise.resolve();}close(){this.state='closed';return Promise.resolve();}
    createBuffer(_channels,length,rate){return {duration:length/rate,copyToChannel(){}};}
    createBufferSource(){const value={connect(){},disconnect(){},start(at){this.at=at;},stop(){this.stopped=true;},finish(){this.onended?.();}};this.nodes.push(value);return value;}
  }
  const media={stopped:false,getTracks(){return [{stop:()=>media.stopped=true}];}};
  const window={crypto,AudioContext:Context,navigator:{mediaDevices:{getUserMedia:async()=>{permissionCalls++;return media;}}},StreamingVoice:{supported:()=>true,
    wav:parts=>new Blob(parts,{type:'audio/wav'}),openCapture:async()=>{const source={subscribe(fn){listener=fn;return ()=>listener=undefined;},observe(){},start(){},close(){this.closed=true;},emit(value){listener?.(value);}};sources.push(source);return source;}}};
  const context=vm.createContext({window,navigator:window.navigator,document:{hidden:false},crypto,WebSocket:Socket,URL,Blob,ArrayBuffer,Float32Array,atob,
    setTimeout(fn,ms){const timer={fn,ms};timers.push(timer);return timer;},clearTimeout(timer){if(timer)timer.cleared=true;}});
  vm.runInContext(fs.readFileSync('dashboard/web/native-conversation.js','utf8'),context);
  const hooks={headers:()=>({'X-Dashboard-CSRF':'fixture'}),getBinding:()=> 'a'.repeat(64),getQuestions:()=>questions,
    retain:async original=>{const hash=Buffer.from(await crypto.subtle.digest('SHA-256',await original.blob.arrayBuffer())).toString('hex');const value={...original,audio_sha256:hash};retained.push(value);return value;},
    release:async(original,hash)=>{assert.equal(hash,original.audio_sha256);released.push(original.id);},onReview:value=>reviews.push(value),onState:value=>states.push(value),onHandoff:value=>handoffs.push(value)};
  // URL is intentionally the real application route shape, with a fake socket.
  window.location={href:'https://example.test/interaction/?view=conversation'};
  const engine=window.NativeConversation.create(hooks);
  return {engine,sockets,contexts,sources,retained,released,reviews,states,handoffs,timers,media,get permissionCalls(){return permissionCalls;},questions:value=>questions=value};
}
async function ready(value){const pending=value.engine.start();await until(()=>value.sockets[0]?.sent.length);assert.equal(value.permissionCalls,0,'Preflight precedes microphone acquisition');const socket=value.sockets[0],id=socket.sent[0].id;socket.push({type:'ready',id,activity_mode:'manual'});assert.equal(await pending,true);return socket;}
(async()=>{
  const value=boot(),socket=await ready(value);assert.equal(value.permissionCalls,1);
  value.questions({later:'v2'});
  const frame=()=>new Uint8Array(3200).buffer;value.sources[0].emit({pcm:frame()});value.sources[0].emit({pcm:frame()});
  const first=crypto.randomUUID();socket.push({type:'capture_started',id:first,start:0});socket.push({type:'phrase_end',id:first,start:0,end:6400});
  await until(()=>value.retained.length===1);assert.equal(value.retained[0].blob.size,6400);assert.equal(value.retained[0].captureQuestions.old,'v1');assert.equal(value.retained[0].captureQuestions.later,undefined,'Scope cannot widen after arming');
  socket.push({type:'original_retained',id:first,sha256:value.retained[0].audio_sha256});await tick();assert.equal(value.released.length,0,'Raw WAV retention does not retire the local original before its text is confirmed');
  socket.push({type:'original_completed',id:first,sha256:value.retained[0].audio_sha256,phase:'foreground'});await until(()=>value.released.length===1);
  socket.push({type:'voice_activity',id:first,activity:'ACTIVITY_END'});
  const output=crypto.randomUUID(),audio=end=>({type:'audio',id:output,end,pcm:Buffer.alloc(640,1).toString('base64'),sample_rate:24000});
  socket.push(audio(640));await until(()=>value.contexts[0].nodes.length===1);assert.equal(value.engine.hasAudio,true);
  value.engine.pause();await tick();assert.equal(value.engine.paused,true);value.engine.resume();await tick();assert.equal(value.engine.paused,false);
  const second=crypto.randomUUID();value.sources[0].emit({pcm:frame()});socket.push({type:'capture_started',id:second,start:6400});socket.push(audio(1280));
  await tick();assert.equal(value.contexts[0].nodes[0].stopped,true);assert.equal(value.contexts[0].nodes.length,1,'Queued old output cannot restart during interruption');
  socket.push({type:'phrase_end',id:second,start:6400,end:9600});await until(()=>value.retained.length===2);
  socket.push({type:'voice_activity',id:first,activity:'ACTIVITY_END'});socket.push(audio(1920));await tick();assert.equal(value.contexts[0].nodes.length,1,'An earlier phrase ACK cannot release stale audio');
  socket.push({type:'voice_activity',id:second,activity:'ACTIVITY_END'});socket.push({type:'audio',id:crypto.randomUUID(),end:640,pcm:Buffer.alloc(640,1).toString('base64'),sample_rate:24000});await until(()=>value.contexts[0].nodes.length===2);
  value.engine.hold();await tick();assert.equal(value.engine.active,false);assert.equal(value.media.stopped,true);assert.equal(value.contexts[0].state,'closed');assert.equal(value.engine.originals.length,1,'Only unconfirmed original remains for recovery');assert.equal(value.engine.originals[0].id,second);
  assert.ok(value.timers.every(t=>t.cleared),'Readiness/session timers are cleared');
  const refused=boot(),pending=refused.engine.start();await until(()=>refused.sockets.length===1);refused.sockets[0].push({type:'review',message:'Listener unsupported'});assert.equal(await pending,false);assert.equal(refused.permissionCalls,0);
  console.log('Native avatar: owner preflight before mic, exact recovery/ACK, frozen scope, native PCM controls, interruption generation fences and cleanup passed; no real devices/models.');
})().catch(error=>{console.error(error);process.exitCode=1;});
