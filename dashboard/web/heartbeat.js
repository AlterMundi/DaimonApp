/* Foreground owner-console status and explicit conditional controls; no setup. */
(() => {
  function state(value) {
    if(value?.schema!=='telecodex.heartbeat-control/v1' || typeof value.admission_paused!=='boolean' || !Number.isSafeInteger(value.generation) || value.generation<0)return 'unavailable';
    if(value.error || value.attention_engine==='error' || value.producer?.state==='error' || value.resources?.state==='error')return 'error';
    if(value.admission_paused)return 'paused';
    if(['not_configured','not_implemented'].includes(value.attention_engine) || value.producer?.state==='not_configured' || value.resources?.state==='not_configured')return 'unconfigured';
    // An open admission gate or running execution is not operational proof.
    if(value.producer?.state==='unavailable' || value.resources?.state==='unavailable')return 'unavailable';
    return value.operational===true?'operational':'unavailable';
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
    const labels={paused:'Paused',unconfigured:'Not configured',unavailable:'Status unavailable',error:'Error',operational:'Operational'};
    let last=-Infinity,pending=false,hold,held=false,epoch=0,expiry,writing=false,current=null,notice="";
    function render(value){
      current=value;clearTimeout(expiry);
      const selected=state(value);button.dataset.state=selected;button.setAttribute('aria-label','Heartbeat · '+labels[selected]);button.title='Heartbeat · '+labels[selected];
      if(selected==='operational')expiry=setTimeout(()=>render(null),15000);
      status.textContent='Heartbeat · '+labels[selected];
      generation.textContent=(Number.isSafeInteger(value?.generation)?'Generation '+value.generation:'')+(notice?' · '+notice:'');
      lanes.replaceChildren();
      for(const [id,name] of [['global','All heartbeat lanes'],['messaging','Messaging'],['issues','Issues'],['sensory','Sensory'],['tasks','Tasks'],['bitacora','Bitácora']]){
        const row=root.createElement('div'),control=root.createElement('button'),reason=root.createElement('span');
        const command=canControl()?action(value,id):null;
        control.type='button';control.disabled=writing || !command;control.textContent=command?(command.paused?'Pause ':'Enable ')+name:name;
        if(command)control.addEventListener('click',()=>write(command));
        reason.textContent=id==='global'?'Shared generation-aware app controls are not available.':id==='messaging'?'Messaging lane control is not available in the selected backend.':'Not supported yet; no resources activated.';
        if(command)reason.textContent=id==='global'?(value.admission_paused?'Globally paused. Enabling preserves each lane selection.':'Admission enabled; operational readiness is separate.'):(value.admission_paused?'Global pause still applies.':'Lane selection does not configure resources or prove operation.');
        if(!canControl())reason.textContent='This monitor is read-only.';
        const reasonId='heartbeat-'+id+'-reason';reason.id=reasonId;control.setAttribute('aria-describedby',reasonId);row.append(control,reason);lanes.append(row);
      }
      if(selected==='paused' && (value?.producer?.state==='not_configured' || value?.resources?.state==='not_configured'))status.textContent+=' · producer/resources not configured';
    }
    async function write(command){
      if(writing || !authenticated() || !canControl())return;
      writing=true;notice='';const selected=++epoch;render(current);
      try{await api('interaction/heartbeat',command);if(selected===epoch)notice='Action acknowledged. Status refreshed.';}
      catch{if(selected===epoch)notice='Action refused or unconfirmed. Check status before choosing again.';}
      finally{writing=false;if(selected===epoch){render(null);await refresh(true);if(!menu.hidden)root.querySelector('#heartbeat-refresh').focus();}}
    }
    function open(){menu.hidden=false;button.setAttribute('aria-expanded','true');void refresh(true);root.querySelector('#heartbeat-refresh').focus();}
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
    render(null);return {refresh,reset};
  }
  window.InteractionHeartbeat={mount,state,action};
})();
