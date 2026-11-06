// Retained surface/v1 masters. Keep saved edition geometry stable.
import {dragonMaster,dragonExpressions} from './precision-renderer.mjs';
export function legacyMaster(body,frame,cue,design){
 if(body==='pocket-dragon')return dragonMaster(frame,cue,design.strength??1);
 const canvas=document.createElement('canvas');canvas.width=576;canvas.height=720;const c=canvas.getContext('2d'),t=frame/12*Math.PI*2,chosen=dragonExpressions[cue]||dragonExpressions.calm,p=Object.fromEntries(Object.entries(chosen).map(([k,v])=>[k,typeof v==='number'?dragonExpressions.calm[k]+(v-dragonExpressions.calm[k])*(design.strength??1):v]));
 c.translate(288,350+Math.sin(t)*3);c.lineCap='round';c.lineJoin='round';
 const gradient=(x,y,r,a,b)=>{const g=c.createRadialGradient(x-r*.3,y-r*.35,1,x,y,r);g.addColorStop(0,a);g.addColorStop(1,b);return g;};
 const oval=(x,y,rx,ry,fill,stroke=null)=>{c.beginPath();c.ellipse(x,y,rx,ry,0,0,Math.PI*2);c.fillStyle=fill;c.fill();if(stroke){c.strokeStyle=stroke;c.lineWidth=4;c.stroke();}};
 const line=(points,fill=null,stroke='#244853',width=4)=>{c.beginPath();for(const [fn,...args] of points)c[fn](...args);if(fill){c.fillStyle=fill;c.fill();}if(stroke){c.strokeStyle=stroke;c.lineWidth=width;c.stroke();}};
 const round=(x,y,w,h,r,fill,stroke='#244853')=>{c.beginPath();c.roundRect(x,y,w,h,r);c.fillStyle=fill;c.fill();if(stroke){c.strokeStyle=stroke;c.lineWidth=4;c.stroke();}};
 let fy=-60,eyeSpace=43,eyeW=27,eyeH=32,faceInk='#263e4b';
 if(body==='modular-bot'){
  line([['moveTo',0,-155],['quadraticCurveTo',Math.sin(t)*12,-180,0,-205]],null,'#789ba6',7);oval(0,-211,13,13,gradient(-3,-215,24,'#ffdda5','#ce7864'));
  round(-72,56,144,144,35,gradient(-20,90,160,'#c7d8e5','#687f9e'));round(-43,84,86,65,14,'#304c69');oval(0,117,18,18,gradient(-4,111,26,'#ffe9a1','#de9363'));
  for(const s of [-1,1]){round(s*58-25,194,50,24,11,'#8eacc1');line([['moveTo',s*68,90],['quadraticCurveTo',s*105,99,s*108,120+Math.sin(t)*6]],null,'#7294a9',10);round(s*108-18,112+Math.sin(t)*6,36,34,11,'#9fbac6');round(s*132-12,-91,24,54,10,'#748ea9');}
  round(-123,-151,246,194,43,gradient(-40,-106,240,'#d8e8e7','#7395a9'));round(-100,-127,200,145,31,gradient(-30,-90,180,'#c5eddb','#78b3b7'));fy=-60;
  for(const s of [-1,1])oval(s*95,-137,5,5,'#f1c47f');
 }else if(body==='moon-visitor'){
  for(let i=-2;i<=2;i++){const x=i*40,end=x+Math.sin(t+i)*17;line([['moveTo',x,35],['bezierCurveTo',x-30,100,end+30,158,end,223-Math.abs(i)*10]],null,i%2?'#b4acde':'#79c5d2',15);oval(end,223-Math.abs(i)*10,10,10,'#e9b4cb');}
  line([['moveTo',-145,36],['bezierCurveTo',-157,-204,154,-204,145,36],['quadraticCurveTo',105,9,80,35],['quadraticCurveTo',40,11,0,36],['quadraticCurveTo',-40,12,-80,35],['quadraticCurveTo',-108,12,-145,36],['closePath']],gradient(-30,-68,230,'#e0cdeb','#708fc6'),'#597491',5);
  oval(-55,-112,22,12,'#e7dced');oval(45,-117,13,8,'#d5e6e9');fy=-52;faceInk='#414779';
 }else if(body==='cloud-axolotl'){
  for(const side of [-1,1])for(let j=-1;j<=1;j++){const end=[side*(169-Math.abs(j)*10),-59+j*48+Math.sin(t+j)*5];line([['moveTo',side*103,-56+j*25],['quadraticCurveTo',side*147,-49+j*35,...end]],null,'#bc7e9e',12);oval(...end,25,15,gradient(end[0]-5,end[1]-5,38,'#f8c4cb','#ce91b2'));}
  oval(0,119,69,98,gradient(-20,90,130,'#f9d9d6','#b791bb'),'#947b9f');oval(0,132,40,60,'#fbe8d6');for(const side of [-1,1]){oval(side*72,113,20,33,'#d8adbf');oval(side*45,205,30,18,'#e4c0c8');}
  oval(0,-57,126,95,gradient(-25,-97,178,'#ffe4d8','#ccacca'),'#997fa7');fy=-61;eyeSpace=47;faceInk='#654e77';
 }else if(body==='comet-fox'){
  line([['moveTo',43,161],['bezierCurveTo',168,200,231,89,173,42],['quadraticCurveTo',182,115,84,106],['closePath']],gradient(133,119,120,'#f5b875','#ba674a'),'#875344');line([['moveTo',173,42],['quadraticCurveTo',191,81,177,113],['quadraticCurveTo',153,99,143,107]],'#f7e5bb',null);
  oval(0,121,70,98,gradient(-17,90,136,'#ffd397','#bf7954'),'#875344');oval(0,128,41,67,'#f7e4bf');for(const side of [-1,1]){oval(side*71,116,21,32,'#d89362');oval(side*47,208,30,17,'#bc7c59');line([['moveTo',side*82,-88],['quadraticCurveTo',side*114,-194,side*97,-207],['lineTo',side*25,-129],['closePath']],gradient(side*80,-157,94,'#eeb57d','#be7852'),'#875344');line([['moveTo',side*76,-123],['lineTo',side*94,-176],['lineTo',side*48,-132]],'#edc1b0',null);}
  oval(0,-60,116,92,gradient(-27,-97,173,'#ffd397','#c48058'),'#875344');for(const side of [-1,1])oval(side*43,-23,52,41,'#f3dfbc');fy=-65;faceInk='#4c4145';
 }else if(body==='little-mushroom'){
  fy=60;eyeSpace=31;eyeW=22;eyeH=26;faceInk='#604b48';
  oval(0,111,78,117,gradient(-20,65,161,'#fff0d2','#cdb397'),'#967e76');for(const side of [-1,1]){oval(side*73,125,18,29,'#e5ceb1');oval(side*43,214,29,17,'#baa492');}
  line([['moveTo',-160,-12],['bezierCurveTo',-150,-191,137,-199,162,-12],['quadraticCurveTo',0,30,-160,-12],['closePath']],gradient(-37,-100,225,'#f6ad9e','#b46077'),'#895e72',5);
  oval(0,-7,155,24,gradient(-22,-17,170,'#f9dfc8','#b68a9d'),'#977383');
  for(const [x,y,rx,ry] of [[-87,-57,24,18],[-30,-111,30,22],[53,-93,24,20],[112,-43,16,11]])oval(x,y,rx,ry,'#ffe5ca');
 }
 // Separate eye whites, irises, highlights, brows and dark mouth; the cap/bell is not a face substitute.
 for(const side of [-1,1]){const x=side*eyeSpace,eh=eyeH*p.eye;
  if(frame===10)line([['moveTo',x-eyeW,fy],['quadraticCurveTo',x,fy+7,x+eyeW,fy]],null,faceInk,5);
  else{oval(x,fy,eyeW,eh,'#fbf4d9',faceInk);oval(x+p.gaze,fy+3,eyeW*.57,Math.min(eyeH*.7,eh*.8),gradient(x-4,fy-5,35,'#8ca69d',faceInk));oval(x+p.gaze,fy+4,eyeW*.3,Math.min(eyeH*.49,eh*.6),'#20313e');oval(x+p.gaze-5,fy-7,5,6,'#fffbed');}
  line([['moveTo',x-side*eyeW,fy-eyeH-12+p.inner],['quadraticCurveTo',x,fy-eyeH-22,(x+side*eyeW),fy-eyeH-12+p.outer]],null,faceInk,4);
  oval(side*(eyeSpace+eyeW+8),fy+35,11,5,body==='modular-bot'?'#9cbba7':'#d79ca5');
 }
 const my=fy+(body==='modular-bot'?52:56),mw=cue==='joy'?32:25,bulge=cue==='joy'?13:p.mouth,opening=cue==='joy'?7:p.open;
 if(opening){line([['moveTo',-mw,my],['quadraticCurveTo',0,my+bulge*2,mw,my],['quadraticCurveTo',0,my+(bulge+opening)*2,-mw,my]],faceInk,null);}
 line([['moveTo',-mw,my],['quadraticCurveTo',0,my+bulge*2,mw,my]],null,faceInk,5);
 if(body==='comet-fox')oval(0,fy+33,7,4,'#756258');
 c.setTransform(1,0,0,1,0,0);return canvas;
}
