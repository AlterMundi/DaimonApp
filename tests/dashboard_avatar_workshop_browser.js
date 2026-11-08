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
  await editor.locator('main:not([inert])').waitFor();
  assert.equal(await editor.locator('.application-bar').innerText(),'ascii-avatar.exe');
  await editor.locator('body').evaluate(()=>document.fonts.ready);
  assert(await editor.locator('body').evaluate(()=>document.fonts.check('20px ArchivePixel')&&document.fonts.check('16px ArchiveText')),'Selected local game fonts loaded');
  assert(await editor.locator('.stage.world').evaluate(stage=>['#use-avatar','#cancel-workshop'].every(id=>{const b=getComputedStyle(document.querySelector(id)),s=getComputedStyle(stage);return b.backgroundColor===s.backgroundColor&&b.color===s.color;})),'Account actions retain readable receiving colors');
  assert.equal(await editor.locator('.upload-symbol svg').count(),1,'Selected letter envelope replaces the old text placeholder');
  await editor.locator('#appearance summary').click();
  assert(await editor.locator('.appearance-popover').evaluate(e=>e.scrollHeight<=e.clientHeight+2),'Appearance controls fit without scroll');
  const gaps=await editor.locator('.appearance-popover').evaluate(e=>{let previous=null;return [...e.querySelectorAll('label')].map(l=>{const a=l.querySelector('.control-label').getBoundingClientRect(),b=l.querySelector('input').getBoundingClientRect(),result={own:b.top-a.bottom,prior:previous===null?null:a.top-previous};previous=b.bottom;return result;});});
  assert(gaps.every(g=>g.own===2&&(g.prior===null||g.prior>g.own)),'Captions belong to their own controls');
  await editor.locator('#close-appearance').click();
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
  const denied=Array.from(previewStates.values()).flatMap(s=>s.batches).find(r=>r.passage==='This is a distinct uncertain phrase.');
  assert(denied);denied.renders.sample.outcome={receipt:{diagnostic:{provider_error_code:'model_not_found'}}};
  await studio.getByRole('button',{name:'Check saved voices and samples',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('.voice-studio-play').disabled);
  const deniedCalls=previewPosts.length;
  await studio.getByRole('button',{name:'▶ Listen',exact:true}).click();
  await studio.getByText('The configured OpenAI voice model is not available for this account. This sample has no confirmed audio. Repeating Play will not fix access.',{exact:true}).first().waitFor();
  assert.equal(previewPosts.length,deniedCalls,'Retained model denial only reads status; no generation replay');

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
  if(process.env.SCHOOL_SOURCE){
   const requestId='00000000-0000-4000-8000-000000000001';
   await page.goto(origin+'/?avatar_mission='+requestId);
   const mission=page.frameLocator('iframe');await mission.locator('main:not([inert])').waitFor();
   assert(await mission.locator('#use-avatar').isHidden(),'Mission never offers activation');
   await mission.locator('#appearance summary').click();await mission.locator('#name').fill('Synthetic mission companion');await mission.locator('#name').dispatchEvent('change');await mission.locator('#close-appearance').click();
   assert(await mission.locator('#return-mission').isDisabled(),'Unsaved changes cannot return an older revision');
   await mission.locator('#save').click();await mission.locator('#return-mission:enabled').waitFor();
   assert(await mission.locator('#use-avatar').isHidden(),'Saving preserves mission mode and cannot reveal activation');
   const before=await page.evaluate(async()=>fetch('/api/interaction/avatars',{headers:{'X-Test-Actor':'100'}}).then(r=>r.json()));
   await mission.locator('#return-mission').click();
   await page.locator('.avatar-workshop-dialog').waitFor({state:'hidden'});
   const entry=await page.evaluate(async id=>fetch('/api/interaction/avatars/missions/'+id,{headers:{'X-Test-Actor':'100'}}).then(r=>r.json()),requestId);
   const revision=entry.returned.saved_revision;
   assert.equal(revision.id,before.editing,'Return pins the explicitly saved version');
   const after=await page.evaluate(async()=>fetch('/api/interaction/avatars',{headers:{'X-Test-Actor':'100'}}).then(r=>r.json()));
   assert.equal(after.active,before.active,'Mission return never activates');
   await page.reload();await mission.locator('main:not([inert])').waitFor();
   assert(await mission.locator('#return-mission').isEnabled(),'Returned revision reopens after reload');
   const compact=page.locator('#avatar-mission-preview canvas');
   assert.equal(await compact.getAttribute('data-revision'),revision.id);
   assert.equal(await compact.getAttribute('data-sha256'),revision.sha256);
   assert(await compact.evaluate(c=>c.width>0&&c.height>0&&c.getContext('2d').getImageData(0,0,c.width,c.height).data.some(v=>v!==0)),'Exact returned revision renders in actual compact mission preview');
   assert(await mission.locator('#portrait').evaluate(c=>c.width>0&&c.height>0),'Reopened revision renders in workshop');
   await mission.locator('#cancel-workshop').click();
   console.log('PASS composed school mission browser entry/save/return/reload, exact immutable revision, workshop and compact rendering without activation');
  }
  await page.goto(origin);await page.locator('.avatar-surface[data-avatar-state="custom"]').waitFor();
  // Actual header stacking and compact cosmetic controls, independent of account API.
  await page.setViewportSize({width:960,height:900});
  await page.evaluate(()=>{document.querySelector('dialog[open]')?.close();document.body.classList.add('standalone-conversation');document.body.style.display='block';const header=document.createElement('header'),identity=document.createElement('div');identity.className='identity';identity.append(document.querySelector('#conversation-companion'));header.append(identity);const line=document.createElement('div');line.id='conversation-presence';line.dataset.pending='true';const pending=document.createElement('button');pending.id='test-pending-hit';pending.textContent='Pending decision';pending.style.cssText='display:block;width:100%;height:32px';line.append(pending);document.body.prepend(header,line);});
  const frameBox=page.locator('.avatar-frame');await frameBox.scrollIntoViewIfNeeded();
  const geometry=await page.evaluate(()=>{const box=document.querySelector('.avatar-frame').getBoundingClientRect(),gear=document.querySelector('#avatar-workshop-open').getBoundingClientRect(),line=document.querySelector('#conversation-presence').getBoundingClientRect(),picture=document.querySelector('.workshop-portrait').getBoundingClientRect();const y=line.top+2,x=Math.min(picture.right-2,picture.left+picture.width/2);return {gearInside:gear.left>=box.left&&gear.right<=box.right,gearWidth:gear.width,overlap:picture.bottom>y,pendingOnTop:document.elementFromPoint(x,y)?.closest('button')?.id==='test-pending-hit'};});
  assert.equal(geometry.gearInside,true);assert.equal(geometry.gearWidth,32);assert.equal(geometry.overlap,true,'Exercise real portrait overlap with pending line');assert.equal(geometry.pendingOnTop,true,'Pending text/action receives the overlapping hit');
  await page.getByRole('button',{name:'Pause avatar',exact:true}).click();
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
