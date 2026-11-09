// Actual MIT editor/Canvas2D and App API/storage; no providers or real accounts.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{}),args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1200,height:900},reducedMotion:'reduce'}),errors=[];
  page.setDefaultTimeout(5000);page.on('pageerror',e=>{errors.push(e.message);console.error('Browser error:',e.message);});page.on('dialog',dialog=>dialog.accept());
  // Browser interaction proof is synthetic; mounted provider/cache ownership is
  // covered by dashboard_voice_studio_preview_api.py, without paid auditions.
  await page.addInitScript(()=>{
   window.testVoicePlays=0;const nativePlay=HTMLMediaElement.prototype.play;HTMLMediaElement.prototype.play=function(...args){testVoicePlays++;return nativePlay.apply(this,args);};
   const create=URL.createObjectURL.bind(URL),revoke=URL.revokeObjectURL.bind(URL);window.testVoiceURLs=new Set();
   URL.createObjectURL=blob=>{const url=create(blob);if(blob.type==='audio/wav')testVoiceURLs.add(url);return url;};
   URL.revokeObjectURL=url=>{testVoiceURLs.delete(url);return revoke(url);};
  });
  const previewStates=new Map();let previewPosts=[],deferPreview=false,unknownPreview=false,blockedPreview,lastPreviewAudio;
  await page.route('**/api/interaction/avatars/voice',async route=>{
   const response=await route.fetch(),value=await response.json();
   if(route.request().method()==='GET')value.audition_available=true;
   await route.fulfill({response,json:value});
  });
  await page.route('**/api/interaction/avatars/voice/previews',async route=>{
   const actor=route.request().headers()['x-test-actor'];if(!previewStates.has(actor))previewStates.set(actor,{generation:0,batches:[]});const previewState=previewStates.get(actor);
   if(route.request().method()==='GET'){await route.fulfill({json:previewState});return;}
   const body=route.request().postDataJSON();previewPosts.push(body);
   if(body.action==='prepare_sample'){
    const profile=body.profile;const row={id:body.id,generation:++previewState.generation,createdAt:Date.now(),phase:'prepared',passage:body.passage,
     choices:{sample:{profile,delivery:body.delivery}},renders:{sample:{state:'prepared'}}};
    previewState.batches.push(row);await route.fulfill({json:row});return;
   }
   const row=previewState.batches.find(r=>r.id===body.id);
   if(body.action==='cancel'){await route.abort();return;}
   if(body.action==='audio'){
    if(row.passage==='Expires while loading.'){row.renders[body.slot].audio_state='expired';await route.fulfill({json:{batch:row,audio:null,audio_state:'expired'}});return;}
    if(deferPreview){blockedPreview={route,row,slot:body.slot};return;}
    await route.fulfill({json:{batch:row,audio:row.renders[body.slot].state==='rendered'?lastPreviewAudio:null}});return;
   }
   if(body.action==='render'){
    if(deferPreview){if(row.renders[body.slot].state!=='rendered')row.renders[body.slot]={state:'intent'};blockedPreview={route,row,slot:body.slot};return;}
    if(unknownPreview){row.renders.sample={state:'unconfirmed'};await route.abort();return;}
    row.renders[body.slot]={state:'rendered',outcome:{receipt:{provider_receipt:{usage:{seconds:2},first_pcm_millis:120}}}};
    const wav=Buffer.alloc(4844);wav.write('RIFF');wav.writeUInt32LE(4836,4);wav.write('WAVEfmt ',8);wav.writeUInt32LE(16,16);wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);wav.writeUInt32LE(24000,24);wav.writeUInt32LE(48000,28);wav.writeUInt16LE(2,32);wav.writeUInt16LE(16,34);wav.write('data',36);wav.writeUInt32LE(4800,40);
    lastPreviewAudio={mime:'audio/wav',data:wav.toString('base64')};await route.fulfill({json:{batch:row,audio:lastPreviewAudio}});return;
   }
   if(body.action==='retire'){previewState.batches=previewState.batches.filter(r=>r.id!==body.id);previewState.generation++;await route.fulfill({json:previewState});return;}
   throw Error('Unexpected preview write '+body.action);
  });
  const origin=process.argv[2];
  if(process.env.OUTPUT_HUD_ONLY==='1'){
   const bootstrap=await page.request.get(origin+'/assets/avatar-workshop/experiments/school-avatar-quest/presentation.mjs');
   assert.equal(bootstrap.status(),200,'Pre-paint bootstrap must use an admitted static asset suffix');
   await page.goto(origin);
   await page.evaluate(()=>{document.documentElement.dataset.stylePolicy='authored';document.body.classList.add('standalone-conversation');});
   await page.locator('#avatar-workshop-open').click();
   const editor=page.frameLocator('iframe');
   await editor.locator('html[data-presentation="navigator-hud"]').waitFor();
   assert((await page.locator('iframe').getAttribute('src')).includes('presentation=navigator-hud'));
   await editor.locator('.wardrobe-tile').first().waitFor();
   const output=process.env.QUALIFICATION_OUTPUT;assert(output&&path.isAbsolute(output)&&!fs.existsSync(output));fs.mkdirSync(output,{mode:0o700});
   for(const width of [1200,375,320]){
    await page.setViewportSize({width,height:860});
    await page.waitForTimeout(100);
    assert.equal(await editor.locator('html').evaluate(e=>e.scrollWidth>innerWidth),false,'Workshop fits '+width);
    const background=await editor.locator('#panel').evaluate(e=>getComputedStyle(e).backgroundColor);
    assert.equal(background,'rgb(18, 36, 48)','Actual wardrobe panel uses authored dark surface');
    if(width<=375)assert.equal(await editor.locator('#tabs').evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length),2,'Phone tabs keep readable labels in two columns');
    await page.screenshot({path:path.join(output,'workshop-'+width+'.png')});
   }
   await page.getByRole('button',{name:/^(Voice|Voces)$/,exact:true}).click();
   await page.locator('.voice-studio-card').first().waitFor();
   assert.equal(await page.locator('.voice-studio-card').first().evaluate(e=>getComputedStyle(e).borderRadius),'3px');
   for(const [width,height] of [[1200,860],[375,860],[320,860],[375,430]]){
    await page.setViewportSize({width,height});
    const geometry=await page.locator('.voice-studio-intro').evaluate(e=>{
     const box=e.getBoundingClientRect(),mark=e.querySelector('.voice-studio-mark').getBoundingClientRect(),heading=e.querySelector('div').getBoundingClientRect();
     return {width:box.width,height:box.height,markRight:mark.right,headingLeft:heading.left,headingBottom:heading.bottom,bottom:box.bottom,display:getComputedStyle(e).display,decoration:getComputedStyle(e,'::before').content};
    });
    assert.equal(geometry.display,'flex','Workshop title never inherits shell header grid');
    assert(geometry.markRight<=geometry.headingLeft,'Voice mark does not overlap title at '+width);
    assert(geometry.headingBottom<=geometry.bottom+1,'Title stays inside its content header');
    assert(['none','normal'].includes(geometry.decoration),'No identity shell decoration over workshop heading');
    assert.equal(await page.locator('.voice-studio').evaluate(e=>e.scrollWidth>e.clientWidth),false,'Voice studio fits '+width);
    const choice=page.locator('.voice-studio-voices button').first();
    await page.keyboard.press('Tab');await choice.focus();
    assert.equal(await choice.evaluate(e=>getComputedStyle(e).outlineStyle),'solid','Keyboard focus remains outside cut control');
    assert.equal(await choice.evaluate(e=>getComputedStyle(e,'::before').clipPath.startsWith('polygon(')),true,'Choice uses cut frame');
    assert.equal(await page.locator('.voice-studio-presets .control-icon').count(),3,'Style icons use device-independent geometry');
    await page.screenshot({path:path.join(output,'voice-studio-'+width+'x'+height+'.png')});
   }
   assert.equal(previewPosts.length,0,'Appearance never auditions or applies a voice');
   assert.equal(errors.length,0,errors.join('\n'));
   console.log('PASS authored workshop/voice sheets at desktop375/320; no overflow, auditions or activation');return;
  }
  if(process.env.OUTPUT_MOUTH_ONLY==='1'){
   await page.goto(origin);
   const input=process.env.AVATAR_MOUTH_DESIGN?JSON.parse(fs.readFileSync(process.env.AVATAR_MOUTH_DESIGN,'utf8')):null;
   const original=process.env.AVATAR_MOUTH_ORIGINAL?JSON.parse(fs.readFileSync(process.env.AVATAR_MOUTH_ORIGINAL,'utf8')).record.design:null;
   const result=await page.evaluate(async({input,original})=>{
    const {fresh}=await import('/assets/avatar-workshop/experiments/school-avatar-quest/model.mjs'),{prepare}=await import('/assets/avatar-workshop/renderer.mjs');
    const design=input||{...fresh(),body:'custom-model',characterStyle:'model/v1',avatarModel:{schema:'ascii-avatar-model/v1',id:'mouth-fixture',name:'Mouth fixture',nodes:[{id:'head',type:'ellipse',cx:288,cy:200,rx:100,ry:100,fill:'#ffffff'},{id:'anchor-mouth',type:'path',path:[['M',288,230]],fill:null,pivot:[288,230]},{id:'jaw',type:'ellipse',cx:288,cy:240,rx:55,ry:12,fill:'#00ffff',parent:'anchor-mouth',pivot:[288,230]}],animations:{calm:[]},anchors:{compact:[160,80,256,320]}}};
    const frozen=JSON.stringify(design),base=original||structuredClone(design);if(!original){base.avatarModel.nodes=base.avatarModel.nodes.filter(n=>n.id!=='anchor-mouth');delete base.avatarModel.nodes.find(n=>n.id==='jaw').parent;}
    let stills=0,mouthChanges=0;
    for(const width of [640,148]){
     const a=document.createElement('canvas'),b=document.createElement('canvas');a.style.width=b.style.width=width+'px';document.body.append(a,b);const old=prepare(a,base),paint=prepare(b,design);
     for(const cue of ['calm','curious','joy','sad','anger','uncertain','focus','welcome','sleep']){
      old.selectCue(cue);paint.selectCue(cue);paint.setSpeechLevel(0);
      for(let frame=0;frame<12;frame++){old(frame);paint(frame);if(a.toDataURL()!==b.toDataURL())throw Error('Adding an inert mouth anchor changed the authored drawing');stills++;}
      paint(0);const rest=b.toDataURL();if(!paint.setSpeechLevel(1))throw Error('Mouth anchor unavailable');paint(0);if(rest!==b.toDataURL())mouthChanges++;paint.setSpeechLevel(0);paint(0);if(rest!==b.toDataURL())throw Error('Speech release did not restore the exact authored expression');
     }a.remove();b.remove();
    }
    return {stills,mouthChanges,unchanged:JSON.stringify(design)===frozen,draft:design};
   },{input,original});
   assert.equal(result.stills,216);assert.equal(result.mouthChanges,18);assert(result.unchanged);assert.equal(errors.length,0,errors.join('\n'));
   await page.evaluate(async design=>{
    const write=async body=>{const r=await fetch('/api/interaction/avatars',{method:'POST',headers:{'X-Test-Actor':'100','X-Dashboard-CSRF':'test-action','Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)throw Error(await r.text());return r.json();};
    const id=crypto.randomUUID();await write({action:'save',id,design,parentId:null,generation:0});await write({action:'activate',id,generation:1});testAvatar.reset();testAvatar.bind('actor100');
   },result.draft);
   await page.locator('#conversation-companion canvas').waitFor();
   const read=()=>page.locator('#conversation-companion canvas').evaluate(c=>c.toDataURL());
   const still=await read();await page.evaluate(()=>testAvatar.speechLevel(1));assert.equal(await read(),still,'Reduced motion suppresses mouth motion');
   await page.emulateMedia({reducedMotion:'no-preference'});
   const transition=await page.evaluate(()=>{const c=document.querySelector('#conversation-companion canvas');testAvatar.speechLevel(0);const still=c.toDataURL();testAvatar.speechLevel(1);const open=c.toDataURL();testAvatar.speechLevel(0);return {still,open,rest:c.toDataURL()};});
   assert.notEqual(transition.open,transition.still);assert.equal(transition.rest,transition.still,'Host restores the current exact authored frame');
   const resume=await page.evaluate(()=>{const c=document.querySelector('#conversation-companion canvas'),pause=document.querySelector('#avatar-workshop-pause');testAvatar.speechLevel(1);const open=c.toDataURL();pause.click();const held=c.toDataURL();testAvatar.speechLevel(1);const still=c.toDataURL();pause.click();return {open,held,still,resumed:c.toDataURL()};});
   assert.notEqual(resume.open,resume.held);assert.equal(resume.held,resume.still);assert.equal(resume.resumed,resume.open,'Resume restores current held audio level without waiting for another output change');
   await page.locator('#avatar-workshop-pause').click();const paused=await read();await page.evaluate(()=>testAvatar.speechLevel(1));assert.equal(await read(),paused,'Explicit avatar pause suppresses live mouth movement');
   await page.locator('#avatar-workshop-pause').click();await page.evaluate(()=>testAvatar.speechLevel(1));await page.locator('#avatar-workshop-open').click();const wardrobe=await read();await page.evaluate(()=>testAvatar.speechLevel(1));assert.equal(await read(),wardrobe,'Wardrobe keeps the active portrait still');
   await page.evaluate(()=>{testAvatar.reset();testAvatar.speechLevel(1);testAvatar.bind('actor100');});await page.locator('#conversation-companion canvas').waitFor();
   const loaded=await page.evaluate(()=>{const c=document.querySelector('#conversation-companion canvas'),open=c.toDataURL();testAvatar.speechLevel(0);const rest=c.toDataURL();testAvatar.speechLevel(1);return {open,rest,resumed:c.toDataURL()};});assert.notEqual(loaded.open,loaded.rest);assert.equal(loaded.resumed,loaded.open,'A portrait loaded after a current output level arrives restores that same level');
   await page.evaluate(()=>{testAvatar.reset();testAvatar.bind('actor100');});await page.locator('#conversation-companion canvas').waitFor();
   const reset=await page.evaluate(()=>{const c=document.querySelector('#conversation-companion canvas'),rest=c.toDataURL();testAvatar.speechLevel(0);return {rest,after:c.toDataURL()};});assert.equal(reset.rest,reset.after,'Actor reset discards the old transient output level');
   console.log('PASS actual glyph renderer:216 authored large/compact frames unchanged at rest,18 cue/view mouth transitions restore exactly, no saved design mutation; no providers');return;
  }
  if(process.env.OUTPUT_ACTIVITY_ONLY==='1'){
   await page.goto(origin);await page.addScriptTag({url:origin+'/assets/webrtc-native-audio.js'});
   const result=await page.evaluate(async()=>{
    const context=new AudioContext({sampleRate:24000}),osc=context.createOscillator(),gain=context.createGain(),destination=context.createMediaStreamDestination(),audio=new Audio(),levels=[];
    gain.gain.value=0;osc.frequency.value=440;osc.connect(gain).connect(destination);osc.start();await context.resume();audio.srcObject=destination.stream;await audio.play();
    let observer;const until=async test=>{for(let i=0;i<100;i++){if(test())return;await new Promise(r=>setTimeout(r,30));}throw Error('Actual output activity not observed');};
    try{
     observer=await WebRtcNativeAudio.observe(destination.stream,{sessionSeconds:300,isPlaying:()=>!audio.paused&&!audio.muted,onActivity:value=>levels.push(value)});
     await until(()=>levels.length>=2);const silence=levels.every(v=>v===0);gain.gain.value=.2;await until(()=>levels.some(v=>v>.1));const speech=levels.at(-1);
     audio.muted=true;await until(()=>levels.at(-1)===0);const muted=levels.at(-1);audio.muted=false;await until(()=>levels.at(-1)>.1);
     gain.gain.value=0;await until(()=>levels.at(-1)===0);observer.close();const count=levels.length;await new Promise(r=>setTimeout(r,300));
     return {silence,speech,muted,afterClose:levels.length-count,stillPlaying:!audio.paused,nativeOwnerCreated:!!window.NativeSpeechAudio};
    }finally{observer?.close();audio.pause();audio.srcObject=null;osc.stop();for(const track of destination.stream.getTracks())track.stop();await context.close();}
   });
   assert(result.silence);assert(result.speech>.1);assert.equal(result.muted,0);assert.equal(result.afterClose,0);assert(result.stillPlaying,'Cosmetic observer close never pauses or replaces the player');assert.equal(result.nativeOwnerCreated,false);
   assert.equal(errors.length,0,errors.join('\n'));console.log('PASS actual Chromium remote-track activity: silent graph observes synthesized PCM/silence/mute, exports no PCM, closes without stopping existing playback; no microphone/provider/device hearing claim');return;
  }
  if(process.env.COMPACT_PREVIEW_ONLY==='1'){
   await page.goto(origin);await page.locator('#avatar-workshop-open').click();
   const editor=page.frameLocator('iframe'),panel=page.locator('.avatar-workshop-compact-preview');
   await editor.locator('#save').waitFor({state:'visible'});
   assert(await editor.locator('#preview-saved').isDisabled(),'Unsaved designs cannot masquerade as immutable revisions');
   await editor.locator('#save').click();
   await page.waitForFunction(()=>!document.querySelector('iframe').contentDocument.querySelector('#preview-saved').disabled);
   const snapshot=()=>page.evaluate(async()=>{const h={'X-Test-Actor':'100'},s=await(await fetch('/api/interaction/avatars',{headers:h})).json();return {state:s,record:await(await fetch('/api/interaction/avatars/'+s.editing,{headers:h})).json()};});
   const saved=await snapshot(),writes=[];page.on('request',r=>{if(r.method()!=='GET'&&r.url().includes('/api/'))writes.push(r.url());});
   await editor.locator('#preview-saved').click();await panel.waitFor({state:'visible'});
   assert.equal(await panel.getAttribute('data-revision'),saved.record.id);
   assert.equal(await panel.getAttribute('data-sha256'),saved.record.sha256);
   const pixels=await panel.locator('canvas').evaluate(c=>({url:c.toDataURL(),ink:c.getContext('2d').getImageData(0,0,c.width,c.height).data.some((v,i)=>i%4===3&&v)}));
   assert(pixels.ink,'Actual saved renderer paints nonempty compact canvas');
   assert(await page.locator('#conversation-companion pre').isVisible(),'Preview does not replace the previous active avatar');
   await page.waitForTimeout(450);assert.equal(await panel.locator('canvas').evaluate(c=>c.toDataURL()),pixels.url,'Reduced motion stays still');
   await panel.getByRole('button',{name:'Animate once',exact:true}).click();
   await page.waitForTimeout(4100);const ended=await panel.locator('canvas').evaluate(c=>c.toDataURL());
   await page.waitForTimeout(400);assert.equal(await panel.locator('canvas').evaluate(c=>c.toDataURL()),ended,'Explicit animation ends without a repeating timer');
   for(const [width,height] of [[375,812],[320,430]]){
    await page.setViewportSize({width,height});
    const bounds=await panel.evaluate(p=>({panel:p.getBoundingClientRect().toJSON(),close:p.querySelector('button:last-child').getBoundingClientRect().toJSON(),canvas:p.querySelector('canvas').getBoundingClientRect().toJSON(),dialog:p.parentElement.getBoundingClientRect().toJSON()}));
    assert.equal(Math.round(bounds.canvas.width),94);assert.equal(Math.round(bounds.canvas.height),90);
    assert(bounds.close.bottom<=bounds.dialog.bottom&&bounds.close.right<=width,'Compact preview controls remain reachable on short phones');
   }
   if(process.env.COMPACT_PREVIEW_SCREENSHOT)await page.screenshot({path:process.env.COMPACT_PREVIEW_SCREENSHOT});
   assert.deepEqual(await snapshot(),saved,'Reading/painting/animation preserve the immutable record and selection generation');assert.deepEqual(writes,[]);
   await panel.getByRole('button',{name:'Close preview',exact:true}).click();await panel.waitFor({state:'detached'});
   let release,arrived;const blocked=new Promise(resolve=>arrived=resolve);
   await page.route('**/api/interaction/avatars/'+saved.record.id,async route=>{const response=await route.fetch();arrived();await new Promise(resolve=>release=resolve);await route.fulfill({response});});
   await editor.locator('#preview-saved').click();await blocked;
   await page.evaluate(()=>{testActor='200';testAvatar.bind('actor200');});release();
   await page.waitForTimeout(200);assert.equal(await panel.count(),0,'Late old-actor record cannot reopen the preview');
   await page.unroute('**/api/interaction/avatars/'+saved.record.id);
   await page.evaluate(()=>{testActor='100';testAvatar.bind('actor100');});await page.locator('#avatar-workshop-open').click();
   await editor.locator('#preview-saved:not([disabled])').waitFor();
   await page.route('**/api/interaction/avatars/'+saved.record.id,async route=>{const response=await route.fetch(),record=await response.json();record.sha256='0'.repeat(64);await route.fulfill({response,json:record});});
   await editor.locator('#preview-saved').click();await editor.locator('#message').filter({hasText:'no coincide'}).waitFor();
   assert.equal(await panel.count(),0,'Hash mismatch never displays a claimed saved revision');
   await page.unroute('**/api/interaction/avatars/'+saved.record.id);
   await editor.locator('#preview-saved').click();await panel.waitFor({state:'visible'});
   await page.getByRole('button',{name:'Voice',exact:true}).click();assert.equal(await panel.count(),0,'Voice tab clears the portrait preview');
   assert.deepEqual(await snapshot(),saved);assert.deepEqual(writes,[]);assert.equal(errors.length,0,errors.join('\n'));
   console.log('PASS saved compact preview: exact immutable ID/hash, actual Canvas, finite animation/reduced motion, narrow phone controls, no writes/activation, stale actor refusal and hash mismatch; zero providers');return;
  }
  if(process.env.AVATAR_LOAD_RECOVERY_ONLY==='1'){
   // Isolate the host's retry from the editor's independent snapshot/get reads.
   // The full journey below exercises the real editor separately.
   await page.route('**/assets/avatar-workshop/experiments/school-avatar-quest/index.html',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><title>Host retry fixture</title>'}));
   await page.goto(origin+'?defer_bind=1');
   const before=await page.evaluate(async()=>{
    const {fresh}=await import('/assets/avatar-workshop/experiments/school-avatar-quest/model.mjs');
    const id=crypto.randomUUID(),write=async body=>{
     const r=await fetch('/api/interaction/avatars',{method:'POST',headers:{'X-Test-Actor':'100','X-Dashboard-CSRF':'test-action','Content-Type':'application/json'},body:JSON.stringify(body)});
     if(!r.ok)throw Error('Synthetic saved selection refused: '+await r.text());return r.json();
    };
    await write({action:'save',id,design:fresh(),parentId:null,generation:0});
    return write({action:'activate',id,generation:1});
   });
   let reads=0,recordReads=0,fail=true;const writes=[];
   await page.route('**/api/interaction/avatars/'+before.active,async route=>{recordReads++;await route.continue();});
   page.on('request',r=>{if(r.method()!=='GET'&&r.url().includes('/api/'))writes.push(r.url());});
   await page.route('**/api/interaction/avatars',async route=>{
    if(route.request().method()==='GET'){reads++;if(fail){await route.fulfill({status:503,json:{detail:'Synthetic temporary read failure'}});return;}}
    await route.continue();
   });
   await page.evaluate(()=>testAvatar.bind('actor100'));
   await page.waitForFunction(()=>document.querySelector('#avatar-workshop-status').textContent.includes('workshop'));
   assert.equal(await page.locator('.avatar-surface').getAttribute('aria-busy'),'false','Failed read is terminal, not perpetual loading');
   assert.equal(await page.locator('#conversation-companion pre').isVisible(),false,'A failed custom read never substitutes the default');
   await page.evaluate(()=>{testAvatar.bind('actor100');testAvatar.bind('actor100');});
   assert.equal(reads,1,'Ordinary polling does not retry a failed load');
   fail=false;await page.locator('#avatar-workshop-open').click();
   await page.locator('.avatar-surface[data-avatar-state="custom"]').waitFor();
   assert.equal(reads,2,'Explicit recovery reads the snapshot once');
   assert.equal(recordReads,1,'Explicit recovery loads the selected revision once');
   assert.equal(await page.locator('#avatar-workshop-status').textContent(),'');
   const after=await page.evaluate(async()=>{
    const r=await fetch('/api/interaction/avatars',{headers:{'X-Test-Actor':'100'}});return r.json();
   });
   assert.deepEqual(after,before,'Recovery keeps immutable versions, active pointer and generation');
   assert.deepEqual(writes,[],'Loading recovery never saves, activates or starts voice');
   assert.equal(errors.length,0,errors.join('\n'));
   console.log('PASS failed avatar load ends busy state; explicit workshop retry restores exact saved selection without writes/default flash/automatic retry; zero providers');return;
  }
  if(process.env.ARTISTIC_CUES_ONLY==='1'){
   const {fixture}=await import('file://'+path.resolve('tests/avatar_layer_model.mjs'));
   await page.goto(origin);await page.waitForFunction(()=>!document.querySelector('.avatar-surface').getAttribute('aria-busy')||document.querySelector('.avatar-surface').getAttribute('aria-busy')==='false');
   const proof=await page.evaluate(async model=>{
    const {fresh}=await import('/assets/avatar-workshop/experiments/school-avatar-quest/model.mjs');
    const design=fresh('model/v1');design.body='custom-model';design.avatarModel=model;
    design.gestures=['calm','curious','joy','sad','anger','uncertain','focus','welcome','sleep'].map(cue=>({id:'fixture-'+cue,name:cue,opening:1,bend:0,motion:'together',rig:'local/v1',cue}));design.activeGestureId='fixture-calm';
    const id=crypto.randomUUID(),read=async path=>(await fetch('/api/'+path,{headers:{'X-Test-Actor':'100'}})).json();
    const write=async body=>{const response=await fetch('/api/interaction/avatars',{method:'POST',headers:{'X-Test-Actor':'100','X-Dashboard-CSRF':'test-action','Content-Type':'application/json'},body:JSON.stringify(body)});if(!response.ok)throw Error('Synthetic save refused');return response.json();};
    await write({action:'save',id,design,parentId:null,generation:0});await write({action:'activate',id,generation:1});
    const before=await read('interaction/avatars'),record=await read('interaction/avatars/'+id);
    const box=document.querySelector('#conversation-companion');for(const cls of ['companion-caption','companion-phases']){const node=document.createElement('p');node.className=cls;box.append(node);}
    await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='/assets/companion.js';script.onload=resolve;script.onerror=reject;document.head.append(script);});
    window.testCompanion=ConversationCompanion.mount({onArtisticRest:rest=>{window.testReaction=rest;testAvatar.artisticRest(rest);}});
    window.testCue={id,design,before,record};testAvatar.reset();testAvatar.bind('actor100');return {id};
   },fixture);
   await page.locator('.workshop-portrait').waitFor();
   const writes=[];page.on('request',request=>{if(request.method()!=='GET'&&request.url().includes('/api/'))writes.push(request.url());});
   const pixel=()=>page.locator('.workshop-portrait').evaluate(c=>c.toDataURL());
   const original=await pixel();
   await page.evaluate(()=>{testCompanion.update({capture:'recording',playback:'playing',question:false});});
   assert.equal(await pixel(),original,'Mic/playback do not invent an artistic expression');
   await page.evaluate(()=>testCompanion.observe({schema:'telecodex.interaction-activity/v1',integrator_busy:true,sources:[]}));
   const working=await pixel();assert.notEqual(working,original,'Actual observed work selects the saved focus gesture');
   await page.evaluate(()=>testCompanion.observe({schema:'telecodex.interaction-activity/v1',sources:[]}));
   assert.equal(await pixel(),original,'Idle work restores saved art without a write');
   await page.evaluate(()=>testCompanion.update({question:true}));assert.equal(await page.evaluate(()=>testReaction),'curious','Question reaches the custom renderer (fixture has the same rest pixels for curious/calm)');
   await page.evaluate(()=>testCompanion.update({question:false}));assert.equal(await pixel(),original);
   await page.evaluate(()=>testCompanion.reply({id:'native:art',revision:'one',kind:'integrator_answer',observed_at:'2026-11-08T00:00:00Z',companion_hint:{rest:'focused',gesture:'none'}}));
   const focused=await pixel();assert.notEqual(focused,original,'A fresh focused hint selects the saved focus gesture');
   await page.waitForTimeout(250);assert.equal(await pixel(),focused,'Reduced motion keeps the chosen expression still');
   await page.evaluate(()=>testCompanion.reply({id:'native:old',revision:'one',kind:'integrator_answer',observed_at:'2026-11-07T00:00:00Z',companion_hint:{rest:'calm'}}));assert.equal(await pixel(),focused);
   await page.evaluate(()=>testAvatar.artisticRest('speaking'));assert.equal(await pixel(),original,'Unsupported artistic cue restores the saved default, without inventing lip sync');
   await page.locator('#avatar-workshop-pause').click();
   await page.evaluate(()=>testAvatar.artisticRest('focused'));const still=await pixel();
   await page.waitForTimeout(250);assert.equal(await pixel(),still);assert.equal(await page.locator('#avatar-workshop-pause').getAttribute('aria-pressed'),'true','Artistic changes do not resume manual pause');
   await page.evaluate(()=>{testAvatar.reset();testAvatar.artisticRest('focused');testAvatar.bind('actor100');});
   await page.locator('.avatar-surface[data-avatar-state="custom"]').waitFor();assert.equal(await pixel(),focused,'A cue retained before loading applies to the selected candidate');
   const unchanged=await page.evaluate(async()=>{
    const read=async path=>(await fetch('/api/'+path,{headers:{'X-Test-Actor':'100'}})).json();
    return JSON.stringify(await read('interaction/avatars'))===JSON.stringify(testCue.before)&&JSON.stringify(await read('interaction/avatars/'+testCue.id))===JSON.stringify(testCue.record);
   });assert(unchanged,'Transient expression selection never modifies saved revisions/pointers/generation');assert.deepEqual(writes,[]);
   await page.evaluate(()=>{testActor='200';testAvatar.bind('actor200');});assert.equal(await page.locator('.workshop-portrait').count(),0,'Actor change removes custom art and transient expression');
   assert.equal(errors.length,0,errors.join('\n'));console.log('PASS actual companion→custom raster cue, operational separation, reduced motion, old-source refusal, fallback, unchanged authenticated storage and actor reset; zero providers');return;
  }
  await page.goto(origin+'?workshop=voice&defer_bind=1');
  assert.equal(await page.locator('.avatar-workshop-dialog').count(),0,'Voice entry waits for authorized actor binding');
  await page.evaluate(()=>testAvatar.bind('actor100'));
  await page.locator('.avatar-workshop-dialog').waitFor({state:'visible'});
  await page.getByRole('region',{name:'Voice workshop'}).waitFor({state:'visible'});
  assert.equal(previewPosts.length,0,'Opening Voice never auditions a provider');
  await page.getByRole('button',{name:'Back to conversation',exact:true}).click();
  await page.goto(origin+'?workshop=unknown');assert.equal(await page.locator('.avatar-workshop-dialog').count(),0,'Unknown entry never opens a workshop');
  await page.goto(origin);await page.locator('#avatar-workshop-open').click();
  const editor=page.frameLocator('iframe');await editor.locator('#save').waitFor({state:'visible'});
  await editor.locator('#save').click();await editor.locator('#use-avatar').waitFor({state:'visible'});
  await page.waitForFunction(()=>!document.querySelector('iframe').contentDocument.querySelector('#use-avatar').disabled);
  assert.equal(await page.locator('#conversation-companion pre').isVisible(),true,'Save must keep previous avatar');
  await editor.locator('#use-avatar').click();await page.locator('.workshop-portrait').waitFor();
  assert.equal(await page.locator('#conversation-companion pre').isVisible(),false);
  const first=await page.locator('.workshop-portrait').evaluate(c=>c.toDataURL());
  await page.waitForTimeout(500);assert.equal(await page.locator('.workshop-portrait').evaluate(c=>c.toDataURL()),first,'Reduced motion stays still');
  await editor.locator('#cancel-workshop').click();await page.reload();await page.locator('.workshop-portrait').waitFor();
  assert.equal(await page.locator('.workshop-portrait').evaluate(c=>c.toDataURL()),first,'Saved active version reloads through API');
  await page.locator('#avatar-workshop-open').click();
  const model=path.resolve('dashboard/web/avatar-workshop/skills/ascii-avatar-author/assets/example.avatar.json');
  await editor.locator('main:not([inert])').waitFor();await editor.locator('#photo').setInputFiles(model);await page.waitForFunction(()=>!document.querySelector('iframe').contentDocument.querySelector('#save').disabled).catch(async e=>{console.error(await editor.locator('#message').textContent());throw e;});await editor.locator('#save').click();
  await page.waitForFunction(()=>!document.querySelector('iframe').contentDocument.querySelector('#use-avatar').disabled);
  assert.equal(await page.locator('.workshop-portrait').evaluate(c=>c.toDataURL()),first,'Editing a custom model preserves active catalogue avatar');
  await editor.locator('#use-avatar').click();
  await page.waitForFunction(old=>document.querySelector('.workshop-portrait').toDataURL()!==old,first);
  const custom=await page.locator('.workshop-portrait').evaluate(c=>c.toDataURL());
  await editor.locator('#versions').click();assert.equal(await editor.locator('#history button').count(),2);
  await editor.locator('#close-versions').click();
  await editor.locator('#tab-accessories').click();await editor.locator('[data-prop]').first().click();
  await editor.locator('#tab-details').click();await editor.locator('[data-prop]').first().click();await editor.locator('#save').click();
  await page.waitForFunction(()=>!document.querySelector('iframe').contentDocument.querySelector('#use-avatar').disabled);
  const saved=await page.evaluate(async()=>{const state=await(await fetch('/api/interaction/avatars',{headers:{'X-Test-Actor':'100'}})).json();return(await fetch('/api/interaction/avatars/'+state.editing,{headers:{'X-Test-Actor':'100'}})).json();});
  assert.equal(saved.design.gestures.find(g=>g.id===saved.design.activeGestureId).props.length,2,'Object and floating detail survive together');
  await page.evaluate(()=>window.testRejectActivation=true);await editor.locator('#use-avatar').click();
  await page.waitForFunction(()=>document.querySelector('iframe').contentDocument.querySelector('#message').textContent.includes('Synthetic activation refusal'));
  assert.equal(await page.locator('.workshop-portrait').evaluate(c=>c.toDataURL()),custom,'Failed activation keeps previous portrait');
  await page.evaluate(()=>window.testRejectActivation=false);
  const png=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=c.height=32;const x=c.getContext('2d');x.fillStyle='#e0b045';x.fillRect(0,0,32,32);x.fillStyle='#152a35';x.fillRect(8,8,16,16);return c.toDataURL().split(',')[1];});
  await editor.locator('#photo').setInputFiles({name:'generated-test.png',mimeType:'image/png',buffer:Buffer.from(png,'base64')});
  await page.waitForFunction(()=>document.querySelector('iframe').contentDocument.querySelector('#message').textContent.includes('Tu imagen ya está'));
  await editor.locator('#save').click();await page.waitForFunction(()=>!document.querySelector('iframe').contentDocument.querySelector('#use-avatar').disabled);
  await editor.locator('#use-avatar').click();await page.waitForFunction(old=>document.querySelector('.workshop-portrait').toDataURL()!==old,custom);
  let image=await page.locator('.workshop-portrait').evaluate(c=>c.toDataURL());
  // Both original drawing sizes and authored prop/detail tabs remain usable.
  for(const size of [{width:375,height:812},{width:320,height:740}]){
   await page.setViewportSize(size);
   assert(await editor.locator('#portrait').evaluate(c=>c.width>0&&c.height>0));
   assert(await editor.locator('#companion-name').isVisible());
   await editor.locator('#tab-accessories').click();await editor.locator('#tab-details').click();
   assert(await editor.locator('body').evaluate(b=>b.scrollWidth<=innerWidth+1),'Narrow workshop overflow');
  }
  image=await page.locator('.workshop-portrait').evaluate(c=>c.toDataURL());
  await editor.locator('body').evaluate(()=>scrollTo(0,0));
  if(process.env.WORKSHOP_SCREENSHOT)await page.screenshot({path:process.env.WORKSHOP_SCREENSHOT});
  await editor.locator('#cancel-workshop').click();assert.equal(await page.locator('.workshop-portrait').evaluate(c=>c.toDataURL()),image,'Cancel keeps current active version');
  await page.evaluate(()=>{for(const [key,value] of Object.entries({background:'#f4efdf',surface:'#fffaf0',text:'#352745',accent:'#654ba0'}))document.body.style.setProperty('--dm-'+key,value);});
  await page.locator('#avatar-workshop-open').click();await editor.locator('main:not([inert])').waitFor();
  assert.equal(await editor.locator('.stage.world').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(255, 250, 240)','Light surface follows the selected appearance');
  assert.equal(await editor.locator('.stage.world').evaluate(e=>getComputedStyle(e).color),'rgb(53, 39, 69)','Light text follows the selected appearance');
  await page.evaluate(()=>{document.body.style.setProperty('--dm-text','#112233');window.dispatchEvent(new Event('home-style:resolved'));});
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('iframe').contentDocument.querySelector('.stage.world')).color==='rgb(17, 34, 51)');
  await editor.locator('#tab-avatar').focus();await page.keyboard.press('ArrowRight');
  assert.equal(await editor.locator('#tab-expression').getAttribute('aria-selected'),'true','Original keyboard tab navigation works');
  await editor.locator('#versions').click();
  const downloading=page.waitForEvent('download');await editor.locator('#export').click();const download=await downloading,stream=await download.createReadStream(),chunks=[];
  let bytes=0;for await(const chunk of stream){bytes+=chunk.length;assert(bytes<=524288);chunks.push(chunk);}
  const exported=Buffer.concat(chunks);assert.equal(JSON.parse(exported).schema,'ascii-quest-design/v2');
  await editor.locator('#restore').setInputFiles({name:'roundtrip-design.json',mimeType:'application/json',buffer:exported});
  await page.waitForFunction(()=>document.querySelector('iframe').contentDocument.querySelector('#message').textContent.includes('Diseño abierto'));
  await editor.locator('#cancel-workshop').click();
  await page.evaluate(()=>{testActor='200';testAvatar.bind('actor200');});
  assert.equal(await page.locator('.workshop-portrait').count(),0,'Actor change removes private portrait');
  await page.locator('#avatar-workshop-open').click();await editor.locator('main:not([inert])').waitFor();await editor.locator('#versions').click();
  assert.equal(await editor.locator('#history button').count(),0,'Another actor has an isolated version library');
  await page.getByRole('button',{name:'Voice',exact:true}).click();
  const studio=page.getByRole('region',{name:'Voice workshop'});
  await studio.getByRole('button',{name:'Warm',exact:true}).click();
  await studio.getByLabel('Name for this voice').fill('My friendly voice');
  await page.evaluate(()=>{testLoseVoiceSaveAck=true;testVoicePosts=0;});
  await studio.getByRole('button',{name:'Save this voice',exact:true}).click();
  await studio.getByText('Saved! You can find it in My saved voices.',{exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>testVoicePosts),1,'Lost save ACK reads the same named revision');
  assert.equal(await studio.getByRole('button',{name:'Use this voice'}).isEnabled(),true);
  assert.equal(previewPosts.length,0,'Open, edits and Save never generate audio');
  await studio.getByRole('button',{name:'Use this voice'}).click();
  await studio.getByText('Chosen for our next voice chat.',{exact:true}).waitFor();
  await studio.getByLabel('Text to listen to').fill('¡Hola, árbol! ¿Nos vamos a explorar?');
  await studio.getByRole('button',{name:'▶ Listen',exact:true}).click();
  await studio.getByText('Try another voice, or save this one.',{exact:true}).waitFor();
  assert.deepEqual(previewPosts.map(r=>r.action),['prepare_sample','render']);
  assert.equal(previewPosts[0].passage,'¡Hola, árbol! ¿Nos vamos a explorar?');
  assert.equal(previewPosts[1].slot,'sample','There is one sample, no comparison');
  const beforeCached=previewPosts.length;
  await studio.getByRole('button',{name:'▶ Listen',exact:true}).click();
  assert.equal(previewPosts.length,beforeCached,'Known audio plays again without another generation');
  await studio.getByRole('button',{name:'▶ Marin',exact:true}).click();
  await page.waitForFunction(n=>(window.testPreviewReplies||0)>=n,(await page.evaluate(()=>testPreviewReplies))-1);
  await page.waitForFunction(()=>!document.querySelector('.voice-studio-play').disabled);
  assert.equal(previewPosts.filter(r=>r.action==='prepare_sample').at(-1).profile.voice,'marin');
  const editsOnly=previewPosts.length;
  await studio.locator('.voice-studio-presets').getByRole('button',{name:'Calm',exact:true}).click();
  await studio.getByRole('button',{name:'Joy',exact:true}).click();
  assert.equal(previewPosts.length,editsOnly,'Style and expression changes are inert');
  await studio.getByRole('button',{name:'Listen: Joy',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('.voice-studio-play').disabled);
  assert.equal(previewPosts.filter(r=>r.action==='prepare_sample').at(-1).passage,'Hooray! We did it! I want to celebrate with you.');
  assert(await page.evaluate(()=>testVoiceURLs.size<=2),'At most two cached audio URLs');
  // Unknown synthesis is read, never hidden by a replacement identity.
  unknownPreview=true;await studio.getByLabel('Text to listen to').fill('This is a distinct uncertain phrase.');
  await studio.getByRole('button',{name:'▶ Listen',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('.voice-studio-play').disabled);
  const uncertainCalls=previewPosts.length;
  await studio.getByRole('button',{name:'▶ Listen',exact:true}).click();
  await studio.getByText('This sample was not confirmed. Check My earlier samples; it won’t be made again.',{exact:true}).waitFor();
  assert.equal(previewPosts.length,uncertainCalls);
  await studio.getByText('My earlier samples',{exact:true}).click();
  assert(await studio.getByRole('button',{name:'Delete sample',exact:true}).evaluateAll(buttons=>buttons.some(b=>b.disabled)),'Unknown sample cannot be retired');
  const retained=studio.getByRole('button',{name:'▶ Listen to saved sample',exact:true}).first();
  const originalSettings=await studio.getByLabel('Text to listen to').inputValue(),historyPlays=await page.evaluate(()=>testVoicePlays),beforeHistory=previewPosts.length;
  await retained.click();await page.waitForFunction(()=>!document.querySelector('.voice-studio-play').disabled);
  assert.deepEqual(previewPosts.slice(beforeHistory).map(r=>r.action),['audio'],'History playback never allocates or renders');
  assert.equal(await page.evaluate(()=>testVoicePlays),historyPlays+1);
  assert.equal(await studio.getByLabel('Text to listen to').inputValue(),originalSettings,'History playback preserves current settings');
  await retained.click();assert.equal(previewPosts.length,beforeHistory+1,'Repeated history Play uses bounded audio cache');
  // Use a different retained row so the explicit read is not already cached.
  deferPreview=true;blockedPreview=undefined;
  await studio.getByRole('button',{name:'▶ Listen to saved sample',exact:true}).nth(1).click();
  for(let n=0;!blockedPreview&&n<100;n++)await page.waitForTimeout(10);assert(blockedPreview);
  await studio.getByRole('button',{name:'Stop',exact:true}).click();
  const lateHistoryPlays=await page.evaluate(()=>testVoicePlays);
  await blockedPreview.route.fulfill({json:{batch:blockedPreview.row,audio:lastPreviewAudio}});
  await page.waitForFunction(()=>!document.querySelector('.voice-studio-play').disabled);
  assert.equal(await page.evaluate(()=>testVoicePlays),lateHistoryPlays,'Stop fences a late retained audio read');
  blockedPreview=undefined;
  await studio.getByRole('button',{name:'▶ Listen to saved sample',exact:true}).nth(2).click();
  for(let n=0;!blockedPreview&&n<100;n++)await page.waitForTimeout(10);assert(blockedPreview);
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'));});
  const hiddenHistoryPlays=await page.evaluate(()=>testVoicePlays);
  await blockedPreview.route.fulfill({json:{batch:blockedPreview.row,audio:lastPreviewAudio}});
  await page.waitForFunction(()=>!document.querySelector('.voice-studio-play').disabled);
  assert.equal(await page.evaluate(()=>testVoicePlays),hiddenHistoryPlays,'Background fences a late retained audio read');
  await page.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));});
  deferPreview=false;
  const denied=Array.from(previewStates.values()).flatMap(s=>s.batches).find(r=>r.passage==='This is a distinct uncertain phrase.');
  assert(denied);denied.renders.sample.outcome={receipt:{diagnostic:{provider_error_code:'model_not_found'}}};
  await studio.getByRole('button',{name:'Check saved voices and samples',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('.voice-studio-play').disabled);
  const deniedCalls=previewPosts.length;
  await studio.getByRole('button',{name:'▶ Listen',exact:true}).click();
  await studio.getByText('The configured OpenAI voice model is not available for this account. This sample has no confirmed audio. Repeating Play will not fix access.',{exact:true}).first().waitFor();
  assert.equal(previewPosts.length,deniedCalls,'Retained model denial only reads status; no generation replay');

  const currentPreviews=previewStates.get(String(await page.evaluate(()=>testActor))),expiredID='b2af94be-4293-4a74-86ca-202611080001';
  currentPreviews.batches.push({id:expiredID,generation:++currentPreviews.generation,phase:'prepared',passage:'Expires while loading.',choices:{sample:{profile:{provider:'openai',api:'gpt-live',model:'gpt-live-1',voice:'cedar'},delivery:''}},renders:{sample:{state:'rendered'}}});
  await studio.getByRole('button',{name:'Check saved voices and samples',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('.voice-studio-play').disabled);
  const expiring=studio.locator('.voice-studio-history').filter({hasText:'Expires while loading.'}),expiryPosts=previewPosts.length,expiryPlays=await page.evaluate(()=>testVoicePlays);
  await expiring.getByRole('button',{name:'▶ Listen to saved sample',exact:true}).click();
  await studio.getByText('This sample’s audio has expired. Your voice settings are kept. Nothing was generated.',{exact:true}).waitFor();
  assert.equal(await expiring.getByRole('button',{name:'▶ Listen to saved sample',exact:true}).count(),0);
  assert.equal(await expiring.getByText('cedar · Audio expired',{exact:true}).count(),1);
  assert.equal(previewPosts.length,expiryPosts+1);assert.equal(previewPosts.at(-1).action,'audio');
  assert.equal(await page.evaluate(()=>testVoicePlays),expiryPlays,'Expiry cannot fabricate playback or regeneration');

  for(const width of [1200,375,320]){await page.setViewportSize({width,height:900});assert(await studio.evaluate(e=>e.scrollWidth<=e.clientWidth+1));}
  // Stop alone and hidden-tab results cannot restart playback, even if the
  // provider completed before it observed cancellation. The receipt is kept.
  unknownPreview=false;deferPreview=true;
  await studio.getByLabel('Text to listen to').fill('This sample is stopped without closing.');
  blockedPreview=undefined;await studio.getByRole('button',{name:'▶ Listen',exact:true}).click();
  for(let n=0;!blockedPreview&&n<100;n++)await page.waitForTimeout(10);assert(blockedPreview);
  await studio.getByRole('button',{name:'Stop',exact:true}).click();
  const stoppedPlays=await page.evaluate(()=>testVoicePlays);
  blockedPreview.row.renders.sample={state:'rendered'};
  await blockedPreview.route.fulfill({json:{batch:blockedPreview.row,audio:lastPreviewAudio}});
  await page.waitForFunction(()=>!document.querySelector('.voice-studio-play').disabled);
  assert.equal(await page.evaluate(()=>testVoicePlays),stoppedPlays,'Stop alone fences late automatic playback');
  const cachedStopped=previewPosts.length;
  await studio.getByRole('button',{name:'▶ Listen',exact:true}).click();
  assert.equal(await page.evaluate(()=>testVoicePlays),stoppedPlays+1,'Only a new explicit Play starts the retained sample');
  assert.equal(previewPosts.length,cachedStopped);
  await studio.getByLabel('Text to listen to').fill('This sample arrives while the page is hidden.');
  blockedPreview=undefined;await studio.getByRole('button',{name:'▶ Listen',exact:true}).click();
  for(let n=0;!blockedPreview&&n<100;n++)await page.waitForTimeout(10);assert(blockedPreview);
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'));});
  const hiddenPlays=await page.evaluate(()=>testVoicePlays);
  blockedPreview.row.renders.sample={state:'rendered'};
  await blockedPreview.route.fulfill({json:{batch:blockedPreview.row,audio:lastPreviewAudio}});
  await page.waitForFunction(()=>!document.querySelector('.voice-studio-play').disabled);
  assert.equal(await page.evaluate(()=>testVoicePlays),hiddenPlays,'Hidden-page late response cannot play');
  await page.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));});
  await studio.getByLabel('Text to listen to').fill('word '.repeat(41));
  await studio.getByText('This phrase has 41 words. Use up to 40.',{exact:true}).waitFor();
  assert.equal(await studio.getByRole('button',{name:'▶ Listen',exact:true}).isDisabled(),true);
  await studio.getByLabel('Text to listen to').fill('🌿'.repeat(300));
  await studio.getByText('This phrase is too long (over 1024 bytes). Try a shorter one.',{exact:true}).waitFor();
  // A pending explicit Play closes immediately and is cancelled only once.
  unknownPreview=false;deferPreview=true;await studio.getByLabel('Text to listen to').fill('A different pending phrase.');
  blockedPreview=undefined;await studio.getByRole('button',{name:'▶ Listen',exact:true}).click();
  for(let n=0;!blockedPreview&&n<100;n++)await page.waitForTimeout(10);assert(blockedPreview);
  const replies=await page.evaluate(()=>testPreviewReplies||0);
  await studio.getByRole('button',{name:'Stop',exact:true}).click();
  await page.getByRole('button',{name:'Back to conversation',exact:true}).click();
  await page.getByRole('dialog',{name:'Avatar workshop',exact:true}).waitFor({state:'hidden'});
  assert.equal(previewPosts.filter(r=>r.action==='cancel'&&r.id===blockedPreview.row.id).length,1);
  assert.equal(await page.evaluate(()=>testVoiceURLs.size),0);
  blockedPreview.row.renders.sample={state:'rendered'};await blockedPreview.route.fulfill({json:{batch:blockedPreview.row,audio:lastPreviewAudio}});
  await page.waitForFunction(n=>(window.testPreviewReplies||0)>n,replies);
  assert.equal(await page.evaluate(()=>testVoiceURLs.size),0,'Late closed-panel audio is ignored');
  await page.locator('#avatar-workshop-open').click();await page.getByRole('button',{name:'Voice',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('.voice-studio-play').disabled);
  assert.equal(await studio.getByLabel('Name for this voice').inputValue(),'My friendly voice');
  assert.equal(await studio.getByLabel('Describe how the voice should sound').inputValue(),'Use a warm, relaxed delivery with natural pauses.');
  await page.evaluate(()=>{testActor='100';testAvatar.bind('actor100');});
  assert.equal(await page.evaluate(()=>testVoiceURLs.size),0);
  await page.locator('#avatar-workshop-open').click();await page.getByRole('button',{name:'Voice',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('.voice-studio-play').disabled);
  assert.equal(await studio.getByLabel('My saved voices').locator('option').count(),1,'Named styles remain actor private');
  assert.deepEqual(errors,[]);
  // New source semantics survive the real account bridge and finite renderer.
  await page.reload();await page.locator('#avatar-workshop-open').click();await editor.locator('main:not([inert])').waitFor();
  await editor.locator('#tab-avatar').click();await editor.locator('[data-body="modular-bot"]').click();await editor.locator('#companion-name').click();
  await editor.locator('#cap-color').evaluate(e=>{e.value='#2266ee';e.dispatchEvent(new Event('input'));});await editor.locator('#close-appearance').click();
  await editor.locator('#tab-expression').click();while(!await editor.locator('[data-gallery="sleep"]').count())await editor.locator('#page-prev').click();
  await editor.locator('[data-gallery="sleep"]').click();await editor.locator('#tab-accessories').click();await editor.locator('#page-next').click();await editor.locator('[data-prop="pillow"]').click();
  await editor.locator('[data-prop-color="pillow"]').evaluate(e=>{e.value='#b185dc';e.dispatchEvent(new Event('input'));e.dispatchEvent(new Event('change'));});
  await editor.locator('#save').click();await page.waitForFunction(()=>!document.querySelector('iframe').contentDocument.querySelector('#use-avatar').disabled);
  const current=await page.evaluate(async()=>{const h={'X-Test-Actor':'100'},state=await(await fetch('/api/interaction/avatars',{headers:h})).json();return(await fetch('/api/interaction/avatars/'+state.editing,{headers:h})).json();});
  assert.equal(current.design.bodyColors['modular-bot'],'#2266ee');const sleeping=current.design.gestures.find(g=>g.id===current.design.activeGestureId);assert.equal(sleeping.cue,'sleep');assert.equal(sleeping.performance,'accessory/v1');assert.equal(sleeping.props[0].color,'#b185dc');
  const renderCheck=await page.evaluate(async d=>{const renderer=await import('/assets/avatar-workshop/renderer.mjs'),c=document.createElement('canvas');c.style='width:300px;height:300px';document.body.append(c);const paint=renderer.prepare(c,d);paint(24);const peak=c.toDataURL();paint(0);const start=c.toDataURL();paint(48);const end=c.toDataURL();c.remove();return {frames:paint.frames,ms:paint.frameMs,loop:start===end,changed:peak!==start};},current.design);
  assert.equal(renderCheck.frames,48);assert(renderCheck.loop&&renderCheck.changed);assert(renderCheck.ms>=80&&renderCheck.ms<=320);
  await editor.locator('#use-avatar').click();await editor.locator('#cancel-workshop').click();await page.reload();await page.locator('.workshop-portrait').waitFor();
  assert.equal(await page.locator('.workshop-portrait').count(),1,'New saved acting avatar reloads through existing account activation');
  // Spanish first-use presentation, explicit choices and selected Home themes.
  const child=await browser.newPage({locale:'es-AR',viewport:{width:375,height:850},reducedMotion:'reduce'});
  const childErrors=[];child.on('pageerror',error=>childErrors.push(error.message));
  await child.route('**/api/interaction/avatars/voice',async route=>{const response=await route.fetch(),value=await response.json();if(route.request().method()==='GET')value.audition_available=true;await route.fulfill({response,json:value});});
  await child.goto(process.argv[2]+'/?workshop=voice');
  const childStudio=child.getByRole('region',{name:'Taller de voces'});
  await childStudio.getByRole('heading',{name:'Encontrá mi voz'}).waitFor();
  await child.getByRole('button',{name:'Cálida',exact:true}).click();
  assert.equal(await child.getByRole('button',{name:'Cálida',exact:true}).getAttribute('aria-pressed'),'true');
  await childStudio.getByLabel('Nombre para esta voz').fill('Mi voz amiga');
  assert.equal(await childStudio.getByRole('button',{name:'Guardar esta voz',exact:true}).isEnabled(),true);
  assert.equal(await childStudio.getByRole('button',{name:'Usar esta voz',exact:true}).isDisabled(),true,'A new edit cannot silently select a voice');
  assert.equal(await childStudio.locator(':scope > details.voice-studio-more').getAttribute('open'),null,'Technical controls start closed');
  for(const width of [375,320,1200]){
   await child.setViewportSize({width,height:850});await childStudio.evaluate(e=>{e.scrollTop=0;});
   assert(await childStudio.evaluate(e=>e.scrollWidth<=e.clientWidth+1),'Spanish workshop reflows at '+width);
   assert(await childStudio.locator('.voice-studio-presets button').evaluateAll(nodes=>nodes.every(e=>e.getBoundingClientRect().height>=44)));
   assert(await childStudio.locator('.voice-studio-card p').evaluateAll(nodes=>nodes.every(e=>parseFloat(getComputedStyle(e).fontSize)>=14)));
   if(process.env.VOICE_STUDIO_SCREENSHOT)await child.screenshot({path:process.env.VOICE_STUDIO_SCREENSHOT.replace(/\.png$/,'-es-'+width+'.png')});
  }
  await child.setViewportSize({width:375,height:850});
  await child.evaluate(()=>{for(const [key,value] of Object.entries({background:'#f5f0df',surface:'#fffaf0',text:'#14283b',accent:'#6346aa'}))document.body.style.setProperty('--dm-'+key,value);});
  await childStudio.evaluate(e=>{e.scrollTop=0;});
  assert.equal(await childStudio.evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(245, 240, 223)');
  if(process.env.VOICE_STUDIO_SCREENSHOT)await child.screenshot({path:process.env.VOICE_STUDIO_SCREENSHOT.replace(/\.png$/,'-es-light.png')});
  await childStudio.getByText('Describila a tu manera',{exact:true}).click();
  await childStudio.getByLabel('Contá cómo querés que suene').fill('Alegre, con pausas suaves.');
  assert.equal(await childStudio.locator('.voice-studio-presets [aria-pressed="true"]').count(),0,'Custom delivery clears preset selection');
  assert.deepEqual(childErrors,[]);await child.close();
  // Actual header stacking and compact cosmetic controls, independent of account API.
  await page.setViewportSize({width:960,height:900});
  await page.evaluate(()=>{document.querySelector('dialog[open]')?.close();document.body.classList.add('standalone-conversation');document.body.style.display='block';const header=document.createElement('header'),identity=document.createElement('div');identity.className='identity';identity.append(document.querySelector('#conversation-companion'));header.append(identity);document.body.prepend(header);});
  const frameBox=page.locator('.avatar-frame');await frameBox.scrollIntoViewIfNeeded();
  const geometry=await page.evaluate(()=>{const box=document.querySelector('.avatar-frame').getBoundingClientRect(),gear=document.querySelector('#avatar-workshop-open').getBoundingClientRect();return {gearInside:gear.left>=box.left&&gear.right<=box.right,gearWidth:gear.width};});
  assert.equal(geometry.gearInside,true);assert.equal(geometry.gearWidth,32);
  assert.equal(await page.locator('#conversation-presence').count(),0,'Removed presence strip is not reintroduced by the workshop');
  assert.equal(await page.getByRole('button',{name:'Animate avatar',exact:true}).getAttribute('aria-pressed'),'true');
  await page.getByRole('button',{name:'Animate avatar',exact:true}).click();
  await page.evaluate(()=>document.body.classList.add('conversation-header-compact'));
  assert.equal(await frameBox.isVisible(),false,'Compact header hides portrait and its cosmetic controls together');
  await page.evaluate(()=>document.body.classList.remove('conversation-header-compact'));
  // The selected surface, including its custom canvas, is the existing voice entry.
  await page.evaluate(()=>{window.testVoiceEntry=ConversationVoiceMode.mount({portrait:document.querySelector('.avatar-surface'),canStart:()=>true,onEnter:()=>{window.testEnters=(window.testEnters||0)+1;},onLeave:()=>{},onSpeak:()=>{}});testVoiceEntry.configure(true);});
  const alignment=await page.evaluate(()=>{const a=document.querySelector('.avatar-surface').getBoundingClientRect(),b=document.querySelector('.workshop-portrait').getBoundingClientRect(),f=document.querySelector('.avatar-frame').getBoundingClientRect();return [a.top-f.top,b.top-f.top];});
  assert.deepEqual(alignment,[0,0],'Selected canvas and interaction surface share the top origin');
  await page.locator('.workshop-portrait').click({position:{x:30,y:20}});
  assert.equal(await page.locator('.voice-mode[open] .workshop-portrait').count(),1,'Voice mode presents the actual selected avatar');
  await page.evaluate(()=>testVoiceEntry.close());
  assert.equal(await page.locator('.avatar-frame .workshop-portrait').count(),1,'Closing restores the same custom portrait');
  await page.locator('.avatar-surface').focus();await page.keyboard.press('Enter');
  assert.equal(await page.locator('.voice-mode[open]').count(),1,'Keyboard entry remains available');
  await page.evaluate(()=>testVoiceEntry.close());
  const glow=await page.evaluate(()=>{const box=document.querySelector('#conversation-companion'),header=document.querySelector('header');box.dataset.pose='listening';const active=getComputedStyle(header).backgroundImage;box.dataset.pose='calm';return {active,rest:getComputedStyle(header).backgroundImage};});
  assert.match(glow.active,/radial-gradient/);assert.notEqual(glow.active,glow.rest,'Operational listening state lights the whole header');
  let releaseSelection;const selectionGate=new Promise(resolve=>releaseSelection=resolve);
  await page.route('**/api/interaction/avatars',async route=>{if(route.request().method()==='GET')await selectionGate;await route.continue();});
  await page.reload({waitUntil:'domcontentloaded'});
  assert.equal(await page.locator('.avatar-surface').getAttribute('data-avatar-state'),'loading');
  assert.equal(await page.locator('#conversation-companion pre').isVisible(),false,'No default portrait flashes while the selected avatar is loading');
  releaseSelection();await page.locator('.avatar-surface[data-avatar-state="custom"]').waitFor();
  assert.equal(await page.locator('#conversation-companion pre').isVisible(),false,'Only the selected avatar becomes visible');

  console.log('PASS actual editor + renderer + authenticated mounted storage: catalogue/custom save/use/reload, prior avatar, cancel, failed activation, actor isolation, image fallback, simultaneous object/detail, editable export/import, keyboard, reduced motion, large/compact and375/320 layouts; named voice save lost-ACK/use, actor isolation, direct Play/change/custom and expression text, exact cached playback, unknown generation no retry and narrow layouts; no provider calls');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
