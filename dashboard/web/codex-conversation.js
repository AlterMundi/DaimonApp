"use strict";
// Native WebRTC owns dialogue/interruption. This path stores originals only;
// its recovery actions never submit ASR, ordinary Send or a backend turn.
window.CodexConversation=(()=>{
  const supported=()=>!!(window.RTCPeerConnection&&window.StreamingVoice?.supported()&&window.VoiceInput?.recoveryStore&&window.indexedDB);
  function create({headers,getBinding,onState=()=>{},onCaption=()=>{},onItem=()=>{},onRecovery=()=>{},onHistory=()=>{}}){
    const recovery=window.VoiceInput?.recoveryStore('codex_voice');
    let socket,peer,channel,media,capture,unsubscribe,audio,visit,binding,active=false,starting=false,closing=false;
    let epoch=0,parts=[],bytes=0,total=0,ordinal=0,seconds=600,finishAck,closeAck,chain=Promise.resolve(),durable=Promise.resolve(),timer,fragmentParts=[],fragmentBytes=0,segment,persistingFragments=0;
    let audible=true,paused=false,connected=false,restored,restoring,historyBefore,historyGeneration=0,openingCount=0,unlockCapture;
    let admission,admissionDeadline,mediaVisit,captureEpoch=0,renewing=false,failureTimer,rejectOpening,replacementRequested=false,terminalClose=false;
    let activityAbort,activityObserver,outputLevel=0;
    const originals=new Map();
    const state=(message,preserveMessage=false)=>onState({active,starting:starting||renewing,reconnecting:renewing||replacementRequested||failureTimer!==undefined,floor:false,pending:originals.size>0,working:closing,
      audioEnabled:audible,audioPaused:paused,playback:paused?'paused':audible&&outputLevel>0?'playing':'idle',outputLevel:paused||!audible?0:outputLevel,...(preserveMessage?{}:{message})});
    function stopActivity(){activityAbort?.abort();activityAbort=undefined;activityObserver?.close();activityObserver=undefined;const previous=outputLevel;outputLevel=0;if(previous)state(undefined,true);}
    const digest=async blob=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',await blob.arrayBuffer()))].map(v=>v.toString(16).padStart(2,'0')).join('');
    async function request(path,options={}){
      const response=await fetch(new URL('api/interaction/voice/codex/'+path,window.location.href),{
        ...options,headers:{...headers(),'x-voice-binding':binding,...options.headers},
        signal:options.method==='POST'&&path.includes('/recordings/')?undefined:AbortSignal.timeout(30000)});
      if(!response.ok)throw Error('Recording could not be confirmed. Your local original is kept.');
      return response.json();
    }
    async function review(){
      const values=await recovery.list(),groups=new Map();originals.clear();
      for(const value of values){
        if(value.engine && value.engine!=='codex')continue;
        if(!value.native_fragment){originals.set(value.id,value);continue;}
        const group=groups.get(value.fragment_group)||[];group.push(value);groups.set(value.fragment_group,group);
      }
      for(const [id,fragments] of groups){
        fragments.sort((a,b)=>a.fragment_offset-b.fragment_offset);let offset=0;
        if(!/^[a-f0-9-]{36}$/.test(id)||fragments.length>32)throw Error('Native recording fragments need review');
        const first=fragments[0];
        for(const value of fragments){
          if(value.fragment_offset!==offset||value.binding!==first.binding||value.codex_visit!==first.codex_visit||value.ordinal!==first.ordinal||value.blob.size<=44||value.blob.size>64044||await digest(value.blob)!==value.audio_sha256)throw Error('Native recording fragments changed');
          offset+=value.blob.size-44;
        }
        if(offset>31*32000)throw Error('Native recording prefix exceeds its bound');
        const blob=window.StreamingVoice.wav(await Promise.all(fragments.map(value=>value.blob.slice(44).arrayBuffer())));
        originals.set(id,{...first,id,blob,native_fragment:undefined,fragment_group:undefined,fragment_offset:undefined,
          audio_sha256:await digest(blob),captureStop:'interrupted_prefix',native_fragments:fragments});
      }
      onRecovery([...originals.values()]);state();return [...originals.values()];
    }
    function withVisitLock(id,run){
      if(!navigator.locks?.request)return Promise.reject(Error('This browser cannot safely coordinate local voice recovery'));
      return navigator.locks.request('daimon-native-voice:'+id,{ifAvailable:true},lock=>{
        if(!lock)throw Error('The original voice capture is still finishing in another page');return run();
      });
    }
    async function upload(original,prefixChecked=false){
      if(original.binding!==getBinding())throw Error('Recording belongs to a different conversation');
      if(original.captureStop==='interrupted_prefix'&&!prefixChecked){
        const status=await request(`visits/${original.codex_visit}`);
        if(status.capture_prefix_retention!=='v1'||status.state!=='closed')throw Error('Keep the recovered prefix until its original voice visit is closed and supported');
      }
      const value=await request(`visits/${original.codex_visit}/recordings/${original.ordinal}`,{
        method:'POST',headers:{'content-type':'audio/wav',...(original.captureStop==='interrupted_prefix'?{'x-voice-capture-stop':'interrupted_prefix'}:{})},body:original.blob});
      const receipt=value.recording;
      if(value.visit!==original.codex_visit||value.binding!==original.binding
          ||receipt?.ordinal!==original.ordinal||receipt.audio_sha256!==original.audio_sha256
          ||receipt.audio_bytes!==original.blob.size||receipt.native_replay!=='never'||original.captureStop==='interrupted_prefix'&&receipt.capture_stop!=='interrupted_prefix')throw Error('Original receipt changed');
      await recovery.remove(original);originals.delete(original.id);onRecovery([...originals.values()]);
      return receipt;
    }
    function checkpoint(){
      if(fragmentBytes<32000)return;
      if(persistingFragments>=2){void hold('Local recording storage is falling behind. Your retained audio needs review.');return;}
      const selected=segment,blob=window.StreamingVoice.wav(fragmentParts),offset=selected.offset;selected.offset+=fragmentBytes;
      fragmentParts=[];fragmentBytes=0;persistingFragments++;
      durable=durable.then(async()=>{
        if(selected.failed)return;
        const value={id:crypto.randomUUID(),binding:selected.binding,codex_visit:selected.visit,ordinal:selected.ordinal,
          blob,mime:'audio/wav',capture_started:selected.started,native_review:true,native_fragment:true,
          fragment_group:selected.id,fragment_offset:offset,audio_sha256:await digest(blob)};
        await recovery.put(value,true);selected.fragments.push(value);
      }).catch(()=>{selected.failed=true;void hold('Local recording storage needs review. Save the retained original.');}).finally(()=>{persistingFragments--;});
    }
    function flush(captureStop){
      if(!bytes)return;
      const blob=window.StreamingVoice.wav(parts),index=ordinal++,selected=segment,id=selected.id,selectedVisit=mediaVisit,selectedBinding=binding;
      parts=[];bytes=0;fragmentParts=[];fragmentBytes=0;
      segment={id:crypto.randomUUID(),binding,visit:mediaVisit,ordinal,started:Date.now(),offset:0,fragments:[]};
      const sealed=durable.then(async()=>{
        const value={id,binding:selectedBinding,codex_visit:selectedVisit,ordinal:index,blob,
          mime:'audio/wav',capture_started:Date.now(),native_review:true,captureStop,
          audio_sha256:await digest(blob)};
        // Keep the in-memory original even if durable local admission fails.
        originals.set(id,value);onRecovery([...originals.values()]);
        await recovery.sealNative(value,selected.fragments);return value;
      });
      durable=sealed.catch(()=>{void hold('Local recording storage needs review. Save the retained original.');});
      chain=chain.then(async()=>{const value=await sealed;try{await upload(value);}catch{state('Original recording kept for recovery.');}}).catch(()=>{void hold('Local recording storage needs review. Save the retained original.');});
    }
    async function hold(message='Voice paused. Accepted work continues.'){
      if(closing)return;closing=true;active=starting=connected=false;stopActivity();clearTimeout(timer);clearTimeout(failureTimer);failureTimer=undefined;state(message);
      const reject=rejectOpening;rejectOpening=undefined;reject?.(Error('Voice activation ended'));
      replacementRequested=false;
      const endedAdmission=admission?mediaVisit:undefined;admission=undefined;
      for(const track of media?.getTracks()||[])track.stop();media=undefined;
      if(capture){
        const finished=new Promise(resolve=>{finishAck=resolve;});capture.finish();
        const complete=await Promise.race([finished,new Promise(resolve=>setTimeout(()=>resolve(false),1000))]);
        flush(complete?undefined:'audio_flush_unconfirmed');unsubscribe?.();unsubscribe=undefined;capture.close();capture=undefined;
      }else flush();
      captureEpoch++;
      channel?.close();channel=undefined;peer?.close();peer=undefined;if(audio){audio.pause();audio.srcObject=null;audio=undefined;}
      if(socket?.readyState===WebSocket.OPEN&&!terminalClose){
        const ended=new Promise(resolve=>{closeAck=resolve;});
        try{socket.send(JSON.stringify({type:'close'}));}catch{closeAck(false);}
        let deadline;await Promise.race([ended,new Promise(resolve=>{deadline=setTimeout(resolve,3000);})]);clearTimeout(deadline);
      }
      socket?.close();socket=undefined;closeAck=undefined;
      if(endedAdmission){try{await request(`visits/${endedAdmission}/capture/ended`,{method:'POST'});}catch{/* Exact originals remain recoverable; no capture or work retry. */}}
      await chain;unlockCapture?.();unlockCapture=undefined;closing=false;state(message);onRecovery([...originals.values()]);
    }
    function acceptAdmission(value,continuing){
      if(!value||value.id!==mediaVisit||!Number.isFinite(value.remaining_seconds)||value.remaining_seconds<=0||value.remaining_seconds>seconds
          ||!Number.isFinite(value.expires)||value.max_input_pcm_bytes!==seconds*32000
          ||value.generation!==(continuing?admission?.generation+1:0)
          ||continuing&&value.expires!==admission?.expires)throw Error('Microphone admission changed');
      if(!continuing)admissionDeadline=Date.now()+value.remaining_seconds*1000;
      admission=value;
    }
    async function renew(){
      if(renewing||closing||!active||starting||openingCount||!admission||admission.generation>=7||Date.now()>=admissionDeadline-2000){
        if(!closing)void hold('Voice paused. Your originals and accepted work are kept.');return;
      }
      renewing=true;const predecessor=visit;++epoch;active=starting=connected=false;stopActivity();clearTimeout(failureTimer);failureTimer=undefined;
      channel?.close();channel=undefined;peer?.close();peer=undefined;
      if(audio){audio.pause();audio.srcObject=null;audio=undefined;}socket?.close();socket=undefined;
      // Capture, its Web Lock, ordinals, PCM allowance and original deadline
      // survive. Audio during setup remains original evidence, never replayed
      // as new speech or silently submitted to ASR/backend work.
      state('Reconnecting voice; microphone recording is kept.');
      try{
        const resumed=await start(predecessor);
        if(!resumed&&(capture||media)&&!closing)await hold('Voice paused. Your originals and accepted work are kept.');
      }finally{renewing=false;state(connected?'Listening':undefined,!connected);}
    }
    async function start(predecessor){
      const continuing=typeof predecessor==='string'&&renewing;
      if(active||starting||closing||document.hidden||!supported())return false;
      if(openingCount>=2){state('Finish the pending microphone permission before starting again.');return false;}
      openingCount++;
      if(!continuing){
        binding=getBinding();mediaVisit=crypto.randomUUID();admission=undefined;captureEpoch++;
        parts=[];bytes=total=ordinal=0;fragmentParts=[];fragmentBytes=0;
        segment={id:crypto.randomUUID(),binding,visit:mediaVisit,ordinal:0,started:Date.now(),offset:0,fragments:[]};
      }
      const owned=++epoch,logicalCapture=captureEpoch;visit=continuing?crypto.randomUUID():mediaVisit;
      replacementRequested=false;terminalClose=false;
      let startupStage='preparing';
      const selectedBinding=binding;let ownedMedia,ownedCapture,ownedPeer,ownedChannel,ownedAudio,ownedUnlock,ownedReject,ownedActivityAbort,ownedActivityObserver;
      const current=()=>owned===epoch&&(active||starting)&&!closing&&selectedBinding===getBinding();
      function closeRetired(){
        if(ownedCapture!==capture)ownedCapture?.close();ownedChannel?.close();ownedPeer?.close();ownedAudio?.pause();
        ownedActivityAbort?.abort();ownedActivityObserver?.close();
        if(ownedUnlock!==unlockCapture)ownedUnlock?.();
        if(!continuing&&(!closing||logicalCapture!==captureEpoch))for(const track of ownedMedia?.getTracks()||[])track.stop();
      }
      starting=true;if(!continuing)paused=false;connected=false;state(continuing?'Reconnecting voice; microphone recording is kept.':'Preparing voice');
      try{
        if(!continuing){
        const pending=await review();
        if(!current())throw Error('Voice recovery read retired');
        if(pending.some(v=>v.binding!==binding)||pending.reduce((sum,v)=>sum+v.blob.size,0)>20*1024*1024-600*32000)
          throw Error('Recover retained originals before starting another voice visit.');
        await new Promise((resolve,reject)=>{
          withVisitLock(visit,()=>new Promise(done=>{let released=false;ownedUnlock=()=>{if(!released){released=true;done();}};resolve();})).catch(reject);
        });
        if(!current()){ownedUnlock?.();throw Error('Voice storage ownership retired');}unlockCapture=ownedUnlock;
        }
        const target=new URL('api/interaction/voice/codex',window.location.href);target.protocol=target.protocol==='https:'?'wss:':'ws:';
        socket=new WebSocket(target);
        const transport=socket;
        let preparedResolve,preparedReject,answerResolve,answerReject,captureResolve,captureReject;
        const prepared=new Promise((yes,no)=>{preparedResolve=yes;preparedReject=no;});
        const answer=new Promise((yes,no)=>{answerResolve=yes;answerReject=no;});answer.catch(()=>{});
        const captureReady=new Promise((yes,no)=>{captureResolve=yes;captureReject=no;});captureReady.catch(()=>{});
        rejectOpening=ownedReject=error=>{preparedReject(error);answerReject(error);captureReject(error);};
        socket.onopen=()=>{if(!current()||socket!==transport)return;const h=headers(),authorization=h.Authorization||h.authorization;
          transport.send(JSON.stringify({id:visit,binding,logical_visit:true,...(continuing?{predecessor}:{}),csrf:h['X-Dashboard-CSRF']||h['x-dashboard-csrf'],...(authorization?{authorization}:{})}));};
        socket.onmessage=event=>{
          if(owned!==epoch||socket!==transport)return;
          try{
            if(typeof event.data!=='string'||event.data.length>70000)throw Error('Voice control exceeds bound');
            const value=JSON.parse(event.data);
            if(value.id!==visit)throw Error('Voice visit changed');
            if(value.type==='closed'){
              terminalClose=true;
              closeAck?.(value.confirmed===true);
              if(!closing){
                if(value.confirmed===true&&value.successor_ready===true&&(value.reason==='native_transport_closed'
                    ||value.reason==='media_replacement'&&replacementRequested))void renew();
                else void hold('Voice paused. Your originals and accepted work are kept.');
              }return;
            }
            if(closing)return;
            if(value.type==='prepared'){
              if(!Number.isInteger(value.session_seconds)||value.session_seconds<300||value.session_seconds>600)throw Error('Voice duration changed');
              if(value.logical_visit!=='v1'||continuing&&value.session_seconds!==seconds)throw Error('Logical voice continuation is unavailable');
              seconds=value.session_seconds;
              if(continuing)acceptAdmission(value.admission,true);
              else if(value.admission!==null)throw Error('Microphone admission already exists');
              preparedResolve();
            }else if(value.type==='capture_ready'){
              if(continuing||admission)throw Error('Microphone admission was repeated');
              acceptAdmission(value.admission,false);captureResolve();
            }else if(value.type==='answer')answerResolve(value.sdp);
            else if(value.type==='transcript'){
              onCaption(value.item.text);onItem({visit,item:value.item,observed_at:Date.now()/1000});
            }else if(value.type==='review')throw Error(value.message);
          }catch(error){preparedReject(error);answerReject(error);captureReject(error);void hold(error.message);}
        };
        socket.onclose=()=>{if(owned!==epoch||socket!==transport)return;closeAck?.(false);preparedReject(Error('Voice connection ended'));answerReject(Error('Voice connection ended'));captureReject(Error('Voice connection ended'));if(!closing)void hold('Voice connection ended. Original recordings are kept.');};
        const wait=async(promise,millis)=>{let id;try{return await Promise.race([promise,new Promise((_,no)=>{id=setTimeout(()=>no(Error('Voice connection timed out')),millis);})]);}finally{clearTimeout(id);}};
        await wait(prepared,45000);
        if(!current())throw Error('Voice conversation changed');
        startupStage='microphone';
        ownedMedia=continuing?media:await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
        if(!current()||document.hidden)throw Error('Microphone activation ended');
        startupStage='peer';
        media=ownedMedia;peer=ownedPeer=new RTCPeerConnection();
        // Native WebRTC SDP includes the provider's events channel. Native Core
        // owns its handoffs; this client sends no response/turn control on it.
        channel=ownedChannel=ownedPeer.createDataChannel('oai-events');ownedChannel.onmessage=()=>{};
        audio=ownedAudio=new Audio();audio.autoplay=!paused;audio.muted=!audible;
        ownedPeer.ontrack=event=>{
          if(!current()||audio!==ownedAudio)return;
          stopActivity();const stream=event.streams[0]||new MediaStream([event.track]);ownedAudio.srcObject=stream;
          if(!paused)ownedAudio.play().catch(()=>{if(current()){paused=true;outputLevel=0;state('Tap Resume audio to listen.');}});
          activityAbort=ownedActivityAbort=new AbortController();const signal=ownedActivityAbort.signal;
          const playing=()=>current()&&!signal.aborted&&audio===ownedAudio&&ownedAudio.srcObject===stream&&!paused&&audible&&!ownedAudio.paused&&!ownedAudio.muted;
          const activity=rms=>{
            if(!current()||signal.aborted||audio!==ownedAudio||ownedAudio.srcObject!==stream)return;
            const level=playing()?Math.round(Math.min(1,Math.max(0,Number.isFinite(rms)?rms:0)*6)*4)/4:0;
            if(level!==outputLevel){outputLevel=level;state();}
          };
          // Cosmetic output observation reuses the existing bounded, outputless
          // worklet. HTML audio remains the only player; no new voice session.
          if(window.WebRtcNativeAudio?.observe)void window.WebRtcNativeAudio.observe(stream,{sessionSeconds:seconds,signal,isPlaying:playing,onActivity:activity})
            .then(value=>{if(!current()||signal.aborted)value.close();else activityObserver=ownedActivityObserver=value;}).catch(()=>{if(current()&&!signal.aborted)activity(0);});
        };
        ownedPeer.onconnectionstatechange=()=>{
          if(!current()||peer!==ownedPeer)return;
          if(ownedPeer.connectionState==='connected'){
            if(replacementRequested){state('Reconnecting voice; microphone recording is kept.');return;}
            clearTimeout(failureTimer);failureTimer=undefined;
            const first=!connected;connected=true;starting=false;active=true;state('Listening');
            if(first&&transport.readyState===WebSocket.OPEN)transport.send(JSON.stringify({type:'ready'}));
          }
          else if(['failed','closed','disconnected'].includes(ownedPeer.connectionState)){
            connected=false;
            // Wait once for the exact native terminal barrier, never infer it
            // from a failed peer or a timeout. The original visit timer binds.
            if(!failureTimer)failureTimer=setTimeout(()=>{
              failureTimer=undefined;
              if(!current()||closing)return;
              if(!admission||transport.readyState!==WebSocket.OPEN){void hold('Voice connection paused. Your originals are kept.');return;}
              replacementRequested=true;
              try{transport.send(JSON.stringify({type:'renew'}));}
              catch{void hold('Voice connection paused. Your originals are kept.');return;}
              failureTimer=setTimeout(()=>void hold('Voice replacement was not confirmed. Your originals are kept.'),15000);
            },3000);
            state('Voice connection paused; microphone recording is kept.');
          }
        };
        // Preserve microphone PCM before enabling its WebRTC sender. No manual
        // activity commits or acoustic turn loop is imposed on native voice.
        if(!continuing){
        transport.send(JSON.stringify({type:'capture'}));await wait(captureReady,10000);
        if(!current())throw Error('Microphone admission retired');
        startupStage='recorder';
        ownedCapture=await window.StreamingVoice.openCapture(ownedMedia,{sessionSeconds:seconds});
        if(!current())throw Error('Voice capture activation ended');
        capture=ownedCapture;
        unsubscribe=capture.subscribe(value=>{
          if(logicalCapture!==captureEpoch)return;
          if(value.finished){finishAck?.(true);return;}
          if(value.captureError){if(!closing)void hold('Voice capture paused. Your originals are kept.');return;}
          if(!value.pcm)return;
          const pcm=value.pcm;
          if(!(pcm instanceof ArrayBuffer)||!pcm.byteLength||pcm.byteLength%2||pcm.byteLength>32000||total+pcm.byteLength>seconds*32000){void hold('Voice capture reached its bound.');return;}
          parts.push(pcm);bytes+=pcm.byteLength;total+=pcm.byteLength;fragmentParts.push(pcm);fragmentBytes+=pcm.byteLength;checkpoint();
          if(bytes>=30*32000)flush();
          if(binding!==getBinding())void hold('Conversation changed. Your original audio is kept.');
        });
        // The visit budget starts with capture, not after SDP negotiation. Leave
        // the existing finish-ACK window time before the recorder hard limit.
        timer=setTimeout(()=>void hold('Voice visit reached its time limit.'),Math.max(0,admissionDeadline-Date.now()-2000));
        capture.start();
        }
        for(const track of ownedMedia.getAudioTracks())ownedPeer.addTrack(track,ownedMedia);
        startupStage='offer';
        const offer=await ownedPeer.createOffer();if(!current())throw Error('Voice offer retired');
        await ownedPeer.setLocalDescription(offer);if(!current())throw Error('Voice offer retired');
        transport.send(JSON.stringify({type:'offer',sdp:ownedPeer.localDescription.sdp}));startupStage='answer';
        const sdp=await wait(answer,45000);if(!current())throw Error('Voice answer retired');
        await ownedPeer.setRemoteDescription({type:'answer',sdp});if(!current())throw Error('Voice connection retired');
        return true;
      }catch(error){
        if(owned===epoch&&(active||starting)){
          const known=['NotAllowedError','NotFoundError','NotReadableError','OverconstrainedError','SecurityError','AbortError','NotSupportedError','InvalidStateError','TimeoutError'];
          const reason=known.includes(error.name)?error.name:'Error';
          if(['microphone','peer','recorder','offer'].includes(startupStage)&&socket?.readyState===WebSocket.OPEN)
            try{socket.send(JSON.stringify({type:'startup_failed',stage:startupStage,reason}));}catch{}
          const message=startupStage==='microphone'&&reason==='NotAllowedError'?'Microphone access was denied. Allow microphone access, then reconnect.':
            startupStage==='microphone'&&reason==='NotFoundError'?'No microphone is available. Connect one, then reconnect.':
            startupStage==='microphone'&&reason==='NotReadableError'?'The microphone could not be opened. Check whether another app is using it, then reconnect.':
            ['microphone','peer','recorder','offer'].includes(startupStage)?`Voice setup stopped at ${startupStage} (${reason}). Reconnect to try again.`:error.message||'Voice unavailable.';
          await hold(message);
        }
        closeRetired();return false;
      }
      finally{if(rejectOpening===ownedReject)rejectOpening=undefined;openingCount--;}
    }
    async function restoreHistory(older=false){
      const selected=getBinding(),generation=historyGeneration;
      if(!older&&restored===selected)return;
      if(restoring)return restoring;
      if(older&&(!historyBefore||restored!==selected))return;
      const cursor=older?historyBefore:undefined;
      onHistory({loading:true,more:!!historyBefore});
      restoring=(async()=>{
        if((active||starting)&&binding!==selected)await hold('Conversation changed.');
        binding=selected;await review();if(getBinding()!==selected||historyGeneration!==generation)throw Error('Voice history binding changed');
        const value=await request('visits'+(cursor?'?before='+encodeURIComponent(cursor):''));
        if(getBinding()!==selected||historyGeneration!==generation)throw Error('Voice history binding changed');
        if(value.more&&(!/^[a-f0-9-]{36}$/.test(value.before||'')||value.before===cursor))throw Error('Voice history cursor changed');
        for(const entry of value.visits||[])for(const item of entry.items||[])onItem({visit:entry.id,item,observed_at:entry.created_at});
        historyBefore=value.more?value.before:undefined;restored=selected;
        onHistory({loading:false,more:!!historyBefore});
      })();
      try{return await restoring;}
      catch(error){if(getBinding()===selected&&historyGeneration===generation)onHistory({loading:false,more:!!historyBefore,error:true,older});throw error;}
      finally{restoring=undefined;}
    }
    return {start:()=>start(),reconnect:()=>start(),hold,restoreHistory,
      resetHistory:()=>{historyGeneration++;restored=historyBefore=undefined;onHistory({loading:false,more:false});},
      retry:async original=>{if(original.binding!==getBinding())throw Error('Recording belongs to a different conversation');binding=original.binding;
        if(original.captureStop==='interrupted_prefix')return withVisitLock(original.codex_visit,async()=>{
          const status=await request(`visits/${original.codex_visit}`);if(status.state!=='closed'||status.capture_prefix_retention!=='v1')throw Error('Original voice visit is not closed or prefix recovery is unavailable');
          if(original.native_fragments){
            const current=(await recovery.list()).find(value=>value.id===original.id);
            if(current){
              if(current.native_fragment||current.audio_sha256!==original.audio_sha256||current.binding!==original.binding||current.codex_visit!==original.codex_visit||current.ordinal!==original.ordinal||current.captureStop!=='interrupted_prefix')throw Error('Recovered original changed');
              original=current;
            }else{const {native_fragments,...sealed}=original;await recovery.sealNative(sealed,native_fragments);original=sealed;}
            originals.set(original.id,original);
          }
          await upload(original,true);state();
        });
        await upload(original);state();},
      discard:async original=>{if(original.native_fragments)await withVisitLock(original.codex_visit,async()=>{
        const current=(await recovery.list()).find(value=>value.id===original.id);
        if(current){
          if(current.native_fragment||current.audio_sha256!==original.audio_sha256||current.binding!==original.binding||current.codex_visit!==original.codex_visit||current.ordinal!==original.ordinal||current.captureStop!=='interrupted_prefix')throw Error('Recovered original changed');
          await recovery.remove(current);
        }else await recovery.discardNative(original.native_fragments);
      });else await recovery.remove(original);originals.delete(original.id);onRecovery([...originals.values()]);state();},
      setEnabled:value=>{audible=value===true;if(!audible)outputLevel=0;if(audio)audio.muted=!audible;state();},
      pause:()=>{paused=true;outputLevel=0;audio?.pause();state();},resume:()=>{paused=false;audio?.play().catch(()=>{paused=true;outputLevel=0;state('Tap Resume audio to listen.');});state();},
      release:()=>false,get originals(){return [];}, // Never feed native originals to ordinary Send recovery.
      get active(){return active||starting||closing||renewing;},get hasAudio(){return connected;},get paused(){return paused;},get floor(){return false;}};
  }
  return {supported,create};
})();
