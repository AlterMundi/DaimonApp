import {drawPillow} from './pillow.mjs';
import {headwearFit,drawHeadwear} from './headwear.mjs';
export const propCatalog=[{id:'magnifier',name:'Lupa'},{id:'book',name:'Libro'},{id:'flower',name:'Flor'},{id:'star',name:'Estrella'},{id:'flashlight',name:'Linterna'},{id:'paintbrush',name:'Pincel'},{id:'watering-can',name:'Regadera'},{id:'firefly-lantern',name:'Farol de luciérnagas'},{id:'question',name:'Signo ?'},{id:'exclamation',name:'Signo !'},{id:'pillow',name:'Almohada'},{id:'wizard-hat',name:'Sombrero de mago'},{id:'artist-beret',name:'Boina de artista'},{id:'leaf-crown',name:'Corona de hojas'}];
export const propColors={gold:{name:'Miel',ink:'#edbc69',light:'#fff0bd'},jade:{name:'Jade',ink:'#70b4a5',light:'#d2eee0'},lilac:{name:'Lila',ink:'#ad94d3',light:'#e9dcf5'}};
export function resolvePropColor(value){
 if(Object.hasOwn(propColors,value))return propColors[value];
 if(!/^#[0-9a-f]{6}$/i.test(value))throw Error('Invalid accessory color');
 const rgb=[1,3,5].map(i=>parseInt(value.slice(i,i+2),16));
 return {ink:value,light:'#'+rgb.map(v=>Math.round(v+(255-v)*.65).toString(16).padStart(2,'0')).join('')};
}
export const isFloatingProp=id=>['star','question','exclamation'].includes(id);
export const propSlot=id=>isFloatingProp(id)?'floating':['wizard-hat','artist-beret','leaf-crown'].includes(id)?'head':'hand';
export function validateProps(value){
 if(value===undefined)return undefined;
 if(!Array.isArray(value)||value.length>3)throw Error('Elegí un objeto, un sombrero y un detalle.');
 const slots=new Set();return value.map(p=>{
  if(!p||!propCatalog.some(x=>x.id===p.id)||slots.has(propSlot(p.id))||!(Object.hasOwn(propColors,p.color)||/^#[0-9a-f]{6}$/i.test(p.color))||!['left','right'].includes(p.side)||!Number.isFinite(p.size)||p.size<.75||p.size>1.25)throw Error('Hay un accesorio inválido.');
  slots.add(propSlot(p.id));return {id:p.id,color:p.color,side:p.side,size:p.size};
 });
}
export function drawProps(canvas,props=[],frame=0,{body='modular-bot',image=false,anchors=null,style='surface/v2',layer='all'}={}){
 if(!props.length)return;const c=canvas.getContext('2d'),t=((frame%12)+12)%12/12*Math.PI*2;
 for(const prop of props){const slot=propSlot(prop.id),colors=resolvePropColor(prop.color);
 if(slot==='head'){
  const fit=!image&&headwearFit(body,frame,style);if(!fit||layer==='front')continue;
  c.save();c.translate(fit.x,fit.y);c.rotate(fit.angle);const clothScale=fit.width/128*prop.size*(prop.id==='wizard-hat'?.84:1);c.scale(clothScale,clothScale);c.lineJoin='round';c.lineCap='round';drawHeadwear(c,prop.id,colors,frame);c.restore();continue;
 }
 if(layer==='behind')continue;
 const custom=anchors?.[prop.side==='left'?'leftHand':'rightHand'],anchor=custom?(prop.side==='left'?[576-custom[0],custom[1]]:custom):image?[465,567]:({'pocket-dragon':[378,457],'modular-bot':[395,472],'moon-visitor':[407,437],'cloud-axolotl':[386,480],'comet-fox':[379,480],'little-mushroom':[390,476]})[body]||[395,472];
 c.save();if(prop.side==='left'){c.translate(576,0);c.scale(-1,1);}const isPlayObject=['flashlight','paintbrush','watering-can','firefly-lantern'].includes(prop.id),x=isFloatingProp(prop.id)?448:isPlayObject?Math.min(prop.id==='flashlight'?420:445,anchor[0]+38):anchor[0],y=isFloatingProp(prop.id)?171:anchor[1];c.translate(x,y);c.rotate(Math.sin(t)*.05);c.scale(prop.size,prop.size);c.lineJoin='round';c.lineCap='round';c.strokeStyle='#354452';c.lineWidth=4;
 const ellipse=(x,y,rx,ry,fill,stroke=null)=>{c.beginPath();c.ellipse(x,y,rx,ry,0,0,Math.PI*2);c.fillStyle=fill;c.fill();if(stroke){c.strokeStyle=stroke;c.stroke();}};
 if(prop.id==='pillow')drawPillow(c,[0,-35],1,0,colors);
 if(prop.id==='magnifier'){c.beginPath();c.moveTo(0,12);c.lineTo(20,-27);c.strokeStyle=colors.ink;c.lineWidth=13;c.stroke();ellipse(32,-51,29,29,'rgba(177,219,233,0.7)',colors.ink);c.beginPath();c.arc(32,-51,20,3.6,4.9);c.strokeStyle='#edfaff';c.lineWidth=4;c.stroke();}
 if(prop.id==='book'){c.fillStyle=colors.ink;c.beginPath();c.roundRect(-43,-43,86,62,8);c.fill();c.strokeStyle='#40505a';c.lineWidth=3;c.stroke();for(const side of [-1,1]){c.fillStyle=colors.light;c.beginPath();c.moveTo(0,-34);c.quadraticCurveTo(side*18,-43,side*34,-32);c.lineTo(side*34,10);c.quadraticCurveTo(side*17,0,0,10);c.closePath();c.fill();}c.beginPath();c.moveTo(0,-34);c.lineTo(0,12);c.strokeStyle='#ab9078';c.lineWidth=3;c.stroke();}
 if(prop.id==='flower'){c.beginPath();c.moveTo(0,18);c.quadraticCurveTo(-9,-21,8,-50);c.strokeStyle='#69a586';c.lineWidth=7;c.stroke();ellipse(-13,-5,14,6,'#88b99b');for(let i=0;i<5;i++){const a=i/5*Math.PI*2;ellipse(8+Math.cos(a)*17,-58+Math.sin(a)*17,13,13,colors.ink);}ellipse(8,-58,10,10,colors.light);}
 if(prop.id==='star'){const scale=1+Math.sin(t)*.07;c.scale(scale,scale);c.beginPath();for(let i=0;i<10;i++){const a=-Math.PI/2+i*Math.PI/5,r=i%2?14:31;c[i?'lineTo':'moveTo'](Math.cos(a)*r,Math.sin(a)*r);}c.closePath();c.fillStyle=colors.ink;c.fill();c.strokeStyle=colors.light;c.lineWidth=3;c.stroke();ellipse(-6,-9,4,5,colors.light);}


 if(prop.id==='question'||prop.id==='exclamation'){
  // Symbols remain readable on either side, instead of mirroring their glyph.
  if(prop.side==='left')c.scale(-1,1);
  c.translate(0,Math.sin(t)*5);c.strokeStyle=colors.ink;c.lineWidth=11;
  c.beginPath();
  if(prop.id==='question'){c.moveTo(-18,-17);c.bezierCurveTo(-18,-43,24,-45,22,-19);c.bezierCurveTo(20,-4,0,-7,0,9);}
  else{c.moveTo(0,-34);c.lineTo(0,9);}
  c.stroke();ellipse(0,30,6,6,colors.light);
 }
 // Original vector masters; the shared renderer converts every part to glyphs.
 if(prop.id==='flashlight'){
  c.rotate(.72);const glow=.65+.15*Math.sin(t);
  c.fillStyle=`rgba(255,235,157,${.22*glow})`;c.beginPath();c.moveTo(-16,-45);c.lineTo(-39,-100);c.quadraticCurveTo(0,-116,39,-100);c.lineTo(16,-45);c.closePath();c.fill();
  c.fillStyle=colors.ink;c.beginPath();c.roundRect(-15,-35,30,60,9);c.fill();c.strokeStyle='#354452';c.lineWidth=3;c.stroke();
  c.fillStyle=colors.ink;c.beginPath();c.moveTo(-15,-30);c.lineTo(-25,-51);c.quadraticCurveTo(0,-62,25,-51);c.lineTo(15,-30);c.closePath();c.fill();
  ellipse(0,-51,23,9,colors.light);ellipse(0,-51,14,5,'#fff4cf');ellipse(0,-9,4,7,'#4b6271');
 }
 if(prop.id==='paintbrush'){
  c.rotate(-.3);c.fillStyle=colors.ink;c.beginPath();c.roundRect(-7,-30,14,65,7);c.fill();
  c.fillStyle='#c6d9dd';c.beginPath();c.roundRect(-11,-49,22,24,4);c.fill();c.strokeStyle='#76959c';c.lineWidth=3;c.stroke();
  c.fillStyle=colors.light;c.beginPath();c.moveTo(-11,-48);c.bezierCurveTo(-22,-67,-7,-77,0,-89);c.bezierCurveTo(4,-68,22,-66,11,-48);c.closePath();c.fill();
  c.fillStyle='#78c6c1';c.beginPath();c.moveTo(-9,-60);c.quadraticCurveTo(-13,-75,0,-89);c.quadraticCurveTo(3,-77,8,-69);c.quadraticCurveTo(3,-59,-9,-60);c.fill();
  const dy=((frame%12)+12)%12/12*20;ellipse(23,-45+dy,4,6,'#78c6c1');
 }
 if(prop.id==='watering-can'){
  // Open handle, sloping spout and round belly read at thumbnail scale.
  c.strokeStyle=colors.ink;c.lineWidth=9;c.beginPath();c.ellipse(-35,-24,23,25,-.25,0,Math.PI*2);c.stroke();
  c.fillStyle=colors.ink;c.beginPath();c.moveTo(18,-22);c.lineTo(60,-55);c.lineTo(67,-47);c.lineTo(29,7);c.closePath();c.fill();
  c.beginPath();c.roundRect(-31,-39,62,58,17);c.fill();ellipse(0,-37,28,8,colors.light);ellipse(4,-11,20,17,colors.light);ellipse(63,-52,13,6,colors.light);
  for(let i=0;i<3;i++){const phase=(((frame%12)+12)%12/12+i/3)%1;ellipse(68+phase*15+i*5,-42+phase*35,2.5,4,'#97d5e6');}
 }
 if(prop.id==='firefly-lantern'){
  c.strokeStyle=colors.ink;c.lineWidth=5;c.beginPath();c.arc(0,-76,15,Math.PI,Math.PI*2);c.stroke();
  c.fillStyle='rgba(124,188,173,.3)';c.beginPath();c.roundRect(-28,-67,56,74,13);c.fill();c.strokeStyle=colors.ink;c.lineWidth=4;c.stroke();
  c.fillStyle=colors.ink;c.beginPath();c.roundRect(-32,-70,64,12,5);c.roundRect(-32,3,64,12,5);c.fill();
  for(let i=0;i<3;i++){const a=t+i*2.1,x=Math.sin(a)*15,y=-28+Math.cos(a*.999+i)*20;
   ellipse(x,y,8,8,`rgba(255,225,137,${.12+.06*Math.sin(a)})`);ellipse(x,y,3.5,4.5,colors.light);
  }
  c.strokeStyle='#e0f4dc';c.lineWidth=3;c.beginPath();c.moveTo(-20,-51);c.lineTo(-20,-15);c.stroke();
 }
 c.restore();}
}
