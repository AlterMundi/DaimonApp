import {chordArc} from './geometry.mjs';
import {localPose} from './rig.mjs';
import {relationScale} from './motion.mjs';
export const abstractBodies=['core','constellation','ribbon','filament','cluster','vortex','pocket-dragon','modular-bot','moon-visitor'];
// Normalized paths retain identity while pose alters topology, tension and cadence.
export function abstractPortrait(s,expression='calm',frame=0,cols=72,rows=40,withLayers=false){
 const W=cols,H=rows,cx=(W-1)/2,cy=(H-1)/2,g=Array.from({length:H},()=>Array(W).fill(' '));
 const roles=Array.from({length:H},()=>Array(W).fill(null)),depths=Array.from({length:H},()=>Array(W).fill(0));let layerRole='contour',layerDepth=1;
 const rig=localPose(s.rigCue,frame,s.rigStrength??1),arcs=[];
 const t=frame/12*Math.PI*2,phase=Math.sin(t),pace=Number(s.rhythm||1),dir=Number(s.direction??1),opening=Number(s.aperture??1),detail=Number(s.complexity??1);
 const pose={calm:[1,1,0],curious:[1.06,.95,.18],focused:[.83,1.12,0],listening:[1.12,.96,.13],speaking:[1.02+phase*.10,1,.02],delighted:[1.18+phase*.06,1.12,-.06],uncertain:[.94,1.04,Math.sin(t)*.14]}[expression]||[1,1,0];
 const breath=.018*Math.sin(t)*(1-rig.strength),sx=(rig.active?1:pose[0])+breath,sy=(rig.active?1:pose[1])-breath,lean=(rig.active?0:pose[2])*dir;
 const tension=expression==='focused'?.7:expression==='delighted'?1.15:1;
 function point(x,y){const bend=Math.max(-1,Math.min(1,Number(s.curvature)||0));y+=bend*(x*x-.25)*.35;const rel=relationScale(s.relation,frame,x),r={x:1+(rel.x-1)*(1-rig.strength),y:1+(rel.y-1)*(1-rig.strength)};return [cx+(x*sx*r.x*(Number(s.stretchX)||1)+y*(lean+(Number(s.lean)||0)))*W*.36,cy+y*sy*r.y*(Number(s.stretchY)||1)*H*.36];}
 function dot(x,y,c='.',transform=true,role=layerRole,depth=layerDepth){if(transform)[x,y]=point(x,y);x=Math.round(x);y=Math.round(y);if(g[y]&&x>=0&&x<W){g[y][x]=c;roles[y][x]=role;depths[y][x]=depth;}}
 function path(points,chars='auto',role=layerRole,depth=layerDepth){let last=null;for(const p of points){if(last){const [a,b]=point(...last),[c,d]=point(...p),n=Math.max(1,Math.ceil(Math.max(Math.abs(c-a),Math.abs(d-b))));const glyph=chars==='auto'?(Math.abs(c-a)>Math.abs(d-b)*1.9?'-':Math.abs(d-b)>Math.abs(c-a)*1.8?'|':(c-a)*(d-b)>0?'\\':'/'):chars;for(let i=0;i<=n;i++)dot(a+(c-a)*i/n,b+(d-b)*i/n,glyph,false,role,depth);}last=p;}}
 const sample=(fn,n=100)=>Array.from({length:n+1},(_,i)=>fn(i/n));
 function ellipse(rx,ry,ox=0,oy=0,ch='auto',gap=0){path(sample(u=>{const a=gap+u*(Math.PI*2-gap*2);return [ox+Math.cos(a)*rx,oy+Math.sin(a)*ry];}),ch);}
 function arc(id,a,c,target,center,role='contour',depth=1){const result=chordArc(a,c,target,center);arcs.push({id,...result});path(result.points,'auto',role,depth);return result;}
 const material=s.material||'fiber',shade=material==='mist'?'.':material==='crystal'?':':',';
 const focus=expression==='curious'||expression==='listening'?dir*.16:expression==='uncertain'?Math.sin(t)*.08:0;
 if(s.body==='core'){
  // Stable outer membranes; the aperture alone carries local bend and orientation.
  const layers=Math.max(2,Math.round(3*detail));
  for(let layer=0;layer<layers;layer++){
   const r=.93-layer*.13;path(sample(u=>{const a=u*Math.PI*2,warp=.06*Math.sin(a*3+.4);return [Math.cos(a)*(r+warp),Math.sin(a)*(r*.8+warp)+Math.cos(a)*.07];}),layer===0?'auto':shade,layer===0?'contour':'weave',layer===0?1:.4);
  }
  const r=.26*opening*(1+rig.open+rig.pulse*.08),y=rig.droop*.3+rig.pulse*.06,x=rig.look;
  arc('aperture-upper',[x-r,y],[x+r,y],-r*(.65-rig.curl),[x,y+.3]);
  arc('aperture-lower',[x+r,y],[x-r,y],-r*(.65+rig.curl*.6),[x,y-.3]);
  for(const a of [.4,2.5,4.2])dot(Math.cos(a)*1.04,Math.sin(a)*.84,'*',true,'spark',1);
 }
 if(s.body==='constellation'){
  const base=[[-.82,-.3],[-.45,-.72],[.05,-.48],[.48,-.8],[.85,-.05],[.43,.52],[-.05,.8],[-.62,.45],[.02,.02]];
  const top=arc('upper-chain',base[0],base[3],-.27*opening-rig.lift*.5+rig.curl*.2+rig.pulse*.04,[0,.3]);
  const bottom=arc('lower-chain',base[4],base[7],-.38*opening-rig.open*.4,[0,-.3]);
  const nodes=[base[0],top.points[10],top.points[22],base[3],base[4],bottom.points[10],bottom.points[22],base[7],[.02+rig.look,.02+rig.droop*.3+rig.pulse*.05]];
  path([nodes[3],nodes[4]],'.','weave',.4);path([nodes[7],nodes[0]],'.','weave',.4);
  for(const i of [2,5,7])path([nodes[i],nodes[8]],'.','weave',.4);
  nodes.forEach(([x,y],i)=>dot(x,y,i===8?'@':i%3===0?'*':'+',true,'spark',1));
 }
 if(s.body==='ribbon'){
  // A fixed crossing and tips; two local folds open and close independently.
  for(const side of [-1,1]){
   const reach=.83*(1+rig.spread*.28)+side*rig.asym*.1,tip=[side*reach,rig.droop*.25+side*rig.asym*.3+rig.pulse*.06],root=[0,0],center=[side*reach*.45,.25];
   arc(side<0?'left-upper-fold':'right-upper-fold',root,tip,-(.42*opening+rig.open*.18)+side*rig.asym*.16,center);
   arc(side<0?'left-lower-fold':'right-lower-fold',tip,root,-(.42*opening+rig.open*.18)+rig.curl*.18,[side*reach*.45,-.25]);
   arc('inner-fold-'+side,[side*.06,0],[tip[0]*.88,tip[1]],-.28*opening,[side*reach*.45,.25],'weave',.4);
  }
  path([[-.72,.43],[-.88,.78],[-.57,.67]],'auto','spark',1);path([[.58,-.53],[.8,-.86],[.89,-.63]],'auto','spark',1);
 }
 if(s.body==='pocket-dragon'){
  // Body, paws and tail stay identifiable; wings and neck provide the gesture.
  const spread=(.78+.16*opening)*(1+rig.spread*.34),drop=rig.droop*.5,flap=rig.pulse*.045;
  for(const side of [-1,1]){
   const root=[side*.16,.05],tip=[side*.73*spread,-.64-rig.lift*.45+side*rig.asym*.3-flap];
   arc('wing-'+side,root,tip,-.13+rig.curl*.2,[0,.4]);
   const ribs=[[side*.89*spread,-.17+drop],[side*.72*spread,-.09+drop],[side*.8*spread,.23+drop],[side*.46*spread,.15+drop],[side*.25,.38]];
   path([tip,...ribs,root],'auto','contour',.4);
   path([[side*.2,.18],ribs[0]],shade,'weave',.4);
  }
  path(sample(u=>{const a=u*Math.PI*1.5;return [-.24-.47*Math.sin(u*Math.PI*.7),.42+.31*Math.sin(a)];},50),'auto','contour',.7);
  path([[-.71,.24],[-.84,.35],[-.67,.43],[-.71,.24]],'auto','spark',.8);
  layerRole='contour';layerDepth=1;ellipse(.3,.43,0,.22);
  const hx=rig.look*.3,hy=rig.droop*.65;
  arc('neck',[.1,-.18],[.1+hx,-.42+hy],-.13-rig.lift*.12,[-.3,-.1]);
  ellipse(.32,.25,.06+hx,-.4+hy);
  path([[.27+hx,-.53+hy],[.46+hx,-.39+hy],[.38+hx,-.25+hy],[.2+hx,-.22+hy]],'auto');
  path([[-.18+hx,-.56+hy],[-.22+hx,-.87+hy],[-.02+hx,-.65+hy]],'auto','spark',1);
  path([[.12+hx,-.63+hy],[.29+hx,-.82+hy],[.26+hx,-.51+hy]],'auto','spark',1);
  layerRole='weave';layerDepth=.85;ellipse(.17,.28,.04,.25,shade);
  for(const side of [-1,1]){path([[side*.22,.32],[side*.38,.56],[side*.21,.64]],'auto','contour',1);path([[side*.21,.64],[side*.35,.64]],'auto','spark',1);}
  dot(.17+hx,-.43+hy,'@',true,'spark',1);dot(.38+hx,-.36+hy,'.',true,'spark',1);
 }
 if(s.body==='modular-bot'){
  const gap=.05+.12*opening+rig.lift*.25,headY=-.46-gap+rig.droop*.35;
  const panel=(x,y,w,h,role='contour',z=1)=>path([[x-w+.06,y-h],[x+w-.06,y-h],[x+w,y-h+.06],[x+w,y+h-.06],[x+w-.06,y+h],[x-w+.06,y+h],[x-w,y+h-.06],[x-w,y-h+.06],[x-w+.06,y-h]],'auto',role,z);
  panel(rig.look*.4,headY,.3,.15);panel(0,.04,.38,.3);panel(0,.47+gap,.28,.12);
  arc('antenna',[rig.look*.4,headY-.16],[rig.look*.4,headY-.4],rig.asym*.25+rig.curl*.09,[.3,headY]);dot(rig.look*.4,headY-.41,'*',true,'spark',1);
  for(let i=-1;i<=1;i++)dot(i*.15+rig.look*.4,headY,i===0?'@':'+',true,'spark',1);
  for(const side of [-1,1]){
   const x=side*(.52+.12*opening+rig.spread*.35),y=.02+rig.droop*.7-rig.lift*.35+side*rig.asym*.4+rig.pulse*.06;
   arc('gripper-'+side,[side*.39,0],[x,y],rig.curl*.18,[0,.5],'contour',.8);panel(x,y,.09,.12,'contour',.85);
   path([[side*.15,.61],[side*.2,.79],[side*.33,.79]],'auto','weave',.7);dot(side*.31,.79,'=',true,'spark',1);
   dot(side*.28,-.17,'o',true,'spark',1);dot(side*.28,.24,'o',true,'spark',1);
  }
  const r=.14*opening*(1+rig.open);
  arc('dial-upper',[-r,.03],[r,.03],-r*.6+rig.curl*.08,[0,.3],'spark',1);
  arc('dial-lower',[r,.03],[-r,.03],-r*.6,[0,-.3],'spark',1);dot(0,.03,'+',true,'spark',1);
  path([[-.16,.47+gap],[.16,.47+gap]],':','weave',.8);
 }
 if(s.body==='moon-visitor'){
  // Outer shell is fixed; antennas and tendrils orient and gather around it.
  for(let side=-1;side<=1;side++){
   const start=[side*.21,-.48],tip=[side*(.38+rig.spread*.35)+rig.look*.3,-.89-(side===0?.14:0)-rig.lift*.3+rig.droop*.6+side*rig.asym*.3];
   arc('antenna-'+side,start,tip,rig.curl*.14,[.4,-.1],'contour',.8);dot(...tip,'*',true,'spark',1);
  }
  for(let i=-2;i<=2;i++){
   const x=i*.15,spread=opening*.75+rig.spread;
   const tip=[x+Math.sin(Math.PI*1.3+i*.6)*.16+x*spread+rig.look*.2,.87-rig.lift*.3+Math.abs(i)*rig.droop*.08];
   arc('tendril-'+i,[x,.08],tip,.09+rig.curl*.1+rig.pulse*.035,[i<0?.5:-.5,.4],'contour',.7);
   dot(...tip,i%2?'o':'*',true,'spark',1);
  }
  for(const side of [-1,1])path([[side*.36,-.25],[side*.68,-.08],[side*.6,.13],[side*.36,.02]],'auto','weave',.35);
  layerRole='contour';layerDepth=1;path(sample(u=>{const a=u*Math.PI*2;return [Math.cos(a)*.44,Math.sin(a)*.34-.22+.025*Math.cos(a*3)];}));
  layerRole='weave';layerDepth=.8;ellipse(.33,.24,0,-.22,shade);
  const r=.15*opening*(1+rig.open),cx=rig.look*.5,cy=-.18;
  arc('membrane-upper',[cx-r,cy],[cx+r,cy],-r*.55+rig.curl*.08,[cx,cy+.2],'spark',1);
  arc('membrane-lower',[cx+r,cy],[cx-r,cy],-r*.55,[cx,cy-.2],'spark',1);
  dot(-.24,-.27,'*',true,'spark',1);dot(.24,-.27,'*',true,'spark',1);dot(0,-.4,'+',true,'spark',1);
 }
 if(s.body==='filament'){
  const branches=Math.round(7*detail);
  for(let i=0;i<branches;i++){
   const a=(i/(branches-1)-.5)*2.7;
   path(sample(u=>{const bend=Math.sin(t-i*.4+u*2)*.045*u;return [Math.sin(a)*u*.96*opening+focus*u+Math.sin(u*3)*.08, .78-Math.cos(a)*u*1.7+bend];}),material==='mist'?'.':'auto');
   dot(Math.sin(a)*.96*opening+focus,.78-Math.cos(a)*1.7, i%2?'*':':');
  }
  ellipse(.17,.14,0,.72,':');
 }
 if(s.body==='cluster'){
  const crystals=[[-.4,.2,.35],[0,-.2,.48],[.43,.13,.28],[-.05,.6,.2]];
  crystals.forEach(([x,y,r],i)=>{x+=focus;const spread=expression==='delighted'?1.15:1;x*=spread;y*=spread;
   const pts=[[x,y-r],[x+r*.65,y-r*.15],[x+r*.52,y+r*.65],[x,y+r],[x-r*.55,y+r*.55],[x-r*.65,y-r*.15],[x,y-r]];
   path(pts);path([[x,y-r],[x-r*.14,y+r*.1],[x,y+r]]);path([[x-r*.65,y-r*.15],[x-r*.14,y+r*.1],[x+r*.65,y-r*.15]],'.');
  });
 }
 if(s.body==='vortex'){
  for(let j=0;j<3;j++)path(sample(u=>{const a=u*Math.PI*4+j*2.1+Math.sin(t)*.1,r=(.14+u*.8)*opening;return [Math.cos(a)*r+focus*(1-u),Math.sin(a)*r*.84];},150),j===0?'auto':shade);
  ellipse(.98,.83,0,0,'.',.38);dot(.05,0,'*');
 }
 // Stable satellite rhythm, not random frame noise.
 if(s.aura==='stars')for(const [x,y] of [[-1.22,-.8],[1.18,.65],[-1.1,.95],[1.15,-1.04]])dot(x,y,'.');
 if(s.aura==='orbit')ellipse(1.2,.35,0,.1,'.',.1);
 const text=g.map(r=>r.join('').replace(/ +$/,'')).join('\n');return withLayers?{text,roles,depths,arcs,emphasis:rig.active?'local-rig':null}:text;
}
