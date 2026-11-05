// Actual workspace module with a bounded DOM/network fixture. No providers.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element{
  constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.attrs={};this.events={};this.hidden=false;this.disabled=false;this._text='';this.scrollTop=0;this.scrollHeight=100;this.clientHeight=100;}
  set textContent(text){this._text=String(text);this.children=[];}get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}
  setAttribute(key,value){this.attrs[key]=String(value);}addEventListener(key,fn){this.events[key]=fn;}
  append(...children){for(const child of children){child.remove();child.parentNode=this;this.children.push(child);}}
  insertBefore(child,before){child.remove();child.parentNode=this;const at=this.children.indexOf(before);this.children.splice(at<0?this.children.length:at,0,child);}
  replaceChildren(...children){for(const child of [...this.children])child.remove();this._text='';this.append(...children);}
  before(child){this.parentNode.insertBefore(child,this);}
  remove(){if(this.parentNode){const at=this.parentNode.children.indexOf(this);if(at>=0)this.parentNode.children.splice(at,1);this.parentNode=undefined;}}
  click(){if(!this.disabled)return this.events.click?.();}
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function boot(options={}){
  const document={createElement:tag=>new Element(tag)},window={},root=new Element('main'),timeline=new Element('div');root.append(timeline);
  if(options.storage)window.localStorage={getItem:key=>options.storage.get(key)||null,setItem:(key,value)=>options.storage.set(key,value),removeItem:key=>options.storage.delete(key)};
  const reference=(n,revision='a')=>({source:`session:${n}`,revision:revision.repeat(64)});
  const row=(id,title,n)=>({id,title,audio_key:`100:${n}`,destination:reference(n),latest_reply:{...reference(n),source:`session:${n}/42`},fresh:true,execution:'idle',goal_state:'absent'});
  let sessions=[row('b','Busy work',7),row('a','Earlier work',8),{...row('entry','Conversation',1),is_entry:true,destination:null,latest_reply:null}],deny=false,held;
  if(options.ids)sessions.forEach((row,n)=>row.id=options.ids[n]);
  const reads=[],targets=[],replies=[],audioCalls=[],mutes=new Set(),solos=new Set();
  async function api(route){
    reads.push(route);
    if(deny)throw Object.assign(Error('No workspace'),{status:403});
    if(route==='interaction/sessions')return {schema:'daimon.session-workspace/v1',sessions,preferred_session:options.preferred};
    const url=new URL(route,'https://fixture.invalid');
    if(held){const hold=held;held=undefined;return hold;}
    return {schema:'daimon.session-view/v1',revision:'f'.repeat(64),items:[{kind:'message',role:'assistant',text:'Retained answer',id:url.pathname,position:50,next_position:150,timestamp:'2026-11-05T01:00:00Z',next:15,more:false}],before:50,after:150,has_earlier:false,more:false};
  }
  vm.runInNewContext(fs.readFileSync('dashboard/web/session-workspace.js','utf8'),{window,document,URLSearchParams,Map,Set,JSON,Number,Error});
  const control=window.SessionWorkspace.mount({timeline,api,onTarget:()=>targets.push(true),onReply:(ref,title)=>replies.push({ref,title}),
    audio:row=>({muted:mutes.has(row.id),solo:solos.has(row.id),filtered:mutes.size+solos.size>0}),
    onAudio:(action,row)=>{audioCalls.push([action,row?.id]);if(action==='mute'){if(mutes.has(row.id))mutes.delete(row.id);else mutes.add(row.id);}if(action==='reset')mutes.clear();control.syncAudio();}});
  const all=()=>{const result=[];const visit=n=>{result.push(n);n.children.forEach(visit);};visit(root);return result;};
  const byText=text=>all().find(n=>n.tag==='button'&&n.textContent===text);
  const byLabel=text=>all().find(n=>n.attrs['aria-label']===text);
  const rows=()=>all().filter(n=>n.className==='session-row');
  return {root,timeline,control,reads,targets,replies,audioCalls,rows,all,byText,byLabel,reference,
    setSessions:value=>{sessions=value;},getSessions:()=>sessions,deny:()=>{deny=true;},
    holdHistory(){let release;held=new Promise(resolve=>{release=resolve;});return release;}};
}
(async()=>{
  const f=boot();await f.control.refresh('binding');
  assert.equal(f.control.active,true);assert.equal(f.control.capture(),undefined);
  assert.deepEqual(f.rows().map(row=>row.children[0].textContent),['Busy work','Earlier work','Conversation']);
  await f.rows()[0].children[2].children[1].click();
  assert.equal(f.control.capture().reference.source,'session:7');
  f.byText('Earlier work').click();await tick();
  assert.equal(f.timeline.hidden,true);assert.equal(f.control.capture().reference.source,'session:8');
  f.byLabel('Back to the conversation').click();
  assert.equal(f.timeline.hidden,false);assert.equal(f.control.capture().reference.source,'session:7','Back restores the explicit prior pin');
  f.byText('Conversation').click();
  assert.equal(f.control.capture().reference,undefined,'Selecting Conversation temporarily overrides a worker pin');
  f.byLabel('Back to the conversation').click();assert.equal(f.control.capture().reference.source,'session:7');
  f.rows()[1].children[2].children[0].click();
  assert.equal(f.replies[0].ref.source,'session:8/42','Reply freezes the exact clicked latest message');
  f.getSessions()[1].latest_reply={...f.reference(8),source:'session:8/99'};
  await f.control.refresh('binding');assert.equal(f.replies[0].ref.source,'session:8/42');
  f.rows()[0].children[2].children[2].click();
  assert.equal(f.audioCalls[0][0],'mute');assert.equal(f.rows()[0].children[2].children[2].attrs['aria-pressed'],'true');
  assert.equal(f.byLabel('Hear all sessions: clear mute and solo').hidden,false);
  f.byLabel('Hear all sessions: clear mute and solo').click();
  assert.equal(f.byLabel('Hear all sessions: clear mute and solo').hidden,true);
  // A different native generation does not rewrite a pin or fall back to integration.
  f.getSessions()[0].destination=f.reference(7,'b');await f.control.refresh('binding');
  assert.equal(f.control.canSend(),false);assert.equal(f.control.capture().reference.revision,'a'.repeat(64));
  f.byLabel('Send to the conversation').click();assert.equal(f.control.canSend(),true);assert.equal(f.control.capture(),undefined);
  // Late selected-history reads cannot appear under another session's heading.
  const release=f.holdHistory();f.byText('Busy work').click();f.byText('Earlier work').click();await tick();
  release({schema:'daimon.session-view/v1',revision:'f'.repeat(64),items:[{text:'Stale other session',kind:'message',role:'assistant',id:'stale',position:1,next_position:2}],before:1,after:2});await tick();
  assert(!f.root.textContent.includes('Stale other session'));
  f.byLabel('Show tools and exposed reasoning summaries').click();await tick();
  assert(f.reads.at(-1).includes('technical=true'));
  // Access loss removes visible history, keeps a refused old target, and leaves
  // the ordinary conversation available without a global sign-out/reset.
  f.deny();await f.control.refresh('binding');
  assert.equal(f.control.active,false);assert.equal(f.timeline.hidden,false);assert.equal(f.control.canSend(),false);
  assert(!f.root.textContent.includes('Retained answer'));
  f.byLabel('Send to the conversation').click();assert.equal(f.control.capture(),undefined);
  f.control.reset();assert.equal(f.control.active,false);
  // Persist only explicit opaque intent, and restore from fresh authorized metadata.
  const storage=new Map(),ids=['b'.repeat(24),'a'.repeat(24),'e'.repeat(24)],owner='1'.repeat(64);
  const first=boot({storage,ids,preferred:ids[0]});await first.control.refresh(owner);await tick();
  assert.equal(first.timeline.hidden,true,'Receiving follow selection opens its history');
  assert.equal(first.control.capture().reference.source,'session:7');
  const saved=JSON.parse([...storage.values()][0]);assert.deepEqual(Object.keys(saved).sort(),['binding','id','version']);
  const reloaded=boot({storage,ids});reloaded.getSessions()[0].destination=reloaded.reference(7,'c');
  await reloaded.control.refresh(owner);await tick();
  assert.equal(reloaded.timeline.hidden,true);assert.equal(reloaded.control.capture().reference.revision,'c'.repeat(64),'Reload resolves a fresh destination, never a persisted authority');
  assert(reloaded.reads.filter(r=>r!=='interaction/sessions').every(r=>r.includes(ids[0])),'Only the followed history is opened');
  const foreign=boot({storage,ids});await foreign.control.refresh('2'.repeat(64));await tick();
  assert.equal(foreign.control.capture(),undefined);assert.deepEqual(foreign.reads,['interaction/sessions'],'Another actor/binding does not restore the old history');
  reloaded.deny();await reloaded.control.refresh(owner);assert.equal(storage.size,0,'Grant loss removes saved intent');
  storage.set('interaction.followed-session.v1',JSON.stringify({version:1,binding:owner,id:'c'.repeat(24)}));
  const absent=boot({storage,ids});await absent.control.refresh(owner);assert.equal(absent.control.canSend(),false,'Unavailable persisted selection never silently falls back to integration');
  absent.getSessions().push({...absent.getSessions()[0],id:'c'.repeat(24),title:'Recovered followed session'});
  await absent.control.refresh(owner);
  assert(absent.rows().some(row=>row.children[0].textContent==='Recovered followed session'),'A returned row remains available for deliberate reselection');
  assert.equal(absent.control.canSend(),false);absent.byText('Recovered followed session').click();await tick();assert.equal(absent.control.canSend(),true);
  absent.byLabel('Send to the conversation').click();assert.equal(absent.control.canSend(),true);
  storage.set('interaction.followed-session.v1',JSON.stringify({version:1,binding:owner,id:ids[0]}));
  const metadataOnly=boot({storage,ids});metadataOnly.getSessions()[0].destination=null;await metadataOnly.control.refresh(owner);
  metadataOnly.getSessions()[0].destination=metadataOnly.reference(7);await metadataOnly.control.refresh(owner);
  assert.equal(metadataOnly.rows().length,3,'Destination recovery must not fail before rendering the metadata-only row');
  assert.equal(metadataOnly.control.canSend(),false);metadataOnly.byText('Busy work').click();await tick();assert.equal(metadataOnly.control.canSend(),true);
  metadataOnly.byLabel('Send to the conversation').click();
  const unpinned=boot({storage,ids,preferred:ids[0]});await unpinned.control.refresh(owner);assert.equal(unpinned.control.capture(),undefined,'Explicit unpin survives reload even with a receiving default');
  console.log('Session workspace: exact reply, pin/expand/Back, stale generation, late history, technical view, audio and grant loss passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
