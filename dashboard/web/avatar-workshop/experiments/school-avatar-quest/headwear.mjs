// Authored fits for the six current masters, not anatomy inferred from pixels.
const fits={
 'pocket-dragon':{x:288,y:195,width:154,angle:-.07},
 'modular-bot':{x:288,y:201,width:198,angle:.04},
 'moon-visitor':{x:280,y:180,width:202,angle:-.08},
 'cloud-axolotl':{x:281,y:201,width:184,angle:-.05},
 'comet-fox':{x:288,y:209,width:150,angle:.08},
 'little-mushroom':{x:281,y:190,width:176,angle:-.1},
};
export function canWearHeadwear(d){return !d.image&&!d.avatarModel&&Object.hasOwn(fits,d.body)&&(d.characterStyle==='surface/v2'||d.characterStyle==='surface/v1'&&['pocket-dragon','modular-bot'].includes(d.body));}
export function headwearFit(body,frame=0,style='surface/v2'){
 if(!fits[body]||style!=='surface/v2'&&!(style==='surface/v1'&&['pocket-dragon','modular-bot'].includes(body)))return null;
 const fit=fits[body];return {...fit,y:fit.y+Math.sin(frame/12*Math.PI*2)*3};
}
export function drawHeadwear(c,id,colors,frame=0){
 const t=frame/12*Math.PI*2;
 const path=(points,fill,stroke=null,width=2.5)=>{c.beginPath();for(const [op,...v] of points)c[op](...v);if(fill){c.fillStyle=fill;c.fill();}if(stroke){c.strokeStyle=stroke;c.lineWidth=width;c.stroke();}};
 const oval=(x,y,rx,ry,fill,stroke=null)=>{c.beginPath();c.ellipse(x,y,rx,ry,0,0,Math.PI*2);c.fillStyle=fill;c.fill();if(stroke){c.strokeStyle=stroke;c.lineWidth=2;c.stroke();}};
 const shaded=c.createLinearGradient(-40,-65,45,8);shaded.addColorStop(0,colors.light);shaded.addColorStop(1,colors.ink);
 if(id==='wizard-hat'){
  // A curved, folded cone and broad ellipse: soft cloth rather than a triangle.
  path([['moveTo',-39,-8],['bezierCurveTo',-32,-34,-25,-66,-6,-85],['bezierCurveTo',8,-99,27,-88,31,-76],['quadraticCurveTo',17,-82,11,-70],['bezierCurveTo',4,-48,26,-28,40,-7],['closePath']],shaded,'#4e5267');
  oval(0,-3,64,12,shaded,'#4e5267');
  path([['moveTo',-34,-18],['quadraticCurveTo',0,-8,33,-18],['lineTo',40,-7],['quadraticCurveTo',0,4,-40,-7],['closePath']],'#546b8b');
  oval(-9,-44,8,10,colors.light);oval(-4,-47,7,9,colors.ink);
  for(const [x,y] of [[8,-30],[-2,-66]]){path([['moveTo',x-4,y],['lineTo',x+4,y],['moveTo',x,y-4],['lineTo',x,y+4]],null,colors.light,2);}
 }
 if(id==='artist-beret'){
  path([['moveTo',-56,-7],['bezierCurveTo',-78,-32,-43,-62,1,-61],['bezierCurveTo',46,-65,76,-40,61,-18],['quadraticCurveTo',45,-1,-56,-7],['closePath']],shaded,'#575568');
  path([['moveTo',-48,-10],['quadraticCurveTo',0,-19,48,-10],['lineTo',43,2],['quadraticCurveTo',0,10,-44,1],['closePath']],colors.ink,'#575568');
  for(const side of [-1,1])path([['moveTo',side*13,-52],['quadraticCurveTo',side*35,-39,side*39,-23]],null,colors.light,2);
  path([['moveTo',5,-59],['quadraticCurveTo',14,-69,8,-73]],null,colors.ink,6);
  oval(40,-24,7,8,'#e2b3b2');oval(38,-26,2,2,'#fff1d6');
 }
 if(id==='leaf-crown'){
  path([['moveTo',-61,-6],['quadraticCurveTo',0,-25,61,-6]],null,'#668d78',6);
  for(let i=-3;i<=3;i++){
   const x=i*17,y=-11-Math.cos(i/4*Math.PI/2)*7,sway=Math.sin(t+i*.6)*1.2;
   c.save();c.translate(x,y);c.rotate(i*.15+sway*.025);
   path([['moveTo',0,0],['bezierCurveTo',-21,-9,-13,-27,-5,-32],['bezierCurveTo',3,-26,11,-10,0,0],['closePath']],i%2?colors.ink:'#88b699','#526f66');
   path([['moveTo',0,-1],['quadraticCurveTo',-4,-12,-5,-27]],null,colors.light,1.8);
   c.restore();
  }
  for(const x of [-38,30]){oval(x,-7,5,5,'#e5b4b4');oval(x+4,-10,2,2,'#ffe9d2');}
 }
}
