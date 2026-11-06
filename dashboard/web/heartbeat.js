/* Foreground owner-console observation; no attention producer or control writes. */
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
  function mount({api,authenticated,root=document,clock=()=>Date.now()}) {
    const button=root.querySelector('#heartbeat-toggle'),menu=root.querySelector('#heartbeat-menu');
    if(!button || !menu)return;
    const status=root.querySelector('#heartbeat-status'),generation=root.querySelector('#heartbeat-generation'),lanes=root.querySelector('#heartbeat-lanes');
    const labels={paused:'Paused',unconfigured:'Not configured',unavailable:'Status unavailable',error:'Error',operational:'Operational'};
    let last=-Infinity,pending=false,hold,held=false,epoch=0,expiry;
    function render(value){
      clearTimeout(expiry);
      const selected=state(value);button.dataset.state=selected;button.setAttribute('aria-label','Heartbeat · '+labels[selected]);button.title='Heartbeat · '+labels[selected];
      if(selected==='operational')expiry=setTimeout(()=>render(null),15000);
      status.textContent='Heartbeat · '+labels[selected];
      generation.textContent=Number.isSafeInteger(value?.generation)?'Generation '+value.generation:'';
      lanes.replaceChildren();
      for(const [id,name] of [['global','All heartbeat lanes'],['messaging','Messaging'],['issues','Issues'],['sensory','Sensory'],['tasks','Tasks'],['bitacora','Bitácora']]){
        const row=root.createElement('div'),control=root.createElement('button'),reason=root.createElement('span');
        control.type='button';control.disabled=true;control.textContent=name;
        reason.textContent=id==='global'?'Shared generation-aware app controls are not available.':id==='messaging'?'Messaging lane control is not available in the selected backend.':'Not supported yet; no resources activated.';
        const reasonId='heartbeat-'+id+'-reason';reason.id=reasonId;control.setAttribute('aria-describedby',reasonId);row.append(control,reason);lanes.append(row);
      }
      if(selected==='paused' && (value?.producer?.state==='not_configured' || value?.resources?.state==='not_configured'))status.textContent+=' · producer/resources not configured';
    }
    function open(){menu.hidden=false;button.setAttribute('aria-expanded','true');void refresh(true);root.querySelector('#heartbeat-refresh').focus();}
    function close(){menu.hidden=true;button.setAttribute('aria-expanded','false');button.focus();}
    async function refresh(force=false){
      if(!authenticated() || document.hidden){epoch++;render(null);return;}
      if(pending || !force && clock()-last<10000)return;
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
    function reset(){epoch++;render(null);menu.hidden=true;button.setAttribute('aria-expanded','false');}
    render(null);return {refresh,reset};
  }
  window.InteractionHeartbeat={mount,state};
})();
