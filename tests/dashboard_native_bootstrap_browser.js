const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=process.env.QUALIFICATION_OUTPUT,origin=process.env.FIXTURE_ORIGIN;const emptyInput=Number(process.env.QUALIFICATION_EMPTY_INPUT||0),cycles=Number(process.env.QUALIFICATION_CYCLES||3);assert(root&&origin,'Use dashboard_native_bootstrap.py to own the bounded server/output lifecycle');
const save=(name,value)=>fs.writeFileSync(path.join(root,name),JSON.stringify(value,null,2));
(async()=>{let browser,context,page;const errors=[],http=[];
try{
 browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--mute-audio','--disk-cache-size=1048576','--media-cache-size=1048576']});
 context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:390,height:720}});
 await context.addCookies([{name:'__Host-home',value:'s'.repeat(43),url:origin+'/',secure:true,httpOnly:true,sameSite:'Lax'}]);
 await context.addInitScript(()=>{
  const f=window.fixture={states:[],retained:[],released:[],sources:[],contexts:[],trackStops:0,captureFrames:0,engineCreations:0},RealContext=window.AudioContext;
  window.AudioContext=class extends RealContext{
   constructor(...args){super(...args);f.contexts.push(this);}
   createBufferSource(){const source=super.createBufferSource(),start=source.start.bind(source),stop=source.stop.bind(source);let row;
    source.start=(at)=>{if(source.buffer?.sampleRate===24000){row={started:performance.now(),frames:source.buffer.length,ended:false};f.sources.push(row);source.addEventListener('ended',()=>{row.ended=true;row.endedAt=performance.now();});}return start(at);};
    source.stop=(at)=>{if(row)row.stopped=performance.now();return stop(at);};return source;
   }
  };
  navigator.mediaDevices.getUserMedia=async()=>{f.inputContext=new RealContext({sampleRate:48000});await f.inputContext.resume();f.destination=f.inputContext.createMediaStreamDestination();const stream=f.destination.stream;for(const track of stream.getTracks()){const stop=track.stop.bind(track);track.stop=()=>{f.trackStops++;stop();void f.inputContext.close();};}return stream;};
  let native,capture;
  Object.defineProperty(window,'NativeConversation',{configurable:true,get:()=>native,set(value){native={...value,create(hooks){f.engineCreations++;const onState=hooks.onState,retain=hooks.retain,release=hooks.release;hooks.onState=value=>{f.states.push({at:performance.now(),...value});return onState?.(value);};hooks.retain=async value=>{const saved=await retain(value);f.retained.push({id:saved.id,sha256:saved.audio_sha256,bytes:saved.blob.size});return saved;};hooks.release=async(...args)=>{await release(...args);f.released.push(args[0].id);};return f.engine=value.create(hooks);}};}});
  Object.defineProperty(window,'StreamingVoice',{configurable:true,get:()=>capture,set(value){capture={...value,async openCapture(...args){f.captureSessionSeconds=args[1]?.sessionSeconds??300;const opened=await value.openCapture(...args),subscribe=opened.subscribe.bind(opened);opened.subscribe=fn=>subscribe(v=>{if(v.pcm)f.captureFrames++;fn(v);});return opened;}};}});
  f.injectTone=async()=>{const source=f.inputContext.createBufferSource(),buffer=f.inputContext.createBuffer(1,4800,16000),data=buffer.getChannelData(0);for(let n=0;n<data.length;n++)data[n]=.2*Math.sin(n*2*Math.PI*440/16000);source.buffer=buffer;source.connect(f.destination);await new Promise(resolve=>{source.onended=resolve;source.start();});};
  f.report=()=>({captureSessionSeconds:f.captureSessionSeconds,states:f.states,retained:f.retained,released:f.released,sources:f.sources,trackStops:f.trackStops,captureFrames:f.captureFrames,engineCreations:f.engineCreations,active:f.engine?.active,pending:f.engine?.originals?.length,inputContextState:f.inputContext?.state,contextStates:f.contexts.map(v=>v.state),sharedAuth:document.documentElement.dataset.sharedAuth,clientVersion:document.querySelector('#client-build')?.getAttribute('aria-label'),account:document.querySelector('#conversation-account')?.textContent,appLoaded:[...document.scripts].some(v=>v.src.includes('/assets/app.js')),dialogOpen:document.querySelector('dialog.voice-mode')?.open});
 });
 page=await context.newPage();page.on('pageerror',e=>errors.push(String(e)));page.on('response',response=>{if(http.length<250)http.push({path:new URL(response.url()).pathname,status:response.status()});});
 await page.goto(origin+'/interaction/?view=conversation&client=standalone',{waitUntil:'load'});
 await page.waitForFunction(()=>document.querySelector('#conversation-account')?.textContent.includes('Synthetic operator'),{},{timeout:12000});
 await page.waitForFunction(()=>document.querySelector('#conversation-companion pre')?.getAttribute('role')==='button',{},{timeout:12000});
 assert.equal(await page.evaluate(()=>fixture.engine?.active),false,'No microphone before explicit avatar activation');
 await page.locator('#conversation-companion pre').click();
 await page.waitForFunction(()=>fixture.engine?.active&&fixture.states.some(v=>v.active===true&&v.starting===false),{},{timeout:15000});
 assert.equal(await page.evaluate(()=>fixture.captureSessionSeconds),Number(process.env.QUALIFICATION_SECONDS||300));
 console.log('Full app cookie/bootstrap/avatar ready');
 for(let n=0;n<cycles;n++){
  await page.evaluate(()=>fixture.injectTone());
  await page.waitForFunction(count=>fixture.sources.length>=count,n+1,{timeout:12000});
  if(n===0){
   const failed=page.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/api/interaction')&&r.status()===503,{timeout:10000});
   await page.evaluate(()=>fetch('/fixture/control',{method:'POST',body:JSON.stringify({fail_metadata:true,invalidate:true})}));await failed;
   assert.equal(await page.evaluate(()=>fixture.engine.active),true,'A transient ordinary HTTP read cannot terminate the active native owner');
   const recovered=page.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/api/interaction')&&r.status()===200,{timeout:10000});
   await page.evaluate(()=>fetch('/fixture/control',{method:'POST',body:JSON.stringify({invalidate:true})}));await recovered;
  }
  await page.waitForFunction(counts=>fixture.retained.length===counts.retained&&fixture.released.length===counts.released&&fixture.sources.every(v=>v.ended&&!v.stopped)&&fixture.sources.reduce((sum,v)=>sum+v.frames,0)===counts.retained*24000,{retained:n+1,released:Math.max(0,n+1-emptyInput)},{timeout:12000});
  assert.equal(await page.evaluate(()=>fixture.engine.active),true,'Native voice stays available for the next phrase');
  console.log('Completed full-app native cycle',n+1);
 }
 await page.screenshot({path:path.join(root,'full-bootstrap-390.png')});
 let finiteWorklet;
 if(Number(process.env.QUALIFICATION_SECONDS)>300){
  finiteWorklet=await page.evaluate('('+fs.readFileSync(path.join(__dirname,'dashboard_native_duration_worklet_fixture.js'),'utf8')+')('+Number(process.env.QUALIFICATION_SECONDS)+')');
  assert.equal(finiteWorklet?.actualChromiumWorklet,true,'The browser must execute the fixture, not serialize its function');
  assert.equal(finiteWorklet.bytes,Number(process.env.QUALIFICATION_SECONDS)*32000);
 }
 const before=await page.evaluate(()=>fixture.report());assert.equal(before.engineCreations,1);assert.equal(before.pending,emptyInput);assert(before.captureFrames>0);assert.equal(before.sharedAuth,'true');assert.equal(before.appLoaded,true);assert.equal(before.retained.length,cycles);assert.equal(before.released.length,cycles-emptyInput);
 assert(http.some(v=>v.path.endsWith('/api/interaction/access')&&v.status===200));assert(http.some(v=>v.path.endsWith('/api/interaction/events')&&v.status===200));assert.equal(http.filter(v=>v.status>=500&&v.status!==503).length,0,JSON.stringify(http));assert.equal(errors.length,0,errors.join('\n'));
 await page.locator('dialog.voice-mode').getByRole('button',{name:'Back to conversation',exact:true}).click();
 await page.waitForFunction(()=>!fixture.engine.active&&fixture.trackStops===1&&fixture.inputContext.state==='closed'&&fixture.contexts.every(c=>c.state==='closed'),{},{timeout:10000});
 save('browser.json',{finiteWorklet,state:'actual-shell-shared-cookie-native-cycles-observed',cycles,before,after:await page.evaluate(()=>fixture.report()),http,errors,limits:'Synthetic identity/provider/detector/MediaStream. Actual shipped app bootstrap, worklet, output/IndexedDB, sockets/HTTP/SSE. No real account login/provider/native work/physical hearing qualified.'});
}catch(error){if(page)try{save('browser-progress.json',await page.evaluate(()=>fixture.report()));}catch{}save('browser-error.json',{error:String(error),http,errors});throw error;}
finally{if(page)try{await page.evaluate(()=>fixture.engine?.hold('Synthetic full-bootstrap cleanup'));}catch{}if(context)await context.close();if(browser)await browser.close();save('browser-closure.json',{closed:true});}
})().catch(error=>{console.error(error);process.exitCode=1;});
