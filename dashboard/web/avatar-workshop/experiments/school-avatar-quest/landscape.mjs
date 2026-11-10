// Landscape game presentation only. No design, storage or account mutation.
const touch=matchMedia('(any-pointer: coarse)');
const viewport=matchMedia('(orientation: portrait)');
const gate=document.createElement('dialog');gate.id='landscape-gate';
gate.setAttribute('aria-labelledby','landscape-title');
gate.innerHTML='<span class="rotate-device" aria-hidden="true">↻ ▯</span><h2 id="landscape-title">Girá tu dispositivo para jugar</h2><p>En horizontal podés ver tu avatar y el armario juntos.</p><p class="rotate-help">Si no gira, desactivá el bloqueo de rotación de tu dispositivo.</p><button type="button" id="landscape-start">Jugar en horizontal</button><button type="button" id="landscape-back">Volver</button>';
document.body.append(gate);
const start=gate.querySelector('#landscape-start'),back=gate.querySelector('#landscape-back');
let ownedLock=false,requesting=false,disposed=false,epoch=0;
function releaseLock(){if(!ownedLock)return;ownedLock=false;try{screen.orientation.unlock();}catch{}}
function portrait(){
 const type=screen.orientation?.type;
 if(typeof type==='string' && /^(portrait|landscape)-/.test(type))return type.startsWith('portrait');
 if(typeof window.orientation==='number')return Math.abs(window.orientation)!==90;
 return viewport.matches;
}
function update(){
 if(disposed)return;
 const mobile=touch.matches;document.documentElement.classList.toggle('landscape-game',mobile);
 if(mobile && portrait()){if(!gate.open)gate.showModal();}
 else if(gate.open)gate.close();
 start.hidden=!(document.documentElement.requestFullscreen && screen.orientation?.lock);
 back.hidden=!document.getElementById('cancel-workshop');
}
start.onclick=async()=>{
 if(requesting)return;const ticket=epoch;requesting=true;start.disabled=true;
 try{
  await document.documentElement.requestFullscreen();
  if(disposed || ticket!==epoch)return;
  await screen.orientation.lock('landscape');ownedLock=true;
  if(disposed || ticket!==epoch){releaseLock();}else update();
 }catch{/* Manual rotation remains the same usable path; no retry loop. */}
 finally{requesting=false;start.disabled=false;}
};
back.onclick=()=>document.getElementById('cancel-workshop')?.click();
gate.addEventListener('cancel',event=>{event.preventDefault();if(!back.hidden)back.click();});
for(const target of [touch,viewport,screen.orientation])target?.addEventListener?.('change',update);
window.addEventListener('resize',update);
document.addEventListener('fullscreenchange',()=>{if(!document.fullscreenElement){epoch++;releaseLock();}update();});
window.addEventListener('pagehide',()=>{disposed=true;epoch++;observer.disconnect();if(ownedLock){releaseLock();}});
window.addEventListener('pageshow',()=>{disposed=false;observer.observe(document.body,{childList:true,subtree:true});update();});
// App's header Back action may be installed after its account-ready barrier.
const observer=new MutationObserver(update);observer.observe(document.body,{childList:true,subtree:true});
update();
