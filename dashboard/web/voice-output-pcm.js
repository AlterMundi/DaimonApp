/* WebRTC output -> bounded PCM24k for the existing Android audio owner.
 * This node has no output: it never plays a second browser audio stream. */
class InteractionOutputPCM extends AudioWorkletProcessor {
  constructor(options){
    super();const seconds=options?.processorOptions?.sessionSeconds;
    if(sampleRate!==24000||!Number.isSafeInteger(seconds)||seconds<300||seconds>600)throw Error('Invalid output PCM bound');
    this.remaining=seconds*24000;this.frames=[];this.active=true;
    this.port.onmessage=event=>{if(event.data==='stop'){this.active=false;this.frames=[];}};
  }
  process(inputs){
    if(!this.active)return false;
    const channels=inputs[0];if(!channels?.length)return true;
    const count=channels[0].length;
    for(let i=0;i<count;i++){
      if(!this.remaining--){this.active=false;this.port.postMessage({error:'output_limit'});return false;}
      let sample=0;for(const channel of channels)sample+=channel[i]||0;
      this.frames.push(Math.max(-1,Math.min(1,sample/channels.length)));
      if(this.frames.length===2400){
        const pcm=new ArrayBuffer(4800),view=new DataView(pcm);
        this.frames.forEach((value,n)=>view.setInt16(n*2,Math.round(value*32767),true));
        this.frames=[];this.port.postMessage({pcm},[pcm]);
      }
    }
    return true;
  }
}
registerProcessor('interaction-output-pcm',InteractionOutputPCM);
