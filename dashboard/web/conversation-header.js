/* Header compaction is paused during the interface redesign. */
(() => {
  const mounted = new WeakMap();
  function pageScroll(timeline,body){
    if(!document.addEventListener)return;
    const wheel=event=>{
      if(event.defaultPrevented||event.ctrlKey||event.metaKey||event.shiftKey||!event.deltaY
          ||!timeline.getClientRects().length||timeline.contains(event.target)
          ||document.querySelector('dialog[open],[aria-modal="true"]:not([hidden])'))return;
      if(event.target.closest?.('input,textarea,select,[contenteditable],iframe'))return;
      for(let node=event.target;node&&node!==body;node=node.parentElement){
        if(node.nodeType!==1)continue;
        const style=getComputedStyle(node);
        if(/auto|scroll/.test(style.overflowY)&&node.scrollHeight>node.clientHeight+1)return;
      }
      const scale=event.deltaMode===1?16:event.deltaMode===2?timeline.clientHeight:1;
      const before=timeline.scrollTop;
      timeline.scrollTop+=event.deltaY*scale;
      if(timeline.scrollTop!==before)event.preventDefault();
    };
    document.addEventListener('wheel',wheel,{passive:false});
    return {expand(){},syncScroll(){},destroy(){document.removeEventListener('wheel',wheel);}};
  }
  function mount({timeline,header=document.querySelector('header'),body=document.body,clock=()=>performance.now(),enabled=false}) {
    if(!timeline || !header)return;
    if(!enabled){
      body.classList.toggle('conversation-header-compact',false);
      if(mounted.has(timeline))return mounted.get(timeline);
      const relay=pageScroll(timeline,body);
      if(relay){const destroy=relay.destroy;relay.destroy=()=>{destroy();mounted.delete(timeline);};mounted.set(timeline,relay);}
      return relay;
    }
    if(mounted.has(timeline))return mounted.get(timeline);
    let previous=timeline.scrollTop,travel=0,direction=0,intentUntil=0,touchY,compact=false;
    const listeners=[];
    const on=(element,type,handler)=>{element.addEventListener(type,handler,{passive:true});listeners.push(()=>element.removeEventListener(type,handler));};
    function show(value){
      if(value && header.contains(document.activeElement))value=false;
      if(compact===value)return;
      compact=value;body.classList.toggle('conversation-header-compact',compact);
      // Header height changes may clamp the timeline; those are not new intent.
      previous=timeline.scrollTop;travel=0;
    }
    function intent(delta){
      const next=Math.sign(delta);if(!next)return;
      if(direction!==next)travel=0;
      direction=next;intentUntil=clock()+500;
    }
    on(timeline,'wheel',event=>intent(event.deltaY));
    on(timeline,'touchstart',event=>{touchY=event.touches[0]?.clientY;});
    on(timeline,'touchmove',event=>{const y=event.touches[0]?.clientY;if(touchY!==undefined && y!==undefined)intent(touchY-y);touchY=y;});
    on(timeline,'touchend',()=>{touchY=undefined;});
    on(timeline,'pointerdown',()=>{direction=0;travel=0;intentUntil=clock()+1000;});
    on(timeline,'keydown',event=>{
      if(event.target?.closest?.('input,textarea,select,[contenteditable="true"]'))return;
      if(['ArrowDown','PageDown','End',' '].includes(event.key))intent(event.shiftKey?-1:1);
      if(['ArrowUp','PageUp','Home'].includes(event.key))intent(-1);
    });
    on(timeline,'scroll',()=>{
      const top=timeline.scrollTop,delta=top-previous;previous=top;
      if(top<=8){show(false);return;}
      if(clock()>intentUntil || Math.abs(delta)<1)return;
      const next=Math.sign(delta);
      if(direction && next!==direction)return;
      if(direction!==next){direction=next;travel=0;}
      travel+=Math.abs(delta);
      if(next>0 && top>64 && travel>=40)show(true);
      if(next<0 && travel>=24)show(false);
    });
    on(header,'focusin',()=>show(false));
    const control={expand:()=>show(false),syncScroll:()=>{previous=timeline.scrollTop;travel=0;direction=0;intentUntil=0;},destroy(){listeners.forEach(close=>close());show(false);mounted.delete(timeline);}};
    mounted.set(timeline,control);return control;
  }
  window.ConversationHeader={mount};
})();
