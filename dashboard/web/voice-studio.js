"use strict";
window.VoiceStudioUI=(()=>{
 function mount({parent,api,credential}){
  const panel=document.createElement('section');panel.className='voice-studio';panel.hidden=true;panel.setAttribute('aria-label','Voice studio');parent.append(panel);
  let state,pendingSave,pendingUse,candidate,dirty=false,busy=false,epoch=0;
  let previews={generation:0,batches:[]},batchId,previewBusy=false,previewEpoch=0,playing;const audioURLs=new Map();
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
  const compare=node('p','A keeps your current voice. B is the delivery you are editing. Opening and saving make no audio request. Prepare freezes the same passage for A and B; generate each preview explicitly.');
  const actions=node('div');actions.className='voice-studio-actions';
  const save=node('button','Save revision'),use=node('button','Use on next conversation'),reload=node('button','Refresh revisions');
  for(const button of [save,use,reload]){button.type='button';actions.append(button);}
  const previewPanel=node('section');previewPanel.setAttribute('aria-label','Voice comparison');
  panel.append(title,node('p','Choose delivery for your next Avatar conversation.'),current,choices,label,presets,node('h3','Compare A / B'),passage,compare,previewPanel,actions,status);
  const selected=()=>state?.versions.find(row=>row.id===candidate);
  function controls(){const supported=!!state?.profiles?.length,occupied=busy||previewBusy;save.disabled=occupied||!supported||!!pendingSave||!!pendingUse||!dirty;use.disabled=occupied||!selected()||!state?.profiles?.some(profile=>['provider','api','model','voice'].every(key=>profile[key]===selected().profile[key]))||dirty||!!pendingSave||!!pendingUse;reload.disabled=occupied;delivery.disabled=occupied||!supported;choices.disabled=occupied||!state;for(const button of presets.children)button.disabled=occupied||!supported;previewControls();}
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
  async function refresh(){if(busy)return;const turn=epoch;busy=true;controls();try{reconcile(await read());}catch(error){if(turn===epoch)status.textContent=error.message||'Voice revisions unavailable. Previous selection is kept.';}finally{if(turn===epoch){busy=false;controls();}}}
  async function write(body){
   if(busy)return;busy=true;controls();const turn=epoch,key=credential();
   try{const value=await api('interaction/avatars/voice',body);if(turn!==epoch||key!==credential())return;reconcile({...state,...value});}
   catch(error){if(turn!==epoch||key!==credential())return;status.textContent='Action not confirmed. Reading the same revisions; no automatic retry.';try{reconcile(await read());}catch{status.textContent='Action not confirmed. Refresh revisions to inspect it; the action will not be sent again automatically.';}}
   finally{if(turn===epoch){busy=false;controls();}}
  }
  const previewSelect=node('select');previewSelect.setAttribute('aria-label','Recorded comparison batches');
  const previewActions=node('div');previewActions.className='voice-studio-actions';
  const prepare=node('button','Prepare comparison'),inspect=node('button','Refresh comparisons'),cancel=node('button','Stop generation'),retire=node('button','Retire comparison');
  for(const button of [prepare,inspect,cancel,retire]){button.type='button';previewActions.append(button);}
  const previewStatus=node('p');previewStatus.setAttribute('role','status');const slots=node('div');
  previewPanel.append(previewSelect,previewActions,slots,previewStatus);
  const batch=()=>previews.batches.find(row=>row.id===batchId);
  function stopAudio(){if(playing){playing.pause();playing.removeAttribute('src');playing.load();playing=undefined;}}
  function clearAudio(){stopAudio();for(const url of audioURLs.values())URL.revokeObjectURL(url);audioURLs.clear();}
  function previewControls(){
   const row=batch();prepare.disabled=busy||previewBusy||!state?.audition_available||previews.batches.length>=4;
   inspect.disabled=previewBusy;previewSelect.disabled=previewBusy;cancel.disabled=!row||(!previewBusy&&!Object.values(row.renders).some(r=>['intent','cancel_requested'].includes(r.state)));
   retire.disabled=busy||previewBusy||!row||Object.values(row.renders).some(r=>!['prepared','rendered','not_started','cancelled_verified'].includes(r.state));
   slots.replaceChildren();if(!row)return;
   for(const slot of ['A','B']){
    const render=row.renders[slot],group=node('div'),description=node('p',slot+' · '+row.choices[slot].profile.voice+' · '+(row.choices[slot].delivery||'Current delivery')+' · '+render.state);
    group.className='voice-studio-actions';group.append(description);
    const generate=node('button',render.state==='rendered'?'Load '+slot:'Generate '+slot),play=node('button','Play '+slot),stop=node('button','Stop playback '+slot);
    generate.type=play.type=stop.type='button';generate.disabled=busy||previewBusy||!['prepared','rendered'].includes(render.state);
    play.disabled=!audioURLs.has(slot)||previewBusy;stop.disabled=!audioURLs.has(slot);
    generate.addEventListener('click',()=>void previewWrite({action:'render',id:row.id,batch_generation:row.generation,slot}));
    play.addEventListener('click',()=>{stopAudio();playing=new Audio(audioURLs.get(slot));playing.play().catch(()=>{previewStatus.textContent='Playback could not start. The recorded preview is kept.';});});
    stop.addEventListener('click',stopAudio);group.append(generate,play,stop);
    const proof=render.outcome?.receipt?.provider_receipt;
    if(proof)group.append(node('p','Recorded preview · usage '+(proof.usage?.seconds??'unknown')+' seconds · first audio '+(proof.first_pcm_millis??'unknown')+' ms. Live conversation latency and hearing are not measured.'));
    slots.append(group);
   }
  }
  function showPreviews(){
   previewSelect.replaceChildren();for(const row of previews.batches){const option=node('option',new Date(row.createdAt).toLocaleTimeString()+' · A / B');option.value=row.id;previewSelect.append(option);}
   if(!batch()){clearAudio();batchId=previews.batches.at(-1)?.id;}previewSelect.value=batchId||'';previewControls();
  }
  async function previewRead(){const turn=epoch,key=credential();const value=await api('interaction/avatars/voice/previews');if(turn!==epoch||key!==credential())throw Error('Voice account changed');return value;}
  async function refreshPreviews(){if(previewBusy)return;const turn=epoch;try{previews=await previewRead();showPreviews();}catch(error){if(turn===epoch)previewStatus.textContent=error.message||'Comparisons unavailable.';}}
  async function previewWrite(body){
   if(previewBusy)return;if(['prepare','retire'].includes(body.action))clearAudio();else stopAudio();if(body.slot&&audioURLs.has(body.slot)){URL.revokeObjectURL(audioURLs.get(body.slot));audioURLs.delete(body.slot);}previewBusy=true;const turn=epoch,key=credential(),operation=++previewEpoch;controls();
   try{
    const value=await api('interaction/avatars/voice/previews',body);if(turn!==epoch||key!==credential())return;
    const row=value.batch||(value.renders?value:null);if(row){batchId=row.id;previews.batches=previews.batches.filter(r=>r.id!==row.id).concat(row);}
    if(value.audio&&body.slot){const bytes=Uint8Array.from(atob(value.audio.data),c=>c.charCodeAt(0));audioURLs.set(body.slot,URL.createObjectURL(new Blob([bytes],{type:value.audio.mime})));}
    previews=await previewRead();previewStatus.textContent='Comparison kept. Playback starts only when you choose Play.';
   }catch(error){if(turn!==epoch||key!==credential())return;previewStatus.textContent='Action not confirmed. Reading its retained status; no generation is retried.';try{previews=await previewRead();}catch{previewStatus.textContent='Status unavailable. Refresh comparisons to inspect the same attempt.';}}
   finally{if(turn===epoch&&operation===previewEpoch){previewBusy=false;showPreviews();controls();}}
  }
  previewSelect.addEventListener('change',()=>{clearAudio();batchId=previewSelect.value;previewControls();});
  prepare.addEventListener('click',()=>{if(!prepare.disabled)void previewWrite({action:'prepare',id:crypto.randomUUID(),profile:state.profiles[0],delivery:delivery.value,voice_generation:state.generation,generation:previews.generation});});
  inspect.addEventListener('click',()=>void refreshPreviews());
  cancel.addEventListener('click',()=>{const row=batch();if(!row)return;const turn=epoch,key=credential();void api('interaction/avatars/voice/previews',{action:'cancel',id:row.id,batch_generation:row.generation}).then(()=>{if(turn===epoch&&key===credential())previewStatus.textContent='Stop requested. Waiting for the owned generation to close.';}).catch(()=>{if(turn===epoch)previewStatus.textContent='Stop not confirmed. Refresh to inspect; no automatic retry.';});});
  retire.addEventListener('click',()=>{const row=batch();if(!retire.disabled&&row)void previewWrite({action:'retire',id:row.id,batch_generation:row.generation,generation:previews.generation});});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stopAudio();});
  choices.addEventListener('change',()=>{if(busy)return;candidate=choices.value||undefined;delivery.value=selected()?.delivery||'';dirty=false;controls();});
  delivery.addEventListener('input',()=>{dirty=true;controls();});
  save.addEventListener('click',()=>{if(save.disabled)return;pendingSave={id:crypto.randomUUID(),profile:state.profiles[0],delivery:delivery.value,parentId:candidate||state.active||null,generation:state.generation};void write({action:'save',...pendingSave});});
  use.addEventListener('click',()=>{if(use.disabled)return;pendingUse={id:candidate,generation:state.generation};void write({action:'use',...pendingUse});});
  reload.addEventListener('click',()=>void refresh());
  function reset(){clearAudio();previews={generation:0,batches:[]};batchId=undefined;previewBusy=false;previewEpoch++;epoch++;state=pendingSave=pendingUse=candidate=undefined;busy=dirty=false;delivery.value='';status.textContent='';previewStatus.textContent='';current.textContent='';choices.replaceChildren();previewSelect.replaceChildren();panel.hidden=true;controls();}
  return {panel,hide(){stopAudio();},open(){panel.hidden=false;if(!state)void refresh();void refreshPreviews();},reset,
   mayClose(){if(previewBusy){previewStatus.textContent='Stop generation and wait for its result before closing.';return false;}if(dirty&&!confirm('Discard the unsaved voice edit?'))return false;clearAudio();dirty=false;return true;}};
 }
 return {mount};
})();
