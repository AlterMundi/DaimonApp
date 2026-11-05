// Mounted avatar engine with synthetic PCM/devices: no browser microphone/model.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),crypto=require('node:crypto').webcrypto;
const tick=()=>new Promise(resolve=>setImmediate(resolve));
// WebCrypto completes on a worker thread; event-loop turns are not a deadline.
const until=async f=>{const deadline=performance.now()+2000;while(!f()){if(performance.now()>=deadline)throw Error('Expected native voice transition');await new Promise(resolve=>setTimeout(resolve,1));}};
function boot(android=false,pcmReady=true,overrides={}){
  const sockets=[],contexts=[],sources=[],retained=[],released=[],reviews=[],states=[],handoffs=[],timers=[],timings=[],reconnectReviews=[];let permissionCalls=0,questions={old:'v1'},listener;
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
  const track={readyState:'live',addEventListener(){},stop(){media.stopped=true;this.readyState='ended';}},media={stopped:false,getTracks(){return [track];}};
  const window={dispatchEvent(){return true;},crypto,AudioContext:Context,navigator:{mediaDevices:{getUserMedia:async()=>{permissionCalls++;return media;}}},StreamingVoice:{supported:()=>true,
    wav:parts=>new Blob(parts,{type:'audio/wav'}),openCapture:async(_media,options)=>{const source={options,subscribe(fn){listener=fn;return ()=>listener=undefined;},observe(){},start(){},close(){this.closed=true;},emit(value){listener?.(value);}};sources.push(source);return source;}}};
  const nativeCommands=[];
  if(android)window.DaimonAudio={postMessage(raw){const value=JSON.parse(raw);nativeCommands.push(value);if(value.command==='pcm_begin'&&pcmReady)queueMicrotask(()=>window.DaimonAudio.onmessage({data:JSON.stringify({id:value.id,type:'pcm_ready'})}));}};
  const context=vm.createContext({window,navigator:window.navigator,document:{hidden:false},crypto,WebSocket:Socket,URL,Blob,ArrayBuffer,Float32Array,Uint8Array,atob,btoa,Event,EventTarget,DOMException,
    setTimeout(fn,ms){const timer={fn,ms};timers.push(timer);return timer;},clearTimeout(timer){if(timer)timer.cleared=true;}});
  if(android)vm.runInContext(fs.readFileSync('clients/android/app/src/main/assets/native-audio.js','utf8'),context);
  vm.runInContext(fs.readFileSync('dashboard/web/native-conversation.js','utf8'),context);
  const hooks={prepareReconnect:async originals=>{assert(originals.every(v=>v.audio_sha256));reconnectReviews.push(originals);},headers:()=>({'X-Dashboard-CSRF':'fixture'}),getBinding:()=> 'a'.repeat(64),getQuestions:()=>questions,
    retain:async original=>{const hash=Buffer.from(await crypto.subtle.digest('SHA-256',await original.blob.arrayBuffer())).toString('hex');const value={...original,audio_sha256:hash};retained.push(value);return value;},
    release:async(original,hash)=>{assert.equal(hash,original.audio_sha256);released.push(original.id);},onReview:value=>reviews.push(value),onState:value=>states.push(value),onHandoff:value=>handoffs.push(value),onTiming:(id,stage)=>timings.push({id,stage})};
  // URL is intentionally the real application route shape, with a fake socket.
  window.location={href:'https://example.test/interaction/?view=conversation'};
  const engine=window.NativeConversation.create({...hooks,...overrides});
  return {reconnectReviews,engine,sockets,contexts,sources,retained,released,reviews,states,handoffs,timers,timings,media,nativeCommands,native:window.NativeSpeechAudio,nativeEvent(value){window.DaimonAudio.onmessage({data:JSON.stringify({id:nativeCommands.find(v=>v.command==='pcm_begin').id,...value})});},get permissionCalls(){return permissionCalls;},questions:value=>questions=value};
}
async function ready(value,diagnostics=false,mode='manual',seconds){const pending=value.engine.start();await until(()=>value.sockets[0]?.sent.length);assert.equal(value.permissionCalls,0,'Preflight precedes microphone acquisition');const socket=value.sockets[0],id=socket.sent[0].id;socket.push({type:'ready',id,activity_mode:mode,...(seconds===undefined?{}:{session_seconds:seconds}),...(diagnostics?{playback_status:true}:{})});assert.equal(await pending,true);return socket;}
(async()=>{
  const stalePlayback=boot(),staleWire=await ready(stalePlayback);
  staleWire.push({type:'audio',id:crypto.randomUUID(),end:640,pcm:Buffer.alloc(640,1).toString('base64'),sample_rate:24000});
  await until(()=>stalePlayback.contexts[0].nodes.length===1);
  const cancelled=stalePlayback.contexts[0].nodes[0];
  stalePlayback.engine.hold('Disconnected; retained originals stay available.');
  const afterHold=stalePlayback.states.length;
  cancelled.finish();
  assert.equal(stalePlayback.states.length,afterHold,'Cancelled audio completion must not publish over the terminal voice state');
  const long=boot(),longSocket=await ready(long,false,'manual',600);
  assert.equal(longSocket.sent[0].session_seconds,1800);
  assert.equal(long.sources[0].options.sessionSeconds,600);
  assert(long.timers.some(t=>t.ms===600000&&!t.cleared));
  let logical=0;
  for(let cycle=0;cycle<3;cycle++){
    for(let n=0;n<198;n++){long.sources[0].emit({pcm:new ArrayBuffer(32000)});logical+=32000;}
    const id=crypto.randomUUID(),start=logical;
    longSocket.push({type:'capture_started',id,start});await tick();
    for(let n=0;n<2;n++){long.sources[0].emit({pcm:new ArrayBuffer(32000)});logical+=32000;}
    longSocket.push({type:'phrase_end',id,start,end:logical});await until(()=>long.retained.length===cycle+1);
    assert.equal(long.retained[cycle].blob.size,64000,'Absolute PCM slices survive confirmed-prefix retirement');
    longSocket.push({type:'original_completed',id,sha256:long.retained[cycle].audio_sha256,phase:'foreground'});
    await until(()=>long.engine.originals.length===0);
    assert.equal(long.engine.active,true,'Confirmed prefix must retire before the next200second span');
  }
  assert.equal(logical,600*32000);long.engine.hold();
  const narrow=boot(true),narrowSocket=await ready(narrow);
  assert.equal(narrowSocket.sent[0].session_seconds,300,'Current native audio client narrows before provider setup');
  assert.equal(narrow.sources[0].options.sessionSeconds,300);narrow.engine.hold();
  const widened=boot(true),widening=widened.engine.start();
  await until(()=>widened.sockets[0]?.sent.length);
  widened.sockets[0].push({type:'ready',id:widened.sockets[0].sent[0].id,activity_mode:'manual',session_seconds:600});
  assert.equal(await widening,false);assert.equal(widened.permissionCalls,0,'Server cannot widen a native client cap before microphone acquisition');

  const quiet=boot(),quietWire=await ready(quiet,false,'manual',600);
  for(let n=0;n<299;n++)quiet.sources[0].emit({pcm:new ArrayBuffer(32000)});
  assert.equal(quiet.engine.active,false,'Unconfirmed resident tail ends before its300second hard bound');
  assert(quietWire.sent.some(v=>v.type==='close'&&v.recover_unassigned===true));
  const observed=boot(),observationSocket=await ready(observed,true),observationOutput=crypto.randomUUID();
  observationSocket.push({type:'audio',id:observationOutput,sample_rate:24000,end:640,pcm:Buffer.alloc(640,1).toString('base64')});
  await until(()=>observationSocket.sent.some(v=>v.type==='playback_status'&&v.handled===1));
  let observation=observationSocket.sent.filter(v=>v.type==='playback_status').at(-1);
  assert.equal(observation.scheduled,1);assert.equal(observation.ended,0);assert.equal(observation.context,'running');
  observed.contexts[0].state='interrupted';observed.contexts[0].onstatechange();
  assert.equal(observationSocket.sent.at(-1).context,'interrupted','An OS context interruption is distinct from generated/scheduled bytes');
  observed.engine.pause('media-session');assert.equal(observationSocket.sent.at(-1).user_paused,true);assert.equal(observed.states.at(-1).audioPaused,true);
  observed.engine.resume();await tick();assert.equal(observationSocket.sent.at(-1).user_paused,false);assert.equal(observed.states.at(-1).audioPaused,false);
  observed.engine.setEnabled(false);assert.equal(observed.states.at(-1).audioEnabled,false);
  observationSocket.push({type:'audio',id:crypto.randomUUID(),sample_rate:24000,end:640,pcm:Buffer.alloc(640,1).toString('base64')});
  await until(()=>observationSocket.sent.some(v=>v.type==='playback_status'&&v.skipped_muted===1));
  observation=observationSocket.sent.filter(v=>v.type==='playback_status').at(-1);assert.equal(observation.audible,false);assert.equal(observation.scheduled,1);
  for(let n=0;n<100;n++)observed.contexts[0].onstatechange();
  assert.equal(observationSocket.sent.filter(v=>v.type==='playback_status').length,32,'One dialogue has a fixed observation cap');
  observed.engine.hold();
  const oldReceiver=boot(),oldWire=await ready(oldReceiver);
  oldWire.push({type:'audio',id:crypto.randomUUID(),sample_rate:24000,end:640,pcm:Buffer.alloc(640,1).toString('base64')});await tick();
  assert.equal(oldWire.sent.some(v=>v.type==='playback_status'),false,'Older receivers never receive an unknown control');oldReceiver.engine.hold();
  const floorObservation=boot(),floorWire=await ready(floorObservation,true);floorObservation.sources[0].emit({pcm:new Uint8Array(3200).buffer});
  floorWire.push({type:'capture_started',id:crypto.randomUUID(),start:0});
  floorWire.push({type:'audio',id:crypto.randomUUID(),sample_rate:24000,end:640,pcm:Buffer.alloc(640,1).toString('base64')});
  await until(()=>floorWire.sent.some(v=>v.type==='playback_status'&&v.skipped_floor===1));
  assert.equal(floorWire.sent.filter(v=>v.type==='playback_status').at(-1).floor,true);assert.equal(floorObservation.states.at(-1).audioPaused,false,'Acoustic floor suspension is not a user pause');floorObservation.engine.hold();
  // Local loudness is not speech authority. Intermittent nonspeech with a
  // delayed classifier must never hold the entire response clock suspended.
  for(const native of [false,true]){
    const noise=boot(native),socket=await ready(noise),out=crypto.randomUUID();
    const packet=end=>({type:'audio',id:out,end,pcm:Buffer.alloc(640,1).toString('base64'),sample_rate:24000});
    socket.push(packet(640));await until(()=>noise.engine.hasAudio);
    for(let n=1;n<=5;n++){
      noise.sources[0].emit({activityBytes:n*6400,totalBytes:n*6400,pcm:new Uint8Array(3200).buffer});
      noise.sources[0].emit({activityBytes:n*6400,totalBytes:n*6400+3200});
      socket.push({type:'turn_activity',activity:{audio_bytes:(n-1)*6400,speaking:false}});
      await tick();assert.equal(noise.engine.paused,false,'Unconfirmed intermittent energy cannot mute native speech');
    }
    assert.equal(noise.engine.hasAudio,true);
    noise.engine.pause();socket.push({type:'turn_activity',activity:{audio_bytes:32000,speaking:false}});await tick();
    assert.equal(noise.engine.paused,true,'Analysis cannot override explicit Pause');
    noise.engine.resume();noise.engine.hold();
  }
  // A provider may generate PCM before its manual-end ACK. Preserve the
  // beginning while waiting for that ACK instead of hearing only a late tail.
  for(const confirmation of ['voice_activity','input_interpreted','input_uninterpreted'])for(const native of [false,true]){
    const early=boot(native),earlySocket=await ready(early,false,'automatic'),input=crypto.randomUUID(),output=crypto.randomUUID();
    early.sources[0].emit({pcm:new Uint8Array(3200).buffer});
    earlySocket.push({type:'capture_started',id:input,start:0});earlySocket.push({type:'phrase_end',id:input,start:0,end:3200});
    await until(()=>early.retained.length===1);
    const packet=end=>({type:'audio',id:output,end,pcm:Buffer.alloc(640,1).toString('base64'),sample_rate:24000});
    earlySocket.push(packet(640));earlySocket.push(packet(1280));await until(()=>early.engine.hasAudio);
    assert.equal(early.engine.paused,true,'Fresh response waits for the matching manual-end ACK');
    assert.equal(early.timings.some(t=>t.id===output&&t.stage==='output_progress'),false);
    if(confirmation!=='input_uninterpreted')earlySocket.push({type:confirmation,id:crypto.randomUUID(),activity:'ACTIVITY_END',text:'Old phrase',reason:'empty_final_transcript'});await tick();
    assert.equal(early.engine.paused,true,'An unrelated input confirmation cannot release output');
    early.engine.pause();earlySocket.push({type:confirmation,id:input,activity:'ACTIVITY_END',text:'Exact phrase',reason:'empty_final_transcript'});await tick();
    assert.equal(early.engine.paused,true,'Input confirmation cannot override the human Pause');
    early.engine.resume();await until(()=>!early.engine.paused);
    if(!native)assert.equal(early.contexts[0].state,'running');
    if(native){await until(()=>early.nativeCommands.filter(v=>v.command==='pcm_chunk').length===2);early.nativeEvent({type:'pcm_progress',positions:[{utterance:output,played_bytes:1280}]});}
    else{assert.equal(early.contexts[0].nodes.length,2,'Both pre-ACK buffers survive');for(const node of early.contexts[0].nodes)node.finish();}
    assert(earlySocket.sent.some(v=>v.type==='playback'&&v.id===output&&v.played_bytes===1280),'Playback includes the first PCM, not only a post-ACK tail');
    early.engine.hold();
  }
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
  socket.push({type:'input_interpreted',id:first,text:'Late previous phrase'});await tick();assert.equal(value.engine.paused,true,'Late interpretation cannot resume during a newer capture');
  socket.push({type:'phrase_end',id:second,start:6400,end:9600});await until(()=>value.retained.length===2);
  socket.push({type:'voice_activity',id:first,activity:'ACTIVITY_END'});socket.push(audio(1920));await tick();assert.equal(value.contexts[0].nodes.length,1,'An earlier phrase ACK cannot release stale audio');
  socket.push({type:'voice_activity',id:second,activity:'ACTIVITY_END'});socket.push({type:'audio',id:crypto.randomUUID(),end:640,pcm:Buffer.alloc(640,1).toString('base64'),sample_rate:24000});await until(()=>value.contexts[0].nodes.length===2);
  value.engine.hold();await tick();assert.equal(value.engine.active,false);assert.equal(value.media.stopped,true);assert.equal(value.contexts[0].state,'closed');assert.equal(value.engine.originals.length,1,'Only unconfirmed original remains for recovery');assert.equal(value.engine.originals[0].id,second);
  assert.equal(value.states.at(-1).pending,true,'Stopping with an unconfirmed original must expose review in the avatar');
  assert.equal(value.handoffs.at(-1).gate,'review','The detector badge must not keep claiming Voice detected after recovery begins');
  assert.ok(value.timers.every(t=>t.cleared),'Readiness/session timers are cleared');
  assert.deepEqual(value.timings.filter(t=>t.id===first).map(t=>t.stage),['capture_started','phrase_end','local_retained','original_confirmed','input_interpreted']);
  assert.ok(value.timings.some(t=>t.id===output&&t.stage==='output_handled'));assert.ok(value.timings.some(t=>t.id===output&&t.stage==='output_scheduled'));assert.ok(value.timings.some(t=>t.id===output&&t.stage==='output_retired'));
  assert.equal(value.timings.some(t=>t.id===output&&t.stage==='output_buffer_ended'),false,'A retired queued source cannot report a completed buffer');
  // Upload backlog, a remote close and invalid capture bytes are distinct
  // failures; none discards the valid original already captured before it.
  for(const reason of ['backlog','closed','invalid']){
    const failed=boot(),wire=await ready(failed),id=crypto.randomUUID();
    failed.sources[0].emit({pcm:new Uint8Array(3200).buffer});
    wire.push({type:'capture_started',id,start:0});await tick();
    if(reason==='backlog')wire.bufferedAmount=256001;
    if(reason==='closed')wire.readyState=3;
    failed.sources[0].emit({pcm:reason==='invalid'?new Uint8Array(3200):new Uint8Array(3200).buffer});
    await until(()=>failed.retained.length===1);
    assert.equal(failed.engine.active,false);assert.equal(failed.engine.originals.length,1);
    assert.equal(failed.retained[0].blob.size,reason==='invalid'?3200:6400,'Every valid frame already captured at a transport failure remains in the local original');
    const message=failed.states.at(-1).message;
    assert(message.startsWith({backlog:'Voice upload is delayed',closed:'Voice connection closed',invalid:'Voice capture returned invalid audio'}[reason]),message);
  }
  const refused=boot(),pending=refused.engine.start();await until(()=>refused.sockets.length===1);refused.sockets[0].push({type:'review',message:'Listener unsupported'});assert.equal(await pending,false);assert.equal(refused.permissionCalls,0);
  const scoped=boot();scoped.questions({['a'.repeat(32)]:'b'.repeat(64)});const scopedSocket=await ready(scoped);
  scopedSocket.push({type:'question_scope',binding:'a'.repeat(64),capture_questions:{['c'.repeat(32)]:'d'.repeat(64)}});await tick();
  scoped.sources[0].emit({activityBytes:3200,pcm:frame()});
  const frozen=scopedSocket.sent.find(v=>v.type==='capture_scope');
  assert.equal(frozen.capture_questions['c'.repeat(32)],'d'.repeat(64),'A voiced canonical question is available before ordinary UI refresh');
  assert.equal(frozen.capture_questions['a'.repeat(32)],undefined,'The current canonical snapshot replaces a stale UI scope');
  scopedSocket.push({type:'question_scope',binding:'a'.repeat(64),capture_questions:{['c'.repeat(32)]:'e'.repeat(64)}});await tick();
  const scopedId=crypto.randomUUID();scopedSocket.push({type:'capture_started',id:scopedId,start:0});scopedSocket.push({type:'phrase_end',id:scopedId,start:0,end:3200});
  await until(()=>scoped.retained.length===1);assert.equal(scoped.retained[0].captureQuestions['c'.repeat(32)],'d'.repeat(64),'Later question versions cannot widen an already marked phrase');scoped.engine.hold();
  const fallback=boot();fallback.questions({['a'.repeat(32)]:'b'.repeat(64)});const fallbackSocket=await ready(fallback);
  fallbackSocket.push({type:'question_scope',binding:'a'.repeat(64),capture_questions:{['c'.repeat(32)]:'d'.repeat(64)}});await tick();fallback.sources[0].emit({pcm:frame()});
  const fallbackId=crypto.randomUUID();fallbackSocket.push({type:'capture_started',id:fallbackId,start:0});fallbackSocket.push({type:'phrase_end',id:fallbackId,start:0,end:3200});
  await until(()=>fallback.retained.length===1);assert.equal(fallback.retained[0].captureQuestions['a'.repeat(32)],'b'.repeat(64));assert.equal(fallback.retained[0].captureQuestions['c'.repeat(32)],undefined,'Without a local marker, the earlier arm-time fallback remains frozen');fallback.engine.hold();
  const android=boot(true),androidSocket=await ready(android);
  assert.equal(android.contexts.length,0,'APK PCM uses the existing native owner rather than a second Web Audio output');
  const androidOutput=crypto.randomUUID();androidSocket.push({type:'audio',id:androidOutput,end:640,pcm:Buffer.alloc(640,1).toString('base64'),sample_rate:24000});
  await until(()=>android.nativeCommands.some(v=>v.command==='pcm_chunk'));
  assert.equal(android.engine.hasAudio,true);android.engine.pause();assert.equal(android.engine.paused,true);android.engine.resume();
  android.nativeEvent({type:'pcm_progress',positions:[{utterance:androidOutput,played_bytes:320}]});
  assert.ok(androidSocket.sent.some(v=>v.type==='playback'&&v.id===androidOutput&&v.played_bytes===320));
  assert.ok(android.timings.some(t=>t.id===androidOutput&&t.stage==='output_progress'),'Native positive progress, not queued PCM, produces the playback observation');
  android.sources[0].emit({activityBytes:3200,pcm:frame()});
  assert.equal(android.engine.hasAudio,true);assert.equal(android.engine.paused,false);
  const androidInput=crypto.randomUUID();androidSocket.push({type:'capture_started',id:androidInput,start:0});await until(()=>!android.engine.hasAudio);
  assert.ok(android.nativeCommands.some(v=>v.command==='pcm_flush'));
  const chunksBefore=android.nativeCommands.filter(v=>v.command==='pcm_chunk').length;
  androidSocket.push({type:'audio',id:androidOutput,end:1280,pcm:Buffer.alloc(640,1).toString('base64'),sample_rate:24000});await tick();
  assert.equal(android.nativeCommands.filter(v=>v.command==='pcm_chunk').length,chunksBefore,'An interrupted utterance tail cannot reacquire native focus');
  androidSocket.push({type:'phrase_end',id:androidInput,start:0,end:3200});
  await until(()=>android.retained.length===1);androidSocket.push({type:'voice_activity',id:androidInput,activity:'ACTIVITY_END'});androidSocket.push({type:'turn_activity',activity:{audio_bytes:3200,speaking:false}});
  const fresh=crypto.randomUUID();androidSocket.push({type:'audio',id:fresh,end:40000,pcm:Buffer.alloc(40000,3).toString('base64'),sample_rate:24000});
  await until(()=>android.nativeCommands.filter(v=>v.command==='pcm_chunk').length===chunksBefore+2);
  const sent=android.nativeCommands.filter(v=>v.command==='pcm_chunk');
  assert.deepEqual(sent.map(v=>v.sequence),[0,1,2]);assert.deepEqual(sent.slice(1).map(v=>v.end),[32768,40000]);
  for(const chunk of sent){const raw=Buffer.from(chunk.data,'base64');assert(raw.length<=32768);assert.equal(chunk.sha256,require('node:crypto').createHash('sha256').update(raw).digest('hex'));}
  android.nativeEvent({type:'pcm_progress',positions:[{utterance:fresh,played_bytes:40000}]});assert.equal(android.engine.hasAudio,false);
  assert.ok(android.timings.some(v=>v.id===fresh&&v.stage==='output_buffer_ended'));
  android.native.background(true);await tick();assert.equal(android.engine.active,false);assert.equal(android.media.stopped,true);
  assert.equal(android.engine.originals[0].id,androidInput,'Background closes native voice and preserves the exact unconfirmed original');
  const interruptedReady=boot(true,false),opening=interruptedReady.engine.start();
  await until(()=>interruptedReady.nativeCommands.some(v=>v.command==='pcm_begin'));interruptedReady.native.background(true);
  assert.equal(await opening,false);assert.equal(interruptedReady.permissionCalls,0);assert.equal(interruptedReady.sockets.length,0,'Background during native readiness never opens a model socket or microphone');
  const focusLoss=boot(true),focusSocket=await ready(focusLoss);focusLoss.nativeEvent({type:'focuslost'});await tick();
  assert.equal(focusLoss.engine.active,false);assert.equal(focusLoss.media.stopped,true);assert.equal(focusSocket.readyState,3,'Focus loss closes voice rather than fighting another app');
  const recovery=boot(),oldSocket=await ready(recovery),originalId=crypto.randomUUID();
  oldSocket.push({type:'capture_started',id:originalId,start:0});await tick();
  recovery.sources[0].emit({pcm:new ArrayBuffer(3200)});
  oldSocket.push({type:'phrase_end',id:originalId,start:0,end:3200});
  await until(()=>recovery.retained[0]?.audio_sha256);
  const oldDialogue=oldSocket.sent[0].id;
  oldSocket.push({type:'review',message:'Voice ended.'});await until(()=>!recovery.engine.active);
  assert.equal(recovery.sockets.length,1,'An unexpected close never reconnects automatically');
  const again=recovery.engine.reconnect();
  assert.equal(recovery.contexts.length,2,'Reconnect unlocks audio in the explicit gesture');
  await until(()=>recovery.sockets[1]?.sent.length);
  const successor=recovery.sockets[1],meta=successor.sent[0];
  assert.notEqual(meta.id,oldDialogue);assert.equal(meta.reconnect.previous_dialogue,oldDialogue);
  assert.equal(meta.reconnect.cause,'server_review');assert.equal(meta.reconnect.audio_bytes,3200);
  assert.equal(recovery.reconnectReviews[0][0].id,originalId);
  assert.equal(recovery.released.length,0,'Reconnect never confirms or discards an old original');
  assert.equal(recovery.permissionCalls,1,'New microphone waits for fresh owner preflight');
  successor.push({type:'reconnect_recorded'});successor.push({type:'ready',id:meta.id,activity_mode:'manual'});
  assert.equal(await again,true);assert.equal(recovery.permissionCalls,2);
  assert.equal(successor.sent.filter(v=>v instanceof ArrayBuffer).length,0,'Old captured audio is never replayed');
  oldSocket.push({type:'review',message:'Late old close'});await tick();assert(recovery.engine.active);
  recovery.engine.hold();
  const preparing=boot(),previousSocket=await ready(preparing),previousDialogue=previousSocket.sent[0].id;
  preparing.engine.hold();
  const attempt=preparing.engine.reconnect();await until(()=>preparing.sockets[1]?.sent.length);
  preparing.sockets[1].push({type:'context_preparing'});await tick();
  assert(preparing.states.some(v=>v.message==='Keeping our conversation ready…'));
  assert.equal(preparing.permissionCalls,1,'Compaction preparation must not acquire another microphone');
  preparing.sockets[1].push({type:'review',message:'The conversation is still being prepared.'});
  assert.equal(await attempt,false);
  const retry=preparing.engine.reconnect();await until(()=>preparing.sockets[2]?.sent.length);
  const retryMeta=preparing.sockets[2].sent[0];
  assert.equal(retryMeta.reconnect.previous_dialogue,previousDialogue,'Retry keeps the last established context, not a nonexistent failed producer');
  preparing.sockets[2].push({type:'ready',id:retryMeta.id,activity_mode:'manual'});
  assert.equal(await retry,true);preparing.engine.hold();
  const neverReady=boot(),initial=neverReady.engine.start();await until(()=>neverReady.sockets[0]?.sent.length);
  neverReady.sockets[0].push({type:'review',message:'Provider unavailable'});assert.equal(await initial,false);
  const newAttempt=neverReady.engine.reconnect();await until(()=>neverReady.sockets[1]?.sent.length);
  assert.equal(neverReady.sockets[1].sent[0].reconnect,undefined,'A first failed preflight has no prior context to restore');
  neverReady.sockets[1].push({type:'ready',id:neverReady.sockets[1].sent[0].id,activity_mode:'manual'});
  assert.equal(await newAttempt,true);neverReady.engine.hold();
  // Already-running old work must neither block nor close a new epoch.
  for(const outcome of ['success','failure']){
    let complete,entered=false;
    const delayed=boot(false,true,{release:()=>{entered=true;return new Promise((resolve,reject)=>{complete=()=>outcome==='failure'?reject(Error('Old storage failure')):resolve();});}});
    const wire=await ready(delayed),id=crypto.randomUUID();
    delayed.sources[0].emit({pcm:new ArrayBuffer(3200)});
    wire.push({type:'capture_started',id,start:0});wire.push({type:'phrase_end',id,start:0,end:3200});
    await until(()=>delayed.retained[0]?.audio_sha256);
    wire.push({type:'original_completed',id,sha256:delayed.retained[0].audio_sha256,phase:'foreground'});
    await until(()=>entered);delayed.engine.hold('Synthetic old close');
    const connecting=delayed.engine.reconnect();await until(()=>delayed.sockets[1]?.sent.length);
    const fresh=delayed.sockets[1];fresh.push({type:'ready',id:fresh.sent[0].id,activity_mode:'manual'});
    assert.equal(await connecting,true);
    const output=crypto.randomUUID();fresh.push({type:'audio',id:output,end:640,pcm:Buffer.alloc(640,1).toString('base64'),sample_rate:24000});
    await until(()=>delayed.contexts[1].nodes.length===1);
    assert(delayed.engine.active,'New events do not wait on an old storage promise');
    complete();await tick();await tick();
    assert(delayed.engine.active,'A late old completion or failure cannot close the successor');
    assert.equal(delayed.engine.originals.length,0,'An old event cannot mutate successor original state');
    delayed.engine.hold();
  }
  console.log('Native avatar: owner preflight before mic, exact recovery/ACK, frozen scope, native PCM controls, interruption generation fences and cleanup passed; no real devices/models.');
})().catch(error=>{console.error(error);process.exitCode=1;});
