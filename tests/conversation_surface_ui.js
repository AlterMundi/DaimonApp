// Canonical frame protocol: synthetic parent/file metadata only, zero media/models.
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),crypto=require('node:crypto').webcrypto;
const id=()=>crypto.randomUUID(),binding='b'.repeat(64),actor='human:fixture:one';
function boot(){
 const sent=[],events={},timers=[],parent={postMessage:(message,origin)=>sent.push({message,origin})};
 const window={parent,addEventListener:(name,fn)=>events[name]=fn,removeEventListener:()=>{}};
 const context={window,crypto,document:{documentElement:{dataset:{surfaceParent:'https://world.test',surfaceVisit:id()}}},setTimeout:(fn,ms)=>{const t={fn,ms};timers.push(t);return t;},clearTimeout:t=>{t.closed=true;}};
 vm.runInNewContext(fs.readFileSync('dashboard/web/conversation-surface.js','utf8'),context);
 const ui=window.ConversationSurface.create();ui.identity(actor);ui.bind(binding);const envelope=sent.at(-1).message;
 const receive=(value,source=parent,origin='https://world.test')=>events.message({source,origin,data:{...envelope,...value}});
 return{ui,sent,timers,receive,parent,events,envelope};
}
(async()=>{
 const b=boot();assert.equal(b.sent.length,1);assert.equal(b.sent[0].message.type,'ready');
 assert.equal(b.sent[0].origin,'https://world.test');
 await assert.rejects(b.ui.prepare({id:id(),binding,modality:'text'}));
 b.receive({type:'connect'},{});await assert.rejects(b.ui.prepare({id:id(),binding,modality:'text'}));
 b.receive({type:'connect'},b.parent,'https://evil.test');await assert.rejects(b.ui.prepare({id:id(),binding,modality:'text'}));
 b.receive({type:'connect',actor:'human:other'});await assert.rejects(b.ui.prepare({id:id(),binding,modality:'text'}));
 b.receive({type:'connect'});
 for(const modality of ['text','audio']){
  const original=id(),promise=b.ui.prepare({id:original,binding,modality,files:[]}),request=b.sent.at(-1).message;
  assert.equal(request.id,original);assert.equal(request.modality,modality);assert(!('text' in request));
  const file={file_id:id(),sha256:'a'.repeat(64),name:'holodeck-situation.json',mime:'application/json',size:64000};
  b.receive({...request,type:'prepared',binding:'c'.repeat(64),file});assert(!b.timers.at(-1).closed);
  b.receive({...request,type:'prepared',file:{...file,size:65537}});assert(!b.timers.at(-1).closed);
  b.receive({...request,type:'prepared',request:id(),file});assert(!b.timers.at(-1).closed);
  b.receive({...request,type:'prepared',file});assert.equal((await promise)[0].sha256,file.sha256);
  b.ui.status({id:original,phase:'accepted',text:'PRIVATE',files:[file],audio:'PRIVATE'},true);
  assert.deepEqual(Object.keys(b.sent.at(-1).message).sort(),['actor','binding','busy','channel','id','phase','schema','type','visit'].sort());
 }
 const count=b.sent.length;b.ui.status({id:id(),phase:'accepted',text:'unrelated private history'});assert.equal(b.sent.length,count);
 await assert.rejects(b.ui.prepare({id:id(),binding,modality:'text',files:Array(8).fill({size:1})}));
 await assert.rejects(b.ui.prepare({id:id(),binding,modality:'audio',files:[{size:40*1024*1024}]}));
 const timeout=b.ui.prepare({id:id(),binding,modality:'text'});b.timers.at(-1).fn();await assert.rejects(timeout);assert.equal(b.sent.at(-1).message.type,'prepare','Timeout never sends another request');
 const cancelledId=id(),cancelled=b.ui.prepare({id:cancelledId,binding,modality:'audio'});const cancelRequest=b.sent.at(-1).message;
 b.ui.discard({id:cancelledId,binding,reason:'capture-cancelled'});await assert.rejects(cancelled);assert.equal(b.sent.at(-1).message.type,'discard');assert.equal(b.sent.at(-1).message.id,cancelledId);
 const afterDiscard=b.sent.length;b.ui.discard({id:cancelledId,binding,reason:'capture-cancelled'});b.receive({...cancelRequest,type:'prepared',file:{file_id:id(),sha256:'a'.repeat(64),name:'holodeck-situation.json',mime:'application/json',size:5}});assert.equal(b.sent.length,afterDiscard);
 const attemptedId=id(),attempted=b.ui.prepare({id:attemptedId,binding,modality:'text'}),prepared=b.sent.at(-1).message;
 b.receive({...prepared,type:'prepared',file:{file_id:id(),sha256:'a'.repeat(64),name:'holodeck-situation.json',mime:'application/json',size:5}});await attempted;b.ui.attempt({id:attemptedId,binding});const beforeUnsafe=b.sent.length;b.ui.discard({id:attemptedId,binding,reason:'preparation-failed'});assert.equal(b.sent.length,beforeUnsafe,'No source-only discard after any original attempt, including unknown outcomes');
 const changed=b.ui.prepare({id:id(),binding,modality:'audio'});b.ui.bind('c'.repeat(64));await assert.rejects(changed);
 const gone=boot();gone.receive({type:'connect'});const pending=gone.ui.prepare({id:id(),binding,modality:'audio'});gone.events.pagehide();await assert.rejects(pending);const beforeReturn=gone.sent.length;gone.events.pageshow({persisted:true});assert.equal(gone.sent.length,beforeReturn+1);assert.equal(gone.sent.at(-1).message.type,'ready','BFCache return needs a fresh handshake and never repeats preparation');
 console.log('PASS exact parent/frame/actor/binding/visit/channel, text/audio IDs, capacity, no private payload, no timeout replay and lifecycle fencing');
})().catch(e=>{console.error(e);process.exitCode=1;});
