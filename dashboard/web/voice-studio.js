"use strict";
window.VoiceStudioUI=(()=>{
 function mount({parent,api,credential}){
  const panel=document.createElement('section');panel.className='voice-studio';panel.hidden=true;panel.setAttribute('aria-label','Voice studio');parent.append(panel);
  let state,pendingSave,pendingUse,candidate,dirty=false,busy=false,epoch=0;
  let previews={generation:0,batches:[]},batchId,previewBusy=false,previewEpoch=0,playing,pendingPreview;const audioURLs=new Map(),cancelling=new Set();
  const node=(tag,text)=>{const value=document.createElement(tag);if(text)value.textContent=text;return value;};
  const spanish=(navigator.language||'').toLowerCase().startsWith('es'),say=(en,es)=>spanish?es:en;
  panel.lang=spanish?'es-AR':'en';
  panel.setAttribute('aria-label',say('Voice workshop','Taller de voces'));
  const title=node('h2',say('A voice that feels like me','Una voz a mi manera')),current=node('p'),status=node('p');status.setAttribute('role','status');status.className='voice-studio-notice';
  const intro=node('header');intro.className='voice-studio-intro';
  const mark=node('span','♪');mark.className='voice-studio-mark';mark.setAttribute('aria-hidden','true');
  const welcome=node('div');welcome.append(node('p',say('VOICE WORKSHOP','TALLER DE VOCES')),title,node('p',say('Try a way of speaking. Listen, play, and keep the one you like.','Probá cómo habla tu daimon. Escuchá, jugá y quedate con el estilo que te guste.')));intro.append(mark,welcome);
  const choices=node('select');choices.setAttribute('aria-label',say('My saved styles','Mis estilos guardados'));
  const delivery=node('textarea');delivery.rows=3;delivery.maxLength=1024;delivery.setAttribute('aria-label',say('Describe how the voice should sound','Contá cómo querés que suene'));delivery.placeholder=say('For example: cheerful, with gentle pauses…','Por ejemplo: alegre, con pausas suaves…');
  const label=node('label',say('How would you like me to speak?','¿Cómo querés que hable?'));label.append(delivery);
  const presets=node('div');presets.className='voice-studio-presets';
  const styles=[['Calm','Tranquila','Take your time','Sin apuro','Use an even, clear delivery with natural pauses.','☁'],['Warm','Cálida','Like a friendly chat','Como una charla entre amigos','Use a warm, relaxed delivery with natural pauses.','☀'],['Robot','De robot','Precise and playful','Precisa y juguetona','Use a precise, deliberately synthetic delivery while keeping every word clear.','⌁']];
  for(const [name,esName,hint,esHint,text,symbol] of styles){
   const button=node('button');button.type='button';button.setAttribute('aria-label',say(name,esName));button.setAttribute('aria-pressed','false');const icon=node('span',symbol);icon.setAttribute('aria-hidden','true');button.append(icon,node('strong',say(name,esName)),node('small',say(hint,esHint)));button.dataset.delivery=text;
   button.addEventListener('click',()=>{if(busy||previewBusy)return;delivery.value=text;candidate=undefined;choices.value='';dirty=true;controls();});presets.append(button);
  }
  const custom=node('details');custom.className='voice-studio-custom';custom.append(node('summary',say('Describe it your way','Describila a tu manera')),label);
  const styling=node('section');styling.className='voice-studio-card';styling.append(node('h3',say('How shall I speak?','¿Cómo voy a hablar?')),node('p',say('Keep my voice, and change its style.','La misma voz puede hablar de muchas maneras.')),presets,custom);
  const passage=node('blockquote','Dale, Compai. Sigamos con la idea de Alter Mundi, con calma y claridad.');
  const compare=node('p',say('Make a short sample of each style. Then press Listen.','Creá una muestra cortita de cada estilo. Después tocá Escuchar.'));
  const actions=node('div');actions.className='voice-studio-actions';
  const save=node('button',say('Save my style','Guardar mi estilo')),use=node('button',say('Choose this style','Elegir este estilo')),reload=node('button',say('Check saved styles','Revisar estilos guardados'));
  save.className='voice-studio-primary';use.className='voice-studio-primary';
  for(const button of [save,use,reload])button.type='button';actions.append(save,use);
  const savedLabel=node('label',say('My saved styles','Mis estilos guardados'));savedLabel.append(choices);
  const keeping=node('section');keeping.className='voice-studio-card voice-studio-keep';keeping.append(node('h3',say('Keep your favourite','Quedate con tu favorita')),node('p',say('Save your style, then choose it. It will be used when we start a new voice chat.','Guardá tu estilo y después elegilo. Lo usaremos cuando empecemos una charla de voz nueva.')),savedLabel,actions,status);
  const previewPanel=node('section');previewPanel.className='voice-studio-card voice-studio-listen';previewPanel.setAttribute('aria-label',say('Listen to your styles','Escuchá tus estilos'));previewPanel.append(node('h3',say('Let’s hear it','Vamos a escuchar')),compare,passage);
  const grid=node('div');grid.className='voice-studio-grid';grid.append(styling,previewPanel);
  const technical=node('details');technical.className='voice-studio-more';technical.append(node('summary',say('More options','Más opciones')),current,reload);
  panel.append(intro,grid,keeping,technical);
  const selected=()=>state?.versions.find(row=>row.id===candidate);
  function controls(){const supported=!!state?.profiles?.length,occupied=busy||previewBusy;save.disabled=occupied||!supported||!!pendingSave||!!pendingUse||!dirty;use.disabled=occupied||!selected()||!state?.profiles?.some(profile=>['provider','api','model','voice'].every(key=>profile[key]===selected().profile[key]))||dirty||!!pendingSave||!!pendingUse;reload.disabled=occupied;delivery.disabled=occupied||!supported;choices.disabled=occupied||!state;for(const button of presets.children){button.disabled=occupied||!supported;button.setAttribute('aria-pressed',String(button.dataset.delivery===delivery.value));}previewControls();}
  function show(){
   const active=state?.versions.find(row=>row.id===state.active),profile=active?.profile||state?.profiles?.[0];
   current.textContent=profile?say('Configured voice: ','Voz configurada: ')+profile.voice:(state?.message||say('Loading voice…','Cargando la voz…'));
   choices.replaceChildren();const fresh=node('option',say('A new style','Un estilo nuevo'));fresh.value='';choices.append(fresh);
   for(const [index,row] of (state?.versions||[]).entries()){const known=styles.find(style=>style[4]===row.delivery);const name=known?say(known[0],known[1]):say('My style ','Mi estilo ')+(index+1);const option=node('option',name+(row.id===state.active?say(' · chosen',' · elegido'):''));option.value=row.id;choices.append(option);}
   choices.value=candidate||'';controls();
  }
  function reconcile(value){
   const first=!state;state=value;if(first&&!dirty){candidate=state.active||undefined;delivery.value=selected()?.delivery||'';}
   if(pendingSave){const row=state.versions.find(row=>row.id===pendingSave.id);
    if(row&&row.parentId===pendingSave.parentId&&row.delivery===pendingSave.delivery&&['provider','api','model','voice'].every(key=>row.profile[key]===pendingSave.profile[key])){
     candidate=row.id;pendingSave=undefined;dirty=false;status.textContent=say('Style saved. Choose it when you are ready.','Estilo guardado. Elegilo cuando quieras.');
    }
   }
   if(pendingUse&&state.active===pendingUse.id&&state.generation===pendingUse.generation+1){pendingUse=undefined;status.textContent=say('Chosen! We will use it in our next voice chat.','¡Elegido! Lo vamos a usar en nuestra próxima charla de voz.');}
   show();
  }
  async function read(){const turn=epoch,key=credential();const value=await api('interaction/avatars/voice');if(turn!==epoch||key!==credential())throw Error('Voice account changed');return value;}
  async function refresh(){if(busy)return;const turn=epoch;busy=true;controls();try{reconcile(await read());}catch(error){if(turn===epoch)status.textContent=error.message||say('Your styles could not be loaded. Your voice is still the same.','No pudimos cargar tus estilos. Tu voz sigue igual.');}finally{if(turn===epoch){busy=false;controls();}}}
  async function write(body){
   if(busy)return;busy=true;controls();const turn=epoch,key=credential();
   try{const value=await api('interaction/avatars/voice',body);if(turn!==epoch||key!==credential())return;reconcile({...state,...value});}
   catch(error){if(turn!==epoch||key!==credential())return;status.textContent=say('Checking whether your change was saved…','Estoy revisando si se guardó tu cambio…');try{reconcile(await read());}catch{status.textContent=say('We could not confirm the change. Check saved styles before trying again.','No pudimos confirmar el cambio. Revisá los estilos guardados antes de intentar de nuevo.');}}
   finally{if(turn===epoch){busy=false;controls();}}
  }
  const previewSelect=node('select');previewSelect.setAttribute('aria-label',say('My earlier tests','Mis pruebas anteriores'));
  const previewActions=node('div');previewActions.className='voice-studio-actions';
  const prepare=node('button',say('Make a voice test','Crear una prueba')),inspect=node('button',say('Check test status','Revisar esta prueba')),cancel=node('button',say('Stop making audio','Detener el audio')),retire=node('button',say('Delete this test','Borrar esta prueba'));prepare.className='voice-studio-primary';
  for(const button of [prepare,inspect,cancel,retire])button.type='button';previewActions.append(prepare,cancel);
  const previewStatus=node('p');previewStatus.setAttribute('role','status');const slots=node('div');
  previewPanel.append(previewActions,slots,previewStatus);const testTools=node('details');testTools.className='voice-studio-more';testTools.append(node('summary',say('My tests','Mis pruebas')),previewSelect,inspect,retire);technical.append(testTools);
  const batch=()=>previews.batches.find(row=>row.id===batchId);
  function stopAudio(){if(playing){playing.pause();playing.removeAttribute('src');playing.load();playing=undefined;}}
  function clearAudio(){stopAudio();for(const url of audioURLs.values())URL.revokeObjectURL(url);audioURLs.clear();}
  function previewControls(){
   const row=batch();prepare.disabled=busy||previewBusy||!state?.audition_available||previews.batches.length>=4;
   inspect.disabled=previewBusy;previewSelect.disabled=previewBusy;cancel.disabled=!row||pendingPreview?.cancelSent===true||cancelling.has(epoch+':'+row.id+':'+row.generation)||(!(previewBusy&&pendingPreview?.mayGenerate)&&!Object.values(row.renders).some(r=>['intent','cancel_requested'].includes(r.state)));
   retire.disabled=busy||previewBusy||!row||Object.values(row.renders).some(r=>!['prepared','rendered','not_started','cancelled_verified'].includes(r.state));
   cancel.hidden=cancel.disabled;slots.replaceChildren();if(!row){slots.append(node('p',state?.audition_available===false?say('Samples are not available here yet. Your saved voice is kept.','Las muestras todavía no están disponibles acá. Tu voz guardada sigue igual.'):say('Your samples will appear here. Nothing is recorded from your microphone.','Tus muestras van a aparecer acá. No grabamos tu micrófono.')));return;}
   for(const slot of ['A','B']){
    const render=row.renders[slot],group=node('div'),description=node('h4',slot==='A'?say('My voice now','Mi voz de ahora'):say('My new style','Mi estilo nuevo'));
    group.className='voice-studio-sample';const badge=node('span',slot==='A'?'♪':'♫');badge.className='voice-studio-sample-mark';badge.setAttribute('aria-hidden','true');
    const states={prepared:say('Ready to make','Lista para crear'),rendered:say('Ready to listen','Lista para escuchar'),intent:say('Making your sample…','Creando tu muestra…'),cancel_requested:say('Stopping…','Deteniendo…'),unconfirmed:say('This sample wasn’t confirmed. Check its status; it won’t be made again.','Esta muestra no se confirmó. Revisá su estado; no la vamos a crear de nuevo.'),not_started:say('Not made','Sin crear'),cancelled_verified:say('Stopped','Detenida')};
    group.append(badge,description,node('p',states[render.state]||say('Check this sample','Revisá esta muestra')));
    const buttons=node('div');buttons.className='voice-studio-actions';
    const generate=node('button',render.state==='rendered'?say('Get saved audio','Cargar audio guardado'):say('Make this sample','Crear esta muestra')),play=node('button',say('▶ Listen','▶ Escuchar')),stop=node('button',say('Stop','Parar'));
    generate.type=play.type=stop.type='button';generate.disabled=busy||previewBusy||!['prepared','rendered'].includes(render.state);generate.hidden=render.state==='rendered'&&audioURLs.has(slot);
    play.disabled=!audioURLs.has(slot)||previewBusy;stop.disabled=!audioURLs.has(slot);stop.hidden=!audioURLs.has(slot);play.className='voice-studio-primary';
    generate.setAttribute('aria-label',(slot==='A'?say('Current voice: ','Voz actual: '):say('New style: ','Estilo nuevo: '))+generate.textContent);
    play.setAttribute('aria-label',slot==='A'?say('Listen to my current voice','Escuchar mi voz actual'):say('Listen to my new style','Escuchar mi estilo nuevo'));
    generate.addEventListener('click',()=>void previewWrite({action:'render',id:row.id,batch_generation:row.generation,slot}));
    play.addEventListener('click',()=>{stopAudio();const output=playing=new Audio(audioURLs.get(slot)),turn=epoch,operation=previewEpoch;output.play().catch(()=>{if(playing===output&&turn===epoch&&operation===previewEpoch)previewStatus.textContent=say('Press Listen again to play your saved sample.','Tocá Escuchar otra vez para oír tu muestra guardada.');});});
    stop.setAttribute('aria-label',slot==='A'?say('Stop my current sample','Parar mi muestra actual'):say('Stop my new sample','Parar mi muestra nueva'));stop.addEventListener('click',stopAudio);buttons.append(generate,play,stop);group.append(buttons);
    const proof=render.outcome?.receipt?.provider_receipt;
    if(proof){const details=node('details');details.append(node('summary',say('Sample details','Detalles de la muestra')),node('p',say('Recorded seconds: ','Segundos registrados: ')+(proof.usage?.seconds??'—')));group.append(details);}
    slots.append(group);
   }
  }
  function showPreviews(){
   previewSelect.replaceChildren();for(const row of previews.batches){const option=node('option',say('Test at ','Prueba de las ')+new Date(row.createdAt).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}));option.value=row.id;previewSelect.append(option);}
   if(!batch()){clearAudio();batchId=previews.batches.at(-1)?.id;}previewSelect.value=batchId||'';previewControls();
  }
  async function previewRead(){const turn=epoch,key=credential();const value=await api('interaction/avatars/voice/previews');if(turn!==epoch||key!==credential())throw Error('Voice account changed');return value;}
  async function refreshPreviews(){if(previewBusy)return;const turn=epoch,operation=previewEpoch;try{const value=await previewRead();if(turn!==epoch||operation!==previewEpoch)return;previews=value;showPreviews();}catch(error){if(turn===epoch&&operation===previewEpoch)previewStatus.textContent=error.message||say('Your tests could not be loaded.','No pudimos cargar tus pruebas.');}}
  async function previewWrite(body){
   if(previewBusy)return;if(['prepare','retire'].includes(body.action))clearAudio();else stopAudio();if(body.slot&&audioURLs.has(body.slot)){URL.revokeObjectURL(audioURLs.get(body.slot));audioURLs.delete(body.slot);}previewBusy=true;const turn=epoch,key=credential(),operation=++previewEpoch;pendingPreview={...body,operation,cancelSent:false,mayGenerate:body.action==='render'&&batch()?.id===body.id&&batch()?.renders[body.slot]?.state==='prepared'};const current=()=>turn===epoch&&key===credential()&&operation===previewEpoch;controls();
   try{
    const value=await api('interaction/avatars/voice/previews',body);if(!current())return;pendingPreview.mayGenerate=false;
    const row=value.batch||(value.renders?value:null);if(row){batchId=row.id;previews.batches=previews.batches.filter(r=>r.id!==row.id).concat(row);}
    if(value.audio&&body.slot){const bytes=Uint8Array.from(atob(value.audio.data),c=>c.charCodeAt(0));audioURLs.set(body.slot,URL.createObjectURL(new Blob([bytes],{type:value.audio.mime})));}
    const snapshot=await previewRead();if(!current())return;previews=snapshot;previewStatus.textContent=say('Your test is saved. Press Listen when the audio is ready.','Tu prueba quedó guardada. Tocá Escuchar cuando el audio esté listo.');
   }catch(error){if(!current())return;previewStatus.textContent=say('Checking your sample. We will not make it again.','Estoy revisando tu muestra. No la vamos a crear de nuevo.');try{const snapshot=await previewRead();if(current())previews=snapshot;}catch{if(current())previewStatus.textContent=say('We could not confirm this sample. Open My tests to check it.','No pudimos confirmar esta muestra. Abrí Mis pruebas para revisarla.');}}
   finally{if(current()){previewBusy=false;pendingPreview=undefined;showPreviews();controls();}}
  }
  previewSelect.addEventListener('change',()=>{clearAudio();batchId=previewSelect.value;previewControls();});
  prepare.addEventListener('click',()=>{if(!prepare.disabled)void previewWrite({action:'prepare',id:crypto.randomUUID(),profile:state.profiles[0],delivery:delivery.value,voice_generation:state.generation,generation:previews.generation});});
  inspect.addEventListener('click',()=>void refreshPreviews());
  function stopGeneration(onlyCurrent=false){
   const job=pendingPreview?.mayGenerate?pendingPreview:undefined,row=batch();
   if(onlyCurrent&&!job)return;
   const id=job?.id||row?.id,generation=job?.batch_generation??row?.generation;
   if(!id||job?.cancelSent)return;
   const turn=epoch,key=credential(),operation=previewEpoch,scope=turn+':'+id+':'+generation;
   if(cancelling.has(scope))return;if(job)job.cancelSent=true;cancelling.add(scope);controls();
   const current=()=>turn===epoch&&key===credential()&&operation===previewEpoch;
   void api('interaction/avatars/voice/previews',{action:'cancel',id,batch_generation:generation})
    .then(()=>{if(current())previewStatus.textContent=say('Stopping your sample…','Estoy deteniendo tu muestra…');})
    .catch(()=>{if(current())previewStatus.textContent=say('Stopping was not confirmed. Check this test’s status.','No pudimos confirmar que se detuvo. Revisá el estado de esta prueba.');})
    .finally(()=>{cancelling.delete(scope);if(turn===epoch)controls();});
  }
  cancel.addEventListener('click',()=>stopGeneration());
  retire.addEventListener('click',()=>{const row=batch();if(!retire.disabled&&row)void previewWrite({action:'retire',id:row.id,batch_generation:row.generation,generation:previews.generation});});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stopAudio();});
  choices.addEventListener('change',()=>{if(busy)return;candidate=choices.value||undefined;delivery.value=selected()?.delivery||'';dirty=false;controls();});
  delivery.addEventListener('input',()=>{dirty=true;controls();});
  save.addEventListener('click',()=>{if(save.disabled)return;pendingSave={id:crypto.randomUUID(),profile:state.profiles[0],delivery:delivery.value,parentId:candidate||state.active||null,generation:state.generation};void write({action:'save',...pendingSave});});
  use.addEventListener('click',()=>{if(use.disabled)return;pendingUse={id:candidate,generation:state.generation};void write({action:'use',...pendingUse});});
  reload.addEventListener('click',()=>void refresh());
  function reset(){clearAudio();pendingPreview=undefined;cancelling.clear();previews={generation:0,batches:[]};batchId=undefined;previewBusy=false;previewEpoch++;epoch++;state=pendingSave=pendingUse=candidate=undefined;busy=dirty=false;delivery.value='';status.textContent='';previewStatus.textContent='';current.textContent='';choices.replaceChildren();previewSelect.replaceChildren();panel.hidden=true;controls();}
  return {panel,hide(){stopAudio();},open(){panel.hidden=false;if(!state)void refresh();void refreshPreviews();},reset,
   mayClose(){const discard=dirty;if(discard&&!confirm(say('Leave without saving your style?','¿Salir sin guardar tu estilo?')))return false;stopGeneration(true);clearAudio();previewEpoch++;previewBusy=false;pendingPreview=undefined;dirty=false;if(discard){candidate=state?.active||undefined;delivery.value=selected()?.delivery||'';show();}controls();return true;}};
 }
 return {mount};
})();
