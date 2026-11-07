// Shipped fullscreen controller with synthetic callbacks; no capture or models.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function boot({suspend=false,reconnect,onReview,getAttention,leaveResult,bridge=false}={}){
 const timers=[],listeners={},nodes=[];
 class Node{
  constructor(tag){this.tag=tag;this.children=[];this.attributes={};this.events={};this.hidden=false;this.dataset={};this.classList={add(){},remove(){}};nodes.push(this);}
  append(...children){for(const child of children){child.remove();child.parent=this;this.children.push(child);}}
  remove(){if(this.parent)this.parent.children.splice(this.parent.children.indexOf(this),1);this.parent=undefined;}
  before(node){node.remove();const parent=this.parent;parent.children.splice(parent.children.indexOf(this),0,node);node.parent=parent;}
  replaceWith(node){this.before(node);this.remove();}
  setAttribute(key,value){this.attributes[key]=value;}
  getAttribute(key){return this.attributes[key]??null;}removeAttribute(key){delete this.attributes[key];}
  addEventListener(name,fn){this.events[name]=fn;}
  showModal(){this.open=true;}close(){this.open=false;}focus(){this.focused=true;document.activeElement=this;}
 }
 const body=new Node('body'),header=new Node('header'),portrait=new Node('pre');body.append(header);header.append(portrait);
 const document={body,hidden:false,createElement:tag=>new Node(tag),createComment:()=>new Node('comment'),addEventListener:(name,fn)=>listeners[name]=fn};
 const window={addEventListener:(name,fn)=>listeners[name]=fn,dispatchEvent:event=>listeners[event.type]?.(event)};
 if(bridge){window.DaimonAudio={postMessage(){}};vm.runInNewContext(fs.readFileSync('clients/android/app/src/main/assets/native-audio.js','utf8'),{window,navigator:{mediaDevices:{}},Event});}
 vm.runInNewContext(fs.readFileSync('dashboard/web/voice-mode.js','utf8'),{window,document,setTimeout:(fn,ms)=>{const timer={fn,ms};timers.push(timer);return timer;},clearTimeout:t=>{if(t)t.cancelled=true;}});
 let starts=0,enters=0,leaves=0,suspends=0,resumes=0,canStart=true,canEnter=true;
 const mode=window.ConversationVoiceMode.mount({portrait,onReview,getAttention,...(reconnect?{onReconnect:reconnect}:{}),...(suspend?{onSuspend:()=>suspends++}:{}),onEnter:()=>{enters++;},onLeave:()=>{leaves++;return leaveResult;},onSpeak:()=>starts++,onResumeAudio:()=>resumes++,canStart:()=>canStart,canEnter:()=>canEnter});
 return {mode,portrait,header,nodes,timers,document,listeners,window,counts:()=>({starts,enters,leaves}),suspends:()=>suspends,resumes:()=>resumes,canStart:value=>canStart=value,canEnter:value=>canEnter=value};
}
const f=boot();f.mode.configure(false);f.portrait.events.click();assert.equal(f.counts().starts,0);
f.mode.configure(true);f.canEnter(false);f.portrait.events.click();assert.equal(f.counts().starts,0,'An unfinished original prevents opening');
f.canEnter(true);f.portrait.events.click();assert(f.mode.active);assert.equal(f.counts().starts,1);assert.notEqual(f.portrait.parent,f.header);
f.mode.update({capture:'recording',message:'Live words'});assert.equal(f.nodes.find(n=>n.className==='voice-mode-state').textContent,'Listening');
f.mode.update({capture:'idle',pending:false,sent:true});assert.equal(f.counts().starts,1,'Receipt alone does not reopen the microphone over the response');
f.mode.update({playback:'playing'});f.mode.update({playback:undefined});
let timer=f.timers.findLast(t=>t.ms===900&&!t.cancelled);assert(timer);f.canStart(false);timer.fn();assert.equal(f.counts().starts,1,'A queued chunk or capture fences automatic rearming');
f.canStart(true);f.mode.update({playback:'playing'});f.mode.update({playback:undefined});timer=f.timers.findLast(t=>t.ms===900&&!t.cancelled);timer.fn();assert.equal(f.counts().starts,2);
f.mode.update({capture:'ready',pending:true});assert.equal(f.nodes.find(n=>n.className==='voice-mode-state').textContent,'Recording needs review');
f.nodes.find(n=>n.tag==='dialog'&&n.open).events.cancel({preventDefault(){}});
assert(!f.mode.active);assert.equal(f.portrait.parent,f.header);assert.deepEqual(f.counts(),{starts:2,enters:1,leaves:1});
f.portrait.events.keydown({key:'Enter',preventDefault(){}});assert(f.mode.active);
f.document.hidden=true;f.listeners.visibilitychange();assert(!f.mode.active);assert.equal(f.portrait.parent,f.header);
f.document.hidden=false;f.portrait.events.click();f.timers.findLast(t=>t.ms===300000&&!t.cancelled).fn();assert(!f.mode.active,'Foreground opt-in has a five-minute stop path');
f.mode.close();assert.equal(f.counts().leaves,3,'Repeated teardown is inert');
const direct=boot();direct.mode.configure(true,true);direct.portrait.events.click();
assert.equal(direct.counts().starts,1);
direct.mode.update({continuousState:{active:true,starting:false,pending:false,working:false}});
direct.mode.update({playback:'playing'});assert.equal(direct.nodes.find(n=>n.className==='voice-mode-state').textContent,'Speaking · listening');
direct.mode.update({playback:undefined});assert(!direct.timers.some(t=>t.ms===900&&!t.cancelled),'Continuous mode never uses the alternating rearm timer');
const directStatus=direct.nodes.find(n=>n.className==='voice-mode-state');
direct.mode.update({continuousState:{active:true,remaining:15}});
assert.equal(directStatus.textContent,'Listening · 0:15');assert.equal(directStatus.dataset.nearLimit,'true');assert.match(directStatus.attributes['aria-label'],/15 seconds of recording remaining/);
direct.mode.update({playback:'playing'});assert.equal(directStatus.textContent,'Speaking · listening · 0:15');
direct.mode.update({continuousState:{active:true,remaining:120}});
assert.equal(directStatus.textContent,'Speaking · listening · 2:00');assert.equal(directStatus.dataset.nearLimit,'false');
direct.mode.update({continuousState:{active:true,remaining:Infinity}});assert.equal(directStatus.textContent,'Speaking · listening');
direct.mode.update({continuousState:{active:false,starting:false,pending:true,working:false,message:'Voice analysis stopped. Your recordings are kept.'}});direct.mode.update({pending:false,uploading:true,capture:'idle'});
assert.equal(direct.nodes.find(n=>n.className==='voice-mode-state').textContent,'Recording needs review','An old ordinary upload cannot clear continuous recovery state');
assert.match(direct.nodes.find(n=>n.className==='voice-mode-caption').textContent,/Voice analysis stopped/,'The actual hold reason survives unrelated ordinary playback updates');
direct.mode.update({continuousState:{playback:'idle',audioPaused:false,audioEnabled:true}});
assert.equal(direct.nodes.find(n=>n.className==='voice-mode-state').textContent,'Recording needs review','Partial audio state cannot clear retained review');
assert.match(direct.nodes.find(n=>n.className==='voice-mode-caption').textContent,/Voice analysis stopped/);
const badge=direct.nodes.find(n=>n.className==='voice-mode-detection');
direct.mode.update({handoff:{id:'first',gate:'waiting_speech',captured_ms:37000,analyzed_ms:6200,words:true}});
assert.match(badge.textContent,/Waiting for voice detection/);assert.match(badge.textContent,/Voice analysis delayed/);assert.equal(badge.hidden,false);
direct.mode.update({handoff:{id:'first',gate:'speaking',captured_ms:1000,analyzed_ms:1000}});assert.equal(badge.textContent,'Voice detected');
direct.mode.update({handoff:{id:'first',gate:'waiting_endpoint'}});assert.match(badge.textContent,/waiting for phrase end/);
direct.mode.update({handoff:{id:'first',gate:'finishing'}});assert.match(badge.textContent,/Phrase end detected/);
direct.mode.update({handoff:{id:'second',gate:'waiting_speech'}});assert.match(badge.textContent,/Previous phrase: phrase end detected/,'Immediate recorder rearm must not erase the visible end marker');
direct.mode.update({handoff:{id:'first',gate:'confirmed'}});assert.match(badge.textContent,/Previous phrase: phrase sent/);
direct.mode.update({handoff:{id:'second',gate:'speaking'}});assert.equal(badge.textContent,'Voice detected');
direct.mode.update({handoff:{id:'first',gate:'confirmed'}});assert.equal(badge.textContent,'Voice detected','An old original cannot replace current voice detection');
direct.mode.update({caption:'Visible words'});assert.equal(badge.textContent,'Voice detected','ASR text cannot assert or erase endpoint detection');
direct.mode.update({handoff:{id:'second',gate:'review',review_after:'waiting_speech'}});assert.match(badge.textContent,/voice was not detected/);
direct.mode.update({handoff:{id:'second',gate:'__proto__',text:'untrusted'}});assert(!badge.textContent.includes('untrusted'));
direct.mode.configure(true,false);assert(!direct.mode.active);assert.equal(direct.portrait.parent,direct.header);
const background=boot({suspend:true});background.mode.configure(true,true);background.portrait.events.click();
background.mode.update({continuousState:{active:true,starting:false,pending:false,working:false}});background.mode.update({playback:'playing'});
background.document.hidden=true;background.listeners.visibilitychange();
assert(background.mode.active,'Hiding a continuous view pauses capture without leaving its Conversation-only audio mix');
assert.equal(background.suspends(),1);assert.equal(background.counts().leaves,0);
background.mode.update({continuousState:{active:false,starting:false,pending:false,working:false}});
assert.equal(background.nodes.find(n=>n.className==='voice-mode-state').textContent,'Reply playback · microphone off');
background.document.hidden=false;background.listeners.visibilitychange();assert.equal(background.counts().starts,1,'Showing the view never reopens the microphone');
background.listeners.pagehide();assert(!background.mode.active,'Leaving the page still closes the bounded view');assert.equal(background.counts().leaves,1);
// MainActivity emits this native bridge event before WebView visibility can
// change. Exercise the shipped bridge and controller together with no device.
const nativeBackground=boot({suspend:true,bridge:true});nativeBackground.mode.configure(true,true);nativeBackground.portrait.events.click();
nativeBackground.mode.update({continuousState:{active:true,starting:false}});
assert.equal(nativeBackground.document.hidden,false);
nativeBackground.window.NativeSpeechAudio.background(true);
assert.equal(nativeBackground.suspends(),1,'Native background signal must suspend Avatar even while the WebView reports visible');
assert(nativeBackground.mode.active,'Keep the review/reconnect view available');
assert.equal(nativeBackground.counts().starts,1,'Backgrounding does not start another capture');
nativeBackground.document.hidden=true;nativeBackground.listeners.visibilitychange();
nativeBackground.document.hidden=false;nativeBackground.listeners.visibilitychange();
assert.equal(nativeBackground.counts().starts,1,'Returning to the app still needs an explicit reconnect');
nativeBackground.listeners.pagehide();const stoppedSuspends=nativeBackground.suspends();
nativeBackground.window.NativeSpeechAudio.background(true);assert.equal(nativeBackground.suspends(),stoppedSuspends,'Closed Avatar ignores later background signals');
const nativeAlternating=boot({bridge:true});nativeAlternating.mode.configure(true);nativeAlternating.portrait.events.click();
nativeAlternating.window.NativeSpeechAudio.background(true);assert.equal(nativeAlternating.mode.active,false,'Legacy capture closes through the same owner');
const unavailable=boot();unavailable.mode.configure(true,true);unavailable.portrait.events.click();
unavailable.mode.update({continuousState:{active:false,starting:false,pending:false,working:false,message:'Native voice disconnected'}});
assert.equal(unavailable.nodes.find(n=>n.className==='voice-mode-caption').textContent,'Native voice disconnected','A stopped native session without an original must still explain why it stopped');
unavailable.mode.update({capture:'idle',pending:false});
assert.equal(unavailable.nodes.find(n=>n.className==='voice-mode-caption').textContent,'Native voice disconnected','Ordinary composer updates cannot hide a native stop reason');
unavailable.mode.update({continuousState:{playback:'playing'},playback:'playing'});
assert.equal(unavailable.nodes.find(n=>n.className==='voice-mode-state').textContent,'Reply playback · microphone off');
assert.equal(unavailable.nodes.find(n=>n.className==='voice-mode-caption').textContent,'Native voice disconnected','Playback does not assert a new voice connection');
unavailable.mode.update({continuousState:{starting:true,message:'Preparing voice'}});
unavailable.mode.update({continuousState:{playback:'idle'},playback:'idle'});
assert.equal(unavailable.nodes.find(n=>n.className==='voice-mode-state').textContent,'Preparing voice','Partial output state cannot erase reconnect preparation');
unavailable.mode.update({continuousState:{active:true,starting:false,pending:false,working:false,message:'Listening'}});
assert.equal(unavailable.nodes.find(n=>n.className==='voice-mode-caption').textContent,'','Restart clears the previous stop reason');unavailable.mode.close();


