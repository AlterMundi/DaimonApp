// Authored associations drawn from the project's research; not emotion measurements.
export const gallery=[
 {id:'calm',name:'Calma',description:'Un centro estable, espacio y un pulso lento.',reading:'Puede sentirse sereno o en reposo.',shape:{opening:1,bend:0,width:1,height:1,lean:0,tempo:.6,motion:'together'}},
 {id:'curious',name:'Curiosidad',description:'Se abre un poco y se inclina hacia algo.',reading:'Puede leerse como interés o exploración.',shape:{opening:1.2,bend:.3,width:1.08,height:.98,lean:.18,tempo:1.1,motion:'rejoin'}},
 {id:'joy',name:'Alegría',description:'Se expande y sus partes vuelven a encontrarse.',reading:'Puede sugerir entusiasmo, celebración o alivio.',shape:{opening:1.4,bend:.2,width:1.18,height:1.12,lean:-.05,tempo:1.6,motion:'rejoin'}},
 {id:'sad',name:'Tristeza',description:'Se recoge y baja su ritmo.',reading:'Puede sugerir tristeza, cansancio o recogimiento.',shape:{opening:.78,bend:.65,width:.88,height:.94,lean:-.12,tempo:.5,motion:'together'}},
 {id:'anger',name:'Enojo',description:'Se comprime; las partes sostienen una tensión distinta.',reading:'Puede leerse como enojo, resistencia o tensión.',shape:{opening:.65,bend:-.8,width:1.02,height:.84,lean:.05,tempo:1.35,motion:'offset'}},
 {id:'uncertain',name:'Duda',description:'Una forma asimétrica, con sus partes desfasadas.',reading:'Puede sugerir duda, búsqueda o desconcierto.',shape:{opening:.95,bend:-.45,width:.94,height:1.06,lean:.2,tempo:.8,motion:'offset'}},
 {id:'focus',name:'Concentración',description:'Se estrecha y reúne su espacio alrededor del centro.',reading:'Puede leerse como atención o concentración.',shape:{opening:.65,bend:-.2,width:.82,height:1.12,lean:0,tempo:.7,motion:'together'}},
 {id:'welcome',name:'Bienvenida',description:'Deja más espacio y se abre hacia un lado.',reading:'Puede sugerir cercanía, acogida o disposición.',shape:{opening:1.35,bend:.8,width:1.12,height:.96,lean:.12,tempo:.85,motion:'together'}}
];
export function galleryGesture(entry){return {id:'gallery-'+entry.id,name:entry.name,...entry.shape,rig:'local/v1',cue:entry.id};}

export function gestureTitle(gesture){return gallery.find(e=>e.id===gesture?.cue)?.name||'Animación anterior';}
