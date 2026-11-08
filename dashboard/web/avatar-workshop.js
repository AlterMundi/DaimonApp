"use strict";
window.AvatarWorkshopUI=(()=>{
 function mount({api,headers}){
  const button=document.querySelector('#avatar-workshop-open'),portrait=document.querySelector('#conversation-companion pre');
  if(!button||!portrait)return;
  button.hidden=false;
  let actor,epoch=0,loaded=false,busy=false,editorReady=false,dialog,iframe,studio,voiceTab,canvas,paint,artisticCue,frame=0,timer,paused=false;
  const motion=matchMedia('(prefers-reduced-motion: reduce)'),asset=path=>new URL('assets/avatar-workshop/'+path,document.baseURI).href;
  const voiceLabel=(en,es)=>(navigator.language||'').toLowerCase().startsWith('es')?es:en;
  const frameBox=document.createElement('div');frameBox.className='avatar-frame';portrait.before(frameBox);const surface=document.createElement('div');surface.className='avatar-surface';surface.dataset.avatarState='loading';surface.setAttribute('aria-busy','true');frameBox.append(surface);surface.append(portrait);
  const controls=document.createElement('nav');controls.className='avatar-frame-controls';controls.setAttribute('aria-label',voiceLabel('Avatar controls','Controles del avatar'));frameBox.append(controls);
  const pause=document.querySelector('#avatar-workshop-pause');controls.append(button);if(pause)controls.append(pause);
  const icon=(target,kind,label)=>{target.setAttribute('aria-label',label);target.title=label;target.innerHTML=kind==='gear'?'<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7"><path d="m9 3-.6 2.3-2 .9-2.1-.6L2.8 8l1.5 1.8-.2 2.3L2.8 14l1.5 2.5 2.3-.4 1.8 1.3L9 20h3l.7-2.6 1.9-1.2 2.3.4 1.5-2.6-1.4-1.8.1-2.3L18.6 8l-1.5-2.5-2.2.6-2-.9L12.3 3Z"/><circle cx="10.7" cy="11.5" r="3"/></svg>':kind==='play'?'<svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor"><path d="M8 4v16l12-8Z"/></svg>':'<svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor"><path d="M6 4h4v16H6zm8 0h4v16h-4z"/></svg>';};
  icon(button,'gear',voiceLabel('Personalize avatar','Personalizar avatar'));if(pause)icon(pause,'pause',voiceLabel('Pause avatar','Pausar avatar'));
  const voiceEntry=new URLSearchParams(window.location?.search||'').get('workshop')==='voice';let voiceEntryOpened=false;
  const resize=new ResizeObserver(()=>{try{paint?.(frame);}catch{stop();message('Avatar drawing paused. Your saved selection is kept.');}});
  const uuid=value=>typeof value==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value);
  const credential=()=>JSON.stringify(headers());
  function appearance(){const style=getComputedStyle(document.body),value={};for(const role of ['background','surface','text','accent','body-font','heading-font','radius','gap']){const v=style.getPropertyValue('--dm-'+role).trim();if(v&&v.length<256&&!/url\(/i.test(v))value['--dm-'+role]=v;}return value;}
  window.addEventListener('home-style:resolved',()=>iframe?.contentWindow.postMessage({kind:'daimon.workshop.appearance',appearance:appearance()},location.origin));
  const message=text=>{const line=document.querySelector('#avatar-workshop-status');if(line)line.textContent=text;};
  function stop(){clearTimeout(timer);timer=undefined;}
  function run(){stop();if(!paint||paused||motion.matches||document.hidden||dialog?.open)return;timer=setTimeout(()=>{try{paint(frame=(frame+1)%(paint.frames||12));run();}catch{stop();message('Avatar animation paused. Your saved selection is kept.');}},Math.max(80,Math.min(320,paint.frameMs||180)));}
  function reset(){epoch++;studio?.reset();loaded=false;artisticCue=undefined;stop();resize.disconnect();canvas?.remove();canvas=paint=undefined;portrait.hidden=false;surface.dataset.avatarState='loading';surface.setAttribute('aria-busy','true');document.querySelector('#avatar-workshop-pause')?.setAttribute('hidden','');if(dialog?.open)dialog.close();iframe?.remove();iframe=undefined;}
  async function prepared(record){
   const selected=epoch,key=credential(),renderer=await import(asset('renderer.mjs'));
   if(selected!==epoch||key!==credential())throw Error('Avatar account changed');
   const candidate=document.createElement('canvas');candidate.className='workshop-portrait';candidate.setAttribute('role','img');candidate.setAttribute('aria-label',record.name||'Your chosen avatar');
   candidate.style.visibility='hidden';portrait.before(candidate);
   try{const render=renderer.prepare(candidate,record.design);return {candidate,render,selected,key};}catch(error){candidate.remove();throw error;}
  }
  function use(preview){
   if(preview.selected!==epoch||preview.key!==credential()){preview.candidate.remove();throw Error('Avatar account changed');}
   // Finish the transient still while hidden, before replacing the previous drawing.
   preview.render.selectCue?.(artisticCue);preview.render(0);
   stop();resize.disconnect();canvas?.remove();canvas=preview.candidate;paint=preview.render;canvas.style.visibility='';portrait.hidden=true;surface.dataset.avatarState='custom';surface.setAttribute('aria-busy','false');document.querySelector('#avatar-workshop-pause')?.removeAttribute('hidden');frame=0;resize.observe(canvas);run();
  }
  function artisticRest(value){
   const aliases={calm:'calm',curious:'curious',focused:'focus',focus:'focus',delighted:'joy',joy:'joy',sad:'sad',anger:'anger',uncertain:'uncertain',welcome:'welcome',sleep:'sleep'};
   const cue=Object.hasOwn(aliases,value)?aliases[value]:undefined;
   if(cue===artisticCue)return;artisticCue=cue;
   if(!paint)return;
   try{if(paint.selectCue?.(cue)){frame=0;paint(frame);}run();}
   catch{stop();message('Avatar drawing paused. Your saved selection is kept.');}
  }
  async function refresh(){
   if(loaded||!actor)return;loaded=true;const selected=epoch,key=credential();
   try{const state=await api('interaction/avatars');if(selected!==epoch||key!==credential())return;if(state.active){const record=await api('interaction/avatars/'+state.active);if(selected!==epoch||key!==credential())return;use(await prepared(record));}else{surface.dataset.avatarState='builtin';surface.setAttribute('aria-busy','false');}}
   catch{if(selected===epoch)message('Your previous avatar is kept. Open the workshop to retry.');}
  }
  function close(){if(studio&&!studio.mayClose())return;if(dialog?.open)dialog.close();iframe?.remove();iframe=undefined;button.focus();run();}
  button.addEventListener('click',()=>{
   if(!actor)return;
   if(!dialog){dialog=document.createElement('dialog');dialog.className='avatar-workshop-dialog';dialog.setAttribute('aria-label',voiceLabel('Avatar workshop','Taller de avatar'));const back=document.createElement('button');back.textContent=voiceLabel('Back to conversation','Volver a la charla');back.type='button';back.addEventListener('click',()=>{if(!editorReady)close();else iframe?.contentWindow.postMessage({kind:'daimon.workshop.close'},location.origin);});const toolbar=document.createElement('nav');toolbar.className='avatar-workshop-toolbar';toolbar.setAttribute('aria-label',voiceLabel('Workshop navigation','Navegación del taller'));dialog.append(toolbar);toolbar.append(back);voiceTab=document.createElement('button');voiceTab.type='button';voiceTab.textContent=voiceLabel('Voice','Voces');voiceTab.setAttribute('aria-expanded','false');toolbar.append(voiceTab);studio=window.VoiceStudioUI?.mount({parent:dialog,api,credential});voiceTab.addEventListener('click',()=>{if(!studio)return;const opening=studio.panel.hidden;if(!opening)studio.hide();studio.panel.hidden=!opening;if(iframe)iframe.hidden=opening;voiceTab.setAttribute('aria-expanded',String(opening));voiceTab.textContent=opening?voiceLabel('Back to avatar','Volver al avatar'):voiceLabel('Voice','Voces');if(opening)studio.open();});document.body.append(dialog);dialog.addEventListener('cancel',event=>{event.preventDefault();if(!editorReady)close();else iframe?.contentWindow.postMessage({kind:'daimon.workshop.close'},location.origin);});}
   if(studio)studio.panel.hidden=true;voiceTab?.setAttribute('aria-expanded','false');if(voiceTab)voiceTab.textContent=voiceLabel('Voice','Voces');
   editorReady=false;iframe?.remove();iframe=document.createElement('iframe');iframe.title='Personalize your avatar';iframe.src=asset('experiments/school-avatar-quest/index.html');dialog.append(iframe);dialog.showModal();stop();
  });
  window.addEventListener('message',async event=>{
   if(!iframe||event.source!==iframe.contentWindow||event.origin!==location.origin)return;
   if(event.data?.kind==='daimon.workshop.ready'){editorReady=true;return;}
   if(event.data?.kind==='daimon.workshop.closed'){close();return;}
   const data=event.data;if(data?.kind!=='daimon.workshop.request'||!uuid(data.id))return;
   const target=iframe.contentWindow,selected=epoch,key=credential();
   const respond=value=>{if(selected===epoch&&target===iframe?.contentWindow&&key===credential()){
    target.postMessage({kind:'daimon.workshop.result',id:data.id,appearance:appearance(),...value},location.origin);
   }};
   if(busy){respond({error:'Esperá que termine la acción anterior.'});return;}
   busy=true;let preview;
   try{
    if(JSON.stringify(data).length>1048576||!data.args||typeof data.args!=='object')throw Error('Diseño demasiado grande.');
    const a=data.args;let value;
    if(data.action==='snapshot'&&Object.keys(a).length===0)value=await api('interaction/avatars');
    else if(data.action==='get'&&Object.keys(a).length===1&&uuid(a.id))value=await api('interaction/avatars/'+a.id);
    else if(['edit','activate'].includes(data.action)&&Object.keys(a).sort().join(',')==='generation,id'&&uuid(a.id)&&Number.isSafeInteger(a.generation)){
     if(data.action==='activate')preview=await prepared(await api('interaction/avatars/'+a.id));
     if(selected!==epoch||key!==credential())throw Error('La cuenta cambió.');
     value=await api('interaction/avatars',{action:data.action,...a});
     if(preview)use(preview);
    }else if(data.action==='save'&&Object.keys(a).sort().join(',')==='design,generation,id,parentId'&&uuid(a.id)&&Number.isSafeInteger(a.generation))value=await api('interaction/avatars',{action:'save',...a});
    else throw Error('Acción de avatar no disponible.');
    respond({value});
   }catch(error){preview?.candidate.remove();respond({error:error.message||'No recibí confirmación. Consultá las versiones sin repetir la acción.'});}
   finally{busy=false;}
  });
  pause?.addEventListener('click',()=>{paused=!paused;pause.setAttribute('aria-pressed',String(paused));icon(pause,paused?'play':'pause',paused?voiceLabel('Animate avatar','Animar avatar'):voiceLabel('Pause avatar','Pausar avatar'));run();});
  document.addEventListener('visibilitychange',run);motion.addEventListener('change',run);
  function openVoiceEntry(){
   if(!actor||!voiceEntry||voiceEntryOpened||!window.VoiceStudioUI)return;
   voiceEntryOpened=true;button.click();if(studio?.panel.hidden)voiceTab.click();
  }
  return {bind(value){if(value!==actor){reset();actor=value;}void refresh();openVoiceEntry();},reset,artisticRest};
 }
 return {mount};
})();
