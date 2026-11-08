"use strict";
/* Explicit Android offer -> editable draft only. No fetch, upload or Send. */
window.NativeSharedText=(()=>{
 const bridge=window.DaimonAudio;if(!bridge?.postMessage)return;
 let offer,view;let epoch=0,reading=false;const resolved=new Set();
 const settle=id=>{resolved.add(id);if(resolved.size>16)resolved.delete(resolved.values().next().value);ack(id);};
 const ack=id=>bridge.postMessage(JSON.stringify({command:'share_ack',id}));
 function refresh(){view?.refresh();}
 function receive(value){
  if(!value||typeof value.id!=='string'||!/^[a-f0-9-]{36}$/.test(value.id)||typeof value.text!=='string'||(!value.text.trim()&&!(value.fileCount>0))||new TextEncoder().encode(value.text).length>12000)return;
  if(value.fileCount!==undefined&&(!Number.isInteger(value.fileCount)||value.fileCount<0||value.fileCount>8))return;
  if(resolved.has(value.id)){ack(value.id);return;}
  if(offer){if(offer.id!==value.id||offer.text!==value.text||offer.fileCount!==(value.fileCount||0))return;if(typeof value.binding==='string')offer.binding=value.binding;}else offer={id:value.id,text:value.text,fileCount:value.fileCount||0,binding:typeof value.binding==='string'?value.binding:undefined,requested:false};refresh();
 }
 function mount({parent,draft,onFiles,getBinding,isBusy=()=>false}){
  if(view)return view;
  const es=(navigator.language||'').startsWith('es'),say=(en,spanish)=>es?spanish:en;
  const box=document.createElement('section'),title=document.createElement('p'),preview=document.createElement('pre'),add=document.createElement('button'),discard=document.createElement('button');
  box.className='native-share-offer';box.setAttribute('aria-label',say('Shared content','Contenido compartido'));box.hidden=true;
  title.textContent=say('Shared with Daimon. Review it before sending.','Compartido con Daimon. Revisalo antes de enviar.');
  preview.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;max-height:8em;overflow:auto';
  for(const b of [add,discard])b.type='button';add.textContent=say('Add to message','Agregar al mensaje');discard.textContent=say('Discard share','Descartar lo compartido');
  box.append(title,preview,add,discard);parent.before(box);
  const picker=document.createElement('input');picker.type='file';picker.multiple=true;picker.hidden=true;box.append(picker);let selection;
  const ready=()=>!!getBinding()&&!draft.disabled;
  view={refresh(){
   box.hidden=true;preview.textContent='';if(!offer||!ready())return;
   const binding=getBinding();if(offer.binding!==binding){
    if(!offer.binding&&!offer.requested){offer.requested=true;bridge.postMessage(JSON.stringify({command:'share_bind',id:offer.id,binding}));}
    return;
   }
   box.hidden=false;preview.textContent=offer.text+(offer.fileCount?`\n${offer.fileCount} ${say('files','archivos')}`:'');add.disabled=isBusy()||reading;discard.disabled=reading;
  },reset(){epoch++;selection=undefined;reading=false;box.hidden=true;preview.textContent='';picker.value='';}};
  const current=own=>own&&own.epoch===epoch&&offer===own.offer&&ready()&&getBinding()===own.binding&&!isBusy();
  function commit(own){
   if(!current(own))return;
   if(own.offer.text){draft.value+=(draft.value?'\n':'')+own.offer.text;draft.dispatchEvent(new Event('input',{bubbles:true}));draft.focus();}
   offer=undefined;reading=false;selection=undefined;refresh();settle(own.offer.id);
  }
  picker.addEventListener('change',async()=>{
   const own=selection;if(!current(own)){picker.value='';return;}
   const files=Array.from(picker.files||[]);if(!files.length){reading=false;refresh();return;}
   reading=true;refresh();
   try{
    if(files.length!==own.offer.fileCount||typeof onFiles!=='function')throw Error(say('Shared files are unavailable. Nothing was added.','Los archivos no están disponibles. No se agregó nada.'));
    await onFiles(files);commit(own);
   }catch(error){if(current(own))title.textContent=error.message||say('Files could not be added.','No se pudieron agregar los archivos.');}
   finally{if(own.epoch===epoch){reading=false;selection=undefined;picker.value='';refresh();}}
  });
  add.addEventListener('click',()=>{
   if(!offer||!ready()||offer.binding!==getBinding()||isBusy()||reading)return;
   const own={offer,binding:getBinding(),epoch};
   if(offer.fileCount){selection=own;picker.accept='application/x-daimon-share-'+offer.id;picker.click();}
   else commit(own);
  });
  discard.addEventListener('click',()=>{if(!offer||!ready()||offer.binding!==getBinding())return;const id=offer.id;offer=undefined;refresh();settle(id);});
  refresh();return view;
 }
 return {receive,mount,refresh};
})();
