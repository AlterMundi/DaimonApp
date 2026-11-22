import {portrait,pack} from './engine.mjs';
export const scenes={seed:{title:'Una semilla',frames:32,frame_ms:280,sprout:15,beats:[[0,'arrival'],[4,'notice'],[8,'approach'],[12,'wait'],[15,'shelter'],[20,'celebrate'],[29,'settle']]},'seed-patient':{title:'Una semilla, un poco más de paciencia',frames:32,frame_ms:300,sprout:21,beats:[[0,'arrival'],[4,'notice'],[8,'approach'],[12,'wait'],[21,'shelter'],[26,'celebrate'],[29,'settle']]}};
export function sceneState(id,index){
 const scene=scenes[id];if(!scene)throw Error('Unknown scene');const frame=Math.max(0,Math.min(31,Math.floor(index))),sprout=scene.sprout;
 const action=scene.beats.filter(([at])=>at<=frame).at(-1)[1];
 return {frame,action,growth:Math.max(0,Math.min(1,(frame-sprout)/6)),approach:Math.max(0,Math.min(1,(frame-7)/5))};
}
export function capabilities(body,image){return image?{gesture:'translation',detail:'Retrato estático con desplazamiento y objetos alrededor; sin rig inferido.'}:['core','ribbon','constellation','pocket-dragon','modular-bot','moon-visitor'].includes(body)?{gesture:'body-specific',detail:'Actuación corporal adaptada a esta forma.'}:{gesture:'translation',detail:'Postura y desplazamiento generales; todavía sin gesto específico para esta forma.'};}
export function renderScene(s,id,index,image=null,compact=false){
 const {frame,action,growth,approach}=sceneState(id,index),W=80,H=40,g=Array.from({length:H},()=>Array(W).fill(' '));
 const put=(x,y,c)=>{x=Math.round(x);y=Math.round(y);if(g[y]&&x>=0&&x<W)g[y][x]=c;};
 const stamp=(x,y,text)=>text.split('\n').forEach((r,j)=>[...r].forEach((c,i)=>{if(c!==' ')put(x+i,y+j,c);}));
 const px=64,py=31;const gesture=capabilities(s.body,image).gesture;
 const e=action==='notice'?'curious':action==='approach'?'listening':action==='celebrate'?'delighted':'calm';
 const adapted={...s,sceneActor:true,rigCue:s.rigCue?({notice:'curious',approach:'welcome',wait:'calm',shelter:'welcome',celebrate:'joy',settle:'calm'}[action]||'calm'):undefined,relation:'original',direction:1,aperture:action==='shelter'?1.35:s.aperture};
 const body=image||portrait(adapted,e,frame%12,40,28),lines=body.split('\n');
 // Fit the selected art in a fixed actor box; no body parts are inferred from images.
 const width=Math.max(1,...lines.map(l=>l.length)),scale=Math.min(1,40/width,28/lines.length),dx=4+Math.round(approach*6),dy=6+(action==='wait'?Math.round(Math.sin(frame*.7)):0);
 for(let y=0;y<Math.ceil(lines.length*scale);y++)for(let x=0;x<Math.ceil(width*scale);x++){const c=lines[Math.min(lines.length-1,Math.floor(y/scale))]?.[Math.floor(x/scale)];if(c&&c!==' ')put(dx+x,dy+y,c);}
 stamp(px-4,py+3,'\\_______/\n \\:::::/\n  \\___/');
 if(action==='arrival'){put(px,3+frame*8,'o');}
 else if(!growth){stamp(px-1,py+2,'(o)');}
 else {
  const height=Math.max(1,Math.round(growth*8));for(let i=0;i<height;i++)put(px,py+2-i,'|');
  if(growth>.2)stamp(px-3,py,'\\  |  /');
  if(growth>.45)stamp(px-3,py-3,'\\__|__/');
  if(growth>.8)stamp(px-3,py-8,' _\u002f*\\_\n(  *  )\n \\_*_/');
 }
 if(gesture==='body-specific'&&['wait','shelter','celebrate'].includes(action)){
  if(s.body==='constellation'){
   const p=(frame%6)/6;for(let i=0;i<9;i++){const x=47+i*2,y=29-Math.sin(i/8*Math.PI)*7;put(x,y,i%3===frame%3?'*':'.');}put(48+p*12,25-p*2,'+');
  }else if(s.body==='ribbon'){
   for(let i=0;i<20;i++){const x=43+i,y=29-Math.sin(i/19*Math.PI)*4;put(x,y,i<9?'/':i>12?'\\':'_');}
  }else if(s.body==='pocket-dragon'){
   // Extend one wing membrane as a roof over the seed.
   for(let i=0;i<20;i++){const x=44+i,y=30-Math.sin(i/19*Math.PI)*8;put(x,y,i<9?'/':i>11?'\\':'_');if(i%4===0)put(x,Math.min(30,y+2),':');}
  }else if(s.body==='modular-bot'){
   for(let i=0;i<16;i++){put(44+i,29,'=');if(i%4===0)put(44+i,28,'o');}stamp(59,28,'[ ]');
  }else if(s.body==='moon-visitor'){
   for(let i=0;i<20;i++){const x=44+i,y=30-Math.sin(i/19*Math.PI)*5+Math.sin(i*.6+frame*.4)*.6;put(x,y,i%5===0?':':'~');}put(63,30,'*');
  }else if(s.body==='core'){
   for(let i=0;i<16;i++){const x=46+i,y=29-Math.sin(i/15*Math.PI)*5;put(x,y,i%3===0?':':'.');}
  }
 }
 if(action==='celebrate'){stamp(px-10,py-12,'+');stamp(px+8,py-7,'*');}
 if(action==='wait')stamp(51,33,frame%4<2?'. .':'.');
 const output=compact?g.filter((_,i)=>i%2===0).map(r=>r.filter((_,i)=>i%2===0)):g;
 return output.map(r=>r.join('').replace(/ +$/,'')).join('\n');
}
export function scenePack(s,image=null){
 const base=pack(s,image);const calm=renderScene(s,'seed',31,image);
 const entries={calm:{alt:(s.name||'Daimon')+' junto a una flor; escena artística.',variants:{portrait:{frames:[calm],frame_ms:300},compact:{frames:[renderScene(s,'seed',31,image,true)],frame_ms:300}}}};
 for(const [id,scene] of Object.entries(scenes))entries['scene-'+id]={alt:scene.title+'. El personaje descubre y acompaña una semilla que brota. Animación artística, sin medición de actividad.',variants:{portrait:{frames:Array.from({length:32},(_,i)=>renderScene(s,id,i,image)),frame_ms:scene.frame_ms},compact:{frames:Array.from({length:32},(_,i)=>renderScene(s,id,i,image,true)),frame_ms:scene.frame_ms}}};
 const result={...base,id:base.id+'-theatre',revision:'theatre-1',authorship:'Original seed-scene choreography by Oliva and Ani; '+capabilities(s.body,image).detail,expressions:entries,defaults:Object.fromEntries(['app','cli','telegram'].map(k=>[k,{expression:'calm',variant:k==='app'?'portrait':'compact',columns:k==='app'?80:40,rows:k==='app'?40:20}]))};
 if(JSON.stringify(result).length>262144)throw Error('La colección supera el tamaño admitido. Elegí un avatar con menos detalle.');return result;
}
