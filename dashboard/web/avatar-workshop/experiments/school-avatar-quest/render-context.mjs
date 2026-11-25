// Viewer-only appearance. Never persisted in an avatar model or design.
const contexts=new Map();let probe;
const rgb=value=>{probe??=document.createElement('canvas').getContext('2d',{willReadFrequently:true});probe.canvas.width=probe.canvas.height=1;probe.clearRect(0,0,1,1);probe.fillStyle='#101e2c';probe.fillStyle=value;probe.fillRect(0,0,1,1);return Array.from(probe.getImageData(0,0,1,1).data);};
export const luminance=channels=>channels.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
export function renderContext(element){
 const style=getComputedStyle(element),root=getComputedStyle(document.documentElement),body=getComputedStyle(document.body);
 const authored=document.documentElement.dataset.stylePolicy==='authored';
 const surface=(authored?body.getPropertyValue('--panel'):'')||style.getPropertyValue('--dm-surface')||root.getPropertyValue('--dm-surface');
 if(!surface.trim())return null; // Unbound authored studies keep their existing night stage.
 const a=rgb(surface.trim()),base=rgb(style.getPropertyValue('--dm-background').trim()||'#ffffff'),alpha=a[3]/255;
 const channels=a.slice(0,3).map((v,i)=>Math.round(v*alpha+base[i]*(1-alpha))),background='#'+channels.map(v=>v.toString(16).padStart(2,'0')).join('');
 if(contexts.has(background))return contexts.get(background);
 const context={key:'surface/v1:'+background,background,luminance:luminance(channels),colors:new Map()};context.dark=context.luminance<.18;contexts.set(background,context);if(contexts.size>8)contexts.delete(contexts.keys().next().value);return context;
}
export function presentedColor(color,context){
 if(!context)return color;if(context.colors.has(color))return context.colors.get(color);
 const source=rgb(color).slice(0,3),l=luminance(source);
 // Preserve relative light/shadow ordering on either surface, with room for hue.
 // This is an artistic range, not a WCAG/text accessibility guarantee.
 const bg=context.luminance,lower=(bg+.05)*1.8-.05,upper=Math.max(.035,Math.min(.24,(bg+.05)/1.8-.05));
 const target=context.dark ? lower+l*(.88-lower) : .012+l*(upper-.012);
 let low=0,high=1;const endpoint=target>l?255:0;let adjusted=source;
 for(let i=0;i<12;i++){const t=(low+high)/2;adjusted=source.map(v=>v+(endpoint-v)*t);if((luminance(adjusted)<target)===(endpoint===255))low=t;else high=t;}
 const result='rgb('+adjusted.map(Math.round).join(',')+')';context.colors.set(color,result);if(context.colors.size>1024)context.colors.delete(context.colors.keys().next().value);return result;
}
