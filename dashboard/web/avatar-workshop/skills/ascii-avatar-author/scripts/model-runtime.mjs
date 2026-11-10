// Inert, bounded avatar drawing/rig contract; browser rendering and Node validation share this module.
export const expressionIds=['calm','curious','joy','sad','anger','uncertain','focus','welcome'];
const atlasCache=new WeakMap();
const channels=['x','y','rotate','scaleX','scaleY'],commands={M:2,L:2,Q:4,C:6,Z:0};
export function validateAvatarModel(input){
 const fail=()=>{throw Error('El modelo de avatar no cumple el formato admitido.');};
 const layered=input?.schema==='ascii-avatar-model/v2',cues=layered?[...expressionIds,'sleep']:expressionIds;
 if(!input||!['ascii-avatar-model/v1','ascii-avatar-model/v2'].includes(input.schema)||typeof input.id!=='string'||! /^[\w-]{8,80}$/.test(input.id)||typeof input.name!=='string'||input.name.length>60||!Array.isArray(input.nodes)||!input.nodes.length||input.nodes.length>64)fail();
 let total=0;const finite=(v,a,b)=>{if(!Number.isFinite(v)||v<a||v>b)fail();return v;};
 let atlas;
 if(layered){const a=input.atlas;if(!a||!Number.isInteger(a.width)||!Number.isInteger(a.height)||a.width<1||a.height<1||a.width>256||a.height>256||!Array.isArray(a.palette)||!a.palette.length||a.palette.length>256||a.palette.some(v=>typeof v!=='string'||!/^#[0-9a-fA-F]{8}$/.test(v))||typeof a.pixels!=='string'||a.pixels.length!==4*Math.ceil(a.width*a.height/3)||! /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(a.pixels))fail();let bytes;try{bytes=atob(a.pixels);}catch{fail();}if(bytes.length!==a.width*a.height||btoa(bytes)!==a.pixels||Array.from(bytes).some(v=>v.charCodeAt(0)>=a.palette.length))fail();atlas={width:a.width,height:a.height,palette:[...a.palette],pixels:a.pixels};}
 const rectangle=(v,source)=>{if(!Array.isArray(v)||v.length!==4)fail();const r=v.map(x=>finite(x,0,source?256:720));if(source&&r.some(x=>!Number.isInteger(x)))fail();const [x,y,w,h]=r;if(w<=0||h<=0||x+w>(source?atlas.width:576)||y+h>(source?atlas.height:720))fail();return r;};
 const color=v=>{if(v===null)return null;if(typeof v!=='string'||!/^#[0-9a-fA-F]{6}$/.test(v))fail();return v;};
 const paint=v=>{if(v===null||typeof v==='string')return color(v);if(!v||v.type!=='radial'||!Array.isArray(v.stops)||v.stops.length<2||v.stops.length>8)fail();let previous=-1;const stops=v.stops.map(s=>{if(!Array.isArray(s)||s.length!==2||typeof s[1]!=='string'||s[0]<previous)fail();previous=finite(s[0],0,1);return [previous,color(s[1])];});return {type:'radial',x:finite(v.x,0,576),y:finite(v.y,0,720),r:finite(v.r,1,500),stops};};
 const geometry=(v,type,partial=false)=>{const r={};if(type==='raster'){if(!partial||v.rect!==undefined)r.rect=rectangle(v.rect,true);if(!partial||v.bounds!==undefined)r.bounds=rectangle(v.bounds,false);if(v.clip!==undefined){if(!Array.isArray(v.clip)||v.clip.length<3||v.clip.length>64)fail();r.clip=v.clip.map(p=>{if(++total>4096||!Array.isArray(p)||p.length!==2)fail();return p.map(x=>finite(x,0,720));});}return r;}for(const k of type==='ellipse'?['cx','cy','rx','ry']:[]){if(partial&&v[k]===undefined)continue;r[k]=finite(v[k],k==='rx'||k==='ry'?.5:0,k==='rx'||k==='ry'?288:720);}
 if(type==='path'&&(!partial||v.path!==undefined)){if(!Array.isArray(v.path)||!v.path.length||v.path.length>128)fail();r.path=v.path.map(row=>{if(!Array.isArray(row)||!Object.hasOwn(commands,row[0])||row.length!==commands[row[0]]+1)fail();if(++total>4096)fail();return [row[0],...row.slice(1).map(v=>finite(v,0,720))];});if(r.path[0][0]!=='M')fail();}
 for(const k of ['fill','stroke'])if(v[k]!==undefined)r[k]=k==='fill'?paint(v[k]):color(v[k]);if(v.width!==undefined)r.width=finite(v.width,.5,20);return r;};
 const ids=new Set(),nodes=input.nodes.map(v=>{if(!v||typeof v.id!=='string'||! /^[\w-]{1,40}$/.test(v.id)||ids.has(v.id)||!(layered?['path','ellipse','raster']:['path','ellipse']).includes(v.type))fail();ids.add(v.id);const r={id:v.id,type:v.type,...geometry(v,v.type)};if(v.parent!==undefined){if(typeof v.parent!=='string')fail();r.parent=v.parent;}if(v.pivot!==undefined&&(!Array.isArray(v.pivot)||v.pivot.length!==2))fail();r.pivot=(v.pivot??[288,350]).map(x=>finite(x,0,720));if(r.pivot.length!==2)fail();if(v.poses!==undefined){r.poses={};for(const [cue,pose] of Object.entries(v.poses)){if(!cues.includes(cue)||!pose||typeof pose!=='object')fail();r.poses[cue]=geometry(pose,v.type,true);}}return r;});
 const byId=new Map(nodes.map(n=>[n.id,n]));for(const n of nodes){let p=n,seen=new Set();while(p.parent){if(seen.has(p.id)||seen.size>=8||!byId.has(p.parent))fail();seen.add(p.id);p=byId.get(p.parent);}}
 const animations={};for(const [cue,tracks] of Object.entries(input.animations||{})){if(!cues.includes(cue)||!Array.isArray(tracks)||tracks.length>128)fail();const targets=new Set();animations[cue]=tracks.map(t=>{if(!byId.has(t.node)||!channels.includes(t.channel)||!Array.isArray(t.frames)||t.frames.length!==12||targets.has(t.node+':'+t.channel))fail();targets.add(t.node+':'+t.channel);return {node:t.node,channel:t.channel,frames:t.frames.map(v=>finite(v,t.channel.startsWith('scale')?.1:t.channel==='rotate'?-.7:-60,t.channel.startsWith('scale')?2:t.channel==='rotate'?.7:60))};});}
 for(const cue of expressionIds)if(!animations[cue]?.length)fail();
 const anchors={};for(const [k,v] of Object.entries(input.anchors||{})){if(!['rightHand','leftHand','compact'].includes(k)||!Array.isArray(v)||v.length!==(k==='compact'?4:2))fail();anchors[k]=v.map(x=>finite(x,0,720));if(k==='compact'&&(v[2]<100||v[3]<100||v[0]+v[2]>576||v[1]+v[3]>720))fail();}
 return {schema:input.schema,id:input.id,name:input.name,nodes,animations,anchors,...(layered?{atlas}:{})};
}
// An inert node named anchor-leftHand/anchor-rightHand explicitly attaches the
// existing rest-space anchor to its hierarchy. Models without that node retain
// their original static anchors; no schema or saved normalization changes.
export function resolveAvatarModelAnchors(model,frame=0,cue='calm'){
 const anchors={...model.anchors},map=new Map(model.nodes.map(n=>[n.id,n])),f=((frame%12)+12)%12,tracks=model.animations[cue]||model.animations.calm||[];
 for(const key of ['leftHand','rightHand']){
  let node=map.get('anchor-'+key);if(!node||!anchors[key])continue;
  let [x,y]=anchors[key];
  while(node){
   const v={x:0,y:0,rotate:0,scaleX:1,scaleY:1};for(const t of tracks)if(t.node===node.id)v[t.channel]=t.frames[f];
   const [px,py]=node.pivot,dx=(x-px)*v.scaleX,dy=(y-py)*v.scaleY,c=Math.cos(v.rotate),s=Math.sin(v.rotate);
   x=px+v.x+dx*c-dy*s;y=py+v.y+dx*s+dy*c;node=node.parent?map.get(node.parent):null;
  }
  anchors[key]=[x,y];
 }
 return anchors;
}
export function renderAvatarModel(model,frame=0,cue='calm',speechLevel=0){
 const level=Number.isFinite(speechLevel)?Math.round(Math.min(1,Math.max(0,speechLevel))*4)/4:0;
 const canvas=document.createElement('canvas');canvas.width=576;canvas.height=720;const c=canvas.getContext('2d'),f=((frame%12)+12)%12,tracks=model.animations[cue]||model.animations.calm||[],map=new Map(model.nodes.map(n=>[n.id,n]));
 const transforms=node=>{if(node.parent)transforms(map.get(node.parent));const values={x:0,y:0,rotate:0,scaleX:1,scaleY:1};for(const t of tracks)if(t.node===node.id)values[t.channel]=t.frames[f];if(node.id==='anchor-mouth'&&node.type==='path'&&!node.fill&&!node.stroke){values.y+=12*level;values.rotate+=.035*level;}const [x,y]=node.pivot;c.translate(x+values.x,y+values.y);c.rotate(values.rotate);c.scale(values.scaleX,values.scaleY);c.translate(-x,-y);};
 for(const node of model.nodes){const n={...node,...node.poses?.[cue]};c.save();transforms(node);if(n.type==='raster'){if(n.clip){c.beginPath();n.clip.forEach(([x,y],i)=>i?c.lineTo(x,y):c.moveTo(x,y));c.closePath();c.clip();}c.imageSmoothingEnabled=false;c.drawImage(rasterAtlas(model),...n.rect,...n.bounds);c.restore();continue;}c.beginPath();if(n.type==='ellipse')c.ellipse(n.cx,n.cy,n.rx,n.ry,0,0,Math.PI*2);else for(const [cmd,...v] of n.path)c[({M:'moveTo',L:'lineTo',Q:'quadraticCurveTo',C:'bezierCurveTo',Z:'closePath'})[cmd]](...v);if(n.fill){if(typeof n.fill==='string')c.fillStyle=n.fill;else{const g=c.createRadialGradient(n.fill.x-n.fill.r*.3,n.fill.y-n.fill.r*.35,1,n.fill.x,n.fill.y,n.fill.r);for(const [at,color] of n.fill.stops)g.addColorStop(at,color);c.fillStyle=g;}c.fill();}if(n.stroke){c.strokeStyle=n.stroke;c.lineWidth=n.width||3;c.lineJoin='round';c.lineCap='round';c.stroke();}c.restore();}return canvas;
}

// One bounded decoded atlas per live normalized model; no URLs, codecs or async fetches.
function rasterAtlas(model){
 let canvas=atlasCache.get(model);if(canvas)return canvas;
 const a=model.atlas,bytes=atob(a.pixels);canvas=document.createElement('canvas');canvas.width=a.width;canvas.height=a.height;
 const c=canvas.getContext('2d'),image=c.createImageData(a.width,a.height),palette=a.palette.map(v=>[1,3,5,7].map(i=>parseInt(v.slice(i,i+2),16)));
 for(let i=0;i<bytes.length;i++)image.data.set(palette[bytes.charCodeAt(i)],i*4);
 c.putImageData(image,0,0);atlasCache.set(model,canvas);return canvas;
}
