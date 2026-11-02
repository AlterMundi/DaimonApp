"use strict";
// Explicit avatar owner: native speech, exact local recovery and bounded PCM.
window.NativeConversation=(()=>{
  const nativePcm=()=>window.NativeSpeechAudio?.pcm===true&&typeof window.NativeSpeechAudio.openPcm==='function';
  const supported=()=>!!(window.StreamingVoice?.supported()&&window.crypto?.randomUUID&&window.navigator?.mediaDevices?.getUserMedia&&(!window.NativeSpeechAudio?.backgroundPlayback||nativePcm()));
  function create({headers,getBinding,getQuestions,retain,release,onReview=()=>{},onState=()=>{},onCaption=()=>{},onUtterance=()=>{},onInterrupt=()=>{},onHandoff=()=>{},onTiming=()=>{}}){
    let active=false,starting=false,floor=false,epoch=0,binding,dialogue,questions,socket,media,capture,unsubscribe,context,timer,chain=Promise.resolve(),pendingEvents=0;
    let parts=[],bytes=0,originals=new Map(),current,writing=Promise.resolve(),nodes=new Set(),next=0,played=new Map(),received=new Map(),retired=new Set(),stopped=true,audible=true,blocked=false,lastEnded,pendingScope,lastRemaining,latestOutput,questionScope,nativeOutput,energyFence=0,lastEnergy=0,energyArmed=true,userPaused=false;
    const state=message=>onState({active,starting,floor,pending:stopped&&originals.size>0,working:false,message,remaining:current?Math.max(0,Math.ceil(120-(bytes-current.start)/32000)):undefined});
    function control(value){try{if(socket?.readyState===WebSocket.OPEN){socket.send(JSON.stringify(value));return true;}}catch{}return false;}
    function position(node){return context.currentTime<=node.at?0:Math.min(node.end,node.begin+Math.floor((context.currentTime-node.at)*24000)*2);}
    function report(id,count){const previous=played.get(id)||0;if(count<=previous)return;played.set(id,count);if(previous===0)onTiming(id,'output_progress');control({type:'playback',id,played_bytes:count});}
    function retireOutput(id){if(id&&!retired.has(id)){retired.add(id);onTiming(id,'output_retired');}}
    function silence(retire=false){
      if(nativeOutput)for(const id of nativeOutput.flush())retireOutput(id);
      if(retire&&latestOutput)retireOutput(latestOutput);
      for(const node of nodes){if(retire)retireOutput(node.id);node.cancelled=true;report(node.id,position(node));try{node.source.stop();node.source.disconnect();}catch{}}
      nodes.clear();next=context?.currentTime||0;onState({active,starting,floor,pending:false,playback:'paused'});
    }
    function pendingTiming(stage){
      // Only actually queued output: a received-but-muted tail is not pending.
      const ids=nativeOutput?(nativeOutput.hasAudio?[...played.keys()]:[]):new Set([...nodes].map(node=>node.id));
      for(const id of ids)if(!retired.has(id)&&(played.get(id)||0)<received.get(id))onTiming(id,stage);
    }
    function pauseOutput(){
      if(nativeOutput)nativeOutput.pause();
      else if(context)void context.suspend().then(()=>{if(!stopped&&context?.state==='suspended')onState({active,starting,floor,pending:false,playback:'paused'});}).catch(()=>hold('Voice playback could not pause.'));
    }
    function resumeOutput(){
      if(stopped||!audible||userPaused||energyFence)return;
      pendingTiming('output_release_requested');
      if(nativeOutput)nativeOutput.resume();
      else if(context)void context.resume().then(()=>{if(!stopped)onState({active,starting,floor,pending:false,playback:nodes.size?'playing':'idle'});}).catch(()=>hold('Voice playback could not resume.'));
    }
    async function play(value){
      if(value.sample_rate!==24000||typeof value.pcm!=='string'||value.pcm.length>350000||!Number.isSafeInteger(value.end))throw Error('Invalid native audio');
      const raw=atob(value.pcm);if(!raw.length||raw.length%2)throw Error('Invalid native PCM');
      const begin=received.get(value.id)||0;if(value.end!==begin+raw.length||value.end>300*48000)throw Error('Native audio continuity changed');
      received.set(value.id,value.end);latestOutput=value.id;onTiming(value.id,'output_handled');
      if(!audible||floor||blocked||retired.has(value.id))return;
      if(energyFence)onTiming(value.id,'output_energy_held');
      if(nativeOutput){
        const bytes=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);
        if(await nativeOutput.append(value.id,value.end,bytes)){if(!played.has(value.id))played.set(value.id,0);onTiming(value.id,'output_scheduled');}return;
      }
      if(nodes.size>=512||Math.max(next,context.currentTime)-context.currentTime+raw.length/48000>30)throw Error('Native playback exceeded its queue bound');
      const samples=new Float32Array(raw.length/2);
      for(let i=0;i<samples.length;i++){const n=raw.charCodeAt(2*i)|(raw.charCodeAt(2*i+1)<<8);samples[i]=(n>=32768?n-65536:n)/32768;}
      const buffer=context.createBuffer(1,samples.length,24000);buffer.copyToChannel(samples,0);
      const source=context.createBufferSource();source.buffer=buffer;source.connect(context.destination);
      const at=Math.max(context.currentTime+.01,next),node={source,at,id:value.id,begin,end:value.end,cancelled:false};
      next=at+buffer.duration;nodes.add(node);
      source.onended=()=>{nodes.delete(node);source.disconnect();if(!node.cancelled){report(node.id,node.end);onTiming(node.id,'output_buffer_ended');}if(!nodes.size)onState({active,starting,floor,pending:false,playback:'idle'});};
      source.start(at);onTiming(value.id,'output_scheduled');onState({active,starting,floor,pending:false,playback:context.state==='suspended'?'paused':'playing'});
    }
    function slice(start,end){
      if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start<0||end<=start||end>bytes||end-start>120*32000)throw Error('Original PCM range unavailable');
      const values=[];let cursor=start;
      for(const part of parts){if(part.end<=cursor)continue;if(part.start>cursor)throw Error('Original PCM gap');const stop=Math.min(end,part.end);values.push(part.pcm.slice(cursor-part.start,stop-part.start));cursor=stop;if(cursor===end)break;}
      if(cursor!==end)throw Error('Original PCM missing');return values;
    }
    function keep(span){
      if(originals.has(span.id))return originals.get(span.id);
      if(originals.size>=2)throw Error('Two originals await confirmation');
      const value={id:span.id,binding,foreground_dialogue:dialogue,capture_started:Date.now(),captureQuestions:span.questions,
        blob:window.StreamingVoice.wav(slice(span.start,span.end)),mime:'audio/wav',submissionRequested:false};
      const promise=writing.then(()=>retain(value)).then(frozen=>{originals.set(span.id,frozen);return frozen;});
      // Reserve capacity before an asynchronous IndexedDB write completes.
      originals.set(span.id,value);writing=promise.then(()=>{},()=>{});return promise;
    }
    function hold(message='Voice ended. Your unconfirmed originals are kept for review.'){
      if(stopped)return;stopped=true;active=starting=floor=false;clearTimeout(timer);silence();
      if(current&&bytes>current.start){const span={...current,end:bytes};current=undefined;try{void Promise.resolve(keep(span)).catch(()=>onReview([...originals.values()]));}catch{}}
      unsubscribe?.();unsubscribe=undefined;capture?.close();capture=undefined;
      for(const track of media?.getTracks()||[])track.stop();media=undefined;
      try{control({type:'close'});socket?.close();}catch{}socket=undefined;
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
        case 'audio':await play(value);break;
        case 'capture_started':
          if(current||typeof value.id!=='string')throw Error('Original capture changed');
          onTiming(value.id,'capture_started');current={id:value.id,start:value.start,questions:pendingScope||questions};pendingScope=undefined;floor=true;blocked=true;silence(true);onInterrupt();state('Listening');
          onHandoff({id:value.id,gate:'speaking'});break;
        case 'phrase_end':{
          if(!current||current.id!==value.id||current.start!==value.start)throw Error('Phrase boundary changed');
          onTiming(value.id,'phrase_end');const span={...current,end:value.end};current=undefined;floor=false;lastEnded=value.id;
          await keep(span);onTiming(value.id,'local_retained');onHandoff({id:value.id,gate:'waiting_transcript'});state('Phrase end detected');break;
        }
        case 'original_retained':{
          const original=originals.get(value.id);if(!original||original.audio_sha256!==value.sha256)throw Error('Retained original differs');
          onHandoff({id:value.id,gate:'foreground_saved'});break;
        }
        case 'original_completed':{
          const original=originals.get(value.id);if(!original||original.audio_sha256!==value.sha256||value.phase!=='foreground')throw Error('Completed original differs');
          onTiming(value.id,'original_confirmed');await release(original,value.sha256);originals.delete(value.id);break;
        }
        case 'input_caption':case 'input_transcript':onCaption(value.text);break;
        case 'assistant_utterance':if(value.utterance.text)onTiming(value.utterance.id,'output_text');onUtterance(value.utterance);onCaption(value.utterance.text);break;
        case 'interrupted':silence(true);break;
        case 'voice_activity':if(value.activity==='ACTIVITY_END'&&value.id===lastEnded)blocked=false;break;
        case 'turn_activity':
          // Local energy pauses immediately, but it is not speech authority.
          // Resume only after quiet analysis has covered that exact PCM fence;
          // confirmed speech already retires the old output at capture_started.
          if(energyFence&&value.activity.speaking===false&&Number.isSafeInteger(value.activity.audio_bytes)&&value.activity.audio_bytes>=energyFence){
            energyFence=0;resumeOutput();
          }
          if(current)onHandoff({id:current.id,gate:value.activity.speaking?'speaking':'waiting_endpoint'});break;
        case 'input_interpreted':onTiming(value.id,'input_interpreted');onCaption(value.text);break;
        case 'review':case 'closing':hold(value.message||'Voice session ended.');break;
      }
    }
    async function start(){
      if(active||starting||originals.size||document.hidden||!getBinding()||!supported())return false;
      const owned=++epoch;binding=getBinding();dialogue=crypto.randomUUID();questions=getQuestions?.();if(questions!==undefined)questions=JSON.parse(JSON.stringify(questions));stopped=false;audible=true;blocked=false;energyFence=lastEnergy=0;energyArmed=true;userPaused=false;questionScope=undefined;lastEnded=pendingScope=lastRemaining=latestOutput=undefined;starting=true;parts=[];bytes=0;current=undefined;received=new Map();played=new Map();retired=new Set();state('Preparing native voice');
      // Unlock output in the explicit gesture; microphone waits for owner preflight.
      timer=setTimeout(()=>hold('Voice session reached five minutes.'),300000);
      try{
        if(nativePcm()){
          nativeOutput=window.NativeSpeechAudio.openPcm({onProgress:report,onBufferEnded:id=>onTiming(id,'output_buffer_ended'),
            onState:playback=>{if(!stopped)onState({active,starting,floor,pending:false,playback});},onUnavailable:hold});
          await nativeOutput.ready;if(stopped||owned!==epoch)return false;
        }else{context=new (window.AudioContext||window.webkitAudioContext)();void context.resume().catch(()=>{});}
        const target=new URL('api/interaction/voice/native',window.location.href);target.protocol=target.protocol==='https:'?'wss:':'ws:';
        const opened=new Promise((resolve,reject)=>{
          socket=new WebSocket(target);
          socket.onopen=()=>{if(owned!==epoch||stopped)return;try{const h=headers(),authorization=h.Authorization||h.authorization;socket.send(JSON.stringify({id:dialogue,binding,csrf:h['X-Dashboard-CSRF']||h['x-dashboard-csrf'],capture_questions:questions,...(authorization?{authorization}:{})}));}catch(error){reject(error);}};
          socket.onmessage=message=>{
            if(owned!==epoch||stopped)return;
            try{
              if(typeof message.data!=='string'||message.data.length>400000||pendingEvents>=128)throw Error('Native event backlog exceeded');
              const value=JSON.parse(message.data);
              if(value.type==='ready'){if(value.id!==dialogue||value.activity_mode!=='manual')throw Error('Native mode changed');resolve();return;}
              if(value.type==='review'&&starting){reject(Error(value.message));return;}
              pendingEvents++;chain=chain.then(()=>event(value,owned)).catch(error=>hold(error.message)).finally(()=>pendingEvents--);
            }catch(error){reject(error);hold(error.message);}
          };
          socket.onerror=socket.onclose=()=>{reject(Error('Native voice disconnected'));if(owned===epoch)hold();};
        });
        let readyTimer;
        try{await Promise.race([opened,new Promise((_,reject)=>{readyTimer=setTimeout(()=>reject(Error('Native voice readiness timed out')),45000);})]);}
        finally{clearTimeout(readyTimer);}
        if(stopped||owned!==epoch||binding!==getBinding())return false;
        const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
        if(stopped||owned!==epoch||document.hidden){for(const t of stream.getTracks())t.stop();return false;}media=stream;
        const openedCapture=await window.StreamingVoice.openCapture(media);
        if(stopped||owned!==epoch){openedCapture.close();return false;}capture=openedCapture;
        unsubscribe=capture.subscribe(value=>{
          if(stopped||owned!==epoch)return;
          if(binding!==getBinding()){hold('Conversation changed.');return;}
          if(value.captureError){hold('Microphone ended.');return;}
          if(!current&&!pendingScope&&Number.isSafeInteger(value.activityBytes)&&value.activityBytes>bytes){
            const snapshot=questionScope===undefined?getQuestions?.():questionScope;pendingScope=snapshot===undefined?{}:JSON.parse(JSON.stringify(snapshot));
            control({type:'capture_scope',audio_bytes:value.activityBytes,capture_questions:pendingScope});
          }
          if(Number.isSafeInteger(value.activityBytes)&&Number.isSafeInteger(value.totalBytes)&&value.totalBytes-value.activityBytes>=3200)energyArmed=true;
          if(Number.isSafeInteger(value.activityBytes)&&value.activityBytes>lastEnergy&&value.activityBytes>=bytes){
            lastEnergy=value.activityBytes;
            // Pause once per local energy episode. Continuous ambient energy
            // must not move the fence ahead of every server nonspeech verdict.
            // A 100ms local quiet gap rearms; confirmed server speech always
            // retires output, including speech beginning over continuous noise.
            if(energyArmed){energyArmed=false;energyFence=lastEnergy;pendingTiming('output_energy_held');pauseOutput();}
          }
          if(!value.pcm)return;
          if(!(value.pcm instanceof ArrayBuffer)||value.pcm.byteLength%2||bytes+value.pcm.byteLength>300*32000||socket?.readyState!==WebSocket.OPEN||socket.bufferedAmount>256000){hold('Voice connection could not keep up.');return;}
          if(current&&bytes+value.pcm.byteLength-current.start>120*32000){hold('Your phrase reached two minutes. The recording is kept for review.');return;}
          const pcm=value.pcm;parts.push({start:bytes,end:bytes+pcm.byteLength,pcm});bytes+=pcm.byteLength;try{socket.send(pcm);}catch{hold('Voice disconnected. Your recording is kept.');return;}
          const remaining=current?Math.max(0,Math.ceil(120-(bytes-current.start)/32000)):undefined;
          if(remaining!==lastRemaining){lastRemaining=remaining;state('Listening');}
        });
        capture.observe();capture.start();active=true;starting=false;state('Listening');return true;
      }catch(error){if(owned===epoch)hold(error.message||'Native voice unavailable.');return false;}
    }
    return {start,hold,setEnabled:value=>{const enabled=value===true;if(audible===enabled)return;audible=enabled;if(!audible)silence();else resumeOutput();},
      pause:()=>{userPaused=true;pauseOutput();onState({active,starting,floor,pending:false,playback:'paused'});},
      resume:()=>{userPaused=false;resumeOutput();},
      get hasAudio(){return !!nativeOutput?.hasAudio||nodes.size>0;},get paused(){return nativeOutput?.paused||context?.state==='suspended';},
      release:id=>originals.delete(id),get active(){return active||starting;},get floor(){return floor;},get originals(){return [...originals.values()];}};
  }
  return {supported,create};
})();
