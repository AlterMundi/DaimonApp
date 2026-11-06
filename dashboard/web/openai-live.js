"use strict";
// Public GPT-Live owns continuous speech/Responses. The application retains
// originals and trusted sideband sources; it never commits synthetic turns.
window.PublicLiveConversation=(()=>{
  const supported=()=>!!(window.RTCPeerConnection&&window.StreamingVoice?.supported()&&window.VoiceInput?.recoveryStore&&window.indexedDB&&navigator.locks?.request);
  function create({headers,getBinding,onState=()=>{},onItem=()=>{},onRecovery=()=>{}}){
    // Keep the existing two-store,20MiB/128-record budget across ALL engines.
    // The historical key/name does not select the provider or replay an input.
    const recovery=window.VoiceInput.recoveryStore('codex_voice'),originals=new Map();
    let binding,visit,socket,peer,channel,media,capture,audio,unsubscribe,unlock,timer,finishAck,closedAck,abortOpen;
    let active=false,starting=false,closing=false,paused=false,audible=true,epoch=0,pendingPermission=false;
    let bytes=0,total=0,ordinal=0,parts=[],fragmentParts=[],fragmentBytes=0,segment;
    let durable=Promise.resolve(),uploads=Promise.resolve(),persisting=0;
    let restored,restoring;
    const digest=async blob=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',await blob.arrayBuffer()))].map(v=>v.toString(16).padStart(2,'0')).join('');
    const state=message=>onState({active,starting,working:closing,pending:originals.size>0,floor:false,
      audioEnabled:audible,audioPaused:paused,playback:paused?'paused':'idle',...(message?{message}:{})});
    const notify=()=>onRecovery([...originals.values()]);
    async function request(value,path,options={}){
      if(value.binding!==getBinding())throw Error('Recording belongs to another conversation');
      const response=await fetch(new URL('api/interaction/voice/gpt-live/visits/'+value.voice_visit+path,window.location.href),{
        ...options,headers:{...headers(),'x-voice-binding':value.binding,...options.headers},signal:AbortSignal.timeout(30000)});
      if(!response.ok)throw Error('Original not confirmed. Keep the same local audio.');
      return response.json();
    }
    async function upload(value){
      const result=await request(value,'/recordings/'+value.ordinal,{method:'POST',body:value.blob,
        headers:{'content-type':'audio/wav',...(value.captureStop?{'x-voice-capture-stop':'interrupted_prefix'}:{})}});
      const receipt=result.recording;
      if(result.visit!==value.voice_visit||result.binding!==value.binding||receipt?.ordinal!==value.ordinal
          ||receipt.audio_sha256!==value.audio_sha256||receipt.audio_bytes!==value.blob.size||receipt.work_replay!=='never'
          ||value.captureStop&&receipt.capture_stop!=='interrupted_prefix')throw Error('Original receipt changed');
      if(value.native_fragments)await recovery.sealNative(value,value.native_fragments);
      await recovery.remove(value);originals.delete(value.id);notify();return receipt;
    }
    async function review(expectedEpoch=epoch){
      const values=(await recovery.list()).filter(v=>v.engine==='gpt-live'),groups=new Map();
      if(expectedEpoch!==epoch)return [];
      originals.clear();
      for(const value of values){
        if(!value.native_fragment){originals.set(value.id,value);continue;}
        const group=groups.get(value.fragment_group)||[];group.push(value);groups.set(value.fragment_group,group);
      }
      for(const [id,fragments] of groups){
        fragments.sort((a,b)=>a.fragment_offset-b.fragment_offset);const first=fragments[0];let offset=0;
        if(fragments.length>32)throw Error('Recording prefix needs review');
        for(const value of fragments){
          if(value.fragment_offset!==offset||value.binding!==first.binding||value.voice_visit!==first.voice_visit
              ||value.ordinal!==first.ordinal||value.blob.size<=44||value.blob.size>64044||await digest(value.blob)!==value.audio_sha256)
            throw Error('Recording prefix changed');
          offset+=value.blob.size-44;
        }
        if(offset>31*32000)throw Error('Recording prefix exceeds its bound');
        const blob=window.StreamingVoice.wav(await Promise.all(fragments.map(v=>v.blob.slice(44).arrayBuffer())));
        if(expectedEpoch!==epoch)return [];
        originals.set(id,{...first,id,blob,native_fragment:undefined,fragment_group:undefined,fragment_offset:undefined,
          audio_sha256:await digest(blob),captureStop:'interrupted_prefix',native_fragments:fragments});
      }
      if(expectedEpoch===epoch)notify();return [...originals.values()];
    }
    function withLock(id,run){return navigator.locks.request('daimon-native-voice:'+id,{ifAvailable:true},lock=>{
      if(!lock)throw Error('The microphone capture is still finishing in another page');return run();
    });}
    function checkpoint(){
      if(fragmentBytes<32000)return;
      if(persisting>=2){void hold('Local audio storage is falling behind. Your retained audio needs review.');return;}
      const selected=segment,blob=window.StreamingVoice.wav(fragmentParts),offset=selected.offset;
      selected.offset+=fragmentBytes;fragmentParts=[];fragmentBytes=0;persisting++;
      durable=durable.then(async()=>{
        const value={id:crypto.randomUUID(),engine:'gpt-live',binding:selected.binding,voice_visit:selected.visit,
          ordinal:selected.ordinal,blob,mime:'audio/wav',capture_started:selected.started,native_review:true,
          native_fragment:true,fragment_group:selected.id,fragment_offset:offset,audio_sha256:await digest(blob)};
        await recovery.put(value,true);selected.fragments.push(value);
      }).catch(()=>{selected.failed=true;void hold('Local audio storage needs review. Save the retained original.');}).finally(()=>{persisting--;});
    }
    function flush(prefix=false){
      if(!bytes)return;
      const selected=segment,owned=epoch,blob=window.StreamingVoice.wav(parts),index=ordinal++;
      parts=[];bytes=fragmentBytes=0;fragmentParts=[];
      segment={id:crypto.randomUUID(),binding,visit,ordinal,started:Date.now(),offset:0,fragments:[]};
      const sealed=durable.then(async()=>{
        const value={id:selected.id,engine:'gpt-live',binding:selected.binding,voice_visit:selected.visit,ordinal:index,
          blob,mime:'audio/wav',capture_started:selected.started,native_review:true,
          ...(prefix?{captureStop:'interrupted_prefix'}:{}),audio_sha256:await digest(blob)};
        originals.set(value.id,value);notify();
        await recovery.sealNative(value,selected.fragments);return value;
      });
      durable=sealed.catch(()=>{void hold('Local audio storage needs review. Save the retained original.');});
      uploads=uploads.then(async()=>{const value=await sealed;try{await upload(value);}catch{if(owned===epoch)state('Original audio is kept for recovery.');}}).catch(()=>{if(owned===epoch)state('Original audio is kept for review.');});
    }
    async function hold(message='Voice paused. Your original audio is kept.'){
      if(closing)return;closing=true;active=starting=false;clearTimeout(timer);state(message);
      abortOpen?.(Error('Voice activation ended'));abortOpen=undefined;
      if(capture){
        const finished=new Promise(resolve=>{finishAck=resolve;});capture.finish();
        let timeout;const complete=await Promise.race([finished,new Promise(resolve=>{timeout=setTimeout(()=>resolve(false),1000);})]);clearTimeout(timeout);
        flush(!complete);unsubscribe?.();unsubscribe=undefined;capture.close();capture=undefined;
      }
      for(const track of media?.getTracks()||[])track.stop();media=undefined;
      if(socket?.readyState===WebSocket.OPEN){
        const finalized=new Promise(resolve=>{closedAck=resolve;});
        try{socket.send(JSON.stringify({type:'close'}));}catch{closedAck(false);}
        let timeout;await Promise.race([finalized,new Promise(resolve=>{timeout=setTimeout(()=>resolve(false),35000);})]);clearTimeout(timeout);
      }
      ++epoch;socket?.close();socket=undefined;channel?.close();channel=undefined;peer?.close();peer=undefined;
      if(audio){audio.pause();audio.srcObject=null;audio=undefined;}
      // Durable local originals survive slow uploads. Do not hold the media
      // lock or freeze navigation for a whole queue of network timeouts.
      await durable;unlock?.();unlock=undefined;closing=false;state(message);notify();
    }
    async function start(){
      if(active||starting||closing||document.hidden||!supported())return false;
      if(pendingPermission){state('Finish the pending microphone permission before trying again.');return false;}
      starting=true;const owned=++epoch;binding=getBinding();visit=crypto.randomUUID();
      const current=()=>owned===epoch&&(active||starting)&&!closing&&binding===getBinding();
      bytes=total=ordinal=fragmentBytes=0;parts=[];fragmentParts=[];
      segment={id:crypto.randomUUID(),binding,visit,ordinal,started:Date.now(),offset:0,fragments:[]};
      const aborted=new Promise((_,reject)=>{abortOpen=reject;});aborted.catch(()=>{});
      async function wait(promise,ms){let timeout;try{return await Promise.race([promise,aborted,new Promise((_,reject)=>{timeout=setTimeout(()=>reject(Error('Voice connection was not confirmed.')),ms);})]);}finally{clearTimeout(timeout);}}
      state('Preparing voice');
      try{
        await review();if(!current())throw Error('Voice activation ended');
        let granted;
        const locked=new Promise(resolve=>{granted=resolve;});
        void navigator.locks.request('daimon-native-voice:'+visit,{ifAvailable:true},async lock=>{
          if(!lock||!current()){granted(false);return;}await new Promise(resolve=>{unlock=resolve;granted(true);});
        }).catch(()=>granted(false));
        if(!await wait(locked,3000))throw Error('Microphone capture is owned by another page');
        const url=new URL('api/interaction/voice/gpt-live',window.location.href);url.protocol=url.protocol==='https:'?'wss:':'ws:';
        const transport=socket=new WebSocket(url);let preparedResolve,answerResolve,readyResolve;
        const prepared=new Promise(resolve=>{preparedResolve=resolve;}),answer=new Promise(resolve=>{answerResolve=resolve;}),ready=new Promise(resolve=>{readyResolve=resolve;});
        transport.onopen=()=>{if(current())transport.send(JSON.stringify({id:visit,binding,csrf:headers()['X-Dashboard-CSRF']||headers()['x-dashboard-csrf'],
          ...(headers().Authorization?{authorization:headers().Authorization}:{})}));};
        transport.onmessage=event=>{
          if(owned!==epoch)return;
          try{
            if(typeof event.data!=='string'||event.data.length>1024*1024)throw Error('Voice event exceeds bound');
            const value=JSON.parse(event.data);
            if(value.type==='prepared')preparedResolve(value);
            else if(value.type==='answer')answerResolve(value);
            else if(value.type==='provider_event')onItem({visit,item:value.event,public_live:true});
            else if(value.type==='finishing'){if(!closing)void hold('Finishing voice; checking pending work.');}
            else if(value.type==='closed'||value.type==='finalization_unconfirmed'||value.type==='unconfirmed'){
              closedAck?.(value.type==='closed');abortOpen?.(Error('Voice connection ended. Original audio is kept.'));
              if(!closing){socket=undefined;transport.close();void hold(value.message||'Voice paused. Your original audio is kept.');}
            }
          }catch{if(!closing)void hold('Voice paused. Review the retained original.');}
        };
        transport.onclose=()=>{if(owned!==epoch)return;closedAck?.(false);abortOpen?.(Error('Voice connection ended.'));
          if(owned===epoch&&!closing){socket=undefined;void hold('Voice connection ended. Your original audio is kept.');}};
        transport.onerror=()=>transport.close();
        const admission=(await wait(prepared,10000)).admission;
        if(!current()||admission?.id!==visit||!Number.isFinite(admission.remaining_seconds)||admission.remaining_seconds<=0
            ||admission.remaining_seconds>600||admission.max_input_pcm_bytes>600*32000)throw Error('Voice admission changed');
        const deadline=Date.now()+admission.remaining_seconds*1000;
        pendingPermission=true;
        const permission=navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}})
          .then(stream=>{if(!current()){for(const track of stream.getTracks())track.stop();throw Error('Microphone permission retired');}return stream;})
          .finally(()=>{pendingPermission=false;});
        permission.catch(()=>{});media=await wait(permission,Math.min(300000,admission.remaining_seconds*1000));
        if(!current())throw Error('Voice activation ended');
        peer=new RTCPeerConnection();channel=peer.createDataChannel('oai-events');
        let sessionId,started=false,connected=false;
        const listening=()=>{if(current()&&started&&connected){starting=false;active=true;state('Listening');readyResolve();}};
        channel.onmessage=event=>{
          try{const value=JSON.parse(event.data);if(value.type==='session.started'&&value.session?.id===sessionId){started=true;listening();}}catch{}
        };
        audio=new Audio();audio.autoplay=!paused;audio.muted=!audible;
        peer.ontrack=event=>{if(!current())return;audio.srcObject=event.streams[0]||new MediaStream([event.track]);audio.play().catch(()=>{if(!current())return;paused=true;state('Tap Resume audio to listen.');});};
        peer.onconnectionstatechange=()=>{if(!current())return;connected=peer.connectionState==='connected';listening();
          if(['failed','closed','disconnected'].includes(peer.connectionState))void hold('Voice connection paused. Your original audio is kept.');};
        const recorder=window.StreamingVoice.openCapture(media,{sessionSeconds:Math.max(300,Math.ceil((deadline-Date.now())/1000))})
          .then(value=>{if(!current()){value.close();throw Error('Voice recorder retired');}return value;});
        recorder.catch(()=>{});capture=await wait(recorder,10000);
        if(!current())throw Error('Voice recorder retired');
        unsubscribe=capture.subscribe(value=>{
          if(owned!==epoch)return;
          if(value.finished){finishAck?.(true);return;}
          if(value.captureError){if(!closing)void hold('Microphone recording paused. Review your originals.');return;}
          if(!value.pcm)return;
          const pcm=value.pcm;
          if(!(pcm instanceof ArrayBuffer)||!pcm.byteLength||pcm.byteLength%2||pcm.byteLength>32000||total+pcm.byteLength>admission.max_input_pcm_bytes){void hold('Voice recording reached its bound.');return;}
          parts.push(pcm);fragmentParts.push(pcm);bytes+=pcm.byteLength;fragmentBytes+=pcm.byteLength;total+=pcm.byteLength;checkpoint();
          if(bytes>=30*32000)flush();
          if(binding!==getBinding())void hold('Conversation changed. Your original audio is kept.');
        });
        timer=setTimeout(()=>void hold('Voice visit reached its time limit.'),Math.max(0,deadline-Date.now()-2000));
        capture.start();for(const track of media.getAudioTracks())peer.addTrack(track,media);
        const offer=await wait(peer.createOffer(),10000);
        if(!current())throw Error('Voice offer retired');
        await wait(peer.setLocalDescription(offer),10000);
        if(peer.iceGatheringState!=='complete'){
          const gathering=peer;let changed;
          try{await wait(new Promise(resolve=>{
            changed=()=>{if(gathering.iceGatheringState==='complete')resolve();};
            gathering.addEventListener('icegatheringstatechange',changed);changed();
          }),10000);}finally{gathering.removeEventListener('icegatheringstatechange',changed);}
        }
        if(!current())throw Error('Voice offer retired');
        transport.send(JSON.stringify({type:'offer',sdp:peer.localDescription.sdp}));
        const result=await wait(answer,60000);sessionId=result.session;
        if(!current()||result.id!==visit||typeof sessionId!=='string'||!sessionId)throw Error('Voice answer changed');
        await wait(peer.setRemoteDescription({type:'answer',sdp:result.sdp}),10000);
        await wait(ready,15000);return true;
      }catch(error){if(owned===epoch&&!closing)await hold(error.name==='NotAllowedError'?'Microphone access was denied.':'Voice paused. Your original audio is kept.');return false;}
    }
    async function restoreHistory(){
      const selected=getBinding();if(restored===selected)return;
      if(restoring)return restoring;
      restoring=review().then(()=>{if(selected===getBinding())restored=selected;}).finally(()=>{restoring=undefined;});
      return restoring;
    }
    return {start,hold,reconnect:start,restoreHistory,resetHistory:()=>{restored=undefined;},
      retry:value=>withLock(value.voice_visit,()=>upload(value)),
      discard:value=>withLock(value.voice_visit,async()=>{if(value.native_fragments)await recovery.discardNative(value.native_fragments);else await recovery.remove(value);originals.delete(value.id);notify();}),
      setEnabled:value=>{audible=value===true;if(audio)audio.muted=!audible;state();},
      pause:()=>{paused=true;audio?.pause();state();},resume:()=>{paused=false;const selected=audio;selected?.play().catch(()=>{if(selected===audio){paused=true;state();}});state();},
      release:()=>false,get originals(){return [];},get active(){return active||starting||closing;},get hasAudio(){return active;},get paused(){return paused;},get floor(){return false;}};
  }
  return {supported,create};
})();
