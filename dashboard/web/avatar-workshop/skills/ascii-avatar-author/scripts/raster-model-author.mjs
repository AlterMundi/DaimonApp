// Author transparent part canvases into the existing inert model import; never fetch media.
import {validateAvatarModel} from './model-runtime.mjs';
export function packRasterLayers({id,name,layers,animations,anchors={}}){
 if(!Array.isArray(layers)||!layers.length||layers.length>64)throw Error('Prepare between 1 and 64 raster parts.');
 const width=256,height=256,pixels=new Uint8Array(width*height),palette=['#00000000'];
 // A fixed 6x6x6 palette bounds authored output and preserves colored ASCII texture.
 for(let r=0;r<6;r++)for(let g=0;g<6;g++)for(let b=0;b<6;b++)palette.push('#'+[r,g,b].map(v=>(v*51).toString(16).padStart(2,'0')).join('')+'ff');
 let x=0,y=0,rowHeight=0;
 const nodes=layers.map(({canvas,...node})=>{
  if(!canvas||!Number.isInteger(canvas.width)||!Number.isInteger(canvas.height)||canvas.width<1||canvas.height<1||canvas.width>256||canvas.height>256)throw Error('Each part must be a canvas of at most 256 by 256 pixels.');
  const w=canvas.width,h=canvas.height;if(x+w>width){x=0;y+=rowHeight;rowHeight=0;}if(y+h>height)throw Error('Parts exceed the single 256 by 256 atlas. Reduce authored resolution.');
  const data=canvas.getContext('2d').getImageData(0,0,w,h).data;
  for(let j=0;j<h;j++)for(let i=0;i<w;i++){const p=(j*w+i)*4;pixels[(y+j)*width+x+i]=data[p+3]<128?0:1+Math.round(data[p]/51)*36+Math.round(data[p+1]/51)*6+Math.round(data[p+2]/51);}
  const result={...node,type:'raster',rect:[x,y,w,h]};x+=w;rowHeight=Math.max(rowHeight,h);return result;
 });
 // Bounded chunks avoid argument-limit failures at the maximum atlas size.
 let binary='';for(let start=0;start<pixels.length;start+=4096)binary+=String.fromCharCode(...pixels.subarray(start,start+4096));
 return validateAvatarModel({schema:'ascii-avatar-model/v2',id,name,nodes,animations,anchors,atlas:{width,height,palette,pixels:btoa(binary)}});
}
