/* Actual composed Canvas: an explicitly attached hand prop follows the rig,
   while simultaneous floating detail and legacy static anchors stay unchanged. */
const assert=require('node:assert/strict'),http=require('node:http'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const root=path.resolve(__dirname,'../dashboard/web/avatar-workshop');
 const server=http.createServer((req,res)=>{if(req.url==='/'){res.end('<!doctype html><body></body>');return;}const name=decodeURIComponent(req.url.split('?')[0]),file=path.resolve(root,'.'+name);if(!file.startsWith(root+path.sep)||!file.endsWith('.mjs')||!fs.existsSync(file)){res.writeHead(404).end();return;}res.setHeader('Content-Type','text/javascript');res.end(fs.readFileSync(file.endsWith('/surface-renderer.mjs')&&process.env.AVATAR_TEST_SURFACE?process.env.AVATAR_TEST_SURFACE:file));});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;
 try{
  browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE||'/usr/bin/chromium',headless:true});const page=await browser.newPage();await page.goto('http://127.0.0.1:'+server.address().port);
  const result=await page.evaluate(async()=>{
   const {validateAvatarModel,resolveAvatarModelAnchors}=await import('/skills/ascii-avatar-author/scripts/model-runtime.mjs');
   const {surfaceSource}=await import('/experiments/school-avatar-quest/surface-renderer.mjs');
   const cues=['calm','curious','joy','sad','anger','uncertain','focus','welcome'];
   const m=validateAvatarModel({schema:'ascii-avatar-model/v1',id:'attached-hand-fixture',name:'Attached hand',nodes:[{id:'arm',type:'path',path:[['M',140,140]],fill:null,pivot:[140,140]},{id:'anchor-rightHand',parent:'arm',type:'path',path:[['M',200,300]],fill:null,pivot:[200,300]}],animations:Object.fromEntries(cues.map(c=>[c,[{node:'arm',channel:'x',frames:[0,8,16,24,32,40,48,40,32,24,16,8]},{node:'arm',channel:'y',frames:[0,4,8,12,16,20,24,20,16,12,8,4]}]])),anchors:{rightHand:[200,300],compact:[50,50,400,500]}});
   const original=JSON.stringify(m),anchors=resolveAvatarModelAnchors(m,6,'focus');
   const d={avatarModel:m,activeProps:[{id:'book',color:'#ff0000',side:'right',size:1},{id:'star',color:'#00ff00',side:'right',size:1}],body:'modular-bot',characterStyle:'surface/v2',aperture:1,curvature:0,motion:'still',palette:'aurora',material:'smooth'};
   const bounds=(canvas,channel)=>{const a=canvas.getContext('2d').getImageData(0,0,576,720).data;let x0=576,x1=0,y0=720,y1=0,n=0;for(let y=0;y<720;y++)for(let x=0;x<576;x++){const i=(y*576+x)*4;if(a[i+3]&&a[i+channel]>a[i+(1-channel)]*1.8&&a[i+channel]>a[i+2]*1.8){x0=Math.min(x,x0);x1=Math.max(x,x1);y0=Math.min(y,y0);y1=Math.max(y,y1);n++;}}return {x0,x1,y0,y1,n};};
   const a=surfaceSource(d,0,'focus'),b=surfaceSource(d,6,'focus'),legacy=structuredClone(m);legacy.nodes=legacy.nodes.filter(n=>n.id!=='anchor-rightHand');const staticDesign={...d,avatarModel:legacy};
   // Noncommuting parent rotation/scale, child offset and negative frame wrap.
   const nested=structuredClone(m);nested.animations.focus=[{node:'arm',channel:'rotate',frames:Array(12).fill(.5)},{node:'arm',channel:'scaleX',frames:Array(12).fill(1.2)},{node:'anchor-rightHand',channel:'x',frames:Array(12).fill(10)}];const left={...nested,nodes:[...nested.nodes,{id:'anchor-leftHand',parent:'arm',type:'path',path:[['M',80,300]],fill:null,stroke:null,pivot:[80,300]}],anchors:{...nested.anchors,leftHand:[80,300]}};
   const leftModel=validateAvatarModel({...m,nodes:[...m.nodes,{id:'anchor-leftHand',type:'path',path:[['M',300,300]],fill:null,pivot:[300,300],parent:'arm'}],anchors:{...m.anchors,leftHand:[300,300]}}),leftDesign={...d,avatarModel:leftModel,activeProps:d.activeProps.map(p=>({...p,side:'left'}))};
   const leftA=surfaceSource(leftDesign,0,'focus'),leftB=surfaceSource(leftDesign,6,'focus');
   return {leftA:bounds(leftA,0),leftB:bounds(leftB,0),leftDetailA:bounds(leftA,1),leftDetailB:bounds(leftB,1),anchors,baseRed:bounds(a,0),movedRed:bounds(b,0),baseGreen:bounds(a,1),movedGreen:bounds(b,1),staticA:bounds(surfaceSource(staticDesign,0,'focus'),0),staticB:bounds(surfaceSource(staticDesign,6,'focus'),0),legacyAnchors:resolveAvatarModelAnchors(legacy,6,'focus'),nested:resolveAvatarModelAnchors(nested,-6,'focus'),left:resolveAvatarModelAnchors(validateAvatarModel(left),6,'focus'),unchanged:original===JSON.stringify(m)};
  });
  assert.deepEqual(result.anchors.rightHand,[248,324]);assert.deepEqual(result.anchors.compact,[50,50,400,500]);
  assert(result.baseRed.n>500&&result.baseGreen.n>500);assert.equal(result.movedRed.x0-result.baseRed.x0,48);assert.equal(result.movedRed.y0-result.baseRed.y0,24);assert.deepEqual(result.movedGreen,result.baseGreen);
  assert.equal(result.leftB.x0-result.leftA.x0,48);assert.equal(result.leftB.y0-result.leftA.y0,24);assert.deepEqual(result.leftDetailA,result.leftDetailB);
  assert.deepEqual(result.staticA,result.staticB);assert.deepEqual(result.legacyAnchors.rightHand,[200,300]);assert(result.unchanged);
  const expected=[140+84*Math.cos(.5)-160*Math.sin(.5),140+84*Math.sin(.5)+160*Math.cos(.5)];result.nested.rightHand.forEach((v,i)=>assert(Math.abs(v-expected[i])<1e-8));
  const l=[140-72*Math.cos(.5)-160*Math.sin(.5),140-72*Math.sin(.5)+160*Math.cos(.5)];result.left.leftHand.forEach((v,i)=>assert(Math.abs(v-l[i])<1e-8));
  console.log('Actual composed Canvas: moving held object, stationary simultaneous detail, unchanged static anchors, nested rotation/scale and mirrored hand passed.');
 }finally{await browser?.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
