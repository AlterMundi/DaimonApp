import {childBodies,characterFrame} from './characters.mjs';
import {abstractBodies,abstractPortrait} from './abstract.mjs';
export const expressions=['calm','curious','focused','listening','speaking','delighted','uncertain'];
export const defaults={name:'Mi daimon',body:'core',eyes:'stars',mouth:'soft',accessory:'halo',texture:'dots',outfit:'scarf',aura:'stars',arms:true,color:'#654ba0',material:'fiber',aperture:1,complexity:1,rhythm:1,direction:1,relation:'original'};
// A 72x40 master is composed from silhouette, material, facial rig and ornaments.
// Compact views are independently composed; no bitmap assets or external art.
export function portrait(s,expression='calm',frame=0,cols=72,rows=40){
 if(s.characterStyle==='storybook/v1'&&childBodies.includes(s.body))return characterFrame(s,frame,cols,rows).text;
 if(abstractBodies.includes(s.body))return abstractPortrait(s,expression,frame,cols,rows);
 const compact=cols<48,W=compact?40:72,H=compact?28:40,cx=W/2,cy=compact?14:20;
 const g=Array.from({length:H},()=>Array(W).fill(' '));
 const put=(x,y,c)=>{x=Math.round(x);y=Math.round(y);if(g[y]&&x>=0&&x<W)g[y][x]=c;};
 const stamp=(x,y,str)=>str.split('\n').forEach((l,j)=>[...l].forEach((c,i)=>put(x+i,y+j,c)));
 const rx=compact?12:19,ry=compact?8:12;
 function field(x,y){const a=(x-cx)/rx,b=(y-cy)/ry;
  if(s.body==='fox'){const head=a*a+b*b-1;const ear=Math.min(Math.max(Math.abs(a+.68)*2.8+Math.abs(b+1.05)*1.3-.6, -b-1.6),Math.max(Math.abs(a-.68)*2.8+Math.abs(b+1.05)*1.3-.6,-b-1.6));return Math.min(head,ear);}
  if(s.body==='bloom')return Math.hypot(a,b)-(.87+.16*Math.cos(Math.atan2(b,a)*7));
  if(s.body==='diamond')return Math.abs(a)*.73+Math.abs(b)*.85-1;
  if(s.body==='robot')return Math.max(Math.abs(a)-.92,Math.abs(b)-.84);
  if(s.body==='jelly')return Math.max(a*a+b*b-1,b-.44-.07*Math.sin(x*.65));
  if(s.body==='flame')return Math.max(Math.abs(a)-(.78-.25*b)*(1-Math.abs(b)*.5)+.065*Math.sin(b*12+a*3),Math.abs(b)-1.12);
  if(s.body==='moth')return Math.min(Math.pow((Math.abs(a)-.63)/.55,2)+Math.pow(b/.9,2)-1,Math.abs(a)*4.5+Math.abs(b)*.55-.8);
  return a*a+b*b-1;
 }
 for(let y=3;y<H-3;y++)for(let x=3;x<W-3;x++){
  const f=field(x,y);if(f>0)continue;
  const edge=[[1,0],[-1,0],[0,1],[0,-1]].some(([a,b])=>field(x+a,y+b)>0);
  const a=(x-cx)/rx,b=(y-cy)/ry;
  if(edge){const dx=field(x+1,y)-field(x-1,y),dy=field(x,y+1)-field(x,y-1);put(x,y,Math.abs(dx)>Math.abs(dy)*1.7?'|':Math.abs(dy)>Math.abs(dx)*1.4?(dy<0?'_':'-'):dx*dy>0?'\\':'/');continue;}
  const dark=Math.max(0,Math.min(1,.28+a*.26+b*.20+Math.pow(Math.abs(a),3)*.25));
  let c=' .,:;+=#'[Math.floor(dark*7)];
  if(s.texture==='stars')c=((x*17+y*13)%67===0)?'*':((x+y*7)%19===0?'.':' ');
  if(s.texture==='waves')c=((Math.round(x*.3+Math.sin(y*.45)*2)+y)%5===0)?'~':c===' ' ?' ':'.';
  if(s.texture==='solid')c=' .:-=+*#%@'[Math.min(9,Math.floor(dark*10))];
  if(s.texture==='lace')c=(x+y)%4===0?'+':(x-y)%6===0?':':' ';
  put(x,y,c);
 }
 if(s.body==='diamond'){for(let i=0;i<ry;i++){put(cx-i*.9,cy-i,'/');put(cx+i*.9,cy-i,'\\');put(cx,cy+i,'|');}}
 if(s.body==='robot'){stamp(cx-11,cy-ry+3,'[ :: :: :: :: :: ]');stamp(cx-9,cy+ry-3,'[o] --==-- [o]');stamp(cx-rx-4,cy-2,'[=]');stamp(cx+rx+1,cy-2,'[=]');}
 if(s.body==='moth'){
  for(const side of [-1,1]){stamp(cx+side*(rx*.8)-3,cy-4,'( o )');stamp(cx+side*(rx*.8)-3,cy+5,'< : >');for(let i=0;i<7;i++)put(cx+side*(3+i*1.8),cy+ry*.65-i*.25,'/');}
 }
 if(s.body==='jelly')for(let k=-2;k<=2;k++)for(let i=0;i<9;i++)put(cx+k*5+Math.sin(i*.8+k)*1.7,cy+ry*.48+i,i%3===0?':':'|');
 if(s.arms){for(const side of [-1,1]){for(let i=0;i<6;i++)put(cx+side*(rx+1+i),cy+3-i*.5,side<0?'/':'\\');stamp(cx+side*(rx+6)-1,cy,'\'o\'');}}
 // Reserve facial negative space: texture never competes with eye recognition.
 const faceHalf=compact?8:10;for(let y=cy-4;y<=cy+4;y++)for(let x=cx-faceHalf;x<=cx+faceHalf;x++)put(x,y,' ');
 const blink=frame===1,eye=blink?'---':expression==='delighted'?'^_^':expression==='uncertain'?'o.O':expression==='focused'?'=-=':({stars:'<*>',round:'(o)',sleepy:'-.-',tiny:' . ',alien:'(@)'})[s.eyes]||'(o)';
 stamp(cx-8,cy-1,eye);stamp(cx+5,cy-1,eye);
 if(!compact){stamp(cx-9,cy-3,expression==='curious'?" /~ ":' ___');stamp(cx+4,cy-3,expression==='uncertain'?' /  ':' ___');stamp(cx-10,cy+2,":' ");stamp(cx+8,cy+2," ':");}
 stamp(cx-1,cy+1,'.');
 const mouth=expression==='speaking'?(frame%2?'( O )':'( o )'):expression==='delighted'?"\\___/":expression==='uncertain'?' ~~~ ':({soft:'  v  ',smile:'\\___/',flat:' --- ',open:' (o) ',none:'     '})[s.mouth]||'  v  ';
 stamp(cx-2,cy+3,mouth);
 const top=Math.round(cy-ry-2);
 if(s.accessory==='antenna'){stamp(cx-1,Math.max(0,top-3),'(*)\n | \n | ');}
 if(s.accessory==='halo'){stamp(cx-9,Math.max(0,top-2),"  .--------------.\n (  *   .   *   . )\n  '--------------'");}
 if(s.accessory==='ears'){stamp(cx-13,Math.max(0,top-3),'/\\                 /\\\n/  \\               /  \\');}
 if(s.accessory==='horns'){stamp(cx-12,Math.max(0,top-3),' /)                 (\\\n((                   ))\n \\)                 (/');}
 if(s.accessory==='crown'){stamp(cx-9,Math.max(0,top-3),' .     *     .\n |\\   / \\   /|\n | \\_/   \\_/ |\n +---o---o---+');}
 const y=Math.round(cy+ry-1);
 if(s.outfit==='scarf'){stamp(cx-10,y,'==~=~=~=~=~=~=~=~=~===');stamp(cx+5,y+1,'| : |\n| : |\nv v v');}
 if(s.outfit==='amulet')stamp(cx-5,y-1,'\\       /\n \\     /\n  \\(*)/');
 if(s.outfit==='collar')stamp(cx-11,y,'\\_/\\_/\\_/\\_/\\_/\\_/');
 if(s.aura==='stars'){for(const [x,y] of [[6,8],[W-8,6],[9,H-8],[W-10,H-5]])stamp(x,y,'+');put(5,13,'.');put(W-5,15,'*');}
 if(s.aura==='orbit'){for(let i=0;i<35;i++){const a=i/35*Math.PI*2;put(cx+Math.cos(a)*(rx+9),cy+Math.sin(a)*5, i%6===0?'*':'.');}}
 let output=g.map(r=>r.join('').replace(/ +$/,'')).join('\n');
 if(compact&&cols<40){const left=Math.floor((40-cols)/2);output=g.map(r=>r.slice(left,left+cols).join('').replace(/ +$/,'')).slice(0,rows).join('\n');}
 return output;
}
export function toAscii(pixels,width,height,cols,contrast=1,invert=false,ramp=' .:-=+*#%@',method='tone'){
 const rows=Math.max(1,Math.round(height/width*cols*.5)),lines=[];
 function lum(x,y){x=Math.max(0,Math.min(width-1,x));y=Math.max(0,Math.min(height-1,y));const i=(y*width+x)*4,a=pixels[i+3]/255;return (.2126*pixels[i]+.7152*pixels[i+1]+.0722*pixels[i+2])*a+255*(1-a);}
 for(let y=0;y<rows;y++){let line='';for(let x=0;x<cols;x++){
 const x0=Math.floor(x/cols*width),x1=Math.max(x0+1,Math.floor((x+1)/cols*width)),y0=Math.floor(y/rows*height),y1=Math.max(y0+1,Math.floor((y+1)/rows*height));let sum=0,n=0;
 for(let py=y0;py<y1;py+=Math.max(1,Math.floor((y1-y0)/6)))for(let px=x0;px<x1;px+=Math.max(1,Math.floor((x1-x0)/6))){sum+=lum(px,py);n++;}
 let l=Math.max(0,Math.min(255,(sum/n-128)*contrast+128));const d=invert?l/255:1-l/255;let c=ramp[Math.round(d*(ramp.length-1))];
 if(method==='structure'){const px=Math.floor((x0+x1)/2),py=Math.floor((y0+y1)/2),sx=Math.max(1,Math.round((x1-x0)/2)),sy=Math.max(1,Math.round((y1-y0)/2));const dx=lum(px+sx,py)-lum(px-sx,py),dy=lum(px,py+sy)-lum(px,py-sy);if(Math.hypot(dx,dy)>55)c=Math.abs(dx)>Math.abs(dy)*1.7?'|':Math.abs(dy)>Math.abs(dx)*1.7?'_':dx*dy>0?'\\':'/';}
 line+=c;}lines.push(line);}return lines.join('\n');
}
export function pack(s,image=null){
 const id='avatar-'+(s.name||'daimon').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9_-]/g,'-').slice(0,45);
 const abstract=abstractBodies.includes(s.body);
 const variants=(e)=>image?{portrait:{frames:[image],frame_ms:120}}:{portrait:{frames:Array.from({length:abstract?12:3},(_,i)=>portrait(s,e,abstract?i:i%3)),frame_ms:abstract?Math.round(160/(Number(s.rhythm)||1)):240},compact:{frames:[portrait(s,e,0,32,24)],frame_ms:240}};
 const v=image?'portrait':'portrait',cols=image?Math.max(...image.split('\n').map(l=>l.length)):72,rows=image?image.split('\n').length:40;
 return {schema:'daimon.ascii-expression/v1',id,revision:'atelier-4',authorship:'Created in ASCII Avatar Atelier; '+(image?'static image conversion, same portrait in every state':'original procedural glyph character'),expressions:Object.fromEntries(expressions.map(e=>[e,{alt:(s.name||'Daimon')+' / '+e+(image?' / static portrait':''),variants:variants(e)}])),defaults:Object.fromEntries(['app','cli','telegram'].map(c=>[c,{expression:'calm',variant:v,columns:cols,rows}]))};
}
