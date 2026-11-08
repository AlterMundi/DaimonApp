// One cushion master for inventory and performance; scale/compression share a pivot.
export function drawPillow(c,center,size=1,squeeze=0,colors,tilt=0){
 c.save();c.translate(...center);c.rotate(tilt);c.scale(size*(1+squeeze*.3),size*(1-squeeze));
 const g=c.createLinearGradient(-40,-25,45,30);g.addColorStop(0,colors.light);g.addColorStop(1,colors.ink);
 c.beginPath();c.moveTo(-55,-28);c.bezierCurveTo(-19,-40,22,-40,55,-28);c.quadraticCurveTo(46,0,55,28);c.bezierCurveTo(20,39,-20,39,-55,28);c.quadraticCurveTo(-46,0,-55,-28);c.closePath();c.fillStyle=g;c.fill();c.strokeStyle=colors.ink;c.lineWidth=4;c.stroke();
 c.beginPath();c.roundRect(-43,-23,86,46,15);c.strokeStyle=colors.light;c.lineWidth=2;c.setLineDash([3,5]);c.stroke();c.setLineDash([]);
 c.beginPath();c.moveTo(-34,-16);c.quadraticCurveTo(-12,-23,8,-20);c.strokeStyle=colors.light;c.lineWidth=4;c.lineCap='round';c.stroke();c.restore();
}
