import {materialTone,bodyColorDefaults} from './body-colors.mjs';
import {capColors} from './body-colors.mjs';
// Original surface/v2 illustrations. Geometry and detail are authored before glyph conversion.
import {dragonExpressions} from './precision-renderer.mjs';
export const organicBodies=['moon-visitor','cloud-axolotl','comet-fox','little-mushroom'];
export function organicMaster(body,frame,cue,design){
 const canvas=document.createElement('canvas');canvas.width=576;canvas.height=720;const c=canvas.getContext('2d'),t=frame/12*Math.PI*2;
 const chosen=dragonExpressions[cue]||dragonExpressions.calm,p=Object.fromEntries(Object.entries(chosen).map(([k,v])=>[k,typeof v==='number'?dragonExpressions.calm[k]+(v-dragonExpressions.calm[k])*(design.strength??1):v]));
 p.eye*=design.actionPose?.eyeScale??1;p.gaze+=design.actionPose?.gazeOffset??0;p.open+=design.actionPose?.mouthOpen??0;
 c.translate(288,350+Math.sin(t)*3);c.lineJoin='round';c.lineCap='round';
 const gradient=(x,y,r,a,b)=>{const g=c.createRadialGradient(x-r*.3,y-r*.4,1,x,y,r);g.addColorStop(0,a);g.addColorStop(1,b);return g;};
 const oval=(x,y,rx,ry,fill,stroke=null,w=3)=>{c.beginPath();c.ellipse(x,y,rx,ry,0,0,Math.PI*2);c.fillStyle=fill;c.fill();if(stroke){c.strokeStyle=stroke;c.lineWidth=w;c.stroke();}};
 const path=(points,fill=null,stroke=null,w=3)=>{c.beginPath();for(const [op,...v] of points)c[op](...v);if(fill){c.fillStyle=fill;c.fill();}if(stroke){c.strokeStyle=stroke;c.lineWidth=w;c.stroke();}};
 let fy=-62,ex=43,ew=27,eh=32,ink='#394d65',cheek='#eaa9ad',iris='#6a9fa3';
 if(body==='moon-visitor'){
  const tone=color=>materialTone(design.bodyColors?.[body],color,bodyColorDefaults[body]);
  // Fine trailing filaments sit behind broad, curling oral-arm ribbons.
  for(let i=-3;i<=3;i++){const root=i*28,sway=Math.sin(t+i*.7)*13;
   path([['moveTo',root,15],['bezierCurveTo',root-38,70,root+48+sway,128,root+sway,181],['bezierCurveTo',root-35+sway,219,root+39,247,root+15,265]],null,i%2?tone('#7b9dd1'):tone('#75cbd5'),i%2?3:5);
  }
  for(let i=-1;i<=1;i++){
   const center=i*62,phase=t+i*.9,points=[],left=[],right=[];
   for(let j=0;j<=52;j++){const u=j/52,y=17+u*215,x=center+Math.sin(u*6.5+phase)*19*u,width=(14+Math.sin(u*23+phase)*5)*(1-u*.7);left.push([x-width,y]);right.push([x+width,y]);}
   points.push(...left,...right.reverse());path(points.map((v,j)=>[j?'lineTo':'moveTo',...v]).concat([['closePath']]),gradient(center,109,153,i===0?'#f4c9df':tone('#bbd7f3'),i===0?'#9d8cc9':tone('#5f9ec8')),tone('#a8cce4'),2);
   for(let j=0;j<11;j++){const u=j/11,y=24+u*207,x=center+Math.sin(u*6.5+phase)*19*u;path([['moveTo',x-9,y],['quadraticCurveTo',x,y+11,x+9,y+2]],null,'#e4dbf1',2);}
  }
  const bell=[['moveTo',-151,18],['bezierCurveTo',-173,-65,-115,-172,-34,-180],['bezierCurveTo',75,-199,154,-111,158,-25],['quadraticCurveTo',164,14,144,29],['bezierCurveTo',86,45,-94,47,-151,18],['closePath']];
  path(bell,gradient(-29,-94,240,tone('#dbd8fa'),tone('#528bbd')),tone('#6689ae'),4);
  // Soft internal meridians avoid the face window.
  for(const side of [-1,1])for(let j=0;j<3;j++)path([['moveTo',side*(35+j*12),-167+j*9],['bezierCurveTo',side*(80+j*10),-132,side*(108+j*11),-61,side*(114+j*13),14]],null,j%2?tone('#a9c9e1'):tone('#87b0d9'),3);
  path([['moveTo',-145,17],['bezierCurveTo',-94,34,95,43,151,17]],null,'#edcff2',13);
  for(let j=0;j<13;j++){const x=-138+j*23,y=23+Math.cos(j/12*Math.PI*2)*5;path([['moveTo',x-10,y-2],['quadraticCurveTo',x,y+17,x+11,y]],null,j%2?'#c2b2e7':'#c6e6eb',6);}
  path([['moveTo',-102,-101],['bezierCurveTo',-85,-140,-45,-157,-10,-153]],null,tone('#edf1fb'),7);
  for(const [x,y,r] of [[-114,-65,4],[-95,-119,3],[84,-127,5],[106,-91,3],[-78,-151,2],[120,-48,3]])oval(x,y,r,r,tone('#dff7ed'));
  fy=-69;ink='#404975';iris='#7e91c4';cheek='#dbaacb';
 }else if(body==='cloud-axolotl'){
  const tone=color=>materialTone(design.bodyColors?.[body],color,bodyColorDefaults[body]);
  // A tapered swimming tail with a two-tone fin, behind the pear-shaped body.
  path([['moveTo',36,121],['bezierCurveTo',132,101,211,123,201,196],['bezierCurveTo',195,247,112,247,83,215],['bezierCurveTo',151,233,163,180,100,179],['quadraticCurveTo',57,183,31,155],['closePath']],gradient(132,176,125,tone('#b6d9eb'),tone('#8ba9d4')),tone('#7c92bb'),4);
  path([['moveTo',52,149],['bezierCurveTo',148,135,195,159,178,202],['quadraticCurveTo',154,230,121,217]],null,tone('#e9b9d0'),15);
  for(const side of [-1,1])for(let j=-1;j<=1;j++){
   const sway=Math.sin(t+j*.7)*4,root=[side*98,-65+j*24],tip=[side*(203-Math.abs(j)*9),-86+j*58+sway];
   path([['moveTo',...root],['quadraticCurveTo',side*153,-65+j*43,...tip]],null,tone('#ca7da8'),9);
   for(let k=1;k<=7;k++){const u=k/8,x=root[0]+(tip[0]-root[0])*u,y=root[1]+(tip[1]-root[1])*u,span=11+Math.sin(u*Math.PI)*15;
    for(const branch of [-1,1])path([['moveTo',x,y],['quadraticCurveTo',x+side*9,y+branch*span*.5,x+side*5,y+branch*span]],null,k%2?tone('#f1a9c7'):tone('#c99bcc'),5);
   }
   oval(...tip,6,8,tone('#f5c7d1'));
  }
  path([['moveTo',-57,32],['bezierCurveTo',-93,87,-76,179,-45,207],['quadraticCurveTo',-8,233,43,208],['bezierCurveTo',85,180,92,81,48,34],['closePath']],gradient(-17,93,150,tone('#f7d4d2'),tone('#ad8dbb')),tone('#a080a9'),4);
  path([['moveTo',-20,55],['bezierCurveTo',-50,93,-37,162,-13,181],['quadraticCurveTo',22,192,36,157],['bezierCurveTo',51,103,25,64,-20,55]],gradient(-7,100,106,'#fff0d7','#e6b8bf'),null);
  for(const side of [-1,1]){path([['moveTo',side*58,85],['quadraticCurveTo',side*108,92,side*93,130]],null,tone('#d7a7bf'),19);oval(side*46,209,31,15,tone('#d9b6c9'),tone('#a68aaa'));for(let k=0;k<3;k++)path([['moveTo',side*89+(k-1)*7,125],['quadraticCurveTo',side*96+(k-1)*7,139,side*97+(k-1)*9,136]],null,tone('#eac5cf'),5);}
  path([['moveTo',-122,-53],['bezierCurveTo',-137,-102,-89,-151,-22,-151],['bezierCurveTo',40,-159,115,-136,128,-81],['bezierCurveTo',151,-15,86,34,10,40],['bezierCurveTo',-58,50,-139,12,-122,-53],['closePath']],gradient(-29,-91,184,tone('#ffe5d5'),tone('#c7a2ca')),tone('#aa88ad'),4);
  path([['moveTo',-87,-105],['quadraticCurveTo',-46,-137,-6,-127]],null,tone('#fff0dd'),6);
  for(const side of [-1,1])for(let j=0;j<4;j++)oval(side*(87+j%2*8),-39+j*12,2.5,2.5,tone('#b185b1'));
  fy=-62;ex=47;ink='#674a70';iris='#b394ba';cheek='#e8a4ba';
 }else if(body==='comet-fox'){
  const tone=color=>materialTone(design.bodyColors?.[body],color,bodyColorDefaults[body]);
  const sway=Math.sin(t)*6;
  path([['moveTo',27,151],['bezierCurveTo',107,123,122,34,192,47+sway],['bezierCurveTo',242,58+sway,252,125,219,177],['quadraticCurveTo',230,179,226,188],['quadraticCurveTo',194,231,128,228],['quadraticCurveTo',146,241,134,244],['bezierCurveTo',84,247,43,210,27,151],['closePath']],gradient(160,109,160,tone('#ffca83'),tone('#bd704d')),tone('#935a45'),4);
  path([['moveTo',192,47+sway],['bezierCurveTo',231,62,239,109,225,139],['quadraticCurveTo',208,120,200,139],['quadraticCurveTo',190,118,181,136],['quadraticCurveTo',172,107,158,123],['bezierCurveTo',148,90,165,53,192,47+sway]],gradient(191,89,93,'#fff2cf','#e7c198'),null);
  path([['moveTo',-46,35],['bezierCurveTo',-88,80,-88,168,-55,205],['quadraticCurveTo',0,240,58,203],['bezierCurveTo',86,157,78,78,42,34],['closePath']],gradient(-15,90,155,tone('#ffd395'),tone('#bb7955')),tone('#976146'),4);
  path([['moveTo',-34,46],['quadraticCurveTo',0,57,35,45],['quadraticCurveTo',28,75,41,90],['quadraticCurveTo',22,92,29,112],['quadraticCurveTo',10,105,16,135],['quadraticCurveTo',0,159,-14,136],['quadraticCurveTo',-11,116,-29,116],['quadraticCurveTo',-21,92,-41,96],['quadraticCurveTo',-27,75,-34,46]],gradient(-6,85,86,'#fff0cb','#e6c39c'),null);
  for(const side of [-1,1]){oval(side*46,211,32,18,tone('#b67d5c'),tone('#94624f'));path([['moveTo',side*63,89],['quadraticCurveTo',side*105,112,side*87,146]],null,tone('#d59767'),24);
   path([['moveTo',side*77,-100],['bezierCurveTo',side*83,-151,side*110,-179,side*91,-209],['bezierCurveTo',side*49,-198,side*31,-148,side*27,-125],['closePath']],gradient(side*67,-163,97,tone('#f5bc80'),tone('#b97754')),tone('#965f47'),4);
   path([['moveTo',side*69,-130],['quadraticCurveTo',side*86,-158,side*87,-180],['quadraticCurveTo',side*60,-171,side*49,-138]],'#e8ad9c',null);
  }
  path([['moveTo',-105,-77],['bezierCurveTo',-114,-127,-54,-148,-4,-145],['bezierCurveTo',52,-153,118,-122,110,-71],['quadraticCurveTo',119,-52,131,-49],['quadraticCurveTo',124,-40,115,-40],['quadraticCurveTo',130,-24,145,-25],['quadraticCurveTo',127,-7,108,-7],['quadraticCurveTo',118,4,124,4],['bezierCurveTo',83,36,42,37,0,36],['bezierCurveTo',-43,38,-96,24,-124,4],['quadraticCurveTo',-114,3,-109,-7],['quadraticCurveTo',-132,-10,-142,-26],['quadraticCurveTo',-124,-25,-115,-41],['quadraticCurveTo',-130,-43,-132,-49],['quadraticCurveTo',-113,-53,-105,-77],['closePath']],gradient(-26,-92,190,tone('#ffd498'),tone('#c17e56')),tone('#9b664e'),4);
  for(const side of [-1,1]){path([['moveTo',side*13,-25],['quadraticCurveTo',side*50,-45,side*104,-28],['quadraticCurveTo',side*93,-16,side*116,-10],['quadraticCurveTo',side*77,22,side*18,24],['quadraticCurveTo',0,19,side*13,-25]],gradient(side*48,-10,98,'#fff0d0','#e7c8a8'),null);
   for(let j=0;j<3;j++)path([['moveTo',side*(82+j*9),-45+j*14],['quadraticCurveTo',side*(94+j*9),-40+j*14,side*(100+j*8),-40+j*14]],null,tone('#e7b282'),2);
  }
  fy=-66;ink='#533f43';iris='#9b915f';cheek='#dca495';
 }else if(body==='little-mushroom'){
  const cap=design.bodyColors?.['little-mushroom']?capColors(design.bodyColors['little-mushroom']):null;
  // Slightly bent stem, leaf-like hands and root toes replace a stacked cylinder.
  path([['moveTo',-54,8],['bezierCurveTo',-81,65,-54,123,-74,183],['quadraticCurveTo',-91,216,-55,225],['bezierCurveTo',-19,235,2,208,34,224],['quadraticCurveTo',82,234,83,204],['bezierCurveTo',66,130,91,64,58,12],['closePath']],gradient(-17,88,177,'#fff2d4','#d0b39a'),'#a88e7d',4);
  for(const side of [-1,1]){path([['moveTo',side*61,103],['quadraticCurveTo',side*112,78,side*109,126],['quadraticCurveTo',side*78,145,side*63,118]],gradient(side*88,110,53,'#c8d5a0','#8ca88b'),'#91a187',3);path([['moveTo',side*71,119],['quadraticCurveTo',side*92,112,side*101,100]],null,'#edf0c4',3);for(let j=0;j<3;j++)path([['moveTo',side*(30+j*14),211],['quadraticCurveTo',side*(34+j*17),231,side*(52+j*14),226]],null,'#d0b79b',9);}
  path([['moveTo',-167,-9],['bezierCurveTo',-144,-95,-99,-170,-15,-169],['bezierCurveTo',56,-190,143,-114,172,-39],['quadraticCurveTo',191,-4,165,9],['bezierCurveTo',105,46,-102,43,-167,13],['quadraticCurveTo',-186,6,-167,-9],['closePath']],gradient(-35,-102,244,(cap?.light||'#f6b58f'),(cap?.shade||'#b55e75')),(cap?.edge||'#a3656c'),4);
  path([['moveTo',-158,8],['bezierCurveTo',-113,30,107,51,163,5],['quadraticCurveTo',174,34,128,47],['bezierCurveTo',69,66,-92,58,-145,35],['quadraticCurveTo',-167,25,-158,8],['closePath']],gradient(-22,19,200,(cap?.rimLight||'#ffe6be'),(cap?.rimShade||'#ca9d95')),(cap?.rimEdge||'#bd8d8d'),3);
  for(let j=0;j<19;j++){const x=-143+j*16;path([['moveTo',x,18+Math.sin(j*.4)*5],['quadraticCurveTo',x*.8,35,x*.33,49]],null,j%2?(cap?.gill||'#d1ac9f'):(cap?.gillLight||'#f4d6b5'),2);}
  path([['moveTo',-145,-19],['bezierCurveTo',-95,8,88,31,154,-13]],null,(cap?.seam||'#f1bca3'),7);
  for(const [x,y,rx,ry] of [[-105,-50,23,14],[-55,-112,28,20],[25,-122,24,17],[92,-73,30,19],[123,-31,13,9],[-19,-47,17,11]]){
   path([['moveTo',x-rx,y],['bezierCurveTo',x-rx,y-ry*1.5,x+rx*.7,y-ry,x+rx,y],['bezierCurveTo',x+rx*.8,y+ry,x-rx*.8,y+ry,x-rx,y],['closePath']],'#ffe5c2',null);
  }
  path([['moveTo',-113,-72],['quadraticCurveTo',-79,-121,-29,-139]],null,(cap?.glint||'#ffdcc0'),5);
  fy=101;ex=31;ew=22;eh=26;ink='#674e50';iris='#9c9571';cheek='#dfa7a0';
 }
 // Keep detail out of the central facial reading; features remain independently animated.
 for(const side of [-1,1]){const x=side*ex,open=eh*p.eye;
  if(frame===10||p.eye<.14)path([['moveTo',x-ew,fy],['quadraticCurveTo',x,fy+7,x+ew,fy]],null,ink,5);
  else{oval(x,fy,ew,open,'#fff5dd',ink,3);oval(x+p.gaze,fy+3,ew*.57,Math.min(eh*.7,open*.8),gradient(x-5,fy-6,36,iris,ink));oval(x+p.gaze,fy+4,ew*.3,Math.min(eh*.49,open*.6),'#20313e');oval(x+p.gaze-5,fy-7,5,6,'#fffdf0');}
  path([['moveTo',x-side*ew,fy-eh-12+p.inner],['quadraticCurveTo',x,fy-eh-22,x+side*ew,fy-eh-12+p.outer]],null,ink,4);
  oval(side*(ex+ew+8),fy+35,11,5,cheek);
 }
 const my=fy+54,mw=cue==='joy'?32:25,bulge=cue==='joy'?13:p.mouth,opening=cue==='joy'?7:p.open;
 if(opening)path([['moveTo',-mw,my],['quadraticCurveTo',0,my+bulge*2,mw,my],['quadraticCurveTo',0,my+(bulge+opening)*2,-mw,my]],ink,null);
 path([['moveTo',-mw,my],['quadraticCurveTo',0,my+bulge*2,mw,my]],null,ink,5);
 if(body==='comet-fox')path([['moveTo',-8,fy+31],['quadraticCurveTo',0,fy+27,8,fy+31],['quadraticCurveTo',0,fy+40,-8,fy+31]],'#735752',null);
 c.setTransform(1,0,0,1,0,0);return canvas;
}
