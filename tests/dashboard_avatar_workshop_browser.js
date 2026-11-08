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
   const create=URL.createObjectURL.bind(URL),revoke=URL.revokeObjectURL.bind(URL);window.testVoiceURLs=new Set();
   URL.createObjectURL=blob=>{const url=create(blob);if(blob.type==='audio/wav')testVoiceURLs.add(url);return url;};
   URL.revokeObjectURL=url=>{testVoiceURLs.delete(url);return revoke(url);};
  });
  const previewStates=new Map();let previewPosts=[],deferPreview=false,blockedPreview,lastPreviewAudio;
  await page.route('**/api/interaction/avatars/voice',async route=>{
   const response=await route.fetch(),value=await response.json();
   if(route.request().method()==='GET')value.audition_available=true;
   await route.fulfill({response,json:value});
  });
  await page.route('**/api/interaction/avatars/voice/previews',async route=>{
   const actor=route.request().headers()['x-test-actor'];if(!previewStates.has(actor))previewStates.set(actor,{generation:0,batches:[]});const previewState=previewStates.get(actor);
   if(route.request().method()==='GET'){await route.fulfill({json:previewState});return;}
   const body=route.request().postDataJSON();previewPosts.push(body);
   if(body.action==='prepare'){
    const profile=body.profile;const row={id:body.id,generation:++previewState.generation,createdAt:Date.now(),phase:'prepared',
     choices:{A:{profile,delivery:'Current delivery'},B:{profile,delivery:body.delivery}},renders:{A:{state:'prepared'},B:{state:'prepared'}}};
    previewState.batches.push(row);await route.fulfill({json:row});return;
   }
   const row=previewState.batches.find(r=>r.id===body.id);
   if(body.action==='cancel'){await route.abort();return;}
   if(body.action==='render'){
    if(deferPreview){if(row.renders[body.slot].state!=='rendered')row.renders[body.slot]={state:'intent'};blockedPreview={route,row,slot:body.slot};return;}
    if(body.slot==='B'){row.renders.B={state:'unconfirmed'};await route.abort();return;}
    row.renders.A={state:'rendered',outcome:{receipt:{provider_receipt:{usage:{seconds:2},first_pcm_millis:120}}}};
    const wav=Buffer.alloc(4844);wav.write('RIFF');wav.writeUInt32LE(4836,4);wav.write('WAVEfmt ',8);wav.writeUInt32LE(16,16);wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);wav.writeUInt32LE(24000,24);wav.writeUInt32LE(48000,28);wav.writeUInt16LE(2,32);wav.writeUInt16LE(16,34);wav.write('data',36);wav.writeUInt32LE(4800,40);
    lastPreviewAudio={mime:'audio/wav',data:wav.toString('base64')};await route.fulfill({json:{batch:row,audio:lastPreviewAudio}});return;
   }
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
  await page.waitForFunction(()=>Array.from(document.querySelectorAll('.voice-studio-presets button')).some(b=>b.getAttribute('aria-label')==='Warm'&&!b.disabled));
  await page.evaluate(()=>{testLoseVoiceSaveAck=true;testVoicePosts=0;});
  await studio.getByRole('button',{name:'Warm',exact:true}).click();
  await studio.getByRole('button',{name:'Save my style',exact:true}).click();
  await studio.getByText('Style saved. Choose it when you are ready.',{exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>testVoicePosts),1,'Lost save ACK only reads the same revision');
  assert.equal(await studio.getByRole('button',{name:'Choose this style'}).isEnabled(),true);
  await page.waitForFunction(()=>Array.from(document.querySelectorAll('.voice-studio-presets button')).some(b=>b.getAttribute('aria-label')==='Warm'&&!b.disabled));
  assert.equal(await page.locator('#conversation-companion pre').isVisible(),true,'Voice save keeps the visual avatar');
  await studio.getByRole('button',{name:'Choose this style'}).click();
  await studio.getByText('Chosen! We will use it in our next voice chat.',{exact:true}).waitFor();
  assert.equal(previewPosts.length,0,'Opening, saving and selecting never generate audio');
  await studio.getByRole('button',{name:'Make a voice test',exact:true}).click();
  await studio.getByRole('button',{name:'Current voice: Make this sample',exact:true}).waitFor();
  assert.deepEqual(previewPosts.map(r=>r.action),['prepare']);
  await studio.getByRole('button',{name:'Current voice: Make this sample',exact:true}).click();
  await page.waitForFunction(()=>!Array.from(document.querySelectorAll('.voice-studio button')).find(b=>b.getAttribute('aria-label')==='Listen to my current voice').disabled);
  await studio.getByRole('button',{name:'Listen to my current voice',exact:true}).click();
  await studio.getByRole('button',{name:'Stop my current sample',exact:true}).click();
  await studio.getByRole('button',{name:'New style: Make this sample',exact:true}).click();
  await studio.getByText('This sample wasn’t confirmed. Check its status; it won’t be made again.',{exact:true}).waitFor();
  assert.equal(previewPosts.filter(r=>r.action==='render'&&r.slot==='B').length,1,'Unknown generation only reads retained status');
  assert.equal(await studio.getByRole('button',{name:'New style: Make this sample',exact:true}).isDisabled(),true);
  assert.equal(await studio.getByRole('button',{name:'Listen to my current voice',exact:true}).isEnabled(),true,'Generating B keeps the cached A audio');
  assert.equal(await page.evaluate(()=>testVoiceURLs.size),1,'Only the current cached A preview is held');
  await studio.getByText('More options',{exact:true}).click();await studio.getByText('My tests',{exact:true}).click();
  assert.equal(await studio.getByRole('button',{name:'Delete this test',exact:true}).isDisabled(),true,'Unknown paid outcome is preserved');
  await studio.getByText('More options',{exact:true}).click();
  for(const width of [1200,375,320]){
   await page.setViewportSize({width,height:900});
   assert(await studio.evaluate(e=>e.scrollWidth<=e.clientWidth+1),'Voice workshop overflow at '+width);
   assert.equal(await studio.getByLabel('Describe how the voice should sound').evaluate(e=>getComputedStyle(e).fontSize),'16px');
  }
  if(process.env.VOICE_STUDIO_SCREENSHOT)await page.screenshot({path:process.env.VOICE_STUDIO_SCREENSHOT});
  await page.evaluate(()=>{for(const [key,value] of Object.entries({background:'#101820',surface:'#17212b',text:'#f3f1e6',accent:'#82d5e7'}))document.body.style.setProperty('--dm-'+key,value);});
  assert.equal(await studio.evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(16, 24, 32)');
  if(process.env.VOICE_STUDIO_SCREENSHOT)await page.screenshot({path:process.env.VOICE_STUDIO_SCREENSHOT.replace(/\.png$/,'-dark.png')});
  // A network-held generation cannot trap the person in the workshop. Its
  // scoped cancellation may also lose its ACK; late audio must stay detached.
  deferPreview=true;await studio.getByRole('button',{name:'Calm',exact:true}).click();
  await studio.getByRole('button',{name:'Make a voice test',exact:true}).click();
  await studio.getByRole('button',{name:'New style: Make this sample',exact:true}).click();
  for(let n=0;!blockedPreview&&n<100;n++)await page.waitForTimeout(10);assert(blockedPreview);
  const replies=await page.evaluate(()=>window.testPreviewReplies||0);
  await page.getByRole('button',{name:'Back to conversation',exact:true}).click();
  await page.getByRole('dialog',{name:'Avatar workshop',exact:true}).waitFor({state:'hidden'});
  assert.equal(previewPosts.filter(r=>r.action==='cancel'&&r.id===blockedPreview.row.id).length,1,'Close sends only one owned stop, without waiting for its lost reply');
  assert.equal(await page.evaluate(()=>testVoiceURLs.size),0,'Closing releases recorded audio URLs');
  blockedPreview.row.renders.B={state:'rendered'};
  await blockedPreview.route.fulfill({json:{batch:blockedPreview.row,audio:lastPreviewAudio}});
  await page.waitForFunction(n=>(window.testPreviewReplies||0)>n,replies);
  assert.equal(await page.evaluate(()=>testVoiceURLs.size),0,'Late closed-panel audio cannot become a new playback URL');
  assert.equal(previewPosts.filter(r=>r.action==='render'&&r.id===blockedPreview.row.id).length,1,'Late audio does not cause generation replay');

  await page.locator('#avatar-workshop-open').click();await page.getByRole('button',{name:'Voice',exact:true}).click();
  await studio.getByRole('button',{name:'New style: Get saved audio',exact:true}).waitFor();
  assert.equal(await studio.getByLabel('Describe how the voice should sound').inputValue(),'Use a warm, relaxed delivery with natural pauses.','Discard returns the editor to the selected saved revision');
  const stopsBefore=previewPosts.filter(r=>r.action==='cancel').length;blockedPreview=undefined;
  await studio.getByRole('button',{name:'New style: Get saved audio',exact:true}).click();
  for(let n=0;!blockedPreview&&n<100;n++)await page.waitForTimeout(10);assert(blockedPreview);
  const cachedReplies=await page.evaluate(()=>window.testPreviewReplies||0);
  await page.getByRole('button',{name:'Back to conversation',exact:true}).click();
  await page.getByRole('dialog',{name:'Avatar workshop',exact:true}).waitFor({state:'hidden'});
  assert.equal(previewPosts.filter(r=>r.action==='cancel').length,stopsBefore,'Closing a pending cached read cannot cancel another slot');
  await blockedPreview.route.fulfill({json:{batch:blockedPreview.row,audio:lastPreviewAudio}});
  await page.waitForFunction(n=>(window.testPreviewReplies||0)>n,cachedReplies);
  assert.equal(await page.evaluate(()=>testVoiceURLs.size),0,'Late cached playback remains detached after closing');
  await page.locator('#avatar-workshop-open').click();await page.getByRole('button',{name:'Voice',exact:true}).click();
  await studio.getByRole('button',{name:'Calm',exact:true}).click();
  await studio.getByRole('button',{name:'Make a voice test',exact:true}).click();
  blockedPreview=undefined;await studio.getByRole('button',{name:'New style: Make this sample',exact:true}).click();
  for(let n=0;!blockedPreview&&n<100;n++)await page.waitForTimeout(10);assert(blockedPreview);
  const manualReplies=await page.evaluate(()=>window.testPreviewReplies||0);
  await studio.getByRole('button',{name:'Stop making audio',exact:true}).click();
  await page.waitForFunction(()=>Array.from(document.querySelectorAll('.voice-studio button')).find(b=>b.textContent==='Stop making audio').disabled);
  await page.getByRole('button',{name:'Back to conversation',exact:true}).click();
  await page.getByRole('dialog',{name:'Avatar workshop',exact:true}).waitFor({state:'hidden'});
  assert.equal(previewPosts.filter(r=>r.action==='cancel'&&r.id===blockedPreview.row.id).length,1,'Closing after an unconfirmed Stop cannot repeat it');
  blockedPreview.row.renders.B={state:'rendered'};
  await blockedPreview.route.fulfill({json:{batch:blockedPreview.row,audio:lastPreviewAudio}});
  await page.waitForFunction(n=>(window.testPreviewReplies||0)>n,manualReplies);
  assert.equal(await page.evaluate(()=>testVoiceURLs.size),0);
  await page.evaluate(()=>{testActor='100';testAvatar.bind('actor100');});
  assert.equal(await studio.getByLabel('My earlier tests').locator('option').count(),0,'Actor reset clears old batch labels before the next read');
  await page.locator('#avatar-workshop-open').click();
  await page.getByRole('button',{name:'Voice',exact:true}).click();
  await page.waitForFunction(()=>Array.from(document.querySelectorAll('.voice-studio-presets button')).some(b=>b.getAttribute('aria-label')==='Warm'&&!b.disabled));
  assert.equal(await studio.getByLabel('My saved styles').locator('option').count(),1,'Voice library is actor isolated');
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
  await childStudio.getByRole('heading',{name:'Una voz a mi manera'}).waitFor();
  await child.getByRole('button',{name:'Cálida',exact:true}).click();
  assert.equal(await child.getByRole('button',{name:'Cálida',exact:true}).getAttribute('aria-pressed'),'true');
  assert.equal(await childStudio.getByRole('button',{name:'Guardar mi estilo',exact:true}).isEnabled(),true);
  assert.equal(await childStudio.getByRole('button',{name:'Elegir este estilo',exact:true}).isDisabled(),true,'A new edit cannot silently select a voice');
  assert.equal(await childStudio.locator(':scope > details.voice-studio-more').getAttribute('open'),null,'Technical controls start closed');
  for(const width of [375,320,1200]){
   await child.setViewportSize({width,height:850});await childStudio.evaluate(e=>{e.scrollTop=0;});
   assert(await childStudio.evaluate(e=>e.scrollWidth<=e.clientWidth+1),'Spanish workshop reflows at '+width);
   assert(await childStudio.locator('.voice-studio-presets button').evaluateAll(nodes=>nodes.every(e=>e.getBoundingClientRect().height>=44)));
   assert(await childStudio.locator('.voice-studio-card p,.voice-studio-presets small').evaluateAll(nodes=>nodes.every(e=>parseFloat(getComputedStyle(e).fontSize)>=14)));
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
  console.log('PASS actual editor + renderer + authenticated mounted storage: catalogue/custom save/use/reload, prior avatar, cancel, failed activation, actor isolation, image fallback, simultaneous object/detail, editable export/import, keyboard, reduced motion, large/compact and375/320 layouts; voice revisions/current A/save lost-ACK/use, actor isolation, explicit A/B generation/playback, lost generation status-only recovery and narrow layouts; no provider calls');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
