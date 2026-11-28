/* One owner-scoped workspace. Refresh reuses Conversation's existing events;
 * no extra poller, transcript persistence, model call or routing store. The
 * bounded notice grace changes presentation only; it never repeats a request. */
(() => {
  const pinIcon='<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m15 3 6 6-4 1-3 5-5-5 5-3Z"/><path d="m9 15-6 6"/></svg>';
  const replyIcon='<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16v12H9l-5 5Z"/><path d="M8 8h8M8 12h5"/></svg>';
  const muteIcon=muted=>'<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H3v6h3l5 4Z"/>'+
    (muted?'<path d="m16 9 5 6m0-6-5 6"/>':'<path d="M15 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>')+'</svg>';
  const active=row=>row.fresh===true&&(row.execution==='working'||row.execution==='running'||row.execution==='queued'||row.tools_running===true||row.goal_state==='active');
  const copy=value=>value&&JSON.parse(JSON.stringify(value));
  const el=(tag,text,cls)=>{const item=document.createElement(tag);if(text!==undefined)item.textContent=text;if(cls)item.className=cls;return item;};
  const button=(text,label,click)=>{const item=el('button',text);item.type='button';item.title=label;item.setAttribute('aria-label',label);item.addEventListener('click',click);return item;};
  function mount({timeline,api,toolbarHost,noticeHost,hosted=false,portableDeliveryText=()=>undefined,daimonName='Daimon',onTarget=()=>{},focusComposer=()=>{},onReply=()=>{},audio=()=>({}),onAudio=()=>{},onReady=()=>{}}){
    if(!timeline?.parentNode)return;
    const shell=el('section',undefined,'session-workspace'),toolbar=el('div',undefined,'session-workspace-toolbar');
    shell.hidden=false;toolbar.hidden=true;shell.setAttribute('aria-label','Session workspace');
    const rail=el('aside',undefined,'session-rail');rail.id='session-rail';rail.hidden=true;rail.setAttribute('aria-label','Your sessions');
    const list=el('div',undefined,'session-list'),target=el('span','Conversation','session-input-target');
    const toggle=button('','Show sessions',()=>showRail(rail.hidden));
    toggle.innerHTML='<svg class="control-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M4 6h16M4 12h12M4 18h16"/></svg>';
    function showRail(open){if(open)void refresh(binding);rail.hidden=!open;toggle.setAttribute('aria-expanded',String(open));toggle.title=open?'Hide sessions':'Show sessions';toggle.setAttribute('aria-label',toggle.title);}
    toggle.setAttribute('aria-controls',rail.id);toggle.setAttribute('aria-expanded','false');
    const reset=button('↺ Reset','Hear all sessions: clear mute and solo',()=>{onAudio('reset');toggle.focus?.();});
    reset.className='session-workspace-reset';
    reset.innerHTML='<svg class="control-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M3 10a9 9 0 1 1 1 7M3 4v6h6"/></svg><span>Reset</span>';
    const unpin=button('⌖','Send to the conversation',()=>{pin=undefined;changed();});
    unpin.innerHTML=pinIcon;
    const status=el('p','','session-workspace-status');status.setAttribute('role','status');status.setAttribute('data-attention','true');
    const retryStatus=button('Retry status','Retry session status',()=>refresh(binding));retryStatus.hidden=true;retryStatus.className='session-workspace-retry';
    const body=el('div',undefined,'session-workspace-body'),content=el('div',undefined,'session-workspace-content');
    const view=el('section',undefined,'session-conversation');view.hidden=true;view.setAttribute('aria-label','Selected session conversation');
    const viewBar=el('div',undefined,'session-view-toolbar'),heading=el('h3','Session');
    const back=button('←','Back to the conversation',()=>{expanded=undefined;leave();changed();toggle.focus?.();});
    back.innerHTML='<svg class="control-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m11 5-7 7 7 7M4 12h16"/></svg>';
    function setView(detail){
      if(technical===detail)return;
      technical=detail;syncView();clearHistory();void history();
    }
    function syncView(){
      entries.dataset.raw=String(technical);
      technicalButton.setAttribute('aria-pressed',String(technical));
    }
    const technicalButton=button('Raw','Raw session view',()=>setView(!technical));
    technicalButton.setAttribute('aria-pressed','false');
    const retryHistory=button('Retry reading','Retry reading this conversation',()=>history(retryDirection));retryHistory.hidden=true;
    const entries=el('div',undefined,'session-messages');entries.setAttribute('role','log');entries.setAttribute('aria-label','Selected session messages');entries.tabIndex=0;
    const historyStatus=el('p','','session-history-status');historyStatus.setAttribute('role','status');
    viewBar.append(heading,technicalButton);view.append(viewBar,historyStatus,retryHistory,entries);
    let historyScrollTop=0,touchStart;
    function pageAtEdge(direction){
      if(view.hidden||!retryHistory.hidden||!activeHistory)return;
      if(direction==='before'&&activeHistory.hasEarlier&&entries.scrollTop<=24)void history('before');
      if(direction==='after'&&activeHistory.moreAfter&&entries.scrollHeight-entries.clientHeight-entries.scrollTop<=24)void history('after');
    }
    entries.addEventListener('scroll',()=>{
      const previous=historyScrollTop;
      historyScrollTop=entries.scrollTop;
      if(historyScrollTop!==previous)pageAtEdge(historyScrollTop<previous?'before':'after');
    },{passive:true});
    // At the edge a wheel or swipe may produce no scroll event (including a
    // short page). Use the gesture to keep the existing cursors reachable.
    entries.addEventListener('wheel',event=>{
      if(!event.ctrlKey&&Math.abs(event.deltaY)>Math.abs(event.deltaX))pageAtEdge(event.deltaY<0?'before':'after');
    },{passive:true});
    entries.addEventListener('touchstart',event=>{touchStart=event.touches.length===1?event.touches[0].clientY:undefined;},{passive:true});
    entries.addEventListener('touchend',event=>{
      const distance=event.changedTouches[0]?.clientY-touchStart;
      touchStart=undefined;
      if(Math.abs(distance)>24)pageAtEdge(distance>0?'before':'after');
    },{passive:true});
    entries.addEventListener('keydown',event=>{
      if(event.target!==entries)return;
      if(['PageUp','Home','ArrowUp'].includes(event.key))pageAtEdge('before');
      if(['PageDown','End','ArrowDown'].includes(event.key))pageAtEdge('after');
    });
    window.ConversationHeader?.mount({timeline:entries});
    shell.addEventListener('keydown',event=>{if(event.key==='Escape'&&!rail.hidden){showRail(false);toggle.focus?.();event.stopPropagation();}});
    let showAll=false;
    const railHeading=el('h3','Sessions · 24h');
    function syncScope(){const label=showAll?'Show recent sessions':'Show all sessions';scopeToggle.textContent=label;scopeToggle.setAttribute('aria-label',label);scopeToggle.setAttribute('aria-pressed',String(showAll));railHeading.textContent=showAll?'Sessions · All':'Sessions · 24h';}
    const scopeToggle=button('Show all sessions','Show all sessions',()=>{showAll=!showAll;syncScope();remember();render();});scopeToggle.className='session-scope-toggle';
    const railHeader=el('div',undefined,'session-rail-header');railHeader.append(railHeading,reset);
    const railScroll=el('div',undefined,'session-rail-scroll');railScroll.append(railHeader,scopeToggle,list);rail.append(railScroll);toolbar.append(toggle,back,target,unpin);body.append(rail,content);shell.append(body,toolbar);(noticeHost||shell).append(status,retryStatus);
    if(toolbarHost)toolbarHost.insertBefore(toolbar,toolbarHost.firstChild);
    timeline.before(shell);content.append(timeline,view);
    let binding,epoch=0,inventory=new Map(),rows=new Map(),pin,expanded,technical=false,allowed=false,loading=false,complete=false,restoreChecked=false;
    let statusFailureAt, statusFailureTimer;
    const reviewed=new Map(), visibleResults=new Map();
    const reviewKey='interaction.reviewed-session-results.v1';
    const sessionId=id=>typeof id==='string'&&/^[a-f0-9]{24}$/.test(id);
    const resultId=id=>typeof id==='string'&&/^[a-f0-9]{64}$/.test(id);
    function loadReviewed(){
      reviewed.clear();
      if(!binding)return;
      try{
        const raw=window.localStorage?.getItem(reviewKey);
        if(!raw||raw.length>16384)return;
        const value=JSON.parse(raw);
        if(value.binding!==binding||!Array.isArray(value.results)||value.results.length>128)return;
        for(const pair of value.results)
          if(Array.isArray(pair)&&sessionId(pair[0])&&resultId(pair[1]))reviewed.set(pair[0],pair[1]);
      }catch{}
    }
    function reviewVisibleResult(){
      if(view.hidden||technical||!allowed||document.hidden||!expanded)return;
      const current=inventory.get(expanded.id), revision=current?.result_revision;
      if(!sessionId(current?.id)||!resultId(revision)||reviewed.get(current.id)===revision)return;
      if(![...visibleResults].some(([box,result])=>box.parentNode===entries&&result===revision))return;
      reviewed.delete(current.id);
      reviewed.set(current.id,revision);
      if(reviewed.size>128)reviewed.delete(reviewed.keys().next().value);
      try{window.localStorage?.setItem(reviewKey,JSON.stringify({binding,results:[...reviewed]}));}catch{}
      const row=rows.get(current.id);
      if(row)row.state.textContent=annotate(row.data);
    }
    const resultObserver=window.IntersectionObserver?new window.IntersectionObserver(changes=>{
      for(const entry of changes){
        if(entry.target.parentNode===entries&&entry.isIntersecting&&entry.intersectionRatio>0)
          visibleResults.set(entry.target,entry.target.dataset.resultRevision);
        else visibleResults.delete(entry.target);
      }
      reviewVisibleResult();
    },{root:entries,threshold:[0,0.01]}):undefined;
    document.addEventListener?.('visibilitychange',reviewVisibleResult);
    const statusFailureText='Session status is unavailable. Your input destination is unchanged.';
    function clearStatusFailure(){clearTimeout(statusFailureTimer);statusFailureTimer=undefined;statusFailureAt=undefined;}
    function observeStatusFailure(){
      statusFailureAt ??= Date.now();
      const owned=epoch;
      const show=()=>{
        statusFailureTimer=undefined;
        if(owned!==epoch || statusFailureAt===undefined || document.hidden===true)return;
        if(!status.textContent || status.textContent===statusFailureText){status.textContent=statusFailureText;retryStatus.hidden=false;}
      };
      if(Date.now()-statusFailureAt>=8000){clearTimeout(statusFailureTimer);show();}
      else if(statusFailureTimer===undefined)statusFailureTimer=setTimeout(show,8000-(Date.now()-statusFailureAt));
    }
    const followKey='interaction.followed-session.v1';
    function saved(){
      if(hosted)return;
      try{const raw=window.localStorage?.getItem(followKey);if(!raw||raw.length>1024)return;const value=JSON.parse(raw),opaque=id=>id===null||typeof id==='string'&&/^[a-f0-9]{24}$/.test(id);if(value?.version===1&&value.binding===binding&&opaque(value.id)&&(!Object.hasOwn(value,'view')||opaque(value.view))&&(!Object.hasOwn(value,'all')||typeof value.all==='boolean'))return value;}catch{}
    }
    function remember(){
      if(hosted)return;
      const id=pin?.id||null,view=expanded?.id||null;if(!binding||[id,view].some(v=>v!==null&&!/^[a-f0-9]{24}$/.test(v)))return;
      try{window.localStorage?.setItem(followKey,JSON.stringify({version:1,binding,id,view,all:showAll}));}catch{}
    }
    const localSubmissions=new Map();
    let activeHistory,retryDirection,historyBusy=false,refreshAfterRead=false,historyEpoch=0,observedAt=0,lastHistoryAttempt=0;
    function selected(){return expanded||pin;}
    function capture(){const value=selected();if(value&&!value.is_entry&&!value.destination)throw Error('Your saved session is unavailable. Select a destination before sending.');return value?copy({selected:true,...(!value.is_entry?{reference:value.destination}:{})}):undefined;}
    function changed(){remember();renderSelection();onTarget();}
    function renderSelection(){
      const current=selected();target.textContent=current&&!current.is_entry?`To ${current.title}`:'To the conversation';target.title=target.textContent;
      back.hidden=hosted||!expanded;
      const backLabel=expanded?.is_entry?'Show all session updates':'Back to the conversation';
      back.title=backLabel;back.setAttribute('aria-label',backLabel);
      unpin.hidden=!pin;unpin.setAttribute('aria-pressed',String(!!pin));
      unpin.title=pin?`Unpin ${pin.title}`:'Send to the conversation';
      unpin.setAttribute('aria-label',expanded?'Clear pinned input destination':'Send to the conversation');
      for(const [id,row] of rows){row.pin.setAttribute('aria-pressed',String(pin?.id===id));row.name.setAttribute('aria-current',String(expanded?.id===id));}
    }
    function sourceRow(source){
      if(hosted||!allowed||!complete||!source)return;
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
      changed();showRail(false);toggle.focus?.();return true;
    }
    function pinSource(source){return setPin(sourceRow(source));}
    function leave(){historyEpoch++;historyBusy=false;view.hidden=true;timeline.hidden=false;clearHistory();renderSelection();}
    function clearHistory(){historyEpoch++;historyBusy=false;refreshAfterRead=false;activeHistory=undefined;localSubmissions.clear();resultObserver?.disconnect();visibleResults.clear();entries.replaceChildren();historyScrollTop=0;touchStart=undefined;historyStatus.textContent='';retryHistory.hidden=true;}
    function open(row,{restore=false}={}){
      if(row.is_entry){expanded={id:row.id,title:row.title,is_entry:true};leave();showRail(false);changed();if(!restore)focusComposer();return;}
      if(!row.destination){status.textContent='This session is unavailable for direct input. Its status remains visible.';return;}
      expanded={id:row.id,title:row.title,destination:copy(row.destination),audio_key:row.audio_key};
      technical=false;syncView();clearHistory();view.hidden=false;timeline.hidden=true;heading.textContent=row.title;
      showRail(false);changed();if(!restore)focusComposer();void history();
    }
    function annotate(row){
      const states=[];
      if(row.human_action_pending)states.push('◆ Needs you');
      if(row.results_review===true || row.results_review==='pending')states.push('▣ Results to review');
      else if(row.result_available===true&&(!row.result_revision||reviewed.get(row.id)!==row.result_revision))states.push('▣ Result available');
      if(row.goal_state==='blocked')states.push('⏸ Goal blocked');
      else if(row.goal_state==='active')states.push('◎ Goal active');
      if(row.tools_running)states.push('⚒ Tools running');
      if(row.execution==='working' || row.execution==='running')states.push('⚙ Working');
      else if(row.execution==='queued')states.push('○ Waiting to start');
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
      const recent=[...inventory.values()].filter(row=>row.is_entry||showAll||active(row)||Number.isFinite(row.last_activity_at)&&row.last_activity_at>=observedAt-86400)
        .sort((a,b)=>Number(b.is_entry===true)-Number(a.is_entry===true)||Number(active(b))-Number(active(a))||(b.last_activity_at||0)-(a.last_activity_at||0)||a.id.localeCompare(b.id));
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
      clearStatusFailure();epoch++;loading=false;binding=next;loadReviewed();pin=undefined;expanded=undefined;restoreChecked=false;showAll=false;syncScope();inventory.clear();rows.clear();list.replaceChildren();leave();
      allowed=false;complete=false;shell.hidden=false;toolbar.hidden=true;status.textContent='';retryStatus.hidden=true;onReady(false);onTarget();
    }
    let refreshFlight;
    function refresh(nextBinding){
      if(binding!==nextBinding)resetBinding(nextBinding);
      if(loading)return refreshFlight;
      if(!binding)return;
      refreshFlight=refreshCurrent();
      return refreshFlight;
    }
    async function refreshCurrent(){
      loading=true;const owned=epoch;
      try{
        const value=await api('interaction/sessions');if(owned!==epoch)return;
        if(value.schema!=='daimon.session-workspace/v1'||!Array.isArray(value.sessions)||value.sessions.length>128)throw Error('Session workspace unavailable');
        clearStatusFailure();observedAt=Number.isFinite(value.observed_at)&&value.observed_at>0?value.observed_at:Date.now()/1000;
        inventory=new Map(value.sessions.map(row=>[row.id,row.is_entry?{...row,title:typeof daimonName==='string'&&daimonName.trim()?daimonName.trim():'Daimon'}:row]));complete=value.truncated!==true;allowed=true;shell.hidden=false;toolbar.hidden=hosted;status.textContent='';retryStatus.hidden=true;
        // Never silently redirect a selected target after grant/binding loss.
        for(const selection of [pin,expanded].filter(value=>value&&!value.is_entry)){
          const row=inventory.get(selection.id);
          if(!row?.destination || row.destination.source!==selection.destination?.source || row.destination.revision!==selection.destination?.revision)
            status.textContent='Your selected session changed. Select it again before sending; the current destination has not been replaced.';
        }
        if(!restoreChecked){
          restoreChecked=true;const previous=saved();showAll=typeof previous?.all==='boolean'?previous.all:value.default_filter==='all';syncScope();
          if(previous?.id){const row=inventory.get(previous.id);pin=row?.destination&&!row.is_entry?{id:row.id,title:row.title,destination:copy(row.destination)}:{id:previous.id,title:'Unavailable saved session'};}
          const viewId=previous?.view,viewRow=inventory.get(viewId);
          if(viewRow?.is_entry||viewRow?.destination)open(viewRow,{restore:true});
          else if(viewId)expanded={id:viewId,title:'Unavailable saved session'};
          if((pin&&!pin.destination)||(expanded&&!expanded.is_entry&&!expanded.destination))status.textContent='Your saved session is unavailable. Select a destination before sending.';
          renderSelection();onTarget();
        }
        reviewVisibleResult();render();onReady(true);
        if(expanded&&!expanded.is_entry&&(activeHistory||!retryHistory.hidden&&Date.now()-lastHistoryAttempt>=5000))
          void history(activeHistory?'after':undefined);
        return true;
      }catch(error){
        if(owned!==epoch)return;
        if(error.status===403||error.status===401){
          revoke();
        }else observeStatusFailure();
      }finally{if(owned===epoch)loading=false;}
    }
    async function selectHostedTopic(room,nextBinding,maySelect=()=>true){
      if(!hosted||!nextBinding||!maySelect())return null;
      if(room===null){
        pin=expanded=undefined;
        leave();changed();
        return {room:null};
      }
      if(typeof room!=='string'||!/^[a-f0-9]{64}$/.test(room)||!await refresh(nextBinding)||
        !maySelect()||nextBinding!==binding||!allowed||!complete)return null;
      const matches=[...inventory.values()].filter(row=>row.topic_ref===room&&!row.is_entry&&row.destination);
      if(matches.length!==1)return null;
      pin=undefined;
      const row=matches[0];
      open(row,{restore:true});
      return {room};
    }
    async function hostedRoom(room,nextBinding,current){
      if(!hosted||!resultId(room)||!nextBinding||!current()||!await refresh(nextBinding)||
        !current()||nextBinding!==binding||!allowed||!complete)return null;
      const matches=[...inventory.values()].filter(row=>row.topic_ref===room);
      return matches.length===1?matches[0]:null;
    }
    async function readHostedResult(room,nextBinding,current){
      const row=await hostedRoom(room,nextBinding,current);
      if(!row||row.is_entry||row.result_available!==true)return null;
      const revision=row.result_revision;
      const portable=['claude','antigravity','goose'].includes(row.runtime?.harness);
      if(!sessionId(row.id)||!portable&&!resultId(revision))return null;
      const path=`interaction/sessions/${row.id}`,owned=epoch;
      const authorized=()=>current()&&owned===epoch&&allowed&&nextBinding===binding&&
        inventory.get(row.id)?.result_available===true&&inventory.get(row.id)?.result_revision===revision;
      const page=await api(path);
      if(!authorized()||page.schema!=='daimon.session-view/v1'||page.session!==row.id||!resultId(page.revision)||
        !Array.isArray(page.items)||page.items.length>80)return null;
      const item=[...page.items].reverse().find(entry=>entry.kind==='message'&&entry.role==='assistant'&&
        (portable||entry.result_revision===revision));
      if(!item||typeof item.text!=='string'||!Number.isSafeInteger(item.position))return null;
      return {title:row.title,item,async part(offset){
        if(!authorized())return null;
        const value=await api(path+'?'+new URLSearchParams({revision:page.revision,event:item.position,text_offset:offset}));
        const next=value.items?.[0];
        return authorized()&&value.revision===page.revision&&value.session===row.id&&
          next?.id===item.id&&next.offset===offset?next:null;
      }};
    }
    function revoke(){
      clearStatusFailure();retryStatus.hidden=true;allowed=false;complete=false;inventory.clear();rows.clear();list.replaceChildren();clearHistory();view.hidden=true;timeline.hidden=false;
      shell.hidden=false;rail.hidden=true;toolbar.hidden=hosted||!selected();
      status.textContent=selected()?'Session workspace access is unavailable. Return the input to the conversation, or restore access.':'';
      onReady(false);
    }
    function matchesDestination(reference){
      const destination=expanded?.destination;
      return allowed&&destination&&reference&&destination.source===reference.source&&destination.revision===reference.revision;
    }
    function observeSubmission(reference){
      if(!matchesDestination(reference))return;
      if(historyBusy){refreshAfterRead=true;return;}
      void history(activeHistory?'after':undefined);
    }
    function previewSubmission(reference,id,text){
      if(!matchesDestination(reference)||!activeHistory?.linksInputIds||technical||!text.trim())return;
      if(localSubmissions.size>=8)return;
      const item={id:'original:'+id,input_id:id,kind:'message',role:'user',text,pending:true,local:true};
      localSubmissions.set(id,item);
      appendItem(item);
      entries.scrollTop=entries.scrollHeight;
    }
    function settlePreview(id,state){
      const item=localSubmissions.get(id);
      if(!item)return;
      const box=[...entries.children].find(child=>child.dataset.event===item.id);
      if(state==='discarded'){localSubmissions.delete(id);box?.remove();return;}
      item.status=state;
      if(box)box.children[2].textContent=state;
    }
    function appendItem(item,prepend=false){
      const found=[...entries.children].find(box=>box.dataset.event===item.id);
      const delivery=portableDeliveryText(item.portable_phase,item.native_tool_declined,item.subscription_limit);
      if(found){
        const status=found.children[2];
        if(delivery&&status?.className==='reply-status'&&status.textContent!==delivery)status.textContent=delivery;
        return;
      }
      const ordinary=!technical&&item.kind==='message';
      const messageStyle=ordinary?'session-message reply'+(item.role==='user'?' human-message':''):'session-message';
      const box=el('article',undefined,messageStyle);box.dataset.event=item.id;box.dataset.position=String(item.position);box.dataset.end=String(item.next_position);
      if(item.pending)box.dataset.pending="true";
      if(item.input_id)box.dataset.inputId=item.input_id;
      const label=item.kind==='message'?(item.role==='user'?'Input':expanded?.title||'Daimon'):item.kind==='tool_call'?`>_ ${item.name||'Tool'}`:item.kind==='tool_output'?'Tool output':'Reasoning summary';
      const caption=el(ordinary?'h3':'h4',label);
      const text=el(item.kind==='message'?'div':'pre',item.text,ordinary?'reply-text':'session-message-text');
      let sourceText=item.text;
      const renderText=()=>{
        box.dataset.characters=String(sourceText.length);
        if(item.kind==='message'&&window.ConversationMarkdown)window.ConversationMarkdown.render(text,sourceText);
        else text.textContent=sourceText;
      };
      renderText();
      box.append(caption,text);
      if(item.local||delivery)box.append(el('p',delivery||item.status||'Sending…','reply-status'));
      if(item.timestamp){
        const time=el('time');time.dateTime=item.timestamp;
        const stamp=new Date(item.timestamp);
        time.textContent=ordinary&&Number.isFinite(stamp.valueOf())
          ?stamp.toLocaleString(undefined,{weekday:'short',hour:'numeric',minute:'2-digit'})
          :item.timestamp;
        box.append(time);
      }
      let offset=item.next;
      if(item.more){
        const more=button('Continue reading','Read the next part of this message',async()=>{
          const owned=historyEpoch,selection=expanded,revision=activeHistory?.revision;if(!selection||!revision||more.disabled)return;
          more.disabled=true;
          try{
            const result=await api(`interaction/sessions/${selection.id}?${new URLSearchParams({technical:String(technical),revision,event:item.position,text_offset:offset})}`);
            if(owned!==historyEpoch)return;
            const part=result.items?.[0];if(!part||part.id!==item.id||part.offset!==offset)throw Error('Message changed');
            sourceText+=part.text;renderText();offset=part.next;more.hidden=!part.more;trimHistory(false,box);
          }catch(error){if(owned===historyEpoch){if(error.status===401||error.status===403)revoke();else historyStatus.textContent='This message could not be read. Select the session again.';}}
          finally{if(owned===historyEpoch)more.disabled=false;}
        });box.append(more);
      }
      if(prepend)entries.insertBefore(box,entries.children[0]||null);
      else if(item.pending)entries.append(box);
      else entries.insertBefore(box,[...entries.children].find(value=>value.dataset.pending)||null);
      if(ordinary&&resultId(item.result_revision)){
        box.dataset.resultRevision=item.result_revision;
        resultObserver?.observe(box);
      }
    }
    function trimHistory(backward,keep){
      const size=box=>Math.max(box.textContent.length,Number(box.dataset.characters)||0);
      const messages=[...entries.children].filter(box=>!box.dataset.pending);
      let characters=messages.reduce((sum,box)=>sum+size(box),0);
      while(messages.length>240 || characters>4*1024*1024){
        const box=backward?messages.pop():messages.shift();
        if(box===keep)break;
        characters-=size(box);
        if(backward){activeHistory.after=Number(box.dataset.position);activeHistory.moreAfter=true;}
        else {activeHistory.before=Number(box.dataset.end);activeHistory.hasEarlier=true;}
        resultObserver?.unobserve(box);visibleResults.delete(box);
        box.remove();
      }
    }
    async function history(direction,recovered=false){
      if(!allowed||!expanded||expanded.is_entry||historyBusy)return;
      historyBusy=true;lastHistoryAttempt=Date.now();retryHistory.hidden=true;const owned=historyEpoch,selection=expanded;
      const query=new URLSearchParams({technical:String(technical)});
      if(activeHistory){query.set('revision',activeHistory.revision);query.set(direction==='before'?'before':'after',activeHistory[direction==='before'?'before':'after']);
        if(activeHistory[direction==='before'?'beforeScan':'afterScan'])query.set('scan','true');}
      if(!activeHistory)historyStatus.textContent='Reading…';
      try{
        const result=await api(`interaction/sessions/${selection.id}?${query}`);if(owned!==historyEpoch)return;
        if(result.schema!=='daimon.session-view/v1'||!Array.isArray(result.items)||result.items.length>80)throw Error('Conversation unavailable');
        if(!activeHistory){activeHistory={linksInputIds:result.links_input_ids===true,revision:result.revision,before:result.before,after:result.after,beforeScan:result.before_scan,afterScan:result.after_scan,hasEarlier:result.has_earlier,moreAfter:result.more};}
        else if(direction==='before'){activeHistory.before=result.before;activeHistory.beforeScan=result.before_scan;activeHistory.hasEarlier=result.has_earlier;}else {activeHistory.after=result.after;activeHistory.afterScan=result.after_scan;activeHistory.moreAfter=result.more;}
        const previousHeight=entries.scrollHeight,previousTop=entries.scrollTop;
        const nearEnd=previousHeight-previousTop-entries.clientHeight<80;
        if(direction==='before')for(const item of [...result.items].reverse())appendItem(item,true);
        else for(const item of result.items)appendItem(item);
        // Keep only a bounded DOM window. Removed messages remain in native
        // history and can be read again with its existing cursors.
        trimHistory(direction==='before');
        if(direction!=='before'&&!technical){
          for(const item of result.items)if(item.role==='user')localSubmissions.delete(item.input_id);
          const pending=Array.isArray(result.pending_items)
            ?result.pending_items.slice(0,8).filter(item=>item.pending===true&&
              (item.role==='user'||(item.role==='assistant'&&item.handoff===true))):[];
          for(const item of pending)if(item.role==='user')localSubmissions.delete(item.input_id);
          pending.push(...localSubmissions.values());
          const visible=new Set(pending.map(item=>item.id));
          for(const box of [...entries.children])if(box.dataset.pending&&!visible.has(box.dataset.event))box.remove();
          for(const item of pending)appendItem(item);
        }
        historyStatus.textContent=result.skipped_records?'Some content could not be previewed.':entries.children.length?'':'No messages yet.';
        if(direction==='before')entries.scrollTop=previousTop+entries.scrollHeight-previousHeight;
        else if(!direction || direction==='after'&&nearEnd)entries.scrollTop=entries.scrollHeight;
        historyScrollTop=entries.scrollTop;
        onReady(true);
      }catch(error){
        if(owned===historyEpoch){
          if(error.status===401||error.status===403)revoke();
          else {
            if(error.status===409)clearHistory();
            if(error.status===409&&!recovered)return history(undefined,true);
            retryDirection=error.status===409?undefined:direction;
            historyStatus.textContent=error.status===409?'This conversation changed. Retry reading to refresh.':'Conversation unavailable. Your draft is kept.';
            retryHistory.hidden=false;
          }
        }
      }
      finally{
        if(owned===historyEpoch){
          historyBusy=false;
          if(refreshAfterRead){refreshAfterRead=false;void history(activeHistory?'after':undefined);}
        }
      }
    }
    function audioScope(){
      if(!allowed||!expanded)return;
      const current=inventory.get(expanded.id);
      if(!current)return {};
      if(current.is_entry===true&&expanded.is_entry===true)return current;
      return current.destination?.source===expanded.destination?.source
        &&expanded.destination&&current.destination.revision===expanded.destination.revision?current:{};
    }
    function runtime(){
      if(!allowed)return;
      const current=selected();
      if(!current)return [...inventory.values()].find(row=>row.is_entry)?.runtime;
      const row=inventory.get(current.id);
      if(current.is_entry)return row?.is_entry?row.runtime:undefined;
      if(row?.destination?.revision===current.destination?.revision &&
          row?.destination?.source===current.destination?.source)return row?.runtime;
    }
    return {refresh,selectHostedTopic,hostedRoom,readHostedResult,observeSubmission,previewSubmission,settlePreview,capture,syncAudio,pinState,pinSource,audioScope,runtime,reset:()=>resetBinding(undefined),get active(){return allowed;},
      canSend(){const value=selected();if(!value||value.is_entry)return true;const row=inventory.get(value.id);return !!(allowed&&value.destination&&row?.destination?.source===value.destination.source&&row.destination.revision===value.destination.revision);}};
  }
  window.SessionWorkspace={mount};
})();