const paused=boot();paused.mode.configure(true,true);paused.portrait.events.click();paused.canStart(false);
paused.mode.update({continuousState:{active:true,starting:false,pending:false,working:false,audioPaused:true,audioEnabled:true},playback:'paused'});
const resume=paused.nodes.find(n=>n.tag==='button'&&n.textContent==='Resume audio');
assert(resume&&!resume.hidden&&!resume.disabled,'A native pause must be recoverable inside the open modal without another microphone start');
assert.equal(paused.nodes.find(n=>n.className==='voice-mode-state').textContent,'Audio paused · listening');
resume.events.click();assert.equal(paused.resumes(),1);assert.equal(paused.counts().starts,1);assert(paused.mode.active);
paused.mode.update({continuousState:{active:true,audioPaused:false,audioEnabled:true},playback:'idle'});assert(resume.hidden);
paused.mode.update({continuousState:{active:true,audioPaused:false,audioEnabled:false}});assert(!resume.hidden);assert.equal(resume.textContent,'Enable audio');
resume.events.click();assert.equal(paused.resumes(),2);assert.equal(paused.counts().starts,1);
paused.mode.update({continuousState:{active:false,pending:true,audioPaused:true}});assert(resume.hidden);paused.mode.close();

console.log('Fullscreen voice: avatar identity, explicit opt-in, response/rearm fences, review, explicit in-avatar audio recovery, Escape, hidden and bounded exit passed.');

