"use strict";
// Existing trusted usage receipts only: no clock-based bill, API or persistence.
window.PublicLiveUsage=(()=>{
  const rate={usdPerMinute:.05,checked:'2026-11-07',url:'https://developers.openai.com/api/docs/pricing'};
  const seconds=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0&&value<=86400?value:null;
  function summary(value){
    const final=value.finalization,confirmed=final?.voice_usage_confirmed===true?seconds(final.usage_seconds):null;
    if(confirmed!==null)return `${confirmed.toFixed(3).replace(/\.?0+$/,'')}s confirmed · voice estimate USD ${(confirmed*rate.usdPerMinute/60).toFixed(4)}`;
    const latest=seconds(value.usage?.seconds);
    return (latest===null?'Usage not received':`${latest.toFixed(3).replace(/\.?0+$/,'')}s observed`)
      +(value.closed?' · final usage unconfirmed':' · provisional');
  }
  function mount(root){
    if(!root)return {observe(){},reset(){}};
    const rows=new Map();
    function render(){
      root.hidden=rows.size===0;const list=root.querySelector('ol');list.replaceChildren();
      for(const value of [...rows.values()].reverse()){
        const item=document.createElement('li');
        item.textContent=(value.backend==='native'?'Native Codex backend':value.backend==='responses'?'Responses backend':'Backend not yet confirmed')+' · '+summary(value);
        list.append(item);
      }
    }
    return {observe(value){
      if(!value||typeof value.visit!=='string'||!/^[a-f0-9-]{36}$/.test(value.visit))return;
      const before=rows.get(value.visit)||{};
      const next={...before};
      if(['native','responses'].includes(value.backend))next.backend=value.backend;
      if(value.usage)next.usage={seconds:seconds(value.usage.seconds)};
      if(value.finalization)next.finalization={voice_usage_confirmed:value.finalization.voice_usage_confirmed===true,usage_seconds:seconds(value.finalization.usage_seconds)};
      if(value.closed===true)next.closed=true;
      rows.set(value.visit,next);
      if(rows.size>8)rows.delete(rows.keys().next().value);
      render();
    },reset(){rows.clear();render();}};
  }
  return {mount,summary,rate};
})();
