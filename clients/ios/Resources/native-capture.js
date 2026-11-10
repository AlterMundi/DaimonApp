"use strict";
// iOS host session ownership around the existing shared getUserMedia wrapper.
// The native reply is not microphone permission or a recording receipt.
(()=>{
  const devices=navigator.mediaDevices, original=devices?.getUserMedia?.bind(devices);
  const handler=window.webkit?.messageHandlers?.capture;
  if(!original||!handler)return;
  let current,epoch=0;
  const send=(command,owner,fields={})=>handler.postMessage(JSON.stringify({command,owner,document_id:window.__DaimonAudioDocument,...fields}));
  const release=state=>{
    if(state.closed)return;state.closed=true;
    if(current===state)current=undefined;
    // A lost end receipt stays unknown; never repeat the session write.
    try{Promise.resolve(send("capture_end",state.owner)).catch(()=>{});}catch{}
  };
  const stop=()=>{
    epoch++;
    const state=current;
    if(!state)return;
    for(const track of state.tracks){try{track.stop();}catch{}}
    release(state);
  };
  const uuid=value=>typeof value==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value);
  window.__DaimonCaptureConnection=async(stream,{visit,predecessor}={})=>{
    const state=current;
    if(!state||state.closed||state.stream!==stream||!state.tracks.length||state.tracks.some(track=>track.readyState!=='live')
        ||!uuid(visit)||(predecessor!==undefined&&!uuid(predecessor))||state.connectionBusy||state.connectionUnknown)
      throw new DOMException('Microphone connection unavailable','InvalidStateError');
    if(state.connection===visit&&state.predecessor===predecessor)return;
    if(predecessor!==state.connection)throw new DOMException('Microphone connection changed','InvalidStateError');
    state.connectionBusy=true;
    try{
      const result=await send('capture_connection',state.owner,{visit,...(predecessor===undefined?{}:{predecessor})});
      if(result!==true)throw new DOMException('Microphone connection not confirmed','AbortError');
      if(state.closed||state!==current||state.epoch!==epoch)throw new DOMException('Microphone connection retired','AbortError');
      state.connection=visit;state.predecessor=predecessor;
    }catch(error){state.connectionUnknown=true;throw error;}
    finally{state.connectionBusy=false;}
  };
  window.__DaimonCaptureStop=stop;
  window.addEventListener("pagehide",stop);
  window.addEventListener("nativecapturebackground",stop);
  devices.getUserMedia=async constraints=>{
    if(!constraints?.audio||constraints.video)throw new DOMException("Only microphone capture is available","NotSupportedError");
    if(current)throw new DOMException("A microphone request is already active","InvalidStateError");
    const state={owner:crypto.randomUUID(),epoch,tracks:[],closed:false};current=state;
    try{
      await send("capture_begin",state.owner);
      if(state.closed||state.epoch!==epoch)throw new DOMException("Microphone start interrupted","AbortError");
      const stream=await original(constraints),tracks=stream.getTracks();
      if(state.closed||state.epoch!==epoch){for(const track of tracks){try{track.stop();}catch{}}throw new DOMException("Microphone permission arrived after interruption","AbortError");}
      state.tracks=tracks;state.stream=stream;
      const finished=()=>{if(tracks.every(track=>track.readyState==="ended"))release(state);};
      for(const track of tracks){
        const originalStop=track.stop.bind(track);
        Object.defineProperty(track,"stop",{configurable:true,value:()=>{originalStop();finished();}});
        track.addEventListener("ended",finished,{once:true});
      }
      finished();return stream;
    }catch(error){
      for(const track of state.tracks){try{track.stop();}catch{}}
      release(state);throw error;
    }
  };
})();
