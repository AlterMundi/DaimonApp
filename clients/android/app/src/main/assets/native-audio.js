"use strict";
/* Loaded only by the Android host, on its exact selected HTTPS main origin. */
window.NativeSpeechAudio=(()=>{
  const bridge=window.DaimonAudio,outputs=new Map(),streams=new Set(),encodedStreams=new Map();
  let serial=0,captureEpoch=0,controls,sessionEnabled=false,pcmOwner,beaconOwner;
  if(!bridge?.postMessage)return;
  const send=value=>bridge.postMessage(JSON.stringify(value));
  bridge.onmessage=event=>{try{const value=JSON.parse(event.data);if(value.type==="file"){window.NativeFiles?.receive(value);return;}if(value.type==="control"){controls?.[value.action]?.();return;}if(value.id===beaconOwner?.id){beaconOwner.receive(value);return;}outputs.get(value.id)?.receive(value);}catch{}};
  send({command:"hello"});
  const devices=navigator.mediaDevices,original=devices?.getUserMedia?.bind(devices);
  if(original)devices.getUserMedia=async constraints=>{
    // Explicit track.stop() does not dispatch ended. Drop finished captures
    // before another recording so the foreground registry cannot accumulate.
    for(const previous of streams)if(previous.getTracks().every(track=>track.readyState==="ended"))streams.delete(previous);
    const epoch=captureEpoch,stream=await original(constraints);
    if(epoch!==captureEpoch){for(const track of stream.getTracks())track.stop();throw new DOMException("Capture interrupted by app lifecycle","AbortError");}
    streams.add(stream);
    stream.getTracks().forEach(track=>track.addEventListener("ended",()=>{if(stream.getTracks().every(t=>t.readyState==="ended"))streams.delete(stream);},{once:true}));
    return stream;
  };
  // Independent from speech; Android bridge/renderer qualification covers this owner.
  function openBeacon({onState=()=>{},onUnavailable=()=>{}}={}){
    if(beaconOwner)throw Error("Native Beacon already active");
    const id="beacon_"+crypto.randomUUID(),clock=()=>performance.now();
    let closed=false,anchor,resolve,reject;
    const ready=new Promise((yes,no)=>{resolve=yes;reject=no;});ready.catch(()=>{});
    const command=(command,extra={})=>send({command,id,...extra});
    const callback=(fn,value)=>{try{fn(value);}catch{}};
    const timer=setTimeout(()=>fail(Error("Native Beacon readiness timed out")),5000);
    function close(){
      if(closed)return;closed=true;clearTimeout(timer);reject(Error("Native Beacon closed"));
      if(beaconOwner===value)beaconOwner=undefined;
      command("beacon_stop");
    }
    function fail(error){if(closed)return;close();callback(onUnavailable,error.message);}
    const number=(n,lo,hi)=>typeof n==="number"&&Number.isFinite(n)&&n>=lo&&n<=hi;
    const vector=(a,lo,hi)=>Array.isArray(a)&&a.length===6&&a.every(n=>number(n,lo,hi));
    const transition=n=>Number.isInteger(n)&&number(n,20,2000);
    const value={id,ready,close,
      receive(event){
        if(closed||event.id!==id)return;
        if(event.type==="beacon_ready"){
          if(anchor)return;
          if(!Number.isSafeInteger(event.clock_ms)||event.clock_ms<0){fail(Error("Native Beacon clock unavailable"));return;}
          // Transport delay makes this anchor conservative, never fresher.
          anchor={native:event.clock_ms,page:clock()};clearTimeout(timer);resolve();
        }else if(event.type==="beacon_closed"||event.type==="beacon_error"){
          fail(Error(event.type==="beacon_error"?"Android Beacon unavailable":"Android Beacon closed"));
        }else if(event.type==="beacon_playing"||event.type==="beacon_quiet")callback(onState,event.type);
      },
      frame(frame){
        if(closed||!anchor)throw Error("Native Beacon is not ready");
        const keys=["frequencies","pulses","weights","depth","level","transition_ms","valid_for_ms"];
        if(!frame||Object.keys(frame).length!==keys.length||!keys.every(key=>Object.hasOwn(frame,key))
          ||!vector(frame.frequencies,20,16384)||!vector(frame.pulses,0,64)||!vector(frame.weights,0,1)
          ||frame.weights.reduce((a,b)=>a+b,0)>1+1e-9||frame.weights.some((weight,i)=>weight>0&&frame.frequencies[i]>=10800)
          ||!number(frame.depth,0,.5)||!number(frame.level,0,.8)||!transition(frame.transition_ms)||!number(frame.valid_for_ms,0,20000))throw Error("Invalid native Beacon frame");
        const {valid_for_ms,...payload}=frame,elapsed=clock()-anchor.page;
        if(!number(elapsed,0,7200000))throw Error("Native Beacon clock expired");
        command("beacon_frame",{...payload,expires_at_ms:Math.floor(anchor.native+elapsed+valid_for_ms)});
      },
      level(level,transition_ms){
        if(closed||!anchor)throw Error("Native Beacon is not ready");
        if(!number(level,0,.8)||!transition(transition_ms))throw Error("Invalid native Beacon level");
        command("beacon_level",{level,transition_ms});
      }
    };
    beaconOwner=value;
    try{command("beacon_begin");}catch(error){fail(error);}
    return value;
  }
  function openStream(){
    if(encodedStreams.size>=3)throw Error("Native speech preparation bound reached");
    const url="native-speech:"+(++serial);
    let queue=[],bytes=0,sequence=0,owner,terminal,closed=false,decoderFailed=false;
    const chunk=(id,part)=>send({command:"stream_chunk",id,...part});
    const stream={url,
      append(raw,sha256){
        if(closed || terminal || !raw.length || raw.length>32768 || bytes+raw.length>8*1024*1024 || !/^[a-f0-9]{64}$/.test(sha256))throw Error("Invalid native stream chunk");
        const part={sequence:sequence++,data:btoa(String.fromCharCode(...raw)),sha256};bytes+=raw.length;
        if(owner)chunk(owner,part);else if(!decoderFailed)queue.push(part);
      },
      finish(value){
        if(closed || terminal || !bytes || value.audio_bytes!==bytes || !/^[a-f0-9]{64}$/.test(value.audio_sha256))throw Error("Incomplete native speech stream");
        terminal={bytes,sha256:value.audio_sha256};
        if(owner)send({command:"stream_end",id:owner,...terminal});
      },
      attach(id){
        if(closed || owner || decoderFailed)throw Error("Native speech source already selected");
        owner=id;send({command:"stream_begin",id});
        for(const part of queue)chunk(id,part);queue=[];
        if(terminal)send({command:"stream_end",id,...terminal});
      },
      detach(){
        // A decoder can reject an incomplete source while the verified HTTP
        // transport is still useful. Drop native ownership, not that transport.
        decoderFailed=true;if(owner)send({command:"stop",id:owner});owner=undefined;queue=[];
      },
      cancel(){
        if(closed)return;closed=true;
        if(owner)send({command:"stop",id:owner});
        queue=[];owner=undefined;encodedStreams.delete(url);
      }
    };
    encodedStreams.set(url,stream);return stream;
  }
  function openPcm({sessionSeconds=300,onProgress=()=>{},onBufferEnded=()=>{},onState=()=>{},onUnavailable=()=>{}}={}){
    if(!Number.isSafeInteger(sessionSeconds)||sessionSeconds<300||sessionSeconds>600)throw Error("Invalid native PCM session bound");
    if(pcmOwner)throw Error("Native conversation output already active");
    // Reuse the single native speech owner, never mix it with an encoded reply.
    for(const output of [...outputs.values()])output.reset();
    const id="pcm_"+(++serial),received=new Map(),active=new Map(),retired=new Set();
    let sequence=0,total=0,epoch=0,closed=false,paused=false,resolve,reject;
    const ready=new Promise((yes,no)=>{resolve=yes;reject=no;});
    const command=(command,extra={})=>send({command,id,...extra});
    const waiting=()=>[...active].some(([key,end])=>(received.get(key)?.played||0)<end);
    const timer=setTimeout(()=>fail(Error("Native PCM readiness timed out")),5000);
    function fail(error){if(closed)return;reject(error);close();onUnavailable(error.message);}
    function close(){if(closed)return;closed=true;epoch++;clearTimeout(timer);reject(Error("Native PCM output closed"));command("stop");outputs.delete(id);active.clear();received.clear();retired.clear();if(pcmOwner===value)pcmOwner=undefined;}
    function receive(event){
      if(closed||event.id!==id)return;
      try{
        if(event.type==="pcm_ready"){
          if(event.session_seconds!==sessionSeconds)throw Error("Native PCM duration was not acknowledged");
          clearTimeout(timer);resolve();return;
        }
        if(event.type==="error"||event.type==="focuslost"){fail(Error(event.type==="focuslost"?"Android audio focus changed. Your recording is kept.":"Android PCM output unavailable."));return;}
        if(event.type==="pcm_progress"){
          if(!Array.isArray(event.positions)||event.positions.length>128)throw Error("Invalid native playback observation");
          for(const item of event.positions){
            const source=received.get(item.utterance),count=item.played_bytes;
            if(!source||!Number.isSafeInteger(count)||count%2||count<source.played||count>source.end)throw Error("Native playback position changed");
            source.played=count;onProgress(item.utterance,count);
            if(!source.ended&&count>=source.firstEnd){source.ended=true;onBufferEnded(item.utterance);}
          }
          if(!waiting())onState("idle");
        }else if(event.type==="playing")onState(paused?"paused":"playing");
        else if(event.type==="pause")onState("paused");
        else if(event.type==="ended"&&!waiting())onState("idle");
      }catch(error){fail(error);}
    }
    const value={ready,
      async append(utterance,end,raw){
        if(closed||retired.has(utterance))return false;
        const previous=received.get(utterance)?.end||0;
        if(!(raw instanceof Uint8Array)||!raw.length||raw.length%2||end!==previous+raw.length||total+raw.length>sessionSeconds*48000||(!received.has(utterance)&&received.size>=128))throw Error("Invalid bounded native PCM");
        const owned=epoch;total+=raw.length;
        const source=received.get(utterance)||{played:0,firstEnd:end,ended:false};source.end=end;received.set(utterance,source);active.set(utterance,end);
        for(let offset=0;offset<raw.length;offset+=32768){
          const part=raw.subarray(offset,offset+32768),digest=[...new Uint8Array(await crypto.subtle.digest("SHA-256",part))].map(n=>n.toString(16).padStart(2,"0")).join("");
          if(closed||owned!==epoch||retired.has(utterance))return false;
          command("pcm_chunk",{sequence:sequence++,utterance,end:previous+offset+part.length,data:btoa(String.fromCharCode(...part)),sha256:digest});
        }
        return true;
      },
      flush(){
        if(closed)return [];epoch++;const ids=[...received.keys()];for(const key of ids)retired.add(key);active.clear();command("pcm_flush");return ids;
      },
      pause(){if(!closed&&!paused){paused=true;command("pause");onState("paused");}},
      resume(){if(!closed){paused=false;onState(waiting()?"preparing":"idle");command("play");}},
      close,suspend:()=>fail(Error("Voice paused while the app is in the background. Your recordings are kept.")),
      get hasAudio(){return !closed&&waiting();},get paused(){return paused;}
    };
    outputs.set(id,{receive,reset:()=>fail(Error("Native PCM owner changed"))});pcmOwner=value;command("pcm_begin",{seconds:sessionSeconds});return value;
  }
  function mount(element){
    if(element.dataset.nativeAudio)return element;
    element.dataset.nativeAudio="progressive-v2";
    let source="",loadedSource="",id,muted=true,paused=true,ended=false,position=0,duration=NaN,loading,playingAttempt,selectedStream;
    const waiters=new Map();
    function fail(error){for(const waiter of waiters.values()){clearTimeout(waiter.timer);waiter.reject(error);}waiters.clear();}
    const wait=type=>new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{waiters.delete(type);reject(Error("Native audio deadline exceeded"));},30000);
      waiters.set(type,{resolve,reject,timer});
    });
    function command(command,extra={}){if(id)send({command,id,...extra});}
    function receive(value){
      if(value.id!==id)return;
      if(value.type!=="loaded" && Number.isFinite(value.position))position=value.position;
      if(Number.isFinite(value.duration))duration=value.duration;
      if(value.type==="error"){paused=true;selectedStream?.detach();fail(Error("Android audio unavailable"));element.dispatchEvent(new Event("error"));return;}
      if(value.type==="playing"){paused=false;ended=false;}
      if(value.type==="ended"){paused=true;ended=true;}
      if(["pause","focuslost"].includes(value.type))paused=true;
      const waiter=waiters.get(value.type);
      if(waiter){clearTimeout(waiter.timer);waiters.delete(value.type);waiter.resolve();}
      if(value.type!=="loaded")element.dispatchEvent(new Event(value.type==="focuslost"?"nativefocusloss":value.type));
    }
    function reset(preserveStream=false){
      command("stop");outputs.delete(id);id=undefined;loadedSource="";loading=undefined;playingAttempt=undefined;
      if(preserveStream)selectedStream?.detach();else selectedStream?.cancel();selectedStream=undefined;
      paused=true;ended=false;position=0;duration=NaN;fail(Error("Native audio source changed"));
    }
    async function load(){
      if(loadedSource===source)return;
      if(loading)return loading;
      const selected=source;
      const owned=id="speech_"+(++serial);outputs.set(owned,{receive,reset});
      loading=(async()=>{
        const candidate=encodedStreams.get(selected);
        if(candidate){
          selectedStream=candidate;
          const ready=wait("loaded");candidate.attach(owned);await ready;
          if(id!==owned)throw Error("Native audio source changed");
          loadedSource=selected;return;
        }
        if(!selected.startsWith("blob:"))throw Error("Native audio requires verified in-page bytes");
        const response=await fetch(selected),bytes=new Uint8Array(await response.arrayBuffer());
        if(id!==owned || source!==selected)throw Error("Native audio source changed");
        if(!bytes.length || bytes.length>8*1024*1024)throw Error("Native audio exceeds playback bound");
        const digest=[...new Uint8Array(await crypto.subtle.digest("SHA-256",bytes))].map(n=>n.toString(16).padStart(2,"0")).join("");
        if(id!==owned)throw Error("Native audio source changed");
        send({command:"begin",id:owned,bytes:bytes.length,sha256:digest});
        let sequence=0;
        for(let offset=0;offset<bytes.length;offset+=32768){
          const part=bytes.subarray(offset,offset+32768);
          send({command:"chunk",id:owned,sequence:sequence++,data:btoa(String.fromCharCode(...part))});
        }
        const ready=wait("loaded");send({command:"ready",id:owned});await ready;
        if(id!==owned)throw Error("Native audio source changed");
        loadedSource=selected;
      })();
      try{await loading;}catch(error){if(id===owned)reset(true);throw error;}
      finally{if(id===owned)loading=undefined;}
    }
    element.play=()=>{
      // Existing canonical source validation invokes muted play first. No focus
      // or sound is acquired until that validation unmutes this exact source.
      if(muted)return Promise.resolve();
      if(playingAttempt)return playingAttempt;
      const selected=source;
      const attempt=(async()=>{
        await load();
        if(source!==selected || muted)throw Error("Native playback interrupted");
        const playing=wait("playing");if(position>0)command("seek",{millis:Math.round(position*1000)});command("volume",{value:1});command("play");await playing;
      })();
      playingAttempt=attempt;
      return attempt.finally(()=>{if(playingAttempt===attempt)playingAttempt=undefined;});
    };
    element.pause=()=>{paused=true;command("pause");};
    element.load=()=>reset();
    const remove=element.removeAttribute.bind(element);
    element.removeAttribute=name=>{if(name==="src"){reset();source="";}else remove(name);};
    Object.defineProperties(element,{
      src:{get:()=>source,set:value=>{reset();source=String(value);}},
      muted:{get:()=>muted,set:value=>{muted=!!value;command("volume",{value:muted?0:1});}},
      paused:{get:()=>paused},ended:{get:()=>ended},duration:{get:()=>duration},
      currentTime:{get:()=>position,set:value=>{if(Number.isFinite(value)&&value>=0){position=value;ended=false;command("seek",{millis:Math.round(value*1000)});}}}
    });
    return element;
  }
  function setSession(enabled){
    enabled=!!enabled;if(enabled===sessionEnabled)return;sessionEnabled=enabled;
    send({command:"session",enabled});
  }
  function serviceLost(){background();controls?.stop?.();}
  function background(keepPlayback=false){
    captureEpoch++;
    beaconOwner?.close(); // Foreground-only even while spoken replies continue.
    window.dispatchEvent(new Event(keepPlayback?"nativecapturebackground":"pagehide"));
    pcmOwner?.suspend(); // Native conversation remains explicitly foreground-only.
    if(!keepPlayback){
      for(const output of [...outputs.values()])output.reset();
      for(const stream of [...encodedStreams.values()])stream.cancel();
    }
    for(const stream of streams)for(const track of stream.getTracks())track.stop();streams.clear();
  }
  return {mount,background,openStream,openPcm,openBeacon,beacon:true,pcm:true,pcmMaxSeconds:600,webrtcPcm:true,progressive:true,backgroundPlayback:true,setSession,serviceLost,setControls:value=>{controls=value;}};
})();
