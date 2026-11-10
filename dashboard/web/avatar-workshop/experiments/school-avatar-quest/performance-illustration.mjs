import {drawPillow} from './pillow.mjs';
import {magnifierGeometry,lanternOrigin} from './interaction-geometry.mjs';
import {prepareStory,illustrateStory} from './performance-stories.mjs';
import {performanceAnatomy,ease} from './performances.mjs';
import {resolvePropColor} from './props.mjs';
const mix=(a,b,t)=>a+(b-a)*t;
const point=(a,b,t)=>[mix(a[0],b[0],ease(t)),mix(a[1],b[1],ease(t))];
function flight(points,p){for(let i=1;i<points.length;i++)if(p<=points[i][0])return point(points[i-1][1],points[i][1],(p-points[i-1][0])/(points[i][0]-points[i-1][0]));return points.at(-1)[1];}
export function preparePerformance(design,prop,state,bodyFrame){
 if(prop.id==='firefly-lantern'){
  const a=performanceAnatomy[design.body],side=prop.side==='left'?-1:1,bob=Math.sin(bodyFrame/12*Math.PI*2)*3,x=Math.min(445,a.hand[0]+38),origin=lanternOrigin([side<0?576-x:x,a.hand[1]],prop.size,side),landing=[a.landing[0],a.landing[1]+bob],orbit=[288+side*137,Math.max(75,a.eye[1]+bob-108)];
  const [fx]=flight([[0,origin],[.12,origin],[.32,orbit],[.51,landing],[.66,landing],[.85,orbit],[.96,origin],[1,origin]],state.p);
  state.face.gazeOffset=(fx-288)*.045*(1-state.landing*.65);
 }
 return prepareStory(design,prop,state,bodyFrame);
}
export function illustratePerformance(canvas,design,prop,state,bodyFrame){
 const c=canvas.getContext('2d'),anatomy=performanceAnatomy[design.body],side=prop.side==='left'?-1:1,bob=Math.sin(bodyFrame/12*Math.PI*2)*3;
 const anchor=[side<0?576-anatomy.hand[0]:anatomy.hand[0],anatomy.hand[1]],eye=[288+side*anatomy.eye[0],anatomy.eye[1]+bob],nose=[...anatomy.nose];nose[1]+=bob;
 const colors=resolvePropColor(prop.color),reach=state.reach;
 const ellipse=(x,y,rx,ry,fill)=>{c.beginPath();c.ellipse(x,y,rx,ry,0,0,Math.PI*2);c.fillStyle=fill;c.fill();};
 const line=(points,color,width)=>{c.beginPath();for(const [op,...v] of points)c[op](...v);c.strokeStyle=color;c.lineWidth=width;c.lineCap='round';c.lineJoin='round';c.stroke();};
 if(prop.id==='sleep'||prop.id==='pillow'){
  state.actor.rotate*=side;
  if(prop.id==='pillow'){
   const halfHead=({'pocket-dragon':115,'modular-bot':123,'moon-visitor':158,'cloud-axolotl':135,'comet-fox':145,'little-mushroom':175})[design.body],offset=Math.min(435,288+halfHead*.85+30)-288;
   const start=[anchor[0]+side*8,anchor[1]+4],target=[288+side*offset,eye[1]+84];
   drawPillow(c,[mix(start[0],target[0],state.rest),mix(start[1],target[1],state.rest)],prop.size,state.squeeze,colors,-side*.12*state.rest);
  }
  if((design.gestures.find(g=>g.id===design.activeGestureId)?.cue==='sleep')&&state.rest>.1){
   const halfHead=({'pocket-dragon':115,'modular-bot':123,'moon-visitor':158,'cloud-axolotl':135,'comet-fox':145,'little-mushroom':175})[design.body],baseY=design.body==='little-mushroom'?155:eye[1]-105;
   c.save();c.lineCap='round';c.lineJoin='round';for(let i=0;i<3;i++){
    const travel=(state.p*1.25-i*.18+1)%1,k=14+i*6,x=288-side*(halfHead+8+i*24),y=baseY-i*43-travel*18;
    c.globalAlpha=state.rest*Math.sin(travel*Math.PI);c.beginPath();c.moveTo(x-k,y);c.lineTo(x+k,y);c.lineTo(x-k,y+k*1.65);c.lineTo(x+k,y+k*1.65);
    c.strokeStyle='#243d58';c.lineWidth=10;c.stroke();c.strokeStyle='#fff2cd';c.lineWidth=6;c.stroke();
   }c.restore();
  }
 }
 if(prop.id==='magnifier'){
  const start=[anchor[0]+side*32,anchor[1]-51],x=mix(start[0],eye[0],reach)+Math.sin(state.p*Math.PI)*side*10*(1-reach),y=mix(start[1],eye[1],reach),r=(29+reach*31)*prop.size,zoom=1+reach*1.5;
  state.camera.target=[mix(288,eye[0],reach),mix(350,eye[1]+8,reach)];
  const lens=magnifierGeometry([x,y],r,prop.size,side,reach);
  // Capture the actual rendered eye before drawing the lens. No replacement eye.
  const sample=document.createElement('canvas');sample.width=576;sample.height=720;sample.getContext('2d').drawImage(canvas,0,0);
  line([['moveTo',...lens.root],['lineTo',...lens.end]],colors.ink,lens.width);
  c.save();c.beginPath();c.arc(x,y,r,0,Math.PI*2);c.clip();c.fillStyle='#a7d2d455';c.fillRect(x-r,y-r,r*2,r*2);c.drawImage(sample,x-r/zoom,y-r/zoom,r*2/zoom,r*2/zoom,x-r,y-r,r*2,r*2);c.restore();
  c.beginPath();c.arc(x,y,r,0,Math.PI*2);c.strokeStyle=colors.ink;c.lineWidth=6*prop.size;c.stroke();c.beginPath();c.arc(x,y,r-5,3.7,4.7);c.strokeStyle=colors.light;c.lineWidth=3;c.stroke();
 }
 if(prop.id==='flower'){
  const start=[anchor[0]+side*8,anchor[1]-58],amount=Math.min(1,reach*1.16),target=[nose[0]+side*15,nose[1]+10],x=mix(start[0],target[0],amount),y=mix(start[1],target[1],amount),size=prop.size;
  state.camera.target=[288,mix(350,nose[1],reach*.3)];
  line([['moveTo',x-side*8*size,y+76*size],['quadraticCurveTo',x-side*17*size,y+37*size,x,y]],'#69a586',7*size);ellipse(x-side*22*size,y+40*size,14*size,6*size,'#88b99b');
  for(let i=0;i<5;i++){const a=i/5*Math.PI*2,spread=17+state.scatter*(22+state.mood.energy*10),turn=state.scatter*.7;ellipse(x+Math.cos(a+turn)*spread*size,y+Math.sin(a+turn)*spread*size-state.scatter*8,13*size,13*size,colors.ink);}ellipse(x,y,10*size,10*size,colors.light);
  for(let i=0;i<6;i++){const a=i/6*Math.PI*2,dist=12+state.scatter*44;ellipse(x+Math.cos(a)*dist,y+Math.sin(a)*dist-12,2*state.scatter,2*state.scatter,colors.light);}
 }
 if(prop.id==='firefly-lantern'){
  const x=Math.min(445,anatomy.hand[0]+38),y=anatomy.hand[1],sx=side<0?576-x:x;
  c.save();if(side<0){c.translate(576,0);c.scale(-1,1);}c.translate(x,y);c.scale(prop.size,prop.size);
  c.strokeStyle=colors.ink;c.lineWidth=5;c.beginPath();c.arc(0,-76,15,Math.PI,Math.PI*2);c.stroke();c.fillStyle='#7cbcaa44';c.beginPath();c.roundRect(-28,-67,56,74,13);c.fill();c.strokeStyle=colors.ink;c.lineWidth=4;c.stroke();c.fillStyle=colors.ink;c.beginPath();c.roundRect(-32,-70,64,12,5);c.roundRect(-32,3,64,12,5);c.fill();
  line([['moveTo',26,-58],['lineTo',26+state.door*20,-54],['lineTo',26+state.door*20,0],['lineTo',26,3]],colors.light,2);
  for(const [px,py] of [[-11,-37],[9,-14]])ellipse(px,py,3.5,4.5,colors.light);c.restore();
  const landing=[...anatomy.landing];landing[1]+=bob;const orbit=[288+side*137,Math.max(75,eye[1]-108)],origin=lanternOrigin([sx,y],prop.size,side);
  const [fx,fy]=flight([[0,origin],[.12,origin],[.32,orbit],[.51,landing],[.66,landing],[.85,orbit],[.96,origin],[1,origin]],state.p);
  state.face.gazeOffset=(fx-288)*.045*(1-state.landing*.65);state.camera.target=[288,mix(350,eye[1],reach*.35)];
  const glow=state.door*(.85+.15*Math.sin(state.p*Math.PI*10)),halo=c.createRadialGradient(fx,fy,1,fx,fy,20);halo.addColorStop(0,'#fff2ac99');halo.addColorStop(1,'#ffeaa100');c.fillStyle=halo;c.fillRect(fx-20,fy-20,40,40);
  if(state.door>.05){ellipse(fx-6,fy-3,7,2+Math.abs(Math.sin(state.p*Math.PI*24))*3,'#d1ecec99');ellipse(fx+6,fy-3,7,2+Math.abs(Math.sin(state.p*Math.PI*24))*3,'#d1ecec99');}ellipse(fx,fy,4.5+glow,5.5+glow,colors.light);
 }
 illustrateStory(canvas,design,prop,state,bodyFrame);return state;
}
export function stagePerformance(base,state){
 const result=document.createElement('canvas');result.width=576;result.height=720;const c=result.getContext('2d'),[cx,cy]=state.camera.target,z=state.camera.zoom;
 c.translate(288,mix(cy,330,(z-1)/.85));c.scale(z,z);c.translate(-cx,-cy);c.translate(288+state.actor.x,350+state.actor.y);c.rotate(state.actor.rotate);c.scale(state.actor.scaleX,state.actor.scaleY);c.translate(-288,-350);c.drawImage(base,0,0);return result;
}
