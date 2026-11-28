"use strict";
// Host correlation only. No credentials, private chat text or media cross frames.
window.ConversationSurface=(()=>{
  const uuid=v=>typeof v==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(v);
  const topicKey=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
  function create({readTopics}={}){
    const {surfaceParent:parent,surfaceVisit:visit}=(document.documentElement?.dataset||{});
    if(!parent||!uuid(visit))return;
    const channel=crypto.randomUUID(),host=window.parent,tracked=new Map();
    let actor,binding,connected=false,pending,closed=false,avatarPlayback=false,lastLevel,lastSpeech=0;
    let topicsEnabled=false,topicRead;
    let avatarMicrophone=false,lastMicLevel=0,lastMicAt=-Infinity,microphoneGeneration=0;
    const envelope=()=>({schema:'conversation.surface/v1',visit,channel,actor,binding});
    function send(type,fields={}){if(!closed&&actor&&binding&&host!==window)host.postMessage({...envelope(),type,...fields},parent);}
    function cancel(){playback(0);microphone(0);microphoneGeneration++;connected=false;topicsEnabled=false;topicRead=undefined;avatarMicrophone=false;lastMicAt=-Infinity;avatarPlayback=false;lastLevel=undefined;lastSpeech=0;if(pending){clearTimeout(pending.timer);pending.reject(Error('World connection changed. Your draft is kept.'));pending=undefined;}}
    function ready(){if(actor&&binding)send('ready',{features:{avatarMicrophone:true,...(readTopics?{topicRooms:true}:{})}});}
    function identity(value){if(actor!==value){cancel();actor=typeof value==='string'&&/^human:[A-Za-z0-9:._/-]{1,240}$/.test(value)?value:undefined;ready();}}
    function bind(value){if(binding!==value){cancel();binding=/^[a-f0-9]{64}$/.test(value||'')?value:undefined;ready();}}
    function receive(event){
      const d=event.data;
      let size;try{size=JSON.stringify(d)?.length;}catch{return;}
      if(closed||event.source!==host||event.origin!==parent||!d||typeof d!=='object'
          ||!size||size>8192||Object.entries(envelope()).some(([k,v])=>!v||d[k]!==v))return;
      if(d.type==='connect'){
        if(d.features?.avatarMicrophone!==true)microphone(0);
        connected=true;
        topicsEnabled=!!readTopics&&d.features?.topicRooms===true;
        avatarPlayback=d.features?.avatarPlayback===true;
        avatarMicrophone=d.features?.avatarMicrophone===true;
        return;
      }
      if(d.type==='topic-rooms-read'){
        if(connected&&topicsEnabled)void projectRooms(d);
        return;
      }
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
    async function projectRooms({request,room,after}){
      if(!uuid(request)||topicRead||room!==undefined&&!topicKey(room)||
         after!==undefined&&!topicKey(after)||room!==undefined&&after!==undefined)return;
      const read={request};topicRead=read;
      const current=()=>topicRead===read&&connected&&topicsEnabled;
      try{
        const value=await readTopics(room);
        if(!current())return;
        if(value?.schema!=='daimon.topic-rooms/v1'||!Array.isArray(value.rooms)||value.rooms.length>128)
          throw Error('Topic catalogue unavailable');
        const rows=value.rooms.map(item=>{
          if(!topicKey(item?.room)||typeof item.title!=='string'||typeof item.general!=='boolean'||
             typeof item.direct_available!=='boolean')throw Error('Invalid topic room');
          const title=Array.from(item.title.replace(/[\u0000-\u001f\u007f]/g,' ').trim()).slice(0,80).join('');
          return {room:item.room,title,general:item.general,direct_available:item.direct_available};
        }).sort((a,b)=>a.room.localeCompare(b.room));
        if(new Set(rows.map(item=>item.room)).size!==rows.length||
           room!==undefined&&(rows.length!==1||rows[0].room!==room))throw Error('Topic room unavailable');
        const page=rows.filter(item=>after===undefined||item.room>after);
        send('topic-rooms-readback',{request,rooms:page.slice(0,12),next:page.length>12?page[11].room:null});
      }catch{
        if(current())send('topic-rooms-readback',{request,unavailable:true});
      }finally{
        if(current())topicRead=undefined;
      }
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
    function playback(value){
      if(!connected||!avatarPlayback)return;
      const level=document.hidden||!Number.isFinite(value)?0:Math.round(Math.min(1,Math.max(0,value))*4)/4;
      const now=performance.now();
      if(level===lastLevel&&(!level||now-lastSpeech<120))return;
      if(level&&lastLevel&&now-lastSpeech<50)return;
      lastLevel=level;lastSpeech=now;
      send('avatar-playback',{level});
    }
    // Fresh levels only, from the recorder callback. UI snapshots can retain
    // a previous level and must never refresh its presentation lifetime.
    function microphone(value){
      if(!connected||!avatarMicrophone)return;
      const level=document.hidden||!Number.isFinite(value)?0:Math.round(Math.min(1,Math.max(0,value))*4)/4;
      const now=performance.now();
      if(level ? now-lastMicAt<100 : !lastMicLevel)return;
      lastMicLevel=level;
      if(level)lastMicAt=now;
      send('avatar-microphone',{level});
    }
    function microphoneSink(selected){
      if(!selected||selected!==binding)return;
      const capture=microphoneGeneration;
      return value=>{if(capture===microphoneGeneration&&selected===binding)microphone(value);};
    }
    document.addEventListener('visibilitychange',()=>{if(document.hidden){playback(0);microphone(0);}});
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
    return {identity,bind,prepare,status,attempt,discard,playback,microphoneSink,silenceMicrophone:()=>microphone(0),disconnect:()=>{cancel();actor=undefined;binding=undefined;},reservedFiles:1,reservedBytes:65536};
  }

  // The same authenticated Conversation origin owns both copies. The parent
  // never receives draft text or a reason to create original work.
  function mountDraft({field,api,busy,show,check,retry}){
    const slot='daimon-conversation-draft/v1',ttl=7*86400000;
    const scope=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
    const textOK=text=>typeof text==='string' && !text.includes('\0') && new TextEncoder().encode(text).length<=32768;
    const bufferOK=text=>typeof text==='string' && text.length<=65536;
    const valid=value=>value&&Number.isSafeInteger(value.revision)&&value.revision>=0&&textOK(value.text);
    const exactOriginal=(pending,binding)=>pending.original?.id===pending.id
      && pending.original.binding===binding && pending.original.text===pending.text
      && JSON.stringify(pending.original).length<=262144;
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
      const pending=!!s.pending;
      show(pending?'unconfirmed':s.conflict?'conflict':'',pending?()=>checkPending(s):()=>choose(s,true),
        pending?(s.pending.original?()=>checkPending(s,true):undefined):()=>choose(s,false));
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
        Object.assign(s,{text:saved.text,base:saved.base,dirty:saved.dirty===true});
        if(uuid(saved.pending?.id)&&textOK(saved.pending?.text)){
          const {id,text,original}=saved.pending;
          s.pending=exactOriginal(saved.pending,binding)?{id,text,original}:{id,text};
        }
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
    function attempt(original){
      const s=current;
      if(!s||!uuid(original.id)||!textOK(original.text)||original.binding!==s.binding)return;
      s.pending={id:original.id,text:original.text,original};
      if(!exactOriginal(s.pending,s.binding))delete s.pending.original;
      persist(s);
    }
    function confirm(value){
      const s=current;if(!s||!s.pending||value?.id!==s.pending.id||value.binding!==s.binding||!value.phase||value.phase==='reselection')return;
      if(s.text===s.pending.text){s.text='';s.dirty=true;}
      s.pending=undefined;persist(s);render(s);pulse(s);
    }
    async function checkPending(s,sendAgain=false){
      if(s!==current||!s.pending||s.checking)return;
      s.checking=true;
      try{
        const {id,original,text}=s.pending;
        const value=sendAgain&&original?await retry(original):await check(id,text);
        if(current===s)confirm(value);
      }
      catch{/* An absent or unknown receipt must not repeat the input. */}
      finally{s.checking=false;render(s);}
    }
    function unsent(id){
      const s=current;if(s?.pending?.id!==id)return;
      s.pending=undefined;persist(s);render(s);pulse(s);
    }
    return {bind,observe,change,attempt,confirm,unsent,
      hasUnconfirmed:text=>!!current?.pending&&(!!current.pending.original||current.pending.text===text),
      lockedText:()=>current?.pending?.original&&current.pending.text===current.text?current.pending.text:undefined};
  }
  return {create,mountDraft};
})();
