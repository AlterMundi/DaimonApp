import {chordArc} from './geometry.mjs';
import {localPose} from './rig.mjs';
export const childBodies=['pocket-dragon','modular-bot','moon-visitor','cloud-axolotl','comet-fox','little-mushroom'];
const faceCues={
 calm:{eyes:1,brow:0,mouth:.055,open:0,gaze:0},
 curious:{eyes:1.15,brow:-.04,mouth:.025,open:.035,gaze:.035},
 joy:{eyes:.8,brow:-.015,mouth:.12,open:.06,gaze:0},
 sad:{eyes:.85,brow:-.07,mouth:-.065,open:0,gaze:0},
 anger:{eyes:.78,brow:.065,mouth:-.035,open:0,gaze:0},
 uncertain:{eyes:1,brow:-.055,mouth:-.02,open:.015,gaze:-.035},
 focus:{eyes:.82,brow:.025,mouth:.005,open:0,gaze:.015},
 welcome:{eyes:1.05,brow:-.015,mouth:.085,open:.015,gaze:0}
};
export function characterFrame(s,frame=0,cols=96,rows=64){
 const W=cols,H=rows,compact=cols<48&&!s.sceneActor,headY=s.body==='little-mushroom'?.13:-.25;
 const grid=Array.from({length:H},()=>Array(W).fill(' ')),roles=Array.from({length:H},()=>Array(W).fill(null)),depths=Array.from({length:H},()=>Array(W).fill(0)),scores=Array.from({length:H},()=>Array(W).fill(-1)),arcs=[],landmarks=[[0,headY]];
 const t=((frame%12)+12)%12/12*Math.PI*2,rig=localPose(s.rigCue,frame,s.rigStrength??1),cue=faceCues[s.rigCue]||faceCues.calm;
 const strength=s.rigCue?Math.max(0,Math.min(1,s.rigStrength??1)):0,mix=(a,b)=>a+(b-a)*strength;
 const breath=Math.sin(t)*.008,blink=(frame%12===10)? .09:1;
 const eyes=mix(1,cue.eyes)*blink,mouth=mix(.055,cue.mouth),brow=mix(0,cue.brow),gaze=mix(0,cue.gaze);
 const eyeY=headY+.015,ex=s.body==='little-mushroom'?.13:.205,erx=s.body==='little-mushroom'?.069:.09,ery=s.body==='little-mushroom'?.1:.125;
 const fullness=.9+.1*(Number(s.aperture)||1),tilt=(Number(s.curvature)||0)*.035;
 const zoom=compact?(s.body==='little-mushroom'?1.1:s.body==='cloud-axolotl'?1.35:1.55):1,cx=(W-1)/2,cy=(H-1)/2;
 const point=([x,y])=>[cx+(x*fullness+y*tilt)*W*.43*zoom,cy+(y-(compact?headY:0)+breath)*H*.43*zoom];
 function put(x,y,char,role='contour',z=1,score=1){x=Math.round(x);y=Math.round(y);if(grid[y]&&x>=0&&x<W&&score>=scores[y][x]){grid[y][x]=char;roles[y][x]=role;depths[y][x]=z;scores[y][x]=score;}}
 // Dense sampling and subcell proximity select round ASCII strokes. No block glyphs.
 function path(points,role='contour',z=1){
  const midX=point([points.reduce((sum,p)=>sum+p[0],0)/points.length,0])[0];
  for(let i=1;i<points.length;i++){
   const a=point(points[i-1]),b=point(points[i]),dx=b[0]-a[0],dy=b[1]-a[1],n=Math.max(1,Math.ceil(Math.hypot(dx,dy)*6));
   const char=Math.abs(dy)>Math.abs(dx)*1.35?((a[0]+b[0])/2<midX?'(':')'):Math.abs(dx)>Math.abs(dy)*2?(dy<0?'\'':'_'):dx*dy>0?'\\':'/';
   for(let j=0;j<=n;j++){const x=a[0]+dx*j/n,y=a[1]+dy*j/n,d=Math.hypot(x-Math.round(x),y-Math.round(y));put(x,y,role==='weave'?(s.material==='mist'?'.':s.material==='fiber'?':':char):d>.64?'.':char,role,z,1-d);}
  }
 }
 const sample=(fn,n=150)=>Array.from({length:n+1},(_,i)=>fn(i/n));
 function ellipse(x,y,rx,ry,role='contour',z=1){path(sample(u=>[x+rx*Math.cos(u*Math.PI*2),y+ry*Math.sin(u*Math.PI*2)]),role,z);}
 function curve(id,a,c,bulge,center,role='contour',z=1){const arc=chordArc(a,c,bulge,center,48);arcs.push({id,...arc});path(arc.points,role,z);return arc;}
 function dot(x,y,char,role='spark'){const p=point([x,y]);put(...p,char,role,1,8);}
 function ovalFill(x,y,rx,ry,role='spark',clear=false){const a=point([x-rx,y-ry]),b=point([x+rx,y+ry]),center=point([x,y]);for(let py=Math.floor(a[1]);py<=Math.ceil(b[1]);py++)for(let px=Math.floor(a[0]);px<=Math.ceil(b[0]);px++){const q=((px-center[0])/Math.max(.5,(b[0]-a[0])/2))**2+((py-center[1])/Math.max(.5,(b[1]-a[1])/2))**2;if(q<1)put(px,py,clear?' ':q<.5?'@':':',role,1,clear?6:5);}}
 const line=(a,b,role='contour',z=1)=>path([a,b],role,z);
 if(!compact){
  if(s.body==='pocket-dragon'){
   for(const side of [-1,1]){const spread=1+rig.spread*.25,tip=[side*.87*spread,-.25-rig.lift*.25];curve('wing-'+side,[side*.27,.1],tip,-.15,[0,.35],'weave',.4);path([tip,[side*.74,.03],[side*.81,.18],[side*.48,.13],[side*.27,.25]],'weave',.4);}
   curve('tail',[-.12,.56],[-.72,.52],-.24,[-.4,.2],'contour',.6);ellipse(-.73,.49,.08,.1,'spark',.7);
  }
  if(s.body==='comet-fox'){
   curve('tail', [.22,.55],[.79,.24],-.35,[.1,.1],'contour',.5);curve('tail-return',[.79,.24],[.25,.69],-.12,[.1,.1],'weave',.5);line([.72,.27],[.52,.5],'spark',.6);
  }
  if(s.body==='moon-visitor'){
   for(let i=-2;i<=2;i++){const root=[i*.16,.13],tip=[i*(.18+rig.spread*.06)+Math.sin(t+i)*.025,.82-rig.lift*.12];curve('tendril-'+i,root,tip,.055+rig.curl*.08,[i<0?.5:-.5,.3],'contour',.7);ellipse(tip[0],tip[1],.045,.035,'spark');}
  }else{
   ellipse(0,.46,s.body==='little-mushroom'?.28:.29,.33,'contour',.7);ellipse(0,.48,.16,.19,'weave',.7);
   for(const side of [-1,1]){ellipse(side*.2,.75,.13,.075,'contour');const hand=[side*(.36+rig.spread*.15),.38+rig.droop*.28-rig.lift*.2];curve('arm-'+side,[side*.23,.33],hand,.05,[0,.6],'contour',.8);ellipse(...hand,.075,.09,'spark');}
  }
 }
 if(s.body==='cloud-axolotl'){
  for(const side of [-1,1])for(let i=-1;i<=1;i++){
   const root=[side*.45,headY+i*.13],tip=[side*(.75+(.07-Math.abs(i)*.03)),headY+i*.25-rig.lift*.12];
   curve('gill-'+side+'-'+i,root,tip,-.04,[0,headY+.22],'spark',.6);ellipse(tip[0],tip[1],.08,.07,'weave',.6);
  }
 }
 if(s.body==='pocket-dragon'){
  for(const side of [-1,1]){curve('horn-'+side,[side*.23,-.59],[side*.27,-.94],-.06,[0,-.5],'spark');curve('ear-'+side,[side*.42,-.45],[side*.69,-.52],-.1,[0,0],'weave',.7);}
 }
 if(s.body==='comet-fox'){
  for(const side of [-1,1]){curve('ear-out-'+side,[side*.43,-.42],[side*.47,-.86],-.035,[0,-.2]);curve('ear-in-'+side,[side*.47,-.86],[side*.12,-.54],-.04,[0,-.2],'spark',.8);}
 }
 if(s.body==='modular-bot'){
  const x=rig.look*.06,y=headY;
  // A rounded shell, not a hard rectangle; the face has its own empty panel.
  path(sample(u=>{const a=u*Math.PI*2;return [x+.56*Math.sign(Math.cos(a))*Math.abs(Math.cos(a))**.5,y+.39*Math.sign(Math.sin(a))*Math.abs(Math.sin(a))**.5];}));
  curve('antenna',[0,-.65],[rig.asym*.12,-.94],rig.curl*.06,[.3,-.3],'weave');ellipse(rig.asym*.12,-.96,.055,.045,'spark');
  for(const side of [-1,1]){ellipse(side*.59,headY,.045,.11,'weave');dot(side*.43,headY-.22,'+');}
 }else if(s.body==='little-mushroom'){
  ellipse(0,.13,.31,.39);
  path(sample(u=>[-.75*Math.cos(u*Math.PI),-.17-.62*Math.sin(u*Math.PI)]));curve('cap-rim',[.75,-.17],[-.75,-.17],-.10,[0,-.6],'spark');
  for(const [x,y,rx,ry] of [[-.35,-.4,.10,.07],[.18,-.52,.13,.08],[.46,-.3,.07,.05]])ellipse(x,y,rx,ry,'weave',.8);
 }else if(s.body==='moon-visitor'){
  path(sample(u=>[-.59*Math.cos(u*Math.PI),.04-.71*Math.sin(u*Math.PI)]));
  path(sample(u=>[-.59+u*1.18,.04+.04*Math.cos(u*Math.PI*6)],80),'weave',.7);
  ellipse(-.22,-.49,.05,.025,'weave');ellipse(.22,-.49,.05,.025,'weave');
 }else if(s.body==='comet-fox'){
  path(sample(u=>{const a=u*Math.PI*2,r=a>0&&a<Math.PI?.43:.54;return [Math.cos(a)*r,headY+Math.sin(a)*.36];}));
 }else ellipse(0,headY,s.body==='cloud-axolotl'?.56:.51,.36);
 // Reserve a face window: no membrane, body texture or ornament crosses eyes/mouth.
 const faceWidth=s.body==='little-mushroom'?.25:.4,faceHeight=s.body==='little-mushroom'?.25:.27;
 const clearA=point([-faceWidth,headY-faceHeight*.65]),clearB=point([faceWidth,headY+faceHeight]);
 for(let y=Math.floor(clearA[1]);y<=Math.ceil(clearB[1]);y++)for(let x=Math.floor(clearA[0]);x<=Math.ceil(clearB[0]);x++)if(grid[y]?.[x]!==undefined&&roles[y][x]==='weave'){grid[y][x]=' ';scores[y][x]=-1;roles[y][x]=null;}
 for(const side of [-1,1]){
  const x=side*ex,ey=eyeY+(s.rigCue==='uncertain'&&side===1?.025:0),open=eyes*(s.rigCue==='curious'&&side===1?1.12:1),a=[x-erx,ey],c=[x+erx,ey];
  const top=curve('eye-upper-'+side,a,c,-ery*open,[x,ey+.3]);
  const bottom=curve('eye-lower-'+side,c,a,-ery*open*.72,[x,ey-.3]);
  landmarks.push(...[a,top.b,c,bottom.b]);
  if(open>.3){const pupil=[x+gaze,ey+.008];ovalFill(...pupil,erx*.48,ery*Math.min(.52,open*.45),'pupil');dot(pupil[0]-erx*.15,pupil[1]-ery*.16,' ','contour');landmarks.push(pupil);}
  const by=ey-ery*1.35,inner=by+brow,outer=by-(s.rigCue==='uncertain'&&side===1?.03:0);
  const eyebrow=curve('brow-'+side,[x-side*erx,inner],[x+side*erx,outer],-.018,[x,ey+.1]);landmarks.push(eyebrow.a,eyebrow.b,eyebrow.c);
 }
 const my=headY+(s.body==='little-mushroom'?.2:.235),mr=s.body==='little-mushroom'?.095:.15;
 const smile=curve('mouth',[-mr,my],[mr,my],mouth,[0,my+.4],'spark');landmarks.push([-mr,my],smile.b,[mr,my]);
 if(cue.open*strength>.025){const lower=curve('mouth-lower',[mr,my],[-mr,my],-(mouth+cue.open*strength),[0,my-.3],'spark');landmarks.push(lower.b);}
 if(s.body==='comet-fox'||s.body==='pocket-dragon'){dot(0,headY+.13,s.body==='comet-fox'?'v':'.','spark');}
 for(const side of [-1,1]){dot(side*(s.body==='little-mushroom'?.235:.36),headY+.13,':','weave');}
 return {text:grid.map(r=>r.join('').replace(/ +$/,'')).join('\n'),roles,depths,arcs,landmarks,faceFeatures:{eyes:2,brows:2,mouth:1,pupils:eyes>.3?2:0},emphasis:'character-face',characterStyle:'storybook/v1'};
}
