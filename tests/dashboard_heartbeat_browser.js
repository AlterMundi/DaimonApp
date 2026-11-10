/* Actual shell/CSS with synthetic owner status; no providers or control writes. */
const fs=require('node:fs'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('https://heartbeat.test/**',route=>{
   const name=new URL(route.request().url()).pathname;
   if(name==='/')return route.fulfill({contentType:'text/html',body:fs.readFileSync('dashboard/web/index.html','utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'')});
   if(name==='/assets/style.css')return route.fulfill({contentType:'text/css',body:fs.readFileSync('dashboard/web/style.css','utf8')});
   return route.abort();
  });
  for(const viewport of [{width:1440,height:900},{width:390,height:720}]){
   await page.setViewportSize(viewport);await page.goto('https://heartbeat.test/');
   await page.addScriptTag({content:fs.readFileSync('dashboard/web/heartbeat.js','utf8')});
   await page.evaluate(()=>{
    document.documentElement.dataset.stylePolicy='authored';document.body.className='standalone-conversation conversation-header-compact';
    const heart=document.querySelector('#heartbeat-toggle');for(let p=heart;p;p=p.parentElement)p.hidden=false;
    window.calls=[];window.ownerStatus={schema:'telecodex.heartbeat-control/v1',generation:34,admission_paused:false,producer:{state:'configured',mode:'continuous',last_check:{outcome:'in_progress',started_at_unix_ms:Date.now()}},resources:{state:'available',mode:'continuous'},lanes:{messaging:{supported:true,paused:false,generation:3},reports:{supported:true,paused:false,generation:11},issues:{supported:false}},controls:{schema:'telecodex.heartbeat-controls/v1',conditional_global:true,conditional_lane:true,actions:['set_paused','set_lane_paused']},operational_evidence:{schema:'telecodex.heartbeat-operational/v1',generation:34,operational:false,reason:'attention_pending',observed_at_unix_ms:Date.now(),valid_for_seconds:15}};
    InteractionHeartbeat.mount({authenticated:()=>true,api:async(...args)=>{calls.push(args);return ownerStatus;}});
   });
   await page.locator('#heartbeat-toggle').click();await page.locator('#heartbeat-status').filter({hasText:'Waiting'}).waitFor();
   const view=await page.evaluate(()=>{
    const rect=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};
    return {heart:rect(document.querySelector('#heartbeat-toggle')),menu:rect(document.querySelector('#heartbeat-menu')),text:document.querySelector('#heartbeat-menu').innerText,pulse:document.querySelector('#heartbeat-toggle').dataset.state,calls};
   });
   assert.equal(view.menu.y,view.heart.bottom+8,'Menu must open immediately below the actual heart');
   assert(view.menu.x>=8 && view.menu.right<=viewport.width-8,'Menu stays within the viewport');
   assert(view.menu.bottom<=viewport.height-8);assert.equal(view.pulse,'unavailable');
   assert.doesNotMatch(view.text,/Generation|reconciled|Source check|Admission|lane|resources|Issues|2026-/);
   assert.match(view.text,/Earlier heartbeat work is still pending/);assert.match(view.text,/Messages/);assert.match(view.text,/Scheduled reviews/);
   assert(view.calls.every(c=>c.length===1),'Opening the menu may only read status');
   if(process.env.QUALIFICATION_OUTPUT)await page.screenshot({path:process.env.QUALIFICATION_OUTPUT+'/heartbeat-'+viewport.width+'.png'});
   await page.keyboard.press('Escape');await page.locator('#heartbeat-menu').waitFor({state:'hidden'});
   assert.equal(await page.locator('#heartbeat-toggle').evaluate(el=>el===document.activeElement),true);
  }
  assert.deepEqual(errors,[]);console.log('Desktop/mobile heartbeat: plain status, supported controls, adjacent menu, viewport bounds, Escape/focus and read-only opening passed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
