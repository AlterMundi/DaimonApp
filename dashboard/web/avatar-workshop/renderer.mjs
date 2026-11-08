import {installSurfaceRenderer,validate,drawFrame,animationSpec} from './experiments/school-avatar-quest/model.mjs';
import {surfaceFrame,surfaceScene} from './experiments/school-avatar-quest/surface-renderer.mjs';
import {paintAscii} from './experiments/school-avatar-quest/color.mjs';
installSurfaceRenderer(surfaceFrame,surfaceScene);
// Same articulated masters/glyph conversion as the workshop. This is an
// authored artistic cue, never a translation of microphone or agent state.
export function prepare(canvas,raw){
 const design=validate(raw),savedGesture=design.activeGestureId,compact=canvas.getBoundingClientRect().width<320;
 const first=drawFrame(design,0,true,compact);
 if(!first||!first.text)throw Error('Avatar drawing unavailable');
 paintAscii(canvas,first,design,0);
 const paint=frame=>paintAscii(canvas,drawFrame(design,frame,true,canvas.getBoundingClientRect().width<320),design,frame);
 const cadence=()=>{const spec=animationSpec(design);Object.assign(paint,{frames:spec.frames,frameMs:spec.frames===12?180:spec.frameMs});};
 paint.selectCue=cue=>{
  // Choose only an already-authored local gesture. This clone is never saved.
  const chosen=design.gestures.find(g=>g.rig==='local/v1'&&g.cue===cue)?.id||savedGesture;
  if(chosen===design.activeGestureId)return false;
  design.activeGestureId=chosen;cadence();return true;
 };
 cadence();return paint;
}
