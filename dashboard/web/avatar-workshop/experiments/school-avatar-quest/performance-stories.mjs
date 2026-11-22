import {objectPoint} from './interaction-geometry.mjs';
// The remaining hand-object stories share the same clock, acting cues and anatomy.
import {performanceAnatomyFor,ease} from './performances.mjs';
import {resolvePropColor} from './props.mjs';
const mix=(a,b,t)=>a+(b-a)*t;
const along=(points,p)=>{for(let i=1;i<points.length;i++)if(p<=points[i][0]){const t=ease((p-points[i-1][0])/(points[i][0]-points[i-1][0]));return [mix(points[i-1][1][0],points[i][1][0],t),mix(points[i-1][1][1],points[i][1][1],t)];}return points.at(-1)[1];};
export function prepareStory(design,prop,state,frame){
 const a=performanceAnatomyFor(design,frame,design.gestures.find(g=>g.id===design.activeGestureId)?.cue,prop.side==='left'?-1:1),side=prop.side==='left'?-1:1,bob=Math.sin(frame/12*Math.PI*2)*3,hand=[side<0?576-a.hand[0]:a.hand[0],a.hand[1]],eye=[288+side*a.eye[0],a.eye[1]+bob],nose=[a.nose[0],a.nose[1]+bob],p=state.p;
 const story={side,hand,eye,nose};
 if(prop.id==='book'){
  story.book=[mix(hand[0],288+side*17,state.open),mix(hand[1],nose[1]+84,state.open)];
  const origin=objectPoint(story.book,[0,-34],prop.size);story.page=origin;story.visitor=along([[0,origin],[.23,origin],[.34,[288+side*174,nose[1]+14]],[.48,[288+side*132,eye[1]-65]],[.60,[nose[0]+side*21,nose[1]-6]],[.73,[288-side*90,eye[1]-30]],[.88,origin],[1,origin]],p);
 }
 if(prop.id==='paintbrush'){
  story.center=[288+side*167,eye[1]-25];const progress=ease((p-.16)/.36),angle=-progress*Math.PI*2;
  const drawing=[story.center[0]+Math.cos(angle)*40,story.center[1]+Math.sin(angle)*21];
  story.tip=along([[0,[hand[0]-side*24,hand[1]-84]],[.16,[story.center[0]+40,story.center[1]]],[.52,drawing],[.7,[hand[0]-side*24,hand[1]-84]],[1,[hand[0]-side*24,hand[1]-84]]],p);
  if(p>=.16&&p<=.52)story.tip=drawing;
  story.visitor=along([[0,story.center],[.53,story.center],[.68,[288+side*180,eye[1]-105]],[.86,[hand[0]-side*24,hand[1]-84]],[1,story.center]],p);
 }
 if(prop.id==='watering-can'){
  story.root=[288+side*157,620];story.sprout=[mix(story.root[0],nose[0]+side*46,state.grow),620-(620-nose[1]+6)*state.grow];story.sprout[0]+=Math.sin(p*Math.PI*13)*state.tickle*5*state.mood.energy;
 }
 if(prop.id==='flashlight'){
  const held=Math.min(420,a.hand[0]+38);story.handle=[side<0?576-held:held,hand[1]];
  story.visitor=along([[0,[288+side*192,eye[1]+22]],[.37,[288+side*192,eye[1]+22]],[.62,[288+side*172,eye[1]+13]],[.74,[288+side*133,hand[1]-66]],[.91,[288+side*192,eye[1]+22]],[1,[288+side*192,eye[1]+22]]],p);
  const aim=[story.visitor[0]+side*Math.sin(p*Math.PI*5)*(1-state.reveal)*18,story.visitor[1]+Math.cos(p*Math.PI*4)*(1-state.reveal)*22];
  story.angle=Math.atan2((aim[0]-story.handle[0])*side,story.handle[1]-aim[1]);story.beamStart=[story.handle[0]+side*Math.sin(story.angle)*51*prop.size,story.handle[1]-Math.cos(story.angle)*51*prop.size];const ray=[aim[0]-story.handle[0],aim[1]-story.handle[1]],distance=Math.hypot(...ray),length=Math.max(1,(51*prop.size+22)/distance);story.beamEnd=[story.handle[0]+ray[0]*length,story.handle[1]+ray[1]*length];
 }
 if(prop.id==='watering-can'){story.can=[hand[0]+side*38,hand[1]];story.spout=objectPoint(story.can,[62,-43],prop.size,side,state.pour*.58);}
 if(prop.id==='paintbrush'){const offset=objectPoint([0,0],[0,-13],prop.size,1,-side*.22);story.brush=story.tip.map((v,i)=>v-offset[i]);}
 if(story.visitor)state.face.gazeOffset=(story.visitor[0]-288)*.038;
 else if(story.sprout)state.face.gazeOffset=(story.sprout[0]-288)*.028;
 state.story=story;return state;
}
export function illustrateStory(canvas,design,prop,state,frame){
 if(!['book','paintbrush','watering-can','flashlight'].includes(prop.id))return;
 const c=canvas.getContext('2d'),color=resolvePropColor(prop.color),s=state.story,side=s.side,p=state.p,size=prop.size;
 const ellipse=(x,y,rx,ry,fill)=>{c.beginPath();c.ellipse(x,y,rx,ry,0,0,Math.PI*2);c.fillStyle=fill;c.fill();};
 const path=(points,fill=null,stroke=null,width=3)=>{c.beginPath();for(const [op,...v] of points)c[op](...v);if(fill){c.fillStyle=fill;c.fill();}if(stroke){c.strokeStyle=stroke;c.lineWidth=width;c.lineCap='round';c.lineJoin='round';c.stroke();}};
 if(prop.id==='book'){
  const [x,y]=s.book,open=state.open;
  const glow=c.createRadialGradient(...s.page,2,...s.page,90);glow.addColorStop(0,`rgba(255,226,165,${open*.18})`);glow.addColorStop(1,'#ffe2a500');c.fillStyle=glow;c.fillRect(s.page[0]-90,s.page[1]-90,180,180);
  c.save();c.translate(x,y);c.scale(size,size);c.fillStyle=color.ink;c.beginPath();c.roundRect(-23-open*26,-39,46+open*52,62,7);c.fill();
  for(const sign of [-1,1]){const width=16+open*25;path([['moveTo',0,-34],['quadraticCurveTo',sign*width*.6,-45,sign*width,-30],['lineTo',sign*width,14],['quadraticCurveTo',sign*width*.6,3,0,13],['closePath']],color.light);for(let j=0;j<3;j++)path([['moveTo',sign*7,-21+j*10],['quadraticCurveTo',sign*width*.55,-26+j*10,sign*(width-5),-20+j*10]],null,'#bfac91',1.8);}
  path([['moveTo',0,-33],['lineTo',0,15]],null,'#92796e',3);c.restore();
  if(state.release>.01){const [bx,by]=s.visitor,flap=.25+.75*Math.abs(Math.sin(p*Math.PI*(8+state.mood.energy*4))),scale=state.release*(1.2+.35*state.mood.energy);
   c.save();c.translate(bx,by);c.scale(scale,scale);for(const sign of [-1,1]){path([['moveTo',0,0],['bezierCurveTo',sign*26*flap,-30,sign*34*flap,-6,sign*13*flap,3],['bezierCurveTo',sign*34*flap,25,sign*4*flap,25,0,0]],color.ink,color.light,2);}ellipse(0,0,3,12,'#809eac');path([['moveTo',-1,-10],['quadraticCurveTo',-11,-22,-13,-16],['moveTo',1,-10],['quadraticCurveTo',11,-22,13,-16]],null,color.light,2);c.restore();
  }
 }
 if(prop.id==='paintbrush'){
  const [cx,cy]=s.center,progress=Math.min(1,ease((p-.16)/.36)),fade=(1-state.fish)*state.stroke;
  if(fade>.01){c.save();c.globalAlpha=fade;const points=[];for(let i=0;i<=Math.ceil(progress*36);i++){const a=-Math.min(i/36,progress)*Math.PI*2;points.push([i?'lineTo':'moveTo',cx+Math.cos(a)*40,cy+Math.sin(a)*21]);}path(points,null,'#8cd9d3',5);c.restore();}
  if(state.fish>.01){const [fx,fy]=s.visitor;c.save();c.translate(fx,fy);c.scale(side*state.fish,state.fish);const wag=Math.sin(p*Math.PI*(9+state.mood.energy*5))*5;path([['moveTo',-29,0],['quadraticCurveTo',4,-34,40,0],['quadraticCurveTo',4,34,-29,0],['lineTo',-52,-20+wag],['quadraticCurveTo',-45,0,-52,20+wag],['closePath']],color.light,'#38556c',3);ellipse(24,-3,4,5,'#344c65');path([['moveTo',1,-13],['quadraticCurveTo',-10,0,1,13]],null,color.ink,3);c.restore();}
  const [x,y]=s.brush;c.save();c.translate(x,y);c.rotate(-side*.22);c.scale(size,size);path([['moveTo',0,2],['lineTo',0,78]],null,color.ink,11);c.fillStyle='#c6d9dd';c.beginPath();c.roundRect(-9,16,18,22,4);c.fill();path([['moveTo',-9,17],['quadraticCurveTo',-14,-2,0,-13],['quadraticCurveTo',12,2,9,17],['closePath']],'#8cd9d3');c.restore();
  if(p>.84&&p<.96)ellipse(x+8,y+10,4,6,color.light);
 }
 if(prop.id==='watering-can'){
  const [x,y]=s.can;
  c.save();c.translate(x,y);c.scale(side*size,size);c.rotate(state.pour*.58);
  path([['moveTo',-25,-34],['bezierCurveTo',-70,-70,-71,10,-25,2]],null,color.ink,8);
  path([['moveTo',18,-18],['lineTo',58,-47],['lineTo',66,-37],['lineTo',28,11],['closePath']],color.ink);
  c.fillStyle=color.ink;c.beginPath();c.roundRect(-31,-38,62,58,17);c.fill();ellipse(0,-36,27,8,color.light);ellipse(4,-9,20,17,color.light);ellipse(62,-43,12,5,color.light);c.restore();
  const dropStart=s.spout;if(state.pour>.01)for(let i=0;i<7;i++){const q=(p*5+i/7)%1;ellipse(mix(dropStart[0],s.root[0],q)+Math.sin(q*Math.PI)*side*9,mix(dropStart[1],s.root[1]-6,q),2.6*state.pour,4.5*state.pour,'#9ad7e5');}
  const [rx,ry]=s.root;ellipse(rx,ry,8,4,'#d3b38e');
  if(state.grow>.01){const [tx,ty]=s.sprout,cx=rx+side*25,cy=ry-(ry-ty)*.6;path([['moveTo',rx,ry],['quadraticCurveTo',cx,cy,tx,ty]],null,'#78b993',8);
   for(const q of [.3,.61,.85]){const lx=(1-q)**2*rx+2*(1-q)*q*cx+q*q*tx,ly=(1-q)**2*ry+2*(1-q)*q*cy+q*q*ty,leafSide=q===.61?-side:side;path([['moveTo',lx,ly],['bezierCurveTo',lx+leafSide*42*state.grow,ly-38*state.grow,lx+leafSide*48*state.grow,ly+7*state.grow,lx,ly],['closePath']],'#b9e3a5','#699d82',2);}
   ellipse(tx,ty,8*state.grow,11*state.grow,color.light);
  }
 }
 if(prop.id==='flashlight'){
  // Dimming is local to the existing authored actor. The beam points outward.
  c.save();c.globalCompositeOperation='source-atop';c.fillStyle=`rgba(5,17,31,${state.dim})`;c.fillRect(0,0,576,720);c.restore();
  const [hx,hy]=s.handle,[sx,sy]=s.beamStart,[ex,ey]=s.beamEnd,dx=ex-sx,dy=ey-sy,len=Math.hypot(dx,dy),nx=-dy/len,ny=dx/len,half=38*size;
  const light=c.createLinearGradient(sx,sy,ex,ey);light.addColorStop(0,'#fff2b766');light.addColorStop(1,`rgba(255,241,172,${.05+state.reach*.23})`);
  path([['moveTo',sx-nx*12,sy-ny*12],['lineTo',ex-nx*half,ey-ny*half],['quadraticCurveTo',ex+dx*.12,ey+dy*.12,ex+nx*half,ey+ny*half],['lineTo',sx+nx*12,sy+ny*12],['closePath']],light);
  c.save();c.translate(hx,hy);c.scale(side*size,size);c.rotate(s.angle);c.fillStyle=color.ink;c.beginPath();c.roundRect(-14,-35,28,60,8);c.fill();path([['moveTo',-14,-30],['lineTo',-25,-51],['quadraticCurveTo',0,-61,25,-51],['lineTo',14,-30],['closePath']],color.ink);ellipse(0,-51,23,8,color.light);ellipse(0,-8,4,7,'#526781');c.restore();
  if(state.reveal>.01){const [vx,vy]=s.visitor;c.save();c.globalAlpha=state.reveal;const flap=Math.abs(Math.sin(p*Math.PI*25));ellipse(vx-11,vy,14,5+flap*5,'#9ec9c0');ellipse(vx+11,vy,14,5+flap*5,'#9ec9c0');ellipse(vx,vy+3,8,13,'#448f85');ellipse(vx,vy+9,5,6,color.ink);ellipse(vx-3,vy-4,2.5,3.5,'#273d58');ellipse(vx+3,vy-4,2.5,3.5,'#273d58');c.restore();}
  const eyes=Math.max(0,state.reach-state.reveal*.6);if(eyes>.01){c.save();c.globalAlpha=eyes;ellipse(s.visitor[0]-5,s.visitor[1]-4,2.7,3.7,'#fff6cc');ellipse(s.visitor[0]+5,s.visitor[1]-4,2.7,3.7,'#fff6cc');c.restore();}
 }
}
