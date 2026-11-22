"use strict";
/* Bounded PCM playback for canonical speech. No input, provider or retry. */
window.PcmSpeech=(()=>{
  const players=new Map();let context;
  const available=()=>typeof (window.AudioContext||window.webkitAudioContext)==="function";
  function unlock(){
    if(!available())return;
    const Audio=window.AudioContext||window.webkitAudioContext;
    context ||= new Audio({sampleRate:24000});
    void context.resume().catch(()=>{});
  }
  function open(){
    if(!available()||players.size>=3)throw Error("Audio preparation capacity reached");
    const url="pcm-speech:"+crypto.randomUUID();
    let chunks=[],bytes=0,complete=false,closed=false,paused=true,muted=true,ended=false;
    let position=0,cursor=0,nextTime=0,nodes=[],segments=[],gain,timer,element,captured;
    const dispatch=type=>element?.dispatchEvent(new Event(type));
    function currentTime(){
      if(paused||!context)return position;
      const now=context.currentTime;
      for(const part of segments){
        if(now<part.time)return part.offset;
        if(now<part.time+part.duration)return part.offset+now-part.time;
        position=part.offset+part.duration;
      }
      return position;
    }
    function halt(){
      position=currentTime();paused=true;clearInterval(timer);timer=undefined;
      for(const node of nodes){try{node.stop();node.disconnect();}catch{}}
      nodes=[];segments=[];cursor=Math.round(position*24000)*2;
    }
    function tick(){
      if(paused||closed||!context)return;
      const now=context.currentTime;
      position=currentTime();segments=segments.filter(v=>v.time+v.duration>now);
      nodes=nodes.filter(v=>!v.finished);
      nextTime=Math.max(nextTime,now+.025);
      // Schedule at most half a second ahead, releasing decoded buffers when
      // played. Encoded PCM stays bounded by the same eight MiB transport cap.
      while(cursor<bytes && nextTime<now+.5){
        let offset=0,raw;
        for(const chunk of chunks){if(cursor<offset+chunk.length){raw=chunk.subarray(cursor-offset);break;}offset+=chunk.length;}
        if(!raw)throw Error("PCM playback source unavailable");
        const count=Math.min(raw.length/2,4800),buffer=context.createBuffer(1,count,24000),out=buffer.getChannelData(0);
        const samples=new DataView(raw.buffer,raw.byteOffset,count*2);
        for(let n=0;n<count;n++)out[n]=samples.getInt16(n*2,true)/32768;
        const node=context.createBufferSource();node.buffer=buffer;node.connect(gain);
        const part={time:nextTime,offset:cursor/48000,duration:count/24000};segments.push(part);nodes.push(node);
        node.onended=()=>{node.finished=true;node.disconnect();};node.start(nextTime);
        cursor+=count*2;nextTime+=part.duration;
      }
      dispatch("timeupdate");
      if(complete&&cursor===bytes&&!segments.length){
        position=bytes/48000;halt();ended=true;dispatch("ended");
      }
    }
    const player={url,
      append(raw){
        if(closed||complete||!(raw instanceof Uint8Array)||!raw.length||raw.length%2||bytes+raw.length>8*1024*1024-44)throw Error("PCM audio bound or sequence failed");
        chunks.push(raw);bytes+=raw.length;if(!paused)tick();
      },
      finish(value){
        if(closed||complete||value.audio_bytes!==bytes||value.format?.encoding!=="pcm_s16le"||value.format?.sample_rate_hz!==24000||value.format?.channels!==1)throw Error("PCM completion format mismatch");
        complete=true;dispatch("durationchange");if(!paused)tick();
      },
      async ready(at=0){
        const deadline=performance.now()+12000;
        while(!closed && !complete && bytes/48000-at<.12){
          if(performance.now()>deadline)throw Error("Audio buffering delayed");
          await new Promise(resolve=>setTimeout(resolve,20));
        }
        if(closed)throw Error("Speech stream closed");
      },
      async play(){
        if(closed)throw Error("Speech stream closed");
        const Audio=window.AudioContext||window.webkitAudioContext;
        context ||= new Audio({sampleRate:24000});
        if(!gain){gain=context.createGain();gain.connect(context.destination);}gain.gain.value=muted?0:1;
        let timeout;
        try{await Promise.race([context.resume(),new Promise((_,reject)=>{timeout=setTimeout(()=>reject(new DOMException("Press Play audio to listen","NotAllowedError")),1000);})]);}
        finally{clearTimeout(timeout);}
        if(closed)throw Error("Speech stream closed");
        if(!paused)return;
        ended=false;paused=false;nextTime=context.currentTime+.04;
        timer=setInterval(()=>{try{tick();}catch{halt();dispatch("error");}},25);tick();dispatch("playing");
      },
      pause(){if(paused)return;halt();dispatch("pause");},
      cancel(){
        if(closed)return;halt();closed=true;gain?.disconnect();for(const track of captured?.stream.getTracks()||[])track.stop();captured=undefined;chunks=[];bytes=0;element=undefined;players.delete(url);
        if(context && ![...players.values()].some(v=>!v.paused))void context.suspend().catch(()=>{});
      },
      captureStream(){
        if(!context||!gain)throw Error("PCM output is not playing");
        if(!captured){captured=context.createMediaStreamDestination();gain.connect(captured);}
        return captured.stream.clone();
      },
      attach(target){element=target;},
      get currentTime(){return currentTime();},
      set currentTime(value){
        if(!Number.isFinite(value)||value<0||value>bytes/48000+.001)throw Error("PCM seek unavailable");
        const wasPlaying=!paused;halt();position=Math.min(value,bytes/48000);cursor=Math.round(position*24000)*2;ended=false;
        if(wasPlaying)void player.play().catch(()=>dispatch("error"));
      },
      get paused(){return paused;},get ended(){return ended;},
      get duration(){return complete?bytes/48000:Infinity;},
      get muted(){return muted;},set muted(value){muted=!!value;if(gain)gain.gain.value=muted?0:1;}
    };
    players.set(url,player);return player;
  }
  function mount(base){
    let selected;
    return new Proxy(base,{
      get(target,key){
        if(key==="src"&&selected)return selected.url;
        if(selected && ["currentTime","duration","paused","ended","muted"].includes(key))return selected[key];
        if(key==="captureStream"&&selected)return ()=>selected.captureStream();
        if(key==="play")return ()=>selected?selected.play():target.play();
        if(key==="pause")return ()=>selected?selected.pause():target.pause();
        if(key==="removeAttribute")return name=>{if(name==="src"){selected?.pause();selected?.attach(undefined);selected=undefined;}return target.removeAttribute(name);};
        const value=Reflect.get(target,key,target);return typeof value==="function"?value.bind(target):value;
      },
      set(target,key,value){
        if(key==="src"){
          selected?.pause();selected?.attach(undefined);selected=players.get(value);
          if(selected){target.pause();target.removeAttribute("src");selected.attach(base);return true;}
        }
        if(selected && ["currentTime","muted"].includes(key)){selected[key]=value;return true;}
        return Reflect.set(target,key,value,target);
      }
    });
  }
  function wav(bytes){
    const header=new ArrayBuffer(44),view=new DataView(header);
    const text=(offset,value)=>{for(let n=0;n<value.length;n++)view.setUint8(offset+n,value.charCodeAt(n));};
    text(0,"RIFF");view.setUint32(4,36+bytes.byteLength,true);text(8,"WAVEfmt ");view.setUint32(16,16,true);
    view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,24000,true);view.setUint32(28,48000,true);
    view.setUint16(32,2,true);view.setUint16(34,16,true);text(36,"data");view.setUint32(40,bytes.byteLength,true);
    return new Blob([header,bytes],{type:"audio/wav"});
  }
  return {available,open,mount,wav,unlock};
})();
