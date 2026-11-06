// Projected chord descriptor independently implemented from Weaver's documented
// equation (a0d690e docs/laboratory/face/MATHEMATICS.md). No emotion classification.
export function chordMeasure(a,b,c,center,referenceScale=1){
 const points=[a,b,c,center];if(points.some(p=>!Array.isArray(p)||p.length!==2||!p.every(Number.isFinite))||!Number.isFinite(referenceScale)||referenceScale<=0)return {valid:false,reason:'invalid-input'};
 const dx=c[0]-a[0],dy=c[1]-a[1],length=Math.hypot(dx,dy);if(length<1e-9)return {valid:false,reason:'degenerate-chord'};
 const distance=p=>(dx*(p[1]-a[1])-dy*(p[0]-a[0]))/length;
 const offset=distance(b),orientation=distance(center);if(Math.abs(orientation)<1e-9)return {valid:false,reason:'unoriented-center',offset:offset/referenceScale};
 return {valid:true,offset:offset/referenceScale,inward:offset*Math.sign(orientation)/referenceScale,chordLength:length/referenceScale};
}

// The middle sample is ON the quadratic curve, not its Bezier control point.
// Positive target means toward the chosen reference side of the chord.
export function chordArc(a,c,target,center,steps=32){
 const mid=[(a[0]+c[0])/2,(a[1]+c[1])/2],orientation=chordMeasure(a,mid,c,center);
 if(!orientation.valid||!Number.isFinite(target))throw Error('Unoriented or invalid expressive arc');
 const dx=c[0]-a[0],dy=c[1]-a[1],len=Math.hypot(dx,dy),sign=Math.sign(dx*(center[1]-a[1])-dy*(center[0]-a[0]));
 const b=[mid[0]-dy/len*sign*target,mid[1]+dx/len*sign*target];
 const control=[2*b[0]-mid[0],2*b[1]-mid[1]];
 const points=Array.from({length:steps+1},(_,i)=>{const t=i/steps,u=1-t;return [u*u*a[0]+2*u*t*control[0]+t*t*c[0],u*u*a[1]+2*u*t*control[1]+t*t*c[1]];});
 return {a,b,c,center,target,control,points,measurement:chordMeasure(a,b,c,center)};
}
