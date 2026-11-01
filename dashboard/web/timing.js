"use strict";
/* Bounded, page-local observation. No media, transcript, storage or network. */
window.ConversationTiming=(()=>{
  function mount({now=()=>performance.now()}={}){
    const list=document.querySelector('#conversation-timing-records'),pause=document.querySelector('#conversation-timing-pause'),clear=document.querySelector('#conversation-timing-clear');
    if(!list || !pause || !clear)return;
    const recordings=new Map(),sources=new Map();let binding,sequence=0,outputSequence=0,pauseMillis,origin=now();
    const gates={waiting_speech:'waiting for detected speech',speaking:'speech detected',waiting_endpoint:'waiting for a complete phrase',waiting_analysis:'waiting for analysis to cover captured sound',waiting_transcript:'waiting for transcript',finishing:'finishing audio',confirming:'confirming original',confirmed:'original confirmed',review:'recording needs review'};
    const positive=value=>Number.isSafeInteger(value)&&value>0;
    const duration=(start,end)=>Number.isFinite(start)&&Number.isFinite(end)&&end>=start?`${((end-start)/1000).toFixed(2)} s`:'not observed';
    const element=(tag,text)=>{const node=document.createElement(tag);node.textContent=text;return node;};
    const point=value=>Number.isFinite(value)&&value>=origin?`+${((value-origin)/1000).toFixed(2)} s`:'not observed';
    function render(){
      pause.textContent=pauseMillis===undefined?'':`Pause applied: ${pauseMillis.toFixed(1)} ms (browser handler, not acoustic silence).`;
      const rows=[];
      for(const recording of [...recordings.values()].reverse()){
        const stages=recording.stages,peers=[...recordings.values()].filter(r=>positive(recording.local)&&r.local===recording.local);
        const shared=peers.length>1;
        const matches=!shared&&positive(recording.local)?[...sources.values()].filter(s=>s.local===recording.local):[];
        const first=field=>Math.min(...matches.map(s=>s[field]).filter(t=>Number.isFinite(t)&&t>=stages.send));
        const row=element('li','');row.append(element('strong',`Recording ${recording.sequence}`));
        if(recording.native){
          row.append(element('p',`Native voice · Capture start: ${point(stages.started)} · Detected end: ${point(stages.ended)}`));
          row.append(element('p',`Detected end → local WAV saved: ${duration(stages.ended,stages.retained)} · Detected end → interpretation received: ${duration(stages.ended,stages.interpreted)} · Detected end → original confirmed: ${duration(stages.ended,stages.confirmed)}`));
          row.append(element('p','Output timing is separate: an asynchronous return is not assigned to this phrase.'));rows.push(row);continue;
        }
        row.append(element('p',`First caption: ${duration(stages.started,stages.partial)} · Stop → saved: ${duration(stages.ended,stages.retained)}`));
        if(recording.handoff){
          const h=recording.handoff,seconds=value=>Number.isSafeInteger(value)?`${(value/1000).toFixed(2)} s`:'not observed';
          row.append(element('p',`Turn handoff: ${gates[h.gate]}${h.review_after?` (after ${gates[h.review_after]})`:''} · Captured: ${seconds(h.captured_ms)} · Analyzed: ${seconds(h.analyzed_ms)} · Acoustic fence: ${seconds(h.fence_ms)} · Captions: ${h.words?'present':'not observed'}.`));
        }
        if(recording.preparation){
          const t=recording.preparation,ms=key=>Number.isFinite(t[key])?`${(t[key]/1000).toFixed(2)} s`:'not observed';
          row.append(element('p',`Server finish → prepared: ${ms('finish_to_prepared_ms')} · Finish authorization: ${ms('finish_authorization_ms')} · Provider final: ${ms('provider_final_ms')} · Final authorization: ${ms('final_authorization_ms')} · Receipt write: ${ms('receipt_write_ms')} (server intervals; not final speech or sound).`));
        }
        row.append(element('p',shared?'Shared native turn; response timing unassigned.':`Send → same-turn text: ${duration(stages.send,first('seen'))} · Send → playback: ${duration(stages.send,first('playing'))}`));
        rows.push(row);
      }
      for(const output of [...sources.values()].filter(s=>s.native).reverse()){
        const row=element('li','');row.append(element('strong',`Voice output ${output.sequence}`));
        row.append(element('p',`First PCM handled: ${point(output.handled)} · First buffer scheduled: ${point(output.scheduled)} · First buffer ended: ${point(output.buffer_ended)} · Output retired: ${point(output.retired)}`));
        row.append(element('p','Page-relative browser events; no phrase attribution or proof of sound heard.'));rows.push(row);
      }
      if(!rows.length)rows.push(element('li','No recordings measured on this page.'));
      list.replaceChildren(...rows);
    }
    function reset(){recordings.clear();sources.clear();sequence=outputSequence=0;pauseMillis=undefined;origin=now();render();}
    clear.addEventListener('click',reset);
    function bind(value){if(binding!==value){binding=value;reset();}}
    function mark(id,stage,detail){
      if(typeof id!=='string'||id.length>128||!['requested','started','partial','ended','send','ready','retained','discarded','prepared','handoff','interpreted','confirmed'].includes(stage))return;
      let recording=recordings.get(id);
      if(!recording){if(stage!=='requested')return;recording={sequence:++sequence,stages:{},native:detail?.native===true};recordings.set(id,recording);while(recordings.size>8)recordings.delete(recordings.keys().next().value);}
      if(stage==='handoff'){
        if(!detail||!Object.hasOwn(gates,detail.gate)||typeof detail.words!=='boolean')return;
        const clean={gate:detail.gate,words:detail.words};
        for(const key of ['captured_ms','analyzed_ms','fence_ms']){
          if(Number.isSafeInteger(detail[key])&&detail[key]>=0&&detail[key]<=120000)clean[key]=detail[key];
        }
        if(Object.hasOwn(gates,detail.review_after))clean.review_after=detail.review_after;
        const old=recording.handoff;
        if(old?.gate==='confirmed'||old?.gate==='review'&&clean.gate!=='review')return;
        recording.handoff=clean;render();return;
      }
      if(recording.stages[stage]!==undefined)return;
      if(stage==='prepared'){
        if(!detail||typeof detail!=='object'||Array.isArray(detail))return;
        const clean={};
        for(const key of ['finish_to_prepared_ms','finish_authorization_ms','provider_final_ms','final_authorization_ms','receipt_write_ms']){
          if(Number.isFinite(detail[key])&&detail[key]>=0&&detail[key]<=140000)clean[key]=detail[key];
        }
        if(!Object.keys(clean).length)return;
        recording.preparation=clean;
      }
      recording.stages[stage]=now();render();
    }
    function native(id,stage){
      if(typeof id!=='string'||!id.length||id.length>128)return;
      if(stage==='capture_started'){mark(id,'requested',{native:true});mark(id,'started');return;}
      const inputStage={phrase_end:'ended',local_retained:'retained',input_interpreted:'interpreted',original_confirmed:'confirmed'};
      if(Object.hasOwn(inputStage,stage)){if(recordings.get(id)?.native)mark(id,inputStage[stage]);return;}
      const outputStage={output_handled:'handled',output_scheduled:'scheduled',output_buffer_ended:'buffer_ended',output_retired:'retired'};
      if(!Object.hasOwn(outputStage,stage))return;
      const key='foreground:'+id;let output=sources.get(key);
      if(!output){if(stage!=='output_handled')return;output={native:true,sequence:++outputSequence};sources.set(key,output);while(sources.size>16)sources.delete(sources.keys().next().value);}
      if(!output.native||output[outputStage[stage]]!==undefined)return;
      output[outputStage[stage]]=now();render();
    }
    function input(value){
      const recording=recordings.get(value.id);
      if(!recording||!positive(value.local_turn)||value.phase!=='accepted'||recording.local===value.local_turn)return;
      recording.local=value.local_turn;render();
    }
    function source(value,playing=false){
      if(!value?.kind?.startsWith('integrator_')||value.current===false||value.correction_pending||value.native_binding_current===false)return;
      const key=typeof value.native_turn==='string'&&typeof value.native_item==='string'?`${value.native_turn}:${value.native_item}`:value.id;
      if(typeof key!=='string'||key.length>512)return;
      let local=value.local_turn;
      if(!positive(local)&&typeof value.native_turn==='string')local=[...sources.values()].find(s=>s.turn===value.native_turn)?.local;
      if(!positive(local))return;
      let item=sources.get(key);
      if(!item){item={local,turn:value.native_turn};sources.set(key,item);while(sources.size>16)sources.delete(sources.keys().next().value);}
      if(item.local!==local)return;
      const field=playing?'playing':'seen';if(item[field]!==undefined)return;
      item[field]=now();render();
    }
    function pauseApplied(start){if(!Number.isFinite(start))return;const elapsed=now()-start;if(elapsed>=0&&elapsed<60000){pauseMillis=elapsed;render();}}
    render();return {bind,mark,native,input,source,pauseApplied};
  }
  return {mount};
})();
