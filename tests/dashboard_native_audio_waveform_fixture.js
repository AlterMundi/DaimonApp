// Real browser audio nodes; synthetic socket/capture only, no physical device.
(async()=>{
 async function render(gap){
 const rate=48000,sockets=[],contexts=[];let captureListener,stopped=false,interruptions=0;
 class OfflineDevice{
  constructor(){this.audio=new OfflineAudioContext(1,rate,rate);this.destination=this.audio.destination;contexts.push(this);}
  get currentTime(){return this.audio.currentTime;}get state(){return this.audio.state;}
  createBuffer(...args){return this.audio.createBuffer(...args);}createBufferSource(){return this.audio.createBufferSource();}
  async resume(){}async close(){}
 }
 class Socket{
  static OPEN=1;
  constructor(){this.readyState=1;this.sent=[];sockets.push(this);queueMicrotask(()=>this.onopen?.());}
  send(raw){const value=JSON.parse(raw);this.sent.push(value);if(value.binding)queueMicrotask(()=>this.push({type:'ready',id:value.id,activity_mode:'manual'}));}
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
  socket.push({type:'audio',id,sample_rate:24000,pcm:pcm(gap?.08:.8),end:gap?3840:38400});
  await new Promise(resolve=>setTimeout(resolve,0));
  let marker;
  device.audio.suspend(.15).then(async()=>{
   marker=device.currentTime;if(gap&&engine.hasAudio)throw Error('Expected a real gap before interruption');captureListener({activityBytes:640});
   // The server has not confirmed an onset yet. Old chunks still arrive.
   socket.push({type:'audio',id,sample_rate:24000,pcm:pcm(.3),end:gap?18240:52800});
   await new Promise(resolve=>setTimeout(resolve,0));await device.audio.resume();
  });
  device.audio.suspend(.6).then(async()=>{
   socket.push({type:'audio',id:'33333333-3333-4333-8333-333333333333',sample_rate:24000,pcm:pcm(.2),end:9600});
   await new Promise(resolve=>setTimeout(resolve,0));await device.audio.resume();
  });
  const data=(await device.audio.startRendering()).getChannelData(0);
  let beforePeak=0,afterPeak=0,freshVoicePeak=0,lastNonzero=0;
  for(let i=0;i<data.length;i++){
   const at=i/rate,amplitude=Math.abs(data[i]);
   if(at>.03&&at<.12)beforePeak=Math.max(beforePeak,amplitude);
   if(at>marker+.03&&at<.58)afterPeak=Math.max(afterPeak,amplitude);
   if(at>.65&&at<.75)freshVoicePeak=Math.max(freshVoicePeak,amplitude);
   if(at<.58&&amplitude>1e-6)lastNonzero=at;
  }
  const result={nativeOfflineAudio:true,physicalPlayback:false,microphoneOpened:false,sampleRate:rate,
   gap,markerSeconds:marker,beforePeak,afterPeak,freshVoicePeak,lastNonzeroSeconds:lastNonzero,markerToLastNonzeroMillis:Math.max(0,(lastNonzero-marker)*1000),interruptions};
  if(beforePeak<.1||interruptions!==(gap?0:1))throw Error('Missing rendered interruption baseline '+JSON.stringify(result));
  if(afterPeak>1e-6)throw Error('Interrupted native audio restarted before server onset '+JSON.stringify(result));
  if(freshVoicePeak<.1)throw Error('Interrupted audio blocked a fresh utterance '+JSON.stringify(result));
  return result;
 }finally{engine.hold();if(!stopped)throw Error('Synthetic capture cleanup did not stop its track');}
 }
 return {nativeOfflineAudio:true,physicalPlayback:false,microphoneOpened:false,cases:[await render(false),await render(true)]};
})()
