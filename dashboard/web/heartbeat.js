/* Foreground owner-console status and explicit conditional controls; no setup. */
(() => {
  function evidenceExpiry(value,now) {
    const e=value?.operational_evidence,lane=value?.lanes?.messaging;
    if(value?.operational!==true || e?.schema!=='telecodex.heartbeat-operational/v1' || e.operational!==true || e.generation!==value.generation || lane?.paused!==false || e.lanes?.messaging?.operational!==true || e.lanes.messaging.generation!==lane.generation)return 0;
    if(!Number.isSafeInteger(e.observed_at_unix_ms) || e.observed_at_unix_ms<=0 || e.observed_at_unix_ms>now || !Number.isInteger(e.valid_for_seconds) || e.valid_for_seconds<1 || e.valid_for_seconds>15)return 0;
    const ends=[e.observed_at_unix_ms+e.valid_for_seconds*1000];
    for(const kind of ['producer','resources'])if(value[kind]?.mode!=='continuous')ends.push(value[kind]?.contract?.expires_at_unix_ms);
    if(ends.some(x=>!Number.isSafeInteger(x) || x<=now))return 0;
    return Math.min(...ends);
  }
  function state(value,now=Date.now()) {
    if(value?.schema!=='telecodex.heartbeat-control/v1' || typeof value.admission_paused!=='boolean' || !Number.isSafeInteger(value.generation) || value.generation<0)return 'unavailable';
    if(value.error || value.attention_engine==='error' || value.producer?.state==='error' || value.resources?.state==='error')return 'error';
    if(value.admission_paused)return 'paused';
    if(['not_configured','not_implemented'].includes(value.attention_engine) || value.producer?.state==='not_configured' || value.resources?.state==='not_configured')return 'unconfigured';
    if(value.producer?.state==='expired')return 'observation_expired';
    if(['stopped','check_capacity','cursor_capacity','receipt_capacity','binding_retired','purpose_retired'].includes(value.producer?.state))return 'observation_stopped';
    if(value.resources?.state==='expired')return 'inference_expired';
    if(value.resources?.state==='exhausted')return 'inference_exhausted';
    if(value.resources?.state==='rate_limited')return 'inference_rate_limited';
    // An open admission gate or running execution is not operational proof.
    if((value.producer?.state && value.producer.state!=='configured') || (value.resources?.state && value.resources.state!=='available'))return 'unavailable';
    return evidenceExpiry(value,now)>now?'operational':'unavailable';
  }
  function observation(value) {
    function time(ms){if(!Number.isSafeInteger(ms) || ms<=0 || ms>8640000000000000)return null;return new Date(ms).toISOString();}
    const producer=value?.producer,check=producer?.last_check;
    if(!check || !['in_progress','succeeded','failed'].includes(check.outcome))return '';
    const completed=time(check.completed_at_unix_ms),started=time(check.started_at_unix_ms);
    if(check.outcome==='in_progress')return started?'Source check started '+started+'; completion not observed.':'';
    if(!completed)return '';
    const different=check.generation!==value.generation || typeof check.activation?.lane!=='string' || !Number.isSafeInteger(check.activation?.generation) || check.activation.generation!==value.lanes?.[check.activation.lane]?.generation;
    let text='Last source check '+check.outcome+' at '+completed+(different?' (different or unconfirmed control generation).':'.');
    const success=time(producer.last_success_at_unix_ms);
    if(check.outcome==='failed')text+=' Last successful source check: '+(success || 'not observed')+'.';
    return text;
  }
  // Product copy is separate from the operational proof used by the pulse.
  function presentation(value,now=Date.now()) {
    const selected=state(value,now);
    const labels={paused:'Paused',unconfigured:'Not set up',unavailable:'Status unavailable',error:'Needs attention',operational:'Ready',observation_expired:'Checks stopped',observation_stopped:'Checks stopped',inference_expired:'Work paused',inference_exhausted:'Usage limit reached',inference_rate_limited:'Waiting for the hourly limit to reset'};
    const details={paused:'Automatic work is paused.',unconfigured:'Heartbeat setup is incomplete.',unavailable:'Refresh to check heartbeat.',error:'Heartbeat could not run. Refresh to check again.',operational:'Heartbeat is ready for automatic work.',observation_expired:'Automatic checks have ended.',observation_stopped:'Automatic checks have stopped.',inference_expired:'The time allowed for automatic work has ended.',inference_exhausted:'The allowance for automatic work has been used.',inference_rate_limited:'Automatic checks continue. New work will wait.'};
    const result={label:labels[selected],detail:details[selected]};
    const e=value?.operational_evidence;
    const fresh=e?.schema==='telecodex.heartbeat-operational/v1' && e.generation===value.generation && Number.isSafeInteger(e.observed_at_unix_ms) && e.observed_at_unix_ms<=now && e.valid_for_seconds>=1 && e.valid_for_seconds<=15 && now<e.observed_at_unix_ms+e.valid_for_seconds*1000;
    if(selected==='unavailable' && fresh){
      if(e.reason==='attention_pending')return {label:'Waiting',detail:'Earlier heartbeat work is still pending.'};
      if(e.reason==='native_busy')return {label:'Waiting',detail:'Automatic work waits while our conversation is busy.'};
      if(['source_check_stale','source_check_unavailable','controls_changed','native_binding_changed'].includes(e.reason))return {label:'Checking',detail:'Checking whether heartbeat is ready.'};
      if(['loop_unavailable','native_support_unavailable','native_admission_unavailable','native_observation_unavailable'].includes(e.reason))return {label:'Needs attention',detail:'Heartbeat is enabled but cannot start automatic work.'};
    }
    return result;
  }
  function action(value,id) {
    const caps=value?.controls,global=Number.isSafeInteger(value?.generation)&&value.generation>=0;
    if(!global || typeof value.admission_paused!=='boolean' || value.schema!=='telecodex.heartbeat-control/v1' || caps?.schema!=='telecodex.heartbeat-controls/v1' || !Array.isArray(caps.actions))return null;
    if(id==='global' && caps.conditional_global===true && caps.actions?.includes('set_paused'))return {action:'set_paused',paused:!value.admission_paused,generation:value.generation};
    const lane=value.lanes?.messaging;
    if(id==='messaging' && caps.conditional_lane===true && caps.actions?.includes('set_lane_paused') && lane?.supported===true && typeof lane.paused==='boolean' && Number.isSafeInteger(lane.generation) && lane.generation>=0)return {action:'set_lane_paused',lane:'messaging',paused:!lane.paused,generation:lane.generation,global_generation:value.generation};
    return null;
  }
  function mount({api,authenticated,canControl=()=>true,root=document,clock=()=>Date.now()}) {
    const button=root.querySelector('#heartbeat-toggle'),menu=root.querySelector('#heartbeat-menu');
    if(!button || !menu)return;
    const status=root.querySelector('#heartbeat-status'),generation=root.querySelector('#heartbeat-generation'),lanes=root.querySelector('#heartbeat-lanes');
    let last=-Infinity,pending=false,hold,held=false,epoch=0,expiry,writing=false,current=null,notice="";
    function render(value){
      current=value;clearTimeout(expiry);
      const selected=state(value,clock()),copy=presentation(value,clock());button.dataset.state=selected;button.setAttribute('aria-label','Heartbeat · '+copy.label);button.title='Heartbeat · '+copy.label;
      if(selected==='operational')expiry=setTimeout(()=>render(null),Math.max(0,evidenceExpiry(value,clock())-clock()));
      status.textContent='Heartbeat · '+copy.label;
      generation.textContent=notice || copy.detail;
      lanes.replaceChildren();
      for(const [id,name] of [['global','Heartbeat'],['messaging','Messages'],['reports','Scheduled reviews']]){
        if(id!=='global' && value?.lanes?.[id]?.supported!==true)continue;
        if(id==='global' && value?.schema!=='telecodex.heartbeat-control/v1')continue;
        const row=root.createElement('div'),label=root.createElement('span');
        const command=canControl()?action(value,id):null;
        const paused=id==='global'?value.admission_paused:value.lanes[id].paused;
        label.textContent=name;row.append(label);
        if(command){
          const control=root.createElement('button');control.type='button';control.disabled=writing;
          control.textContent=command.paused?'Pause':'Enable';control.setAttribute('aria-label',control.textContent+' '+name.toLowerCase());
          control.addEventListener('click',()=>write(command));row.append(control);
        }else{
          const status=root.createElement('span');status.textContent=paused?'Paused':'Enabled';row.append(status);
        }
        lanes.append(row);
      }
      position();
    }
    function position(){
      if(menu.hidden)return;
      const viewport=window.visualViewport,x=viewport?.offsetLeft || 0,y=viewport?.offsetTop || 0;
      const width=viewport?.width || window.innerWidth,height=viewport?.height || window.innerHeight;
      const anchor=button.getBoundingClientRect(),gap=8,edge=8;
      menu.style.maxWidth=Math.max(0,width-edge*2)+'px';menu.style.maxHeight=Math.max(0,height-edge*2)+'px';
      const box=menu.getBoundingClientRect();
      const left=Math.max(x+edge,Math.min(anchor.left,x+width-edge-box.width));
      const below=anchor.bottom+gap;
      const top=below+box.height<=y+height-edge?below:Math.max(y+edge,anchor.top-gap-box.height);
      menu.style.left=left+'px';menu.style.top=top+'px';
    }

    async function write(command){
      if(writing || !authenticated() || !canControl())return;
      writing=true;notice='';const selected=++epoch;render(current);
      try{await api('interaction/heartbeat',command);if(selected===epoch)notice='Updated.';}
      catch{if(selected===epoch)notice='Could not confirm the change. Refresh before trying again.';}
      finally{writing=false;if(selected===epoch){render(null);await refresh(true);if(!menu.hidden)root.querySelector('#heartbeat-refresh').focus();}}
    }
    function open(){menu.hidden=false;button.setAttribute('aria-expanded','true');position();void refresh(true);root.querySelector('#heartbeat-refresh').focus();}
    function close(){menu.hidden=true;button.setAttribute('aria-expanded','false');button.focus();}
    async function refresh(force=false){
      if(!authenticated() || document.hidden){epoch++;render(null);return;}
      if(writing || pending || !force && clock()-last<10000)return;
      pending=true;last=clock();const selected=epoch;
      try{const value=await api('interaction/heartbeat');if(selected===epoch && authenticated() && !document.hidden)render(value);}
      catch{if(selected===epoch)render(null);}
      finally{pending=false;}
    }
    button.addEventListener('click',event=>{if(held){held=false;event.preventDefault();return;}menu.hidden?open():close();});
    button.addEventListener('contextmenu',event=>{event.preventDefault();clearTimeout(hold);open();});
    button.addEventListener('pointerdown',event=>{if(event.pointerType==='touch'){held=false;hold=setTimeout(()=>{held=true;open();},500);}});
    for(const type of ['pointerup','pointercancel','pointermove'])button.addEventListener(type,()=>clearTimeout(hold));
    button.addEventListener('keydown',event=>{if(event.key==='ContextMenu' || event.key==='F10' && event.shiftKey){event.preventDefault();open();}});
    menu.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();close();}});
    root.querySelector('#heartbeat-refresh').addEventListener('click',()=>refresh(true));root.querySelector('#heartbeat-close').addEventListener('click',close);
    document.addEventListener('visibilitychange',()=>{if(document.hidden){epoch++;render(null);}});
    function reset(){epoch++;notice="";render(null);menu.hidden=true;button.setAttribute('aria-expanded','false');}
    window.addEventListener('resize',position);window.addEventListener('scroll',position,true);
    window.visualViewport?.addEventListener('resize',position);window.visualViewport?.addEventListener('scroll',position);
    render(null);return {refresh,reset};
  }
  window.InteractionHeartbeat={mount,state,action,observation,presentation};
})();
