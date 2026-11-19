export const LIMITS = Object.freeze({ triangles:250000, objects:6, inputBytes:20*1024*1024, historyBytes:64*1024*1024, historySteps:64, storageBytes:200*1024*1024 });
const uuidPattern=/^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
export function uuid(){ return crypto.randomUUID(); }
export function validId(v){return typeof v==='string'&&uuidPattern.test(v);}
export function nameOf(v,fallback='Sin título'){return typeof v==='string'?v.trim().slice(0,80)||fallback:fallback;}
export function cleanName(v){return nameOf(v).replace(/[<>:"/\\|?*\u0000-\u001f]/g,'-').slice(0,64);}
export async function digest(text){const b=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text));return [...new Uint8Array(b)].map(v=>v.toString(16).padStart(2,'0')).join('');}
function vector(v, min=-10000,max=10000){return Array.isArray(v)&&v.length===3&&v.every(n=>Number.isFinite(n)&&n>=min&&n<=max);}
export function validateProject(value){
  if(!value||value.schema!=='sculpt.project/v1'||value.units!=='mm'||!validId(value.id))throw Error('Este archivo no es un proyecto editable compatible.');
  if(!Array.isArray(value.objects)||value.objects.length>LIMITS.objects)throw Error('La escena puede tener hasta seis piezas.');
  const seen=new Set();let triangles=0;
  const objects=value.objects.map(o=>{
    if(!o||!validId(o.id)||seen.has(o.id))throw Error('La identidad de una pieza no es válida.');seen.add(o.id);
    const p=o.positions,i=o.indices;
    if(!Array.isArray(p)||p.length<9||p.length%3||p.length>2250000||!p.every(n=>Number.isFinite(n)&&Math.abs(n)<=10000))throw Error('La geometría contiene coordenadas fuera de rango.');
    if(!Array.isArray(i)||i.length<3||i.length%3||!i.every(n=>Number.isSafeInteger(n)&&n>=0&&n<p.length/3))throw Error('La geometría contiene caras inválidas.');
    triangles+=i.length/3;if(triangles>LIMITS.triangles)throw Error('Esta escena supera el límite de detalle del taller.');
    if(!vector(o.position)||!Number.isFinite(o.scale)||o.scale<0.01||o.scale>100)throw Error('El tamaño o la posición de una pieza no es válido.');
    if(!p.every((n,j)=>Math.abs(n*o.scale+o.position[j%3])<=20000))throw Error('La pieza queda fuera del espacio de trabajo.');
    let surface=false;for(let f=0;f<i.length&&!surface;f+=3){const a=i[f]*3,b=i[f+1]*3,c=i[f+2]*3,ux=p[b]-p[a],uy=p[b+1]-p[a+1],uz=p[b+2]-p[a+2],vx=p[c]-p[a],vy=p[c+1]-p[a+1],vz=p[c+2]-p[a+2];surface=(uy*vz-uz*vy)**2+(uz*vx-ux*vz)**2+(ux*vy-uy*vx)**2>1e-16;}if(!surface)throw Error('La pieza no tiene una superficie editable.');
    if(typeof o.color!=='string'||!/^#[a-f\d]{6}$/i.test(o.color))throw Error('El color de una pieza no es válido.');
    return {id:o.id,name:nameOf(o.name,'Pieza'),color:o.color.toLowerCase(),visible:o.visible!==false,position:[...o.position],scale:o.scale,positions:p.slice(),indices:i.slice()};
  });
  const camera=value.camera&&vector(value.camera.position,-100000,100000)&&vector(value.camera.target,-100000,100000)?{position:[...value.camera.position],target:[...value.camera.target]}:null;
  return {schema:'sculpt.project/v1',id:value.id,name:nameOf(value.name),units:'mm',objects,camera};
}
export async function makeRevision(project,parentId=null){
  const normalized=validateProject(project),document=JSON.stringify(normalized);
  if(new TextEncoder().encode(document).length>LIMITS.inputBytes)throw Error('El proyecto es demasiado grande para esta versión.');
  const revision={schema:'sculpt.revision/v1',id:uuid(),projectId:normalized.id,parentId:validId(parentId)?parentId:null,createdAt:new Date().toISOString(),sha256:await digest(document),document};if(new TextEncoder().encode(JSON.stringify(revision,null,2)).length>LIMITS.inputBytes)throw Error('El archivo editable supera el límite de esta versión.');return revision;
}
export async function readRevision(text){
  if(typeof text!=='string'||new TextEncoder().encode(text).length>LIMITS.inputBytes)throw Error('El archivo supera el límite de 20 MiB.');
  let r;try{r=JSON.parse(text);}catch{throw Error('No pude leer el proyecto. El archivo no contiene JSON válido.');}
  if(!r||r.schema!=='sculpt.revision/v1'||!validId(r.id)||!validId(r.projectId)||(r.parentId!==null&&!validId(r.parentId))||typeof r.document!=='string'||!/^[a-f\d]{64}$/.test(r.sha256)||typeof r.createdAt!=='string'||r.createdAt.length>40||!Number.isFinite(Date.parse(r.createdAt)))throw Error('La revisión no tiene el formato esperado.');
  if(await digest(r.document)!==r.sha256)throw Error('El contenido no coincide con la huella del archivo. Conservé tu trabajo actual.');
  const project=validateProject(JSON.parse(r.document));if(project.id!==r.projectId)throw Error('El proyecto y su revisión no coinciden.');
  return {revision:{schema:r.schema,id:r.id,projectId:r.projectId,parentId:r.parentId,createdAt:r.createdAt,sha256:r.sha256,document:r.document},project};
}
