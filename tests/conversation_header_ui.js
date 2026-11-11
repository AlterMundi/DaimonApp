/* Scroll intent, focus retention and automatic-follow behavior; no browser/model. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('dashboard/web/conversation-header.js','utf8');
function fixture(enabled){
  const element=()=>({handlers:{},scrollTop:0,addEventListener(k,f){this.handlers[k]=f;},removeEventListener(k){delete this.handlers[k];}});
  const timeline=element(),header=element(),classes=new Set(),body={classList:{toggle(k,v){v?classes.add(k):classes.delete(k);}}};
  let now=100;const document={body,activeElement:null};header.contains=x=>x===header;
  const window={};vm.runInNewContext(source,{window,document,WeakMap,Math,performance:{now:()=>now}});
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
