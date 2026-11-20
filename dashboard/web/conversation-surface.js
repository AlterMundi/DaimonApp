"use strict";
// Host correlation only. No credentials, private chat text or media cross frames.
window.ConversationSurface=(()=>{
  const uuid=v=>typeof v==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(v);
  function create(){
    const {surfaceParent:parent,surfaceVisit:visit}=(document.documentElement?.dataset||{});
    if(!parent||!uuid(visit))return;
    const channel=crypto.randomUUID(),host=window.parent,tracked=new Map();
    let actor,binding,connected=false,pending,closed=false;
    const envelope=()=>({schema:'conversation.surface/v1',visit,channel,actor,binding});
    function send(type,fields={}){if(!closed&&actor&&binding&&host!==window)host.postMessage({...envelope(),type,...fields},parent);}
    function cancel(){connected=false;if(pending){clearTimeout(pending.timer);pending.reject(Error('World connection changed. Your draft is kept.'));pending=undefined;}}
    function ready(){if(actor&&binding)send('ready');}
    function identity(value){if(actor!==value){cancel();actor=typeof value==='string'&&/^human:[A-Za-z0-9:._/-]{1,240}$/.test(value)?value:undefined;ready();}}
    function bind(value){if(binding!==value){cancel();binding=/^[a-f0-9]{64}$/.test(value||'')?value:undefined;ready();}}
    function receive(event){
      const d=event.data;
      let size;try{size=JSON.stringify(d)?.length;}catch{return;}
      if(closed||event.source!==host||event.origin!==parent||!d||typeof d!=='object'
          ||!size||size>8192||Object.entries(envelope()).some(([k,v])=>!v||d[k]!==v))return;
      if(d.type==='connect'){connected=true;return;}
      if(!connected||!pending||d.request!==pending.request||d.id!==pending.id)return;
      if(d.type==='error'){const old=pending;pending=undefined;clearTimeout(old.timer);old.reject(Error('World context could not be prepared. Your draft is kept.'));return;}
      if(d.type!=='prepared')return;
      const f=d.file;
      if(!f||Object.keys(f).sort().join(',')!=='file_id,mime,name,sha256,size'||!uuid(f.file_id)
          ||!/^[a-f0-9]{64}$/.test(f.sha256||'')||f.name!=='holodeck-situation.json'||f.mime!=='application/json'
          ||!Number.isSafeInteger(f.size)||f.size<1||f.size>65536)return;
      const old=pending;pending=undefined;clearTimeout(old.timer);
      if(tracked.get(old.id)?.discarded)return;
      old.resolve({...f});
    }
    window.addEventListener('message',receive);
    async function prepare({id,binding:selected,modality,files=[]}){
      if(closed||!connected||pending||!uuid(id)||selected!==binding||!['text','audio'].includes(modality))throw Error('Connect to the world before sending. Your draft is kept.');
      const count=files.length,total=files.reduce((n,f)=>n+f.size,0);
      if(count>7||total>40*1024*1024-65536)throw Error('Leave room for the world context: at most seven files and 40 MiB total.');
      const request=crypto.randomUUID();
      if(tracked.has(id))throw Error('This original already has a context preparation. Keep its saved status.');
      tracked.set(id,{binding:selected,actor,attempted:false,discarded:false});
      while(tracked.size>128)tracked.delete(tracked.keys().next().value);
      const file=await new Promise((resolve,reject)=>{
        pending={id,request,resolve,reject,timer:setTimeout(()=>{if(pending?.request===request){pending=undefined;reject(Error('World context was not confirmed. Your draft is kept; nothing was sent.'));}},30000)};
        send('prepare',{id,request,modality,capacity:{files:8-count,bytes:40*1024*1024-total,context_bytes:65536}});
      });
      if(selected!==binding||!connected)throw Error('World connection changed. Your draft is kept.');
      return [...files,file];
    }
    function current(value){const record=tracked.get(value?.id);return record&&record.binding===binding&&record.actor===actor&&(!value.binding||value.binding===record.binding)?record:undefined;}
    function attempt(value){const record=current(value);if(record)record.attempted=true;}
    function discard(value){
      const record=current(value);
      if(!record||record.attempted||record.discarded||!['capture-cancelled','preparation-failed'].includes(value.reason))return;
      record.discarded=true;
      send('discard',{id:value.id,reason:value.reason});
      if(pending?.id===value.id){const old=pending;pending=undefined;clearTimeout(old.timer);old.reject(Error('Recording cancelled. Your draft is kept.'));}
    }
    function status(value,busy){if(current(value)&&!current(value).discarded)send('status',{id:value.id,phase:typeof value.phase==='string'?value.phase.slice(0,64):'unconfirmed',busy:busy===undefined?!['accepted','queued','completed','routed','foreground','matrix_requested'].includes(value.phase):!!busy});}
    window.addEventListener('pagehide',()=>{cancel();closed=true;window.removeEventListener('message',receive);});
    window.addEventListener('pageshow',event=>{if(event.persisted&&closed){closed=false;window.addEventListener('message',receive);ready();}});
    return {identity,bind,prepare,status,attempt,discard,disconnect:()=>{cancel();actor=undefined;binding=undefined;},reservedFiles:1,reservedBytes:65536};
  }
  return {create};
})();
