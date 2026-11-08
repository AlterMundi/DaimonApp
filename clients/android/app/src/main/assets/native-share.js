"use strict";
/* Explicit Android offer -> editable draft only. No fetch, upload or Send. */
window.NativeSharedText=(()=>{
 const bridge=window.DaimonAudio;if(!bridge?.postMessage)return;
 let offer,view;const resolved=new Set();
 const settle=id=>{resolved.add(id);if(resolved.size>16)resolved.delete(resolved.values().next().value);ack(id);};
 const ack=id=>bridge.postMessage(JSON.stringify({command:'share_ack',id}));
 function refresh(){view?.refresh();}
 function receive(value){
  if(!value||typeof value.id!=='string'||!/^[a-f0-9-]{36}$/.test(value.id)||typeof value.text!=='string'||!value.text.trim()||new TextEncoder().encode(value.text).length>12000)return;
  if(resolved.has(value.id)){ack(value.id);return;}
  if(offer&&offer.id!==value.id)return;offer={id:value.id,text:value.text,binding:typeof value.binding==='string'?value.binding:undefined,requested:false};refresh();
 }
 function mount({parent,draft,getBinding,isBusy=()=>false}){
  if(view)return view;
  const es=(navigator.language||'').startsWith('es'),say=(en,spanish)=>es?spanish:en;
  const box=document.createElement('section'),title=document.createElement('p'),preview=document.createElement('pre'),add=document.createElement('button'),discard=document.createElement('button');
  box.className='native-share-offer';box.setAttribute('aria-label',say('Shared content','Contenido compartido'));box.hidden=true;
  title.textContent=say('Shared with Daimon. Review it before sending.','Compartido con Daimon. Revisalo antes de enviar.');
  preview.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;max-height:8em;overflow:auto';
  for(const b of [add,discard])b.type='button';add.textContent=say('Add to message','Agregar al mensaje');discard.textContent=say('Discard share','Descartar lo compartido');
  box.append(title,preview,add,discard);parent.before(box);
  const ready=()=>!!getBinding()&&!draft.disabled;
  view={refresh(){
   box.hidden=true;preview.textContent='';if(!offer||!ready())return;
   const binding=getBinding();if(offer.binding!==binding){
    if(!offer.binding&&!offer.requested){offer.requested=true;bridge.postMessage(JSON.stringify({command:'share_bind',id:offer.id,binding}));}
    return;
   }
   box.hidden=false;preview.textContent=offer.text;add.disabled=isBusy();
  },reset(){box.hidden=true;preview.textContent='';}};
  add.addEventListener('click',()=>{
   if(!offer||!ready()||offer.binding!==getBinding()||isBusy())return;const selected=offer,binding=getBinding();
   const value=draft.value+(draft.value?'\n':'')+selected.text;
   if(binding!==getBinding()||!ready())return;
   draft.value=value;draft.dispatchEvent(new Event('input',{bubbles:true}));draft.focus();
   offer=undefined;refresh();settle(selected.id);
  });
  discard.addEventListener('click',()=>{if(!offer||!ready()||offer.binding!==getBinding())return;const id=offer.id;offer=undefined;refresh();settle(id);});
  refresh();return view;
 }
 return {receive,mount,refresh};
})();
