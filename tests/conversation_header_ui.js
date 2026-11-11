/* Scroll intent, focus retention and automatic-follow behavior; no browser/model. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('dashboard/web/conversation-header.js','utf8');
function fixture(enabled,relay=false){
  const element=()=>({handlers:{},scrollTop:0,addEventListener(k,f){this.handlers[k]=f;},removeEventListener(k){delete this.handlers[k];}});
  const timeline=element(),header=element(),classes=new Set(),body={classList:{toggle(k,v){v?classes.add(k):classes.delete(k);}}};
  let now=100;const document={body,activeElement:null};header.contains=x=>x===header;
  document.handlers={};document.querySelector=()=>document.modal||null;
  if(relay){document.addEventListener=(k,f)=>{document.handlers[k]=f;};document.removeEventListener=k=>{delete document.handlers[k];};timeline.getClientRects=()=>[{}];timeline.contains=node=>node===timeline;timeline.clientHeight=200;}
  const window={};vm.runInNewContext(source,{window,document,WeakMap,Math,getComputedStyle:node=>({overflowY:node.overflowY||'visible'}),performance:{now:()=>now}});
  const control=window.ConversationHeader.mount({timeline,header,body,clock:()=>now,enabled});
  const scroll=y=>{timeline.scrollTop=y;timeline.handlers.scroll();};
  return {timeline,header,document,control,scroll,compact:()=>classes.size>0,tick:()=>{now+=1000;}};
}
const paused=fixture();assert.equal(paused.compact(),false);assert.equal(Object.keys(paused.timeline.handlers).length,0,'Default presentation keeps the full header without scroll listeners');
let f=fixture(true);f.scroll(200);assert.equal(f.compact(),false,'Programmatic following cannot hide the header');
f.timeline.handlers.wheel({deltaY:120});f.scroll(250);assert.equal(f.compact(),true);
f.timeline.handlers.wheel({deltaY:-100});f.scroll(220);assert.equal(f.compact(),false);
f.timeline.handlers.wheel({deltaY:100});f.scroll(230);assert.equal(f.compact(),false,'Ignore small direction jitter');
f.scroll(270);assert.equal(f.compact(),true);f.scroll(0);assert.equal(f.compact(),false);
f.timeline.handlers.wheel({deltaY:100});f.tick();f.scroll(100);assert.equal(f.compact(),false,'Expired intent cannot hide on a later update');
f.document.activeElement=f.header;f.timeline.handlers.wheel({deltaY:100});f.scroll(200);assert.equal(f.compact(),false,'Keep focused header controls visible');
f.document.activeElement=null;f.timeline.handlers.keydown({key:'PageDown'});f.scroll(260);assert.equal(f.compact(),true);
f.header.handlers.focusin();assert.equal(f.compact(),false);
f.timeline.handlers.touchstart({touches:[{clientY:200}]});f.timeline.handlers.touchmove({touches:[{clientY:100}]});f.scroll(320);assert.equal(f.compact(),true);
f.timeline.handlers.wheel({deltaY:-100});f.scroll(290);assert.equal(f.compact(),false);
f.timeline.handlers.pointerdown();f.timeline.scrollTop=450;f.control.syncScroll();f.timeline.handlers.scroll();
assert.equal(f.compact(),false,'Loading earlier history preserves the scroll anchor without consuming click intent as scrolling');
f.timeline.handlers.wheel({deltaY:100});f.scroll(510);assert.equal(f.compact(),true,'Real scrolling works after anchor synchronization');
f.control.destroy();assert.equal(f.compact(),false);assert.equal(Object.keys(f.timeline.handlers).length,0);
console.log('Conversation header scroll/focus/touch/keyboard cases passed');

const page=fixture(undefined,true),background={nodeType:1,parentElement:page.document.body};
function wheel(target=background,more={}){const event={target,deltaY:20,deltaMode:0,preventDefault(){this.prevented=true;},...more};page.document.handlers.wheel(event);return event;}
assert(wheel().prevented);assert.equal(page.timeline.scrollTop,20,'Outer page wheel scrolls the chat');
wheel(page.timeline);assert.equal(page.timeline.scrollTop,20,'Native chat wheel is not applied twice');
wheel(background,{ctrlKey:true});assert.equal(page.timeline.scrollTop,20,'Zoom gesture stays native');
wheel({nodeType:1,parentElement:background,overflowY:'auto',scrollHeight:400,clientHeight:100});assert.equal(page.timeline.scrollTop,20,'Other scrolling panels retain their wheel');
wheel({closest:()=>({})});assert.equal(page.timeline.scrollTop,20,'Editors retain their native wheel behavior');
page.document.modal={};wheel();assert.equal(page.timeline.scrollTop,20,'Modal dialogs isolate the chat');page.document.modal=null;
wheel(background,{deltaMode:1,deltaY:2});assert.equal(page.timeline.scrollTop,52);
wheel(background,{deltaMode:2,deltaY:1});assert.equal(page.timeline.scrollTop,252);
page.control.destroy();assert.equal(Object.keys(page.document.handlers).length,0,'Teardown removes the page relay');
console.log('Outer page wheel ownership, zoom, editor and modal cases passed');