let reconnected=0;const recoveryMode=boot({reconnect:()=>reconnected++});recoveryMode.mode.configure(true,true);recoveryMode.portrait.events.click();recoveryMode.canStart(false);recoveryMode.mode.update({continuousState:{active:false,starting:false,pending:true,working:false,message:'Recordings retained.'}});const reconnectButton=recoveryMode.nodes.find(v=>v.textContent==='Reconnect voice');assert(reconnectButton&&!reconnectButton.hidden&&!reconnectButton.disabled);reconnectButton.events.click();assert.equal(reconnected,1);assert(recoveryMode.mode.active,'Reconnect stays inside Avatar and keeps the review action available');

// A continuous engine owns a ten-minute microphone visit, whereas the legacy
// alternating view retains its independent five-minute opt-in.
const continuousBudget=boot();continuousBudget.mode.configure(true,true);continuousBudget.portrait.events.click();
for(const t of continuousBudget.timers.filter(t=>!t.cancelled&&t.ms<=300000))t.fn();
assert.equal(continuousBudget.mode.active,true,'The legacy five-minute timer must not terminate a continuous voice visit');
assert.equal(continuousBudget.counts().leaves,0);
const endContinuous=continuousBudget.timers.find(t=>!t.cancelled&&t.ms===600000);assert(endContinuous,'Continuous view still has a finite ten-minute stop path');
endContinuous.fn();assert.equal(continuousBudget.mode.active,false);assert.equal(continuousBudget.counts().leaves,1,'Budget expiry closes through the ordinary owner once');
console.log('Avatar view budget: continuous voice survives the legacy five-minute deadline and closes at ten minutes.');

