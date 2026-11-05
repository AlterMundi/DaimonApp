// Real browser audio nodes; synthetic socket/capture only, no physical device.
(async()=>{
 async function bounded(promise,stage){
  let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Synthetic audio stage did not finish: '+stage)),10000);})]);}finally{clearTimeout(timer);}
 }
 async function render(gap){
 const rate=48000,sockets=[],contexts=[];let captureListener,stopped=false,interruptions=0;
 class OfflineDevice{
  constructor(){this.audio=new OfflineAudioContext(1,rate,rate);this.destination=this.audio.destination;contexts.push(this);}
  get currentTime(){return this.audio.currentTime;}get state(){return this.audio.state;}
  createBuffer(...args){return this.audio.createBuffer(...args);}createBufferSource(){return this.audio.createBufferSource();}
  // The fixture driver itself suspends OfflineAudioContext at the marker.
  async suspend(){}async resume(){}async close(){}
 }
 class Socket{
  static OPEN=1;
  constructor(){this.readyState=1;this.sent=[];sockets.push(this);queueMicrotask(()=>this.onopen?.());}
  send(raw){if(typeof raw!=='string')return;const value=JSON.parse(raw);this.sent.push(value);if(value.binding)queueMicrotask(()=>this.push({type:'ready',id:value.id,activity_mode:'manual'}));}
  push(value){this.onmessage({data:JSON.stringify(value)});}close(){this.readyState=3;queueMicrotask(()=>this.onclose?.());}
 }
 const media={getTracks:()=>[{stop:()=>stopped=true}]},navigator={mediaDevices:{getUserMedia:async()=>media}};
 const fake={navigator,crypto:{randomUUID:()=> '22222222-2222-4222-8222-222222222222'},AudioContext:OfflineDevice,
  location:{href:'https://example.test/interaction/'},StreamingVoice:{supported:()=>true,wav:parts=>new Blob(parts),
   openCapture:async()=>({subscribe(fn){captureListener=fn;return ()=>captureListener=undefined;},observe(){},start(){},close(){}})}};
 const api=new Function('window','navigator','document','crypto','WebSocket',__NATIVE_SOURCE__+';return window.NativeConversation;')(fake,navigator,{hidden:false},fake.crypto,Socket);
 const engine=api.create({headers:()=>({}),getBinding:()=> 'a'.repeat(64),retain:async value=>value,release:async()=>{},onInterrupt:()=>interruptions++});
 const pcm=seconds=>{let raw='';for(let i=0;i<seconds*24000;i++){const n=Math.round(.25*32767*Math.sin(2*Math.PI*440*i/24000));raw+=String.fromCharCode(n&255,(n>>8)&255);}return btoa(raw);};
 try{
  if(!await engine.start())throw Error('Synthetic capture did not start');
  const socket=sockets[0],device=contexts[0],id='11111111-1111-4111-8111-111111111111';
  socket.push({type:'audio',id,sample_rate:24000,pcm:pcm(gap?.08:.4),end:gap?3840:19200});
  if(!gap)socket.push({type:'audio',id,sample_rate:24000,pcm:pcm(.4),end:38400});
  await new Promise(resolve=>setTimeout(resolve,0));
  let marker;const failures=[];
  device.audio.suspend(gap?.22:.15).then(async()=>{try{
   marker=device.currentTime;if(gap&&engine.hasAudio)throw Error('Expected a real gap before interruption');captureListener({activityBytes:640,pcm:new Uint8Array(640).buffer});
   socket.push({type:'capture_started',id:'44444444-4444-4444-8444-444444444444',start:0});
   // Confirmed speech retires the old utterance, including chunks in flight.
   socket.push({type:'audio',id,sample_rate:24000,pcm:pcm(.3),end:gap?18240:52800});
   await new Promise(resolve=>setTimeout(resolve,0));
  }catch(error){failures.push(error);}finally{await device.audio.resume();}
  });
  device.audio.suspend(.6).then(async()=>{try{
   socket.push({type:'phrase_end',id:'44444444-4444-4444-8444-444444444444',start:0,end:640});
   await new Promise(resolve=>setTimeout(resolve,0));
   socket.push({type:'voice_activity',id:'44444444-4444-4444-8444-444444444444',activity:'ACTIVITY_END'});
   socket.push({type:'turn_activity',activity:{audio_bytes:640,speaking:false}});
   socket.push({type:'audio',id:'33333333-3333-4333-8333-333333333333',sample_rate:24000,pcm:pcm(.2),end:9600});
   await new Promise(resolve=>setTimeout(resolve,0));
  }catch(error){failures.push(error);}finally{await device.audio.resume();}
  });
  const data=(await bounded(device.audio.startRendering(),'offline interruption gap='+gap)).getChannelData(0);
  if(failures.length)throw failures[0];
  let beforePeak=0,afterPeak=0,freshVoicePeak=0,lastNonzero=0;
  for(let i=0;i<data.length;i++){
   const at=i/rate,amplitude=Math.abs(data[i]);
   if(at>.03&&at<.12)beforePeak=Math.max(beforePeak,amplitude);
   if(at>marker+.03&&at<.58)afterPeak=Math.max(afterPeak,amplitude);
   if(at>.65&&at<.75)freshVoicePeak=Math.max(freshVoicePeak,amplitude);
   if(at<.58&&amplitude>1e-6)lastNonzero=at;
  }
  const playedBytes=Math.max(0,...socket.sent.filter(value=>value.type==='playback'&&value.id===id).map(value=>value.played_bytes));
  const result={nativeOfflineAudio:true,physicalPlayback:false,microphoneOpened:false,sampleRate:rate,
   gap,playedBytes,markerSeconds:marker,beforePeak,afterPeak,freshVoicePeak,lastNonzeroSeconds:lastNonzero,markerToLastNonzeroMillis:Math.max(0,(lastNonzero-marker)*1000),interruptions};
  if(beforePeak<.1||interruptions!==1)throw Error('Missing rendered interruption baseline '+JSON.stringify(result));
  if(playedBytes>Math.ceil(marker*48000))throw Error('Queued unheard PCM reported as played '+JSON.stringify(result));
  if(afterPeak>1e-6)throw Error('Confirmed interrupted native audio restarted '+JSON.stringify(result));
  if(freshVoicePeak<.1)throw Error('Interrupted audio blocked a fresh utterance '+JSON.stringify(result));
  return result;
 }finally{engine.hold();if(!stopped)throw Error('Synthetic capture cleanup did not stop its track');}
 }
 async function provisional(){
  let listener,device,socket;const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  class Output extends AudioContext{constructor(){super({sinkId:{type:'none'}});device=this;}}
  class Socket{
   static OPEN=1;constructor(){socket=this;this.readyState=1;this.bufferedAmount=0;this.sent=[];queueMicrotask(()=>this.onopen());}
   send(raw){if(typeof raw!=='string')return;const v=JSON.parse(raw);this.sent.push(v);if(v.binding)queueMicrotask(()=>this.push({type:'ready',id:v.id,activity_mode:'manual'}));}
   push(v){this.onmessage({data:JSON.stringify(v)});}close(){this.readyState=3;}
  }
  const nav={mediaDevices:{getUserMedia:async()=>({getTracks:()=>[{stop(){}}]})}};
  const ownedCrypto={randomUUID:()=> '66666666-6666-4666-8666-666666666666'};
  const fake={AudioContext:Output,navigator:nav,crypto:ownedCrypto,location:{href:'https://example.test/interaction/'},StreamingVoice:{supported:()=>true,
   openCapture:async()=>({subscribe(fn){listener=fn;return ()=>{};},observe(){},start(){},close(){}})}};
  const api=new Function('window','navigator','document','crypto','WebSocket',__NATIVE_SOURCE__+';return window.NativeConversation;')(fake,nav,{hidden:false},ownedCrypto,Socket);
  const engine=api.create({headers:()=>({}),getBinding:()=> 'a'.repeat(64)}),id='55555555-5555-4555-8555-555555555555';
  const packet=end=>({type:'audio',id,end,sample_rate:24000,pcm:btoa(String.fromCharCode(...new Uint8Array(9600).fill(1)))});
  try{
   if(!await bounded(engine.start(),'synthetic output start'))throw Error('Realtime output did not start');
   socket.push(packet(9600));await wait(40);if(device.state!=='running')throw Error('Output did not run');
   const at=device.currentTime;
   // Intermittent loudness and delayed nonspeech verdicts cannot suspend audio.
   for(let n=1;n<=4;n++){
    listener({activityBytes:n*640,totalBytes:n*640});
    listener({activityBytes:n*640,totalBytes:n*640+3200});
    socket.push({type:'turn_activity',activity:{audio_bytes:(n-1)*640,speaking:false}});
    await wait(30);
    if(device.state!=='running')throw Error('Unconfirmed noise suspended the output clock');
   }
   socket.push(packet(19200));await wait(60);
   if(device.currentTime<=at)throw Error('Output clock stopped during nonspeech');
   await wait(500);
   if(!socket.sent.some(v=>v.type==='playback'&&v.id===id&&v.played_bytes===19200))throw Error('Same utterance did not finish after nonspeech recovery');
   return {actualAudioContext:true,physicalPlayback:false,microphoneOpened:false,unconfirmedNoiseCannotPause:true,sameUtterancePlayedBytes:19200};
  }finally{engine.hold();}
 }
 return {nativeOfflineAudio:true,physicalPlayback:false,microphoneOpened:false,cases:[await render(false),await render(true)],provisional:await provisional()};
})()
