// App adaptation of the MIT workshop storage contract. Authority stays with
// the parent's existing authenticated API; no credentials or private cache here.
let snapshot,pending,missionContext;
function request(action,args={}){
 if(parent===window)return Promise.reject(Error('Abrí el taller desde tu conversación en DaimonApp.'));
 if(pending)return Promise.reject(Error('Esperá que termine la acción anterior.'));
 return new Promise((resolve,reject)=>{
  const id=crypto.randomUUID(),timer=setTimeout(()=>{pending=null;reject(Error('No recibí confirmación. Volvé a abrir el taller para consultar lo guardado; no se repitió la acción.'));},15000);
  pending={id,resolve,reject,timer};parent.postMessage({kind:'daimon.workshop.request',id,action,args},location.origin);
 });
}
window.addEventListener('message',event=>{
 if(event.origin!==location.origin||event.source!==parent||!['daimon.workshop.result','daimon.workshop.appearance'].includes(event.data?.kind))return;
 if(event.data.kind==='daimon.workshop.result'&&event.data.id!==pending?.id)return;
 for(const [name,value] of Object.entries(event.data.appearance||{}))if(/^--dm-(background|surface|text|accent|body-font|heading-font|radius|gap)$/.test(name)&&typeof value==='string'&&value.length<256&&!/url\(/i.test(value))document.documentElement.style.setProperty(name,value);
 if(event.data.appearance?.presentation==='navigator-hud')document.documentElement.dataset.presentation='navigator-hud';
 else delete document.documentElement.dataset.presentation;
 window.dispatchEvent(new Event('avatar-appearance:changed'));
 if(event.data.kind==='daimon.workshop.appearance')return;
 const selected=pending;pending=null;clearTimeout(selected.timer);
 if(event.data.error)selected.reject(Error(event.data.error));else selected.resolve(event.data.value);
});
export async function openStore(){snapshot=await request('snapshot');missionContext=snapshot.mission||null;}
export async function list(){return snapshot.versions;}
export async function selected(){return snapshot.editing;}
export async function get(id){return request('get',{id});}
export async function select(id){snapshot=await request('edit',{id,generation:snapshot.generation});}
export async function save(design,parentId){
 const id=crypto.randomUUID();snapshot=await request('save',{id,design,parentId:parentId||null,generation:snapshot.generation});
 return snapshot.versions.find(row=>row.id===id);
}
export async function activate(id){snapshot=await request('activate',{id,generation:snapshot.generation});}
export function close(){parent.postMessage({kind:'daimon.workshop.closed'},location.origin);}

export function mission(){return missionContext||null;}
export async function returnMission(id){return request('mission-return',{id});}
export function preview(id){return request('preview',{id});}
