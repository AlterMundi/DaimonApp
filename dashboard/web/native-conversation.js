"use strict";
// Explicit avatar owner: native speech, exact local recovery and bounded PCM.
window.NativeConversation=(()=>{
  const nativePcm=()=>window.NativeSpeechAudio?.pcm===true&&typeof window.NativeSpeechAudio.openPcm==='function';
  const supported=()=>!!(window.StreamingVoice?.supported()&&window.crypto?.randomUUID&&window.navigator?.mediaDevices?.getUserMedia&&(!window.NativeSpeechAudio?.backgroundPlayback||nativePcm()));
  function create({headers,getBinding,getQuestions,retain,release,reviewOriginal=async()=>{},prepareReconnect=async originals=>{if(originals.length)throw Error('Recording recovery is unavailable');},onReview=()=>{},onState=()=>{},onCaption=()=>{},onUtterance=()=>{},onInterrupt=()=>{},onHandoff=()=>{},onTiming=()=>{}}){
    let active=false,starting=false,floor=false,epoch=0,binding,dialogue,questions,socket,media,capture,unsubscribe,context,timer,chain=Promise.resolve(),pendingEvents=0;
    let parts=[],bytes=0,originals=new Map(),rawRetained=new Set(),uninterpreted=new Set(),markedReview=new Set(),current,writing=Promise.resolve(),nodes=new Set(),next=0,played=new Map(),received=new Map(),retired=new Set(),stopped=true,audible=true,blocked=false,lastEnded,pendingScope,lastRemaining,latestOutput,questionScope,nativeOutput,userPaused=false;
    let playbackReporting=false,playbackReports=0,playbackCounts;
    let sessionSeconds=300,pcmBase=0,originalRanges=new Map(),closeSnapshot;
    const emitState=value=>onState({...value,audioPaused:userPaused,audioEnabled:audible});
    const state=message=>emitState({active,starting,floor,pending:stopped&&originals.size>0,working:false,message,remaining:current?Math.max(0,Math.ceil(120-(bytes-current.start)/32000)):undefined});
    function control(value){try{if(socket?.readyState===WebSocket.OPEN){socket.send(JSON.stringify(value));return true;}}catch{}return false;}
    function diagnosePlayback(){
      if(!playbackReporting||stopped||playbackReports>=32)return;
      const observed=context?.state,contextState=nativeOutput?'native':['running','suspended','interrupted','closed'].includes(observed)?observed:'unavailable';
      if(control({type:'playback_status',...playbackCounts,context:contextState,audible,user_paused:userPaused,floor,blocked}))playbackReports++;
    }
    function position(node){return context.currentTime<=node.at?0:Math.min(node.end,node.begin+Math.floor((context.currentTime-node.at)*24000)*2);}
    function report(id,count){const previous=played.get(id)||0;if(count<=previous)return;played.set(id,count);if(previous===0)onTiming(id,'output_progress');control({type:'playback',id,played_bytes:count});}
    function retireOutput(id){if(id&&!retired.has(id)){retired.add(id);onTiming(id,'output_retired');}}
    function silence(retire=false){
      if(nativeOutput)for(const id of nativeOutput.flush())retireOutput(id);
      if(retire&&latestOutput)retireOutput(latestOutput);
      for(const node of nodes){if(retire)retireOutput(node.id);node.cancelled=true;report(node.id,position(node));try{node.source.stop();node.source.disconnect();}catch{}}
      nodes.clear();next=context?.currentTime||0;emitState({active,starting,floor,pending:false,playback:'paused'});
    }
    function pendingTiming(stage){
      // Only actually queued output: a received-but-muted tail is not pending.
      const ids=nativeOutput?(nativeOutput.hasAudio?[...played.keys()]:[]):new Set([...nodes].map(node=>node.id));
      for(const id of ids)if(!retired.has(id)&&(played.get(id)||0)<received.get(id))onTiming(id,stage);
    }
    function pauseOutput(){
      const owned=epoch;
      if(nativeOutput)nativeOutput.pause();
      else if(context)void context.suspend().then(()=>{if(!stopped&&owned===epoch&&context?.state==='suspended')emitState({active,starting,floor,pending:false,playback:'paused'});}).catch(()=>{if(owned===epoch)hold('Voice playback could not pause.');});
    }
    function resumeOutput(){
      const owned=epoch;
      if(stopped||!audible||userPaused||floor||blocked)return;
      pendingTiming('output_release_requested');
      if(nativeOutput)nativeOutput.resume();
      else if(context)void context.resume().then(()=>{if(!stopped&&owned===epoch){emitState({active,starting,floor,pending:false,playback:nodes.size?'playing':'idle'});diagnosePlayback();}}).catch(()=>{if(owned===epoch)hold('Voice playback could not resume.');});
    }
    async function play(value,owned){
      if(value.sample_rate!==24000||typeof value.pcm!=='string'||value.pcm.length>350000||!Number.isSafeInteger(value.end))throw Error('Invalid native audio');
      const raw=atob(value.pcm);if(!raw.length||raw.length%2)throw Error('Invalid native PCM');
      const begin=received.get(value.id)||0;if(value.end!==begin+raw.length||value.end>sessionSeconds*48000)throw Error('Native audio continuity changed');
      received.set(value.id,value.end);latestOutput=value.id;onTiming(value.id,'output_handled');
      playbackCounts.handled++;
      if(!audible||floor||retired.has(value.id)){
        playbackCounts[!audible?'skipped_muted':floor?'skipped_floor':'skipped_retired']++;
        if(begin===0)diagnosePlayback();return;
      }
      if(nativeOutput){
        const bytes=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);
        const scheduled=await nativeOutput.append(value.id,value.end,bytes);
        if(stopped||owned!==epoch)return;
        if(scheduled){playbackCounts.scheduled++;if(!played.has(value.id))played.set(value.id,0);onTiming(value.id,'output_scheduled');}
        if(begin===0)diagnosePlayback();return;
      }
      if(nodes.size>=512||Math.max(next,context.currentTime)-context.currentTime+raw.length/48000>30)throw Error('Native playback exceeded its queue bound');
      const samples=new Float32Array(raw.length/2);
      for(let i=0;i<samples.length;i++){const n=raw.charCodeAt(2*i)|(raw.charCodeAt(2*i+1)<<8);samples[i]=(n>=32768?n-65536:n)/32768;}
      const buffer=context.createBuffer(1,samples.length,24000);buffer.copyToChannel(samples,0);
      const source=context.createBufferSource();source.buffer=buffer;source.connect(context.destination);
      const at=Math.max(context.currentTime+.01,next),node={source,at,id:value.id,begin,end:value.end,cancelled:false};
      next=at+buffer.duration;nodes.add(node);
      source.onended=()=>{if(owned!==epoch)return;nodes.delete(node);source.disconnect();if(!node.cancelled){playbackCounts.ended++;report(node.id,node.end);onTiming(node.id,'output_buffer_ended');if(node.begin===0)diagnosePlayback();}if(!nodes.size)emitState({active,starting,floor,pending:false,playback:'idle'});};
      source.start(at);playbackCounts.scheduled++;if(begin===0)diagnosePlayback();onTiming(value.id,'output_scheduled');emitState({active,starting,floor,pending:false,playback:context.state==='suspended'?'paused':'playing'});
    }
    function slice(start,end){
      if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start<0||end<=start||end>bytes||end-start>120*32000)throw Error('Original PCM range unavailable');
      const values=[];let cursor=start;
      for(const part of parts){if(part.end<=cursor)continue;if(part.start>cursor)throw Error('Original PCM gap');const stop=Math.min(end,part.end);values.push(part.pcm.slice(cursor-part.start,stop-part.start));cursor=stop;if(cursor===end)break;}
      if(cursor!==end)throw Error('Original PCM missing');return values;
    }
    function keep(span){
      if(originals.has(span.id))return originals.get(span.id);
      if([...originals.keys()].filter(id=>!rawRetained.has(id)||!uninterpreted.has(id)).length>=2)throw Error('Two originals await confirmation');
      // Retained review originals are distinct from in-flight confirmations.
      // Keep the server's128-original ceiling and the same session PCM bound.
      if(originals.size>=128)throw Error('Review recording capacity reached');
      const value={id:span.id,binding,foreground_dialogue:dialogue,capture_started:Date.now(),captureQuestions:span.questions,
        blob:window.StreamingVoice.wav(slice(span.start,span.end)),mime:'audio/wav',submissionRequested:false};
      const promise=writing.then(()=>retain(value)).then(frozen=>{originals.set(span.id,frozen);return frozen;});
      // Reserve capacity before an asynchronous IndexedDB write completes.
      originals.set(span.id,value);originalRanges.set(span.id,{start:span.start,end:span.end});writing=promise.then(()=>{},()=>{});return promise;
    }
    async function markReviewed(id,owned){
      if(rawRetained.has(id)&&uninterpreted.has(id)&&!markedReview.has(id)){
        await reviewOriginal(originals.get(id));if(!stopped&&owned===epoch)markedReview.add(id);
      }
    }
    function hold(message='Voice ended. Your unconfirmed originals are kept for review.',recoverUnassigned=false,cause='client_hold'){
      if(stopped)return;
      closeSnapshot={previous_dialogue:dialogue,cause,audio_bytes:bytes,retained_originals:originals.size,
        pending_events:pendingEvents,queued_audio_bytes:Math.min(32000000,socket?.bufferedAmount||0),
        generated_audio_bytes:[...received.values()].reduce((a,b)=>a+b,0),played_audio_bytes:[...played.values()].reduce((a,b)=>a+b,0),
        playback_context:nativeOutput?'native':context?.state||'unavailable',floor,blocked,user_paused:userPaused};
      diagnosePlayback();stopped=true;active=starting=floor=false;clearTimeout(timer);silence();
      if(current&&bytes>current.start){const span={...current,end:bytes};current=undefined;try{void Promise.resolve(keep(span)).catch(()=>onReview([...originals.values()]));}catch{}}
      unsubscribe?.();unsubscribe=undefined;capture?.close();capture=undefined;
      for(const track of media?.getTracks()||[])track.stop();media=undefined;
      try{control({type:'close',...(recoverUnassigned?{recover_unassigned:true}:{})});socket?.close();}catch{}socket=undefined;
      if(nativeOutput){nativeOutput.close();nativeOutput=undefined;}
      if(context){void context.close().catch(()=>{});context=undefined;}
      parts=[];bytes=0;retired.clear();latestOutput=undefined;if(originals.size)onHandoff({id:originals.keys().next().value,gate:'review'});state(message);void writing.finally(()=>onReview([...originals.values()]));
    }
    async function event(value,owned){
      if(stopped||owned!==epoch||binding!==getBinding())return;
      switch(value.type){
        case 'question_scope':{
          const scope=value.capture_questions;
          if(value.binding!==binding||!scope||typeof scope!=='object'||Array.isArray(scope)||Object.keys(scope).length>32||
              Object.entries(scope).some(([id,revision])=>!(/^[a-f0-9]{32}$/.test(id))||typeof revision!=='string'||!(/^[a-f0-9]{64}$/.test(revision))))throw Error('Canonical question scope changed');
          questionScope={...scope};break;
        }
        case 'audio':await play(value,owned);break;
        case 'capture_started':
          if(current||typeof value.id!=='string')throw Error('Original capture changed');
          onTiming(value.id,'capture_started');current={id:value.id,start:value.start,questions:pendingScope||questions};pendingScope=undefined;floor=true;blocked=true;silence(true);pauseOutput();onInterrupt();state('Listening');
          onHandoff({id:value.id,gate:'speaking'});break;
        case 'phrase_end':{
          if(!current||current.id!==value.id||current.start!==value.start)throw Error('Phrase boundary changed');
          onTiming(value.id,'phrase_end');const span={...current,end:value.end};current=undefined;floor=false;lastEnded=value.id;
          await keep(span);if(stopped||owned!==epoch)return;onTiming(value.id,'local_retained');onHandoff({id:value.id,gate:'waiting_transcript'});state('Phrase end detected');break;
        }
        case 'original_retained':{
          const original=originals.get(value.id);if(!original||original.audio_sha256!==value.sha256)throw Error('Retained original differs');
          rawRetained.add(value.id);await markReviewed(value.id,owned);if(stopped||owned!==epoch)return;onHandoff({id:value.id,gate:uninterpreted.has(value.id)?'review':'foreground_saved'});break;
        }
        case 'original_completed':{
          const original=originals.get(value.id);if(!original||original.audio_sha256!==value.sha256||value.phase!=='foreground')throw Error('Completed original differs');
          onTiming(value.id,'original_confirmed');await release(original,value.sha256);if(stopped||owned!==epoch)return;originals.delete(value.id);rawRetained.delete(value.id);uninterpreted.delete(value.id);markedReview.delete(value.id);
          const range=originalRanges.get(value.id);originalRanges.delete(value.id);
          if(range){
            if(current&&current.start<range.end)throw Error('Confirmed PCM overlaps live capture');
            pcmBase=Math.max(pcmBase,range.end);
            parts=parts.filter(part=>part.end>pcmBase).map(part=>part.start<pcmBase?{...part,start:pcmBase,pcm:part.pcm.slice(pcmBase-part.start)}:part);
          }
          break;
        }
        case 'input_caption':case 'input_transcript':onCaption(value.text);break;
        case 'assistant_utterance':if(value.utterance.text)onTiming(value.utterance.id,'output_text');onUtterance(value.utterance);onCaption(value.utterance.text);break;
        case 'interrupted':silence(true);break;
        case 'voice_activity':if(value.activity==='ACTIVITY_END'&&value.id===lastEnded){blocked=false;resumeOutput();}break;
        case 'turn_activity':
          if(current)onHandoff({id:current.id,gate:value.activity.speaking?'speaking':'waiting_endpoint'});break;
        case 'input_uninterpreted':
          if(!originals.has(value.id)||value.reason!=='empty_final_transcript')throw Error('Unknown original review');
          uninterpreted.add(value.id);await markReviewed(value.id,owned);if(stopped||owned!==epoch)return;
          if(value.id===lastEnded&&!floor){blocked=false;resumeOutput();}
          onHandoff({id:value.id,gate:'review'});state('No words confirmed. Recording kept for review; you can keep talking.');break;
        case 'input_interpreted':
          // Exact input confirmation is provider-neutral. Qwen commits an
          // input item instead of emitting Gemini's ACTIVITY_END event.
          if(value.id===lastEnded&&!floor){blocked=false;resumeOutput();}
          onTiming(value.id,'input_interpreted');onCaption(value.text);break;
        case 'reconnect_recorded':break;
        case 'review':case 'closing':hold(value.message||'Voice session ended.',false,'server_review');break;
      }
    }
    async function start({reconnect=false}={}){
      if(active||starting||originals.size&&!reconnect||document.hidden||!getBinding()||!supported())return false;
      const diagnostic=reconnect?closeSnapshot:undefined;
      const owned=++epoch;chain=Promise.resolve();pendingEvents=0;binding=getBinding();dialogue=crypto.randomUUID();questions=getQuestions?.();if(questions!==undefined)questions=JSON.parse(JSON.stringify(questions));stopped=false;audible=true;blocked=false;userPaused=false;questionScope=undefined;lastEnded=pendingScope=lastRemaining=latestOutput=undefined;starting=true;parts=[];bytes=0;current=undefined;rawRetained=new Set();uninterpreted=new Set();markedReview=new Set();received=new Map();played=new Map();retired=new Set();state('Preparing native voice');
      playbackReporting=false;playbackReports=0;playbackCounts={handled:0,scheduled:0,ended:0,skipped_floor:0,skipped_muted:0,skipped_retired:0};
      sessionSeconds=300;pcmBase=0;originalRanges=new Map();const requestedSeconds=nativePcm()?300:1800;
      // Unlock output in the explicit gesture; microphone waits for owner preflight.
      timer=setTimeout(()=>hold('Voice session reached five minutes.'),300000);
      try{
        if(nativePcm()){
          nativeOutput=window.NativeSpeechAudio.openPcm({onProgress:(id,count)=>{if(!stopped&&owned===epoch)report(id,count);},onBufferEnded:id=>{if(stopped||owned!==epoch)return;playbackCounts.ended++;onTiming(id,'output_buffer_ended');diagnosePlayback();},
            onState:playback=>{if(!stopped&&owned===epoch)emitState({active,starting,floor,pending:false,playback});},onUnavailable:message=>{if(owned===epoch)hold(message);}});
          await nativeOutput.ready;if(stopped||owned!==epoch)return false;
        }else{context=new (window.AudioContext||window.webkitAudioContext)();context.onstatechange=()=>{if(owned===epoch)diagnosePlayback();};void context.resume().catch(()=>{});}
        if(reconnect){
          await writing;
          if(stopped||owned!==epoch)return false;
          await prepareReconnect([...originals.values()]);
          if(stopped||owned!==epoch||binding!==getBinding())throw Error('Conversation changed before reconnect');
          originals=new Map();
        }
        const target=new URL('api/interaction/voice/native',window.location.href);target.protocol=target.protocol==='https:'?'wss:':'ws:';
        const opened=new Promise((resolve,reject)=>{
          socket=new WebSocket(target);
          socket.onopen=()=>{if(owned!==epoch||stopped)return;try{const h=headers(),authorization=h.Authorization||h.authorization;socket.send(JSON.stringify({id:dialogue,binding,csrf:h['X-Dashboard-CSRF']||h['x-dashboard-csrf'],capture_questions:questions,session_seconds:requestedSeconds,...(diagnostic?{reconnect:diagnostic}:{}),...(authorization?{authorization}:{})}));}catch(error){reject(error);}};
          socket.onmessage=message=>{
            if(owned!==epoch||stopped)return;
            try{
              if(typeof message.data!=='string'||message.data.length>400000||pendingEvents>=128)throw Error('Native event backlog exceeded');
              const value=JSON.parse(message.data);
              if(value.type==='ready'){
                const seconds=value.session_seconds??300;
                if(value.id!==dialogue||!['manual','automatic'].includes(value.activity_mode)||!Number.isSafeInteger(seconds)||seconds<300||seconds>requestedSeconds||seconds>300&&value.activity_mode!=='manual')throw Error('Native mode or duration changed');
                sessionSeconds=seconds;clearTimeout(timer);timer=setTimeout(()=>hold('Voice session reached its time limit.',true),sessionSeconds*1000);
                playbackReporting=value.playback_status===true;resolve();return;
              }
              if(value.type==='review'&&starting){reject(Error(value.message));return;}
              pendingEvents++;chain=chain.then(()=>event(value,owned)).catch(error=>{if(owned===epoch&&!stopped)hold(error.message);}).finally(()=>{if(owned===epoch)pendingEvents--;});
            }catch(error){reject(error);hold(error.message);}
          };
          socket.onerror=socket.onclose=()=>{reject(Error('Native voice disconnected'));if(owned===epoch)hold(undefined,false,'transport_closed');};
        });
        let readyTimer;
        try{await Promise.race([opened,new Promise((_,reject)=>{readyTimer=setTimeout(()=>reject(Error('Native voice readiness timed out')),45000);})]);}
        finally{clearTimeout(readyTimer);}
        if(stopped||owned!==epoch||binding!==getBinding())return false;
        const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
        if(stopped||owned!==epoch||document.hidden){for(const t of stream.getTracks())t.stop();return false;}media=stream;
        const openedCapture=await window.StreamingVoice.openCapture(media,{sessionSeconds});
        if(stopped||owned!==epoch){openedCapture.close();return false;}capture=openedCapture;
        unsubscribe=capture.subscribe(value=>{
          if(stopped||owned!==epoch)return;
          if(binding!==getBinding()){hold('Conversation changed.');return;}
          if(value.captureError){hold('Microphone ended.',true);return;}
          if(!current&&!pendingScope&&Number.isSafeInteger(value.activityBytes)&&value.activityBytes>bytes){
            const snapshot=questionScope===undefined?getQuestions?.():questionScope;pendingScope=snapshot===undefined?{}:JSON.parse(JSON.stringify(snapshot));
            control({type:'capture_scope',audio_bytes:value.activityBytes,capture_questions:pendingScope});
          }
          // Energy freezes question scope only. Muting waits for the server's
          // confirmed capture_started, so ambient noise cannot own playback.
          if(!value.pcm)return;
          if(!(value.pcm instanceof ArrayBuffer)||!value.pcm.byteLength||value.pcm.byteLength%2||value.pcm.byteLength>32000){hold('Voice capture returned invalid audio. Your recording is kept for review.');return;}
          if(bytes+value.pcm.byteLength>sessionSeconds*32000){hold('Voice capture reached its time limit. Your recording is kept for review.',true);return;}
          if(current&&bytes+value.pcm.byteLength-current.start>120*32000){hold('Your phrase reached two minutes. The recording is kept for review.');return;}
          // This valid frame is already captured, even if transport has closed.
          // Retain it before the network guard so recovery includes that tail.
          const pcm=value.pcm;parts.push({start:bytes,end:bytes+pcm.byteLength,pcm});bytes+=pcm.byteLength;
          if(socket?.readyState!==WebSocket.OPEN){hold('Voice connection closed before this audio could be sent. Your recording is kept for review.');return;}
          if(socket.bufferedAmount>256000){hold('Voice upload is delayed: more than eight seconds of audio is waiting to send. Your recording is kept for review.');return;}
          try{socket.send(pcm);}catch{hold('Voice disconnected. Your recording is kept.');return;}
          if(sessionSeconds>300&&(bytes-pcmBase>=299*32000||current&&bytes-current.start>=119*32000)){
            hold('Voice reached its retained audio capacity. Your recording is kept for review.',true);return;
          }
          const remaining=current?Math.max(0,Math.ceil(120-(bytes-current.start)/32000)):undefined;
          if(remaining!==lastRemaining){lastRemaining=remaining;state('Listening');}
        });
        capture.observe();capture.start();active=true;starting=false;state('Listening');return true;
      }catch(error){if(owned===epoch)hold(error.message||'Native voice unavailable.');return false;}
    }
    return {start,reconnect:()=>start({reconnect:true}),hold,setEnabled:value=>{const enabled=value===true;if(audible===enabled)return;audible=enabled;if(!audible)silence();else resumeOutput();diagnosePlayback();},
      pause:(reason='manual')=>{userPaused=true;pauseOutput();diagnosePlayback();emitState({active,starting,floor,pending:false,playback:'paused',pauseReason:reason});},
      resume:()=>{userPaused=false;resumeOutput();},
      get hasAudio(){return !!nativeOutput?.hasAudio||nodes.size>0;},get paused(){return nativeOutput?.paused||context?.state==='suspended';},
      release:id=>{rawRetained.delete(id);uninterpreted.delete(id);markedReview.delete(id);return originals.delete(id);},get active(){return active||starting;},get floor(){return floor;},get originals(){return [...originals.values()];}};
  }
  return {supported,create};
})();
