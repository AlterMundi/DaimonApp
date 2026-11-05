/* Shipped shell/assets in Chromium with synthetic API fixtures only.
 * Output <=4MiB, one temporary HTTP server/browser, no provider/native calls. */
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const output=process.env.QUALIFICATION_OUTPUT;assert(output&&path.isAbsolute(output)&&!fs.existsSync(output));fs.mkdirSync(output,{mode:0o700});
const publicRoot=path.resolve('dashboard/web'),binding='a'.repeat(64),revision='b'.repeat(64),posts=[],errors=[],sockets=new Set();
const ref=n=>({source:`session:${n}`,revision});
const sessions=[{id:'1'.repeat(24),title:'Materials · Results ready for a closer look',audio_key:'100:7',destination:ref(7),latest_reply:{...ref(7),source:'session:7/42'},fresh:true,execution:'idle',goal_state:'absent',result_available:true},
{id:'2'.repeat(24),title:'Garden · Waiting for your choice',audio_key:'100:8',destination:ref(8),latest_reply:{...ref(8),source:'session:8/43'},fresh:true,human_action_pending:true,execution:'working',goal_state:'blocked'},
{id:'3'.repeat(24),title:'Conversation',audio_key:'100:1',destination:null,is_entry:true,fresh:true,execution:'working',goal_state:'active'}];
for(const row of sessions)row.last_activity_at=Date.now()/1000;
sessions.push({id:'4'.repeat(24),title:'Old inactive session',last_activity_at:Date.now()/1000-172800,fresh:false,execution:'idle',goal_state:'absent'});
const originals=[];let seen=0,workspaceAllowed=true;
const sources=Array.from({length:30},(_,i)=>({id:`native:${i+1}`,kind:'integrator_answer',revision,preview:`A small observation ${i+1}. `+'A retained synthetic conversation gives this reading area enough room to scroll naturally. '.repeat(8),observed_at:new Date(1704067200000+i*1000).toISOString()}));
const base=()=>({binding,csrf:'fixture-csrf',items:[],cursor:0,newest:0,more:false});
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://fixture.invalid');
 const json=(v,status=200)=>{res.writeHead(status,{'content-type':'application/json','cache-control':'no-store'});res.end(JSON.stringify(v));};
 try{
 if(url.pathname.startsWith('/api/')){
  const route=url.pathname.slice(5);
  if(route==='interaction/access')return json({csrf:'fixture-csrf',label:'Synthetic operator'});
  if(route==='interaction/sessions')return workspaceAllowed?json({schema:'daimon.session-workspace/v1',sessions}):json({detail:'Workspace grant revoked'},403);
  if(route.startsWith('interaction/sessions/')){
   const technical=url.searchParams.get('technical')==='true',after=url.searchParams.has('after');
   return json({schema:'daimon.session-view/v1',revision:'c'.repeat(64),before:50,after:250,has_earlier:false,more:false,
    items:after?[]:[{id:'message',kind:'message',role:'user',text:'Show me what we discovered.',position:50,next_position:100},
     {id:'response',kind:'message',role:'assistant',text:'The first prototype is ready. Let us look together.',position:100,next_position:150},
     ...(technical?[{id:'tool',kind:'tool_call',name:'inspect_result',text:'{"result":"prototype"}',position:150,next_position:200},
      {id:'summary',kind:'reasoning_summary',role:'assistant',text:'Compare the measured result with our original question.',position:200,next_position:250}]:[])]});
  }
  if(route==='interaction/inputs'&&req.method==='POST'){
   let raw='';for await(const block of req)raw+=block;const body=JSON.parse(raw);posts.push(body);
   const value={...body,phase:body.reply?'routed':'accepted',sequence:++seen,received_at:new Date().toISOString(),...(body.reply?{routing:{phase:'accepted',label:'Materials',target:{thread_id:7},instruction:'fixture-instruction'}}:{})};originals.push(value);return json(value);
  }
  if(route==='interaction/inputs')return json({...base(),items:originals,cursor:seen,newest:seen});
  if(route==='interaction')return json({...base(),items:sources,cursor:{delivery:0,native:30,matrix:0},newest:{delivery:0,native:30,matrix:0},can_reply_updates:true,can_listen:false,can_speak:false,activity:{connected:true,sessions:[],observed_at:Date.now()/1000},goal_controls:{items:[],more:false}});
  if(route==='interaction/part')return json({text:sources.find(v=>v.id===url.searchParams.get('source'))?.preview||'Synthetic text',next_offset:null});
  if(route==='interaction/sonic')return json({configured:false,connected:true,sources:[]});
  if(route==='interaction/alerts')return json({state:'available',producers:[],incidents:[],csrf:'fixture-csrf'});
  if(route==='interaction/events'){res.writeHead(200,{'content-type':'text/event-stream'});res.write(': synthetic fixture\n\n');return;}
  if(route.startsWith('interaction/inputs/'))return json({schema:'telecodex.conversation-trace/v1',routes:[],text:'Exact synthetic input',read_only:true});
  return json({...base(),schema:route==='interaction/telegram-inputs'?'telecodex.telegram-input-list/v1':undefined});
 }
 const name=url.pathname.startsWith('/assets/')?path.basename(url.pathname):'index.html';
 const file=path.join(publicRoot,name);if(!fs.existsSync(file)){res.writeHead(404);return res.end();}
 let body=fs.readFileSync(file);
 if(name==='index.html')body=body.toString().replace('<html lang="en">','<html lang="en" data-shared-auth="true">').replace('    <script src="https://telegram.org/js/telegram-web-app.js" defer></script>','');
 res.writeHead(200,{'content-type':name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':name.endsWith('.woff2')?'font/woff2':'text/html'});res.end(body);
 }catch(error){errors.push(String(error));res.writeHead(500);res.end('Fixture error');}
});
server.on('connection',socket=>{sockets.add(socket);socket.on('close',()=>sockets.delete(socket));});
(async()=>{let browser;const report={state:'started',source:'shipped source assets with synthetic HTTP fixtures; no native/provider/audio hearing claim'};
 try{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin=`http://127.0.0.1:${server.address().port}`;
 browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--mute-audio','--disk-cache-size=1048576','--media-cache-size=1048576']});
 const context=await browser.newContext({viewport:{width:1280,height:800}});await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
 await context.addInitScript(()=>{
  let original;window.workspaceFixture={};Object.defineProperty(window,'VoiceInput',{configurable:true,get:()=>original,set(value){original={...value,mount(hooks){window.workspaceFixture.microphone=hooks;return value.mount(hooks);}};}});
 });
 const page=await context.newPage();page.on('pageerror',error=>errors.push(String(error)));
 await page.goto(origin+'/?view=conversation&client=standalone',{waitUntil:'load'});
 await page.locator('.session-workspace-toolbar').waitFor({state:'visible',timeout:12000});
 assert.equal(await page.getByRole('button',{name:'Show routing map',exact:true}).count(),0,'Messages have no routing-map shortcut');
 await page.getByRole('button',{name:'Under the hood',exact:true}).click();
 await page.locator('#conversation-flow > summary').click();
 assert(await page.locator('#routing-graph-viewport').isVisible(),'Routing map remains under the hood');
 await page.getByRole('button',{name:'Under the hood',exact:true}).click();
 await page.getByRole('button',{name:'Show sessions',exact:true}).click();
 async function bottomMenu(){
  const rect=async selector=>page.locator(selector).evaluate(node=>{const r=node.getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right};});
  const bar=await rect('.session-workspace-toolbar'),body=await rect('.session-workspace-body'),menu=await rect('.session-rail'),input=await rect('#conversation-dock');
  assert(body.bottom<=bar.top+1,'Destination toolbar follows the reading area');
  assert(bar.bottom<=input.top+1,'Destination toolbar sits above the input');
  assert(menu.bottom<=bar.top+1&&menu.top>=body.top-1,'Sessions expand upward inside the reading area');
  assert(menu.left>=0&&menu.right<=await page.evaluate(()=>innerWidth),'Session menu stays inside viewport');
 }
 await bottomMenu();
 assert.equal(await page.getByRole('button',{name:'Old inactive session',exact:true}).count(),0);
 assert.deepEqual(await page.locator('.session-name').allTextContents(),[sessions[1].title,sessions[2].title,sessions[0].title]);
 await page.locator('.session-row').filter({has:page.getByRole('button',{name:sessions[0].title,exact:true})}).getByRole('button',{name:'Pin as the input destination',exact:true}).click();
 await page.locator('#conversation-message').fill('Keep this draft while I look around.');
 assert.equal(await page.evaluate(()=>workspaceFixture.microphone.getReply().reference.source),'session:7');
 await page.getByRole('button',{name:sessions[1].title,exact:true}).click();
 await page.locator('.session-message').first().waitFor();
 assert.equal(await page.evaluate(()=>workspaceFixture.microphone.getReply().reference.source),'session:8');
 assert.equal(await page.locator('#conversation-message').inputValue(),'Keep this draft while I look around.');
 await page.getByRole('button',{name:'Show tools and exposed reasoning summaries'}).click();
 await page.getByText('>_ inspect_result',{exact:true}).waitFor();
 assert(await page.getByText('Reasoning summary',{exact:true}).isVisible());
 await page.screenshot({path:path.join(output,'desktop-technical.png')});
 await page.getByRole('button',{name:'Back to the conversation',exact:true}).click();
 assert.equal(await page.evaluate(()=>workspaceFixture.microphone.getReply().reference.source),'session:7');
 await page.locator('#conversation-send').click();await page.waitForFunction(()=>document.querySelector('#conversation-message').value==='');
 assert.equal(posts.at(-1).reply.source,'session:7');assert.equal(posts.at(-1).text,'Keep this draft while I look around.');
 await page.getByRole('button',{name:'Show sessions',exact:true}).click();
 await page.locator('.session-row').filter({has:page.getByRole('button',{name:sessions[0].title,exact:true})}).getByRole('button',{name:'Reply to the latest message',exact:true}).click();
 await page.locator('#conversation-message').fill('About that exact result.');await page.locator('#conversation-send').click();
 await page.waitForFunction(()=>document.querySelector('#conversation-message').value==='');assert.equal(posts.at(-1).reply.source,'session:7/42');
 await page.getByRole('button',{name:`Mute ${sessions[0].title}`,exact:true}).click();
 assert.equal(await page.getByRole('button',{name:`Unmute ${sessions[0].title}`,exact:true}).getAttribute('aria-pressed'),'true');
 await page.getByRole('button',{name:'Hear all sessions: clear mute and solo',exact:true}).click();
 await page.screenshot({path:path.join(output,'desktop-sessions.png')});
 await page.setViewportSize({width:390,height:844});
 await page.locator('#conversation-message').fill('My draft stays here.');await page.screenshot({path:path.join(output,'mobile-sessions.png')});
 await bottomMenu();
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'No horizontal page overflow');
 const layout=await page.locator('.session-row').first().evaluate(row=>{
  const rect=selector=>{const r=row.querySelector(selector).getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom};};
  return {name:rect('.session-name'),actions:rect('.session-row-actions'),state:rect('.session-row-state')};
 });
 assert(layout.actions.x>=layout.name.right-1,'Controls sit to the right of the title');
 assert(layout.state.y>=Math.max(layout.name.bottom,layout.actions.bottom)-1,'Status sits below title and controls');
 assert((await page.getByRole('button',{name:`Mute ${sessions[0].title}`,exact:true}).innerHTML()).includes('M11 5 6 9H3'),'Canonical speaker mute icon');

 await page.getByRole('button',{name:'Hide sessions',exact:true}).click();
 const timeline=page.locator('#conversation-timeline');await timeline.evaluate(node=>{node.scrollTop=0;});await page.waitForTimeout(100);
 assert.equal(await page.locator('body').evaluate(body=>body.classList.contains('conversation-header-compact')),false,'Programmatic positioning does not compact header');
 await page.locator('#conversation-presence').evaluate(node=>{node.hidden=false;node.textContent='Pending work';});
 await timeline.hover();await page.mouse.wheel(0,900);await page.waitForTimeout(150);
 assert(await page.locator('body').evaluate(body=>body.classList.contains('conversation-header-compact')),'User forward scroll compacts header');
 assert.equal(await page.locator('#conversation-presence').isVisible(),false,'Compact header hides the pending line');
 const identity=await page.locator('header .companion-name').boundingBox(),header=await page.locator('header').boundingBox();
 assert(identity.y>=header.y&&identity.y+identity.height<=header.y+header.height,'Compact identity remains fully visible');
 await page.screenshot({path:path.join(output,'mobile-compact.png')});
 await page.mouse.wheel(0,-300);await page.waitForTimeout(150);
 assert.equal(await page.locator('body').evaluate(body=>body.classList.contains('conversation-header-compact')),false,'Reverse scroll restores header');
 assert(await page.locator('#conversation-presence').isVisible(),'Reverse scroll restores the pending line');
 await page.screenshot({path:path.join(output,'mobile-conversation.png')});
 assert.equal(await page.locator('#conversation-message').inputValue(),'My draft stays here.');
 workspaceAllowed=false;await page.locator('#conversation-refresh').evaluate(button=>button.click());
 await page.getByText('Session workspace access is unavailable. Return the input to the conversation, or restore access.',{exact:true}).waitFor();
 assert(await page.locator('#conversation-timeline').isVisible());assert(await page.locator('#conversation-account').isVisible(),'Workspace denial is not a global sign-out');
 assert.equal(await page.locator('#conversation-message').inputValue(),'My draft stays here.');
 await page.getByRole('button',{name:'Send to the conversation',exact:true}).click();assert.equal(errors.length,0,errors.join('\n'));
 report.state='qualified-synthetic-browser';report.posts=posts.map(v=>({text:v.text,reply:v.reply}));report.viewports=['1280x800','390x844'];report.errors=errors;
 }finally{
 if(browser)await browser.close();for(const socket of sockets)socket.destroy();await new Promise(resolve=>server.close(resolve));
 report.errors=errors;fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(report,null,2));
 const bytes=fs.readdirSync(output).reduce((n,file)=>n+fs.statSync(path.join(output,file)).size,0);assert(bytes<=4*1024*1024);console.log(JSON.stringify({state:report.state,retained_bytes:bytes,errors}));
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