let pendingCount=2,reviews=0,restoreReview;
const attentionView=boot({getAttention:()=>pendingCount,onReview:restore=>{reviews++;restoreReview=restore;}});
attentionView.mode.configure(true,true);attentionView.portrait.events.click();
const reviewButton=attentionView.nodes.find(n=>n.attributes['aria-label']==='For you · 2 pending requests');
assert(reviewButton&&!reviewButton.hidden,'Opening Avatar reads already-pending attention');
const attentionTimers=attentionView.timers.filter(t=>t.ms===600000&&!t.cancelled).length;
reviewButton.events.click();assert.equal(attentionView.timers.filter(t=>t.ms===600000&&!t.cancelled).length,attentionTimers,'Review cannot reset the microphone/view budget');assert.equal(reviews,1);assert.equal(attentionView.mode.active,true);assert.equal(attentionView.counts().leaves,0,'Reading attention does not close capture or answer a request');
restoreReview();assert.equal(reviewButton.focused,true,'Closing attention can return focus to Avatar');
pendingCount=0;attentionView.mode.attention(pendingCount);assert.equal(reviewButton.hidden,true);
restoreReview();assert.equal(attentionView.nodes.find(n=>n.textContent==='Back to conversation').focused,true,'Withdrawn attention returns focus to the remaining Avatar control');
attentionView.mode.attention(3);assert.equal(reviewButton.textContent,'For you · 3');
attentionView.mode.close();assert.equal(attentionView.counts().leaves,1);assert.equal(restoreReview(),false,'Closed Avatar declines focus restoration so For you can use its ordinary opener');
console.log('Avatar attention: existing/live pending counts, review without capture stop, withdrawal and focus restoration passed.');

