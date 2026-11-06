import {validateAvatarModel} from '../../skills/ascii-avatar-author/scripts/model-runtime.mjs';
import {validateProps} from './props.mjs';
import {validateImageArt,coloredImageFrame} from './image-avatar.mjs';
import {childBodies,characterFrame} from '../avatar-studio/characters.mjs';
import {defaults,portrait,toAscii,pack} from '../avatar-studio/engine.mjs';
import {cues} from '../avatar-studio/rig.mjs';
import {abstractPortrait} from '../avatar-studio/abstract.mjs';
import {renderScene} from '../avatar-studio/scenes.mjs';
export const legacyFamilies=[{id:'ribbon',name:'Un hilo que se pliega',symbol:'~{ }~',detail:'Se cruza, se estira y deja un espacio adentro.'},{id:'core',name:'Una nube con un centro',symbol:'(( * ))',detail:'Capas, pequeños poros y un hueco por descubrir.'},{id:'constellation',name:'Una constelación compañera',symbol:'*.-.+',detail:'Puntos que se encuentran y se mueven en relación.'},{id:'pocket-dragon',name:'Un dragón de bolsillo',symbol:'<^>',detail:'Alas que se abren, cuernitos y una cola que hace dibujos.'},{id:'modular-bot',name:'Un robot de piezas',symbol:'[+]',detail:'Módulos flotantes, una antena y pinzas que se acercan.'},{id:'moon-visitor',name:'Un visitante lunar',symbol:'~*~',detail:'Antenas luminosas y cinco tentáculos que exploran.'}];
export const families=[
 {id:'pocket-dragon',name:'Dragón de bolsillo',symbol:'<^>',detail:'Dos ojos grandes, cuernitos redondos y alas pequeñas.'},
 {id:'modular-bot',name:'Robot de piezas',symbol:'[+]',detail:'Una carita en su pantalla, pinzas y una antena curiosa.'},
 {id:'moon-visitor',name:'Medusa lunar',symbol:'~*~',detail:'Una campana blandita, ojos luminosos y tentáculos suaves.'},
 {id:'cloud-axolotl',name:'Ajolote de nube',symbol:'(o)',detail:'Branquias como pétalos y una sonrisa chiquita.'},
 {id:'comet-fox',name:'Zorrito cometa',symbol:'/o\\',detail:'Orejas grandes, mejillas claras y una cola esponjosa.'},
 {id:'little-mushroom',name:'Setita viajera',symbol:'(T)',detail:'Un sombrero con lunares, una carita y patitas cortas.'}
];
export const allFamilies=[{id:'custom-model',name:'Nuestro modelo',detail:'Construido con tu daimon.'},...families,...legacyFamilies.filter(f=>!families.some(n=>n.id===f.id))];
export const materials=[{id:'fiber',name:'De hilos',symbol:'///',detail:'Tramas que se pueden seguir con la mirada.'},{id:'mist',name:'De niebla',symbol:'. : .',detail:'Una presencia suave, hecha de puntos.'},{id:'crystal',name:'De cristal',symbol:'< / >',detail:'Bordes y pequeños reflejos.'}];
export const colors=[['#654ba0','Violeta'],['#226758','Bosque'],['#9a4439','Terracota']];
export function fresh(characterStyle='surface/v2'){const first={id:crypto.randomUUID(),name:'Estoy juntando una idea',opening:1,bend:0,motion:'together',rig:'local/v1',cue:'focus'};return {schema:'ascii-quest-design/v2',artId:crypto.randomUUID(),name:'Mi daimon',material:'fiber',motion:'together',body:'modular-bot',characterStyle,color:colors[0][0],colorMode:'layers',palette:'aurora',depth:false,aperture:1,complexity:1,curvature:0,gestures:[first],activeGestureId:first.id,image:null,imageArt:null,avatarModel:null,creativeBrief:'',choiceNote:''};}
const clamp=(n,a,b)=>Math.max(a,Math.min(b,Number(n)));
export function validate(input){
 if(!input||!['ascii-quest-design/v1','ascii-quest-design/v2'].includes(input.schema))throw Error('Este archivo no es un diseño de este taller.');
 const d=fresh();if(typeof input.artId!=='string'||! /^[\w-]{8,80}$/.test(input.artId))throw Error('Falta la identidad del diseño.');
 const str=(v,max)=>{if(typeof v!=='string'||v.length>max)throw Error('Hay un texto demasiado largo o inválido.');return v;};
 d.avatarModel=input.avatarModel?validateAvatarModel(input.avatarModel):null;
 d.creativeBrief=str(input.creativeBrief??'',500);d.choiceNote=str(input.choiceNote??'',500);
 d.artId=input.artId;d.name=str(input.name,60);d.body=allFamilies.some(f=>f.id===input.body)?input.body:'ribbon';d.material=materials.some(m=>m.id===input.material)?input.material:'fiber';d.motion=['together','offset','rejoin'].includes(input.motion)?input.motion:'together';d.color=colors.some(c=>c[0]===input.color)?input.color:colors[0][0];
 d.characterStyle=input.characterStyle??'classic/v1';if(['cloud-axolotl','comet-fox','little-mushroom'].includes(d.body)&&d.characterStyle==='classic/v1')d.characterStyle='storybook/v1';if(!['model/v1','surface/v2','surface/v1','storybook/v1','classic/v1'].includes(d.characterStyle))throw Error('El estilo de personaje no es compatible.');
 if(d.characterStyle==='model/v1'&&(!d.avatarModel||d.body!=='custom-model'||input.image!==null))throw Error('Falta el modelo articulado o su cuerpo no coincide.');
 if(d.avatarModel&&d.characterStyle!=='model/v1')throw Error('El modelo necesita su propio estilo de dibujo.');
 if(['surface/v1','surface/v2'].includes(d.characterStyle)&&!childBodies.includes(d.body))throw Error('Esta forma no tiene una ilustración de superficies.');
 d.colorMode=input.colorMode===undefined?'mono':input.colorMode;d.palette=input.palette??'aurora';d.depth=input.depth??false;if(!['mono','layers'].includes(d.colorMode)||!['aurora','forest','ember'].includes(d.palette)||typeof d.depth!=='boolean')throw Error('Hay una paleta o un modo de color inválido.');
 for(const [k,a,b] of [['aperture',.6,1.4],['complexity',.6,1.4],['curvature',-1,1]]){if(!Number.isFinite(input[k]))throw Error('Hay un control inválido.');d[k]=clamp(input[k],a,b);}
 const source=input.schema==='ascii-quest-design/v1'?[{...input.gesture,id:'legacy-first-gesture',motion:d.motion}]:input.gestures;
 if(!Array.isArray(source)||source.length<1||source.length>16)throw Error('El taller conserva entre uno y dieciséis gestos por compañero.');
 const ids=new Set();d.gestures=source.map(g=>{if(!g||typeof g.id!=='string'||! /^[\w-]{8,80}$/.test(g.id)||ids.has(g.id)||!Number.isFinite(g.opening)||!Number.isFinite(g.bend)||!['together','offset','rejoin'].includes(g.motion))throw Error('Hay un gesto inválido o repetido.');ids.add(g.id);const result={id:g.id,name:str(g.name,90),opening:clamp(g.opening,.6,1.4),bend:clamp(g.bend,-1,1),motion:g.motion};for(const [key,min,max] of [['width',.75,1.25],['height',.75,1.25],['lean',-.25,.25],['tempo',.5,1.8]])if(g[key]!==undefined){if(!Number.isFinite(g[key])||g[key]<min||g[key]>max)throw Error('Hay una proporción de gesto inválida.');result[key]=g[key];}if(g.rig!==undefined){if(g.rig!=='local/v1'||!cues.includes(g.cue))throw Error('Hay un gesto por partes inválido.');result.rig=g.rig;result.cue=g.cue;}const props=validateProps(g.props);if(props!==undefined)result.props=props;return result;});
 d.activeGestureId=input.schema==='ascii-quest-design/v1'?d.gestures[0].id:input.activeGestureId;
 if(!ids.has(d.activeGestureId))throw Error('No encontré el gesto elegido en el archivo.');
 if(input.image!==null){const t=str(input.image,12000),lines=t.split('\n');if(!/^[\x20-\x7e\n]+$/.test(t)||lines.length>100||lines.some(l=>l.length>96))throw Error('La imagen ASCII excede el tamaño del taller.');d.image=t;}
 d.imageArt=validateImageArt(input.imageArt,d.image);if(d.imageArt&&!d.image)throw Error('Falta el dibujo del retrato de colores.');
 return d;
}
export function activeGesture(d){return d.gestures.find(g=>g.id===d.activeGestureId);}
export function settings(d,gesture=false,blend=1){const g=activeGesture(d),mix=(base,chosen)=>base+(chosen-base)*Math.max(0,Math.min(1,blend)),local=gesture&&g.rig==='local/v1';return {...defaults,characterStyle:d.characterStyle,name:d.name,body:d.body,material:d.material,color:d.color,aura:'none',relation:local?d.motion:gesture&&blend>0?g.motion:d.motion,aperture:local?d.aperture:gesture?mix(d.aperture,g.opening):d.aperture,complexity:d.complexity,curvature:local?d.curvature:gesture?mix(d.curvature,g.bend):d.curvature,stretchX:local?1:gesture?mix(1,g.width??1):1,stretchY:local?1:gesture?mix(1,g.height??1):1,lean:local?0:gesture?mix(0,g.lean??0):0,rigCue:local?g.cue:undefined,rigStrength:local?blend:0};}
let surfaceRenderer=null,surfaceSceneRenderer=null;
export function installSurfaceRenderer(portrait,scene){surfaceRenderer=portrait;surfaceSceneRenderer=scene;}
export function draw(d,frame=0,gesture=false,compact=false,blend=1){if(d.imageArt||!d.image&&['surface/v1','surface/v2','model/v1'].includes(d.characterStyle))return drawFrame(d,frame,gesture,compact,blend).text;return d.image||portrait(settings(d,gesture,blend),'calm',frame,compact?32:d.characterStyle==='storybook/v1'?96:72,compact?24:d.characterStyle==='storybook/v1'?64:40);}
export function drawFrame(d,frame=0,gesture=false,compact=false,blend=1){if(d.imageArt)return coloredImageFrame(d,frame,gesture,compact);if(!d.image&&['surface/v1','surface/v2','model/v1'].includes(d.characterStyle)){if(!surfaceRenderer)throw Error('Surface rendering requires the browser adapter.');return surfaceRenderer(d,frame,gesture,compact,blend);}if(!d.image&&d.characterStyle==='storybook/v1'&&childBodies.includes(d.body))return characterFrame(settings(d,gesture,blend),frame,compact?32:96,compact?24:64);return d.image?{text:d.image,flat:true}:abstractPortrait(settings(d,gesture,blend),'calm',frame,compact?32:72,compact?24:40,true);}
export function drawScene(d,id,frame){if(d.imageArt&&surfaceSceneRenderer)return surfaceSceneRenderer(d,id,frame);if(!d.image&&['surface/v1','surface/v2','model/v1'].includes(d.characterStyle)){if(!surfaceSceneRenderer)throw Error('Surface scenes require the browser adapter.');return surfaceSceneRenderer(d,id,frame);}return renderScene(settings(d,true),id,frame,d.image);}
export function proposals(d){return families.map(f=>({...d,body:f.id,characterStyle:['surface/v1','surface/v2','model/v1'].includes(d.characterStyle)?'surface/v2':'storybook/v1',image:null,imageArt:null,avatarModel:null}));}
export function designPack(d){if(d.imageArt)throw Error('Colored portraits export through workshop TXT/SVG; native packs are not qualified.');if(['surface/v1','surface/v2','model/v1'].includes(d.characterStyle)&&!d.image)throw Error('Surface designs export through workshop TXT/SVG; native packs are not qualified.');return pack(settings(d,true),d.image);}
export function convert(pixels,w,h){const cols=Math.min(72,Math.floor(100*2*w/h));if(cols<12)throw Error('La imagen es muy alta. Probá recortarla un poco antes de cargarla.');return toAscii(pixels,w,h,cols,1.15,false,' .:-=+*#%@','structure');}
export async function digest(value){const b=new TextEncoder().encode(JSON.stringify(value));return [...new Uint8Array(await crypto.subtle.digest('SHA-256',b))].map(x=>x.toString(16).padStart(2,'0')).join('');}
