/* WebRTC output -> bounded PCM24k for the existing Android audio owner.
 * This node has no output: it never plays a second browser audio stream. */
class InteractionOutputPCM extends AudioWorkletProcessor {
  constructor(options){
    super();const seconds=options?.processorOptions?.sessionSeconds;
    if(sampleRate!==24000||!Number.isSafeInteger(seconds)||seconds<300||seconds>600)throw Error('Invalid output PCM bound');
    this.remaining=seconds*24000;this.frames=[];this.active=true;
    this.activityOnly=options?.processorOptions?.activityOnly===true;this.energy=0;this.count=0;
    this.port.onmessage=event=>{if(event.data==='stop'){this.active=false;this.frames=[];}};
  }
  process(inputs){
    if(!this.active)return false;
    const channels=inputs[0];if(!channels?.length)return true;
    const count=channels[0].length;
    for(let i=0;i<count;i++){
      if(!this.remaining--){this.active=false;this.port.postMessage({error:'output_limit'});return false;}
      let sample=0,channelEnergy=0;for(const channel of channels){const value=Math.max(-1,Math.min(1,channel[i]||0));sample+=value;channelEnergy+=value*value;}
      sample=Math.max(-1,Math.min(1,sample/channels.length));
      this.energy+=this.activityOnly?channelEnergy/channels.length:sample*sample;this.count++;if(!this.activityOnly)this.frames.push(sample);
      if(this.count===2400){
        const rms=Math.sqrt(this.energy/this.count);this.energy=this.count=0;
        if(this.activityOnly){this.port.postMessage({rms});continue;}
        const pcm=new ArrayBuffer(4800),view=new DataView(pcm);
        this.frames.forEach((value,n)=>view.setInt16(n*2,Math.round(value*32767),true));
        this.frames=[];this.port.postMessage({pcm,rms},[pcm]);
      }
    }
    return true;
  }
}
registerProcessor('interaction-output-pcm',InteractionOutputPCM);
