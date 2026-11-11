"use strict";
// A foreground, bounded view. No persisted microphone opt-in or second sender.
window.ConversationVoiceMode=(()=>{
  // Cosmetic RMS envelopes reuse existing capture buffers. No audio is copied,
  // retained, played or opened here; at most ten measurements per second.
  function meter(notify,clock=()=>Date.now()){
    let previous=-Infinity;
    return pcm=>{
      try{
        if(!(pcm instanceof ArrayBuffer)||!pcm.byteLength||pcm.byteLength>32000||pcm.byteLength%2)return;
        const at=clock();if(at-previous<100)return;previous=at;
        const samples=new Int16Array(pcm);let sum=0;
        for(const x of samples)sum+=(x/32768)**2;
        notify(Math.min(1,Math.sqrt(sum/samples.length)*6));
      }catch{/* Presentation cannot interrupt the capture owner. */}
    };
  }
  function signalSurface(dialog){
    if(!document.createElementNS)return;
    const make=tag=>document.createElementNS('http://www.w3.org/2000/svg',tag);
    const svg=make('svg');svg.classList.add('voice-signal');svg.setAttribute('viewBox','0 0 320 100');svg.setAttribute('preserveAspectRatio','none');svg.setAttribute('aria-hidden','true');
    const tracks=['input','output'].map(kind=>{const path=make('path');path.dataset.signal=kind;svg.append(path);return {kind,path,values:Array(40).fill(0)};});
    dialog.append(svg);let levels={input:0,output:0};
    function clear(){levels={input:0,output:0};for(const t of tracks){t.values.fill(0);t.path.removeAttribute('d');}svg.dataset.active='false';}
    function update(value){
      if(document.hidden){clear();return;}
      for(const t of tracks){
        const field=t.kind+'Level';if(!Object.hasOwn(value,field))continue;
        const level=Number.isFinite(value[field])?Math.min(1,Math.max(0,value[field])):0;levels[t.kind]=level;
        if(!level){t.values.fill(0);t.path.removeAttribute('d');continue;}
        t.values.shift();t.values.push(level);
        const points=t.values.map((v,i)=>[i*320/39,50-v*28]);
        const other=t.values.map((v,i)=>[i*320/39,50+v*28]).reverse();
        // Smooth the measured envelope without inventing an oscillating carrier.
        let previous=points[0],d='M'+previous.map(v=>v.toFixed(1)).join(' ');
        for(const point of points.slice(1).concat(other)){
          const mid=(previous[0]+point[0])/2;
          d+=' C'+[mid,previous[1],mid,point[1],...point].map(v=>v.toFixed(1)).join(' ');previous=point;
        }
        t.path.setAttribute('d',d+' Z');
      }
      svg.dataset.active=String(levels.input>0||levels.output>0);
    }
    return {clear,update};
  }
  function mount({portrait,onEnter,onLeave,onSuspend,onSpeak,onReconnect,onResumeAudio,onReview,getAttention=()=>0,canStart,canReconnect=()=>true,canEnter=canStart}){
    if(!portrait || typeof document.createElement('dialog').showModal!=='function')return;
    const dialog=document.createElement('dialog');dialog.className='voice-mode';
    dialog.setAttribute('aria-label','Direct voice conversation');
    let signal;try{signal=signalSurface(dialog);}catch{/* Cosmetic surface unavailable. */}
    const clearSignal=()=>{try{signal?.clear();}catch{}};
    const showSignal=value=>{try{signal?.update(value);}catch{}};
    const heading=document.createElement('h2');heading.textContent='Conversation';
    const hint=document.createElement('p');hint.textContent='Only you and your daimon';
    const stage=document.createElement('div');stage.className='voice-mode-portrait';
    const status=document.createElement('p');status.className='voice-mode-state';status.setAttribute('role','status');
    const detection=document.createElement('p');detection.className='voice-mode-detection';detection.setAttribute('role','status');detection.hidden=true;
    const caption=document.createElement('p');caption.className='voice-mode-caption';
    const speak=document.createElement('button');speak.type='button';speak.textContent='Speak again';
    const back=document.createElement('button');back.type='button';back.textContent='Back to conversation';
    const review=document.createElement('button');review.type='button';review.hidden=true;
    const controls=document.createElement('div');controls.className='voice-mode-controls';controls.append(review,speak,back);
    dialog.append(heading,hint,stage,status,detection,caption,controls);document.body.append(dialog);
    let available=false,opened=false,marker,timer,rearm,lastClose,waiting=false,heard=false,phase='idle',pending=false,playing=false,remaining,normal,continuous=false,listening=false,preparing=false,directPending=false,directWorking=false,directMessage,detectorId,detectionText,recentEnd;
    const detectionLabels={waiting_speech:'Waiting for speech',speaking:'Voice detected',waiting_endpoint:'Voice detected',waiting_analysis:'Processing your recording',waiting_transcript:'Processing your recording',finishing:'Saving your recording',confirming:'Sending your recording',confirmed:'Recording sent',foreground_saved:'Recording saved',review:'Check your recording in the conversation'};
    let audioPaused=false,audioEnabled=true,reconnecting=false,untilStop=false;
    const reconnectNotice='Your recording is kept; anything said during the pause may need review.';
    const canResumeAudio=()=>continuous&&listening&&!preparing&&!directPending&&typeof onResumeAudio==='function'&&(audioPaused||!audioEnabled);
    function showDetection(value){
      if(!value||typeof value.id!=='string'||value.id.length>128||!Object.hasOwn(detectionLabels,value.gate))return;
      const {id,gate}=value;
      if(gate==='speaking'){detectorId=id;recentEnd=undefined;}
      if(!detectorId||['waiting_speech','speaking','waiting_endpoint','waiting_analysis','waiting_transcript','finishing'].includes(gate))detectorId=id;
      if(gate==='waiting_transcript'||gate==='finishing')recentEnd={id,label:'Phrase ended'};
      if(recentEnd?.id===id&&gate==='confirmed')recentEnd.label='Recording sent';
      if(recentEnd?.id===id&&gate==='foreground_saved')recentEnd.label='Recording saved';
      if(id===detectorId||gate==='review'){
        detectionText=gate==='review'&&value.review_after==='waiting_speech'?'Speech was not detected. Check your recording in the conversation.':detectionLabels[gate];
        // Capture/analysis timings remain in the existing technical inspector.
        // Ordinary voice feedback describes progress or the user's next action.
        detection.dataset.warning=String(gate==='review');
      }
      const text=(detectionText||'')+(recentEnd&&recentEnd.id!==detectorId?' · Previous recording: '+recentEnd.label.toLowerCase():'');
      if(detection.textContent!==text)detection.textContent=text;
      detection.hidden=!continuous||!text;
    }
    function attention(count){
      const pending=Number.isSafeInteger(count)&&count>0?count:0;
      review.hidden=!pending||typeof onReview!=='function';review.textContent=`For you · ${pending}`;
      review.setAttribute('aria-label',`For you · ${pending} pending requests`);
      if(review.hidden&&opened&&document.activeElement===review)back.focus();
    }
    function entryState(){
      portrait.dataset.voiceEntry=String(available);
      if(!available){
        if(normal)for(const [name,value] of normal){if(value===null)portrait.removeAttribute(name);else portrait.setAttribute(name,value);}
        return;
      }
      portrait.setAttribute('role',available&&!opened?'button':'img');portrait.tabIndex=available&&!opened?0:-1;
      portrait.setAttribute('aria-hidden',available?'false':'true');
      portrait.setAttribute('aria-label',opened?'Conversation avatar':'Open direct voice conversation');
      portrait.title=available&&!opened?'Direct voice conversation':'';
    }
    // Each physical engine keeps its own capture budget. An explicitly admitted
    // renewing native dialogue owns the logical lifetime until human Stop.
    function armClose(){clearTimeout(timer);timer=undefined;if(continuous&&untilStop)return;timer=setTimeout(close,(continuous?10:5)*60*1000);}
    function close(){
      if(!opened)return lastClose;clearSignal();opened=false;clearTimeout(timer);clearTimeout(rearm);
      marker.replaceWith(portrait);marker=undefined;dialog.close();document.body.classList.remove('direct-voice-open');
      entryState();lastClose=onLeave();portrait.focus();return lastClose;
    }
    function open(){
      if(opened || !available || document.hidden || !canEnter())return;
      if(onEnter()===false)return;
      opened=true;untilStop=false;audioPaused=false;audioEnabled=true;reconnecting=false;detectorId=detectionText=recentEnd=undefined;detection.textContent='';detection.hidden=true;waiting=false;heard=false;pending=false;directPending=false;directWorking=false;directMessage=undefined;listening=false;preparing=false;phase='idle';playing=false;remaining=undefined;
      entryState();
      marker=document.createComment('portrait return');portrait.before(marker);stage.append(portrait);
      document.body.classList.add('direct-voice-open');dialog.showModal();back.focus();attention(getAttention());
      armClose();status.textContent='Opening microphone…';caption.textContent='';speak.hidden=true;onSpeak();
    }
    function maybeRearm(){
      clearTimeout(rearm);
      if(continuous || !opened || !heard || playing || pending || phase!=='idle')return;
      rearm=setTimeout(()=>{if(opened && heard && !playing && phase==='idle' && !pending && canStart()){
        heard=false;waiting=false;speak.hidden=true;onSpeak();
      }},900);
    }
    function update(value){
      if(!opened)return;
      if(value.connected===false){close();return;}
      showSignal(value.continuousState||value);
      if(continuous&&value.handoff)showDetection(value.handoff);
      const wasStopped=!listening&&!preparing&&!!directMessage,wasReconnecting=reconnecting;
      if(value.continuousState?.starting){detectorId=detectionText=recentEnd=undefined;detection.textContent='';detection.hidden=true;}
      if(value.continuousState){
        const state=value.continuousState;
        if(typeof state.untilStop==='boolean'&&state.untilStop!==untilStop){untilStop=state.untilStop;armClose();}
        if(Object.hasOwn(state,'message'))directMessage=state.message;
        if(typeof state.active==='boolean')listening=state.active;
        if(typeof state.starting==='boolean')preparing=state.starting;
        if(typeof state.reconnecting==='boolean')reconnecting=state.reconnecting;
        if(typeof state.pending==='boolean')directPending=state.pending;
        if(typeof state.working==='boolean')directWorking=state.working;
        if(Object.hasOwn(state,'remaining'))remaining=Number.isInteger(state.remaining)&&state.remaining>=0&&state.remaining<=120?state.remaining:undefined;
      }
      if(typeof value.continuousState?.audioPaused==='boolean')audioPaused=value.continuousState.audioPaused;
      if(typeof value.continuousState?.audioEnabled==='boolean')audioEnabled=value.continuousState.audioEnabled;
      if(Object.hasOwn(value,'capture'))phase=value.capture||'idle';
      if(Object.hasOwn(value,'pending'))pending=value.pending;
      if(Number.isInteger(value.remaining)&&value.remaining>=0&&value.remaining<=120)remaining=value.remaining;
      if(Object.hasOwn(value,'playback')){playing=value.playback==='playing'||value.playback==='preparing';if(playing)heard=true;}
      if(value.sent){waiting=true;heard=false;}
      if(continuous){
        const left=remaining===undefined?'':` · ${Math.floor(remaining/60)}:${String(remaining%60).padStart(2,'0')}`;
        status.textContent=reconnecting?'Reconnecting voice':preparing?'Preparing voice':directPending?'Recording needs review':directWorking?'Saving your voice':listening&&!audioEnabled?'Audio off · listening'+left:listening&&audioPaused?'Audio paused · listening'+left:playing&&listening?'Speaking · listening'+left:playing?'Reply playback · microphone off':listening?'Listening'+left:'Voice paused';
        status.dataset.nearLimit=String(listening&&remaining!==undefined&&remaining<=15);
        status.setAttribute('aria-label',status.textContent+(listening&&remaining!==undefined?`. ${remaining} seconds of recording remaining`:''));
        if(Object.hasOwn(value,'caption'))caption.textContent=value.caption;
        if(wasReconnecting&&!reconnecting&&caption.textContent===reconnectNotice)caption.textContent='';
        if(reconnecting&&!Object.hasOwn(value,'caption'))caption.textContent=reconnectNotice;
        else if(directPending)caption.textContent=(directMessage?directMessage+' ':'')+(typeof onReconnect==='function'&&canReconnect()?'Reconnect to keep talking; your recordings stay available for review.':'Return to the conversation to review your recordings.');
        else if(!listening&&!preparing&&directMessage)caption.textContent=directMessage;
        else if(value.continuousState&&wasStopped&&!Object.hasOwn(value,'caption'))caption.textContent='';
        const resume=!reconnecting&&canResumeAudio(),reconnect=!reconnecting&&!listening&&!preparing&&typeof onReconnect==='function'&&canReconnect();
        speak.hidden=reconnect?false:!resume&&(preparing||listening||directPending);speak.disabled=directWorking||preparing||!resume&&!reconnect&&!canStart();speak.title='';speak.textContent=reconnect?'Reconnect voice':resume?(audioEnabled?'Resume audio':'Enable audio'):'Start voice';
        dialog.dataset.phase=phase==='recording'?'listening':playing?'speaking':'waiting';return;
      }
      status.dataset.nearLimit='false';status.removeAttribute('aria-label');
      const recording=phase==='recording',working=phase==='permission'||phase==='finalizing'||value.uploading;
      status.textContent=recording?`Listening${remaining===undefined?'':` · ${Math.floor(remaining/60)}:${String(remaining%60).padStart(2,'0')} left`}`:working?'Saving your voice':playing?'Speaking':pending||phase==='ready'?'Recording needs review':waiting?'Waiting for your reply':'Ready';
      caption.textContent=recording?(value.message||''):pending||phase==='ready'?'Return to the conversation to review your recording.':!waiting&&!playing?(value.message||''):'';
      speak.hidden=recording||working||pending||phase==='ready'||playing;
      dialog.dataset.phase=recording?'listening':playing?'speaking':'waiting';
      maybeRearm();
    }
    portrait.addEventListener('click',open);
    portrait.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();open();}});
    review.addEventListener('click',()=>{if(opened&&typeof onReview==='function')onReview(()=>{if(!opened)return false;(review.hidden?back:review).focus();return true;});});
    back.addEventListener('click',close);dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
    speak.addEventListener('click',()=>{if(!opened)return;if(canResumeAudio()){onResumeAudio();return;}if(continuous&&!listening&&!preparing&&typeof onReconnect==='function'&&canReconnect()){armClose();onReconnect();return;}if(canStart()){waiting=false;heard=false;speak.hidden=true;onSpeak();}});
    function suspend(){
      if(!opened)return;clearSignal();
      if(continuous && onSuspend)onSuspend();
      else close();
    }
    document.addEventListener('visibilitychange',()=>{if(document.hidden)suspend();});
    // Android sends this before (or without) WebView visibilitychange. Ordinary
    // background reply playback stays owned by its separate speech session.
    window.addEventListener('nativecapturebackground',suspend);
    window.addEventListener('pagehide',close);
    return {update,attention,close,get active(){return opened;},configure(enabled,direct=false){
      if(opened&&continuous!==(direct===true))close();
      continuous=direct===true;
      if(enabled!==true&&!available)return;
      if(enabled===true&&!available)normal=['role','tabindex','aria-hidden','aria-label','title'].map(name=>[name,portrait.getAttribute(name)]);
      available=enabled===true;entryState();
      if(!available)close();
    }};
  }
  return {mount,meter};
})();