const ownerClosed=Promise.resolve(),closureView=boot({leaveResult:ownerClosed});
closureView.mode.configure(true,true);closureView.portrait.events.click();
assert.equal(closureView.mode.close(),ownerClosed,'Explicit read-aloud can await the engine closure barrier');
assert.equal(closureView.mode.close(),ownerClosed,'A timer-closed view retains its existing closure barrier');
assert.equal(closureView.counts().leaves,1,'Waiting again never closes/replays the engine twice');
const nativeRecovery=boot({reconnect:()=>{throw Error('Automatic replacement must not require a manual reconnect click');}});
nativeRecovery.mode.configure(true,true);nativeRecovery.portrait.events.click();
nativeRecovery.mode.update({continuousState:{active:false,starting:true,reconnecting:true,pending:false,working:false}});
const nativeRecoveryStatus=nativeRecovery.nodes.find(n=>n.className==='voice-mode-state');
const nativeRecoveryCaption=nativeRecovery.nodes.find(n=>n.className==='voice-mode-caption');
assert.equal(nativeRecoveryStatus.textContent,'Reconnecting voice');assert.match(nativeRecoveryCaption.textContent,/may need review/);
nativeRecovery.mode.update({playback:'idle'});assert.equal(nativeRecoveryStatus.textContent,'Reconnecting voice');
nativeRecovery.mode.update({continuousState:{active:true,starting:false,reconnecting:false,pending:false,working:false,message:'Listening'}});
assert.equal(nativeRecoveryStatus.textContent,'Listening');assert.equal(nativeRecoveryCaption.textContent,'');
nativeRecovery.mode.update({continuousState:{active:false,starting:true,reconnecting:true}});
nativeRecovery.mode.update({caption:'New audible words'});
nativeRecovery.mode.update({continuousState:{active:true,starting:false,reconnecting:false}});
assert.equal(nativeRecoveryCaption.textContent,'New audible words','Restoring the status must not erase a new provider caption');
nativeRecovery.mode.update({continuousState:{active:false,starting:true,reconnecting:true}});
nativeRecovery.mode.update({continuousState:{active:false,starting:false,reconnecting:false,message:'Voice replacement was not confirmed. Your originals are kept.'}});
assert.match(nativeRecoveryCaption.textContent,/not confirmed/);nativeRecovery.mode.close();
console.log('Native replacement view: explicit reconnection/original-review status, no manual click and no stale notice or lost new caption.');
