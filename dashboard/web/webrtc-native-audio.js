"use strict";
// Foreground WebRTC output uses the same Android PCM owner as native dialogue.
// No provider/capture/work operation, archive or browser playback destination.
window.WebRtcNativeAudio=(()=>{
  const supported=()=>window.NativeSpeechAudio?.webrtcPcm===true
    &&window.NativeSpeechAudio.pcmMaxSeconds>=600
    &&typeof window.NativeSpeechAudio.openPcm==='function';
  async function open({sessionSeconds=600,onUnavailable=()=>{},onActivity=()=>{},signal}={}){
    if(!supported()||!Number.isSafeInteger(sessionSeconds)||sessionSeconds<300||sessionSeconds>600)
      throw Error('Native WebRTC audio is unavailable');
    let context,node,source,driver,closed=false,paused=false,enabled=true,epoch=0;
    let sourceId=crypto.randomUUID(),end=0,pending=0,chain=Promise.resolve(),rejectOpen;const levels=[];
    const activity=value=>{try{onActivity(value);}catch{/* Presentation cannot fail audio ownership. */}};
    const cancelled=new Promise((resolve,reject)=>{rejectOpen=reject;});cancelled.catch(()=>{});
    const abort=()=>{close();rejectOpen(Error('Native audio preparation retired'));};
    function close(){
      if(closed)return;closed=true;epoch++;levels.length=0;activity(0);
      signal?.removeEventListener('abort',abort);
      try{source?.disconnect();}catch{}source=undefined;
      if(node){node.port.postMessage('stop');node.port.onmessage=null;node.port.close();try{node.disconnect();}catch{}}
      driver?.close();if(context)void context.close().catch(()=>{});
    }
    function fail(message){if(closed)return;close();rejectOpen(Error(message));onUnavailable(message);}
    function silence(){
      epoch++;sourceId=crypto.randomUUID();end=0;levels.length=0;activity(0);
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
      if(signal?.aborted)throw Error('Native audio preparation retired');
      signal?.addEventListener('abort',abort,{once:true});
      const Context=window.AudioContext||window.webkitAudioContext;
      context=new Context({sampleRate:24000,latencyHint:'interactive'});
      context.onstatechange=()=>{if(!closed&&context.state!=='running')activity(0);};
      if(context.sampleRate!==24000||!context.audioWorklet)throw Error('Native output conversion unavailable');
      driver=window.NativeSpeechAudio.openPcm({sessionSeconds,onUnavailable:fail,
        onProgress:(id,count)=>{if(closed||paused||!enabled||id!==sourceId)return;const row=levels.find(v=>v.start<count&&count<=v.end);if(row)activity(row.rms);while(levels.length&&levels[0].end<count)levels.shift();},
        onState:state=>{if(state==='idle'||state==='paused')activity(0);}});
      // Observe readiness rejection even if module loading or Resume fails first.
      driver.ready.catch(()=>{});
      await Promise.race([context.audioWorklet.addModule('assets/voice-output-pcm.js'),cancelled]);
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
        levels.push({start:end-bytes.length,end,rms:Number.isFinite(event.data.rms)&&event.data.rms>=0&&event.data.rms<=1?event.data.rms:0});if(levels.length>32)levels.shift();
        chain=chain.then(async()=>{
          if(closed||owned!==epoch)return;
          await driver.append(id,through,bytes);
        }).catch(()=>fail('Native output could not be confirmed.')).finally(()=>{pending--;});
      };
      await Promise.race([Promise.all([context.resume(),driver.ready]),cancelled]);
      if(closed||context.state!=='running')throw Error('Native audio was not activated');
      return value;
    }catch(error){close();throw error;}
  }
  // Observe the decoded remote track without another audible destination or
  // retaining PCM. The existing HTML player keeps sole browser playback ownership.
  async function observe(stream,{sessionSeconds=600,isPlaying=()=>false,onActivity=()=>{},signal}={}){
    if(!Number.isSafeInteger(sessionSeconds)||sessionSeconds<300||sessionSeconds>600)throw Error('Invalid output activity bound');
    let context,node,source,closed=false,timeout,reject;const tracks=stream.getAudioTracks?.()||[];const muted=()=>activity(0);
    const cancelled=new Promise((resolve,no)=>{reject=no;});cancelled.catch(()=>{});
    const activity=value=>{try{onActivity(value);}catch{/* Cosmetic callback only. */}};
    const close=()=>{if(closed)return;closed=true;clearTimeout(timeout);reject(Error('Output activity retired'));signal?.removeEventListener('abort',close);for(const track of tracks){track.removeEventListener('ended',close);track.removeEventListener('mute',muted);}activity(0);try{source?.disconnect();}catch{}if(node){node.port.postMessage('stop');node.port.onmessage=null;node.port.close();try{node.disconnect();}catch{}}if(context)void context.close().catch(()=>{});};
    try{
      if(signal?.aborted)throw Error('Output activity retired');signal?.addEventListener('abort',close,{once:true});for(const track of tracks){track.addEventListener('ended',close,{once:true});track.addEventListener('mute',muted);}
      const Context=window.AudioContext||window.webkitAudioContext;context=new Context({sampleRate:24000,latencyHint:'interactive'});
      context.onstatechange=()=>{if(!closed&&context.state!=='running')activity(0);};
      if(context.sampleRate!==24000||!context.audioWorklet)throw Error('Output activity unavailable');
      await Promise.race([context.audioWorklet.addModule('assets/voice-output-pcm.js'),cancelled,new Promise((resolve,no)=>{timeout=setTimeout(()=>no(Error('Output activity unavailable')),5000);})]);clearTimeout(timeout);if(closed)throw Error('Output activity retired');
      node=new AudioWorkletNode(context,'interaction-output-pcm',{numberOfInputs:1,numberOfOutputs:0,channelCount:2,channelCountMode:'max',processorOptions:{sessionSeconds,activityOnly:true}});
      node.port.onmessage=event=>{if(closed)return;const rms=event.data?.rms;if(event.data?.error||!Number.isFinite(rms)||rms<0||rms>1){close();return;}activity(context.state==='running'&&isPlaying()?rms:0);};
      node.onprocessorerror=close;source=context.createMediaStreamSource(stream);source.connect(node);
      await Promise.race([context.resume(),cancelled,new Promise((resolve,no)=>{timeout=setTimeout(()=>no(Error('Output activity unavailable')),5000);})]);clearTimeout(timeout);if(closed||context.state!=='running')throw Error('Output activity unavailable');return {close};
    }catch(error){close();throw error;}
  }
  return {supported,open,observe};
})();
