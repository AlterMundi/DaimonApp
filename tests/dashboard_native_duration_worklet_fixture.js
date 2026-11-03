// Real Chromium OfflineAudioContext and shipped capture worklet. No device,
// microphone, provider, stored PCM or physical-hearing claim.
async seconds=>{
  if(seconds!==600)throw Error('Select the finite600second qualification');
  const context=new OfflineAudioContext(1,(seconds+1)*16000,16000);
  await context.audioWorklet.addModule(new URL('assets/voice-pcm.js',location.href));
  const node=new AudioWorkletNode(context,'interaction-pcm',{processorOptions:{sessionSeconds:seconds}});
  const tone=context.createOscillator();tone.frequency.value=230;tone.connect(node);node.connect(context.destination);
  let bytes=0,packets=0,peak=0,maximumPacket=0,resolve,reject,timer;
  const ended=new Promise((yes,no)=>{resolve=yes;reject=no;});
  node.port.onmessage=({data})=>{
    try{
      if(data.pcm){
        if(!(data.pcm instanceof ArrayBuffer)||data.pcm.byteLength>3200||data.pcm.byteLength%2)throw Error('Invalid actual PCM packet');
        bytes+=data.pcm.byteLength;packets++;maximumPacket=Math.max(maximumPacket,data.pcm.byteLength);
        if(data.totalBytes!==bytes||bytes>seconds*32000||packets>seconds*10)throw Error('Worklet duration or absolute count changed');
        const sample=new Int16Array(data.pcm);
        for(let n=0;n<Math.min(32,sample.length);n++)peak=Math.max(peak,Math.abs(sample[n]));
      }
      if(data.captureError){if(data.captureError!=='session_limit')throw Error('Unexpected worklet failure');resolve();}
    }catch(error){reject(error);}
  };
  try{
    tone.start();await context.startRendering();
    await Promise.race([ended,new Promise((_,no)=>{timer=setTimeout(()=>no(Error('Missing finite worklet stop')),15000);})]);
    if(bytes!==seconds*32000||peak<10000||context.state!=='closed')throw Error('Missing exact real-worklet completion');
    return {actualChromiumWorklet:true,offlineAudio:true,physicalPlayback:false,microphoneOpened:false,
      seconds,bytes,packets,maximumPacket,peak,contextState:context.state,stop:'session_limit',retainedPCMBytes:0};
  }finally{clearTimeout(timer);tone.disconnect();node.disconnect();node.port.close();}
}
