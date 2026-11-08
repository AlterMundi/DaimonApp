// Derived from Homemaker public/lib/interface-roles.js; see docs/homemaker-interface-roles.md.
(()=>{
// Local derived roles, not an extension of the strict appearance/v1 wire schema.
const validColor = value => typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value);
const luminance = hex => [1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255)
  .map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4)
  .reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
const contrast = (a,b) => {const x=luminance(a),y=luminance(b);return(Math.max(x,y)+.05)/(Math.min(x,y)+.05);};
const mix = (a,b,weight) => '#'+[1,3,5].map(i=>Math.round(parseInt(a.slice(i,i+2),16)*weight+parseInt(b.slice(i,i+2),16)*(1-weight)).toString(16).padStart(2,'0')).join('');
function interfaceRoles(appearance) {
  if(appearance?.contract!=='homemaker.appearance/v1'||!['background','surface','text','accent'].every(k=>validColor(appearance[k])))throw Error('Expected bounded appearance/v1 colors.');
  const background=appearance.background;
  let surface=appearance.surface;
  const readable = (candidate,minimum=4.5) => [background,surface].every(bg=>contrast(candidate,bg)>=minimum);
  // Opposing extreme surfaces have no common readable foreground. Keep the
  // authored canvas and collapse only the derived panel, never the recipe.
  if(![appearance.text,'#000000','#ffffff'].some(c=>readable(c)))surface=background;
  const choose = candidates => candidates.find(c=>readable(c)) ?? ['#000000','#ffffff'].sort((a,b)=>contrast(b,background)-contrast(a,background))[0];
  const text=choose([appearance.text]);
  const accent=choose([appearance.accent,text]);
  const muted=choose([mix(text,background,.78),text]);
  const dark=luminance(background)<.18;
  const warning=choose(dark?['#f4c283',text]:['#794500',text]);
  const positive=choose(dark?['#a8dac6',text]:['#176241',text]);
  const danger=choose(dark?['#ffb5b5',text]:['#a21b32',text]);
  const secondary=choose(dark?['#dcb3c3',text]:['#773e67',text]);
  const border=choose([mix(text,background,.65),text]);
  return Object.freeze({contract:'homemaker.interface-roles/v1',background,surface,text,accent,muted,border,
    focus:accent,warning,positive,danger,secondary,controlSurface:surface,controlText:text,
    selectedSurface:accent,selectedText:background,messageSurface:surface,composerSurface:surface});
}

const root=document.documentElement;
const owned=new Map();
function refresh(){
 if(root.dataset.stylePolicy==='authored'){
  for(const [key,previous] of owned){
   if(previous.value)root.style.setProperty(key,previous.value,previous.priority);
   else root.style.removeProperty(key);
  }
  owned.clear();
  return;
 }
 const css=getComputedStyle(root),read=n=>css.getPropertyValue('--dm-'+n).trim();
 try{
  const roles=interfaceRoles({contract:'homemaker.appearance/v1',background:read('background'),surface:read('surface'),text:read('text'),accent:read('accent')});
  for(const key of ['background','surface','text','accent','muted','border','focus','warning','positive','danger','secondary']){
   const name='--dm-ui-'+key;
   if(!owned.has(name))owned.set(name,{value:root.style.getPropertyValue(name),priority:root.style.getPropertyPriority(name)});
   root.style.setProperty(name,roles[key]);
  }
 }catch{/* Missing/invalid provider keeps the existing local appearance. */}
}
window.addEventListener('home-style:resolved',refresh);
refresh();
})();
