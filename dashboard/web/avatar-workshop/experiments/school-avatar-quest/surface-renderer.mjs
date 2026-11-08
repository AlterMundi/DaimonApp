import {performanceFor,performanceState,playbackSpec} from './performances.mjs';
import {preparePerformance,illustratePerformance,stagePerformance} from './performance-illustration.mjs';
import {renderAvatarModel,resolveAvatarModelAnchors} from '../../skills/ascii-avatar-author/scripts/model-runtime.mjs';
import {drawProps,propSlot} from './props.mjs';
import {coloredImageFrame} from './image-avatar.mjs';
import {legacyMaster} from './surface-classic-masters.mjs';
import {organicMaster,organicBodies} from './surface-organic-masters.mjs';
import {dragonMaster,dragonExpressions,glyphAtlas,convertMaster} from './precision-renderer.mjs';
import {sceneState,renderScene} from '../avatar-studio/scenes.mjs';
const cache=new Map(),references=new Map();let atlas;
function master(body,frame,cue,design){if(design.avatarModel)return renderAvatarModel(design.avatarModel,frame,cue);return design.characterStyle==='surface/v2'&&organicBodies.includes(body)?organicMaster(body,frame,cue,design):legacyMaster(body,frame,cue,design);}
export function surfaceSource(design,frame,cue,compact=false,blend=1,performer=null){
 const bodyFrame=((frame%12)+12)%12,state=performer?preparePerformance(design,performer,performanceState(performer.id,cue,frame),bodyFrame):null,passiveProps=(design.activeProps||[]).filter(p=>p.id!==performer?.id);
 const illustration=master(design.body,bodyFrame,cue,{...design,strength:blend,actionPose:state?.face}),base=document.createElement('canvas');base.width=576;base.height=720;
 const options={body:design.body,anchors:design.avatarModel?resolveAvatarModelAnchors(design.avatarModel,bodyFrame,cue):null,style:design.characterStyle};
 drawProps(base,passiveProps,bodyFrame,{...options,layer:'behind'});base.getContext('2d').drawImage(illustration,0,0);
 drawProps(base,passiveProps,bodyFrame,{...options,layer:'front'});
 if(state)illustratePerformance(base,design,performer,state,bodyFrame);const composed=state?stagePerformance(base,state):base;const canvas=document.createElement('canvas');canvas.width=576;canvas.height=720;const c=canvas.getContext('2d');
 const scale=.93+.07*design.aperture;c.save();c.translate(288,350);const t=frame/12*Math.PI*2;c.rotate(design.curvature*.045+(design.motion==='offset'?Math.sin(t)*.008:0));c.scale(scale*(design.motion==='rejoin'?1+.015*Math.sin(t):1),1);c.translate(-288,-350);
 if(compact&&(performer||design.activeProps?.some(p=>propSlot(p.id)==='head'))){c.drawImage(composed,38,0,500,625,0,0,576,720);}else if(compact&&design.activeProps?.length){c.drawImage(composed,105,100,380,475,0,0,576,720);}else if(compact&&design.avatarModel?.anchors.compact){c.drawImage(composed,...design.avatarModel.anchors.compact,0,0,576,720);}else if(compact){const mushroom=design.body==='little-mushroom';c.drawImage(composed,mushroom?208:158,mushroom?340:140,mushroom?160:260,mushroom?200:325,0,0,576,720);}else c.drawImage(composed,0,0);c.restore();
 // Appearance variants operate on authored surfaces; alpha and facial geometry remain intact.
 const image=c.getImageData(0,0,576,720),px=image.data;
 for(let i=0;i<px.length;i+=4){if(!px[i+3])continue;let [r,g,b]=[px[i],px[i+1],px[i+2]];if(!design.bodyColors?.[design.body]&&design.palette==='forest')[r,g,b]=[g*.9,r*.4+g*.6,b*.75];if(!design.bodyColors?.[design.body]&&design.palette==='ember')[r,g,b]=[Math.min(255,r*1.13+20),g*.87,b*.78];const y=Math.floor(i/4/576),x=(i/4)%576,texture=y>370?(design.material==='fiber'?(y%17<2?.94:1):design.material==='crystal'?((x+y)%31<3?1.06:1):((x*7+y*11)%37<2?1.04:1)):1;px[i]=r*texture;px[i+1]=g*texture;px[i+2]=b*texture;}
 c.putImageData(image,0,0);return canvas;
}
export function surfaceFrame(design,frame=0,gesture=false,compact=false,blend=1,scene=null){
 atlas??=glyphAtlas();const g=design.gestures.find(g=>g.id===design.activeGestureId),cue=scene?.cue||(gesture&&blend>0&&g.rig==='local/v1'?g.cue:'calm'),cols=scene?40:compact?32:96;
 const propGesture=scene?.cue?design.gestures.find(g=>g.cue===scene.cue):g;const activeProps=gesture?propGesture?.props||[]:[];design={...design,activeProps};
 const performer=!scene&&gesture?performanceFor(design,g):null,count=performer?playbackSpec(design,g).frames:12;frame=((frame%count)+count)%count;
 const appearance=[performer?.id||'',g.performance||'',JSON.stringify(design.avatarModel),JSON.stringify(activeProps),design.characterStyle,design.body,JSON.stringify(design.bodyColors),design.palette,design.aperture,design.curvature,design.material,design.motion,blend,compact,cols,cue].join(':'),key=appearance+':'+frame;let art=cache.get(key);
 if(!art){const ref=references.get(appearance)||convertMaster(surfaceSource(design,0,cue,compact,blend,performer),'structure',cols,atlas);references.set(appearance,ref);if(references.size>10)references.delete(references.keys().next().value);art=convertMaster(surfaceSource(design,frame,cue,compact,blend,performer),'structure',cols,atlas,ref);cache.set(key,art);if(cache.size>40)cache.delete(cache.keys().next().value);}
 const colors=Array.from({length:art.rows},()=>Array(art.cols).fill(null));for(const p of art.cells)colors[p.y][p.x]=p.color;
 return {text:art.text,colors,flat:true,emphasis:'surface',characterStyle:design.characterStyle};
}
export function surfaceScene(design,id,index){
 const state=sceneState(id,index),cue=({notice:'curious',approach:'welcome',wait:'calm',shelter:'welcome',celebrate:'joy',settle:'calm'})[state.action]||'calm';
 const actor=design.imageArt?coloredImageFrame(design,index,true,true,cue):surfaceFrame(design,index,true,false,1,{cue}),lines=renderScene({},id,index,' ').split('\n').map(l=>l.padEnd(80).split('')),colors=Array.from({length:40},()=>Array(80).fill('#b9d7b5')),dx=4+Math.round(state.approach*6),dy=6+(state.action==='wait'?Math.round(Math.sin(index*.7)):0);
 actor.text.split('\n').forEach((line,y)=>[...line].forEach((char,x)=>{if(char!==' '&&lines[y+dy]&&x+dx<80){lines[y+dy][x+dx]=char;colors[y+dy][x+dx]=actor.colors[y][x];}}));
 return {text:lines.map(l=>l.join('')).join('\n'),colors,flat:true,emphasis:'surface'};
}
