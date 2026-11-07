"use strict";
window.VoiceStudioUI=(()=>{
 function mount({parent,api,credential}){
  const panel=document.createElement('section');panel.className='voice-studio';panel.hidden=true;panel.setAttribute('aria-label','Voice studio');parent.append(panel);
  let state,pendingSave,pendingUse,candidate,dirty=false,busy=false,epoch=0;
  const node=(tag,text)=>{const value=document.createElement(tag);if(text)value.textContent=text;return value;};
  const title=node('h2','Avatar voice'),current=node('p'),status=node('p');status.setAttribute('role','status');
  const choices=node('select');choices.setAttribute('aria-label','Saved voice revisions');
  const delivery=node('textarea');delivery.rows=4;delivery.maxLength=1024;delivery.setAttribute('aria-label','Voice delivery instruction');
  const label=node('label','Delivery');label.append(delivery);
  const presets=node('div');presets.className='voice-studio-actions';
  for(const [name,text] of [['Neutral','Use an even, clear delivery with natural pauses.'],['Warm','Use a warm, relaxed delivery with natural pauses.'],['Synthetic','Use a precise, deliberately synthetic delivery while keeping every word clear.']]){
   const button=node('button',name);button.type='button';button.addEventListener('click',()=>{if(busy)return;delivery.value=text;candidate=undefined;dirty=true;controls();});presets.append(button);
  }
  const passage=node('blockquote','Dale, Compai. Sigamos con la idea de Alter Mundi, con calma y claridad.');
  const compare=node('p','A keeps your current voice. B is the delivery you are editing. Audio comparison is not available yet; opening or saving makes no audio request.');
  const actions=node('div');actions.className='voice-studio-actions';
  const save=node('button','Save revision'),use=node('button','Use on next conversation'),reload=node('button','Refresh revisions');
  for(const button of [save,use,reload]){button.type='button';actions.append(button);}
  panel.append(title,node('p','Choose delivery for your next Avatar conversation.'),current,choices,label,presets,node('h3','Compare A / B'),passage,compare,actions,status);
  const selected=()=>state?.versions.find(row=>row.id===candidate);
  function controls(){const supported=!!state?.profiles?.length;save.disabled=busy||!supported||!!pendingSave||!!pendingUse||!dirty;use.disabled=busy||!selected()||!state?.profiles?.some(profile=>['provider','api','model','voice'].every(key=>profile[key]===selected().profile[key]))||dirty||!!pendingSave||!!pendingUse;reload.disabled=busy;delivery.disabled=busy||!supported;choices.disabled=busy||!state;for(const button of presets.children)button.disabled=busy||!supported;}
  function show(){
   const active=state?.versions.find(row=>row.id===state.active),profile=active?.profile||state?.profiles?.[0];
   current.textContent=profile?'A · '+profile.voice+' · '+(active?.delivery||'Current delivery'):(state?.message||'Loading voice…');
   choices.replaceChildren();const fresh=node('option','New revision');fresh.value='';choices.append(fresh);
   for(const row of state?.versions||[]){const option=node('option',row.profile.voice+' · '+(row.delivery||'Current delivery'));option.value=row.id;choices.append(option);}
   choices.value=candidate||'';controls();
  }
  function reconcile(value){
   state=value;
   if(pendingSave){const row=state.versions.find(row=>row.id===pendingSave.id);
    if(row&&row.parentId===pendingSave.parentId&&row.delivery===pendingSave.delivery&&['provider','api','model','voice'].every(key=>row.profile[key]===pendingSave.profile[key])){
     candidate=row.id;pendingSave=undefined;dirty=false;status.textContent='Revision saved. Your current voice is kept until you choose Use.';
    }
   }
   if(pendingUse&&state.active===pendingUse.id&&state.generation===pendingUse.generation+1){pendingUse=undefined;status.textContent='Selected for the next conversation. An open connection and its reconnects keep their voice.';}
   show();
  }
  async function read(){const turn=epoch,key=credential();const value=await api('interaction/avatars/voice');if(turn!==epoch||key!==credential())throw Error('Voice account changed');return value;}
  async function refresh(){if(busy)return;busy=true;controls();try{reconcile(await read());}catch(error){status.textContent=error.message||'Voice revisions unavailable. Previous selection is kept.';}finally{busy=false;controls();}}
  async function write(body){
   if(busy)return;busy=true;controls();const turn=epoch,key=credential();
   try{const value=await api('interaction/avatars/voice',body);if(turn!==epoch||key!==credential())return;reconcile({...state,...value});}
   catch(error){if(turn!==epoch||key!==credential())return;status.textContent='Action not confirmed. Reading the same revisions; no automatic retry.';try{reconcile(await read());}catch{status.textContent='Action not confirmed. Refresh revisions to inspect it; the action will not be sent again automatically.';}}
   finally{if(turn===epoch){busy=false;controls();}}
  }
  choices.addEventListener('change',()=>{if(busy)return;candidate=choices.value||undefined;delivery.value=selected()?.delivery||'';dirty=false;controls();});
  delivery.addEventListener('input',()=>{dirty=true;controls();});
  save.addEventListener('click',()=>{if(save.disabled)return;pendingSave={id:crypto.randomUUID(),profile:state.profiles[0],delivery:delivery.value,parentId:candidate||state.active||null,generation:state.generation};void write({action:'save',...pendingSave});});
  use.addEventListener('click',()=>{if(use.disabled)return;pendingUse={id:candidate,generation:state.generation};void write({action:'use',...pendingUse});});
  reload.addEventListener('click',()=>void refresh());
  function reset(){epoch++;state=pendingSave=pendingUse=candidate=undefined;busy=dirty=false;delivery.value='';status.textContent='';current.textContent='';choices.replaceChildren();panel.hidden=true;controls();}
  return {panel,open(){panel.hidden=false;if(!state)void refresh();},reset,
   mayClose(){if(dirty&&!confirm('Discard the unsaved voice edit?'))return false;dirty=false;return true;}};
 }
 return {mount};
})();
