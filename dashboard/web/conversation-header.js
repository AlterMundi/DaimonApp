/* User-directed scrolling frees reading space; automatic speech following does not. */
(() => {
  const mounted = new WeakMap();
  function mount({timeline,header=document.querySelector('header'),body=document.body,clock=()=>performance.now()}) {
    if(!timeline || !header)return;
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
    const control={expand:()=>show(false),destroy(){listeners.forEach(close=>close());show(false);mounted.delete(timeline);}};
    mounted.set(timeline,control);return control;
  }
  window.ConversationHeader={mount};
})();
