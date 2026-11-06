export const relations=['original','together','offset','rejoin'];
// Prescribed 1:1 oscillations, not a simulation of emergent physical coupling.
export function relationPhase(kind,frame){
 const t=frame/12*Math.PI*2;
 const offset=kind==='offset'?Math.PI/2:kind==='rejoin'?Math.PI*.85*Math.sin(t/2)**2:0;
 return {a:t,b:t+offset,offset};
}
export function relationScale(kind,frame,x){
 if(!kind||kind==='original')return {x:1,y:1};
 const {a,b}=relationPhase(kind,frame),weight=(1+Math.tanh(x*4))/2;
 const wave=Math.sin(a)*(1-weight)+Math.sin(b)*weight;
 return {x:1+.12*wave,y:1-.10*wave};
}
