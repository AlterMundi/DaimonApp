// Authored accessory acting vocabulary, not observed emotion or agent activity.
export const performanceVersion='accessory/v1';
export const interactiveProps=['magnifier','flower','firefly-lantern','book','paintbrush','watering-can','flashlight','pillow'];
export const performanceAnatomy={
 'pocket-dragon':{eye:[45,288],nose:[288,348],landing:[288,341],hand:[378,457]},
 'modular-bot':{eye:[43,290],nose:[288,332],landing:[288,117],hand:[395,472]},
 'moon-visitor':{eye:[43,281],nose:[288,307],landing:[288,298],hand:[407,437]},
 'cloud-axolotl':{eye:[47,288],nose:[288,319],landing:[288,316],hand:[386,480]},
 'comet-fox':{eye:[43,284],nose:[288,315],landing:[288,315],hand:[379,480]},
 'little-mushroom':{eye:[31,451],nose:[288,477],landing:[288,471],hand:[390,476]},
};
export const actingMoods={
 sleep:{energy:.15,look:0,tilt:.015,hesitate:0,delay:0,eye:-.3},
 calm:{energy:.4,look:1.5,tilt:.015,hesitate:0,delay:.07,eye:.05},
 curious:{energy:.8,look:6,tilt:.035,hesitate:0,delay:0,eye:.14},
 joy:{energy:1.2,look:4,tilt:.055,hesitate:0,delay:-.04,eye:.12},
 sad:{energy:.28,look:-2,tilt:-.025,hesitate:.025,delay:.09,eye:-.06},
 anger:{energy:.95,look:1,tilt:.025,hesitate:0,delay:-.03,eye:-.1},
 uncertain:{energy:.6,look:5,tilt:-.03,hesitate:.09,delay:.04,eye:.04},
 focus:{energy:.25,look:1.2,tilt:.008,hesitate:0,delay:0,eye:-.04},
 welcome:{energy:.6,look:3,tilt:.03,hesitate:0,delay:.03,eye:.1},
};
export function performanceFor(design,g){
 if(g?.performance!==performanceVersion||design.image||design.avatarModel||!performanceAnatomy[design.body])return null;
 if(design.characterStyle!=='surface/v2'&&!(design.characterStyle==='surface/v1'&&['pocket-dragon','modular-bot'].includes(design.body)))return null;
 return (g.props||[]).find(p=>interactiveProps.includes(p.id))||(g.cue==='sleep'?{id:'sleep',color:'gold',side:'right',size:1}:null);
}
export function playbackSpec(design,g){return performanceFor(design,g)?{frames:48,frameMs:95/Math.pow(g.tempo||1,.35)}:{frames:12,frameMs:160/(g?.tempo||1)};}
const clamp=x=>Math.max(0,Math.min(1,x));
export const ease=x=>{x=clamp(x);return x*x*(3-2*x);};
const rise=(x,a,b)=>ease((x-a)/(b-a));
const window=(x,a,b,c,d)=>rise(x,a,b)*(1-rise(x,c,d));
const pulse=(x,center,width)=>Math.exp(-(((x-center)/width)**2));
export function performanceState(id,cue,frame=0){
 const phase=((frame%48)+48)%48/48,mood=actingMoods[cue]||actingMoods.calm;
 const p=clamp(phase-mood.delay*Math.sin(phase*Math.PI)),activity=window(p,.10,.33,.68,.92),dwell=window(p,.30,.41,.59,.72),event=pulse(p,.59,.045)*window(p,.48,.53,.68,.73);
 const hesitancy=mood.hesitate*Math.sin(p*Math.PI*6)*window(p,.12,.22,.65,.8);
 const reach=clamp(activity+hesitancy),look=Math.sin((p-.34)*Math.PI*5)*dwell*mood.look;
 const state={phase,p,mood,reach,dwell,event,look,face:{eyeScale:1+dwell*mood.eye,gazeOffset:look,mouthOpen:cue==='joy'?dwell*2:0},actor:{x:0,y:0,rotate:mood.tilt*activity,scaleX:1,scaleY:1},camera:{zoom:1,target:[288,350]}};
 if(id==='magnifier'){state.camera.zoom=1+activity*.85;state.actor.y=-Math.sin(p*Math.PI*4)*dwell*mood.energy*2;}
 if(id==='flower'){
  state.sniff=window(p,.25,.40,.49,.55);state.scatter=window(p,.54,.62,.69,.85);
  state.face.eyeScale=Math.max(.08,1-state.sniff*.86-event*.96);state.face.mouthOpen=event*(5+7*mood.energy);
  state.actor.y=-event*14*mood.energy;state.actor.x=Math.sin(p*Math.PI*18)*event*8*mood.energy;
  state.actor.rotate-=state.sniff*.035;state.actor.rotate+=event*.16*mood.energy;
  state.actor.scaleX=1-event*.1*mood.energy;state.actor.scaleY=1+event*.1*mood.energy;
  state.camera.zoom=1+activity*.18;
 }
 if(id==='firefly-lantern'){state.door=window(p,.08,.2,.82,.96);state.landing=window(p,.43,.53,.65,.73);state.face.eyeScale=1+state.landing*mood.eye;state.actor.rotate=mood.tilt*state.landing;state.camera.zoom=1+activity*.28;}
 if(id==='book'){state.open=window(p,.09,.27,.77,.94);state.release=window(p,.24,.37,.73,.88);state.face.eyeScale=1+state.release*mood.eye;state.camera.zoom=1+activity*.18;}
 if(id==='paintbrush'){state.stroke=rise(p,.16,.52)*(1-rise(p,.75,.94));state.fish=window(p,.50,.61,.72,.9);state.actor.y=-Math.sin(p*Math.PI*6)*state.fish*mood.energy*3;state.camera.zoom=1+activity*.14;}
 if(id==='watering-can'){state.pour=window(p,.12,.27,.4,.53);state.grow=window(p,.25,.54,.72,.92);state.tickle=window(p,.53,.61,.68,.8);state.face.eyeScale=Math.max(.12,1-state.tickle*.85);state.face.mouthOpen=state.tickle*(2+4*mood.energy);state.actor.rotate+=Math.sin(p*Math.PI*12)*state.tickle*mood.energy*.05;state.actor.y=-Math.abs(Math.sin(p*Math.PI*9))*state.tickle*mood.energy*6;state.camera.zoom=1+activity*.1;state.camera.target=[288,380];}
 if(id==='flashlight'){state.dim=window(p,.08,.23,.76,.94)*.64;state.reveal=window(p,.37,.57,.73,.9);state.camera.zoom=1+activity*.1;state.face.eyeScale=1+state.reveal*mood.eye;}
 if(id==='sleep'||id==='pillow'){
  state.rest=window(p,.12,.34,.72,.96);state.breathe=Math.sin(p*Math.PI*6)*state.rest;
  const soft=cue==='sleep'||cue==='calm'||cue==='sad',bounce=cue==='joy'?Math.abs(Math.sin(p*Math.PI*8))*state.rest:0;
  state.squeeze=state.rest*(cue==='anger'?.36:.14)+bounce*.1;
  state.face.eyeScale=soft?Math.max(.04,1-state.rest*.96):1-state.rest*.18;
  state.actor.y=state.rest*5+state.breathe*1.7-bounce*7;
  state.actor.rotate=state.rest*(cue==='uncertain'?Math.sin(p*Math.PI*8)*.045:.055);
  state.actor.scaleY=1+state.breathe*.006;
 }
 return state;
}
