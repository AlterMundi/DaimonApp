"use strict";
window.AvatarWorkshopUI=(()=>{
 function mount({api,headers}){
  const button=document.querySelector('#avatar-workshop-open'),portrait=document.querySelector('#conversation-companion pre');
  if(!button||!portrait)return;
  button.hidden=false;
  let actor,epoch=0,loaded=false,busy=false,editorReady=false,dialog,iframe,studio,voiceTab,canvas,paint,frame=0,timer,paused=false;
  const motion=matchMedia('(prefers-reduced-motion: reduce)'),asset=path=>new URL('assets/avatar-workshop/'+path,document.baseURI).href;
  const resize=new ResizeObserver(()=>{try{paint?.(frame);}catch{stop();message('Avatar drawing paused. Your saved selection is kept.');}});
  const uuid=value=>typeof value==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value);
  const credential=()=>JSON.stringify(headers());
  function appearance(){const style=getComputedStyle(document.body),value={};for(const role of ['background','surface','text','accent','body-font','heading-font','radius','gap']){const v=style.getPropertyValue('--dm-'+role).trim();if(v&&v.length<256&&!/url\(/i.test(v))value['--dm-'+role]=v;}return value;}
  window.addEventListener('home-style:resolved',()=>iframe?.contentWindow.postMessage({kind:'daimon.workshop.appearance',appearance:appearance()},location.origin));
  const message=text=>{const line=document.querySelector('#avatar-workshop-status');if(line)line.textContent=text;};
  function stop(){clearTimeout(timer);timer=undefined;}
  function run(){stop();if(!paint||paused||motion.matches||document.hidden||dialog?.open)return;timer=setTimeout(()=>{try{paint(frame=(frame+1)%12);run();}catch{stop();message('Avatar animation paused. Your saved selection is kept.');}},180);}
  function reset(){epoch++;studio?.reset();loaded=false;stop();resize.disconnect();canvas?.remove();canvas=paint=undefined;portrait.hidden=false;document.querySelector('#avatar-workshop-pause')?.setAttribute('hidden','');if(dialog?.open)dialog.close();iframe?.remove();iframe=undefined;}
  async function prepared(record){
   const selected=epoch,key=credential(),renderer=await import(asset('renderer.mjs'));
   if(selected!==epoch||key!==credential())throw Error('Avatar account changed');
   const candidate=document.createElement('canvas');candidate.className='workshop-portrait';candidate.setAttribute('role','img');candidate.setAttribute('aria-label',record.name||'Your chosen avatar');
   candidate.style.visibility='hidden';portrait.before(candidate);
   try{const render=renderer.prepare(candidate,record.design);return {candidate,render,selected,key};}catch(error){candidate.remove();throw error;}
  }
  function use(preview){
   if(preview.selected!==epoch||preview.key!==credential()){preview.candidate.remove();throw Error('Avatar account changed');}
   stop();resize.disconnect();canvas?.remove();canvas=preview.candidate;paint=preview.render;canvas.style.visibility='';portrait.hidden=true;document.querySelector('#avatar-workshop-pause')?.removeAttribute('hidden');frame=0;resize.observe(canvas);run();
  }
  async function refresh(){
   if(loaded||!actor)return;loaded=true;const selected=epoch,key=credential();
   try{const state=await api('interaction/avatars');if(selected!==epoch||key!==credential())return;if(state.active){const record=await api('interaction/avatars/'+state.active);if(selected!==epoch||key!==credential())return;use(await prepared(record));}}
   catch{if(selected===epoch)message('Your previous avatar is kept. Open the workshop to retry.');}
  }
  function close(){if(studio&&!studio.mayClose())return;if(dialog?.open)dialog.close();iframe?.remove();iframe=undefined;button.focus();run();}
  button.addEventListener('click',()=>{
   if(!actor)return;
   if(!dialog){dialog=document.createElement('dialog');dialog.className='avatar-workshop-dialog';dialog.setAttribute('aria-label','Avatar workshop');const back=document.createElement('button');back.textContent='Back to conversation';back.type='button';back.addEventListener('click',()=>{if(!editorReady)close();else iframe?.contentWindow.postMessage({kind:'daimon.workshop.close'},location.origin);});dialog.append(back);voiceTab=document.createElement('button');voiceTab.type='button';voiceTab.textContent='Voice';voiceTab.setAttribute('aria-expanded','false');dialog.append(voiceTab);studio=window.VoiceStudioUI?.mount({parent:dialog,api,credential});voiceTab.addEventListener('click',()=>{if(!studio)return;const opening=studio.panel.hidden;if(!opening)studio.hide();studio.panel.hidden=!opening;if(iframe)iframe.hidden=opening;voiceTab.setAttribute('aria-expanded',String(opening));voiceTab.textContent=opening?'Back to avatar':'Voice';if(opening)studio.open();});document.body.append(dialog);dialog.addEventListener('cancel',event=>{event.preventDefault();if(!editorReady)close();else iframe?.contentWindow.postMessage({kind:'daimon.workshop.close'},location.origin);});}
   if(studio)studio.panel.hidden=true;voiceTab?.setAttribute('aria-expanded','false');if(voiceTab)voiceTab.textContent='Voice';
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
  const pause=document.querySelector('#avatar-workshop-pause');
  pause?.addEventListener('click',()=>{paused=!paused;pause.setAttribute('aria-pressed',String(paused));pause.textContent=paused?'Animate avatar':'Pause avatar';run();});
  document.addEventListener('visibilitychange',run);motion.addEventListener('change',run);
  return {bind(value){if(value!==actor){reset();actor=value;}void refresh();},reset};
 }
 return {mount};
})();
