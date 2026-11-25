"use strict";
// Host correlation only. No credentials, private chat text or media cross frames.
window.ConversationSurface=(()=>{
  const uuid=v=>typeof v==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(v);
  function create(){
    const {surfaceParent:parent,surfaceVisit:visit}=(document.documentElement?.dataset||{});
    if(!parent||!uuid(visit))return;
    const channel=crypto.randomUUID(),host=window.parent,tracked=new Map();
    let actor,binding,connected=false,pending,closed=false,avatarPlayback=false,machineMode=false,lastLevel,lastSpeech=0;
    const envelope=()=>({schema:'conversation.surface/v1',visit,channel,actor,binding});
    function send(type,fields={}){if(!closed&&actor&&binding&&host!==window)host.postMessage({...envelope(),type,...fields},parent);}
    function cancel(){playback(0);connected=false;avatarPlayback=false;machineMode=false;lastLevel=undefined;lastSpeech=0;if(pending){clearTimeout(pending.timer);pending.reject(Error('World connection changed. Your draft is kept.'));pending=undefined;}}
    function ready(){if(actor&&binding)send('ready',{features:{machineSource:true}});}
    function identity(value){if(actor!==value){cancel();actor=typeof value==='string'&&/^human:[A-Za-z0-9:._/-]{1,240}$/.test(value)?value:undefined;ready();}}
    function bind(value){if(binding!==value){cancel();binding=/^[a-f0-9]{64}$/.test(value||'')?value:undefined;ready();}}
    function receive(event){
      const d=event.data;
      let size;try{size=JSON.stringify(d)?.length;}catch{return;}
      if(closed||event.source!==host||event.origin!==parent||!d||typeof d!=='object'
          ||!size||size>8192||Object.entries(envelope()).some(([k,v])=>!v||d[k]!==v))return;
      if(d.type==='connect'){
        avatarPlayback=d.features?.avatarPlayback===true;
        if(!connected){connected=true;machineMode=d.features?.machineSource==='owner-journal/v1';}
        return;
      }
      if(!connected||!pending||d.request!==pending.request||d.id!==pending.id)return;
      if(d.type==='error'){const old=pending;pending=undefined;clearTimeout(old.timer);old.reject(Error('World context could not be prepared. Your draft is kept.'));return;}
      if(d.type!=='prepared')return;
      const f=d.file;
      if(pending.machine){if(f!==undefined||!uuid(d.machine_source))return;}
      else if(d.machine_source!==undefined||!f||Object.keys(f).sort().join(',')!=='file_id,mime,name,sha256,size'||!uuid(f.file_id)
          ||!/^[a-f0-9]{64}$/.test(f.sha256||'')||f.name!=='holodeck-situation.json'||f.mime!=='application/json'
          ||!Number.isSafeInteger(f.size)||f.size<1||f.size>65536)return;
      const old=pending;pending=undefined;clearTimeout(old.timer);
      if(tracked.get(old.id)?.discarded)return;
      old.resolve(old.machine?{machine_source:d.machine_source}:{file:{...f}});
    }
    window.addEventListener('message',receive);
    async function prepare({id,binding:selected,modality,files=[],reply}){
      if(closed||!connected||pending||!uuid(id)||selected!==binding||!['text','audio'].includes(modality))throw Error('Connect to the world before sending. Your draft is kept.');
      const count=files.length,total=files.reduce((n,f)=>n+f.size,0);
      const machine=machineMode;
      if(machine&&reply?.source?.startsWith('request:')&&!reply.context_only)return [];
      if(count>(machine?8:7)||total>40*1024*1024-(machine?0:65536))throw Error('This message has too many attachments or exceeds 40 MiB.');
      const request=crypto.randomUUID();
      if(tracked.has(id))throw Error('This original already has a context preparation. Keep its saved status.');
      tracked.set(id,{binding:selected,actor,attempted:false,discarded:false});
      while(tracked.size>128)tracked.delete(tracked.keys().next().value);
      const source=await new Promise((resolve,reject)=>{
        pending={id,request,machine,resolve,reject,timer:setTimeout(()=>{if(pending?.request===request){pending=undefined;reject(Error('World context was not confirmed. Your draft is kept; nothing was sent.'));}},30000)};
        send('prepare',{id,request,modality,capacity:{files:8-count,bytes:40*1024*1024-total,context_bytes:65536},
          ...(machine?{mode:'owner-journal/v1'}:{})});
      });
      if(selected!==binding||!connected)throw Error('World connection changed. Your draft is kept.');
      return machine?source:[...files,source.file];
    }
    function playback(value){
      if(!connected||!avatarPlayback)return;
      const level=document.hidden||!Number.isFinite(value)?0:Math.round(Math.min(1,Math.max(0,value))*4)/4;
      const now=performance.now();
      if(level===lastLevel&&(!level||now-lastSpeech<120))return;
      if(level&&lastLevel&&now-lastSpeech<50)return;
      lastLevel=level;lastSpeech=now;
      send('avatar-playback',{level});
    }
    document.addEventListener('visibilitychange',()=>{if(document.hidden)playback(0);});
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
    return {identity,bind,prepare,status,attempt,discard,playback,disconnect:()=>{cancel();actor=undefined;binding=undefined;},
      get reservedFiles(){return machineMode?0:1;},get reservedBytes(){return machineMode?0:65536;}};
  }

  // The same authenticated Conversation origin owns both copies. The parent
  // never receives draft text or a reason to create original work.
  function mountDraft({field,api,busy,show,check}){
    const slot='daimon-conversation-draft/v1',ttl=7*86400000;
    const scope=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
    const textOK=text=>typeof text==='string' && !text.includes('\0') && new TextEncoder().encode(text).length<=32768;
    const bufferOK=text=>typeof text==='string' && text.length<=65536;
    const valid=value=>value&&Number.isSafeInteger(value.revision)&&value.revision>=0&&textOK(value.text);
    let current,timer;
    function buffers(){
      try{const values=JSON.parse(window.sessionStorage.getItem(slot));return Array.isArray(values)?values.filter(v=>v&&Date.now()-v.at<ttl):[];}
      catch{return [];}
    }
    function persist(s){
      try{window.sessionStorage.setItem(slot,JSON.stringify([{key:s.key,at:Date.now(),text:s.text,base:s.base,dirty:s.dirty,pending:s.pending},
        ...buffers().filter(v=>v.key!==s.key).slice(0,3)]));}catch{}
    }
    function render(s){
      if(current!==s || busy())return;
      if(field.value!==s.text)field.value=s.text;
      const pending=s.pending?.text===s.text;
      show(pending?'unconfirmed':s.conflict?'conflict':'',pending?()=>checkPending(s):()=>choose(s,true),()=>choose(s,false));
    }
    function bind(owner,binding){
      const key=scope(owner)&&scope(binding)?owner+'|'+binding:undefined;
      if(key===current?.key)return;
      clearTimeout(timer);
      if(current){field.value='';show('');}
      current=undefined;
      if(!key)return;
      const saved=buffers().find(v=>v.key===key);
      const s={key,binding,text:'',base:0,dirty:false};
      if(saved&&Number.isSafeInteger(saved.base)&&saved.base>=0&&bufferOK(saved.text)){
        Object.assign(s,{text:saved.text,base:saved.base,dirty:saved.dirty===true,
          pending:uuid(saved.pending?.id)&&textOK(saved.pending?.text)?saved.pending:undefined});
      }
      current=s;render(s);
      if(s.pending)void checkPending(s);
    }
    function pulse(s){
      clearTimeout(timer);
      if(!s.remote||!s.dirty||s.conflict||s.posting||s.pending?.text===s.text||!textOK(s.text))return;
      timer=setTimeout(async()=>{
        if(current!==s || s.posting)return;
        const sent=s.text,revision=s.base;
        s.posting=true;
        try{
          const result=await api('interaction/draft',{binding:s.binding,revision,text:sent});
          if(current!==s||!valid(result))return;
          if(result.text===sent){s.base=result.revision;s.dirty=s.text!==sent;}
          observe(result);
        }catch{/* The local buffer stays; the next observation reconciles the same revision. */}
        finally{s.posting=false;if(current===s&&s.text!==sent)pulse(s);}
      },650);
    }
    function observe(value){
      const s=current;if(!s)return;
      if(valid(value)&&(!s.remote||value.revision>=s.remote.revision)){
        s.remote=value;
        if(!s.dirty){s.text=value.text;s.base=value.revision;s.conflict=false;}
        else if(!s.posting||s.base===value.revision){s.conflict=value.revision!==s.base&&value.text!==s.text;
          if(value.text===s.text){s.base=value.revision;s.dirty=false;}}
        persist(s);
      }
      render(s);pulse(s);
    }
    function choose(s,keep){
      if(s!==current||!s.remote||busy())return;
      if(!keep)s.text=s.remote.text;
      s.base=s.remote.revision;s.dirty=keep&&s.text!==s.remote.text;s.conflict=false;persist(s);render(s);pulse(s);
    }
    function change(text){
      const s=current;if(!s||!bufferOK(text))return;
      s.text=text;s.dirty=true;persist(s);pulse(s);
    }
    function attempt(id,text){const s=current;if(s&&textOK(text)){s.pending={id,text};persist(s);}}
    function confirm(value){
      const s=current;if(!s||!s.pending||value?.id!==s.pending.id||value.binding!==s.binding||!value.phase||value.phase==='reselection')return;
      if(s.text===s.pending.text){s.text='';s.dirty=true;}
      s.pending=undefined;persist(s);render(s);pulse(s);
    }
    async function checkPending(s){
      if(s!==current||!s.pending||s.checking)return;
      s.checking=true;
      try{const value=await check(s.pending.id);if(current===s)confirm(value);}
      catch{/* An absent or unknown receipt must not repeat the input. */}
      finally{s.checking=false;render(s);}
    }
    function unsent(id){
      const s=current;if(s?.pending?.id!==id)return;
      s.pending=undefined;persist(s);render(s);pulse(s);
    }
    return {bind,observe,change,attempt,confirm,unsent,isUnconfirmed:text=>current?.pending?.text===text};
  }
  return {create,mountDraft};
})();
