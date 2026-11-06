import {chordArc} from '../avatar-studio/geometry.mjs';
export const dragonExpressions={calm:{name:'En calma',eye:1,inner:0,outer:0,mouth:11,open:0,gaze:0},curious:{name:'Curiosidad',eye:1.12,inner:-7,outer:-4,mouth:5,open:5,gaze:5},joy:{name:'Alegría',eye:.8,inner:-4,outer:-4,mouth:14,open:7,gaze:0},sad:{name:'Tristeza',eye:.82,inner:-14,outer:4,mouth:-12,open:0,gaze:0},anger:{name:'Enojo',eye:.72,inner:12,outer:-6,mouth:-5,open:0,gaze:0},uncertain:{name:'Duda',eye:1,inner:-9,outer:3,mouth:-3,open:0,gaze:-5},focus:{name:'Concentración',eye:.8,inner:5,outer:0,mouth:1,open:0,gaze:3},welcome:{name:'Bienvenida',eye:1.04,inner:-4,outer:-2,mouth:16,open:3,gaze:0}};
// Original vector master and bounded glyph-atlas matcher. No external assets.
export function dragonMaster(frame=0,expression='calm',strength=1){
 const canvas=document.createElement('canvas');canvas.width=576;canvas.height=720;const c=canvas.getContext('2d',{willReadFrequently:true});
 frame=((frame%12)+12)%12;const chosen=dragonExpressions[expression]||dragonExpressions.calm;const cue=Object.fromEntries(Object.entries(chosen).map(([k,v])=>[k,typeof v==='number'?dragonExpressions.calm[k]+(v-dragonExpressions.calm[k])*strength:v]));
 const t=frame/12*Math.PI*2,b=Math.sin(t)*3,wing=Math.sin(t)*7;
 c.translate(288,350+b);c.lineJoin='round';c.lineCap='round';
 const path=(points,fill,stroke='#123c45',width=4)=>{c.beginPath();for(const [op,...v] of points)c[op](...v);if(fill){c.fillStyle=fill;c.fill();}if(stroke){c.strokeStyle=stroke;c.lineWidth=width;c.stroke();}};
 const oval=(x,y,rx,ry,fill,stroke=null,width=3)=>{c.beginPath();c.ellipse(x,y,rx,ry,0,0,Math.PI*2);c.fillStyle=fill;c.fill();if(stroke){c.strokeStyle=stroke;c.lineWidth=width;c.stroke();}};
 const grad=(x,y,r,a,z)=>{const g=c.createRadialGradient(x-r*.3,y-r*.35,2,x,y,r);g.addColorStop(0,a);g.addColorStop(1,z);return g;};
 // Wings and tail remain behind the same face/body silhouette.
 for(const s of [-1,1]){c.save();c.scale(s,1);path([['moveTo',58,45],['bezierCurveTo',100,-55,178,-92-wing,216,-35-wing],['quadraticCurveTo',168,-28,180,38],['quadraticCurveTo',128,8,132,85],['quadraticCurveTo',91,48,65,115],['closePath']],grad(135,10,100,'#a0d1cf','#347884'));path([['moveTo',65,83],['quadraticCurveTo',108,12,208,-37-wing]],null,'#c5dfbd',3);c.restore();}
 path([['moveTo',-41,161],['bezierCurveTo',-142,220,-215,120,-178,82],['bezierCurveTo',-193,177,-101,164,-70,110],['closePath']],grad(-125,150,90,'#79baa3','#22575d'));
 oval(0,113,82,112,grad(-15,70,145,'#a8dac0','#3b8581'),'#143e48',5);oval(0,127,48,76,grad(-8,100,90,'#ffe6ab','#d8a86f'));
 for(const s of [-1,1]){oval(s*54,210,38,22,grad(s*50,200,40,'#9cd4b7','#3d8381'),'#173f48');oval(s*81,106,23,37,grad(s*76,92,40,'#9ed6b6','#397c7d'),'#173f48');for(let j=0;j<3;j++)oval(s*50+j*9-9,212,3,6,'#f1d8ad');}
 // Horns and ears; paired frontal eyes stay clear of texture.
 for(const s of [-1,1]){c.save();c.scale(s,1);path([['moveTo',57,-124],['quadraticCurveTo',99,-185,70,-212],['quadraticCurveTo',65,-171,29,-137],['closePath']],grad(65,-167,65,'#fff2c2','#c99665'));path([['moveTo',95,-86],['quadraticCurveTo',169,-129,154,-69],['quadraticCurveTo',131,-35,92,-42],['closePath']],'#62a99b');c.restore();}
 oval(0,-58,115,105,grad(-22,-95,152,'#b2e2b9','#3e8d88'),'#153e48',5);
 oval(0,2,77,45,grad(-12,-12,95,'#c3e2ac','#75b99a'));
 const blink=frame===10;
 const arc=(a,b,bulge,center,color,width=4)=>{const shape=chordArc(a,b,bulge,center,32);path(shape.points.map((p,i)=>[i?'lineTo':'moveTo',...p]),null,color,width);};
 for(const side of [-1,1]){const x=side*45,eh=38*cue.eye,look=cue.gaze;
  if(blink){arc([x-25,-62],[x+25,-62],4,[x,-20],'#24505a',5);}
  else{oval(x,-62,31,eh,'#eff6d6','#23505a',3);oval(x+look,-57,17,Math.min(25,eh*.72),grad(x,-65,28,'#8c9c5e','#19404b'));oval(x+look,-57,9,Math.min(19,eh*.55),'#102632');oval(x+look-7,-68,6,7,'#fffbe9');oval(x+look+7,-48,2.5,3,'#deecd0');}
  const inner=[x-side*25,-108+cue.inner],outer=[x+side*23,-109+cue.outer];arc(inner,outer,-5,[x,-40],'#245762',5);oval(side*76,-13,15,7,'#cc9d89');oval(side*21,-2,4,3,'#7b8460');
 }
 // The wider joy mouth stays inside the muzzle, including its lower lip.
 const mouthX=expression==='joy'?26+8*strength:26,mouthY=expression==='joy'?20-4*strength:20,mouthInk='#173f39';
 if(cue.open>0){c.beginPath();c.moveTo(-mouthX,mouthY);c.quadraticCurveTo(0,mouthY+cue.mouth*2,mouthX,mouthY);c.quadraticCurveTo(0,mouthY+(cue.mouth+cue.open)*2,-mouthX,mouthY);c.fillStyle=mouthInk;c.fill();}
 arc([-mouthX,mouthY],[mouthX,mouthY],cue.mouth,[0,80],mouthInk,5);
 for(const [x,y] of [[0,-132],[-15,-122],[14,-121],[-94,-40],[94,-40]])oval(x,y,4,6,'#d1e4af');
 c.setTransform(1,0,0,1,0,0);return canvas;
}
export function glyphAtlas(){
 const glyphs=' .,:;\'`-_~|/\\(){}<>+*=!irox%#@MW',w=6,h=10,canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;const c=canvas.getContext('2d',{willReadFrequently:true});c.font='600 10px monospace';c.textBaseline='top';
 return [...glyphs].map(char=>{c.clearRect(0,0,w,h);c.fillStyle='#fff';c.fillText(char,0,-1);const rgba=c.getImageData(0,0,w,h).data,a=Array.from({length:w*h},(_,i)=>rgba[i*4+3]/255);return {char,a,energy:a.reduce((s,v)=>s+v*v,0),coverage:a.reduce((s,v)=>s+v,0)/a.length};});
}
export function convertMaster(master,mode='structure',cols=96,atlas=glyphAtlas(),anchor=null){
 const rows=Math.round(cols*master.height/master.width*.6),w=cols*6,h=rows*10,canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;const c=canvas.getContext('2d',{willReadFrequently:true});c.drawImage(master,0,0,w,h);const px=c.getImageData(0,0,w,h).data,cells=[],lines=[],reference=new Map(anchor?.cells.map(p=>[p.y*cols+p.x,p])||[]);
 for(let y=0;y<rows;y++){let line='';for(let x=0;x<cols;x++){
  const target=[],rgb=[0,0,0];let peak=0,mean=0;
  for(let j=0;j<10;j++)for(let i=0;i<6;i++){const k=((y*10+j)*w+x*6+i)*4,a=px[k+3]/255,l=(px[k]*.2126+px[k+1]*.7152+px[k+2]*.0722)/255*a;target.push(l);peak=Math.max(peak,l);mean+=l;for(let q=0;q<3;q++)rgb[q]+=px[k+q]*a;}
  mean/=60;let chosen=atlas[0];const prior=reference.get(y*cols+x);
  if(peak>.025){if(mode==='tone'){const density=Math.min(.62,mean*.72);chosen=atlas.reduce((best,g)=>Math.abs(g.coverage-density)<Math.abs(best.coverage-density)?g:best,atlas[0]);}
   else{let best=Infinity,priorError=Infinity;for(const g of atlas){if(!g.energy)continue;let dot=0;for(let i=0;i<60;i++)dot+=target[i]/peak*g.a[i];const gain=Math.min(2.5,dot/g.energy);let err=0;for(let i=0;i<60;i++)err+=(target[i]/peak-gain*g.a[i])**2;err+=.12*Math.abs(g.coverage-mean/peak)*60;if(g.char===prior?.char)priorError=err;if(err<best){best=err;chosen=g;}}
    // Retain the reference glyph only for near-equivalent fits; never retain blank silhouettes.
    if(prior&&Math.abs(mean-prior.mean)<.045&&priorError<=best+.8)chosen=atlas.find(g=>g.char===prior.char);
   }
  }
  const alpha=target.reduce((sum,_,i)=>sum+px[((y*10+Math.floor(i/6))*w+x*6+i%6)*4+3]/255,0),color=mode==='tone'?'#c4d2d2':`rgb(${rgb.map(v=>Math.min(255,Math.round(v/Math.max(1,alpha)*1.6))).join(',')})`;
  if(chosen.char!==' ')cells.push({x,y,char:chosen.char,color,mean});line+=chosen.char;
 }lines.push(line.replace(/ +$/,''));}
 return {cols,rows,cells,text:lines.join('\n')};
}
export function paintConverted(canvas,art){const r=canvas.getBoundingClientRect(),d=Math.min(2,devicePixelRatio||1);canvas.width=r.width*d;canvas.height=r.height*d;const c=canvas.getContext('2d');c.scale(d,d);c.fillStyle='#101e2c';c.fillRect(0,0,r.width,r.height);const size=Math.min(r.width/(art.cols*.6+2),r.height/(art.rows+2)),ox=(r.width-art.cols*size*.6)/2,oy=(r.height-art.rows*size)/2;c.font='600 '+size+'px monospace';c.textBaseline='top';for(const p of art.cells){c.fillStyle=p.color;c.fillText(p.char,ox+p.x*size*.6,oy+p.y*size);}}
