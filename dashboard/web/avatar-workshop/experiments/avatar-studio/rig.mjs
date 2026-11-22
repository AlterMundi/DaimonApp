// Authored local actions, not inferred internal states. Values are local offsets
// applied to ordered feature arcs; identity lines retain their base coordinates.
export const cues=['calm','curious','joy','sad','anger','uncertain','focus','welcome'];
const neutral={open:0,lift:0,spread:0,curl:0,asym:0,look:0,droop:0,energy:0};
const poses={
 calm:{open:.03,lift:0,spread:.02,curl:0,asym:0,look:0,droop:0,energy:.12},
 curious:{open:.2,lift:.16,spread:.1,curl:.16,asym:.2,look:.16,droop:0,energy:.3},
 joy:{open:.38,lift:.38,spread:.42,curl:.28,asym:0,look:0,droop:-.18,energy:.6},
 sad:{open:-.28,lift:-.3,spread:-.38,curl:-.28,asym:0,look:-.08,droop:.3,energy:.08},
 anger:{open:-.36,lift:.2,spread:-.16,curl:.42,asym:0,look:.02,droop:-.04,energy:.22},
 uncertain:{open:-.1,lift:.02,spread:.04,curl:-.14,asym:.34,look:-.12,droop:.1,energy:.18},
 focus:{open:-.24,lift:.08,spread:-.24,curl:.1,asym:0,look:.04,droop:0,energy:.08},
 welcome:{open:.3,lift:.12,spread:.32,curl:.24,asym:.06,look:.1,droop:-.04,energy:.2}
};
export function localPose(cue,frame=0,strength=1){const active=cues.includes(cue),p=active?poses[cue]:neutral,t=((frame%12)+12)%12/12*Math.PI*2,k=Math.max(0,Math.min(1,strength));return {active:active&&k>0,...Object.fromEntries(Object.keys(neutral).map(key=>[key,p[key]*k])),pulse:active?Math.sin(t)*p.energy*k:0,strength:active?k:0};}
