// Shared authored-space anchors. Match Canvas translate -> scale -> rotate.
export function objectPoint(origin,local,size=1,side=1,angle=0){
 const [x,y]=local,c=Math.cos(angle),s=Math.sin(angle);
 return [origin[0]+side*size*(c*x-s*y),origin[1]+size*(s*x+c*y)];
}
export function magnifierGeometry(center,radius,size,side,reach){
 // A capsule starts beyond the glass: its round cap touches only the outer rim.
 const angle=.62+reach*.52,direction=[side*Math.sin(angle),Math.cos(angle)];
 const at=d=>center.map((v,i)=>v+direction[i]*d);
 return {center,radius,width:12*size,root:at(radius+6*size),end:at(radius+48*size)};
}
export function lanternOrigin(hand,size,side){return objectPoint(hand,[26,-28],size,side);}
