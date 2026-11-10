/* Real Canvas raster-layer transforms, poses and clipping; bounded local fixture. */
const assert=require('node:assert/strict'),http=require('node:http'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{const {fixture}=await import('./avatar_layer_model.mjs');
const root=path.resolve(__dirname,'../dashboard/web/avatar-workshop');
const server=http.createServer((req,res)=>{if(req.url==='/'){res.end('<!doctype html><body></body>');return;}
const name=['/model.mjs','/model-runtime.mjs','/raster-model-author.mjs'].includes(req.url)?'skills/ascii-avatar-author/scripts/'+(req.url==='/raster-model-author.mjs'?'raster-model-author.mjs':'model-runtime.mjs'):new URL(req.url,'http://fixture.invalid').pathname.slice(1);
const file=path.resolve(root,name);if(!file.startsWith(root+path.sep)||!file.endsWith('.mjs')||!fs.existsSync(file)){res.writeHead(404).end();return;}
res.setHeader('Content-Type','text/javascript');res.end(fs.readFileSync(file));});
await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;
try{browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE||'/usr/bin/chromium',headless:true});const page=await browser.newPage();await page.goto('http://127.0.0.1:'+server.address().port);
const result=await page.evaluate(async fixture=>{const {packRasterLayers}=await import('/raster-model-author.mjs');const part=document.createElement('canvas');part.width=2;part.height=2;part.getContext('2d').fillRect(0,0,1,1);const packed=packRasterLayers({id:'packed-fixture',name:'Packed',layers:[{id:'head',canvas:part,bounds:[0,0,100,100]}],animations:fixture.animations.calm?Object.fromEntries(['calm','curious','joy','sad','anger','uncertain','focus','welcome'].map(c=>[c,fixture.animations.calm])):{}});if(packed.atlas.palette.length!==217||packed.atlas.pixels.length>90000)throw Error('Packing bound failed');const {validateAvatarModel,renderAvatarModel}=await import('/model.mjs'),m=validateAvatarModel(fixture);const pixel=(c,x,y)=>Array.from(c.getContext('2d').getImageData(x,y,1,1).data),a=renderAvatarModel(m,0,'calm'),b=renderAvatarModel(m,6,'focus'),sleep=renderAvatarModel(m,0,'sleep');
const clip=structuredClone(m);clip.nodes[0].clip=[[100,100],[140,100],[100,140]];const clipped=renderAvatarModel(clip);
// All pixels outside the two moving parts must remain identical.
let outside=0;const aa=a.getContext('2d').getImageData(0,0,576,720).data,bb=b.getContext('2d').getImageData(0,0,576,720).data;for(let y=300;y<720;y++)for(let x=0;x<576;x++)for(let k=0;k<4;k++)if(aa[(y*576+x)*4+k]!==bb[(y*576+x)*4+k])outside++;
const jaw=structuredClone(m);jaw.nodes.push({id:'anchor-mouth',type:'path',path:[['M',300,200]],fill:null,parent:'head',pivot:[300,200]},{id:'jaw',type:'ellipse',cx:300,cy:200,rx:12,ry:5,fill:'#ffffff',parent:'anchor-mouth',pivot:[300,200]});const jm=validateAvatarModel(jaw),original=JSON.stringify(jm),closed=renderAvatarModel(jm,0,'calm',0),open=renderAvatarModel(jm,0,'calm',1);
if(pixel(closed,300,200)[3]!==255||pixel(open,300,200)[3]!==0||pixel(open,300,212)[3]!==255)throw Error('Independent mouth anchor did not follow output level');
if(original!==JSON.stringify(jm)||renderAvatarModel(m,0,'calm',1).toDataURL()!==a.toDataURL()||renderAvatarModel(jm,0,'calm',NaN).toDataURL()!==closed.toDataURL())throw Error('Mouth playback changed saved/legacy drawing');
return {calm:pixel(a,110,110),focus:pixel(b,110,130),sleep:pixel(sleep,110,110),oldHeadEdge:pixel(b,110,101),clipped:pixel(clipped,170,170),fingerMoved:pixel(b,215,150),outside};},fixture);
assert.deepEqual(result.calm,[255,0,0,255]);assert.deepEqual(result.focus,[0,255,0,255]);assert.deepEqual(result.sleep,[0,255,0,255]);assert.equal(result.oldHeadEdge[3],0);assert.equal(result.clipped[3],0);assert.equal(result.fingerMoved[3],0);assert.equal(result.outside,0);
console.log('Actual Canvas: cue texture, relative parent/finger motion, polygon clip, sleep and stable outside pixels passed.');
const framing=await page.evaluate(async model=>{
 const {prepare}=await import('/renderer.mjs'),{fresh,validate,drawFrame}=await import('/experiments/school-avatar-quest/model.mjs'),{paintAscii}=await import('/experiments/school-avatar-quest/color.mjs');
 const design=fresh('model/v1');design.body='custom-model';design.avatarModel=model;
 design.avatarModel.nodes.push({id:'foot',type:'raster',rect:[0,0,2,2],bounds:[240,620,80,80],pivot:[280,660]});
 const saved=JSON.stringify(design),header=document.createElement('div'),stage=document.createElement('div');stage.className='voice-mode-portrait';document.body.append(header,stage);
 const canvas=document.createElement('canvas');canvas.style='width:200px;height:170px';header.append(canvas);const paint=prepare(canvas,design);paint(0);const compact=canvas.toDataURL();
 stage.append(canvas);paint(0);const full=canvas.toDataURL();
 const expected=document.createElement('canvas');expected.style=canvas.style.cssText;document.body.append(expected);const normalized=validate(design);paintAscii(expected,drawFrame(normalized,0,true,false),normalized,0);
 const matches=full===expected.toDataURL();header.append(canvas);paint(0);const restored=canvas.toDataURL()===compact;
 header.remove();stage.remove();expected.remove();return {matches,changed:compact!==full,restored,unchanged:saved===JSON.stringify(design)};
},fixture);
assert.deepEqual(framing,{matches:true,changed:true,restored:true,unchanged:true},'Narrow fullscreen keeps the complete figure and Back restores compact framing');
console.log('Narrow fullscreen: full-body framing, same canvas, compact return and unchanged saved model passed.');
}finally{await browser?.close();await new Promise(r=>server.close(r));}})().catch(e=>{console.error(e);process.exitCode=1;});
