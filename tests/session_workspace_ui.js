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
  focus(){this.focused=true;}
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function boot({storage=new Map(),defaultFilter,daimonName='Daimon',noticeHost=false,hosted=false,portableDeliveryText}={}){
  const document={createElement:tag=>new Element(tag)},window={localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)}},root=new Element('main'),timeline=new Element('div');root.append(timeline);
  let observer;
  window.IntersectionObserver=class{
    constructor(callback){this.callback=callback;this.nodes=new Set();observer=this;}
    observe(box){this.nodes.add(box);}
    unobserve(box){this.nodes.delete(box);}
    disconnect(){this.nodes.clear();}
  };
  const reference=(n,revision='a')=>({source:`session:${n}`,revision:revision.repeat(64)});
  const observedAt=Date.now()/1000;
  const row=(id,title,n)=>({id,title,audio_key:`100:${n}`,destination:reference(n),latest_reply:{...reference(n),source:`session:${n}/42`},fresh:true,execution:'idle',goal_state:'absent',last_activity_at:observedAt});
  let pendingItems, completedItems, sessions=[row('b','Busy work',7),row('a','Earlier work',8),{...row('entry','Conversation',1),is_entry:true,destination:null,latest_reply:null}],deny=false,held,truncated=false,failHistory=false,failWorkspace=false,historyFailures=[],scanPage=false,resultRevision,now=Date.now();
  const timers=new Map();let timerId=0;const noticePanel=noticeHost?new Element('aside'):undefined;if(noticePanel)root.append(noticePanel);
  const reads=[],targets=[],replies=[],focuses=[],audioCalls=[],mutes=new Set(),solos=new Set();
  async function api(route){
    reads.push(route);
    if(deny)throw Object.assign(Error('No workspace'),{status:403});
    if(route==='interaction/sessions'&&failWorkspace)throw Object.assign(Error('Synthetic metadata outage'),{status:503});
    if(route==='interaction/sessions')return {schema:'daimon.session-workspace/v1',sessions,truncated,default_filter:defaultFilter};
    const url=new URL(route,'https://fixture.invalid');
    if(held){const hold=held;held=undefined;return hold;}
    if(historyFailures.length)throw Object.assign(Error('Synthetic replaced history'),{status:historyFailures.shift()});
    if(failHistory)throw Object.assign(Error('Synthetic history connection lost'),{status:typeof failHistory==='number'?failHistory:undefined});
    return {schema:'daimon.session-view/v1',session:url.pathname.split('/').at(-1),revision:'f'.repeat(64),items:completedItems||[{kind:'message',role:'assistant',text:'Retained answer',result_revision:resultRevision,id:url.pathname,position:50,next_position:150,timestamp:'2026-11-05T01:00:00Z',next:15,more:false}],before:50,after:150,before_scan:scanPage,after_scan:scanPage,has_earlier:scanPage,more:scanPage,pending_items:pendingItems,links_input_ids:true};
  }
  vm.runInNewContext(fs.readFileSync('dashboard/web/session-workspace.js','utf8'),{window,document,URLSearchParams,Map,Set,JSON,Number,Error,Date:class extends Date{static now(){return now;}},setTimeout:(fn,ms)=>{const id=++timerId;timers.set(id,{fn,at:now+ms});return id;},clearTimeout:id=>timers.delete(id)});
  const control=window.SessionWorkspace.mount({timeline,api,daimonName,hosted,portableDeliveryText,noticeHost:noticePanel,onTarget:()=>targets.push(true),focusComposer:()=>focuses.push(true),onReply:(ref,title)=>replies.push({ref,title}),
    audio:row=>({muted:mutes.has(row.id),solo:solos.has(row.id),filtered:mutes.size+solos.size>0}),
    onAudio:(action,row)=>{audioCalls.push([action,row?.id]);if(action==='mute'){if(mutes.has(row.id))mutes.delete(row.id);else mutes.add(row.id);}if(action==='solo'){if(solos.has(row.id))solos.delete(row.id);else solos.add(row.id);}if(action==='reset'){mutes.clear();solos.clear();}control.syncAudio();}});
  const all=()=>{const result=[];const visit=n=>{result.push(n);n.children.forEach(visit);};visit(root);return result;};
  const byText=text=>all().find(n=>n.tag==='button'&&n.textContent===text);
  const byLabel=text=>all().find(n=>n.attrs['aria-label']===text);
  const rows=()=>all().filter(n=>n.className==='session-row');
  return {storage,root,timeline,control,noticePanel,reads,targets,replies,focuses,audioCalls,rows,all,byText,byLabel,reference,
    failHistory:value=>{failHistory=value;},failOnce:status=>historyFailures.push(status),advance:ms=>{now+=ms;for(const [id,timer] of [...timers])if(timer.at<=now){timers.delete(id);timer.fn();}},scanPage:value=>{scanPage=value;},failWorkspace:value=>{failWorkspace=value;},setSessions:value=>{sessions=value;},setTruncated:value=>{truncated=value;},getSessions:()=>sessions,deny:()=>{deny=true;},
    resultHistory:value=>{resultRevision=value;},pending:value=>{pendingItems=value;},completed:value=>{completedItems=value;},
    showResult(visible=true){observer.callback([...observer.nodes].map(target=>({
      target,isIntersecting:visible,intersectionRatio:visible?1:0
    })));},
    holdHistory(){let release;held=new Promise(resolve=>{release=resolve;});return release;}};
}
(async()=>{
  const hosted=boot({hosted:true});
  const topic='e'.repeat(64);
  hosted.setSessions(hosted.getSessions().map(row=>row.id==='b'?{...row,topic_ref:topic}:row));
  assert.equal(hosted.control.capture(),undefined);
  assert.equal((await hosted.control.selectHostedTopic(topic,'owned')).room,topic);
  assert.equal(hosted.control.capture().reference.source,'session:7');
  assert.equal(await hosted.control.selectHostedTopic('c'.repeat(64),'owned'),null);
  assert.equal(hosted.control.capture().reference.source,'session:7');
  assert.equal(await hosted.control.selectHostedTopic(topic,'owned',()=>false),null);
  assert.equal((await hosted.control.selectHostedTopic(null,'owned')).room,null);
  assert.equal(hosted.control.capture(),undefined);
  assert.equal(hosted.storage.has('interaction.followed-session.v1'),false);
  const resultTopic=boot({hosted:true}),revision='d'.repeat(64),session='7'.repeat(24);
  resultTopic.setSessions(resultTopic.getSessions().map(row=>row.id==='b'?{
    ...row,id:session,topic_ref:topic,result_available:true,result_revision:revision
  }:row));
  resultTopic.resultHistory(revision);
  let current=true;
  const openedResult=await resultTopic.control.readHostedResult(topic,'owned',()=>current);
  assert.equal(openedResult.item.text,'Retained answer');
  assert.equal(resultTopic.control.capture(),undefined,'Opening a result leaves General as recipient');
  assert.equal(await resultTopic.control.readHostedResult('c'.repeat(64),'owned',()=>true),null);
  resultTopic.resultHistory('a'.repeat(64));
  assert.equal(await resultTopic.control.readHostedResult(topic,'owned',()=>true),null,'Old canonical result is refused');
  current=false;
  assert.equal(await openedResult.part(0),null,'Leaving the room fences later reads');


  // Returning to a suspended view may fail one metadata read. Keep that normal
  // recovery quiet; a persistent failure uses the existing compact notice panel.
  const quiet=boot({noticeHost:true});await quiet.control.refresh('binding');
  quiet.byLabel('Show sessions').click();await tick();
  quiet.rows()[0].children[2].children[1].click();
  const frozenTarget=quiet.control.capture();
  quiet.failWorkspace(true);await quiet.control.refresh('binding');quiet.advance(1000);
  assert.equal(quiet.byLabel('Retry session status').hidden,true);
  assert(!quiet.noticePanel.textContent.includes('Session status is unavailable'));
  quiet.failWorkspace(false);await quiet.control.refresh('binding');quiet.advance(9000);
  assert.equal(quiet.byLabel('Retry session status').hidden,true,'Successful recovery cancels the delayed notice');
  quiet.failWorkspace(true);await quiet.control.refresh('binding');quiet.advance(8000);
  assert.equal(quiet.byLabel('Retry session status').hidden,false);
  assert.equal(quiet.byLabel('Retry session status').parentNode,quiet.noticePanel);
  assert(quiet.noticePanel.textContent.includes('Session status is unavailable'));
  assert.deepEqual(quiet.control.capture(),frozenTarget,'A metadata outage never redirects the draft');
  quiet.failWorkspace(false);await quiet.control.refresh('binding');
  assert(!quiet.noticePanel.textContent.includes('Session status is unavailable'));
  quiet.failWorkspace(true);await quiet.control.refresh('binding');quiet.control.reset();quiet.advance(9000);
  assert.equal(quiet.byLabel('Retry session status').hidden,true,'Old binding notices cannot reappear after reset');

  const saved=boot({portableDeliveryText:phase=>({steering:'Waiting to enter',accepted:'Received by the session'})[phase]});await saved.control.refresh('binding');
  saved.byText('Busy work').click();await tick();
  const inputId='a1111111-1111-4111-8111-111111111111';
  const original={kind:'message',role:'user',id:'pending-original',input_id:inputId,text:'Please start the selected work',pending:true};
  const start=saved.reads.length;
  saved.control.previewSubmission(saved.reference(7,'b'),inputId,original.text);
  assert.equal(saved.all().filter(node=>node.dataset.inputId===inputId).length,0,'Another revision cannot acquire the local text');
  saved.control.previewSubmission(saved.reference(7),inputId,original.text);
  assert.equal(saved.reads.length,start,'Local display precedes the network');
  const visible=()=>saved.all().filter(node=>node.dataset.inputId===inputId);
  assert.equal(visible().length,1);
  assert.match(visible()[0].textContent,/Sending/);
  saved.control.settlePreview(inputId,'Message saved.');
  assert.match(visible()[0].textContent,/Message saved/);
  saved.pending([{...original,portable_phase:"steering"}]);
  saved.control.observeSubmission(saved.reference(7,'b'));await tick();
  assert.equal(saved.reads.length,start,'A change to the selected revision fences the immediate refresh');
  saved.control.observeSubmission(saved.reference(7));await tick();
  assert.equal(saved.reads.length,start+1,'Admission refreshes only the selected history');
  assert.match(saved.reads.at(-1),/^interaction\/sessions\/b\?/);
  assert.equal(visible().length,1);
  assert.equal(visible()[0].dataset.event,'pending-original','The retained input replaces the local preview');
  assert.match(visible()[0].textContent,/Waiting to enter/);
  const pendingCard=visible()[0];
  saved.pending([{...original,portable_phase:"accepted"}]);
  saved.control.observeSubmission(saved.reference(7));await tick();
  assert.equal(visible().length,1);
  assert.equal(visible()[0],pendingCard,'A receipt updates the existing input card');
  assert.match(visible()[0].textContent,/Received by the session/);
  saved.pending([]);saved.completed([{...original,id:'completed-original',pending:false,position:150,next_position:160}]);
  saved.control.observeSubmission(saved.reference(7));await tick();
  assert.equal(visible().length,1);
  assert.equal(visible()[0].dataset.event,'completed-original','The final history supersedes the pending input');
  const general=boot({daimonName:'CompAII'}),entry=general.getSessions().find(row=>row.is_entry);
  entry.title='Daimon Interaction';entry.last_activity_at=1;
  general.getSessions()[0].execution='working';await general.control.refresh('binding');
  assert.equal(general.rows()[0].children[0].textContent,'CompAII','General conversation is always first, including when idle and old');
  general.byText('CompAII').click();assert.equal(general.control.capture().reference,undefined,'Display naming preserves the integrating destination');
  assert.equal(entry.title,'Daimon Interaction','The retained native title is not rewritten');
  const reviews=boot(),work=reviews.getSessions()[0],result='a'.repeat(64),next='b'.repeat(64);
  Object.assign(work,{id:'7'.repeat(24),result_available:true,result_revision:result});
  reviews.resultHistory(result);
  await reviews.control.refresh('binding');
  const state=fixture=>fixture.rows().find(row=>row.children[0].textContent==='Busy work').children[1].textContent;
  assert.match(state(reviews),/Result available/);
  reviews.failHistory(true);
  reviews.byText('Busy work').click();await tick();
  reviews.showResult();assert.match(state(reviews),/Result available/,'A failed history read cannot mark the result');
  reviews.failHistory(false);
  await reviews.byLabel('Retry reading this conversation').click();await tick();
  reviews.showResult(false);assert.match(state(reviews),/Result available/,'Off-screen results stay unread');
  reviews.showResult();assert.equal(state(reviews),'○ Idle');
  work.execution='working';work.latest_reply={...work.latest_reply,source:'session:7/43'};
  await reviews.control.refresh('binding');
  assert.equal(state(reviews),'⚙ Working','Later commentary does not reopen the reviewed result');
  const reopened=boot({storage:reviews.storage});
  reopened.setSessions(reviews.getSessions());await reopened.control.refresh('binding');
  assert.equal(state(reopened),'⚙ Working','Review survives a reload in the same binding');
  work.result_revision=next;await reviews.control.refresh('binding');
  reviews.showResult();assert.match(state(reviews),/Result available/,'Old visible history cannot clear a new result');
  work.result_revision=result;await reviews.control.refresh('different binding');
  assert.match(state(reviews),/Result available/,'A different binding never inherits a local review');

  const storage=new Map(),profile=boot({storage});
  const inventory=profile.getSessions().map((row,i)=>({...row,id:String(i+1).repeat(24)}));
  inventory[1].last_activity_at=Date.now()/1000-172800;
  profile.setSessions(inventory);await profile.control.refresh('binding');
  assert.equal(profile.rows().length,2,'Recent remains the ordinary default');
  profile.byLabel('Show all sessions').click();assert.equal(profile.rows().length,3);
  profile.rows().find(row=>row.children[0].textContent==='Busy work').children[2].children[1].click();
  profile.byText('Earlier work').click();await tick();
  assert.equal(profile.control.capture().reference.source,'session:8');
  const restored=boot({storage});restored.setSessions(inventory.map(row=>({...row,destination:row.destination?{...row.destination,revision:'c'.repeat(64)}:null})));
  await restored.control.refresh('binding');await tick();
  assert.equal(restored.control.capture().reference.source,'session:8');assert.equal(restored.control.capture().reference.revision,'c'.repeat(64),'Reload uses fresh authorized references');
  assert.equal(restored.focuses.length,0,'Restoring history does not take composer focus');
  restored.byLabel('Back to the conversation').click();assert.equal(restored.control.capture().reference.source,'session:7','Back restores the prior explicit pin');
  assert.equal(restored.rows().length,3,'All/recent preference survives reload');
  const persisted=storage.get('interaction.followed-session.v1');assert(!persisted.includes('session:')&&!persisted.includes('Earlier work'),'Only opaque navigation preferences are retained');
  const missing=boot({storage});missing.setSessions([]);await missing.control.refresh('binding');assert.throws(()=>missing.control.capture(),/saved session is unavailable/);
  const foreign=boot({storage});await foreign.control.refresh('different-binding');assert.equal(foreign.control.capture(),undefined,'Another binding cannot adopt the saved target');
  const allProfile=boot({defaultFilter:'all'});allProfile.setSessions(inventory);await allProfile.control.refresh('binding');assert.equal(allProfile.rows().length,3,'Explicit receiving profile can select all registered sessions');
  const f=boot();await f.control.refresh('binding');
  assert.equal(f.control.active,true);assert.equal(f.control.capture(),undefined);
  assert.deepEqual(f.rows().map(row=>row.children[0].textContent),['Daimon','Earlier work','Busy work']);
  f.getSessions()[0].execution='working';await f.control.refresh('binding');
  assert.equal(f.rows()[0].children[0].textContent,'Daimon');
  assert.equal(f.rows()[1].children[0].textContent,'Busy work');
  f.byLabel('Show sessions').click();
  await f.rows()[1].children[2].children[1].click();
  assert.equal(f.byLabel('Your sessions').hidden,true,'Pin selection collapses the menu');
  assert.equal(f.byLabel('Show sessions').focused,true,'Pin returns focus to the menu toggle');
  f.byLabel('Show sessions').click();
  assert.equal(f.control.capture().reference.source,'session:7');
  const selectedBeforeOutage=JSON.stringify(f.control.capture());
  f.failWorkspace(true);await tick();await f.control.refresh('binding');f.advance(8000);
  assert.equal(f.byLabel('Retry session status').hidden,false);
  assert.equal(JSON.stringify(f.control.capture()),selectedBeforeOutage,'Metadata failure keeps the exact selected destination');
  f.failWorkspace(false);await f.byLabel('Retry session status').click();
  assert.equal(f.byLabel('Retry session status').hidden,true);
  assert.equal(JSON.stringify(f.control.capture()),selectedBeforeOutage,'Retry does not route input or clear the pin');
  f.byText('Earlier work').click();await tick();
  assert.equal(f.timeline.hidden,true);assert.equal(f.control.capture().reference.source,'session:8');
  assert.equal(f.focuses.length,1);
  assert.equal(f.control.audioScope().audio_key,'100:8','Opening limits audio to the exact selected session');
  assert.equal(f.rows()[1].children[2].children[1].attrs['aria-pressed'],'true');
  assert.equal(f.rows()[2].children[2].children[1].attrs['aria-pressed'],'false','Opening does not pin');
  f.byLabel('Back to the conversation').click();
  assert.equal(f.timeline.hidden,false);assert.equal(f.control.capture().reference.source,'session:7','Back restores its explicit pin');
  assert.equal(f.control.audioScope(),undefined);
  assert.equal(f.byLabel('Send to the conversation').attrs['aria-pressed'],'true');
  f.byText('Daimon').click();
  assert.equal(f.control.capture().reference,undefined,'Selecting general temporarily selects the general destination');
  assert.equal(f.control.audioScope().is_entry,true);
  f.byLabel('Show all session updates').click();
  assert.equal(f.control.capture().reference.source,'session:7');
  f.byLabel('Show sessions').click();
  f.rows()[2].children[2].children[0].click();
  assert.equal(f.byLabel('Your sessions').hidden,true,'Exact-message reply collapses the menu');
  assert.equal(f.replies[0].ref.source,'session:8/42','Reply freezes the exact clicked latest message');
  f.getSessions()[1].latest_reply={...f.reference(8),source:'session:8/99'};
  await f.control.refresh('binding');assert.equal(f.replies[0].ref.source,'session:8/42');
  f.byLabel('Show sessions').click();
  f.rows()[1].children[2].children[2].click();
  assert.equal(f.byLabel('Your sessions').hidden,false,'Mute keeps the menu open');
  assert.equal(f.audioCalls[0][0],'mute');assert.equal(f.rows()[1].children[2].children[2].attrs['aria-pressed'],'true');
  assert.equal(f.byLabel('Hear all sessions: clear mute and solo').hidden,false);
  f.rows()[1].children[2].children[3].click();
  assert.equal(f.byLabel('Your sessions').hidden,false,'Solo keeps the menu open');
  assert.equal(f.rows()[1].children[2].children[3].attrs['aria-pressed'],'true');
  assert.equal(f.byLabel('Hear all sessions: clear mute and solo').parentNode.className,'session-rail-header','Reset lives in the menu header');
  f.byLabel('Hear all sessions: clear mute and solo').click();
  assert.equal(f.byLabel('Your sessions').hidden,false,'Reset keeps the menu open');
  assert.equal(f.byLabel('Hear all sessions: clear mute and solo').hidden,true);
  // A different native generation does not rewrite a pin or fall back to integration.
  f.getSessions()[0].destination=f.reference(7,'b');await f.control.refresh('binding');
  assert.equal(f.control.canSend(),false);assert.equal(f.control.capture().reference.revision,'a'.repeat(64));
  f.byLabel('Send to the conversation').click();assert.equal(f.control.canSend(),true);assert.equal(f.control.capture(),undefined);
  const separate=boot();await separate.control.refresh('binding');
  separate.byText('Earlier work').click();await tick();
  assert.equal(separate.byLabel('Clear pinned input destination').hidden,true);
  separate.rows().find(row=>row.children[0].textContent==='Busy work').children[2].children[1].click();
  assert.equal(separate.timeline.hidden,true,'Pinning a different session does not close the current view');
  separate.byLabel('Clear pinned input destination').click();
  assert.equal(separate.control.capture().reference.source,'session:8','Clearing pin does not redirect the current view');
  separate.byLabel('Back to the conversation').click();assert.equal(separate.control.capture(),undefined);
  // A failed initial history read stays actionable rather than returning to
  // an endless Reading indicator on every metadata observation.
  const broken=boot();await broken.control.refresh('binding');broken.failHistory(true);
  broken.byText('Busy work').click();await tick();
  assert.equal(broken.byLabel('Retry reading this conversation').hidden,false);
  assert(broken.root.textContent.includes('Conversation unavailable'));
  const initialReads=broken.reads.length;await broken.control.refresh('binding');await tick();
  assert.equal(broken.reads.length,initialReads+1,'Metadata refresh does not restart failed initial history');
  assert.equal(broken.byLabel('Retry reading this conversation').hidden,false);
  broken.failHistory(false);broken.byLabel('Retry reading this conversation').click();await tick();
  assert(broken.root.textContent.includes('Retained answer'));
  assert.equal(broken.byLabel('Retry reading this conversation').hidden,true);
  assert.equal(broken.control.capture().reference.source,'session:7','Reading retry preserves the selected destination');
  const automatic=boot();await automatic.control.refresh('binding');automatic.failHistory(true);
  automatic.byText('Busy work').click();await tick();automatic.failHistory(false);
  automatic.advance(5001);await automatic.control.refresh('binding');await tick();
  assert(automatic.root.textContent.includes('Retained answer'),'An existing metadata event recovers a failed initial read without a timer or click');
  assert.equal(automatic.control.capture().reference.source,'session:7');
  const interruptedRead=boot();await interruptedRead.control.refresh('binding');
  interruptedRead.byText('Busy work').click();await tick();
  interruptedRead.failHistory(503);await interruptedRead.control.refresh('binding');await tick();
  assert(interruptedRead.root.textContent.includes('Retained answer'),'A temporary read outage keeps the visible history');
  assert.equal(interruptedRead.byLabel('Retry reading this conversation').hidden,false);
  assert.equal(interruptedRead.control.capture().reference.source,'session:7');
  const replaced=boot();await replaced.control.refresh('binding');replaced.failOnce(409);
  replaced.byText('Busy work').click();await tick();await tick();
  assert(replaced.root.textContent.includes('Retained answer'),'A changed file gets one fresh read automatically');
  assert.equal(replaced.reads.filter(route=>route.startsWith('interaction/sessions/b?')).length,2);
  replaced.failHistory(409);await replaced.control.refresh('binding');await tick();await tick();
  const bounded=replaced.reads.length;await replaced.control.refresh('binding');await tick();
  assert.equal(replaced.reads.length,bounded+1,'A persistent conflict cannot cause a tight retry loop');
  assert.equal(replaced.control.capture().reference.source,'session:7','File recovery never changes the frozen input target');
  const scanning=boot();await scanning.control.refresh('binding');scanning.scanPage(true);
  scanning.byText('Busy work').click();await tick();await scanning.control.refresh('binding');await tick();
  assert(scanning.reads.at(-1).includes('after=150')&&scanning.reads.at(-1).includes('scan=true'));
  assert(!scanning.byText('Earlier')&&!scanning.byText('Newer'));
  const messages=scanning.byLabel('Selected session messages');
  assert.equal(messages.tabIndex,0);
  messages.scrollTop=0;messages.events.wheel({deltaY:-40,deltaX:0});await tick();
  assert(scanning.reads.at(-1).includes('before=50')&&scanning.reads.at(-1).includes('scan=true'));
  messages.events.touchstart({touches:[{clientY:80}]});
  messages.events.touchend({changedTouches:[{clientY:140}]});await tick();
  assert(scanning.reads.at(-1).includes('before=50'),'A touch gesture loads history even when the page is too short to scroll');
  messages.scrollTop=messages.scrollHeight;messages.events.keydown({target:messages,key:'PageDown'});await tick();
  assert(scanning.reads.at(-1).includes('after=150'),'Keyboard navigation reaches newer history');
  // Late selected-history reads cannot appear under another session's heading.
  const release=f.holdHistory();f.byText('Busy work').click();f.byText('Earlier work').click();await tick();
  release({schema:'daimon.session-view/v1',revision:'f'.repeat(64),items:[{text:'Stale other session',kind:'message',role:'assistant',id:'stale',position:1,next_position:2}],before:1,after:2});await tick();
  assert(!f.root.textContent.includes('Stale other session'));
  f.byLabel('Raw session view').click();await tick();
  assert(f.reads.at(-1).includes('technical=true'));
  const selectedTarget=f.control.capture();
  f.byLabel('Raw session view').click();await tick();
  assert(f.reads.at(-1).includes('technical=false'));
  assert.deepEqual(f.control.capture(),selectedTarget,'Changing presentation keeps the input destination');
  f.byLabel('Raw session view').click();await tick();
  f.byText('Busy work').click();await tick();
  assert(f.reads.at(-1).includes('technical=false'),'Opening a session always starts with the conversation');
  // Access loss removes visible history, keeps a refused old target, and leaves
  // the ordinary conversation available without a global sign-out/reset.
  f.deny();await f.control.refresh('binding');
  assert.equal(f.control.active,false);assert.equal(f.timeline.hidden,false);assert.equal(f.control.canSend(),false);
  assert(!f.root.textContent.includes('Retained answer'));
  f.byLabel('Clear pinned input destination').click();
  f.byLabel('Back to the conversation').click();assert.equal(f.control.capture(),undefined);
  f.control.reset();assert.equal(f.control.active,false);
  const aging=boot();const now=Date.now()/1000;const records=aging.getSessions();
  records[0].last_activity_at=now-86399;records[1].last_activity_at=now-86401;
  records[2].last_activity_at=now-172800;records[2].execution='working';
  await aging.control.refresh('binding');
  assert.deepEqual(aging.rows().map(row=>row.children[0].textContent),['Daimon','Busy work'],'Active now counts as activity; expired idle sessions are hidden');
  aging.rows()[1].children[2].children[1].click();
  records[0].last_activity_at=now-86401;await aging.control.refresh('binding');
  assert.equal(aging.control.capture().reference.source,'session:7');
  assert.equal(aging.control.canSend(),true,'Hiding an old row does not change an explicit destination');
  assert.equal(aging.byText('Busy work'),undefined);
  const icon=aging.rows()[0].children[2].children[2];assert(icon.innerHTML.includes('M11 5 6 9H3'));
  icon.click();assert(icon.innerHTML.includes('m16 9 5 6m0-6-5 6'));

  const titles=boot(),worker={kind:'worker_result',target:{chat_id:100,thread_id:7},label:'Unrelated display label'};
  await titles.control.refresh('binding');
  assert.equal(titles.control.pinState(worker).available,true);
  assert.equal(titles.control.pinSource(worker),true);assert.equal(titles.control.capture().reference.source,'session:7');
  assert.equal(titles.control.pinState(worker).pinned,true);
  assert.equal(titles.rows()[2].children[2].children[1].attrs['aria-pressed'],'true','Title pin updates the menu');
  assert.equal(titles.byLabel('Send to the conversation').attrs['aria-pressed'],'true','Destination unpin indicates the explicit pin');
  titles.rows()[2].children[2].children[1].click();assert.equal(titles.control.pinState(worker).pinned,false,'Menu unpin updates the title');
  assert.equal(titles.control.pinState({...worker,target:{chat_id:200,thread_id:7}}).available,false,'A matching label cannot select another target');
  titles.getSessions()[0].last_activity_at=now-172800;await titles.control.refresh('binding');
  assert.equal(titles.byText('Busy work'),undefined);assert.equal(titles.control.pinSource(worker),true,'Hidden old rows still resolve through the complete exact inventory');
  assert.equal(titles.control.pinSource({kind:'integrator_answer'}),true);assert.equal(titles.control.capture(),undefined,'Conversation title clears the worker pin');
  titles.setSessions([...titles.getSessions(),{...titles.getSessions()[0],id:'duplicate-target'}]);await titles.control.refresh('binding');
  assert.equal(titles.control.pinState(worker).available,false);assert.equal(titles.control.pinSource(worker),false,'Ambiguous exact targets are refused');
  titles.setSessions(titles.getSessions().slice(0,3));titles.setTruncated(true);await titles.control.refresh('binding');
  assert.equal(titles.control.pinSource(worker),false,'Incomplete inventory cannot grant a title pin');
  titles.setTruncated(false);titles.getSessions()[0].destination=null;await titles.control.refresh('binding');
  assert.equal(titles.control.pinState(worker).available,false,'Missing native-issued destination remains unavailable');
  titles.deny();await titles.control.refresh('binding');assert.equal(titles.control.pinSource(worker),false,'Grant loss prevents title pinning');
  console.log('Session workspace: exact reply, pin/expand/Back, stale generation, late history, technical view, audio and grant loss passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
