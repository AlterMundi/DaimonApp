// Native output ownership, bounded PCM and lifecycle; no provider or microphone.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const crypto=require('node:crypto').webcrypto;
const source=fs.readFileSync(process.env.QUALIFICATION_AUDIO_SOURCE||'dashboard/web/webrtc-native-audio.js','utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture({blocked=false,rejectModule=false,blockModule=false,holdModule=false}={}){
  const contexts=[],nodes=[],writes=[],events=[];let release,driverOptions,releaseModule;
  const stalled=blocked?new Promise(resolve=>release=resolve):Promise.resolve();
  const driver={ready:Promise.resolve(),close(){events.push('close');},flush(){events.push('flush');return [];},
    pause(){events.push('pause');},resume(){events.push('resume');},
    async append(id,end,raw){writes.push({id,end,raw});await stalled;return true;}};
  class Context{
    constructor(options){assert.equal(options.sampleRate,24000);this.sampleRate=24000;this.state='suspended';contexts.push(this);
      this.audioWorklet={addModule:async path=>{assert.equal(path,'assets/voice-output-pcm.js');if(rejectModule)throw Error('module unavailable');if(blockModule)await new Promise(()=>{});if(holdModule)await new Promise(resolve=>releaseModule=resolve);}};}
    async resume(){this.state='running';}async close(){this.state='closed';events.push('context-close');}
    createMediaStreamSource(stream){return {connect(node){assert(nodes.includes(node));events.push('attach');},disconnect(){events.push('detach');}};}
  }
  class Node{
    constructor(context,name,options){assert.equal(name,'interaction-output-pcm');assert.equal(options.numberOfOutputs,0);
      assert.equal(options.processorOptions.sessionSeconds,600);this.port={postMessage(){},close(){events.push('port-close');}};nodes.push(this);}
    disconnect(){events.push('node-disconnect');}
  }
  const window={AudioContext:Context,NativeSpeechAudio:{webrtcPcm:true,pcmMaxSeconds:600,
    openPcm(options){assert.equal(options.sessionSeconds,600);driverOptions=options;return driver;}}};
  vm.runInNewContext(source,{window,crypto,AudioWorkletNode:Node,ArrayBuffer,Uint8Array,AbortController,setTimeout,clearTimeout});
  const send=(rms=0)=>nodes[0].port.onmessage?.({data:{pcm:new Uint8Array(4800).buffer,rms}});
  return {api:window.WebRtcNativeAudio,contexts,nodes,writes,events,driver,send,release,releaseModule:()=>releaseModule(),progress:(id,count)=>driverOptions.onProgress(id,count)};
}
(async()=>{
  const f=fixture(),failures=[];const output=await f.api.open({onUnavailable:message=>failures.push(message)});
  output.attach({});f.send();await tick();assert.equal(f.writes.length,1);assert.equal(f.writes[0].end,4800);
  f.send();await tick();assert.equal(f.writes[1].end,9600);assert.equal(f.writes[1].id,f.writes[0].id);
  output.setEnabled(false);f.send();await tick();assert.equal(f.writes.length,2);
  output.setEnabled(true);f.send();await tick();assert.equal(f.writes[2].end,4800);assert.notEqual(f.writes[2].id,f.writes[0].id);
  output.pause();f.send();await tick();assert.equal(f.writes.length,3);
  output.resume();f.send();await tick();assert.equal(f.writes[3].end,4800);
  output.close();output.close();assert.equal(f.events.filter(v=>v==='close').length,1);assert.equal(f.contexts[0].state,'closed');assert.deepEqual(failures,[]);

  const observed=fixture(),levels=[];const observedOutput=await observed.api.open({onActivity:value=>levels.push(value)});
  observed.send(.2);await tick();assert.equal(levels.length,0,'Received/queued audio is not playback');
  observed.progress(observed.writes[0].id,2400);assert.equal(levels.at(-1),.2,'Actual native progress selects the bounded corresponding PCM window');
  observedOutput.pause();assert.equal(levels.at(-1),0);const stoppedLevels=levels.length;
  observed.progress(observed.writes[0].id,4800);assert.equal(levels.length,stoppedLevels,'Old progress is ignored while paused');
  observedOutput.resume();observed.send(0);await tick();observed.progress(observed.writes.at(-1).id,4800);assert.equal(levels.at(-1),0,'Silence remains silent');
  observedOutput.close();

  const late=fixture({blocked:true}),held=await late.api.open();late.send();await tick();late.send();held.pause();
  late.release();await tick();await tick();assert.equal(late.writes.length,1,'Queued old epoch must not replay after pause');held.close();
  const overload=fixture(),errors=[];await overload.api.open({onUnavailable:message=>errors.push(message)});
  for(let n=0;n<9;n++)overload.send();await tick();assert.equal(errors.length,1);assert.equal(overload.events.filter(v=>v==='close').length,1);
  const module=fixture({rejectModule:true});await assert.rejects(module.api.open(),/module unavailable/);assert.equal(module.events.filter(v=>v==='close').length,1);
  const stalled=fixture({blockModule:true}),controller=new AbortController();
  const opening=stalled.api.open({signal:controller.signal});controller.abort();
  await assert.rejects(opening,/retired/);assert.equal(stalled.events.filter(v=>v==='close').length,1);
  assert.equal(stalled.contexts[0].state,'closed','Abort releases native output and context even if addModule never settles');

  // The encoded-reply element remains the sole audio owner. Cosmetic output
  // observation must retire before a successor, including late setup callbacks.
  function element(){
    const value=new EventTarget();value.paused=false;value.muted=false;value.ended=false;
    value.streams=[];value.captureStream=()=>{const track=new EventTarget();track.stops=0;track.stop=()=>track.stops++;
      const stream={getAudioTracks:()=>[track],getTracks:()=>[track]};value.streams.push({stream,track});return stream;};
    value.fire=name=>value.dispatchEvent(new Event(name));return value;
  }
  const replies=fixture(),el=element(),replyLevels=[];
  const watcher=replies.api.watchElement(el,{onActivity:v=>replyLevels.push(v)});
  el.fire('playing');await tick();await tick();
  const firstReply=replies.nodes[0].port.onmessage;
  firstReply({data:{rms:.25}});assert.equal(replyLevels.at(-1),.25);
  el.paused=true;el.fire('pause');assert.equal(replyLevels.at(-1),0);
  assert.equal(el.streams[0].track.stops,1);assert.equal(replies.contexts[0].state,'closed');
  const afterPause=replyLevels.length;firstReply({data:{rms:.8}});assert.equal(replyLevels.length,afterPause);
  el.paused=false;el.fire('playing');await tick();await tick();
  replies.nodes[1].port.onmessage({data:{rms:.2}});assert.equal(replyLevels.at(-1),.2);
  el.muted=true;el.fire('volumechange');assert.equal(replyLevels.at(-1),0);
  el.muted=false;el.fire('volumechange');await tick();await tick();
  replies.nodes[2].port.onmessage({data:{rms:.3}});assert.equal(replyLevels.at(-1),.3);
  el.fire('emptied');assert.equal(replyLevels.at(-1),0);watcher.close();
  const afterClose=replies.contexts.length;el.fire('playing');assert.equal(replies.contexts.length,afterClose);
  const lateReply=fixture({holdModule:true}),lateEl=element(),lateLevels=[];
  const lateWatcher=lateReply.api.watchElement(lateEl,{onActivity:v=>lateLevels.push(v)});
  lateEl.fire('playing');await tick();lateEl.paused=true;lateEl.fire('pause');lateReply.releaseModule();await tick();await tick();
  assert.equal(lateReply.nodes.length,0);assert.equal(lateReply.contexts[0].state,'closed');assert.equal(lateLevels.at(-1),0);lateWatcher.close();
  const unavailable=fixture(),unsupported=element();delete unsupported.captureStream;
  const noObserver=unavailable.api.watchElement(unsupported);unsupported.fire('playing');assert.equal(unavailable.contexts.length,0);noObserver.close();
  const failing=fixture({rejectModule:true}),failingEl=element();const cosmetic=failing.api.watchElement(failingEl);
  failingEl.fire('playing');await tick();await tick();assert.equal(failingEl.paused,false,'Cosmetic setup failure never pauses the player');cosmetic.close();

  let Processor;let bytes=0,first,error;const activityLevels=[];
  class Worklet{constructor(){this.port={postMessage(value){if(value.pcm){bytes+=value.pcm.byteLength;first??=value.pcm;}else if(value.rms!==undefined)activityLevels.push(value.rms);else error=value.error;}};}}
  vm.runInNewContext(fs.readFileSync('dashboard/web/voice-output-pcm.js','utf8'),{
    AudioWorkletProcessor:Worklet,sampleRate:24000,registerProcessor:(name,value)=>{assert.equal(name,'interaction-output-pcm');Processor=value;},ArrayBuffer,DataView});
  assert.throws(()=>new Processor({processorOptions:{sessionSeconds:601}}),/bound/);
  const pcm=new Processor({processorOptions:{sessionSeconds:600}}),left=new Float32Array(128).fill(.5),right=new Float32Array(128).fill(-.25);
  for(let n=0;n<600*24000/128;n++)assert.equal(pcm.process([[left,right]]),true);
  assert.equal(bytes,600*48000);assert.equal(new DataView(first).getInt16(0,true),4096,'Stereo must downmix rather than double amplitude');
  assert.equal(pcm.process([[left,right]]),false);assert.equal(error,'output_limit');assert.equal(pcm.process([[left,right]]),false);
  const beforeBytes=bytes,activity=new Processor({processorOptions:{sessionSeconds:300,activityOnly:true}});
  for(let n=0;n<19;n++)activity.process([[left,right]]);
  assert.equal(bytes,beforeBytes,'Activity-only worklet never exports or retains PCM');assert.equal(activity.frames.length,0);assert.equal(activityLevels.length,1);assert.equal(activityLevels[0],Math.sqrt((.5*.5+.25*.25)/2));
  activity.port.onmessage({data:'stop'});assert.equal(activity.process([[left,right]]),false);
  console.log('WebRTC native output: one silent browser graph/native owner, exact bounded24k PCM,600s cap, mute/pause retirement, cleanup and overload refusal passed; no provider/device calls.');
})().catch(error=>{console.error(error);process.exitCode=1;});
