// One cushion master for inventory and performance; scale/compression share a pivot.
export function drawPillow(c,center,size=1,squeeze=0,colors,tilt=0){
 c.save();c.translate(...center);c.rotate(tilt);c.scale(size*(1+squeeze*.3),size*(1-squeeze));
 const g=c.createLinearGradient(-65,-45,60,50);g.addColorStop(0,colors.light);g.addColorStop(.58,colors.light);g.addColorStop(1,colors.ink);
 // Wide puffy body with four pinched corners. Broad piping survives glyph sampling.
 c.beginPath();c.moveTo(-85,-48);c.quadraticCurveTo(-69,-55,-64,-45);c.bezierCurveTo(-30,-57,30,-57,64,-45);c.quadraticCurveTo(87,-58,85,-35);c.quadraticCurveTo(97,0,85,35);c.quadraticCurveTo(91,58,64,45);c.bezierCurveTo(27,58,-29,58,-64,45);c.quadraticCurveTo(-89,57,-85,35);c.quadraticCurveTo(-97,0,-85,-35);c.closePath();c.fillStyle=g;c.fill();c.strokeStyle=colors.ink;c.lineWidth=6;c.stroke();
 c.beginPath();c.roundRect(-74,-39,148,78,26);c.strokeStyle='#685278';c.globalAlpha=.8;c.lineWidth=4;c.stroke();c.globalAlpha=1;
 // A short fold at the contact side and broad highlight communicate fabric loft.
 c.beginPath();c.moveTo(-66,-29);c.quadraticCurveTo(-35,-41,9,-35);c.strokeStyle=colors.light;c.lineWidth=7;c.lineCap='round';c.stroke();
 for(const side of [-1,1]){c.beginPath();c.moveTo(side*78,side*39);c.lineTo(side*65,side*27);c.strokeStyle='#685278';c.lineWidth=4;c.stroke();}
 c.beginPath();c.moveTo(58,-42);c.quadraticCurveTo(73,0,58,43);c.strokeStyle=colors.ink;c.lineWidth=7;c.stroke();c.restore();
}
