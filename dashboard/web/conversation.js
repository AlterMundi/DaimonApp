"use strict";
window.Conversation = (() => {
  const $ = (selector) => document.querySelector(selector);
  const node = (tag, text, cls) => {
    const value = document.createElement(tag);
    if (text !== undefined) value.textContent = text;
    if (cls) value.className = cls;
    return value;
  };
  function messageTime(element, timestamp) {
    const date = new Date(timestamp);
    element.hidden = !timestamp || !Number.isFinite(date.getTime());
    if(element.hidden)return;
    const locale="en"; // Match the current English UI; full localization is tracked separately.
    const weekday=new Intl.DateTimeFormat(locale,{weekday:"short"}).format(date).replace(/\.$/,"").toLocaleLowerCase(locale);
    element.textContent=`${weekday} ${String(date.getHours()).padStart(2,"0")}:${String(date.getMinutes()).padStart(2,"0")}`;
    element.dateTime=date.toISOString();
    element.title=date.toLocaleString(locale,{dateStyle:"full",timeStyle:"long",hour12:false});
  }
  function mount({api, headers, setCsrf, modeChanged, telegram, readOnly=false, standalone=false, onUnauthorized}) {
    let hostedTopic,hostedResult;
    function closeHostedResult(){hostedResult?.close();hostedResult=undefined;}
    async function openHostedResult(room,current){
      const result=await workspace?.readHostedResult(room,binding,current);
      if(!result||!current()||document.querySelector('dialog[open]'))return false;
      const dialog=node('dialog',undefined,'conversation-decision-dialog');
      const heading=node('h2',result.title),body=node('div',undefined,'reply-text');
      dialog.setAttribute('aria-label',`Result from ${result.title}`);
      const close=node('button','Close'),more=node('button','Continue reading');
      const status=node('p');status.setAttribute('role','status');
      close.onclick=()=>dialog.close();
      let item=result.item,text=item.text;
      const render=()=>{
        if(window.ConversationMarkdown)window.ConversationMarkdown.render(body,text);
        else body.textContent=text;
        more.hidden=!item.more;
      };
      more.onclick=async()=>{
        if(more.disabled)return;
        more.disabled=true;
        try{
          const part=await result.part(item.next);
          if(!part||!dialog.open)throw Error('Result changed');
          item=part;text+=part.text;render();
        }catch{if(dialog.open)status.textContent='This result changed or is no longer available.';}
        finally{more.disabled=false;}
      };
      dialog.addEventListener('close',()=>{if(hostedResult===dialog)hostedResult=undefined;dialog.remove();},{once:true});
      dialog.append(heading,close,body,more,status);
      render();
      document.body.append(dialog);hostedResult=dialog;dialog.showModal();close.focus();
      return true;
    }
    const hostSurface=window.ConversationSurface?.create({
      readTopics:readOnly?undefined:room=>api('interaction/sessions?'+new URLSearchParams({
        projection:'holodeck',...(room?{room}:{})
      })),
      openResult:readOnly?undefined:openHostedResult,closeResult:closeHostedResult,
      openQuestion:readOnly?undefined:async(room,current)=>{
        const row=await workspace?.hostedRoom(room,binding,current);
        if(!row||!current()||!pendingNavigation||document.querySelector('dialog[open]'))return false;
        const match=/^(-?\d+):(\d+)$/.exec(row.audio_key||'');
        if(!match)return false;
        const target={chat_id:Number(match[1]),thread_id:Number(match[2])};
        if(!Object.values(target).every(Number.isSafeInteger))return false;
        const questions=await requestControls.questionIds(target,current);
        return pendingNavigation.openSelected(questions,current);
      },
      closeQuestion:()=>pendingNavigation?.closeSelected(),
      selectTopic:readOnly?undefined:async(room,current)=>{
        const allowed=()=>current()&&!posting&&!captureBusy&&!transcriptPreview&&
          !voiceMode?.active&&!microphone?.ownsSend?.()&&!attachedFiles?.hasFiles();
        const result=await workspace?.selectHostedTopic?.(room,binding,allowed);
        if(!result)return null;
        hostedTopic=room||undefined;
        voiceContext=undefined;
        draftState?.setTopic(hostedTopic);
        return result;
      },
    });
    const timing=readOnly?undefined:window.ConversationTiming?.mount();
    const liveUsage=window.PublicLiveUsage?.mount($('#conversation-live-usage'));
    let canFiles=false,filesConnected=true;
    const files=new Map(),fileDownloads=new Map(),fileStatus=new Map(),filePreviews=new Map();let fileJobs=[];
    const imageFile=file=>/\.(png|jpe?g|webp)$/i.test(file.name||"")&&file.bytes>0&&file.bytes<=8*1024*1024;
    function closeFilePreview(id){const value=filePreviews.get(id);if(value)URL.revokeObjectURL(value.url);filePreviews.delete(id);}
    const previewRoom=file=>filePreviews.size<4&&[...filePreviews.values()].reduce((n,v)=>n+v.bytes,0)+file.bytes<=16*1024*1024;
    const fileCredential=()=>JSON.stringify(Object.entries(headers()).filter(([key])=>key.toLowerCase()==="authorization"));
    function clearFiles(){for(const work of fileDownloads.values())work.abort();fileDownloads.clear();for(const id of filePreviews.keys())closeFilePreview(id);files.clear();fileStatus.clear();fileJobs=[];canFiles=false;}
    function renderFiles(card){
      const sameSource=file=>file.native_source===card.source.id || file.result_id && file.result_id===card.source.result_id;
      const selected=[...new Map((canFiles?[...(card.source.artifacts||[]),...[...files.values()].filter(sameSource)]:[]).map(file=>[file.id,file])).values()].map(file=>({...file,available:!!file.available && (!file.expires_at || Date.parse(file.expires_at)>Date.now())}));
      const stage=canFiles?(fileJobs.find(sameSource)?.phase || card.source.artifact_status):null,preparing=stage==="pending" || stage==="running";
      if(!selected.length && !preparing && stage!=="partial"){if(card.files){card.files.hidden=true;card.files.replaceChildren();delete card.files.dataset.version;}return;}
      if(!card.files){card.files=node("div",undefined,"artifact-files");card.files.setAttribute("role","group");card.files.setAttribute("aria-label","Generated files");card.box.append(card.files);}
      const version=JSON.stringify([filesConnected,stage,selected,[...fileDownloads.keys()],[...fileStatus],[...filePreviews.keys()]]);
      if(card.files.dataset.version===version){card.files.hidden=false;return;}
      card.files.dataset.version=version;card.files.hidden=false;card.files.replaceChildren(node("h4","Files"));
      if(preparing || stage==="partial"){const status=node("p",preparing?"Preparing files… You can keep chatting.":"Some files could not be prepared.","reply-status");status.setAttribute("role","status");card.files.append(status);}
      for(const file of selected){
        const row=node("div",undefined,"artifact-file"),button=node("button",`↓ ${file.name||"File"}`),status=node("span",fileStatus.get(file.id)||(!filesConnected?"Files connection unavailable":file.available?`${Math.ceil((file.bytes||0)/1024)} KB`:"Unavailable or expired"),"reply-status");
        button.type="button";button.disabled=!filesConnected || !file.available || fileDownloads.has(file.id) || fileDownloads.size>=2;status.setAttribute("role","status");
        button.addEventListener("click",()=>downloadFile(file));row.append(button,status);card.files.append(row);
        const shown=filePreviews.get(file.id);
        if(imageFile(file)){
          const view=node("button",shown?"Close image":"View image");view.type="button";
          view.disabled=!shown&&(!filesConnected||!file.available||fileDownloads.has(file.id)||fileDownloads.size>=2||!previewRoom(file));
          view.addEventListener("click",()=>{if(filePreviews.has(file.id)){closeFilePreview(file.id);fileStatus.delete(file.id);refreshFiles();}else return downloadFile(file,true);});row.append(view);
          if(shown&&file.available&&shown.sha256===file.sha256){const image=node("img",undefined,"artifact-image-preview");image.src=shown.url;image.alt=file.name;card.files.append(image);}
        }
      }
    }
    function refreshFiles(){
      for(const [id,preview] of filePreviews){
        const file=files.get(id)||preview.file;
        if(!file.available||file.expires_at&&Date.parse(file.expires_at)<=Date.now()||![...cards.values()].some(card=>(card.source.artifacts||[]).some(v=>v.id===id)||file.native_source===card.source.id||file.result_id&&file.result_id===card.source.result_id))closeFilePreview(id);
      }
      for(const card of cards.values())renderFiles(card);
    }
    async function verifyArtifact(blob,asImage){
      const bytes=await blob.arrayBuffer(),view=new Uint8Array(bytes);
      const hash=[...new Uint8Array(await crypto.subtle.digest("SHA-256",bytes))].map(value=>value.toString(16).padStart(2,"0")).join("");
      const starts=prefix=>prefix.every((n,i)=>view[i]===n);let type;
      if(asImage){
        if(starts([137,80,78,71,13,10,26,10]))type="image/png";
        else if(starts([255,216,255]))type="image/jpeg";
        else if(view.length>=12&&starts([82,73,70,70])&&[87,69,66,80].every((n,i)=>view[i+8]===n))type="image/webp";
      }
      return {hash,type};
    }
    async function downloadFile(file,preview=false){
      if(preview&&(!imageFile(file)||!previewRoom(file)))return;
      if(!canFiles || fileDownloads.has(file.id) || fileDownloads.size>=2 || !file.available)return;
      if(!/^[a-f0-9-]{36}$/.test(file.id) || !/^[a-f0-9]{64}$/.test(file.sha256) || !Number.isSafeInteger(file.bytes) || file.bytes<0 || file.bytes>256*1024*1024)return;
      const controller=new AbortController(),credential=fileCredential(),deadline=setTimeout(()=>controller.abort(),120000);
      fileDownloads.set(file.id,controller);fileStatus.set(file.id,"Downloading…");refreshFiles();
      try{
        const response=await fetch(`api/interaction/artifacts/${encodeURIComponent(file.id)}`,{headers:headers(),credentials:"same-origin",signal:controller.signal});
        if(!response.ok)throw Object.assign(Error("File unavailable or access changed."),{status:response.status});
        if(response.headers.get("X-Artifact-Sha256")!==file.sha256)throw Error("File changed. Refresh before downloading.");
        const blob=await response.blob();if(blob.size!==file.bytes)throw Error("Download interrupted. Try the same file again.");
        const {hash,type}=await verifyArtifact(blob,preview);
        if(hash!==file.sha256)throw Error("File verification failed. Nothing was saved.");
        if(controller.signal.aborted || fileDownloads.get(file.id)!==controller || !canFiles || fileCredential()!==credential || files.has(file.id) && files.get(file.id).sha256!==file.sha256)return;
        if(preview){
          if(!type)throw Error("This file cannot be shown as an image.");
          if(!previewRoom(file))throw Error("Close another image before opening this one.");
          const url=URL.createObjectURL(new Blob([blob],{type}));filePreviews.set(file.id,{url,sha256:file.sha256,bytes:file.bytes,file});fileStatus.set(file.id,"Image verified");return;
        }
        if(window.NativeFiles?.save){
          const saved=await window.NativeFiles.save(blob,file.name,file.sha256);
          fileStatus.set(file.id,saved?"Saved":"Save cancelled. Original remains available.");return;
        }
        const url=URL.createObjectURL(blob),link=node("a");link.href=url;link.download=file.name;link.hidden=true;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);
        fileStatus.set(file.id,"Download ready");
      }catch(error){if(fileDownloads.get(file.id)===controller && fileCredential()===credential){fileStatus.set(file.id,error.name==="AbortError"?"Download stopped. You can try again.":error.message||"File unavailable.");if(error.status===401)failed(error);}}
      finally{clearTimeout(deadline);if(fileDownloads.get(file.id)===controller)fileDownloads.delete(file.id);refreshFiles();}
    }
    let voiceEnabled=false,voiceSuspended=false,captureBusy=false,voiceBusy=false,voiceContext,voiceMode,conversationOnly=false,voiceModePrevious,voiceSession,continuousEnabled=false,nativeEnabled=false,nativeVoiceSession,legacyVoiceSession;
    let providerVoiceSession,codexVoiceSession,publicLiveSession,voiceChoice='provider',codexEnabled=false,publicLiveEnabled=false,publicLiveResponsesEnabled=false,publicLiveNativeEnabled=false,providerNativeEnabled=false,providerContinuousEnabled=false,providerVoiceAvailable=false;
    const voiceEngine=$('#conversation-voice-engine'),voiceChoiceBox=$('#conversation-voice-choice');
    let conversationServices='current',openaiConversationAvailable=false,lastVoiceCapabilities,servicesDefaultApplied=false;
    const servicesEngine=$('#conversation-services-engine'),servicesChoice=$('#conversation-services-choice');
    function applyConversationServices(){
      const useOpenAI=conversationServices==='openai';
      if(lastVoiceCapabilities){
        canStreamSpeech=canListen&&!!(useOpenAI?lastVoiceCapabilities.openai_can_stream_speech:(lastVoiceCapabilities.previous_can_stream_speech??lastVoiceCapabilities.can_stream_speech));
        canSpeakLive=canListen&&(useOpenAI?lastVoiceCapabilities.openai_speech_live_response:(lastVoiceCapabilities.previous_can_speak_live_response??lastVoiceCapabilities.can_speak_live_response))===true;
        microphone?.configure(lastVoiceCapabilities.can_speak,!useOpenAI&&(lastVoiceCapabilities.previous_can_stream_transcribe??lastVoiceCapabilities.can_stream_transcribe),lastVoiceCapabilities.streaming_transcription_mode,useOpenAI&&lastVoiceCapabilities.openai_can_stream_transcribe);
      }
      if(servicesChoice)servicesChoice.hidden=lastVoiceCapabilities?.voice_services_only==='openai'||!openaiConversationAvailable&&conversationServices==='current';
      const previousOption=servicesEngine?.querySelector?.('option[value="current"]');if(previousOption)previousOption.textContent=lastVoiceCapabilities?.voice_services_default==='openai'?'Previous voice':'Current voice';
      if(servicesEngine){servicesEngine.value=conversationServices;servicesEngine.disabled=captureBusy||voiceBusy||!!active||!!speechWait||!!voiceSession?.active||!!microphone?.ownsSend();}
    }
    servicesEngine?.addEventListener('change',()=>{
      if(captureBusy||voiceBusy||active||speechWait||voiceSession?.active||microphone?.ownsSend()||!['current','openai'].includes(servicesEngine.value)||servicesEngine.value==='openai'&&!openaiConversationAvailable){servicesEngine.value=conversationServices;return;}
      stop();conversationServices=servicesEngine.value;
      if(conversationServices==='openai'&&publicLiveNativeEnabled){voiceChoice='gpt-live-native';selectVoiceEngine();}
      if(conversationServices!=='openai'&&voiceChoice==='conversation'){voiceChoice='provider';selectVoiceEngine();}
      applyConversationServices();
    });
    const isPublicLive=()=>voiceChoice==='gpt-live'||voiceChoice==='gpt-live-native';
    const canonicalVoiceAvailable=()=>conversationServices==='openai'&&lastVoiceCapabilities?.can_openai_converse_continuous===true;
    function selectVoiceEngine(){
      const publicEnabled=voiceChoice==='gpt-live-native'?publicLiveNativeEnabled:publicLiveResponsesEnabled;
      const canonical=voiceChoice==='conversation';
      const nextNative=!canonical&&(isPublicLive()?publicEnabled:voiceChoice==='codex'?codexEnabled:providerNativeEnabled);
      const next=canonical?(canonicalVoiceAvailable()?legacyVoiceSession:undefined):isPublicLive()?(publicEnabled?publicLiveSession:undefined):voiceChoice==='codex'?(codexEnabled?codexVoiceSession:undefined):providerNativeEnabled?providerVoiceSession:legacyVoiceSession;
      if((next!==voiceSession||nextNative!==nativeEnabled)&&voiceMode?.active)voiceMode.close();
      nativeEnabled=nextNative;nativeVoiceSession=nextNative?next:providerVoiceSession;voiceSession=next;
      continuousEnabled=canonical?canonicalVoiceAvailable():isPublicLive()?publicEnabled:voiceChoice==='codex'?codexEnabled:providerNativeEnabled||providerContinuousEnabled;
      voiceMode?.configure(canonical?canonicalVoiceAvailable():isPublicLive()?publicEnabled:voiceChoice==='codex'?codexEnabled:providerVoiceAvailable||providerNativeEnabled,continuousEnabled);
      if(voiceEngine){
        voiceEngine.value=voiceChoice;voiceEngine.disabled=!!voiceSession?.active;
        const codexOption=voiceEngine.querySelector?.('option[value="codex"]');
        if(codexOption)codexOption.disabled=!codexEnabled;
        const publicOption=voiceEngine.querySelector?.('option[value="gpt-live"]');
        if(publicOption)publicOption.disabled=!publicLiveResponsesEnabled;
        const nativeOption=voiceEngine.querySelector?.('option[value="gpt-live-native"]');
        if(nativeOption)nativeOption.disabled=!publicLiveNativeEnabled;
        const canonicalOption=voiceEngine.querySelector?.('option[value="conversation"]');
        if(canonicalOption)canonicalOption.disabled=!canonicalVoiceAvailable();
      }
      if(voiceChoiceBox)voiceChoiceBox.hidden=!codexEnabled&&!publicLiveEnabled&&!canonicalVoiceAvailable()&&voiceChoice==='provider';
    }
    voiceEngine?.addEventListener('change',()=>{
      if(voiceSession?.active||voiceMode?.active){voiceEngine.value=voiceChoice;return;}
      if(!['provider','codex','gpt-live','gpt-live-native','conversation'].includes(voiceEngine.value)||voiceEngine.value==='codex'&&!codexEnabled||voiceEngine.value==='gpt-live'&&!publicLiveResponsesEnabled||voiceEngine.value==='gpt-live-native'&&!publicLiveNativeEnabled||voiceEngine.value==='conversation'&&!canonicalVoiceAvailable())return;
      voiceChoice=voiceEngine.value;selectVoiceEngine();
    });
    // Reuse the same presence renderer in the fixed header, freeing conversation space.
    if(standalone){
      const presence=$("#conversation-companion"),identity=$("header .identity");
      if(presence && identity)identity.append(presence);
      const build=$("#client-build"),name=$("#conversation-companion .companion-name");
      if(build && name)name.before(build);
      const compose = $("#conversation-compose"), playback = $("#conversation-audio-tools");
      const dock = node("div"); dock.id = "conversation-dock";
      const bar = node("div"); bar.id = "conversation-compose-bar";
      compose.before(dock); dock.append(bar, playback, compose);
      bar.append($("#conversation-compose-notices"));
    }
    const avatarWorkshop=standalone&&!readOnly?window.AvatarWorkshopUI?.mount({api,headers}):undefined;
    const companion=standalone?window.ConversationCompanion?.mount({onArtisticRest:rest=>avatarWorkshop?.artisticRest(rest)}):undefined;
    let headerSignal,headerSignalAt=-Infinity;
    const headerMotion=window.matchMedia?.('(prefers-reduced-motion: reduce)');
    try{if(standalone)headerSignal=window.ConversationVoiceMode?.signalSurface?.(document.querySelector('header'));}catch{/* Optional feedback cannot affect voice. */}
    const clearHeaderSignal=()=>{try{headerSignal?.clear();}catch{}};
    function showHeaderSignal(patch){
      if(!headerSignal)return;
      if(document.hidden||headerMotion?.matches||patch.connected===false){clearHeaderSignal();return;}
      const levels={};
      if(Object.hasOwn(patch,'inputLevel'))levels.inputLevel=patch.inputLevel;
      else if(patch.capture&&patch.capture!=='recording')levels.inputLevel=0;
      if(Object.hasOwn(patch,'outputSignalLevel'))levels.outputLevel=patch.outputSignalLevel;
      else if(Object.hasOwn(patch,'outputLevel'))levels.outputLevel=patch.outputLevel;
      else if(patch.playback&&patch.playback!=='playing')levels.outputLevel=0;
      if(!Object.keys(levels).length)return;
      const now=performance.now(),zero=Object.values(levels).every(v=>!v);
      if(!zero&&now-headerSignalAt<100)return;
      headerSignalAt=now;try{headerSignal.update(levels);}catch{/* Cosmetic failure stays local. */}
    }
    document.addEventListener('visibilitychange',()=>{if(document.hidden)clearHeaderSignal();});
    window.addEventListener('pagehide',clearHeaderSignal);
    headerMotion?.addEventListener?.('change',()=>{if(headerMotion.matches)clearHeaderSignal();});
    const presentState=(patch,updateVoice=true)=>{showHeaderSignal(patch);if(Object.hasOwn(patch,'outputLevel')){avatarWorkshop?.speechLevel?.(patch.outputLevel);hostSurface?.playback(patch.outputLevel);}else if(patch.playback&&patch.playback!=='playing')hostSurface?.playback(0);companion?.update(patch);if(updateVoice)voiceMode?.update(patch);};
    const settings=$("#conversation-settings"), settingsButton=$("#conversation-settings-open");
    if(settingsButton && settings){
      settingsButton.hidden=readOnly;
      settingsButton.addEventListener("click",()=>settings.showModal());
    }
    const decisionDialog=$("#conversation-goal-review"), decisionButton=$("#conversation-goals-open");
    decisionButton?.addEventListener("click",()=>decisionDialog?.showModal());
    const budgetView=$("#conversation-coordination"),budgetRefresh=$("#conversation-coordination-refresh"),budgetStatus=$("#conversation-coordination-status"),budgetEpisodes=$("#conversation-coordination-episodes");
    let canBudgets=false,budgetLoading=false,budgetControlBusy=false;
    const pendingBudgetControls=new Map();
    const budgetLabels={paused:"Paused",expired:"Expired",not_started:"Not started",call_fuel_exhausted:"Call allowance exhausted",charge_exposure_unavailable:"Charge allowance reserved or insufficient",concurrency_full:"Concurrency limit reached",uncertain_exposure:"An earlier operation is unconfirmed",clock_untrusted:"Clock requires operator attention"};
    async function loadBudgets(){
      if(!canBudgets||budgetLoading)return;
      budgetLoading=true;budgetRefresh.disabled=true;budgetStatus.textContent="Reading budgets…";
      const authority=fileCredential();
      try{
        const value=await api("interaction/coordination");
        if(!canBudgets||fileCredential()!==authority)return;
        if(value.state!=="available"){budgetStatus.textContent=value.state==="busy"?"Another budget read is finishing. Refresh when ready.":"Budgets are not configured.";return;}
        budgetEpisodes.replaceChildren();
        for(const episode of value.episodes){
          const card=node("li"),title=node("h3",episode.objective);card.append(title);
          card.append(node("p",`${episode.work.queued||0} queued · ${episode.work.intent||0} admitted`,"note"));
          const participants=node("details"),participantSummary=node("summary",`Participants (${episode.participants.length})`);participants.append(participantSummary,node("p",episode.participants.join(", "),"note"));card.append(participants);
          const expiry=new Date(episode.end*1000);if(Number.isFinite(expiry.getTime()))card.append(node("p",`Expires ${expiry.toLocaleString()}`,"note"));
          if(episode.constraints.length)card.append(node("p",episode.constraints.map(v=>budgetLabels[v]||v).join(" · "),"note"));
          const accounts=node("ul");accounts.className="coordination-accounts";
          for(const account of episode.accounts){
            const row=node("li");row.append(node("strong",`${account.kind[0].toUpperCase()+account.kind.slice(1)} · ${account.account_id}`));
            row.append(node("p",`${account.available_calls.toLocaleString()} of ${account.max_calls.toLocaleString()} calls left`));
            row.append(node("p",`${account.available_charge.toLocaleString()} ${account.unit} available · ${account.spent.toLocaleString()} spent · ${account.reserved.toLocaleString()} reserved`,"note"));
            row.append(node("p",`${account.active} active · ${account.uncertain} unconfirmed`,"note"));
            if(account.paused)row.append(node("p","Paused","note"));accounts.append(row);
          }
          card.append(accounts);
          if(episode.notice){const notice=node("p","Earlier allowance notice. Check the current balances above; reservations may have changed.","note");notice.dataset.noticeId=episode.notice.id;card.append(notice);}
          const root=episode.accounts.find(account=>account.kind==="episode"&&account.account_id===episode.id);
          if(value.can_control===true&&Number.isSafeInteger(root?.control_revision)&&root.control_revision>=0){
            const button=node("button",pendingBudgetControls.has(episode.id)?"Check previous control":root.paused?"Resume coordination":"Pause new coordination");button.type="button";
            button.disabled=budgetControlBusy;
            button.addEventListener("click",async()=>{
              if(budgetControlBusy||!canBudgets||fileCredential()!==authority)return;
              if(!pendingBudgetControls.has(episode.id)&&pendingBudgetControls.size>=8){budgetStatus.textContent="Check the retained controls before selecting another episode.";return;}
              const body=pendingBudgetControls.get(episode.id)||{nonce:crypto.randomUUID(),account_id:episode.id,expected_revision:root.control_revision,paused:!root.paused};
              pendingBudgetControls.set(episode.id,body);budgetControlBusy=true;button.disabled=true;
              budgetStatus.textContent="Recording coordination control…";
              try{
                const outcome=await api("interaction/coordination/control",body);
                if(fileCredential()!==authority)return;
                if(outcome.state==="confirmed"||outcome.state==="rejected")pendingBudgetControls.delete(episode.id);
                budgetControlBusy=false;await loadBudgets();
                budgetStatus.textContent=outcome.state==="confirmed"?"Control recorded. Pausing blocks new work; resuming does not start or repeat work.":outcome.state==="rejected"?"Control rejected. Refresh the current allowance and its authority.":"Control outcome is unconfirmed. Check the same action before another control.";
              }catch(error){if(fileCredential()===authority){button.textContent="Check previous control";budgetStatus.textContent="Control outcome is unconfirmed. Check the same action before another control.";}}
              finally{budgetControlBusy=false;button.disabled=false;}
            });
            card.append(button,node("p","Pause blocks new coordination. It does not stop an active call or change the allowance.","note"));
          }else card.append(node("p","Read only. These observations do not start work or change its limits.","note"));
          budgetEpisodes.append(card);
        }
        budgetStatus.textContent="Current budget observation. Refresh to read again.";
      }catch(error){budgetEpisodes.replaceChildren();budgetStatus.textContent="Budgets are unavailable. The conversation can continue.";}
      finally{budgetLoading=false;budgetRefresh.disabled=false;}
    }
    budgetRefresh?.addEventListener("click",loadBudgets);
    budgetView?.addEventListener("toggle",()=>{if(budgetView.open)loadBudgets();});
    const speechGaps={chunk:180,reply:450,question:1200};
    let speechWait;
    const voiceQueue=[],voiceSeen=new Set(),voiceFinalTimes=new Map();
    const queuedPreparations=new Map(),skippedMessages=new Map(),interruptedTurns=new Map();
    const messageKey=source=>sameNative(source,source)?JSON.stringify([source.native_turn,source.native_item]):JSON.stringify([source?.id,source?.revision]);
    const sameMessage=(a,b)=>a && b && (a.id===b.id && a.revision===b.revision || sameNative(a,b));
    function rememberSkipped(source){
      if(!source)return;
      skippedMessages.set(messageKey(source),true);
      while(skippedMessages.size>128)skippedMessages.delete(skippedMessages.keys().next().value);
    }
    function retainedCorrection(value){
      const reference=value?.playback;
      for(const [turn,source] of interruptedTurns)if(reference?.source===source.id && reference.revision===source.revision)interruptedTurns.delete(turn);
    }
    const automaticInterrupted=source=>{
      const previous=source?.kind?.startsWith("integrator_") && interruptedTurns.get(source.native_turn);
      if(!previous)return false;
      // A newly sourced internal return is independent useful conversation,
      // even if the native runtime steers it into the same physical turn.
      const key=value=>typeof value==="string"?value:JSON.stringify(value);
      const known=new Set((previous.native_returns||[]).map(key));
      return !Array.isArray(source.native_returns) || !source.native_returns.some(value=>!known.has(key(value)));
    };
    const preparationKey=(source,offset=source?.speech_start||0)=>JSON.stringify([source?.id,source?.revision,offset]);
    const sameNative=(a,b)=>a && b && typeof a.native_turn==="string" && typeof a.native_item==="string" && a.native_turn===b.native_turn && a.native_item===b.native_item;
    function removeQueued(index){
      const [source]=voiceQueue.splice(index,1),key=preparationKey(source),prepared=queuedPreparations.get(key);
      prepared?.controller.abort();queuedPreparations.delete(key);return source;
    }
    function clearVoiceQueue(){for(const prepared of queuedPreparations.values())prepared.controller.abort();queuedPreparations.clear();voiceQueue.length=0;}
    function cancelPreparedMessage(source){
      if(sameNative(prefetched?.source||prefetched?.owner,source)){prefetched.controller.abort();prefetched=undefined;}
      for(let n=voiceQueue.length-1;n>=0;n--)if(sameNative(voiceQueue[n],source) && queuedPreparations.has(preparationKey(voiceQueue[n])))removeQueued(n);
    }
    function parkPrepared(){
      if(!prefetched?.ahead)return;
      const prepared=prefetched;prefetched=undefined;
      if(!prepared.source || active?.interrupted){prepared.controller.abort();return;}
      const source={...prepared.source,speech_start:prepared.offset};queuedPreparations.set(preparationKey(source),prepared);
      const existing=voiceQueue.findIndex(value=>value.id===source.id && value.revision===source.revision);
      if(existing>=0)voiceQueue[existing]=source;
      else {const nextReply=voiceQueue.findIndex(value=>value.kind!=="native_question");voiceQueue.splice(nextReply<0?voiceQueue.length:nextReply,0,source);}
    }

    const liveSpeech=window.LiveSpeech?.mount(standalone?{
      read:key=>window.localStorage?.getItem(key),write:(key,value)=>window.localStorage?.setItem(key,value)
    }:undefined);let canSpeakLive=false;
    let pendingNavigation,internalControls,internalAttentionItems=()=>[];
    async function listenFromAttention(source){
      try{await voiceMode?.close();}
      catch{audioState('Voice could not finish closing. Return to the conversation before listening.');return;}
      return listenTo(source);
    }
    let canDecideRequests=!readOnly&&!standalone;
    const requestControls = window.RequestControls.mount({api,getBinding:()=>binding,setCsrf,unauthorized:failed,onReply:(...args)=>{pendingNavigation?.close(false);voiceMode?.close();return selectFocus(...args);},onListen:listenFromAttention,getCanListen:()=>canListen,getCanDecide:()=>canDecideRequests,allowCancel:()=>canDecideRequests,makeCopy:read=>copyButton(()=>copyParts(read)),onSource:offerVoice});
    const taskControls=window.HumanTaskControls?.mount({api,getBinding:()=>binding,setCsrf,unauthorized:failed,canReply:()=>!readOnly,makeCopy:read=>copyButton(()=>copyParts(read)),onReply:task=>{
      if(readOnly || posting || draft.value.trim())return false;
      pendingNavigation?.close(false);voiceMode?.close();voiceContext=undefined;selectFocus({source:`task:${task.id}`,revision:task.revision,context_only:true},`${task.label} · ${task.title}`);return true;
    }});
    const goalControls=window.GoalControls?.mount({api,getBinding:()=>binding,readOnly,onAvailable:available=>{
      if(decisionButton)decisionButton.hidden=!available;
      if(!available && decisionDialog?.open)decisionDialog.close();
    },onChoose:message=>{
      if(readOnly || posting || draft.value.trim())return false;
      decisionDialog?.close?.();pendingNavigation?.close(false);voiceMode?.close();clearFocus();voiceContext=undefined;draft.value=message;draftState?.change(message);draft.focus?.();compose.scrollIntoView?.({block:"nearest"});return true;
    }});
    if(standalone && !readOnly && !hostSurface){
      const inflight=new Map();
      const scopedApi=async(path,body)=>{
        const match=path.match(/^interaction\/(requests|tasks)(\?.*)?$/);
        if(match && body===undefined){
          const key=match[2]||"";
          let work=inflight.get(key);
          if(!work){work=api(`interaction/internal${key}`);inflight.set(key,work);work.finally(()=>{if(inflight.get(key)===work)inflight.delete(key);}).catch(()=>{});}
          const page=await work;
          return {...page,items:page.items.filter(v=>match[1]==="tasks"?v.kind==="task":v.kind!=="task")};
        }
        return api(path.replace(/^interaction\/(requests|tasks)/,"interaction/internal/$1"),body);
      };
      const requests=window.RequestControls.mount({api:scopedApi,getBinding:()=>binding,setCsrf,unauthorized:failed,prefix:"internal",allowCancel:()=>canDecideRequests,getCanDecide:view=>canDecideRequests||view?.kind==="question"});
      const tasks=window.HumanTaskControls?.mount({api:scopedApi,getBinding:()=>binding,setCsrf,unauthorized:failed,prefix:"internal"});
      const panel=$("#internal-attention");panel.hidden=false;
      $("#conversation-attention").append(panel);
      // A routed task can appear in both readers. Keep its ledger identity so
      // For you uses the Conversation card when available, with its reply control.
      internalAttentionItems=()=>[
        ...requests.attentionItems().map(item=>({...item,id:`internal:${item.id}`})),
        ...(tasks?.attentionItems()||[])
      ];
      internalControls={refresh:()=>Promise.all([requests.refresh(),tasks?.refresh()]),reset:()=>{pendingNavigation?.close(false);requests.reset();tasks?.reset();}};
    }
    if(standalone && !readOnly)pendingNavigation=window.AttentionCarousel?.mount({
      line:$("header .header-tools"),panel:$("#conversation-attention"),localOnly:true,onChange:count=>voiceMode?.attention(count),
      getItems:()=>[...(requestControls.attentionItems?.()||[]),...(taskControls?.attentionItems?.()||[]),...internalAttentionItems()]
    });
    const attachedFiles = readOnly ? undefined : window.FileInput?.mount({headers,getBinding:()=>binding,unauthorized:failed,maxFiles:8-(hostSurface?.reservedFiles||0),maxBytes:40*1024*1024-(hostSurface?.reservedBytes||0)});
    const visual = readOnly ? undefined : window.VisualInput?.mount({headers,getBinding:()=>binding,unauthorized:failed});
    let transcriptPreview,editedPreview;
    function previewTranscript(value){
      const input=$('#conversation-message');if(!input)return;
      const previous=transcriptPreview;
      if(!value.active){
        if(!previous||value.id!==previous.id)return;
        transcriptPreview=undefined;if(value.edited)editedPreview={...previous,text:input.value};
        if(!value.edited&&input.value===previous.text){
          input.value=previous.binding===binding?previous.draft:'';
          if(previous.binding===binding)input.setSelectionRange?.(previous.start,previous.end);
        }
        input.readOnly=previous.readOnly;input.removeAttribute('data-voice-preview');return;
      }
      if(value.binding!==binding)return;
      if(!previous){
        transcriptPreview={id:value.id,binding,draft:input.value,start:input.selectionStart,end:input.selectionEnd,readOnly:input.readOnly,text:input.value};
        input.readOnly=!value.editable;input.setAttribute('data-voice-preview','true');
      }else if(previous.id!==value.id||input.value!==previous.text)return;
      // This is the existing audio recognizer's provisional preview, never a text submission.
      transcriptPreview.text=value.text;input.value=value.text;
      input.scrollTop=input.scrollHeight;if(value.resumed){input.focus?.();input.setSelectionRange?.(input.value.length,input.value.length);}
    }
    const microphone = readOnly ? undefined : window.VoiceInput?.mount({api,headers,beforeOriginal:hostSurface?value=>hostSurface.prepare(value):undefined,onOriginalAttempt:value=>hostSurface?.attempt?.(value),onOriginalDiscard:value=>hostSurface?.discard?.(value),getBinding:()=>binding,onTranscript:previewTranscript,canEditDraft:()=>lastVoiceCapabilities?.can_download_files===true,onTiming:(id,stage,detail)=>{timing?.mark(id,stage,detail);hostSurface?.status({id,phase:stage},true);},onInput:(value,version)=>{if(editedPreview?.id===value.id&&editedPreview.binding===binding){if(draft.value===editedPreview.text)draft.value=editedPreview.draft;editedPreview=undefined;}hostSurface?.status(value);retainedCorrection(value);voiceSession?.release(value.id);voiceMode?.update({sent:true});inputCard(value);if(timeline)timeline.scrollTop=timeline.scrollHeight;if(version===focusVersion)clearFocus();},getReply:()=>{const reference=inputReference();return reference&&({reference,version:focusVersion});},getPlayback:()=>playbackContext(true),getTranscriptionProfile:()=>conversationServices==='openai'?(lastVoiceCapabilities?.can_openai_live_result?'openai-live':'openai'):(lastVoiceCapabilities?.can_previous_live_result?'previous-live':lastVoiceCapabilities?.voice_services_default==='openai'?'previous':undefined),canFinalizeOpenAIFile:()=>lastVoiceCapabilities?.can_openai_conversation===true,getCaptureQuestions:()=>canLimitCaptureQuestions?requestControls.captureQuestions():undefined,getFiles:()=>attachedFiles?.capture(),onFilesSent:refs=>attachedFiles?.consumed(refs),getVisual:()=>visual?.captureForVoice?visual.captureForVoice():visual?.capture(),onVisualSent:reference=>visual?.consumed(reference),pauseAudio:beginVoiceCapture,getLevelSink:value=>hostSurface?.microphoneSink(value),onLevel:value=>{if(!value)hostSurface?.silenceMicrophone();presentState({inputLevel:value});},onActivity:(value,detail)=>{captureBusy=voiceMode?.active&&voiceModePrevious?.continuous?!!voiceSession?.floor:value;presentState({capture:detail?.phase,uploading:detail?.uploading,transcribing:detail?.transcribing,pending:detail?.pending,message:detail?.message,remaining:detail?.remaining});if(!captureBusy){if(voiceEnabled && active?.interrupted)toggle.disabled=!blobUrl;drainVoice();}},unauthorized:failed,telegram,onLocalDiscard:id=>voiceSession?.release(id)});
    document.body.classList.toggle("standalone-conversation",standalone);
    const timeline = standalone ? $("#conversation-timeline") : undefined;
    const headerBehavior=timeline?window.ConversationHeader?.mount({timeline}):undefined;
    const responseDraft=node("article",undefined,"reply response-draft");
    const responseDraftBody=node("div",undefined,"reply-text");
    responseDraft.id="conversation-response-draft";responseDraft.hidden=true;
    responseDraft.setAttribute("aria-label","Response being written");
    responseDraft.append(node("h3","Writing…"),responseDraftBody);
    function showResponseDraft(value){
      const text=value?.provisional===true && typeof value.text==="string" && value.text.length<=65536?value.text:"";
      const follow=atTimelineEnd();
      responseDraft.hidden=!text.trim();responseDraft.dataset.nativeKey=value?`${value.native_turn}:${value.native_item}`:"";
      if(responseDraftBody.dataset.text!==text){setReplyText(responseDraftBody,text);responseDraftBody.dataset.text=text;}
      if(!responseDraft.hidden){
        timing?.source({...value,kind:"integrator_live"});
        if(timeline)placeInTimeline(responseDraft,"response-draft",value.observed_at,follow);
        else $("#conversation-answers").append(responseDraft);
      }
    }
    if(timeline){
      timeline.hidden=false;
      $("#conversation-history").hidden=true;
      $("#conversation-refresh").hidden=true;
    }
    function atTimelineEnd() {return !!timeline && !followingSpeech() && timeline.scrollHeight-timeline.scrollTop-timeline.clientHeight<80;}
    function arrangeTimelineReplies() {
      if(!timeline)return;
      const reference=box=>JSON.stringify([box.dataset.sourceId,box.dataset.sourceRevision]);
      const visible=new Map([...timeline.children].filter(box=>box.dataset.sourceId && !box.dataset.replyAnchor).map(box=>[reference(box),box]));
      const needed=new Set();
      for(const card of inputs.values()){
        const reply=card.value.reply;if(!reply)continue;
        const key=JSON.stringify([reply.source,reply.revision]);
        if(visible.has(key))continue;
        const original=cards.get(reply.source)?.source;
        if(original?.revision!==reply.revision || original.kind!=="worker_progress")continue;
        needed.add(key);
        if(replyAnchors.has(key))continue;
        // A coalesced update must not replace the exact update the person answered.
        // Keep a compact visible anchor; routing still carries only the original reference.
        const box=node("article",undefined,"reply session-update"),time=node("time",undefined,"message-time");
        box.append(node("h3",`Referenced update from ${original.label}`),node("p",original.preview,"reply-text"),time);
        messageTime(time,original.observed_at);box.dataset.replyAnchor="true";
        box.dataset.sourceId=original.id;box.dataset.sourceRevision=original.revision;
        box.dataset.timelineKey=`reply-source:${key}`;box.dataset.timelineTime=String(Date.parse(original.observed_at)||0);
        replyAnchors.set(key,box);timeline.append(box);
      }
      for(const [key,box] of replyAnchors)if(!needed.has(key)){box.remove();replyAnchors.delete(key);}
      const chronological=[...timeline.children].sort((a,b)=>Number(a.dataset.timelineTime)-Number(b.dataset.timelineTime)||String(a.dataset.timelineKey).localeCompare(String(b.dataset.timelineKey)));
      const anchors=new Map(chronological.filter(box=>box.dataset.sourceId).map(box=>[reference(box),box]));
      const groups=new Map(),attached=new Set();
      for(const box of chronological){
        if(!box.dataset.replySource)continue;
        const anchor=anchors.get(JSON.stringify([box.dataset.replySource,box.dataset.replyRevision]));
        if(!anchor || anchor===box)continue;
        if(!groups.has(anchor))groups.set(anchor,[]);groups.get(anchor).push(box);attached.add(box);
      }
      const claudeReplies=new Map(chronological.filter(box=>box.dataset.claudeReplyTo)
        .map(box=>[box.dataset.claudeReplyTo,box]));
      const ordered=chronological.filter(box=>!attached.has(box) && !box.dataset.claudeReplyTo)
        .flatMap(box=>[box,...(groups.get(box)||[])])
        .flatMap(box=>claudeReplies.has(box.dataset.inputId)?[box,claudeReplies.get(box.dataset.inputId)]:[box]);
      // Move existing nodes only: expanded text, media, focus and drafts stay intact.
      ordered.forEach((box,index)=>{if(timeline.children[index]!==box)timeline.insertBefore(box,timeline.children[index]||null);});
    }
    function placeInTimeline(box, key, timestamp, nearEnd=atTimelineEnd()) {
      if(!timeline)return;
      box.dataset.timelineKey=key;
      const parsedTime=Date.parse(timestamp);
      box.dataset.timelineTime=String(Number.isFinite(parsedTime)?parsedTime:Number(box.dataset.timelineTime)||Date.now());
      const following=[...timeline.children].find(item=>item!==box &&
        (Number(item.dataset.timelineTime)>Number(box.dataset.timelineTime) ||
        (item.dataset.timelineTime===box.dataset.timelineTime && item.dataset.timelineKey>key)));
      timeline.insertBefore(box,following||null);
      arrangeTimelineReplies();
      if(nearEnd)timeline.scrollTop=timeline.scrollHeight;
    }
    const cards = new Map(),progressCards=new Map(),settledProgress=new Map(),replyAnchors=new Map();
    // Device-local audio attention, scoped to this conversation binding. No
    // transcript, labels, native work state or playback backlog is persisted.
    const mutedSessions=new Set(),soloSessions=new Set();let muteBinding,workspaceAudioScope,canReplyUpdates=false;
    function sessionKey(source){
      if(["integrator_answer","integrator_progress","integrator_live"].includes(source.kind) || source.kind==="native_question" && source.audio_track==="conversation")return "conversation";
      const target=source.target;
      if(!["worker_progress","worker_result","native_question"].includes(source.kind) || !target
        || !Number.isSafeInteger(target.chat_id) || target.thread_id!=null && !Number.isSafeInteger(target.thread_id))return;
      return JSON.stringify([target.chat_id,target.thread_id??null]);
    }
    function sessionMuted(source){
      const key=sessionKey(source);
      if(conversationOnly)return key!=="conversation";
      if(workspaceAudioScope!==undefined)return key!==workspaceAudioScope||mutedSessions.has(key);
      return key?mutedSessions.has(key)||soloSessions.size>0&&!soloSessions.has(key):soloSessions.size>0;
    }
    function restoreSessionKeys(saved,target){
      if(!Array.isArray(saved)||saved.length>256)return;
      for(const key of saved){
        if(key==="conversation"){target.add(key);continue;}
        if(typeof key!=="string" || key.length>64)continue;
        try{const pair=JSON.parse(key);
          if(Array.isArray(pair)&&pair.length===2&&Number.isSafeInteger(pair[0])&&(pair[1]===null||Number.isSafeInteger(pair[1]))
            &&JSON.stringify(pair)===key)target.add(key);
        }catch{}
      }
    }
    function loadSessionMutes(){
      if(muteBinding===binding)return;muteBinding=binding;mutedSessions.clear();soloSessions.clear();
      try{
        const raw=window.localStorage?.getItem("interaction-session-audio:"+binding);
        if(raw){
          if(raw.length>32768)return;
          const saved=JSON.parse(raw);if(saved?.version!==1)return;
          restoreSessionKeys(saved.muted,mutedSessions);restoreSessionKeys(saved.solo,soloSessions);
        }else{
          const legacy=window.localStorage?.getItem("interaction-session-mutes:"+binding);
          if(legacy&&legacy.length<=32768)restoreSessionKeys(JSON.parse(legacy),mutedSessions);
        }
      }catch{}
    }
    function audioFilterChanged({persist=true,scopeChanged=false}={}){
      if(persist)try{
        window.localStorage?.setItem("interaction-session-audio:"+binding,JSON.stringify({version:1,muted:[...mutedSessions],solo:[...soloSessions]}));
        window.localStorage?.removeItem?.("interaction-session-mutes:"+binding);
      }catch{}
      for(const other of [...cards.values(),...progressCards.values()])muteButtonState(other);
      workspace?.syncAudio();
      if(prefetched && sessionMuted(prefetched.source||prefetched.owner)){prefetched.controller.abort();prefetched=undefined;}
      for(let n=voiceQueue.length-1;n>=0;n--)if(sessionMuted(voiceQueue[n]))removeQueued(n);
      if(active&&(active.queued||scopeChanged||workspaceAudioScope!==undefined)&&sessionMuted(active.source))stop();
      else if(scopeChanged&&speechWait?.source&&sessionMuted(speechWait.source)){cancelSpeechWait();voiceBusy=false;}
      voiceStatus();Promise.resolve().then(drainVoice);
    }
    function muteButtonState(card){
      if(!card.mute)return;
      const key=sessionKey(card.muteSource),muted=mutedSessions.has(key),solo=soloSessions.has(key),label=key==="conversation"?"Conversation":card.muteSource.label||"this session";
      card.mute.setAttribute("aria-pressed",String(muted));
      card.mute.setAttribute("aria-label",`${muted?"Unmute":"Mute"} automatic audio updates from ${label}`);
      card.mute.title=card.mute.getAttribute?.("aria-label") || `${muted?"Unmute":"Mute"} automatic audio updates from ${label}`;
      card.mute.disabled=!muted&&mutedSessions.size>=256;
      if(card.mute.disabled)card.mute.title="Session mute limit reached. Unmute another session first.";
      card.mute.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H3v6h3l5 4Z"/>'+
        (muted?'<path d="m16 9 5 6m0-6-5 6"/>':'<path d="M15 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>')+'</svg>';
      card.solo.setAttribute("aria-pressed",String(solo));
      card.solo.setAttribute("aria-label",`${solo?"Remove solo from":"Solo"} automatic audio updates from ${label}`);
      card.solo.title=card.solo.getAttribute?.("aria-label");
      card.solo.disabled=!solo&&soloSessions.size>=256;
      card.reset.hidden=workspace?.active===true||mutedSessions.size===0&&soloSessions.size===0;
    }
    function pinButtonState(card){
      if(!card.pin)return;
      const state=workspace?.pinState(card.muteSource),label=card.muteSource.label||'Conversation';
      card.pin.hidden=!workspace;card.pin.disabled=!state?.available;
      card.pin.setAttribute('aria-pressed',String(!!state?.pinned));
      card.pin.title=state?.pinned?`Unpin ${label} as the input destination`:`Pin ${label} as the input destination`;
      card.pin.setAttribute('aria-label',card.pin.title);
    }
    function syncTitleControls(){for(const card of [...cards.values(),...progressCards.values()]){pinButtonState(card);muteButtonState(card);}}
    function sessionTitle(card,source,label){
      card.muteSource=source;
      const key=sessionKey(source);
      if(readOnly || !key){card.title.textContent=label;card.titleLabel=undefined;card.muteAttached=false;return;}
      // Refresh labels without detaching focused keyboard controls.
      if(!card.titleLabel){card.title.textContent="";card.titleLabel=node("span");card.title.append(card.titleLabel);}
      card.titleLabel.textContent=label;
      if(!card.mute){
        card.audioControls=node("span",undefined,"session-audio-controls");
        card.pin=node('button',undefined,'session-title-pin');card.pin.type='button';
        card.pin.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m15 3 6 6-4 1-3 5-5-5 5-3Z"/><path d="m9 15-6 6"/></svg>';
        card.pin.addEventListener('click',()=>workspace?.pinSource(card.muteSource));
        card.mute=node("button",undefined,"session-audio-mute");card.mute.type="button";
        card.mute.addEventListener("click",()=>{
          const selected=sessionKey(card.muteSource);if(!selected)return;
          if(mutedSessions.has(selected))mutedSessions.delete(selected);
          else {if(mutedSessions.size>=256)return;mutedSessions.add(selected);}
          audioFilterChanged();
        });
        card.solo=node("button",undefined,"session-audio-solo");card.solo.type="button";
        card.solo.innerHTML='<svg class="control-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M4 14v-3a8 8 0 0 1 16 0v3M4 12H2v8h5v-8ZM20 12h2v8h-5v-8Z"/></svg>';
        card.solo.addEventListener("click",()=>{
          const selected=sessionKey(card.muteSource);if(!selected)return;
          if(soloSessions.has(selected))soloSessions.delete(selected);
          else {if(soloSessions.size>=256)return;soloSessions.add(selected);}
          // Solo starts a fresh mix; previously muted tracks never reappear muted.
          mutedSessions.clear();audioFilterChanged();
        });
        card.reset=node("button",undefined,"session-audio-reset");card.reset.type="button";
        card.reset.setAttribute("aria-label","Hear all sessions: clear mute and solo");card.reset.title="Hear all sessions";
        card.reset.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10a9 9 0 1 1 1 7M3 4v6h6"/></svg>';
        card.reset.addEventListener("click",()=>{mutedSessions.clear();soloSessions.clear();audioFilterChanged();});
      }
      muteButtonState(card);pinButtonState(card);card.audioControls.hidden=false;
      if(!card.muteAttached){card.audioControls.replaceChildren(card.pin,card.mute,card.solo,card.reset);card.title.append(card.audioControls);card.muteAttached=true;}
    }
    function clearProgress(){for(const card of progressCards.values())card.box.remove();progressCards.clear();settledProgress.clear();}
    async function copyParts(read,valid=()=>true){
      let text="",offset=0;const deadline=Date.now()+15000;
      for(let n=0;n<128;n++){
        if(!valid() || Date.now()>deadline)throw Error("Message changed or copying took too long. Try again.");
        const value=await read(offset);
        if(!valid() || typeof value.text!=="string" || value.offset!==undefined && value.offset!==offset)throw Error("Message changed. Try again.");
        text+=value.text;
        if(text.length>262144)throw Error("Message is too large to copy at once.");
        if(value.next_offset===null)return text;
        if(!Number.isSafeInteger(value.next_offset)||value.next_offset<=offset)throw Error("Complete message unavailable. Try again.");
        offset=value.next_offset;
      }
      throw Error("Complete message unavailable. Try again.");
    }
    const foregroundCards=new Map();let foregroundReading=false;
    function foregroundCard(value){
      if(!value||value.kind!=="voice_foreground"||value.speaker!=="assistant"||typeof value.text!=="string"||value.text.length>16384)return;
      const derived=value.derived_caption,caption=!!(derived?.draft===true&&typeof derived.parent_source==="string"&&derived.parent_source.length<=128);
      const key=caption?derived.parent_source:value.id;
      let card=foregroundCards.get(key);
      if(!card){const box=node("article",undefined,"reply"),title=node("h3","Voice conversation"),status=node("p",undefined,"reply-status"),body=node("div",undefined,"reply-text"),actions=node("div",undefined,"reply-actions"),time=node("time",undefined,"message-time");
        card={box,status,body,time,value};actions.append(copyButton(()=>card.value.text));box.append(title,status,body,actions,time);foregroundCards.set(key,card);$("#conversation-answers").append(box);}
      if(caption)card.caption=value;else card.original=value;
      card.value=card.original?.text?card.original:(card.caption||card.original);
      const shown=card.value,approximate=shown===card.caption;
      setReplyText(card.body,shown.text);card.status.textContent=approximate?"Recovered voice transcript — approximate; it may contain errors.":shown.closed&&!shown.text&&shown.generated_bytes>0?"Voice response — transcript unavailable.":shown.interrupted?"Speech interrupted. The text includes generated words you may not have heard.":shown.closed?"Assistant voice conversation.":"Speaking…";
      const observed=new Date((card.original||shown).observed_at*1000).toISOString();messageTime(card.time,observed);placeInTimeline(card.box,'foreground:'+key,observed);
    }
    async function foregroundHistory(){
      if(foregroundReading)return;foregroundReading=true;
      try{
        const value=await api("interaction/foreground?before=0");
        for(const item of value.items)foregroundCard(item);
      }catch(error){if(error.status===401||error.status===403)failed(error);}
      finally{foregroundReading=false;}
    }
    function copyButton(read){
      const button=node("button","Copy");button.type="button";button.className="message-copy";
      button.setAttribute("aria-label","Copy message text");button.setAttribute("aria-live","polite");
      button.addEventListener("click",async()=>{
        if(button.disabled)return;
        button.disabled=true;button.textContent="Copying…";button.title="Copy message text";
        try{
          const clipboard=window.navigator?.clipboard;
          if(!clipboard)throw Error("Clipboard unavailable. Select the text to copy it.");
          // Start the clipboard write during the click, even when a complete
          // immutable message still needs paging (including Safari activation).
          const complete=()=>Promise.resolve().then(read).then(text=>{
            if(typeof text!=="string" || !text.length)throw Error("No message text is available yet.");return text;
          });
          if(clipboard.write && window.ClipboardItem){
            const payload=complete().then(text=>new Blob([text],{type:"text/plain"}));payload.catch(()=>{});
            await clipboard.write([new window.ClipboardItem({"text/plain":payload})]);
          }else if(clipboard.writeText)await clipboard.writeText(await complete());
          else throw Error("Clipboard unavailable. Select the text to copy it.");
          button.textContent="Copied";button.title="Message text copied";button.setAttribute("aria-label","Message copied. Copy again");
        }catch(error){button.textContent="Copy failed";button.title=error.message||"Could not copy. Try again.";button.setAttribute("aria-label",`Copy failed: ${button.title}`);}
        finally{button.disabled=false;}
      });
      return button;
    }
    async function copySource(card){
      if(!card)throw Error("Message unavailable. Refresh before copying.");
      const source=card.source,owned=binding;
      const valid=()=>binding===owned && cards.get(source.id)===card && card.source.revision===source.revision;
      if(card.expanded && card.offset===null && valid())return replyText(card.body);
      return copyParts(offset=>part(source,offset),valid);
    }
    const replyText=body=>window.ConversationMarkdown?.source(body) ?? body.textContent;
    const setReplyText=(body,text)=>window.ConversationMarkdown?window.ConversationMarkdown.render(body,text):(body.textContent=text);
    function sessionProgress(source){
      if(!timeline || !source.target || !["worker_progress","worker_result"].includes(source.kind))return;
      const key=`${source.target.chat_id}:${source.target.thread_id??""}`,stamp=Date.parse(source.observed_at)||0,previous=progressCards.get(key);
      if(source.kind==="worker_result"){
        settledProgress.set(key,Math.max(settledProgress.get(key)||0,stamp));
        if(previous && previous.stamp<=stamp){previous.box.remove();progressCards.delete(key);}return;
      }
      if(stamp<=(settledProgress.get(key)||0) || previous && previous.stamp>stamp)return;
      let card=previous;
      if(!card){
        const box=node("article",undefined,"reply session-update"),title=node("h3"),body=node("p",undefined,"reply-text"),listen=node("button","Listen");
        const time=node("time",undefined,"message-time"),reply=node("button","Reply to this update");reply.type="button";reply.className="session-update-reply";
        const read=node("button","Read reply"),error=node("p","","reply-error");read.type="button";read.className="session-update-read";error.setAttribute("role","status");
        listen.type="button";listen.className="session-update-listen";box.append(title,body,listen,reply,copyButton(()=>copySource(cards.get(card.source))),read,error,time);card={box,title,body,listen,reply,read,error,time};progressCards.set(key,card);
        read.addEventListener("click",()=>{const original=cards.get(card.source);if(!original || original.source.revision!==card.revision)return;return readCard(original);});
        reply.addEventListener("click",()=>{const original=cards.get(card.source);if(!original || original.source.revision!==card.revision || !canReplyUpdates || readOnly)return;selectFocus({source:card.source,revision:card.revision},original.source.label||"this session");});
        listen.addEventListener("click",()=>{const original=cards.get(card.source);if(!original || original.source.revision!==card.revision || !canListen)return;return listenCard(original);});
      }
      const changed=card.source!==source.id || card.revision!==source.revision;
      card.source=source.id;card.revision=source.revision;card.stamp=stamp;sessionTitle(card,source,`Update from ${source.label}`);
      card.box.dataset.sourceId=source.id;card.box.dataset.sourceRevision=source.revision;
      const original=cards.get(source.id);
      setReplyText(card.body,original?.expanded && original.source.revision===source.revision?replyText(original.body):source.preview);
      card.listen.hidden=!canListen;card.listen.setAttribute("aria-label",`Listen to update from ${source.label}`);
      card.reply.hidden=readOnly||!canReplyUpdates;
      if(original)progressTextControls(original);
      messageTime(card.time,source.observed_at);
      placeInTimeline(card.box,`session-update:${key}`,source.observed_at);
      if(changed)textObserver?.unobserve(card.box);
      textObserver?.observe(card.box);
    }

    function progressTextControls(original){
      for(const visible of progressCards.values())if(visible.source===original.source.id && visible.revision===original.source.revision){
        visible.read.hidden=original.read.hidden;visible.read.disabled=original.read.disabled;
        visible.read.textContent=original.read.textContent;
        visible.error.textContent=original.error.textContent;visible.error.hidden=!original.error.textContent;
      }
    }

    // Read visible answers through the existing immutable source endpoint. Two
    // finite readers keep long history from blocking input or flooding the API.
    const textQueue=[];let textJobs=0;
    const textObserver=timeline && window.IntersectionObserver?new window.IntersectionObserver(entries=>{
      for(const entry of entries){const card=cards.get(entry.target.dataset.sourceId)||inputs.get(entry.target.dataset.inputId);if(card){card.textVisible=entry.isIntersecting;if(card.textVisible)queueText(card);}}
    },{root:timeline,rootMargin:"200px"}):undefined;
    const textRevision=card=>card.source?.revision ?? card.value.preview;
    const inputNeedsText=card=>!card.value.text && Array.from(card.value.preview||"").length>=1000 && card.originalOffset!==null;
    function autoTextEligible(card){
      if(card?.value)return card.textVisible && inputs.get(card.value.id)===card && inputNeedsText(card) && card.autoRevision!==textRevision(card);
      return card && card.textVisible && cards.get(card.source.id)===card
      && ["integrator_answer","integrator_progress","worker_progress","worker_result","matrix_result"].includes(card.source.kind)
      && Number.isSafeInteger(card.source.text_characters) && card.source.text_characters>Array.from(card.source.preview).length
      && !(card.expanded && card.offset===null) && card.autoRevision!==card.source.revision;}
    function queueText(card){
      if(!autoTextEligible(card))return;
      card.autoWanted=true;
      if(!card.textLoading && !textQueue.includes(card))textQueue.push(card);
      drainText();
    }
    function drainText(){
      while(textJobs<2 && textQueue.length && enabled && ready && !document.hidden){
        const card=textQueue.shift();if(!autoTextEligible(card)||card.textLoading)continue;
        const revision=textRevision(card);textJobs++;
        void (card.value?readInputText(card,true):readCard(card,true)).finally(()=>{
          textJobs--;if(card.autoWanted && textRevision(card)!==revision)queueText(card);drainText();
        });
      }
    }
    function clearText(){textQueue.length=0;textObserver?.disconnect();}
    function renderInputText(card){
      const text=card.value.text || card.originalText || card.value.preview;
      hostSurface?.status(card.value);
      card.text.textContent=card.value.voice?(text?"Automatic voice transcript:\n"+text:"Original voice recording saved."):text;
      const reply=card.value.claude_reply;
      if(typeof reply?.text==="string"){
        if(!card.claudeBody){
          card.claudeBox=node("article",undefined,"reply claude-message");
          card.claudeBody=node("div",undefined,"reply-text");
          card.claudeRead=node("button","Read full reply");card.claudeRead.type="button";
          card.claudeRead.addEventListener("click",async()=>{
            const owned=inputGeneration,id=card.value.id,message=card.value.claude_reply?.message_id;
            const valid=()=>owned===inputGeneration && inputs.get(id)===card && card.value.claude_reply?.message_id===message;
            card.claudeRead.disabled=true;
            try{
              card.claudeFull=await copyParts(async offset=>{
                const part=await api(`interaction/inputs/${encodeURIComponent(id)}/trace/claude-reply?offset=${offset}`);
                if(part.id!==id || part.source!=="claude-reply")throw Error("Reply changed");
                return part;
              },valid);
              if(valid())renderInputText(card);
            }catch(error){
              if(valid()){card.claudeRead.textContent="Retry reading reply";if([401,403].includes(error.status))failed(error);}
            }finally{card.claudeRead.disabled=false;}
          });
          card.claudeBox.append(node("h3","Claude Code"),card.claudeBody,card.claudeRead);
          card.claudeBox.dataset.claudeReplyTo=card.value.id;
        }
        setReplyText(card.claudeBody,card.claudeFull??reply.text);
        card.claudeRead.hidden=card.claudeFull!==undefined || !Number.isSafeInteger(reply.next_offset);
        placeClaudeReply(card);
      }
      if(inputNeedsText(card)){
        card.check.hidden=false;card.check.textContent=card.originalText?"Continue reading":"Read full message";
      }else {
        card.check.textContent="Check status";
        card.check.hidden=readOnly || card.value.read_only===true || ((["accepted","routed","answered"].includes(card.value.phase) || claudeReplied(card.value.phase)) && (!!card.value.text || card.originalOffset===null || Array.from(card.value.preview||"").length<1000));
      }
    }
    function placeClaudeReply(card){
      if(!card.claudeBox || !card.box.parentNode)return;
      if(timeline){
        if(card.claudeBox.parentNode!==timeline)
          placeInTimeline(card.claudeBox,`claude-reply:${card.value.id}`,card.value.received_at);
      }else if(card.box.nextSibling!==card.claudeBox){
        card.box.parentNode.insertBefore(card.claudeBox,card.box.nextSibling);
      }
    }
    async function readInputText(card,automatic=false){
      if(card.textLoading || inputs.get(card.value.id)!==card)return;
      const owned=inputGeneration,id=card.value.id,preview=card.value.preview;
      const valid=()=>owned===inputGeneration && inputs.get(id)===card && card.value.preview===preview;
      card.textLoading=true;card.check.disabled=true;if(automatic)card.autoRevision=preview;
      try{
        let parts=0;
        do{
          const offset=card.originalOffset||0;
          const result=await api(`interaction/inputs/${encodeURIComponent(id)}/trace/original?offset=${offset}`);
          if(!valid())return;
          if(result.id!==id || result.source!=="original" || result.offset!==offset || typeof result.text!=="string"
            || (result.next_offset!==null && (!Number.isSafeInteger(result.next_offset)||result.next_offset!==offset+Array.from(result.text).length||result.next_offset<=offset)))throw Error("Saved message text changed. Refresh before reading.");
          const text=(card.originalText||"")+result.text;
          if(!text.startsWith(preview.slice(0,Math.min(preview.length,text.length))))throw Error("Saved message text changed. Refresh before reading.");
          card.originalText=text;card.originalOffset=result.next_offset;parts++;renderInputText(card);
        }while(automatic && card.originalOffset!==null && parts<12 && card.originalText.length<16000 && enabled && !document.hidden && card.textVisible);
        if(automatic && card.originalOffset!==null && parts<12 && card.originalText.length<16000 && (!enabled||document.hidden||!card.textVisible))card.autoRevision=undefined;
      }catch(error){
        if(valid()){card.status.textContent="Full message text unavailable. Nothing was resent.";card.check.textContent="Retry reading";card.check.hidden=false;if([401,403].includes(error.status))failed(error);}
      }finally{card.textLoading=false;card.check.disabled=false;if(automatic && card.autoRevision===undefined)queueText(card);}
    }
    function appendTextPart(card,result){
      const following=atTimelineEnd();
      setReplyText(card.body,(card.expanded?replyText(card.body):"")+result.text);
      card.expanded=true;card.offset=result.next_offset;
      for(const visible of progressCards.values())if(visible.source===card.source.id && visible.revision===card.source.revision)setReplyText(visible.body,replyText(card.body));
      card.read.hidden=card.offset===null;card.read.textContent="Continue reading";
      progressTextControls(card);
      if(following && timeline)timeline.scrollTop=timeline.scrollHeight;
    }
    async function readCard(card,automatic=false){
      if(card.textLoading || cards.get(card.source.id)!==card)return;
      const selected=card.source;card.textLoading=true;card.read.disabled=true;card.error.textContent="";
      progressTextControls(card);
      if(automatic)card.autoRevision=selected.revision;
      try{
        let parts=0;
        do{
          const result=await part(selected,card.offset);
          if(cards.get(selected.id)!==card || card.source.revision!==selected.revision)return;
          appendTextPart(card,result);
          parts++;
        }while(automatic && card.offset!==null && parts<12 && replyText(card.body).length<16000 && enabled && !document.hidden && card.textVisible);
        if(automatic && card.offset!==null && parts<12 && replyText(card.body).length<16000 && (!enabled || document.hidden || !card.textVisible)){
          card.autoRevision=undefined;card.autoWanted=true;
        }
      }catch(error){
        if(cards.get(selected.id)===card && card.source.revision===selected.revision){
          card.error.textContent=error.message;card.read.textContent="Retry reading";
          if(error.status===401 || error.status===403)failed(error);
        }
      }finally{card.textLoading=false;card.read.disabled=false;progressTextControls(card);if(automatic && card.autoWanted && card.autoRevision===undefined)queueText(card);}
    }

    const inputs = new Map();
    const compose = $("#conversation-compose"), draft = $("#conversation-message"), send = $("#conversation-send");
    const runtimeSummary=$("#conversation-runtime");
    function syncRuntimeSummary(){
      if(!runtimeSummary)return;
      const runtime=workspace?.runtime?.();
      const harness={codex:"Codex",claude:"Claude Code",antigravity:"Antigravity",goose:"Goose"}[runtime?.harness];
      const claudeModel=runtime?.harness==="claude"
        ? /^claude-(opus|sonnet|haiku)-(\d{1,2})(?:-(\d{1,2}))?(?:-\d{8})?$/.exec(runtime.model)
        : null;
      const modelNames={opus:"Opus",sonnet:"Sonnet",haiku:"Haiku"};
      const model=claudeModel
        ? `${modelNames[claudeModel[1]]} ${[claudeModel[2],claudeModel[3]].filter(Boolean).join(".")}`
        : modelNames[runtime?.model]??runtime?.model;
      const quota=runtime?.weekly_available_percent;
      const seconds=Math.floor(runtime?.weekly_resets_at-Date.now()/1000);
      const days=Math.floor(seconds/86400), hours=Math.floor(seconds/3600)%24;
      const reset=seconds>0?(days>0?`${days}d${hours}h`:hours>0?`${hours}h`:`${Math.ceil(seconds/60)}m`):"";
      const weekly=Number.isFinite(quota)&&quota>=0&&quota<=100
        ? [`${Math.round(quota)}%`,reset].filter(Boolean).join(" "):undefined;
      const limited=runtime?.session_available_percent===0 && runtime.session_resets_at>Date.now()/1000;
      const shortReset=limited?new Date(runtime.session_resets_at*1000):null;
      const shortLimit=shortReset ? "5h limit until "+shortReset.toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}) : "";
      const text=harness?[harness,model,runtime.effort,weekly,shortLimit].filter(Boolean).join(" · "):"";
      runtimeSummary.hidden=!text;
      runtimeSummary.textContent=text;
      runtimeSummary.title=text;
    }
    const draftStatus=node('div',undefined,'conversation-tools composer-draft-notice'),draftNote=node('span'),draftPrimary=node('button'),draftOther=node('button','Use other draft');
    draftStatus.hidden=true;draftNote.setAttribute('role','status');draftPrimary.type=draftOther.type='button';
    draftStatus.append(draftNote,draftPrimary,draftOther);
    const draftState=readOnly?undefined:window.ConversationSurface?.mountDraft?.({field:draft,api,
      busy:()=>posting||captureBusy||!!transcriptPreview,
      async check(id,text){
        const owned=inputGeneration,selected=inputBinding;
        const result=await api(`interaction/inputs/${encodeURIComponent(id)}`);
        if(owned!==inputGeneration||!selected||selected!==inputBinding||result.id!==id||!result.phase)return;
        const receipt=draftReceipt(result);
        if(receipt.binding!==selected)return;
        // The exact confirmed original may no longer be in the loaded history
        // window. Project it before the draft receipt releases the composer.
        if(!latestComposerId)latestComposerId=id;
        inputCard({...receipt,text},++inputObservation,selected);
        return receipt;
      },
      async retry(original){
        if(posting||captureBusy||!ready||original.binding!==binding||inputBinding!==binding)return;
        const owned=inputGeneration;
        const result=await api('interaction/inputs',original);
        if(owned!==inputGeneration||result.id!==original.id||!result.phase)return;
        const receipt=draftReceipt(result);
        if(receipt.binding!==original.binding)return;
        hostSurface?.status(result);
        if(!latestComposerId)latestComposerId=original.id;
        inputCard({...receipt,text:original.text},++inputObservation,original.binding);
        return receipt;
      },
      show(state,primary,other){
        draftStatus.hidden=!state;
        if(!state)return;
        const conflict=state==='conflict';
        draftNote.textContent=conflict?'Another device changed this draft.':'This message may already have been sent.';
        draftPrimary.textContent=conflict?'Keep this draft':'Check message status';draftPrimary.onclick=primary;
        draftOther.textContent=conflict?'Use other draft':'Retry this same message';
        draftOther.hidden=!other;draftOther.onclick=other;
      }});
    if(draftState)draft.after(draftStatus);
    let submittedText;
    // Keep a submitted draft intact until its original has an exact receipt.
    // A live transcript has its own editing lifecycle.
    const lockedDraft=()=>transcriptPreview?undefined:(submittedText??draftState?.lockedText());
    const pauseDraft=()=>{if(transcriptPreview&&microphone?.pauseEditing?.()){
      if(transcriptPreview.draft){draft.value=transcriptPreview.draft+'\n'+draft.value;transcriptPreview.draft='';transcriptPreview.text=draft.value;microphone.editDraft(draft.value);}
    }};
    draft.addEventListener('pointerdown',pauseDraft);
    draft.addEventListener('beforeinput',event=>{
      if(lockedDraft()!==undefined){event.preventDefault();return;}
      pauseDraft();
    });
    draft.addEventListener('input',()=>{
      const original=lockedDraft();
      if(original!==undefined){if(draft.value!==original)draft.value=original;return;}
      if(transcriptPreview){transcriptPreview.text=draft.value;microphone?.editDraft?.(draft.value);}
      else draftState?.change(draft.value);
    });

    const sharedText=readOnly?undefined:window.NativeSharedText?.mount({parent:compose,draft,onFiles:files=>attachedFiles.addFiles(files),getBinding:()=>binding,isBusy:()=>captureBusy||!!voiceMode?.active||!!microphone?.ownsSend()});
    const sendState = $("#conversation-send-state");
    const sendFeedback = $("#conversation-send-feedback");
    const composerDismiss = $("#conversation-send-dismiss");
    let noticeId, noticeAttention=false;
    function composerNotice(text,attention=true){
      if(noticeId!==latestComposerId || sendState.textContent!==text)sendFeedback.hidden=false;
      noticeId=latestComposerId;
      noticeAttention=attention&&!!text;
      if(sendState.textContent!==text)sendState.textContent=text;
      sendState.setAttribute('data-attention',String(attention));
      syncComposerRecovery();
    }
    const claudeReplied = phase => ["matrix_replied","claude_replied"].includes(phase);
    const claudeFailure = phase => ["claude_rejected","claude_unconfirmed"].includes(phase);
    const savedWaiting=value=>value.routing ? value.routing.phase==="queued" : ["retained","queued"].includes(value.phase);
    const contextUnavailable=route=>route?.phase==="retained_unsent" && route.context_unavailable;
    const goalControlUnavailable=route=>route?.phase==="retained_unsent" && route.goal_control_unavailable;
    const nativeToolDeclinedText="A tool request was declined and the session ended without a reply. Your message is saved.";
    function inputNotice(value){
      if(savedWaiting(value))return composerNotice('',false);
      composerNotice(phaseText(value),!!(value.subscription_limit || value.routing?.subscription_limit || contextUnavailable(value.routing) || goalControlUnavailable(value.routing) || value.routing?.native_tool_declined) || ['awaiting_target','preparation_unconfirmed','retained_unsent','uncertain','claude_unconfirmed','claude_rejected','reselection'].includes(value.phase) || (!value.phase && !value.routing));
    }
    let replyFocus, focusVersion = 0, routingChoices = [], presentationProfile;
    let posting = false, inputNewest = 0, inputBinding, inputEntryBinding, inputGeneration = 0, inputObservation = 0, latestComposerId;
    let telegramNewest=0,telegramLoaded=false,telegramReading=false;
    const portableDeliveryText = (phase,toolDeclined,limit) => limit ? subscriptionLimitText(limit) : toolDeclined ? nativeToolDeclinedText : ({
      queued:"Saved · waiting for the session",
      submitting:"Sending to the session…",
      steering:"Waiting for the session to pick up this message",
      accepted:"Received by the session",
      retained_unsent:"Saved · waiting to send",
      uncertain:"Saved · delivery unconfirmed",
      rejected:"Saved · the session did not receive this message",
      cancelled:"Saved · sending cancelled",
    })[phase];
    const phaseText = value => ["blocked","pending"].includes(value.media_retention?.state) ? value.media_retention.message : value.origin_kind==="telegram" ? portableDeliveryText(value.portable_phase,value.native_tool_declined,value.subscription_limit) ?? `Telegram input retained (${value.phase}). Inspect its routing path for delivery evidence.${value.ordering_unknown?" Historical capture order unavailable.":""}${!value.received_at?" Historical capture time unavailable.":""}` : value.retired ? "Saved from an earlier conversation binding."
      : value.subscription_limit ? subscriptionLimitText(value.subscription_limit)
      : (value.routing?.subscription_limit || contextUnavailable(value.routing) || goalControlUnavailable(value.routing) || value.routing?.native_tool_declined) ? routeText(value.routing)
      : value.target==="claude" ? ({retained:"Saved for Claude Code.",sending:"Sending to Claude Code…",matrix_received:"Received by Claude Code. Waiting for a confirmed reply.",matrix_replied:"",claude_preparing:"Preparing Claude Code…",claude_running:"Waiting for Claude Code…",claude_replied:"",retained_unsent:"Saved. Claude Code did not receive this message.",uncertain:"Delivery to Claude Code is unconfirmed.",claude_rejected:"Claude Code could not start. Your message is saved.",claude_unconfirmed:"Claude Code’s reply could not be confirmed. Your message is saved."})[value.phase]??"Check this message’s status before sending again."
      : value.routing ? routeText(value.routing) : ({foreground:"Saved in the voice conversation; no work requested automatically.",foreground_captured:"Voice original saved; waiting for its interpretation.",awaiting_target:"Choose the session for this saved message.",preparing:"Confirming transcript…", preparation_unconfirmed:"Recording saved; transcription unconfirmed. No work was submitted automatically.", retained:"Saved · in queue", queued:"Saved · in queue",
          sending:"Sending to your conversation…", steering:"Sending to your conversation…",
          accepted:"Sent to your conversation. Work may continue.", matrix_requested:"Saved for the selected daimon; awaiting its authorized execution and reply.",
          reselection:"This attempt did not submit the message. Select the image again, then send.", answered:"Answer recorded for the selected question. Work may continue.",
          retained_unsent:"Saved; not sent.", uncertain:"Saved; delivery unconfirmed. Check status."})[value.phase]
        || "Submission unconfirmed. Check status before sending this message again.";
    function subscriptionLimitText(limit) {
      const window=limit.window==="five_hour" ? "5-hour usage limit"
        : ["seven_day","seven_day_opus","seven_day_sonnet"].includes(limit.window) ? "weekly usage limit" : "usage limit";
      const reset=new Date(limit.resets_at*1000);
      const when=Number.isFinite(limit.resets_at)&&Number.isFinite(reset.getTime())
        ? " Resets "+reset.toLocaleString([], {dateStyle:"short",timeStyle:"short"})+"." : "";
      return `Claude Code reached its ${window}. Your message is saved.${when}`;
    }
    function routeText(route) {
      if(route.native_tool_declined)return `#${route.label}: ${nativeToolDeclinedText}`;
      if(goalControlUnavailable(route))return `#${route.label}: Claude Code cannot pause or resume a goal. The goal was not changed. Use /goal to check its status.`;
      if(contextUnavailable(route))return `#${route.label}: Your message is saved. Claude Code could not recover the earlier context it needs.`;
      if(route.subscription_limit)return `#${route.label}: ${subscriptionLimitText(route.subscription_limit)}`;
      if(!route.instruction)return `#${route.label}: `+({requested:"turn interruption requested.",no_active_turn:"no selected running turn.",scope_unavailable:"the original turn selection is unavailable; no interruption was made.",unconfirmed:"interruption remains unconfirmed; nothing will be repeated."}[route.phase]||"control outcome retained.");
      return `#${route.label}: `+({accepted:"sent to this session. Work may continue.",queued:"saved; waiting for this session.",submitting:"sending to this session…",steering:"sending to this session…",retained_unsent:"saved; not sent.",uncertain:"delivery unconfirmed. Check status.",cancelled:"not sent; withdrawn.",rejected:"not accepted by this execution."}[route.phase]||"route retained; inspect its current state.");
    }
    function clearFocus() {replyFocus=undefined;focusVersion++;$("#conversation-focus").hidden=true;}
    function selectFocus(reference,label) {
      replyFocus={reference:JSON.parse(JSON.stringify(reference)),label};focusVersion++;
      $("#conversation-focus-label").textContent=`Reply to ${label}`;$("#conversation-focus").hidden=false;
      draft.focus?.();compose.scrollIntoView?.({block:"nearest"});
    }
    const workspace=standalone&&!readOnly?window.SessionWorkspace?.mount({timeline,api,portableDeliveryText,hosted:!!hostSurface,toolbarHost:$("#conversation-compose-bar"),noticeHost:$("#conversation-compose-notices .composer-notice-panel"),daimonName:$("#conversation-daimon")?.textContent,
      onTarget:()=>{clearFocus();syncTitleControls();syncWorkspaceAudio();syncRuntimeSummary();},
      focusComposer:()=>draft.focus?.({preventScroll:true}),onReply:selectFocus,
      audio:row=>{const key=workspaceAudioKey(row);return {muted:mutedSessions.has(key),solo:soloSessions.has(key),filtered:mutedSessions.size>0||soloSessions.size>0};},
      onAudio:(action,row)=>{
        const key=row&&workspaceAudioKey(row);
        if(action==="reset"){mutedSessions.clear();soloSessions.clear();}
        else if(key&&action==="mute"){if(mutedSessions.has(key))mutedSessions.delete(key);else if(mutedSessions.size<256)mutedSessions.add(key);}
        else if(key&&action==="solo"){if(soloSessions.has(key))soloSessions.delete(key);else if(soloSessions.size<256)soloSessions.add(key);mutedSessions.clear();}
        audioFilterChanged();
      },onReady:()=>{syncTitleControls();syncWorkspaceAudio();syncRuntimeSummary();}
    }):undefined;
    function inputReference(){
      if(replyFocus)return replyFocus.reference;
      const selection=workspace?.capture();
      return selection?selection.reference:hostSurface?undefined:voiceContext;
    }
    function syncWorkspaceAudio(){
      const row=workspace?.audioScope?.();
      const next=row?(workspaceAudioKey(row)??null):undefined;
      if(next===workspaceAudioScope)return;
      workspaceAudioScope=next;
      audioFilterChanged({persist:false,scopeChanged:true});
    }
    function workspaceAudioKey(row){
      if(row.is_entry)return "conversation";
      const pair=row.audio_key?.split(":").map(Number);
      return pair?.length===2&&pair.every(Number.isSafeInteger)?JSON.stringify(pair):undefined;
    }
    $("#conversation-focus-clear").addEventListener("click",clearFocus);
    async function routeInput(card,frozen) {
      if(readOnly || card.routeBusy || inputs.get(card.value.id)!==card)return;
      card.routePending=frozen;card.routeBusy=true;renderRoute(card);
      const owned=inputGeneration,observation=++inputObservation;
      try {
        const result=await api(`interaction/inputs/${card.value.id}/route`,frozen);
        if(owned===inputGeneration && inputs.get(card.value.id)===card)inputCard(result,observation);
      } catch(e) {
        if(owned!==inputGeneration)return;
        card.routeNote.textContent="Selection unconfirmed. Check message status before choosing again.";
        if(e.status===401 || e.status===403)failed(e);
      } finally {if(owned===inputGeneration){card.routeBusy=false;renderRoute(card);}}
    }
    function renderRoute(card) {
      const selected=card.select.value||"";
      if(card.choiceVersion!==JSON.stringify(routingChoices)){
        const placeholder=node("option","Choose a session");placeholder.value="";placeholder.disabled=true;placeholder.selected=true;
        card.select.replaceChildren(placeholder);
        for(const choice of routingChoices){const option=node("option",`#${choice.label}`);option.value=choice.selector;card.select.append(option);}
        card.select.value=routingChoices.some(c=>c.selector===selected)?selected:"";card.choiceVersion=JSON.stringify(routingChoices);
      }
      if(card.value.routing){card.routePending=undefined;card.routeNote.textContent="";}
      card.routeBox.hidden=readOnly || card.value.read_only || card.value.phase!=="awaiting_target";
      card.select.disabled=!!card.routePending || card.routeBusy || card.value.retired;
      card.routeButton.textContent=card.routePending?"Retry this selection":"Send to session";
      card.routeButton.disabled=card.routeBusy || card.value.retired || (!card.routePending && !card.select.value);
      card.continueButton.hidden=!!hostSurface || readOnly || card.value.read_only || !card.value.continuation;
    }
    function savedRecovery(card) {
      if(card.value.retired)return null;
      return (card.value.recoveries||[]).find(r=>r.instruction &&
        !(card.value.routing?.instruction===r.instruction && card.value.routing.phase==="accepted"));
    }
    function renderRetry(card) {
      const recovery=savedRecovery(card);
      card.retry.hidden=readOnly || card.value.read_only===true || card.value.target==="claude" || !card.value.binding || (!recovery && !!card.value.phase);
      card.retry.textContent=recovery?`Try again with #${recovery.label}`:"Retry this same message";
      card.retry.disabled=!!card.retryBusy || !!card.retryNeedsCheck;
      if(card.retryNeedsCheck)card.check.hidden=false;
    }
    const composerCheck=$("#conversation-send-check");
    function syncComposerRecovery(){
      if(!composerCheck)return;
      const card=inputs.get(latestComposerId),value=card?.value;
      const checkable=value&&!savedWaiting(value)&&(!value.phase||['uncertain','claude_unconfirmed','preparation_unconfirmed','retained_unsent'].includes(value.phase)||value.routing?.phase==='uncertain');
      composerCheck.hidden=readOnly||posting||!checkable||value.binding!==binding;
      composerCheck.disabled=!!card?.checking;
      composerDismiss.hidden=readOnly||(!noticeAttention&&composerCheck.hidden);
    }
    composerDismiss.addEventListener('click',()=>{
      sendFeedback.hidden=true;
      send.focus?.({preventScroll:true});
    });
    composerCheck?.addEventListener('click',async()=>{
      const card=inputs.get(latestComposerId);
      if(!card||posting||card.value.binding!==binding||card.checking)return;
      await card.checkStatus();
    });
    function inputActivity() {
      syncComposerRecovery();
      presentState({transcribing:[...inputs.values()].some(c=>c.value.voice && c.value.phase==="preparing"),
        routing:[...inputs.values()].some(c=>["requested","queued","submitting","steering"].includes(c.value.routing?.phase))});
    }
    function resetInputs() {
      canDecideRequests=false;
      liveUsage?.reset();
      voiceMode?.close();showResponseDraft();
      companion?.reset();goalControls?.reset();presentationProfile=undefined;replyAnchors.clear();
      disableVoice();timeline?.replaceChildren();
      codexVoiceSession?.resetHistory?.();
      publicLiveSession?.resetHistory?.();
      foregroundCards.clear();
      inputGeneration++; inputs.clear(); inputNewest = 0; inputBinding = inputEntryBinding = undefined;
      latestComposerId = undefined;syncComposerRecovery(); composerNotice("",false);clearFocus();routingChoices=[];
      telegramNewest=0;telegramLoaded=false;
      $("#conversation-inputs").replaceChildren();
      $("#conversation-telegram-state").textContent="";
      sharedText?.reset();draft.disabled = true; send.disabled = true;
    }
    async function readTrace(card) {
      if (card.traceBusy) return;
      const owned=inputGeneration;
      card.traceBusy=true;card.traceRefresh.disabled=true;
      card.traceState.textContent="Reading saved routing evidence…";
      try {
        const value=await api(`interaction/inputs/${encodeURIComponent(card.value.id)}/trace`);
        if(owned!==inputGeneration || inputs.get(card.value.id)!==card)return;
        if(value.id!==card.value.id || value.schema!=="telecodex.conversation-trace/v1")throw new Error("Wrong routing observation");
        const original=node("section");
        original.append(node("h3",value.voice?"Voice transcript":"Original text"),node("p",value.text||"No transcript is confirmed yet.","reply-text"));
        traceTextMore(card,original,original.children[1],"original",value.text_next_offset);
        const stages=[original];
        for(const route of value.routes) {
          const step=node("section",undefined,"route-step");
          const relation=({new:"New task",amends:"Correction",context:"Additional context"})[route.relation?.kind]||"Related input";
          step.append(node("h3",`→ #${route.label} · ${relation}`),node("p",routeText({...route,phase:route.transport_phase}),"reply-status"));
          step.append(node("p","Exact original forwarded to this session:","note"),node("p",route.forwarded_original,"reply-text"));
          traceTextMore(card,step,step.children[3],route.instruction,route.forwarded_next_offset);
          if(!route.target_available)step.append(node("p","This session is no longer available in your current scope. Its response is not exposed.","note"));
          for(const result of route.results) {
            const state=!result.current?"Earlier result; a later correction may apply.":result.correction_pending?"A correction is still pending.":result.instruction_covered&&result.completed?"Session declared this input incorporated and the request completed.":"The session has not declared this input fully incorporated and completed.";
            step.append(node("p",state,"reply-status"),node("p",result.text_excerpt,"reply-text"));
            if(result.text_bounded)step.append(node("p","Response excerpt; read the complete reply under From your sessions.","note"));
          }
          if(route.more_results)step.append(node("p","Earlier related results remain in reply history.","note"));
          const identity=node("details"),summary=node("summary","Request references");
          identity.append(summary,node("p",`Instruction: ${route.instruction}\nRequests: ${route.requests.join(", ")}`,"route-identity"));step.append(identity);stages.push(step);
        }
        if(!value.routes.length)stages.push(node("p",value.answer?"Recorded as an answer to a session question; recording an answer does not prove incorporation.":value.routing?routeText(value.routing):"No work-session dispatch is recorded. The input may remain with the integrator or await clarification.","note"));
        stages.push(node("p",value.evidence,"note"));
        card.traceContent.replaceChildren(...stages);
        card.traceState.textContent=`Saved input: ${value.phase}. Observation only; no message was resent.`;
      } catch(e) {
        if(owned!==inputGeneration || inputs.get(card.value.id)!==card)return;
        card.traceState.textContent="Routing observation unavailable. Previous evidence is retained; nothing was resent.";
        if([401,403].includes(e.status))failed(e);
      } finally {card.traceBusy=false;card.traceRefresh.disabled=false;}
    }
    function traceTextMore(card,section,text,source,nextOffset) {
      const cached=card.traceText.get(source);
      if(cached && cached.text.startsWith(text.textContent)) {
        text.textContent=cached.text;nextOffset=cached.nextOffset;
      } else card.traceText.set(source,{text:text.textContent,nextOffset});
      if(nextOffset===null || nextOffset===undefined)return;
      const more=node("button","Read more saved text");more.type="button";section.append(more);
      more.addEventListener("click",async()=>{
        const owned=inputGeneration,offset=nextOffset;more.disabled=true;
        try {
          const value=await api(`interaction/inputs/${encodeURIComponent(card.value.id)}/trace/${encodeURIComponent(source)}?offset=${offset}`);
          if(owned!==inputGeneration || inputs.get(card.value.id)!==card)return;
          if(value.id!==card.value.id || value.source!==source || value.offset!==offset)throw new Error("Wrong saved text");
          text.textContent+=value.text;nextOffset=value.next_offset;
          card.traceText.set(source,{text:text.textContent,nextOffset});
          more.hidden=nextOffset===null;more.textContent="Read more saved text";
        }catch(e){more.textContent="Read unavailable; try again";if([401,403].includes(e.status))failed(e);}
        finally{more.disabled=false;}
      });
    }
    const avatarVoiceAdmissions = new Map();
    function updateAvatarAdmission(value, track = false) {
      if (voiceChoice !== 'conversation' || !voiceMode?.active || value.binding !== undefined && value.binding !== binding
          || (!track && !avatarVoiceAdmissions.has(value.id))) return;
      const phase = value.routing?.phase || value.phase;
      if (value.retired || ['accepted','answered','cancelled','rejected'].includes(phase))
        avatarVoiceAdmissions.delete(value.id);
      else {
        const waiting = ['retained','queued','preparing','sending','steering','submitting'].includes(phase);
        avatarVoiceAdmissions.set(value.id, waiting ? 'waiting' : 'review');
        if(avatarVoiceAdmissions.size > 128)avatarVoiceAdmissions.delete(avatarVoiceAdmissions.keys().next().value);
      }
      const outcomes = [...avatarVoiceAdmissions.values()];
      voiceMode.update({admissionNotice:outcomes.includes('review') ? 'Check your recording in Conversation.'
        :outcomes.includes('waiting') ? 'Recording saved. Waiting for Conversation.' : ''});
    }
    function draftReceipt(value, scopedBinding){
      // Direct native receipts identify their entry as a tuple. History rows
      // inherit the verified page binding only for the current native entry.
      const entry=value.entry_binding;
      const sameEntry=Array.isArray(entry)&&entry.length===4&&inputEntryBinding&&entry[1]&&inputEntryBinding[1]
        && entry[0]===inputEntryBinding[0] && entry[1].chat_id===inputEntryBinding[1].chat_id
        && entry[1].thread_id===inputEntryBinding[1].thread_id && entry[2]===inputEntryBinding[2] && entry[3]===inputEntryBinding[3];
      return value.binding===undefined&&(scopedBinding||sameEntry)?{...value,binding:scopedBinding||inputBinding}:value;
    }
    function inputCard(value, observed = ++inputObservation, scopedBinding) {
      if(draftState&&value.phase)draftState.confirm(draftReceipt(value,scopedBinding));
      timing?.input(value);
      const followingLive=atTimelineEnd();
      let card = inputs.get(value.id);
      if (!card) {
        const box = node("article", undefined, "reply");
        const text = node("div", "", "reply-text"), status = node("p", "", "reply-status");
        const check = node("button", "Check status / read message"); check.type = "button";
        const retry = node("button", "Retry this same message"); retry.type = "button"; retry.hidden = true;
        const actions = node("div", undefined, "reply-actions"); actions.append(check,retry);const copy=copyButton(async()=>{
          const selected=card.value,owned=inputGeneration;
          const valid=()=>inputGeneration===owned && inputs.get(selected.id)===card;
          if(!valid())throw Error("Message changed. Try again.");
          if(typeof selected.text==="string")return selected.text;
          return copyParts(async offset=>{
            const value=await api(`interaction/inputs/${encodeURIComponent(selected.id)}/trace/original?offset=${offset}`);
            if(value.id!==selected.id || value.source!=="original")throw Error("Wrong saved message");
            return value;
          },valid);
        });
        const continueButton=node("button","Reply to this session");continueButton.type="button";continueButton.hidden=true;actions.append(continueButton,copy);
        const routeBox=node("div",undefined,"reply-route"),select=node("select"),routeButton=node("button","Send to session"),routeNote=node("p","","reply-error");
        select.setAttribute("aria-label","Destination session");routeButton.type="button";routeBox.hidden=true;routeBox.append(select,routeButton,routeNote);
        const imageButton=node("button","Show selected image"),imageView=node("div");imageButton.type="button";imageButton.hidden=true;imageView.hidden=true;imageView.className="input-visual";imageView.setAttribute("role","img");
        imageButton.addEventListener("click",async()=>{
          const references=Array.isArray(card.value.visual)?card.value.visual:[card.value.visual];
          const showLabel=references.length>1?`Show images (${references.length})`:"Show selected image";
          if(!imageView.hidden){imageView.hidden=true;imageView.replaceChildren();imageButton.textContent=showLabel;return;}
          const owned=inputGeneration,controller=new AbortController(),deadline=setTimeout(()=>controller.abort(),20000);imageButton.disabled=true;imageButton.textContent="Loading images…";
          try{
            const views=[];
            for(const [index,ref] of references.entries()){
              const response=await fetch(`api/interaction/inputs/${encodeURIComponent(card.value.id)}/image?index=${index}`,{headers:headers(),credentials:"same-origin",signal:controller.signal});
              if(!response.ok)throw Object.assign(Error("Image unavailable"),{status:response.status});
              const bitmap=await createImageBitmap(await response.blob());
              if(owned!==inputGeneration){bitmap.close();return;}
              const view=node("canvas");view.className="input-visual";view.width=bitmap.width;view.height=bitmap.height;const context=view.getContext("2d");context.drawImage(bitmap,0,0);bitmap.close();
              if(ref.point){context.strokeStyle="#fff";context.lineWidth=Math.max(3,ref.width/200);context.beginPath();context.arc(ref.point.x,ref.point.y,Math.max(6,ref.width/80),0,2*Math.PI);context.stroke();}
              view.setAttribute("role","img");view.setAttribute("aria-label",`Captured image ${index+1} of ${references.length}.`+(ref.point?` Selected point X ${ref.point.x}, Y ${ref.point.y}.`:" Whole image; no point selected."));views.push(view);
            }
            imageView.replaceChildren(...views);imageView.hidden=false;imageButton.textContent=references.length>1?"Hide images":"Hide selected image";
          }catch(e){status.textContent="Selected image unavailable. The message was not resent.";if([401,403].includes(e.status))failed(e);}
          finally{clearTimeout(deadline);imageButton.disabled=false;if(imageView.hidden)imageButton.textContent=showLabel;}
        });
        const trace=node("details",undefined,"routing-trace"),traceSummary=node("summary","Show routing path"),traceState=node("p","","note"),traceContent=node("div"),traceRefresh=node("button","Refresh route");
        traceRefresh.type="button";traceState.setAttribute("role","status");trace.append(traceSummary,traceState,traceContent,traceRefresh);
        if(timeline){box.classList.add?.("human-message");box.append(node("h3","You"));}
        box.dataset.inputId=value.id;
        const time=node("time",undefined,"message-time");
        box.append(text,status,actions,routeBox,imageButton,imageView,...(timeline?[]:[trace]),time);
        card = {box,text,time,actions,imageButton,imageView,status,check,retry,value,observed,continueButton,routeBox,select,routeButton,routeNote,trace,traceSummary,traceState,traceContent,traceRefresh,traceText:new Map()};
        trace.addEventListener("toggle",()=>trace.open&&readTrace(card));
        traceRefresh.addEventListener("click",()=>readTrace(card));
        continueButton.addEventListener("click",()=>card.value.continuation&&selectFocus(card.value.continuation,`#${card.value.routing?.label||"session"}`));
        select.addEventListener("change",()=>renderRoute(card));
        routeButton.addEventListener("click",()=>routeInput(card,card.routePending||{binding,selector:select.value})); inputs.set(value.id, card);
        card.checkStatus = async () => {
          if(card.checking)return;
          card.checking=true;syncComposerRecovery();
          const owned = inputGeneration, observation = ++inputObservation;
          check.disabled = true;
          try {
            const result = await api(`interaction/inputs/${encodeURIComponent(value.id)}`);
            if (owned !== inputGeneration || inputs.get(value.id) !== card) return;
            inputCard(result, observation);
            if(savedWaiting(card.value))status.textContent="Still in queue · waiting for a turn";
          } catch (e) {
            if (owned !== inputGeneration) return;
            if (observation >= card.observed) status.textContent = phaseText(card.value) + " Status check unavailable.";
            if (e.status === 401 || e.status === 403) failed(e);
          } finally { card.checking=false;check.disabled = false;syncComposerRecovery(); }
        };
        check.addEventListener("click",()=>inputNeedsText(card)?readInputText(card):card.checkStatus());
        retry.addEventListener("click", async () => {
          const recovery=savedRecovery(card);
          if (readOnly || (card.value.phase && !recovery) || retry.disabled) return;
          const owned = inputGeneration, observation = ++inputObservation;
          card.retryBusy=true;retry.disabled = true;
          try {
            const result = recovery ? await api(`interaction/inputs/${card.value.id}/retry`,{binding:card.value.binding,instruction:recovery.instruction}) : await api("interaction/inputs", {id:card.value.id,binding:card.value.binding,text:card.value.text,...(card.value.reply?{reply:card.value.reply}:{}),...(card.value.visual?{visual:card.value.visual}:{}),...(card.value.files?.length?{files:card.value.files}:{}),...(card.value.playback?{playback:card.value.playback}:{})});
            if (owned === inputGeneration) inputCard(result, observation);
          } catch(e) {
            if (owned !== inputGeneration) return;
            if (recovery)card.retryNeedsCheck=true;
            if (observation >= card.observed) status.textContent = phaseText(card.value) + (recovery?" Recovery unconfirmed. Check saved status before trying again.":" The same message identity was used.");
            if (e.status === 401 || e.status === 403) failed(e);
          } finally {card.retryBusy=false;renderRetry(card);}
        });
      }
      if (observed < card.observed) {
        // A request that started earlier can nevertheless observe a later commit.
        if (["accepted","answered","matrix_requested","retained_unsent"].includes(value.phase) &&
            (!["answered","matrix_requested"].includes(card.value.phase) || value.phase===card.value.phase)) {
          if (!draftState && !card.value.phase && draft.value === card.value.text) draft.value = "";
          card.value.phase = value.phase;
          // Adopt only a first committed voice body for this exact recording;
          // a late read cannot replace already observed text or another capture.
          if(card.value.voice&&!card.value.text&&!card.value.preview&&value.voice?.transcription?.capture_id===value.id&&value.voice.audio_sha256===card.value.voice.audio_sha256){
            if(typeof value.text==="string"&&value.text)card.value.text=value.text;
            else if(typeof value.preview==="string"&&value.preview)card.value.preview=value.preview;
            card.value.voice={...card.value.voice,...value.voice};
          }
        }
        if (claudeReplied(value.phase) && typeof value.claude_reply?.text === "string" &&
            !claudeReplied(card.value.phase)) {
          card.value.phase = value.phase;
          card.value.claude_reply = value.claude_reply;
        } else if (claudeFailure(value.phase) && !claudeReplied(card.value.phase)) {
          card.value.phase = value.phase;
        }
        if(value.routing && (!card.value.routing || (value.routing.phase==="accepted" && card.value.routing.instruction===value.routing.instruction))){
          card.value.routing=value.routing;card.value.phase=value.phase;
          if(value.continuation)card.value.continuation=value.continuation;
        }
        card.value.retired = !!card.value.retired || !!value.retired;
        if(card.value.phase && card.value.focusVersion===focusVersion)clearFocus();
        // A later-completing status read can carry the first committed transcript,
        // even when a newer-started history request sampled the pending state.
        renderInputText(card);
        card.status.textContent = phaseText(card.value);
        microphone?.observe(card.value,phaseText(card.value));
        updateAvatarAdmission(card.value);
        taskControls?.observeInput?.(card.value);
        renderRetry(card);
        if (card.value.id === latestComposerId) inputNotice(card.value);
        renderRoute(card);inputActivity();return card;
      }
      // Native acceptance and retirement cannot be undone by a late snapshot.
      if (["answered","matrix_requested","retained_unsent"].includes(card.value.phase) || claudeReplied(card.value.phase) ||
          (card.value.phase==="accepted" && !["answered","matrix_requested"].includes(value.phase))) value = {...value,phase:card.value.phase};
      if (claudeFailure(card.value.phase) && ["retained","sending","matrix_received","claude_preparing","claude_running"].includes(value.phase)) {
        value = {...value,phase:card.value.phase};
      }
      if(card.value.routing) {
        // Destination selection is immutable, even if a later-started request
        // sampled an earlier database state before the route committed.
        if(!value.routing || value.routing.instruction!==card.value.routing.instruction || value.routing.target?.thread_id!==card.value.routing.target?.thread_id)
          value={...value,routing:card.value.routing,phase:card.value.phase,continuation:card.value.continuation};
        else if(card.value.routing.phase==="accepted")value={...value,routing:{...value.routing,phase:"accepted"}};
      }
      value = {...value,retired:!!value.retired || !!card.value.retired};
      card.observed = observed;
      card.retryNeedsCheck=false;
      if (!draftState && !card.value.phase && value.phase && draft.value === card.value.text) draft.value = "";
      // Preserve full original text after reading it, and an unknown POST's text.
      if(typeof value.preview==="string" && value.preview!==card.value.preview){
        card.originalText=undefined;card.originalOffset=undefined;card.autoRevision=undefined;
      }
      if(card.value.portable_phase==="accepted")value={...value,portable_phase:"accepted"};
      card.value = {...card.value, ...value};
      messageTime(card.time,card.value.received_at);
      if(card.fileList)card.fileList.remove();
      if(card.value.files?.length){card.fileList=node('div');card.fileList.className='input-files';card.value.files.forEach((file,index)=>{const button=node('button',file.name);button.type='button';button.disabled=!attachedFiles;button.addEventListener('click',async()=>{button.disabled=true;try{await attachedFiles.download(file,card.value.id,index);button.textContent=file.name;}catch(error){button.textContent=error.message||'Original file unavailable';}finally{button.disabled=!attachedFiles;}});card.fileList.append(button);});card.imageButton.parentNode.append(card.fileList);}
      card.imageButton.hidden=!card.value.visual;
      if(card.imageView.hidden)card.imageButton.textContent=Array.isArray(card.value.visual)?`Show images (${card.value.visual.length})`:"Show selected image";
      renderInputText(card);
      card.status.textContent = phaseText(card.value);
      microphone?.observe(card.value,phaseText(card.value));
      updateAvatarAdmission(card.value);
      if(card.value.phase && card.value.focusVersion===focusVersion)clearFocus();
      if (card.value.id === latestComposerId) inputNotice(card.value);
      renderRetry(card);
      renderRoute(card);
      card.box.dataset.sequence = String(card.value.capture_order ?? (card.value.ordering_unknown?Number.MIN_SAFE_INTEGER:card.value.sequence ?? Number.MAX_SAFE_INTEGER));
      const container = $("#conversation-inputs");
      const following = [...container.children].find(item => item !== card.box
        && Number(item.dataset.sequence) < Number(card.box.dataset.sequence));
      const replySource=card.value.reply?.source||"",replyRevision=card.value.reply?.revision||"";
      const replyChanged=card.box.dataset.replySource!==replySource||card.box.dataset.replyRevision!==replyRevision;
      card.box.dataset.replySource=replySource;card.box.dataset.replyRevision=replyRevision;
      if(timeline){
        const original=cards.get(card.value.reply?.source)?.source;
        card.box.children[0].textContent=card.value.reply?`You · reply to ${original?.kind?.startsWith("integrator_")?"Conversation":original?.label||"earlier message"}`:"You";
      }
      if(timeline){
        card.traceSummary.textContent=`Routing path · ${(card.value.text||card.value.preview||"Saved voice input").slice(0,80)}`;
        card.trace.dataset.sequence=card.box.dataset.sequence;
        const next=[...container.children].find(item=>item!==card.trace&&Number(item.dataset.sequence)<Number(card.trace.dataset.sequence));
        container.insertBefore(card.trace,next||null);
      }
      if(timeline){
        const received=card.value.received_at || (card.value.origin_kind==="telegram"?"1970-01-01T00:00:00Z":undefined);
        if(card.box.parentNode!==timeline || card.timelineReceived!==received || replyChanged){
          card.timelineReceived=received;
          placeInTimeline(card.box,`input:${card.value.id}`,received,followingLive);
        }else if(followingLive)timeline.scrollTop=timeline.scrollHeight;
      }else container.insertBefore(card.box, following || null);
      placeClaudeReply(card);
      card.box.dataset.inputId=card.value.id;textObserver?.observe(card.box);queueText(card);

      inputActivity();
      return card;
    }
    async function inputPage(before = 0, direction = "before", remember = true) {
      const owned = inputGeneration, observation = ++inputObservation;
      const result = await api(`interaction/inputs?before=${before}&direction=${direction}${draftState&&before===0&&direction==='before'?'&draft=text':''}`);
      if (owned !== inputGeneration) return;
      if (result.binding !== binding) throw new Error("Conversation changed. Refresh before sending.");
      if (inputBinding && inputBinding !== result.binding) {resetInputs(); requestControls.reset(); internalControls?.reset(); taskControls?.reset(); microphone?.reset(); visual?.reset();attachedFiles?.reset();}
      inputBinding = result.binding;
      inputEntryBinding = Array.isArray(result.entry_binding)&&result.entry_binding.length===4?result.entry_binding:undefined;
      setCsrf(result.csrf);routingChoices=result.routing_choices||[];
      if(draftState && result.conversation_draft)draftState.bind(result.conversation_draft.owner,binding,hostedTopic);
      for (const value of result.items) inputCard(value, observation,value.native_binding_current===true?inputBinding:undefined);
      draftState?.observe(result.conversation_draft);
      if (direction === "after" || (remember && !inputNewest)) inputNewest = Math.max(inputNewest, result.newest || 0);
      draft.disabled = readOnly; send.disabled = readOnly || posting;sharedText?.refresh();microphone?.syncControls?.();
      return result;
    }
    async function telegramPage(before=0,direction="before") {
      const owned=inputGeneration,observation=++inputObservation;
      const result=await api(`interaction/telegram-inputs?before=${before}&direction=${direction}`);
      if(owned!==inputGeneration)return;
      if(result.binding!==binding || result.schema!=="telecodex.telegram-input-list/v1")throw new Error("Telegram observation binding changed");
      for(const value of result.items)inputCard(value,observation);
      if(direction==="after" || !telegramLoaded)telegramNewest=Math.max(telegramNewest,result.newest||0);
      telegramLoaded=true;
      return result;
    }
    async function refreshTelegram() {
      if(telegramReading || !enabled || !ready || (!standalone && !$("#conversation-sent").open))return;
      const owned=inputGeneration;telegramReading=true;
      try {
        if(!telegramLoaded)await telegramPage();
        else {
          let more=true;
          for(let n=0;n<4 && more;n++){const page=await telegramPage(telegramNewest,"after");more=!!page?.more;if(n===3 && more)refreshAgain=true;}
          if(owned===inputGeneration)await telegramPage();
        }
        if(owned===inputGeneration)$("#conversation-telegram-state").textContent="Telegram and app/device inputs share the retained capture order. Historical inputs without that order are labelled separately.";
      }catch(e){if(owned===inputGeneration)$("#conversation-telegram-state").textContent="Telegram observation unavailable. Saved app/device inputs remain visible; nothing was resent.";if(e.status===401)failed(e);}
      finally{telegramReading=false;}
    }
    $("#conversation-sent").addEventListener("toggle",()=>refreshTelegram());
    draft.addEventListener("keydown", event => {
      if(event.key!=="Enter" || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey
        || event.isComposing || event.keyCode===229)return;
      event.preventDefault();
      if(!event.repeat && !send.disabled && !readOnly){
        if(typeof compose.requestSubmit==="function")compose.requestSubmit();else send.click();
      }
    });
    function finishTextPost(){
      submittedText=undefined;posting=false;draftState?.observe();
      send.disabled=!inputBinding;microphone?.syncControls?.();syncComposerRecovery();
    }
    compose.addEventListener("submit", async event => {
      event.preventDefault();
      if(microphone?.ownsSend?.())return microphone.submit();
      if (readOnly || posting || !ready || !binding || inputBinding !== binding) return;
      const text = draft.value;
      if(draftState?.hasUnconfirmed(text)){composerNotice('Check message status before sending another message.');return;}
      if (!text.trim() && !attachedFiles?.hasFiles() || text.includes("\0") || new TextEncoder().encode(text).length > 32768) {
        composerNotice("Write a message of at most 32 KiB."); return;
      }
      if ([...inputs.values()].some(card => !card.value.phase && card.value.text === text)) {
        composerNotice("This message has an unconfirmed submission. Use Check status before sending it again.");
        $("#conversation-sent").open = true; return;
      }
      if(!replyFocus && workspace && !workspace.canSend()){
        composerNotice("Select your session again or return the input to the conversation before sending.");return;
      }
      // Freeze the destination before file/image preparation can yield to a
      // later pin or expansion. Original retries keep this same selection.
      const id=crypto.randomUUID(),owned=inputGeneration,observation=++inputObservation,focusAtSubmit=focusVersion,selectedBinding=binding;
      const context=inputReference();
      const reply=context&&JSON.parse(JSON.stringify(context)),playback=playbackContext();
      let selectedVisual,selectedFiles;
      submittedText=text;posting=true;send.disabled=true;
      let contextPreparation;
      try {
        // Dispatch the host snapshot before any visual/file operation can yield.
        if(hostSurface){contextPreparation=hostSurface.prepare({id,binding:selectedBinding,modality:'text',files:[]});contextPreparation.catch(()=>{});}
        if(visual)selectedVisual=await visual.capture();if(attachedFiles)selectedFiles=await attachedFiles.capture();
        if(contextPreparation)selectedFiles=[...(selectedFiles||[]),...await contextPreparation];
        if((selectedFiles?.length||0)>8||(selectedFiles||[]).reduce((n,f)=>n+f.size,0)>40*1024*1024)throw Error('Attachments and world context exceed eight files or 40 MiB. Your draft is kept.');
      }
      catch(e){hostSurface?.discard?.({id,binding:selectedBinding,reason:'preparation-failed'});finishTextPost();composerNotice(e.message||"Select your image again.");return;}
      if(owned!==inputGeneration || selectedBinding!==binding){hostSurface?.discard?.({id,binding:selectedBinding,reason:'preparation-failed'});finishTextPost();return;}
      posting = true; send.disabled = true; latestComposerId = id;
      inputCard({id,text,binding,reply,playback,visual:selectedVisual,files:selectedFiles,focusVersion:focusAtSubmit}, observation); if(timeline)timeline.scrollTop=timeline.scrollHeight; $("#conversation-sent").open = true;
      composerNotice("Sending…",false);
      try {
        hostSurface?.attempt?.({id,binding:selectedBinding});
        const original={binding:selectedBinding,id,text,...(reply?{reply}:{}),...(selectedVisual?{visual:selectedVisual}:{}),...(selectedFiles?.length?{files:selectedFiles}:{}),...(playback?{playback}:{})};
        draftState?.attempt(original);
        workspace?.previewSubmission?.(reply,id,text);
        const result=await api("interaction/inputs",original);
        if (owned !== inputGeneration) return;
        if(result.id!==id || result.binding!==undefined&&result.binding!==selectedBinding || !result.phase)throw Error('Wrong message receipt');
        hostSurface?.status(result);retainedCorrection(result);
        const confirmed = inputCard(result, observation,selectedBinding);
        if(result.phase==="accepted"||result.phase==="routed"){
          workspace?.settlePreview?.(id,result.routing?.phase==="queued"?"Saved. Waiting for this session.":"Message saved.");
          workspace?.observeSubmission?.(reply);
        }else workspace?.settlePreview?.(id,phaseText(confirmed.value));
        visual?.consumed(selectedVisual);attachedFiles?.consumed(selectedFiles);
        if(focusAtSubmit===focusVersion)clearFocus();
        if (draft.value === text) draft.value = "";
        inputNotice(confirmed.value);
      } catch (e) {
        if (owned !== inputGeneration) return;
        if(e.visualReselection){workspace?.settlePreview?.(id,"discarded");draftState?.unsent(id);inputCard({id,phase:"reselection"},observation);composerNotice("Select the image again, then send. This attempt did not submit the message.");return;}
        const retained = inputs.get(id)?.value;
        workspace?.settlePreview?.(id,retained?.phase?phaseText(retained):"Submission unconfirmed.");
        if (id === latestComposerId) {
          if(retained?.phase)inputNotice(retained);
          else composerNotice("Submission unconfirmed. Check this message status; it will not be resent automatically.");
        }
        if (e.status === 401 || e.status === 403) failed(e);
      } finally { finishTextPost(); }
    });
    const audioElement = $("#conversation-audio");
    const mountedAudio = standalone && window.NativeSpeechAudio?.mount(audioElement) || audioElement;
    const audio = window.PcmSpeech?.mount(mountedAudio)||mountedAudio;
    audio.controls = false;
    audio.hidden = true;
    const replyActivity=window.WebRtcNativeAudio?.watchElement?.(audio,{
      isPlaying:()=>!!active&&!active.verifying&&!active.segmentEnded&&enabled&&!captureBusy&&!voiceSuspended&&playbackAllowed(),
      onActivity:rms=>{const measured=Math.min(1,Math.max(0,Number.isFinite(rms)?rms:0)*6),level=Math.round(measured*4)/4;presentState({outputLevel:level,outputSignalLevel:measured});}
    });
    const toggle = node("button", "Play audio");
    toggle.type = "button";
    toggle.id = "conversation-play";
    audio.before(toggle);
    const playLabel = text => {
      toggle.textContent = text; toggle.title = text;
      toggle.setAttribute("aria-label", text);
      toggle.dataset.playbackState = text.startsWith("Pause") ? "pause" : "play";
    };
    playLabel("Play audio");
    const follow = $("#conversation-follow");
    let followEnabled=true,followHintHeldUntil=0;
    const showFollow=()=>follow.setAttribute("aria-pressed",String(followEnabled));
    const followPointers=new Set();let followTouch=false,followSettle;
    const followHeld=()=>followPointers.size>0 || followTouch || !!followSettle;
    const resumeFollow=()=>{if(!followHeld())followPlayback(true);};
    const saveFollow=()=>{try{window.localStorage?.setItem("interaction-follow-audio",String(followEnabled));}catch{}};
    if(standalone && follow){
      $("#conversation-follow-control").hidden=false;
      try{followEnabled=window.localStorage?.getItem("interaction-follow-audio")!=="false";}catch{}
      showFollow();
      follow.addEventListener("click",()=>{if(Date.now()<followHintHeldUntil)return;followEnabled=!followEnabled;showFollow();saveFollow();if(followEnabled)followPlayback(true);});
      const settleFollow=()=>{clearTimeout(followSettle);followSettle=setTimeout(()=>{followSettle=undefined;resumeFollow();},180);};
      timeline.addEventListener("wheel",settleFollow,{passive:true});
      timeline.addEventListener("pointerdown",event=>{followPointers.add(event.pointerId);});
      const releasePointer=event=>{followPointers.delete(event.pointerId);resumeFollow();};
      window.addEventListener("pointerup",releasePointer);
      window.addEventListener("pointercancel",releasePointer);
      timeline.addEventListener("touchstart",()=>{followTouch=true;},{passive:true});
      const releaseTouch=event=>{followTouch=!!event.touches?.length;resumeFollow();};
      window.addEventListener("touchend",releaseTouch,{passive:true});
      window.addEventListener("touchcancel",releaseTouch,{passive:true});
      timeline.addEventListener("keydown",event=>{
        if(["ArrowUp","ArrowDown","PageUp","PageDown","Home","End"," "].includes(event.key)
          && !["INPUT","TEXTAREA","BUTTON","SELECT"].includes(event.target?.tagName))settleFollow();
      });
    }
    function followingSpeech(){
      return standalone && follow && followEnabled && !followHeld() && voiceEnabled && !voiceSuspended && !document.hidden
        && active?.auto && !active.verifying && !audio.paused && !audio.muted;
    }
    function followCard(){
      if(active?.source.kind==="integrator_live"){
        const source=active.source,key=`${source.native_turn}:${source.native_item}`;
        if(!responseDraft.hidden && responseDraft.dataset.nativeKey===key)return {box:responseDraft,body:responseDraftBody,expanded:true};
        return [...cards.values()].find(card=>card.source.native_turn===source.native_turn && card.source.native_item===source.native_item);
      }
      const original=cards.get(active?.source.id);
      if(original?.source.revision!==active?.source.revision)return;
      return timeline?.contains?.(original?.box)?original:[...progressCards.values()]
        .find(value=>value.source===active.source.id && value.revision===active.source.revision);
    }
    async function loadFollowText(selected){
      if(selected.source.kind==="integrator_live"){
        const card=followCard();if(!card?.source || card.textLoading || selected.followTextRequested)return;
        selected.followTextRequested=true;await readCard(card);if(active===selected)followPlayback();return;
      }
      const card=cards.get(selected.source.id);
      if(!card || card.textLoading || selected.followTextRequested)return;
      selected.followTextRequested=true;
      if(card.source.revision===selected.source.revision && card.offset===selected.offset)appendTextPart(card,selected.verified);
      // Reuse the canonical reader, keeping one bounded request chain per segment.
      for(let n=0;n<12 && active===selected && followingSpeech()
        && card.source.revision===selected.source.revision
        && (!card.expanded || Array.from(replyText(card.body)).length<selected.textEnd);n++){
        const before=replyText(card.body);
        await readCard(card);
        if(replyText(card.body)===before || card.offset===null)break;
      }
      if(active===selected && !followingSpeech())selected.followTextRequested=false;
      if(active===selected)followPlayback();
    }
    function followPlayback(force=false){
      if(!followingSpeech() || settings?.open || decisionDialog?.open)return;
      const card=followCard();
      if(!card || !timeline?.contains?.(card.box))return;
      const selected=active, viewport=timeline.getBoundingClientRect();
      const scroll=top=>timeline.scrollTo({top:Math.max(0,top),behavior:window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches?"instant":"smooth"});
      if(!selected.followed && selected.offset===0){
        scroll(timeline.scrollTop+card.box.getBoundingClientRect().top-viewport.top);
        selected.followed=true;
        return;
      }
      if(!Number.isSafeInteger(selected.textEnd))return;
      const original=cards.get(selected.source.id)||card;
      if(!original.expanded || Array.from(replyText(original.body)).length<selected.textEnd){
        void loadFollowText(selected);return;
      }
      if(!card.body.firstChild || !document.createRange)return;
      // Media progress guides a reading window, not a claimed word alignment.
      const timed=Number.isFinite(audio.duration) && audio.duration>0 && Number.isFinite(audio.currentTime);
      if(!timed && selected.followed && !force)return;
      const fraction=timed?Math.max(0,Math.min(1,audio.currentTime/audio.duration)):0;
      const characters=Array.from(replyText(card.body));
      const wordOffset=selected.streaming?.position?.(audio.currentTime);
      const aligned=Number.isSafeInteger(wordOffset) && wordOffset>=selected.offset && wordOffset<=selected.textEnd;
      const position=Math.min(characters.length-1,aligned?wordOffset:selected.offset+Math.floor(Math.max(0,selected.textEnd-selected.offset-1)*fraction));
      if(position<0)return;
      const start=characters.slice(0,position).join("").length;
      const range=window.ConversationMarkdown?window.ConversationMarkdown.range(card.body,position):(()=>{
        const result=document.createRange();result.setStart(card.body.firstChild,start);
        result.setEnd(card.body.firstChild,start+characters[position].length);return result;
      })();
      if(!range)return;
      const point=range.getBoundingClientRect();
      if(!point.height || !viewport.height)return;
      if(force || point.top<viewport.top || point.bottom>viewport.bottom-24)
        scroll(timeline.scrollTop+point.top-viewport.top-viewport.height*.25);
      selected.followed=true;
    }
    let enabled = false, ready = false, reading = false, binding, canListen = false, canStreamSpeech = false, canReportPlayback=false,canReportWordPosition=false,canLimitCaptureQuestions=false;
    let newest = {delivery:0, native:0, matrix:0,inbox:0,responses:0,publications:0};
    let initialized = false, active, generation = 0, requestAbort, blobUrl, prefetched;
    function playerStatus() {
      if(nativeEnabled&&nativeVoiceSession?.active){
        const playable=nativeVoiceSession.hasAudio;toggle.hidden=!playable;toggle.disabled=false;playLabel(nativeVoiceSession.paused?"Resume audio":"Pause audio");$("#conversation-audio-state").hidden=playable;$("#conversation-player").hidden=false;voiceStatus();return;
      }
      const playable=!!active && !!blobUrl && !active.segmentEnded && !audio.ended;
      toggle.hidden=!playable;
      $("#conversation-audio-state").hidden=playable;
      $("#conversation-player").hidden=false;
      voiceStatus();
    }
    const audioIndicator=$("#conversation-audio-state"),audioHint=$("#conversation-audio-hint");let audioHintTimer,audioHintHeldUntil=0;
    // Keep the explanation outside the dock's clipping/layout ancestors.
    document.body.append(audioHint);
    const closeAudioHint=()=>{clearTimeout(audioHintTimer);audioHint.hidden=true;audioIndicator.setAttribute("aria-expanded","false");follow?.setAttribute("aria-expanded","false");};
    const showAudioHint=(anchor=audioIndicator,text=audioIndicator.textContent)=>{
      closeAudioHint();audioHint.textContent=text;audioHint.hidden=false;anchor.setAttribute("aria-expanded","true");
      const rect=anchor.getBoundingClientRect?.(),viewport=window.visualViewport;
      if(rect){
        const x=viewport?.offsetLeft||0,y=viewport?.offsetTop||0,width=viewport?.width||window.innerWidth,height=viewport?.height||window.innerHeight;
        audioHint.style.maxWidth=Math.max(1,width-16)+"px";audioHint.style.maxHeight=Math.max(1,height-16)+"px";
        const size=audioHint.getBoundingClientRect();
        audioHint.style.left=Math.max(x+8,Math.min(rect.left,x+width-size.width-8))+"px";
        const above=rect.top-size.height-8,top=above>=y+8?above:rect.bottom+8;
        audioHint.style.top=Math.max(y+8,Math.min(top,y+height-size.height-8))+"px";
      }
      audioHintTimer=setTimeout(closeAudioHint,8000);
    };
    audioIndicator.addEventListener("click",()=>{if(Date.now()<audioHintHeldUntil)return;if(audioHint.hidden)showAudioHint();else closeAudioHint();});
    audioIndicator.addEventListener("contextmenu",event=>{event.preventDefault();audioHintHeldUntil=Date.now()+1000;showAudioHint();});
    const explainFollow=()=>showAudioHint(follow,"Follow: keep the spoken passage in view. Tap to turn following on or off.");
    follow?.addEventListener("contextmenu",event=>{event.preventDefault();followHintHeldUntil=Date.now()+1000;explainFollow();});
    follow?.addEventListener("keydown",event=>{if(event.key==="F1"){event.preventDefault();explainFollow();}});
    window.addEventListener("keydown",event=>{if(event.key==="Escape")closeAudioHint();});
    window.addEventListener("resize",closeAudioHint);window.visualViewport?.addEventListener("resize",closeAudioHint);window.visualViewport?.addEventListener("scroll",closeAudioHint);
    const audioState = (text) => {
      closeAudioHint();audioIndicator.textContent=text;audioIndicator.removeAttribute("title");audioIndicator.setAttribute("aria-label",text);
      audioIndicator.dataset.audioState=text==="Audio off"?"off":text.startsWith("Waiting")||text.startsWith("A short pause")?"waiting":
        text.startsWith("Preparing")?"preparing":text.startsWith("Listening")?"listening":text.startsWith("Recovering")?"recovering":
        text.startsWith("End of")?"done":text.startsWith("Question finished")?"question":text.startsWith("Connection unavailable")?"offline":
        text.startsWith("Playing")?"playing":text.startsWith("Paused")||text.startsWith("Audio ready")?"paused":"warning";
      playerStatus();
    };
    audioState("Audio off");
    const initialMode = () => readOnly || new URL(location.href).searchParams.get("view") === "conversation"
      || new URLSearchParams(telegram?.initData || "").get("start_param") === "conversation";

    const playbackAllowed = () => !document.hidden || (standalone && voiceEnabled && !voiceSuspended);
    function voiceKey(source) {return source.kind==="native_question"?`${source.id}:${source.revision}`:source.id;}
    function voiceStatus() {
      if(nativeEnabled&&nativeVoiceSession?.active)nativeVoiceSession.setEnabled(voiceEnabled);
      const button=$("#conversation-voice-replies");
      const state=voiceEnabled || active && blobUrl && !audio.ended?"on":"off";
      window.NativeSpeechAudio?.setSession?.(state==="on");
      button.dataset.voiceState=state;
      button.setAttribute("aria-pressed",String(state==="on"));
      button.setAttribute("aria-label",state==="on"?"Stop audio and disable spoken replies":"Enable spoken replies");
      button.title=state==="on"?"Stop audio and disable spoken replies":"Enable spoken replies";
    }
    function enableVoice() {
      if(readOnly || !canListen&&!nativeEnabled)return;
      const resume=voiceSuspended;voiceSuspended=false;
      if(!voiceEnabled || resume){
        voiceEnabled=true;voiceSeen.clear();
        for(const card of cards.values()){voiceSeen.add(voiceKey(card.source));rememberFinal(card.source);}
        for(const source of requestControls.audioSources?.()||[])voiceSeen.add(voiceKey(source));
      }
      if(active && !audio.ended)voiceBusy=true;
      voiceStatus();
    }
    // Client media progress is advisory. Persist only source/revision and the
    // last aligned word or segment boundary, never transcript text or a hearing claim.
    const speechPositions=new Map();let positionBinding;
    const positionKey=()=>"interaction-speech-position:"+binding;
    function positionLabel(card){
      const skipping=active && !active.segmentEnded && !voiceSuspended && (active.auto && !audio.paused || requestAbort) && sameMessage(active.source,card.source);
      const saved=speechPositions.get(card.source.id);
      card.listen.textContent=skipping?"Skip":saved?.revision===card.source.revision?"Resume audio":"Listen";
      card.listen.title=skipping?"Skip the rest of this reply and continue the queue":saved?.revision===card.source.revision?"Resume from the saved word or segment boundary; part of a word may repeat":"Listen to this reply";
    }
    function playbackLabels(){
      for(const card of cards.values())positionLabel(card);
      for(const card of progressCards.values()){
        const original=cards.get(card.source);if(!original || original.source.revision!==card.revision)continue;
        card.listen.textContent=original.listen.textContent;
        card.listen.title=original.listen.title;
        card.listen.setAttribute("aria-label",`${original.listen.textContent} update`);
      }
    }
    async function skipReply(){
      const selected=active;if(!selected || captureBusy)return;
      // A skip is an explicit selection, never a claim that unsaid text was heard.
      rememberSkipped(selected.source);
      liveSpeech?.interrupt(selected.source);
      for(let n=voiceQueue.length-1;n>=0;n--)if(sameMessage(voiceQueue[n],selected.source))removeQueued(n);
      if(prefetched?.ahead && prefetched.selection)await prefetched.selection;
      if(active!==selected)return;
      if(prefetched?.source && !sameMessage(prefetched.source,selected.source))parkPrepared();
      stop("Reply skipped. Continuing the queue.");
      if(voiceEnabled && !voiceSuspended)drainVoice();
    }
    function savePositions(){
      if(!standalone || !binding)return false;
      try{const storage=window.localStorage;if(!storage)return false;storage.setItem(positionKey(),JSON.stringify([...speechPositions.values()]));return true;}catch{return false;}
    }
    function loadPositions(){
      if(positionBinding===binding)return;positionBinding=binding;speechPositions.clear();skippedMessages.clear();interruptedTurns.clear();
      if(!standalone)return;
      try{
        const raw=window.localStorage?.getItem(positionKey());if(!raw || raw.length>16384)return;
        const saved=JSON.parse(raw);if(!Array.isArray(saved)||saved.length>24)return;
        for(const value of saved)if(value && typeof value.source==='string' && value.source.length<=256
          && typeof value.revision==='string' && value.revision.length<=256
          && Number.isSafeInteger(value.offset) && value.offset>=0 && value.offset<=1000000)
          speechPositions.set(value.source,{source:value.source,revision:value.revision,offset:value.offset});
      }catch{}
    }
    function forgetPosition(source){
      if(speechPositions.delete(source.id)){if(savePositions())liveSpeech?.canonicalSaved(source);const card=cards.get(source.id);if(card)positionLabel(card);}
    }
    function rememberPosition(){
      if(!active || active.verifying || !blobUrl)return;
      const source=active.source;
      if(source.current===false || source.correction_pending || source.native_binding_current===false)return;
      const word=alignedPosition();
      if(source.kind==="integrator_live"){
        if(!active.segmentEnded)rememberLiveCursor(liveSpeech?.checkpoint(source,active.offset,word??active.offset));
        return;
      }
      const normal=active.segmentEnded?(Number.isSafeInteger(active.next)?active.next:active.textEnd):(word??active.offset);
      const contiguous=liveSpeech?.checkpoint(source,active.offset,normal)?.resume ?? liveSpeech?.resume(source);
      // A provider word cursor can refine this segment, but cannot hide an
      // earlier interrupted/failed live prefix. No duration interpolation.
      const offset=contiguous===undefined || contiguous>=active.offset?normal:Math.min(normal,contiguous);
      if(active.next===null && offset===active.textEnd && (active.segmentEnded || word===active.textEnd)){
        forgetPosition(source);return;
      }
      speechPositions.delete(source.id);speechPositions.set(source.id,{source:source.id,revision:source.revision,offset});
      while(speechPositions.size>24)speechPositions.delete(speechPositions.keys().next().value);
      if(savePositions())liveSpeech?.canonicalSaved(source);
      const card=cards.get(source.id);if(card)positionLabel(card);
    }
    function rememberLiveCursor(cursor){
      if(!cursor)return;
      if(cursor.resume>=cursor.source.text_characters){forgetPosition(cursor.source);return;}
      speechPositions.delete(cursor.source.id);speechPositions.set(cursor.source.id,{source:cursor.source.id,revision:cursor.source.revision,offset:cursor.resume});
      while(speechPositions.size>24)speechPositions.delete(speechPositions.keys().next().value);
      if(savePositions())liveSpeech?.canonicalSaved(cursor.source);
      const card=cards.get(cursor.source.id);if(card)positionLabel(card);
    }
    function alignedPosition(){
      if(!canReportWordPosition || !active || !Number.isFinite(audio.currentTime) || audio.currentTime<0 || audio.currentTime>3600)return;
      const offset=active.streaming?.position?.(audio.currentTime);
      if(Number.isSafeInteger(offset) && offset>=active.offset && offset<=active.textEnd && offset<=1000000)return offset;
    }
    function playbackContext(interrupted=false){
      if(!canReportPlayback || !active || !blobUrl || active.verifying || active.segmentEnded
        || active.source.current===false || active.source.correction_pending || active.source.native_binding_current===false)return;
      const millis=value=>Number.isFinite(value) && value>=0 && value<=3600?Math.floor(value*1000):undefined;
      const position=millis(audio.currentTime),duration=millis(audio.duration);
      if(position===undefined)return;
      const wordOffset=alignedPosition();
      const word=wordOffset===undefined?{}:{word_offset:wordOffset};
      return {source:active.source.id,revision:active.source.revision,segment_offset:active.offset,...word,
        position_millis:position,duration_millis:duration>0?duration:null,state:interrupted?'interrupted':audio.paused?'paused':'playing'};
    }
    function beginVoiceCapture() {
      replyActivity?.clear();
      const pauseStarted=active && !audio.paused && !audio.muted?window.performance?.now?.():undefined;
      liveSpeech?.interrupt(active?.source);
      if(active?.source.kind.startsWith("integrator_") && typeof active.source.native_turn==="string"){
        interruptedTurns.set(active.source.native_turn,active.source);rememberSkipped(active.source);
        while(interruptedTurns.size>128)interruptedTurns.delete(interruptedTurns.keys().next().value);
      }
      if(automaticInterrupted(prefetched?.source||prefetched?.owner) && !sameMessage(prefetched?.source||prefetched?.owner,active?.source)){prefetched.controller.abort();prefetched=undefined;}
      for(const prepared of queuedPreparations.values())liveSpeech?.interrupt(prepared.source);
      // A canonical tail can already be queued while its live prefix plays.
      // Interrupt the whole native message, including that queued continuation;
      // floor release is not permission to resume it ahead of the correction.
      for(let n=voiceQueue.length-1;n>=0;n--)if(queuedPreparations.has(preparationKey(voiceQueue[n])) || sameMessage(voiceQueue[n],active?.source) || automaticInterrupted(voiceQueue[n])){
        if(automaticInterrupted(voiceQueue[n]))rememberSkipped(voiceQueue[n]);removeQueued(n);
      }
      draft.blur?.();enableVoice();voiceBusy=false;cancelSpeechWait();
      if(active && blobUrl && !active.verifying){
        rememberPosition();active.generation=++generation;active.auto=false;active.interrupted=true;
        audio.pause();audio.muted=true;toggle.disabled=true;playLabel("Resume audio");
        presentState({playback:undefined});
        audioState("Listening to your input. The interrupted reply can be resumed.");
      }else stop("Listening to your input. Replies remain in the conversation.");
      timing?.pauseApplied(pauseStarted);
    }
    const speaker=source=>source.kind.startsWith("integrator_")?"integrator":JSON.stringify(source.target);
    function rememberFinal(source) {
      if(!["worker_result","integrator_answer"].includes(source.kind) || source.current===false || source.correction_pending)return;
      const key=speaker(source),time=Date.parse(source.observed_at)||0;
      voiceFinalTimes.set(key,Math.max(voiceFinalTimes.get(key)||0,time));
    }
    function offerVoice(source) {
      // Attributed peer speech/own delivery intents are visible, not automatic speech as this daimon.
      if(["matrix_inbox","matrix_response","matrix_visibility"].includes(source.kind))return;
      if(nativeEnabled&&nativeVoiceSession?.active)return;
      if(automaticInterrupted(source)){rememberSkipped(source);return;}
      if(!voiceEnabled || voiceSeen.has(voiceKey(source)) || skippedMessages.has(messageKey(source)))return;
      voiceSeen.add(voiceKey(source));
      if(voiceSuspended)return;
      if(active?.source.id===source.id && active.source.revision!==source.revision)stop("This reply changed. Refresh before listening.");
      if(source.current===false || source.correction_pending || source.native_binding_current===false)return;
      const observed=Date.parse(source.observed_at)||0;
      if(source.kind.endsWith("_progress") && observed && observed<=(voiceFinalTimes.get(speaker(source))||0))return;
      rememberFinal(source);
      if(sessionMuted(source))return;
      // A source-bound return announcement is useful conversation, even when
      // the same native turn ends with a different answer or pending decision.
      // Coalesce routine progress without dropping that unheard announcement.
      const sameSpeaker=other=>source.kind.startsWith("integrator_")?other.kind==="integrator_progress"
        && !(Array.isArray(other.native_returns) && other.native_returns.length):
        other.kind==="worker_progress" && JSON.stringify(other.target)===JSON.stringify(source.target);
      if(source.kind.endsWith("_progress") || ["worker_result","integrator_answer"].includes(source.kind)){
        for(let n=voiceQueue.length-1;n>=0;n--)if(sameSpeaker(voiceQueue[n]))removeQueued(n);
      }
      if(source.kind==="native_question"){
        const nextReply=voiceQueue.findIndex(item=>item.kind!=="native_question");
        voiceQueue.splice(nextReply<0?voiceQueue.length:nextReply,0,source);
      }else voiceQueue.push(source);
      voiceStatus();Promise.resolve().then(drainVoice);
    }
    // A single generation-owned waiting state belongs to this player, including
    // gaps when no audio element is active. Cancellation always settles its waiter.
    function cancelSpeechWait() {
      if(!speechWait)return;
      const previous=speechWait;speechWait=undefined;
      clearTimeout(previous.timer);previous.resolve(false);
    }
    function waitForSpeech(kind, source, delay = speechGaps[kind]) {
      cancelSpeechWait();
      const owned=generation;
      return new Promise(resolve=>{
        const waiting={generation:owned,source,resolve,kind};
        speechWait=waiting;
        waiting.timer=setTimeout(()=>{
          if(speechWait!==waiting)return;
          speechWait=undefined;
          resolve(generation===owned && enabled && playbackAllowed() && !captureBusy && !voiceSuspended);
        },delay);
      });
    }
    async function nextSpokenReply(kind="reply", source) {
      if(!voiceEnabled || voiceSuspended)return;
      voiceBusy=true;
      if(await waitForSpeech(kind,source)){voiceBusy=false;drainVoice();}
    }
    async function drainVoice() {
      if(nativeEnabled&&nativeVoiceSession?.active)return;
      if(!voiceEnabled || voiceSuspended || voiceBusy || speechWait || captureBusy || questionRefreshPending || !enabled || !canListen || !playbackAllowed())return;
      while(voiceQueue.length&&(sessionMuted(voiceQueue[0]) || skippedMessages.has(messageKey(voiceQueue[0])) || automaticInterrupted(voiceQueue[0])))removeQueued(0);
      voiceBusy=true;const selectionGeneration=generation;
      if(prefetched?.ahead && !active?.interrupted)await prefetched.selection;
      if(generation!==selectionGeneration)return;
      if(questionRefreshPending){voiceBusy=false;return;}
      if(voiceQueue[0]?.kind==="native_question")parkPrepared();
      let next,prepared;
      if(voiceQueue[0]?.kind!=="native_question" && prefetched?.ahead && prefetched.source && !active?.interrupted){
        prepared=prefetched;next=prepared.source;
        const duplicate=voiceQueue.findIndex(source=>source.id===next.id && source.revision===next.revision);
        if(duplicate>=0)voiceQueue.splice(duplicate,1);
      }else next=voiceQueue.shift() || (canSpeakLive && !sessionMuted({kind:"integrator_live"})?await liveSpeech?.next():undefined);
      if(generation!==selectionGeneration){liveSpeech?.unsent(next);return;}
      if(questionRefreshPending || (next?.kind!=="native_question" && voiceQueue[0]?.kind==="native_question")){
        if(next && !prepared){
          if(next.kind==="integrator_live")liveSpeech?.unsent(next);
          else {const afterQuestions=voiceQueue.findIndex(source=>source.kind!=="native_question");voiceQueue.splice(afterQuestions<0?voiceQueue.length:afterQuestions,0,next);}
        }
        voiceBusy=false;if(!questionRefreshPending)drainVoice();return;
      }
      voiceStatus();if(!next){voiceBusy=false;return;}
      if(automaticInterrupted(next)){rememberSkipped(next);liveSpeech?.interrupt(next);liveSpeech?.unsent(next);voiceBusy=false;return;}
      const offset=next.speech_start||0;
      prepared ||= queuedPreparations.get(preparationKey(next,offset));
      if(!voiceEnabled || voiceSuspended || captureBusy || !enabled || !playbackAllowed() || sessionMuted(next)){liveSpeech?.unsent(next);voiceBusy=false;return;}
      if(next.kind==="integrator_live" && !prepared && !liveSpeech?.admit(next)){voiceBusy=false;return;}
      const result=await listenTo(next,offset,{queued:true});
      if(result?.failed && result.generation===generation && !active)
        nextSpokenReply("reply",next);
    }
    function continueSpeech(){
      interruptedTurns.delete(active?.source.native_turn);if(active)skippedMessages.delete(messageKey(active.source));
      const remaining=liveSpeech?.continueSource(active?.source);
      if(!remaining || voiceQueue.some(source=>source.id===remaining.id && source.revision===remaining.revision))return;
      const nextReply=voiceQueue.findIndex(source=>source.kind!=="native_question");
      voiceQueue.splice(nextReply<0?voiceQueue.length:nextReply,0,remaining);
    }
    function disableVoice() {
      voiceEnabled=false;voiceBusy=false;clearVoiceQueue();voiceFinalTimes.clear();voiceContext=undefined;voiceStatus();stop();
    }
    $("#conversation-voice-replies").addEventListener("click",()=>{
      if(voiceEnabled || active && blobUrl && !audio.ended){disableVoice();}else {
        window.PcmSpeech?.unlock();enableVoice();
        if(captureBusy){voiceBusy=false;return;}
        if(active && blobUrl && !audio.ended){
          continueSpeech();voiceBusy=true;void startPlayback();
        }else{
          // A cancelled preparation or ended segment cannot own the queue
          // forever. Release it without retrying its synthesis automatically.
          if(active)stop();
          voiceBusy=false;audioState("Waiting for replies");drainVoice();
        }
      }
    });
    function stop(text = voiceEnabled?"Waiting for replies":"Audio off") {
      replyActivity?.clear();
      rememberPosition();
      presentState({playback:undefined});
      cancelSpeechWait();voiceBusy=false;generation++;
      requestAbort?.abort(); requestAbort = undefined;
      prefetched?.controller.abort();prefetched=undefined;
      active?.streaming?.cancel();
      active = undefined;playbackLabels();
      audio.pause(); audio.muted = true;
      audio.removeAttribute("src"); audio.load();
      if (blobUrl) URL.revokeObjectURL(blobUrl);
      blobUrl = undefined;
      toggle.disabled = true;playLabel("Play audio");
      if(mediaSession)try{mediaSession.playbackState="none";}catch{}
      audioState(text);
      $("#conversation-playing").textContent="Audio";playerStatus();
    }
    function pause(reason="manual") {
      replyActivity?.clear();
      if(nativeEnabled&&nativeVoiceSession?.active){nativeVoiceSession.pause(reason);return;}
      if(voiceEnabled && !voiceSuspended){
        const button=$("#conversation-voice-replies");
        button.dataset.lastPauseReason=reason;button.dataset.lastPauseAt=new Date().toISOString();
      }
      rememberPosition();
      presentState({playback:undefined});
      cancelSpeechWait();voiceBusy=false;clearVoiceQueue();
      voiceSuspended=true;voiceStatus();
      if(mediaSession)try{mediaSession.playbackState="paused";}catch{}
      generation++;
      if (!active) return;
      if(!active.streaming)requestAbort?.abort();
      requestAbort = undefined;
      active.generation = generation;
      active.auto = false;
      audio.pause(); audio.muted = true;
      playLabel("Play audio");
      toggle.disabled = !blobUrl;
      audioState("Paused. Your replies remain available.");playbackLabels();
    }
    function setMode(value, initial = false, navigate = true) {
      if(standalone && !value)return;
      enabled = value;
      document.body.classList.toggle("conversation-mode", enabled);
      $("#conversation").hidden = !enabled;
      $(".identity h1").textContent = standalone ? "Daimon" : readOnly ? "Routing monitor" : enabled ? "Conversation" : "Sessions";
      document.title = standalone ? "Daimon Interaction" : `${enabled ? "Conversation" : "Sessions"} · Telecodex`;
      if (navigate && !readOnly) {
        const url = new URL(location.href);
        if (enabled) url.searchParams.set("view", "conversation");
        else url.searchParams.delete("view");
        history.replaceState(null, "", url);
      }
      try { telegram?.BackButton?.[enabled ? "show" : "hide"]?.(); } catch (_) {}
      if (!enabled) {pause("view");  microphone?.deactivate();}
      modeChanged(enabled, initial);
    }
    // api() aborts a request at its deadline. That is a connection interruption,
    // not an explicit decision to pause spoken replies.
    const transientConnectionError=error=>["TypeError","AbortError"].includes(error.name) || error.status>=500;
    function failed(error) {
      showResponseDraft();
      // A metadata refresh is not the independently authorized native socket.
      // Only actual access rejection closes both; that socket checks its actor
      // and binding itself while a background HTTP observation is unavailable.
      const keepNative=nativeEnabled&&nativeVoiceSession?.active&&error.status!==401&&error.status!==403;
      presentState({connected:false},!keepNative);
      if (error.status === 401 || error.status === 403) {
        hostSurface?.disconnect();draftState?.bind();avatarWorkshop?.reset();
        onUnauthorized?.(error);
        workspace?.reset();clearFiles();
        pause("access");stop(); cards.clear();clearProgress();clearText(); initialized = false; resetInputs(); requestControls.reset(); internalControls?.reset(); taskControls?.reset(); microphone?.reset(); visual?.reset();attachedFiles?.reset();
        $("#conversation-answers").replaceChildren();
        $("#conversation-results").replaceChildren();
      } else if(!keepNative&&!(standalone && voiceEnabled && !voiceSuspended && transientConnectionError(error)))pause("observation");
      $("#conversation-state").textContent = error.name === "TypeError" ? "Connection unavailable. Refresh to reconnect."
        : error.message || "Replies are unavailable. Refresh to continue.";
    }
    function part(source, offset) {
      const query = new URLSearchParams({source:source.id, revision:source.revision, offset:String(offset)});
      return api(`interaction/part?${query}`);
    }
    function listenCard(card) {
      if(readOnly || captureBusy || card.listen.disabled)return;
      if(active && !active.segmentEnded && !voiceSuspended && (active.auto && !audio.paused || requestAbort) && sameMessage(active.source,card.source))return skipReply();
      const saved=speechPositions.get(card.source.id);
      if(active?.source.id===card.source.id && active.source.revision===card.source.revision && blobUrl && !audio.ended && (!saved || saved.offset>=active.offset)){
        continueSpeech();voiceSuspended=false;voiceStatus();return startPlayback();
      }
      return listenTo(card.source,saved?.revision===card.source.revision?saved.offset:0);
    }
    const matrixAddress=String.raw`dm:(?:being|identity):v[0-9]+:[A-Za-z0-9_-]+(?:/embodiment:[a-f0-9-]{36})?`;
    const machineRoute=new RegExp(`^${matrixAddress} → ${matrixAddress}(?: · [0-9]+/[0-9]+)?\r?\n(?:\r?\n|↩ )`);
    function upsert(source) {
      // The visibility writer's unresolved route header is transport data.
      // Keep its full retained copy in the existing diagnostic reader.
      const technicalVisibility=source.kind==="matrix_visibility"&&machineRoute.test(source.preview);
      // One visible card per signed event when both ordinary reply and inbox projections exist.
      const matrixEvent=source.kind==="matrix_result"?source.id.slice("matrix:".length):source.kind==="matrix_response"?source.handling?.outcome?.message_id:undefined;
      if(matrixEvent){const echo=cards.get(`matrix-inbox:${matrixEvent}`);if(echo){echo.box.remove();cards.delete(echo.source.id);}}
      if(source.kind==="matrix_inbox"){
        const event=source.id.slice("matrix-inbox:".length);
        if(cards.has(`matrix:${event}`)||[...cards.values()].some(card=>card.source.kind==="matrix_response"&&card.source.handling?.outcome?.message_id===event))return;
      }
      const followingLive=atTimelineEnd();
      let card = cards.get(source.id);
      if (!card) {
        const container = $(source.kind === "integrator_answer" ? "#conversation-answers" : "#conversation-results");
        const box = node("article", undefined, "reply");
        const title = node("h3");
        const status = node("p", "", "reply-status");
        const body = node("div", undefined, "reply-text");setReplyText(body,source.preview);
        const actions = node("div", undefined, "reply-actions");
        const read = node("button", "Read reply"); read.type = "button";
        const listen = node("button", "Listen"); listen.type = "button";
        const error = node("p", "", "reply-error"); error.setAttribute("role", "status");
        const reply=node("button",source.kind.startsWith("integrator_")?"Reply to this message":"Reply to this session");reply.type="button";reply.hidden=readOnly || !["worker_result","matrix_result","matrix_inbox","matrix_response","integrator_answer","integrator_progress"].includes(source.kind);
        const time=node("time",undefined,"message-time");
        actions.append(read, listen,reply,copyButton(()=>copySource(card))); box.append(title, status, body, actions, error,time);
        box.dataset.sequence = String(source.sequence);
        const following = [...container.children].find((item) => Number(item.dataset.sequence) < source.sequence);
        if(!timeline || source.kind==="worker_progress" || technicalVisibility)container.insertBefore(box, following || null);
        card = {source, box, title, status, body, read, listen, error,time, offset:0, expanded:false};
        cards.set(source.id, card);
        reply.addEventListener("click",()=>selectFocus({source:card.source.id,revision:card.source.revision,...(["matrix_result","matrix_inbox","matrix_response"].includes(card.source.kind) || card.source.kind.startsWith("integrator_")?{context_only:true}:{})},card.source.label||"this session"));
        read.addEventListener("click",()=>readCard(card));
        listen.hidden=readOnly;listen.addEventListener("click",()=>listenCard(card));
      } else if (card.source.text_sha256 !== source.text_sha256) {
        setReplyText(card.body,source.preview);
        card.autoRevision=undefined;card.autoWanted=false;
        card.offset = 0; card.expanded = false; card.read.hidden = false;
        card.read.textContent = "Read reply";
      }
      for(let n=voiceQueue.length-1;n>=0;n--)
        if(voiceQueue[n].id===source.id && voiceQueue[n].revision!==source.revision)removeQueued(n);
      if (active?.source.id === source.id && active.source.revision !== source.revision)
        stop("This reply changed. Refresh before listening.");
      const textChanged=card.source.revision!==source.revision;
      card.source = source;card.box.dataset.sourceId=source.id;card.box.dataset.sourceRevision=source.revision;
      if(!card.expanded && Number.isSafeInteger(source.text_characters) && source.text_characters===Array.from(source.preview).length)card.read.hidden=true;
      for(const file of source.artifacts||[])files.set(file.id,file);
      renderFiles(card);
      messageTime(card.time,source.observed_at);card.box.append(card.time);
      const integrator=source.kind.startsWith("integrator_");
      const progress=source.kind.endsWith("_progress");
      sessionTitle(card,source,integrator ? "Conversation" : source.label);
      const matrix=source.kind==="matrix_inbox"||source.kind==="matrix_response";
      const visibility=source.kind==="matrix_visibility";
      card.box.classList.toggle("matrix-visibility-record",visibility);
      const deliveryPhase=source.handling?.phase;
      const delivery=source.handling?.outcome;
      const sendingBeing=delivery?.author?.being_ref;
      const partialDelivery=deliveryPhase==="submitted" && !!sendingBeing && Array.isArray(delivery.members) &&
        delivery.members.some(member=>member?.being_ref && member.being_ref!==sendingBeing && member.receiving_copy==="proved");
      const diagnosticStatus = visibility ? "Durable communication copy. This record is not a human message or a delivery confirmation." : matrix ? (source.kind==="matrix_response" ?
        deliveryPhase==="recipient_copy_proved" ? "Recipient receiving copy proved. Reading and work completion are unconfirmed." :
        deliveryPhase==="uncertain" ? "Delivery uncertain. The original response intent is retained; it has not been resent." :
        partialDelivery ? "Delivery confirmed for some recipients; the remaining recipients are unconfirmed." :
        deliveryPhase==="submitted" ? "Submitted; recipient delivery is not proved." : "Response intent retained; delivery is not proved."
        : source.direction==="outgoing" ? "Own message retained in the signed Matrix inbox. Recipient delivery is not established by this copy." : "SDK-authenticated incoming message. Peer speech is not human instruction or proof of completed work.") : progress ? "Progress update." : source.kind === "integrator_answer" ? "Reply from this conversation."
        : source.correction_pending ? "A later correction is pending."
        : !source.native_binding_current ? "From an earlier session."
        : !source.current ? "Instruction coverage has not been confirmed."
        : source.kind === "matrix_result" ? "Reply from the selected daimon. Work completion is not independently verified."
        : source.completed ? "Session reports this request complete." : "Session progress; work may continue.";
      card.status.textContent = visibility ? "Communication" : matrix ? (
        source.kind==="matrix_response" ? deliveryPhase==="recipient_copy_proved" ? "Delivered" :
          partialDelivery ? "Partly delivered" : deliveryPhase==="submitted" ? "Sent · delivery unconfirmed" : "Delivery not confirmed" :
          source.direction==="incoming" ? "Received" : "Message copy") : diagnosticStatus;
      if(matrix || visibility){
        if(!card.matrixDetails){
          card.matrixDetails=node("details");card.matrixDetails.append(node("summary","Matrix details"));card.matrixReceipt=node("pre",undefined,"route-identity");card.matrixDetails.append(card.matrixReceipt);card.box.append(card.matrixDetails);
        }
        card.matrixReceipt.textContent=JSON.stringify({direction:source.direction,author:source.source_author,
          original:source.kind==="matrix_inbox"?source.id.slice("matrix-inbox:".length):undefined,
          parent:source.parent_message_id,thread:source.thread_id,send:source.send_id,
          handling:source.handling,verification:source.verification,diagnostic:diagnosticStatus,
          ...(visibility?{publication:source.publication_id,resource:source.publication_resource,
            request_sha256:source.publication_request_sha256,part_index:source.part_index,part_count:source.part_count}:{})},null,2);
      }
      card.box.dataset.pending = String(!!source.correction_pending || source.native_binding_current === false);
      card.technicalVisibility = technicalVisibility;
      card.listen.hidden = !canListen || technicalVisibility;
      if(source.current===false || source.correction_pending || source.native_binding_current===false
        || speechPositions.get(source.id)?.revision!==source.revision)forgetPosition(source);
      positionLabel(card);
      sessionProgress(source);
      if(technicalVisibility){
        textObserver?.unobserve(card.box);
        const results=$("#conversation-results");
        if(card.box.parentNode!==results)results.append(card.box);
      }else if(source.kind!=="worker_progress"){
        placeInTimeline(card.box,source.id,source.observed_at,followingLive);
        if(textChanged)textObserver?.unobserve(card.box);
        textObserver?.observe(card.box);
      }
    }
    async function page(cursor, direction, rememberHistory = true) {
      const value = await api(`interaction?${new URLSearchParams({...cursor, direction})}`);
      if (binding && value.binding !== binding) {
        draftState?.bind();
        hostedTopic=undefined;workspace?.reset();clearVoiceQueue();stop(); cards.clear();clearProgress();clearText(); initialized = false; resetInputs(); requestControls.reset(); internalControls?.reset(); taskControls?.reset(); microphone?.reset(); visual?.reset();attachedFiles?.reset();
        newest = {delivery:0,native:0,matrix:0,inbox:0,responses:0,publications:0};
        $("#conversation-answers").replaceChildren(); $("#conversation-results").replaceChildren();
      }
      if(standalone){
        const profile=value.presentation_profile==="explorer"?"explorer":"simple";
        if(profile!==presentationProfile){
          document.body.dataset.presentationProfile=profile;
          presentationProfile=profile;
        }
      }
      companion?.configure?.(value.expression_pack,value.expression_pack_sha256);
      avatarWorkshop?.bind(value.binding);
      companion?.observe(value.activity);
      binding = value.binding;hostSurface?.bind(binding);timing?.bind(binding);loadPositions();loadSessionMutes();canReportPlayback=value.can_report_playback===true;canReportWordPosition=value.can_report_word_position===true;canLimitCaptureQuestions=value.can_limit_capture_questions===true;canReplyUpdates=value.can_reply_updates===true;
      canBudgets=!readOnly && value.can_view_coordination===true;
      if(budgetView)budgetView.hidden=!canBudgets;
      if(!canBudgets)budgetEpisodes?.replaceChildren();
      canFiles=!readOnly && value.can_download_files===true;
      if(!canFiles)clearFiles();
      else if(value.artifacts?.state==="unavailable")filesConnected=false;
      else {filesConnected=true;fileJobs=value.artifacts?.jobs||[];files.clear();for(const card of cards.values())for(const file of card.source.artifacts||[])files.set(file.id,file);for(const file of value.artifacts?.items||[])files.set(file.id,file);}
      refreshFiles();
      await goalControls?.observe(value.goal_controls);
      lastVoiceCapabilities=value;openaiConversationAvailable=value.can_openai_conversation===true;
      microphone?.configure(value.can_speak,conversationServices!=='openai'&&(value.previous_can_stream_transcribe??value.can_stream_transcribe),value.streaming_transcription_mode,conversationServices==='openai'&&value.openai_can_stream_transcribe);
      providerNativeEnabled=value.can_converse_native===true&&window.NativeConversation?.supported()===true;
      providerContinuousEnabled=value.can_converse_continuous===true;providerVoiceAvailable=value.can_converse===true;
      codexEnabled=value.can_converse_codex===true&&window.CodexConversation?.supported()===true;
      publicLiveEnabled=value.can_converse_public_live===true&&window.PublicLiveConversation?.supported()===true;
      publicLiveResponsesEnabled=publicLiveEnabled&&value.can_converse_public_live_responses!==false;
      publicLiveNativeEnabled=publicLiveEnabled&&value.can_converse_public_live_native===true;
      if(!servicesDefaultApplied){servicesDefaultApplied=true;if(value.voice_services_default==='openai'){conversationServices='openai';voiceChoice='gpt-live-native';}if(value.avatar_voice_default==='gpt-live-native'&&publicLiveNativeEnabled)voiceChoice='gpt-live-native';}
      selectVoiceEngine();
      if(codexEnabled)void codexVoiceSession?.restoreHistory().catch(()=>{});
      if(publicLiveEnabled)void publicLiveSession?.restoreHistory().catch(()=>{});
      setCsrf(value.csrf);void foregroundHistory();
      canListen = !readOnly && value.can_listen;canStreamSpeech=canListen && !!value.can_stream_speech;
      if(Object.hasOwn(value,'can_decide_requests'))canDecideRequests=!readOnly&&value.can_decide_requests===true;
      canSpeakLive=canListen && value.can_speak_live_response===true;
      applyConversationServices();
      if(!canSpeakLive)liveSpeech?.reset();
      else liveSpeech?.observe(value.response_draft,binding);
      if(!canListen && !nativeEnabled && (voiceEnabled || active || speechWait))pause("capability");
      $("#conversation-voice-replies").disabled=!canListen&&!nativeEnabled;
      const sources=hostSurface?value.items.filter(source=>source.kind.startsWith('integrator_')):value.items;
      for (const source of sources){
        upsert(source);timing?.source(source);
        const card=cards.get(source.id);
        if(card)card.listen.disabled=canSpeakLive && liveSpeech?.needsReconcile(source)===true;
      }
      if(direction==="after")for(const source of sources)if(!["matrix_inbox","matrix_response","matrix_visibility"].includes(source.kind))companion?.reply(source);
      for(const source of [...sources].sort((a,b)=>(Date.parse(a.observed_at)||0)-(Date.parse(b.observed_at)||0))){
        if(active?.source.kind==="integrator_live" && active.source.native_turn===source.native_turn && active.source.native_item===source.native_item)rememberPosition();
        const reconciled=canSpeakLive && (direction==="after" || liveSpeech?.needsReconcile(source))?await liveSpeech?.reconcile(source,part):undefined;
        if(reconciled?.changed)cancelPreparedMessage(source);
        if(reconciled?.changed && active?.source.kind==="integrator_live" && active.source.native_turn===source.native_turn && active.source.native_item===source.native_item)
          stop("The confirmed response changed. Its updated text remains available.");
        if(reconciled?.resume!==undefined){
          speechPositions.set(source.id,{source:source.id,revision:source.revision,offset:reconciled.resume});
          if(savePositions())liveSpeech?.canonicalSaved(source);
          const card=cards.get(source.id);if(card)positionLabel(card);
        }
        const card=cards.get(source.id);
        if(card?.source.revision===source.revision)card.listen.disabled=false;
        // Initial/history pages can contain a response confirmed while the
        // view was closed. Transfer its retained cursor without speaking history.
        if(reconciled?.skip)voiceSeen.add(voiceKey(source));
        else if(direction==="after")offerVoice(reconciled?.source||source);
      }
      const next=voiceQueue[0];
      // Prepare one confirmed reply while the timeline and question registry
      // finish refreshing. Only drainVoice can make automatic speech audible.
      if(direction==="after" && questionRefreshPending && next
        && ["integrator_answer","worker_result"].includes(next.kind)
        && voiceEnabled && !voiceSuspended && !voiceBusy && !active && !captureBusy
        && !prefetched && !queuedPreparations.size && enabled && canListen && !canStreamSpeech
        && playbackAllowed() && window.navigator?.onLine!==false && !sessionMuted(next)){
        const offset=next.speech_start||0,controller=new AbortController();
        const prepared={source:next,offset,controller};
        prepared.result=requestAudio(next,offset,controller,nextOffset=>{
          prepared.bufferedNext=nextOffset;
          prepared.onBufferedPart?.(nextOffset);
        }).then(value=>({value}),error=>({error}));
        queuedPreparations.set(preparationKey(next,offset),prepared);
      }
      playbackLabels();
      showResponseDraft(value.response_draft);
      if(active?.auto && !audio.paused && !active.verifying)prefetchNext(active);
      for (const card of cards.values()) card.listen.hidden = !canListen || card.technicalVisibility;
      // Recent metadata may jump ahead of a backlog still being read forward.
      if (direction === "after" || (rememberHistory && !initialized)) {
        newest.delivery = Math.max(newest.delivery, value.newest.delivery);
        newest.native = Math.max(newest.native, value.newest.native);
        newest.matrix = Math.max(newest.matrix || 0, value.newest.matrix || 0);
        for(const key of ["inbox","responses","publications"])newest[key]=Math.max(newest[key]||0,value.newest[key]||0);
      }
      return value;
    }
    let refreshAgain = false, questionRefreshPending = false, inputRefresh;
    function refreshSavedInputs() {
      if(!binding)return;
      if(inputRefresh)return inputRefresh;
      const owned=inputGeneration;
      inputRefresh=(async()=>{
        try {
          if(!inputBinding)await inputPage();
          else {
            let more=true;
            for(let n=0;n<4 && more && owned===inputGeneration;n++){
              const result=await inputPage(inputNewest,"after");
              more=!!result?.more;
            }
            if(owned===inputGeneration)await inputPage(0,"before",false);
          }
        }catch(error){
          if(owned===inputGeneration && [401,403].includes(error.status))failed(error);
        }
      })().finally(()=>{inputRefresh=undefined;});
      return inputRefresh;
    }
    async function refresh(force = false) {
      if (!enabled || !ready || (!playbackAllowed() && !force)) return;
      if(reading){
        refreshAgain ||= force;
        void refreshSavedInputs();
        return;
      }
      let saved=refreshSavedInputs();
      drainText();
      reading = true;questionRefreshPending=!readOnly;
      $("#conversation-refresh").disabled = true;
      try {
        const previousBinding=binding;
        if(previousBinding&&(!hostSurface||hostedTopic))void workspace?.refresh(previousBinding);
        if (!initialized) {
          newest = {delivery:0,native:0,matrix:0,inbox:0,responses:0,publications:0};
          await page({delivery:0,native:0,matrix:0,inbox:0,responses:0,publications:0}, "before");
          initialized = true;
        } else {
          let more = true;
          for (let n = 0; n < 4 && more && enabled && playbackAllowed(); n++) {
            const value = await page(newest, "after");
            if (!initialized) { newest = {delivery:0,native:0,matrix:0,inbox:0,responses:0,publications:0}; await page(newest,"before"); initialized = true; break; }
            more = value.more;
            if(n===3 && more)refreshAgain=true;
          }
          if (enabled && playbackAllowed()) await page({delivery:0,native:0,matrix:0,inbox:0,responses:0,publications:0}, "before", false);
        }
        // Saved input receipts and transcripts have their own bounded reader.
        // Sound, questions and presentation must not hold their readback.
        saved ||= refreshSavedInputs();
        if(binding!==previousBinding&&(!hostSurface||hostedTopic))void workspace?.refresh(binding);
        // Resolve current questions before starting newly observed speech. Input
        // history, Telegram and inspector reads do not gate useful playback.
        const questionsCurrent=readOnly || await requestControls.refresh();
        if(!readOnly && questionsCurrent){
          const questions=requestControls.audioSources?.()||[];
          presentState({question:questions.length>0});
          const current=source=>questions.some(q=>q.id===source.id && q.revision===source.revision);
          for(let n=voiceQueue.length-1;n>=0;n--)
            if(voiceQueue[n].kind==="native_question" && !current(voiceQueue[n]))removeQueued(n);
          if(active?.source.kind==="native_question" && !current(active.source))
            stop("This question is no longer current. Refresh before answering.");
        }
        $("#conversation-state").textContent = (standalone||hostSurface)&&cards.size ? "" : cards.size ? `${cards.size} ${cards.size===1?"reply":"replies"} available.`
          : "No replies yet. Work can continue while this view is closed.";
        questionRefreshPending=!questionsCurrent;drainVoice();
        if (active && enabled && playbackAllowed()) {
          const selected = active, owned = generation;
          try { await part(selected.source, selected.offset); }
          catch (error) {
            if (active === selected && generation === owned){
              if(error.status===401 || error.status===403)failed(error);
              else if(!transientConnectionError(error))stop("This reply is no longer current. Refresh before listening.");
            }
          }
        }
        if(!readOnly){await taskControls?.refresh();await internalControls?.refresh();}
        await refreshTelegram();
        for(const card of inputs.values())if(card.trace.open)await readTrace(card);
        drainVoice();
      } catch (e) { failed(e); }
      finally { reading = false; $("#conversation-refresh").disabled = false;
        if(refreshAgain){refreshAgain=false;setTimeout(()=>refresh(true),0);}
      }
      await saved;
    }

    async function fallbackProgressive(selected,owned,position=audio.currentTime){
      if(!selected?.streaming || selected.usingBlob)return false;
      if(selected.fallbackPromise)return selected.fallbackPromise;
      audioState("Recovering playback from the same audio. No new synthesis requested.");
      selected.fallbackPromise=(async()=>{
        const result=await selected.streaming.done;
        if(active!==selected || generation!==owned || captureBusy || voiceSuspended || !enabled || !playbackAllowed())return true;
        if(!result?.complete || !result.blob?.size)return false;
        // Reuse only the already verified encoded bytes. No provider/network
        // retry, new paid attempt, rewritten source or lost playback cursor.
        selected.generation=++generation;
        selected.usingBlob=true;selected.resumePosition=Number.isFinite(position)&&position>=0?position:0;
        selected.streaming.cancel();
        blobUrl=URL.createObjectURL(result.blob);audio.src=blobUrl;
        await startPlayback();return true;
      })();
      const attempt=selected.fallbackPromise;
      try{return await attempt;}finally{if(selected.fallbackPromise===attempt)delete selected.fallbackPromise;}
    }
    function stopFailedSpeech(selected,message){
      if(active!==selected)return;
      // An incomplete stream cannot establish a heard boundary. Hold the
      // rest of this message for explicit playback and keep independent replies.
      rememberSkipped(selected.source);
      liveSpeech?.interrupt(selected.source);
      for(let n=voiceQueue.length-1;n>=0;n--)if(sameMessage(voiceQueue[n],selected.source))removeQueued(n);
      if(prefetched?.source&&!sameMessage(prefetched.source,selected.source))parkPrepared();
      stop(message);
      if(voiceEnabled && !voiceSuspended)void nextSpokenReply("reply",selected.source);
    }
    async function audioDecodeFailed(selected=active){
      if(!selected || active!==selected)return;
      const owned=generation,position=audio.currentTime;
      if(await fallbackProgressive(selected,owned,position))return;
      if(active!==selected || generation!==owned)return;
      stopFailedSpeech(selected,"Audio decoding stopped. Your text and playback position remain available.");
    }
    const continuationLeadSeconds = 2;
    const continuationProofMaxMs = 2400;
    function verifyBufferedContinuation(selected) {
      const prepared = prefetched;
      if (!selected?.auto || selected.segmentEnded || selected.verifying || (selected.streaming && !selected.usingBlob)
        || selected.source.kind === "integrator_live" || selected.source.kind === "native_question"
        || selected.next == null || selected.end !== selected.next || !prepared?.buffered
        || prepared.source.id !== selected.source.id || prepared.source.revision !== selected.source.revision
        || prepared.offset !== selected.next
        || prepared.continuationCheck?.generation === generation || audio.paused || audio.muted
        || document.hidden || window.navigator?.onLine===false || voiceSuspended || captureBusy
        || !enabled || !playbackAllowed() || sessionMuted(selected.source)) return;
      const remaining = audio.duration - audio.currentTime;
      if (!Number.isFinite(remaining) || remaining <= 0 || remaining > continuationLeadSeconds) return;
      prepared.continuationCheck = {
        previous: selected,
        generation,
        binding,
        result: part(prepared.source, prepared.offset)
          .then(value=>({value,verifiedAt:performance.now()}),error=>({error}))
      };
    }

    async function startPlayback(continuationCheck) {
      const selected = active;
      if (!selected || !blobUrl || !playbackAllowed() || !enabled || captureBusy
        || workspaceAudioScope!==undefined&&sessionMuted(selected.source)) return;
      const owned = selected.generation;
      const position = selected.resumePosition ?? audio.currentTime;
      selected.verifying = true;
      audio.muted = true;
      // Unlock this element on a user gesture; source validation happens muted.
      try {
        const started = audio.play();
        const check = continuationCheck?.result || part(selected.source, selected.offset).then(value=>({value}));
        const [,observed]=await Promise.all([started, check]);
        if (active !== selected || generation !== owned) return;
        if(observed.error)throw observed.error;
        let verified=observed.value;
        if(continuationCheck && (continuationCheck.binding!==binding || document.hidden
          || window.navigator?.onLine===false || performance.now()-observed.verifiedAt>continuationProofMaxMs)){
          verified=await part(selected.source, selected.offset);
          if(active!==selected || generation!==owned)return;
        }
        async function validatePrefix(value){
          if(selected.end===undefined)return value;
          const chars=Array.from(value.text),count=selected.end-selected.offset;
          if(count>chars.length)throw Error("Audio exceeds its canonical text part");
          const text=chars.slice(0,count).join("");
          const hash=[...new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(text)))].map(byte=>byte.toString(16).padStart(2,"0")).join("");
          if(hash!==selected.textHash)throw Error("Audio text prefix changed");
          return {...value,text,next_offset:selected.next};
        }
        verified=await validatePrefix(verified);
        if(active!==selected || generation!==owned)return;
        audio.pause(); audio.currentTime = position;delete selected.resumePosition;
        // Unlock on the gesture above, then build a small media-time reserve
        // before making progressive speech audible. No new synthesis/retry.
        if(selected.streaming?.ready && !selected.usingBlob){
          await selected.streaming.ready(position);
          if(active!==selected || generation!==owned)return;
          // Buffering can outlive a source revision or access grant. Revalidate
          // the exact audible prefix after that wait, before releasing sound.
          verified=await validatePrefix(await part(selected.source,selected.offset));
          if(active!==selected || generation!==owned)return;
        }
        selected.verifying = false;
        selected.segmentEnded = false;
        selected.verified=verified;
        selected.textEnd=selected.offset+Array.from(verified.text).length;
        selected.auto = true;selected.interrupted=false;
        audio.muted = false;
        await audio.play();
        if (active !== selected || generation !== owned) return;
        if(replyFocus?.reference.context_only){clearFocus();selected.focusVersion=focusVersion;}
        voiceContext=["worker_result","matrix_result","native_question"].includes(selected.source.kind)
          ?{source:selected.source.id,revision:selected.source.revision,context_only:true}:undefined;
        playLabel("Pause audio");
        audioState("Playing this reply.");
        presentState({playback:"playing"});playbackLabels();
        if(mediaSession)try{
          if(window.MediaMetadata)mediaSession.metadata=new window.MediaMetadata({title:selected.source.label||"Conversation reply",artist:"Daimon Interaction"});
          mediaSession.playbackState="playing";
        }catch{}
        followPlayback();
        prefetchNext(selected);
        verifyBufferedContinuation(selected);
      } catch (e) {
        if (active !== selected || generation !== owned) return;
        selected.verifying = false;
        audio.pause(); audio.muted = true;
        if(e.name!=="NotAllowedError" && !transientConnectionError(e) && selected.streaming && !selected.usingBlob){
          if(await fallbackProgressive(selected,owned,position))return;
          if(active!==selected || generation!==owned)return;
        }
        if (e.name === "NotAllowedError") {
          toggle.disabled = false; playLabel("Play audio");
          audioState("Audio ready. Press Play audio to listen.");
        } else if(standalone && voiceEnabled && !voiceSuspended && transientConnectionError(e)){
          selected.auto=true;playLabel("Play audio");toggle.disabled=false;
          audioState("Connection unavailable. Playback will resume after reconnection.");
        } else {
          stop("This reply changed or is unavailable. Refresh before listening.");
          return {failed:true,generation};
        }
      }
    }
    async function requestAudio(source,offset,controller,onBufferedPart){
      const deadline=setTimeout(()=>controller.abort(),145000),speechProvider=conversationServices==='openai'?'openai':undefined;
      try{
        const response = await fetch("api/interaction/audio", {method:"POST",credentials:"same-origin",
          headers:headers(),signal:controller.signal,body:JSON.stringify({source:source.id,revision:source.revision,offset,...((speechProvider||lastVoiceCapabilities?.voice_services_default==='openai')?{speech_provider:speechProvider||'current'}:{}),...(canStreamSpeech && window.NativeSpeechAudio?.progressive!==false && source.kind!=="native_question" && window.SpeechStream?.available()?{stream:true}:{})})});
        if (!response.ok) {
          const value = await response.json();
          const error = new Error(value.detail || "Audio unavailable. Continue reading or refresh.");
          error.status = response.status; throw error;
        }
        if(speechProvider && response.headers.get("x-speech-provider")!==speechProvider)throw Error("Selected speech provider unavailable; no fallback");
        if (response.headers.get("x-presentation-source") !== source.id
            || response.headers.get("x-presentation-revision") !== source.revision
            || response.headers.get("x-presentation-offset") !== String(offset)) throw new Error("Audio source mismatch");
        if(response.headers.get("content-type")?.startsWith("application/x-ndjson")){
          const encoding=response.headers.get("x-audio-encoding");
          if(!canStreamSpeech || !window.SpeechStream?.available() || !["mp3","pcm_s16le"].includes(encoding))throw Error("Unexpected streaming audio");
          const nextHeader=response.headers.get("x-presentation-next-offset"),next=nextHeader===""?null:Number(nextHeader),end=Number(response.headers.get("x-presentation-end-offset"));
          if(!Number.isSafeInteger(end)||end<=offset||end>offset+1600||next!==null&&next!==end)throw Error("Invalid stream boundary");
          const bufferedPcm=encoding==="pcm_s16le";
          const streaming=window.SpeechStream.open(response,controller.signal,{bufferedPcm});
          const metadata={streaming,next,end,textHash:response.headers.get("x-presentation-text-sha256"),prefetch:true};
          if(!bufferedPcm)return metadata;
          // Play one verified PCM part through the media element. Transport
          // gaps and delayed browser timers cannot drain it mid-part.
          onBufferedPart?.(next);
          const completed=await streaming.done;
          if(controller.signal.aborted)throw new DOMException("Audio preparation ended", "AbortError");
          if(!completed.complete || !completed.blob?.size)throw Error("Audio stopped before it was ready. The reply is still available to read.");
          return {...metadata,blob:completed.blob,usingBlob:true};
        }
        const nextHeader=response.headers.get("x-presentation-next-offset"),next=nextHeader===""?null:Number(nextHeader);
        if(next!==null && (!Number.isSafeInteger(next)||next<=offset))throw Error("Invalid audio continuation");
        const endHeader=response.headers.get("x-presentation-end-offset"),end=endHeader?Number(endHeader):undefined;
        if(end!==undefined && (!Number.isSafeInteger(end)||end<=offset||end>offset+1600||next!==null&&next!==end))throw Error("Invalid audio segment boundary");
        const aheadHeader=response.headers.get("x-presentation-lookahead-offset"),lookahead=aheadHeader?Number(aheadHeader):undefined;
        if(lookahead!==undefined && (next===null || !Number.isSafeInteger(lookahead) || lookahead<=next || lookahead>offset+1600))throw Error("Invalid audio lookahead boundary");
        const prefetch=response.headers.get("x-presentation-prefetch")==="true";
        if(prefetch && end!==undefined && !controller.signal.aborted)onBufferedPart?.(next);
        const stream = response.body.getReader(); const chunks = []; let length = 0;
        while (true) {
          const {value, done} = await stream.read(); if (done) break;
          length += value.byteLength;
          if (length > 8 * 1024 * 1024) { await stream.cancel(); throw new Error("Audio exceeds playback limit"); }
          chunks.push(value);
        }
        const blob = new Blob(chunks, {type:"audio/wav"});
        const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()))]
          .map((byte) => byte.toString(16).padStart(2,"0")).join("");
        if (hash !== response.headers.get("x-audio-sha256")) throw new Error("Audio integrity check failed");
        return {blob,next,end,lookahead,textHash:response.headers.get("x-presentation-text-sha256"),prefetch};
      }finally{clearTimeout(deadline);}
    }
    function prefetchNext(selected,next=selected.next,ready=selected.prefetch){
      if(!ready || voiceSuspended || captureBusy || active!==selected || queuedPreparations.size || sessionMuted(selected.source))return;
      if(selected.source.kind!=="integrator_live"){
        if(next===null)return;
        const prepare=offset=>{
          const controller=new AbortController(),source=selected.source,waiting={controller,source,offset};
          waiting.result=requestAudio(source,offset,controller).then(value=>{
            waiting.buffered=!!value.blob&&(!value.streaming||value.usingBlob);
            if(waiting===prefetched)verifyBufferedContinuation(active);
            return {value};
          },error=>({error}));
          return waiting;
        };
        if(!prefetched)prefetched=prepare(next);
        // Only finalized WAV Live readings advertise the second exact boundary.
        // Two future preparations share the existing server's two slots; no
        // guessed offsets, recursive expansion or retry of an unknown attempt.
        if(selected.lookahead!==undefined && !selected.streaming && !prefetched.following
            && prefetched.source?.id===selected.source.id && prefetched.source.revision===selected.source.revision
            && prefetched.offset===selected.next){
          const waiting=prefetched;waiting.following=prepare(selected.lookahead);
          waiting.abortFollowing=()=>waiting.following?.controller.abort();
          waiting.controller.signal.addEventListener("abort",waiting.abortFollowing,{once:true});
        }
        return;
      }
      if(prefetched)return;
      if(!voiceEnabled || !canSpeakLive || !selected.auto || selected.interrupted || selected.segmentEnded)return;
      const owned=generation,waiting={controller:new AbortController(),owner:selected.source,ahead:true};prefetched=waiting;
      waiting.selection=(async()=>{
        const source=await liveSpeech?.next() || liveSpeech?.continuation(selected.source);
        if(!source || prefetched!==waiting || active!==selected || generation!==owned || voiceSuspended || captureBusy || selected.interrupted || sessionMuted(source)){
          liveSpeech?.unsent(source);waiting.controller.abort();if(prefetched===waiting)prefetched=undefined;return;
        }
        if(source.kind==="integrator_live" && !liveSpeech?.admit(source)){prefetched=undefined;return;}
        waiting.source=source;waiting.offset=source.speech_start||0;
        // Own exactly one preparation, including its failed/uncertain result.
        waiting.result=requestAudio(source,waiting.offset,waiting.controller).then(value=>({value}),error=>({error}));
      })().catch(()=>{waiting.controller.abort();if(prefetched===waiting)prefetched=undefined;});
    }
    async function listenTo(source, offset = 0, chain) {
      if(workspaceAudioScope!==undefined&&sessionMuted(source))return;
      window.PcmSpeech?.unlock();
      if(captureBusy)return;
      const key=preparationKey(source,offset);
      const prepared=queuedPreparations.get(key) || (prefetched?.source?.id===source.id && prefetched.source.revision===source.revision && prefetched.offset===offset?prefetched:undefined);
      const proof=prepared?.continuationCheck;
      const continuationCheck=chain===active && chain?.segmentEnded && proof?.previous===chain
        && proof.generation===generation && proof.binding===binding && !document.hidden
        && window.navigator?.onLine!==false ? proof : undefined;
      const following=prepared?.following;
      if(following)prepared.controller.signal.removeEventListener("abort",prepared.abortFollowing);
      if(prepared===prefetched)prefetched=undefined;
      queuedPreparations.delete(key);
      if(!chain?.queued){
        cancelPreparedMessage(source);
        for(let n=voiceQueue.length-1;n>=0;n--){
          if(sameMessage(voiceQueue[n],source))removeQueued(n);
        }
      }
      if(!chain?.queued){interruptedTurns.delete(source.native_turn);skippedMessages.delete(messageKey(source));liveSpeech?.continueSource(source);voiceSuspended=false;}
      stop();
      // Transfer the already owned successor after teardown, which must still
      // cancel every preparation on ordinary Stop/Skip/source replacement.
      if(following)prefetched=following;
      if(voiceEnabled)voiceBusy=true;
      const owned = generation;
      active = {source, offset, generation:owned, auto:false, focusVersion:chain?.focusVersion ?? focusVersion,queued:!!chain?.queued};
      const selected = active;playbackLabels();
      $("#conversation-player").hidden = false;
      $("#conversation-playing").textContent = source.kind.startsWith("integrator_") ? "Conversation reply" : source.label;
      presentState({playback:"preparing"});
      audioState("Preparing audio…"); toggle.disabled = true;
      requestAbort = prepared?.controller||new AbortController();
      const controller = requestAbort;playbackLabels();
      try {
        const onBufferedPart=next=>{
          if(source.kind!=="integrator_live" && enabled && playbackAllowed())prefetchNext(selected,next,true);
        };
        if(prepared){
          prepared.onBufferedPart=onBufferedPart;
          if(prepared.bufferedNext!==undefined)onBufferedPart(prepared.bufferedNext);
        }
        const result=prepared?await prepared.result:{value:await requestAudio(source,offset,controller,onBufferedPart)};
        if(result.error)throw result.error;
        const {blob,...metadata}=result.value;
        if(active!==selected || generation!==owned)return;
        Object.assign(selected,metadata);
        blobUrl = selected.streaming?.url || URL.createObjectURL(blob);
        selected.streaming?.onError(()=>stopFailedSpeech(selected,"This reply’s audio stopped. You can still read it or listen again."));
        selected.streaming?.onDecoderError?.(()=>{if(active===selected)void audioDecodeFailed(selected);});
        if(active!==selected)return;
        audio.src = blobUrl;
        toggle.disabled = false;
        return await startPlayback(continuationCheck);
      } catch (e) {
        if (active !== selected || generation !== owned) return;
        stop();voiceBusy=false;
        if (e.status === 401 || e.status === 403) failed(e);
        $("#conversation-state").textContent = e.name === "AbortError" ? "Audio preparation ended. Your text replies remain available."
          : e.message || "Audio unavailable. Text replies remain available.";
        return {failed:true,generation};
      } finally { if (requestAbort === controller) requestAbort = undefined;playerStatus(); }
    }
    audio.addEventListener("error",()=>{void audioDecodeFailed();});
    audio.addEventListener("nativefocusloss",()=>pause("audio-focus"));
    audio.addEventListener("pause",()=>{if(active && !active.verifying && !requestAbort){playLabel("Play audio");playerStatus();presentState({playback:undefined});}});
    audio.addEventListener("timeupdate",()=>{followPlayback();verifyBufferedContinuation(active);});
    audio.addEventListener("playing",()=>{
      if(active && !active.verifying && !audio.muted){if(active.queued)timing?.source(active.source,true);playLabel("Pause audio");playerStatus();presentState({playback:"playing"});}
    });
    audio.addEventListener("ended", async () => {
      if (!audio.ended || !active || active.segmentEnded || active.verifying || !active.auto || !playbackAllowed() || !enabled) return;
      presentState({playback:undefined});
      const selected=active, owned=generation;selected.segmentEnded=true;playbackLabels();
      rememberLiveCursor(liveSpeech?.ended(selected.source,selected.offset,selected.textEnd));
      rememberPosition();
      if (selected.next !== null) {
        audioState("A short pause before continuing…");
        // A verified buffered part already contains its own speech cadence.
        // Leave a short handoff while the same reply's next part is prepared.
        const bufferedBoundary = (!selected.streaming || selected.usingBlob)
          && selected.source.kind !== "integrator_live" && selected.end === selected.next;
        if(await waitForSpeech("chunk",selected.source,bufferedBoundary?60:speechGaps.chunk)){
          const result=await listenTo(selected.source,selected.next,selected);
          if(result?.failed && result.generation===generation && !active)nextSpokenReply("reply",selected.source);
        }
        return;
      }
      audioState("End of reply."); playLabel("Play audio again");
      if(selected.source.kind!=="native_question" || selected.finished){nextSpokenReply(selected.source.kind==="integrator_live"?"chunk":"reply",selected.source);return;}
      selected.finished=true;
      try {
        await part(selected.source, selected.offset);
        if(active!==selected || generation!==owned || !selected.auto || !playbackAllowed() || !enabled || focusVersion!==selected.focusVersion)return;
        if(!voiceEnabled)selectFocus({source:selected.source.id,revision:selected.source.revision,context_only:true},selected.source.label);
        audioState("Question finished. Press Talk to answer or change topic.");
      } catch (_) {
        if(active===selected && generation===owned)stop("This question changed. Refresh before answering.");
      }
      if(voiceEnabled && generation===owned)nextSpokenReply("question",selected.source);
    });
    toggle.addEventListener("click", () => {
      window.PcmSpeech?.unlock();
      if(nativeEnabled&&nativeVoiceSession?.active){if(nativeVoiceSession.paused)nativeVoiceSession.resume();else nativeVoiceSession.pause();return;}
      if(captureBusy)return;
      if (audio.paused) { cancelSpeechWait();continueSpeech();voiceSuspended=false;voiceStatus();if (audio.ended) audio.currentTime = 0; startPlayback(); }
      else pause("player");
    });
    $("#conversation-open").addEventListener("click", () => setMode(true));
    $("#conversation-back").addEventListener("click", () => setMode(false));
    $("#conversation-refresh").addEventListener("click", () => refresh(true));
    document.addEventListener("visibilitychange", () => {
      if(document.hidden){if(!playbackAllowed())pause("hidden");return;}
      if(standalone && voiceEnabled && !voiceSuspended && enabled && ready){
        // A browser suspension preserves intent; a human pause clears active.auto.
        if(active?.auto && audio.ended && !active.segmentEnded)audio.dispatchEvent?.(new Event("ended"));
        else if(active?.auto && audio.paused && blobUrl && !active.verifying)startPlayback();
        else if(!active && !speechWait){voiceBusy=false;drainVoice();}
      }
      refresh(true);
    });
    window.addEventListener("pagehide", event => {
      if(event?.persisted && standalone && voiceEnabled && !voiceSuspended)return;
      pause("pagehide");stop();clearFiles();
    });
    window.addEventListener("pageshow", event => {
      if(event?.persisted && enabled && ready){
        if(active?.auto && audio.paused && blobUrl && !active.verifying && playbackAllowed())startPlayback();
        refresh(true);
      }
    });
    window.addEventListener("offline", () => {
      presentState({connected:false});
      if(!standalone || !voiceEnabled || voiceSuspended)pause("offline");
      $("#conversation-state").textContent = "Offline. Replies already loaded remain readable.";
    });
    window.addEventListener("online", () => {
      if (enabled && ready && playbackAllowed()) {
        if(active?.auto && audio.ended && !active.segmentEnded)audio.dispatchEvent?.(new Event("ended"));
        else if(active?.auto && audio.paused && !audio.ended && blobUrl && !active.verifying)startPlayback();
        refresh(true);
      }
    });
    const mediaActions={
      play:()=>{if(nativeEnabled&&nativeVoiceSession?.active){nativeVoiceSession.resume();return;}voiceSuspended=false;voiceStatus();if(active && blobUrl){continueSpeech();startPlayback();}else {enableVoice();drainVoice();}},
      pause:()=>pause("media-session"),stop:()=>disableVoice()
    };
    window.NativeSpeechAudio?.setControls?.(mediaActions);
    const mediaSession=standalone && !window.NativeSpeechAudio?.backgroundPlayback?window.navigator?.mediaSession:undefined;
    if(mediaSession){
      for(const [action,handler] of Object.entries(mediaActions))try{mediaSession.setActionHandler(action,handler);}catch{}
    }
    telegram?.onEvent?.("deactivated", pause);
    telegram?.BackButton?.onClick?.(() => setMode(false));
    if(standalone)$("#conversation-back").hidden=true;
    if(readOnly){document.body.classList.toggle("monitor-mode",true);$("#conversation-sent").open=true;}
    if(standalone&&!readOnly&&microphone)legacyVoiceSession=window.ContinuousConversation?.create({
      headers,getBinding:()=>binding,getQuestions:()=>canLimitCaptureQuestions?requestControls.captureQuestions():undefined,
      getTranscriptionProvider:()=>voiceChoice==='conversation'?'openai':'current',
      prepareReconnect:originals=>microphone.prepareReconnect(originals,true),
      getPlayback:()=>playbackContext(true),retain:original=>microphone.retainContinuous(original),commit:original=>microphone.commitContinuous(original),
      onInterrupt:beginVoiceCapture,onCaption:text=>voiceMode?.update({caption:text}),onTiming:(id,stage,detail)=>{timing?.mark(id,stage,detail);if(stage==='handoff')voiceMode?.update({handoff:{...detail,id}});},
      onSent:(value,sourceBinding)=>{
        if(sourceBinding===binding)updateAvatarAdmission(inputs.get(value.id)?.value || value,true);
      },
      onReview:originals=>{void microphone.reviewContinuous(originals);},
      onState:value=>{
        if(!voiceModePrevious?.continuous)return;
        captureBusy=value.floor;presentState({capture:value.floor?'recording':value.starting?'permission':'idle'});
        voiceMode?.update({continuousState:value});if(!captureBusy)drainVoice();
      }
    });
    voiceSession=legacyVoiceSession;
    if(standalone&&!readOnly&&microphone)providerVoiceSession=window.NativeConversation?.create({
      headers,getBinding:()=>binding,getQuestions:()=>canLimitCaptureQuestions?requestControls.captureQuestions():undefined,
      prepareReconnect:originals=>microphone.prepareReconnect(originals),retain:original=>microphone.retainContinuous(original),reviewOriginal:original=>microphone.reviewNativeContinuous(original),release:(original,hash)=>microphone.releaseContinuous(original,hash),
      onReview:originals=>{if(!voiceMode?.active)void microphone.reviewContinuous(originals);},
      onInterrupt:beginVoiceCapture,onCaption:text=>voiceMode?.update({caption:text}),onUtterance:foregroundCard,
      onHandoff:handoff=>voiceMode?.update({handoff}),onTiming:(id,stage)=>timing?.native?.(id,stage),
      onState:value=>{if(!voiceModePrevious?.continuous)return;if(value.pauseReason)timing?.pauseRequested?.(value.pauseReason);captureBusy=value.floor;
        presentState({capture:value.floor?'recording':value.starting?'permission':'idle',...(value.playback?{playback:value.playback}:{})});
        voiceMode?.update({continuousState:value});
        if(value.playback)audioState(value.playback==='playing'?'Playing voice conversation':value.playback==='paused'?'Paused voice conversation':'Waiting for voice');
        else playerStatus();}
    });
    if(standalone&&!readOnly&&microphone)codexVoiceSession=window.CodexConversation?.create({
      headers,getBinding:()=>binding,
      onCaption:text=>voiceMode?.update({caption:text}),
      onItem:value=>{
        if(!value||!value.item||!['user','assistant'].includes(value.item.role)||typeof value.item.text!=='string'||value.item.text.length>16384)return;
        const key='codex:'+value.visit+':'+value.item.id;
        let card=foregroundCards.get(key);
        if(!card){const box=node('article',undefined,'reply'),body=node('div',undefined,'reply-text'),status=node('p',undefined,'reply-status'),time=node('time',undefined,'message-time');
          box.append(node('h3',value.item.role==='user'?'You · voice':'Voice conversation'),status,body,time);card={box,body,status,time};foregroundCards.set(key,card);$('#conversation-answers').append(box);}
        setReplyText(card.body,value.item.text);card.status.textContent='Native voice transcript · words may differ from what was heard.';
        const observed=new Date((value.item.observed_at||value.observed_at)*1000).toISOString();messageTime(card.time,observed);placeInTimeline(card.box,key,observed);
      },
      onRecovery:values=>{
        const panel=$('#conversation-codex-recovery');if(!panel)return;
        panel.replaceChildren();const selected=values.filter(value=>value.binding===binding);panel.hidden=!selected.length;
        panel.append(node('summary',`${selected.length} audio cop${selected.length===1?'y':'ies'} to review`),node('p','These audio copies are still on this device. Download a copy for review or use the available saving controls after voice mode stops.','note'));
        for(const original of selected){
          const partial=original.captureStop==='interrupted_prefix';
          const row=node('div',undefined,'conversation-tools'),label=node('span',`${partial?'Recovered audio prefix':'Voice recording'} · ${Math.ceil((original.blob.size-44)/32000)}s · local copy${partial?' · ending may be missing':''}`);
          const retry=node('button','Try saving audio'),save=node('button','Download copy'),discard=node('button','Remove device copy');
          for(const button of [retry,save,discard])button.type='button';
          retry.title='Save this same original; never send the conversation again';
          discard.title='Discard this local copy; accepted work continues';
          retry.addEventListener('click',async()=>{retry.disabled=true;try{await codexVoiceSession.retry(original);}catch{label.textContent=partial?'Recovered audio prefix not confirmed; your local copy is kept and its ending may be missing.':'Original not confirmed; your local audio is kept.';}finally{retry.disabled=false;}});
          save.addEventListener('click',()=>{const url=URL.createObjectURL(original.blob),link=node('a');link.href=url;link.download='voice-'+original.codex_visit+'-'+original.ordinal+'.wav';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
          discard.addEventListener('click',async()=>{discard.disabled=true;try{await codexVoiceSession.discard(original);}catch{label.textContent='Local audio is kept; its capture may still be finishing in another page.';}finally{discard.disabled=false;}});
          row.append(label,retry,save,discard);panel.append(row);
        }
      },
      onState:value=>{if(voiceChoice!=='codex')return;if(voiceEngine)voiceEngine.disabled=!!codexVoiceSession?.active||!!voiceMode?.active;
        if(!voiceModePrevious?.continuous)return;captureBusy=false;voiceMode?.update({continuousState:value});presentState({capture:value.starting?'permission':'idle',playback:value.playback,outputLevel:value.outputLevel,inputLevel:value.inputLevel},false);}
    });
    if(standalone&&!readOnly&&microphone&&window.PublicLiveConversation?.supported()){
      const panel=node('details');panel.id='conversation-public-live-recovery';panel.hidden=true;
      panel.setAttribute('aria-label','Voice audio recovery');$('#conversation-compose-notices .composer-notice-panel').prepend(panel);
      let speech;const retained=[];
      function renderPublicTranscript(values,previous,replaceVisit){
        const changed=new Map();
        let current=previous;
        for(const value of values){
          const event=value?.item,role=event?.type==='session.input_transcript.delta'?'user':event?.type==='session.output_transcript.delta'?'assistant':undefined;
          if(!role||typeof event.delta!=='string'||!event.delta||event.delta.length>32768)continue;
          const observed=value.observed_at||new Date().toISOString();
          for(let offset=0;offset<event.delta.length;){
            if(!current||current.visit!==value.visit||current.role!==role||current.text.length>=16000){
              const key='live:'+value.visit+':'+(value.history?String(value.source_order).padStart(8,'0'):event.event_id)+':'+offset;
              const box=node('article',undefined,'reply'),body=node('div',undefined,'reply-text'),status=node('p',undefined,'reply-status'),time=node('time',undefined,'message-time');
              box.append(node('h3',role==='user'?'You · voice':'Voice conversation'),status,body,time);
              status.textContent='Voice transcript';status.title='Automatic transcript; may be partial or differ from speech.';
              current={key,box,body,time,text:'',visit:value.visit,role,binding};retained.push(current);
            }
            const part=event.delta.slice(offset,offset+16000-current.text.length);offset+=part.length;current.text+=part;
            changed.set(current,observed);
          }
        }
        if(replaceVisit&&changed.size){
          for(let i=retained.length-1;i>=0;i--){
            const card=retained[i];
            if(card.visit===replaceVisit&&!changed.has(card)){card.box.remove();retained.splice(i,1);}
          }
        }
        let size=retained.reduce((n,v)=>n+v.text.length,0);
        while(retained.length>64||size>128*1024){
          const old=retained.shift();size-=old.text.length;changed.delete(old);old.box.remove();
        }
        for(const [card,observed] of changed){
          setReplyText(card.body,card.text);
          if(!card.box.parentNode)$('#conversation-answers').append(card.box);
          messageTime(card.time,observed);placeInTimeline(card.box,card.key,observed);
        }
        return current;
      }
      publicLiveSession=window.PublicLiveConversation.create({headers,getBinding:()=>binding,getBackend:()=>voiceChoice==='gpt-live-native'?'native':undefined,
        onUsage:value=>{if(value.binding===binding)liveUsage?.observe(value);},
        onCaption:text=>{if(isPublicLive()&&voiceMode?.active)voiceMode.update({caption:text});},
        onItem:value=>{speech=renderPublicTranscript([value],speech);},
        onHistoryItems:values=>{
          const visit=values[0]?.visit;
          if(renderPublicTranscript(values,undefined,visit)&&speech?.visit===visit)speech=undefined;
        },
        onRecovery:values=>{
          panel.replaceChildren();const selected=values.filter(value=>value.binding===binding);panel.hidden=!selected.length;
          panel.append(node('summary',`${selected.length} audio cop${selected.length===1?'y':'ies'} to review`),node('p','These recordings are still on this device. Saving may be pending or unconfirmed. After voice mode stops, you can try saving the audio, download a copy, or remove the device copy. This does not repeat your messages or restart work.','note'));
          for(const original of selected){
            const row=node('div',undefined,'conversation-tools'),label=node('span',original.downloadOnly?'Audio fragment · download to review':original.captureStop?'Recovered audio prefix · ending may be missing':'Voice recording · local copy');
            const retry=node('button','Try saving audio'),save=node('button','Download copy'),discard=node('button','Remove device copy');
            for(const button of [retry,save,discard])button.type='button';
            retry.title='Retain this same original; never resend speech or work';
            retry.addEventListener('click',async()=>{retry.disabled=true;try{await publicLiveSession.retry(original);}catch{label.textContent='Original not confirmed; your local copy is kept.';}finally{retry.disabled=false;}});
            save.addEventListener('click',()=>{const url=URL.createObjectURL(original.blob),link=node('a');link.href=url;link.download='voice-'+original.voice_visit+'-'+original.ordinal+(original.downloadOnly?'-'+original.id:'')+'.wav';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
            discard.addEventListener('click',async()=>{discard.disabled=true;try{await publicLiveSession.discard(original);}catch{label.textContent='Local audio is kept; capture may still be finishing in another page.';}finally{discard.disabled=false;}});
            row.append(label,...(original.downloadOnly?[save]:[retry,save,discard]));panel.append(row);
          }
        },
        onState:value=>{
          for(let i=retained.length-1;i>=0;i--)if(retained[i].binding!==binding){retained[i].box.remove();retained.splice(i,1);speech=undefined;}
          if(!isPublicLive())return;if(voiceEngine)voiceEngine.disabled=!!publicLiveSession?.active||!!voiceMode?.active;
          if(!voiceModePrevious?.continuous)return;captureBusy=false;voiceMode?.update({continuousState:value});presentState({capture:value.starting?'permission':'idle',playback:value.playback,outputLevel:value.outputLevel,inputLevel:value.inputLevel},false);
        }
      });
    }
    nativeVoiceSession=providerVoiceSession;
    if(standalone && !readOnly)voiceMode=window.ConversationVoiceMode?.mount({
      portrait:$("#conversation-companion .avatar-surface")||$("#conversation-companion pre"),onReview:restore=>pendingNavigation?.open(restore),getAttention:()=>pendingNavigation?.count||0,canEnter:()=>!!microphone && !microphone.ownsSend() && !captureBusy && (!continuousEnabled||!!voiceSession&&(nativeEnabled?microphone.canStartNative():microphone.canStartContinuous(voiceChoice==='conversation'))),
      canStart:()=>continuousEnabled?!!voiceSession&&!voiceSession.active&&(nativeEnabled?microphone.canStartNative():microphone.canStartContinuous(voiceChoice==='conversation')):!!microphone && !microphone.ownsSend() && !captureBusy && !voiceBusy && !speechWait,
      onEnter:()=>{
        avatarVoiceAdmissions.clear();
        if(voiceEngine)voiceEngine.disabled=true;
        voiceModePrevious={enabled:voiceEnabled,suspended:voiceSuspended,continuous:continuousEnabled};
        if(continuousEnabled)microphone.continuousOwner(true);
        conversationOnly=true;stop();audioFilterChanged();enableVoice();
      },
      onSpeak:({avatarEntry=false}={})=>voiceModePrevious?.continuous?
        (voiceSession===publicLiveSession?publicLiveSession?.start({avatarEntry}):voiceSession?.start()):
        microphone?.startConversation(),
      canReconnect:()=>nativeEnabled||voiceChoice==='conversation'&&!microphone.ownsSend()&&voiceSession?.canReconnect(),
      onReconnect:()=>{
        if(nativeEnabled&&!nativeVoiceSession?.active){enableVoice();return nativeVoiceSession?.reconnect();}
        if(voiceChoice==='conversation'&&!microphone.ownsSend()&&voiceSession?.canReconnect())return voiceSession.reconnect();
      },
      onResumeAudio:()=>{if(nativeEnabled&&nativeVoiceSession?.active){enableVoice();nativeVoiceSession.resume();}},
      onSuspend:()=>voiceSession?.hold('Microphone paused. Review your recording before speaking again.'),
      onLeave:({returnToText=false}={})=>{
        avatarVoiceAdmissions.clear();
        const direct=voiceModePrevious?.continuous, owner=binding, observed=inputGeneration,publicVoice=voiceSession===publicLiveSession;
        let held;
        if(direct){held=voiceSession?.hold();microphone.continuousOwner(false);void microphone.reviewContinuous(voiceSession?.originals||[]);captureBusy=false;}
        else held=microphone?.hold();conversationOnly=false;
        if(voiceModePrevious?.enabled){voiceSuspended=voiceModePrevious.suspended;voiceStatus();}
        else disableVoice();
        voiceModePrevious=undefined;presentState({outputLevel:0},false);audioFilterChanged();companion?.update({});
        if(voiceEngine)voiceEngine.disabled=!!voiceSession?.active;
        if(returnToText&&direct){
          const reconcile=()=>{
            if(binding===owner&&inputGeneration===observed&&!document.hidden&&!voiceMode?.active){
              void refresh(true);
              if(publicVoice)void publicLiveSession?.reconcileHistory?.().catch(()=>{});
            }
          };
          // Show received voice work immediately, then pick up anything that
          // settled during close. These are reads and do not hold the draft.
          reconcile();
          if(typeof held?.then==='function')void held.then(reconcile,reconcile);
        }
        return held;
      }
    });
    setMode(initialMode(), true, false);
    return {refresh, pause, identity:value=>hostSurface?.identity(value), stop:disableVoice,
      unauthenticated() { hostSurface?.disconnect();ready=false; failed({status:401,message:document.documentElement.dataset.sharedAuth==='true'?"Sign in again to reconnect.":"Open your conversation access file to reconnect."}); },
      authenticated() { ready = true; $("#conversation-open").disabled = false; }};
  }
  return {mount};
})();
