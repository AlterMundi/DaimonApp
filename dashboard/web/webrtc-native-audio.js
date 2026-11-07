"use strict";
// Foreground WebRTC output uses the same Android PCM owner as native dialogue.
// No provider/capture/work operation, archive or browser playback destination.
window.WebRtcNativeAudio=(()=>{
  const supported=()=>window.NativeSpeechAudio?.webrtcPcm===true
    &&window.NativeSpeechAudio.pcmMaxSeconds>=600
    &&typeof window.NativeSpeechAudio.openPcm==='function';
  async function open({sessionSeconds=600,onUnavailable=()=>{}}={}){
    if(!supported()||!Number.isSafeInteger(sessionSeconds)||sessionSeconds<300||sessionSeconds>600)
      throw Error('Native WebRTC audio is unavailable');
    let context,node,source,driver,closed=false,paused=false,enabled=true,epoch=0;
    let sourceId=crypto.randomUUID(),end=0,pending=0,chain=Promise.resolve();
    function close(){
      if(closed)return;closed=true;epoch++;
      try{source?.disconnect();}catch{}source=undefined;
      if(node){node.port.postMessage('stop');node.port.onmessage=null;node.port.close();try{node.disconnect();}catch{}}
      driver?.close();if(context)void context.close().catch(()=>{});
    }
    function fail(message){if(closed)return;close();onUnavailable(message);}
    function silence(){
      epoch++;sourceId=crypto.randomUUID();end=0;
      driver.flush();driver.pause();
    }
    const value={close,
      attach(stream){
        if(closed)throw Error('Native WebRTC audio closed');
        source?.disconnect();source=context.createMediaStreamSource(stream);source.connect(node);
      },
      pause(){if(!closed&&!paused){paused=true;silence();}},
      resume(){if(!closed){paused=false;if(enabled)driver.resume();}},
      setEnabled(next){
        if(closed||enabled===(next===true))return;enabled=next===true;
        if(!enabled)silence();else if(!paused)driver.resume();
      }
    };
    try{
      const Context=window.AudioContext||window.webkitAudioContext;
      context=new Context({sampleRate:24000,latencyHint:'interactive'});
      if(context.sampleRate!==24000||!context.audioWorklet)throw Error('Native output conversion unavailable');
      driver=window.NativeSpeechAudio.openPcm({sessionSeconds,onUnavailable:fail});
      // Observe readiness rejection even if module loading or Resume fails first.
      driver.ready.catch(()=>{});
      await context.audioWorklet.addModule('assets/voice-output-pcm.js');
      node=new AudioWorkletNode(context,'interaction-output-pcm',{numberOfInputs:1,numberOfOutputs:0,
        channelCount:2,channelCountMode:'max',processorOptions:{sessionSeconds}});
      node.onprocessorerror=()=>fail('Native output conversion stopped.');
      node.port.onmessage=event=>{
        if(closed)return;
        if(event.data?.error){fail('Voice output reached its bound.');return;}
        const raw=event.data?.pcm;
        if(!(raw instanceof ArrayBuffer)||!raw.byteLength||raw.byteLength%2||raw.byteLength>4800){fail('Native output changed format.');return;}
        // Muted/paused data is not queued for later replay or marked as heard.
        if(!enabled||paused)return;
        if(pending>=8){fail('Native output is falling behind.');return;}
        const owned=epoch,id=sourceId,bytes=new Uint8Array(raw);end+=bytes.length;const through=end;pending++;
        chain=chain.then(async()=>{
          if(closed||owned!==epoch)return;
          await driver.append(id,through,bytes);
        }).catch(()=>fail('Native output could not be confirmed.')).finally(()=>{pending--;});
      };
      await Promise.all([context.resume(),driver.ready]);
      if(closed||context.state!=='running')throw Error('Native audio was not activated');
      return value;
    }catch(error){close();throw error;}
  }
  return {supported,open};
})();
