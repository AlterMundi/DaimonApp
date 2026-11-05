"use strict";
// Native WebRTC owns dialogue/interruption. This path stores originals only;
// its recovery actions never submit ASR, ordinary Send or a backend turn.
window.CodexConversation=(()=>{
  const supported=()=>!!(window.RTCPeerConnection&&window.StreamingVoice?.supported()&&window.VoiceInput?.recoveryStore&&window.indexedDB);
  function create({headers,getBinding,onState=()=>{},onCaption=()=>{},onItem=()=>{},onRecovery=()=>{}}){
    const recovery=window.VoiceInput?.recoveryStore('codex_voice');
    let socket,peer,channel,media,capture,unsubscribe,audio,visit,binding,active=false,starting=false,closing=false;
    let epoch=0,parts=[],bytes=0,total=0,ordinal=0,seconds=600,finishAck,closeAck,chain=Promise.resolve(),timer;
    let audible=true,paused=false,connected=false,restored,restoring,openingCount=0;
    const originals=new Map();
    const state=message=>onState({active,starting,floor:false,pending:originals.size>0,working:closing,
      audioEnabled:audible,audioPaused:paused,playback:paused?'paused':'idle',message});
    const digest=async blob=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',await blob.arrayBuffer()))].map(v=>v.toString(16).padStart(2,'0')).join('');
    async function request(path,options={}){
      const response=await fetch(new URL('api/interaction/voice/codex/'+path,window.location.href),{
        ...options,headers:{...headers(),'x-voice-binding':binding,...options.headers},signal:AbortSignal.timeout(30000)});
      if(!response.ok)throw Error('Recording could not be confirmed. Your local original is kept.');
      return response.json();
    }
    async function review(){
      const values=await recovery.list();for(const value of values)originals.set(value.id,value);
      onRecovery([...originals.values()]);state();return [...originals.values()];
    }
    async function upload(original){
      if(original.binding!==getBinding())throw Error('Recording belongs to a different conversation');
      const value=await request(`visits/${original.codex_visit}/recordings/${original.ordinal}`,{
        method:'POST',headers:{'content-type':'audio/wav'},body:original.blob});
      const receipt=value.recording;
      if(value.visit!==original.codex_visit||value.binding!==original.binding
          ||receipt?.ordinal!==original.ordinal||receipt.audio_sha256!==original.audio_sha256
          ||receipt.audio_bytes!==original.blob.size||receipt.native_replay!=='never')throw Error('Original receipt changed');
      await recovery.remove(original);originals.delete(original.id);onRecovery([...originals.values()]);
      return receipt;
    }
    function flush(captureStop){
      if(!bytes)return;
      const blob=window.StreamingVoice.wav(parts),index=ordinal++,id=crypto.randomUUID(),selectedVisit=visit,selectedBinding=binding;
      parts=[];bytes=0;
      chain=chain.then(async()=>{
        const value={id,binding:selectedBinding,codex_visit:selectedVisit,ordinal:index,blob,
          mime:'audio/wav',capture_started:Date.now(),native_review:true,captureStop,
          audio_sha256:await digest(blob)};
        // Keep the in-memory original even if durable local admission fails.
        originals.set(id,value);onRecovery([...originals.values()]);
        await recovery.put(value,true);
        try{await upload(value);}catch{state('Original recording kept for recovery.');}
      }).catch(()=>{void hold('Local recording storage needs review. Save the retained original.');});
    }
    async function hold(message='Voice paused. Accepted work continues.'){
      if(closing)return;closing=true;active=starting=connected=false;clearTimeout(timer);state(message);
      for(const track of media?.getTracks()||[])track.stop();media=undefined;
      if(capture){
        const finished=new Promise(resolve=>{finishAck=resolve;});capture.finish();
        const complete=await Promise.race([finished,new Promise(resolve=>setTimeout(()=>resolve(false),1000))]);
        flush(complete?undefined:'audio_flush_unconfirmed');unsubscribe?.();unsubscribe=undefined;capture.close();capture=undefined;
      }else flush();
      channel?.close();channel=undefined;peer?.close();peer=undefined;if(audio){audio.pause();audio.srcObject=null;audio=undefined;}
      if(socket?.readyState===WebSocket.OPEN){
        const ended=new Promise(resolve=>{closeAck=resolve;});
        try{socket.send(JSON.stringify({type:'close'}));}catch{closeAck(false);}
        let deadline;await Promise.race([ended,new Promise(resolve=>{deadline=setTimeout(resolve,3000);})]);clearTimeout(deadline);
      }
      socket?.close();socket=undefined;closeAck=undefined;
      await chain;closing=false;state(message);onRecovery([...originals.values()]);
    }
    async function start(){
      if(active||starting||closing||document.hidden||!supported())return false;
      if(openingCount>=2){state('Finish the pending microphone permission before starting again.');return false;}
      openingCount++;
      binding=getBinding();const owned=++epoch;visit=crypto.randomUUID();parts=[];bytes=total=ordinal=0;
      const selectedBinding=binding;let ownedMedia,ownedCapture,ownedPeer,ownedChannel,ownedAudio;
      const current=()=>owned===epoch&&(active||starting)&&!closing&&selectedBinding===getBinding();
      function closeRetired(){
        ownedCapture?.close();ownedChannel?.close();ownedPeer?.close();ownedAudio?.pause();
        for(const track of ownedMedia?.getTracks()||[])track.stop();
      }
      starting=true;paused=false;connected=false;state('Preparing voice');
      try{
        const pending=await review();
        if(!current())throw Error('Voice recovery read retired');
        if(pending.some(v=>v.binding!==binding)||pending.reduce((sum,v)=>sum+v.blob.size,0)>20*1024*1024-600*32000)
          throw Error('Recover retained originals before starting another voice visit.');
        const target=new URL('api/interaction/voice/codex',window.location.href);target.protocol=target.protocol==='https:'?'wss:':'ws:';
        socket=new WebSocket(target);
        const transport=socket;
        let preparedResolve,preparedReject,answerResolve,answerReject;
        const prepared=new Promise((yes,no)=>{preparedResolve=yes;preparedReject=no;});
        const answer=new Promise((yes,no)=>{answerResolve=yes;answerReject=no;});answer.catch(()=>{});
        socket.onopen=()=>{if(!current()||socket!==transport)return;const h=headers(),authorization=h.Authorization||h.authorization;
          transport.send(JSON.stringify({id:visit,binding,csrf:h['X-Dashboard-CSRF']||h['x-dashboard-csrf'],...(authorization?{authorization}:{})}));};
        socket.onmessage=event=>{
          if(owned!==epoch||socket!==transport)return;
          try{
            if(typeof event.data!=='string'||event.data.length>70000)throw Error('Voice control exceeds bound');
            const value=JSON.parse(event.data);
            if(value.id!==visit)throw Error('Voice visit changed');
            if(value.type==='closed'){closeAck?.(value.confirmed===true);return;}
            if(closing)return;
            if(value.type==='prepared'){
              if(!Number.isInteger(value.session_seconds)||value.session_seconds<300||value.session_seconds>600)throw Error('Voice duration changed');
              seconds=value.session_seconds;preparedResolve();
            }else if(value.type==='answer')answerResolve(value.sdp);
            else if(value.type==='transcript'){
              onCaption(value.item.text);onItem({visit,item:value.item,observed_at:Date.now()/1000});
            }else if(value.type==='review')throw Error(value.message);
          }catch(error){preparedReject(error);answerReject(error);void hold(error.message);}
        };
        socket.onclose=()=>{if(owned!==epoch||socket!==transport)return;closeAck?.(false);preparedReject(Error('Voice connection ended'));answerReject(Error('Voice connection ended'));if(!closing)void hold('Voice connection ended. Original recordings are kept.');};
        const wait=async(promise,millis)=>{let id;try{return await Promise.race([promise,new Promise((_,no)=>{id=setTimeout(()=>no(Error('Voice connection timed out')),millis);})]);}finally{clearTimeout(id);}};
        await wait(prepared,45000);
        if(!current())throw Error('Voice conversation changed');
        ownedMedia=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
        if(!current()||document.hidden)throw Error('Microphone activation ended');
        media=ownedMedia;peer=ownedPeer=new RTCPeerConnection();
        // Native WebRTC SDP includes the provider's events channel. Native Core
        // owns its handoffs; this client sends no response/turn control on it.
        channel=ownedChannel=ownedPeer.createDataChannel('oai-events');ownedChannel.onmessage=()=>{};
        audio=ownedAudio=new Audio();audio.autoplay=true;audio.muted=!audible;
        ownedPeer.ontrack=event=>{if(!current()||audio!==ownedAudio)return;ownedAudio.srcObject=event.streams[0]||new MediaStream([event.track]);ownedAudio.play().catch(()=>{if(current()){paused=true;state('Tap Resume audio to listen.');}});};
        ownedPeer.onconnectionstatechange=()=>{
          if(!current()||peer!==ownedPeer)return;
          if(ownedPeer.connectionState==='connected'){connected=true;starting=false;active=true;state('Listening');}
          else if(['failed','closed','disconnected'].includes(ownedPeer.connectionState))void hold('Voice connection paused. Your originals are kept.');
        };
        // Preserve microphone PCM before enabling its WebRTC sender. No manual
        // activity commits or acoustic turn loop is imposed on native voice.
        ownedCapture=await window.StreamingVoice.openCapture(ownedMedia,{sessionSeconds:seconds});
        if(!current())throw Error('Voice capture activation ended');
        capture=ownedCapture;
        unsubscribe=capture.subscribe(value=>{
          if(owned!==epoch)return;
          if(value.finished){finishAck?.(true);return;}
          if(value.captureError){if(!closing)void hold('Voice capture paused. Your originals are kept.');return;}
          if(!value.pcm)return;
          const pcm=value.pcm;
          if(!(pcm instanceof ArrayBuffer)||!pcm.byteLength||pcm.byteLength%2||pcm.byteLength>32000||total+pcm.byteLength>seconds*32000){void hold('Voice capture reached its bound.');return;}
          parts.push(pcm);bytes+=pcm.byteLength;total+=pcm.byteLength;
          if(bytes>=30*32000)flush();
          if(binding!==getBinding())void hold('Conversation changed. Your original audio is kept.');
        });
        capture.start();for(const track of ownedMedia.getAudioTracks())ownedPeer.addTrack(track,ownedMedia);
        const offer=await ownedPeer.createOffer();if(!current())throw Error('Voice offer retired');
        await ownedPeer.setLocalDescription(offer);if(!current())throw Error('Voice offer retired');
        transport.send(JSON.stringify({type:'offer',sdp:ownedPeer.localDescription.sdp}));
        const sdp=await wait(answer,45000);if(!current())throw Error('Voice answer retired');
        await ownedPeer.setRemoteDescription({type:'answer',sdp});if(!current())throw Error('Voice connection retired');
        timer=setTimeout(()=>void hold('Voice visit reached its time limit.'),seconds*1000);
        return true;
      }catch(error){if(owned===epoch&&(active||starting))await hold(error.message||'Voice unavailable.');closeRetired();return false;}
      finally{openingCount--;}
    }
    async function restoreHistory(){
      if(restored===getBinding())return;
      if(restoring)return restoring;
      const selected=getBinding();
      restoring=(async()=>{
        if((active||starting)&&binding!==selected)await hold('Conversation changed.');
        binding=selected;await review();if(getBinding()!==selected)throw Error('Voice history binding changed');
        const value=await request('visits');if(getBinding()!==selected)throw Error('Voice history binding changed');
        for(const entry of value.visits||[])for(const item of entry.items||[])onItem({visit:entry.id,item,observed_at:entry.created_at});
        restored=selected;
      })();
      try{return await restoring;}finally{restoring=undefined;}
    }
    return {start,reconnect:start,hold,restoreHistory,
      retry:async original=>{if(original.binding!==getBinding())throw Error('Recording belongs to a different conversation');binding=original.binding;await upload(original);state();},
      discard:async original=>{await recovery.remove(original);originals.delete(original.id);onRecovery([...originals.values()]);state();},
      setEnabled:value=>{audible=value===true;if(audio)audio.muted=!audible;state();},
      pause:()=>{paused=true;audio?.pause();state();},resume:()=>{paused=false;audio?.play().catch(()=>{paused=true;state('Tap Resume audio to listen.');});state();},
      release:()=>false,get originals(){return [];}, // Never feed native originals to ordinary Send recovery.
      get active(){return active||starting||closing;},get hasAudio(){return connected;},get paused(){return paused;},get floor(){return false;}};
  }
  return {supported,create};
})();
