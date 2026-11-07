// Native output ownership, bounded PCM and lifecycle; no provider or microphone.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const crypto=require('node:crypto').webcrypto;
const source=fs.readFileSync('dashboard/web/webrtc-native-audio.js','utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture({blocked=false,rejectModule=false,blockModule=false}={}){
  const contexts=[],nodes=[],writes=[],events=[];let release;
  const stalled=blocked?new Promise(resolve=>release=resolve):Promise.resolve();
  const driver={ready:Promise.resolve(),close(){events.push('close');},flush(){events.push('flush');return [];},
    pause(){events.push('pause');},resume(){events.push('resume');},
    async append(id,end,raw){writes.push({id,end,raw});await stalled;return true;}};
  class Context{
    constructor(options){assert.equal(options.sampleRate,24000);this.sampleRate=24000;this.state='suspended';contexts.push(this);
      this.audioWorklet={addModule:async path=>{assert.equal(path,'assets/voice-output-pcm.js');if(rejectModule)throw Error('module unavailable');if(blockModule)await new Promise(()=>{});}};}
    async resume(){this.state='running';}async close(){this.state='closed';events.push('context-close');}
    createMediaStreamSource(stream){return {connect(node){assert(nodes.includes(node));events.push('attach');},disconnect(){events.push('detach');}};}
  }
  class Node{
    constructor(context,name,options){assert.equal(name,'interaction-output-pcm');assert.equal(options.numberOfOutputs,0);
      assert.equal(options.processorOptions.sessionSeconds,600);this.port={postMessage(){},close(){events.push('port-close');}};nodes.push(this);}
    disconnect(){events.push('node-disconnect');}
  }
  const window={AudioContext:Context,NativeSpeechAudio:{webrtcPcm:true,pcmMaxSeconds:600,
    openPcm(options){assert.equal(options.sessionSeconds,600);return driver;}}};
  vm.runInNewContext(source,{window,crypto,AudioWorkletNode:Node,ArrayBuffer,Uint8Array});
  const send=()=>nodes[0].port.onmessage?.({data:{pcm:new Uint8Array(4800).buffer}});
  return {api:window.WebRtcNativeAudio,contexts,nodes,writes,events,driver,send,release};
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

  const late=fixture({blocked:true}),held=await late.api.open();late.send();await tick();late.send();held.pause();
  late.release();await tick();await tick();assert.equal(late.writes.length,1,'Queued old epoch must not replay after pause');held.close();
  const overload=fixture(),errors=[];await overload.api.open({onUnavailable:message=>errors.push(message)});
  for(let n=0;n<9;n++)overload.send();await tick();assert.equal(errors.length,1);assert.equal(overload.events.filter(v=>v==='close').length,1);
  const module=fixture({rejectModule:true});await assert.rejects(module.api.open(),/module unavailable/);assert.equal(module.events.filter(v=>v==='close').length,1);
  const stalled=fixture({blockModule:true}),controller=new AbortController();
  const opening=stalled.api.open({signal:controller.signal});controller.abort();
  await assert.rejects(opening,/retired/);assert.equal(stalled.events.filter(v=>v==='close').length,1);
  assert.equal(stalled.contexts[0].state,'closed','Abort releases native output and context even if addModule never settles');

  let Processor;let bytes=0,first,error;
  class Worklet{constructor(){this.port={postMessage(value){if(value.pcm){bytes+=value.pcm.byteLength;first??=value.pcm;}else error=value.error;}};}}
  vm.runInNewContext(fs.readFileSync('dashboard/web/voice-output-pcm.js','utf8'),{
    AudioWorkletProcessor:Worklet,sampleRate:24000,registerProcessor:(name,value)=>{assert.equal(name,'interaction-output-pcm');Processor=value;},ArrayBuffer,DataView});
  assert.throws(()=>new Processor({processorOptions:{sessionSeconds:601}}),/bound/);
  const pcm=new Processor({processorOptions:{sessionSeconds:600}}),left=new Float32Array(128).fill(.5),right=new Float32Array(128).fill(-.25);
  for(let n=0;n<600*24000/128;n++)assert.equal(pcm.process([[left,right]]),true);
  assert.equal(bytes,600*48000);assert.equal(new DataView(first).getInt16(0,true),4096,'Stereo must downmix rather than double amplitude');
  assert.equal(pcm.process([[left,right]]),false);assert.equal(error,'output_limit');assert.equal(pcm.process([[left,right]]),false);
  console.log('WebRTC native output: one silent browser graph/native owner, exact bounded24k PCM,600s cap, mute/pause retirement, cleanup and overload refusal passed; no provider/device calls.');
})().catch(error=>{console.error(error);process.exitCode=1;});
