/* One owner-scoped workspace. Refresh reuses Conversation's existing events;
 * no timer, transcript persistence, model call or alternate routing store. */
(() => {
  const pinIcon='<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m15 3 6 6-4 1-3 5-5-5 5-3Z"/><path d="m9 15-6 6"/></svg>';
  const replyIcon='<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16v12H9l-5 5Z"/><path d="M8 8h8M8 12h5"/></svg>';
  const muteIcon=muted=>'<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H3v6h3l5 4Z"/>'+
    (muted?'<path d="m16 9 5 6m0-6-5 6"/>':'<path d="M15 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>')+'</svg>';
  const active=row=>row.fresh===true&&(row.execution==='working'||row.execution==='running'||row.tools_running===true||row.goal_state==='active');
  const copy=value=>value&&JSON.parse(JSON.stringify(value));
  const el=(tag,text,cls)=>{const item=document.createElement(tag);if(text!==undefined)item.textContent=text;if(cls)item.className=cls;return item;};
  const button=(text,label,click)=>{const item=el('button',text);item.type='button';item.title=label;item.setAttribute('aria-label',label);item.addEventListener('click',click);return item;};
  function mount({timeline,api,onTarget=()=>{},onReply=()=>{},audio=()=>({}),onAudio=()=>{},onReady=()=>{}}){
    if(!timeline?.parentNode)return;
    const shell=el('section',undefined,'session-workspace'),toolbar=el('div',undefined,'session-workspace-toolbar');
    shell.hidden=false;toolbar.hidden=true;shell.setAttribute('aria-label','Session workspace');
    const rail=el('aside',undefined,'session-rail');rail.id='session-rail';rail.hidden=true;rail.setAttribute('aria-label','Your sessions');
    const list=el('div',undefined,'session-list'),target=el('span','Conversation','session-input-target');
    const toggle=button('☰','Show sessions',()=>showRail(rail.hidden));
    function showRail(open){if(open)void refresh(binding);rail.hidden=!open;toggle.setAttribute('aria-expanded',String(open));toggle.title=open?'Hide sessions':'Show sessions';toggle.setAttribute('aria-label',toggle.title);}
    toggle.setAttribute('aria-controls',rail.id);toggle.setAttribute('aria-expanded','false');
    const reset=button('↺ Reset','Hear all sessions: clear mute and solo',()=>{onAudio('reset');toggle.focus?.();});
    reset.className='session-workspace-reset';
    const unpin=button('⌖','Send to the conversation',()=>{pin=undefined;expanded=undefined;leave();changed();});
    unpin.innerHTML=pinIcon;
    const status=el('p','','session-workspace-status');status.setAttribute('role','status');
    const retryStatus=button('Retry status','Retry session status',()=>refresh(binding));retryStatus.hidden=true;retryStatus.className='session-workspace-retry';
    const body=el('div',undefined,'session-workspace-body'),content=el('div',undefined,'session-workspace-content');
    const view=el('section',undefined,'session-conversation');view.hidden=true;view.setAttribute('aria-label','Selected session conversation');
    const viewBar=el('div',undefined,'session-view-toolbar'),heading=el('h3','Session');
    const back=button('←','Back to the conversation',()=>{expanded=undefined;leave();changed();toggle.focus?.();});
    const technicalButton=button('>_','Show tools and exposed reasoning summaries',()=>{technical=!technical;technicalButton.setAttribute('aria-pressed',String(technical));clearHistory();void history();});
    technicalButton.setAttribute('aria-pressed','false');
    const earlier=button('Earlier','Read earlier messages',()=>history('before'));
    const newer=button('Newer','Read newer messages',()=>history('after'));
    const retryHistory=button('Retry reading','Retry reading this conversation',()=>history(retryDirection));retryHistory.hidden=true;
    const entries=el('div',undefined,'session-messages');entries.setAttribute('role','log');entries.setAttribute('aria-label','Selected session messages');
    const historyStatus=el('p','','session-history-status');historyStatus.setAttribute('role','status');
    viewBar.append(heading,technicalButton);view.append(viewBar,historyStatus,retryHistory,earlier,entries,newer);
    window.ConversationHeader?.mount({timeline:entries});
    shell.addEventListener('keydown',event=>{if(event.key==='Escape'&&!rail.hidden){showRail(false);toggle.focus?.();event.stopPropagation();}});
    const railHeader=el('div',undefined,'session-rail-header');railHeader.append(el('h3','Sessions · 24h'),reset);
    rail.append(railHeader,list);toolbar.append(toggle,back,target,unpin);body.append(rail,content);shell.append(body,status,retryStatus,toolbar);
    timeline.before(shell);content.append(timeline,view);
    let binding,epoch=0,inventory=new Map(),rows=new Map(),pin,expanded,technical=false,allowed=false,loading=false,complete=false;
    let activeHistory,retryDirection,historyBusy=false,historyEpoch=0,observedAt=0;
    function selected(){return expanded||pin;}
    function capture(){const value=selected();return value?copy({selected:true,...(!value.is_entry?{reference:value.destination}:{})}):undefined;}
    function changed(){renderSelection();onTarget();}
    function renderSelection(){
      const current=selected();target.textContent=current&&!current.is_entry?`To ${current.title}`:'To the conversation';
      back.hidden=!expanded;
      unpin.hidden=!current;unpin.setAttribute('aria-pressed',String(!!pin&&pin.id===current?.id));
      unpin.title=pin?`Unpin ${pin.title}: send to the conversation`:'Send to the conversation';
      for(const [id,row] of rows){row.pin.setAttribute('aria-pressed',String(pin?.id===id));row.name.setAttribute('aria-current',String(expanded?.id===id));}
    }
    function sourceRow(source){
      if(!allowed||!complete||!source)return;
      const entry=['integrator_answer','integrator_progress','integrator_live'].includes(source.kind)||source.kind==='native_question'&&source.audio_track==='conversation';
      const target=source.target;
      if(!entry&&(!['worker_progress','worker_result','native_question'].includes(source.kind)||!Number.isSafeInteger(target?.chat_id)||!Number.isSafeInteger(target?.thread_id)))return;
      const matches=[...inventory.values()].filter(row=>entry?row.is_entry===true:row.audio_key===`${target.chat_id}:${target.thread_id}`);
      if(matches.length!==1)return;
      const row=matches[0];if(row.is_entry||row.destination?.source&&row.destination?.revision)return row;
    }
    function pinState(source){const row=sourceRow(source);return {available:!!row,pinned:!!row&&pin?.id===row.id};}
    function setPin(row){
      if(!allowed||!row||!row.is_entry&&!row.destination)return false;
      if(row.is_entry)pin=undefined;
      else pin=pin?.id===row.id?undefined:{id:row.id,title:row.title,destination:copy(row.destination)};
      if(expanded&&expanded.id!==row.id){expanded=undefined;leave();}
      changed();showRail(false);toggle.focus?.();return true;
    }
    function pinSource(source){return setPin(sourceRow(source));}
    function leave(){historyEpoch++;historyBusy=false;view.hidden=true;timeline.hidden=false;clearHistory();renderSelection();}
    function clearHistory(){historyEpoch++;historyBusy=false;activeHistory=undefined;entries.replaceChildren();earlier.hidden=true;newer.hidden=true;historyStatus.textContent='';retryHistory.hidden=true;}
    function open(row){
      if(row.is_entry){expanded={id:row.id,title:row.title,is_entry:true};leave();showRail(false);changed();toggle.focus?.();return;}
      if(!row.destination){status.textContent='This session is unavailable for direct input. Its status remains visible.';return;}
      expanded={id:row.id,title:row.title,destination:copy(row.destination)};
      clearHistory();view.hidden=false;timeline.hidden=true;heading.textContent=row.title;
      showRail(false);changed();back.focus?.();void history();
    }
    function annotate(row){
      const states=[];
      if(row.human_action_pending)states.push('◆ Needs you');
      if(row.results_review===true || row.results_review==='pending')states.push('▣ Results to review');
      else if(row.result_available===true)states.push('▣ Result available');
      if(row.goal_state==='blocked')states.push('⏸ Goal blocked');
      else if(row.goal_state==='active')states.push('◎ Goal active');
      if(row.tools_running)states.push('⚒ Tools running');
      if(row.execution==='working' || row.execution==='running')states.push('⚙ Working');
      else if(row.execution==='idle')states.push('○ Idle');
      if(row.error)states.push('! Needs attention');
      if(!row.fresh)states.push('◌ Status not current');
      if(!states.length)states.push('? Status unknown');
      return states.join(' · ');
    }
    function syncAudio(){
      let filtered=!!audio({}).filtered;
      for(const [id,row] of rows){
        const value=audio(row.data);filtered ||= !!value.filtered;
        row.mute.setAttribute('aria-pressed',String(!!value.muted));row.solo.setAttribute('aria-pressed',String(!!value.solo));
        row.mute.title=`${value.muted?'Unmute':'Mute'} ${row.data.title}`;row.mute.setAttribute('aria-label',row.mute.title);
        row.solo.title=`${value.solo?'Remove solo from':'Solo'} ${row.data.title}`;row.solo.setAttribute('aria-label',row.solo.title);
        row.mute.innerHTML=muteIcon(!!value.muted);
      }
      reset.hidden=!filtered;
    }
    function render(){
      // Visibility is separate from intent: an expired row must not silently
      // erase a selected pin or change the target of an existing recording.
      const recent=[...inventory.values()].filter(row=>active(row)||Number.isFinite(row.last_activity_at)&&row.last_activity_at>=observedAt-86400)
        .sort((a,b)=>Number(active(b))-Number(active(a))||(b.last_activity_at||0)-(a.last_activity_at||0)||a.id.localeCompare(b.id));
      const visible=new Set(recent.map(row=>row.id));
      for(const [id,row] of rows)if(!visible.has(id)){row.box.remove();rows.delete(id);}
      for(const data of recent){
        let row=rows.get(data.id);
        if(!row){
          row={data,box:el('article',undefined,'session-row')};
          row.name=button('',data.title,()=>open(row.data));row.name.className='session-name';
          row.state=el('p','','session-row-state');
          row.reply=button('▱','Reply to the latest message',()=>{const ref=row.data.latest_reply;if(ref){showRail(false);onReply(copy(ref),row.data.title);}});
          row.pin=button('⌖','Pin as the input destination',()=>setPin(row.data));
          row.pin.innerHTML=pinIcon;row.reply.innerHTML=replyIcon;
          row.mute=button('','Mute this session',()=>onAudio('mute',row.data));
          row.solo=button('S','Solo this session',()=>onAudio('solo',row.data));
          const actions=el('div',undefined,'session-row-actions');actions.append(row.reply,row.pin,row.mute,row.solo);
          row.box.append(row.name,row.state,actions);rows.set(data.id,row);
        }
        row.data=data;row.name.textContent=data.title;row.name.title=data.title;row.state.textContent=annotate(data);
        row.box.dataset.attention=String(!!data.human_action_pending||!!data.error||data.goal_state==='blocked');
        row.box.dataset.fresh=String(!!data.fresh);row.reply.disabled=!data.latest_reply;row.pin.disabled=!data.is_entry&&!data.destination;
        list.append(row.box); // Existing nodes retain focus while activity reorders.
      }
      renderSelection();syncAudio();
    }
    function resetBinding(next){
      epoch++;loading=false;binding=next;pin=undefined;expanded=undefined;inventory.clear();rows.clear();list.replaceChildren();leave();
      allowed=false;complete=false;shell.hidden=false;toolbar.hidden=true;status.textContent='';retryStatus.hidden=true;onReady(false);onTarget();
    }
    async function refresh(nextBinding){
      if(binding!==nextBinding)resetBinding(nextBinding);
      if(loading||!binding)return;
      loading=true;const owned=epoch;
      try{
        const value=await api('interaction/sessions');if(owned!==epoch)return;
        if(value.schema!=='daimon.session-workspace/v1'||!Array.isArray(value.sessions)||value.sessions.length>128)throw Error('Session workspace unavailable');
        observedAt=Number.isFinite(value.observed_at)&&value.observed_at>0?value.observed_at:Date.now()/1000;
        inventory=new Map(value.sessions.map(row=>[row.id,row]));complete=value.truncated!==true;allowed=true;shell.hidden=false;toolbar.hidden=false;status.textContent='';retryStatus.hidden=true;
        // Never silently redirect a selected target after grant/binding loss.
        for(const selection of [pin,expanded].filter(value=>value&&!value.is_entry)){
          const row=inventory.get(selection.id);
          if(!row?.destination || row.destination.source!==selection.destination.source || row.destination.revision!==selection.destination.revision)
            status.textContent='Your selected session changed. Select it again before sending; the current destination has not been replaced.';
        }
        render();onReady(true);
        if(expanded&&!expanded.is_entry&&activeHistory)void history('after');
      }catch(error){
        if(owned!==epoch)return;
        if(error.status===403||error.status===401){
          revoke();
        }else {status.textContent='Session status could not be refreshed. Your input destination is unchanged.';retryStatus.hidden=false;}
      }finally{if(owned===epoch)loading=false;}
    }
    function revoke(){
      retryStatus.hidden=true;allowed=false;complete=false;inventory.clear();rows.clear();list.replaceChildren();clearHistory();view.hidden=true;timeline.hidden=false;
      shell.hidden=false;rail.hidden=true;toolbar.hidden=!selected();
      status.textContent=selected()?'Session workspace access is unavailable. Return the input to the conversation, or restore access.':'';
      onReady(false);
    }
    function appendItem(item,prepend=false){
      const found=[...entries.children].find(box=>box.dataset.event===item.id);
      if(found)return;
      const box=el('article',undefined,'session-message');box.dataset.event=item.id;box.dataset.position=String(item.position);box.dataset.end=String(item.next_position);
      const label=item.kind==='message'?(item.role==='user'?'Input':document.querySelector?.('#conversation-daimon')?.textContent||'Daimon'):item.kind==='tool_call'?`>_ ${item.name||'Tool'}`:item.kind==='tool_output'?'Tool output':'Reasoning summary';
      const caption=el('h4',label),text=el(item.kind==='message'?'div':'pre',item.text,'session-message-text');
      const time=el('time');time.textContent=item.timestamp||'';box.append(caption,text,time);
      let offset=item.next;
      if(item.more){
        const more=button('Continue reading','Read the next part of this message',async()=>{
          const owned=historyEpoch,selection=expanded,revision=activeHistory?.revision;if(!selection||!revision||more.disabled)return;
          more.disabled=true;
          try{
            const result=await api(`interaction/sessions/${selection.id}?${new URLSearchParams({technical:String(technical),revision,event:item.position,text_offset:offset})}`);
            if(owned!==historyEpoch)return;
            const part=result.items?.[0];if(!part||part.id!==item.id||part.offset!==offset)throw Error('Message changed');
            text.textContent+=part.text;offset=part.next;more.hidden=!part.more;trimHistory(false,box);
          }catch(error){if(owned===historyEpoch){if(error.status===401||error.status===403)revoke();else historyStatus.textContent='This message could not be read. Select the session again.';}}
          finally{if(owned===historyEpoch)more.disabled=false;}
        });box.append(more);
      }
      if(prepend)entries.insertBefore(box,entries.children[0]||null);else entries.append(box);
    }
    function trimHistory(backward,keep){
      let characters=[...entries.children].reduce((sum,box)=>sum+box.textContent.length,0);
      while(entries.children.length>240 || characters>4*1024*1024){
        const box=backward?entries.children[entries.children.length-1]:entries.children[0];
        if(box===keep)break;
        characters-=box.textContent.length;
        if(backward){activeHistory.after=Number(box.dataset.position);activeHistory.moreAfter=true;}
        else {activeHistory.before=Number(box.dataset.end);activeHistory.hasEarlier=true;}
        box.remove();
      }
    }
    async function history(direction){
      if(!allowed||!expanded||expanded.is_entry||historyBusy)return;
      historyBusy=true;retryHistory.hidden=true;const owned=historyEpoch,selection=expanded;
      const query=new URLSearchParams({technical:String(technical)});
      if(activeHistory){query.set('revision',activeHistory.revision);query.set(direction==='before'?'before':'after',activeHistory[direction==='before'?'before':'after']);}
      if(!activeHistory)historyStatus.textContent='Reading…';
      try{
        const result=await api(`interaction/sessions/${selection.id}?${query}`);if(owned!==historyEpoch)return;
        if(result.schema!=='daimon.session-view/v1'||!Array.isArray(result.items)||result.items.length>80)throw Error('Conversation unavailable');
        if(!activeHistory){activeHistory={revision:result.revision,before:result.before,after:result.after,hasEarlier:result.has_earlier,moreAfter:result.more};}
        else if(direction==='before'){activeHistory.before=result.before;activeHistory.hasEarlier=result.has_earlier;}else {activeHistory.after=result.after;activeHistory.moreAfter=result.more;}
        const previousHeight=entries.scrollHeight,previousTop=entries.scrollTop;
        const nearEnd=previousHeight-previousTop-entries.clientHeight<80;
        if(direction==='before')for(const item of [...result.items].reverse())appendItem(item,true);
        else for(const item of result.items)appendItem(item);
        // Keep only a bounded DOM window. Removed messages remain in native
        // history and can be read again with its existing cursors.
        trimHistory(direction==='before');
        earlier.hidden=!activeHistory.hasEarlier;newer.hidden=!activeHistory.moreAfter;historyStatus.textContent=result.skipped_records?'Some retained records are unavailable.':'Live conversation';
        if(direction==='before')entries.scrollTop=previousTop+entries.scrollHeight-previousHeight;
        else if(!direction || direction==='after'&&nearEnd)entries.scrollTop=entries.scrollHeight;
        onReady(true);
      }catch(error){
        if(owned===historyEpoch){
          if(error.status===401||error.status===403)revoke();
          else {
            if(error.status===409)clearHistory();
            retryDirection=error.status===409?undefined:direction;
            historyStatus.textContent=error.status===409?'This conversation changed. Retry reading to refresh.':'Conversation unavailable. Your draft is kept.';
            retryHistory.hidden=false;
          }
        }
      }
      finally{if(owned===historyEpoch)historyBusy=false;}
    }
    return {refresh,capture,syncAudio,pinState,pinSource,reset:()=>resetBinding(undefined),get active(){return allowed;},
      canSend(){const value=selected();if(!value||value.is_entry)return true;const row=inventory.get(value.id);return allowed&&row?.destination?.source===value.destination.source&&row.destination.revision===value.destination.revision;}};
  }
  window.SessionWorkspace={mount};
})();
