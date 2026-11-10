// Material roles for the first authored recolorable body. No pixel-wide tint.
export const defaultCapColor='#cb7783';
export function capColors(primary){
 if(!/^#[0-9a-f]{6}$/i.test(primary))throw Error('Invalid cap color');
 const rgb=[1,3,5].map(i=>parseInt(primary.slice(i,i+2),16));
 const mix=(target,amount)=>'#'+rgb.map(v=>Math.round(v+(target-v)*amount).toString(16).padStart(2,'0')).join('');
 return {light:mix(255,.48),shade:mix(0,.18),edge:mix(0,.32),rimLight:mix(255,.78),rimShade:mix(255,.28),rimEdge:mix(0,.1),gill:mix(255,.45),gillLight:mix(255,.72),seam:mix(255,.6),glint:mix(255,.83)};
}

export const bodyColorDefaults={'pocket-dragon':'#70b49a','modular-bot':'#8aafc1','moon-visitor':'#81a9d3','cloud-axolotl':'#d1a6ca','comet-fox':'#d18b59','little-mushroom':defaultCapColor};
export function materialTone(primary,source,base){
 if(!primary)return source;
 const rgb=hex=>[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16));
 const luminance=hex=>rgb(hex).reduce((n,v,i)=>n+v*[.2126,.7152,.0722][i],0);
 const l=luminance(source),b=luminance(base),light=l>=b,amount=light?(l-b)/(255-b):(b-l)/b;
 return '#'+rgb(primary).map(v=>Math.round(v+((light?255:0)-v)*amount).toString(16).padStart(2,'0')).join('');
}
