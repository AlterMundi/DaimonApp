// Actual Web Audio conversion graph; synthetic oscillator, no mic/provider/account.
// PLAYWRIGHT_MODULE and CHROMIUM_EXECUTABLE may select existing local tools.
const assert=require('node:assert/strict'),http=require('node:http'),fs=require('node:fs');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
  const server=http.createServer((req,res)=>{
    if(req.url==='/'){res.setHeader('Content-Type','text/html');res.end('<script src="/assets/webrtc-native-audio.js"></script>');return;}
    const name=req.url.split('/').pop();
    if(!['webrtc-native-audio.js','voice-output-pcm.js'].includes(name)){res.writeHead(404).end();return;}
    res.setHeader('Content-Type','application/javascript');res.end(fs.readFileSync(name==='webrtc-native-audio.js'&&process.env.QUALIFICATION_AUDIO_SOURCE?process.env.QUALIFICATION_AUDIO_SOURCE:'dashboard/web/'+name));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let browser;
  try{
    browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{}),
      args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
    const page=await browser.newPage();await page.goto('http://127.0.0.1:'+server.address().port);
    const result=await page.evaluate(async()=>{
      const writes=[],failures=[];let closed=0;
      window.NativeSpeechAudio={webrtcPcm:true,pcmMaxSeconds:600,openPcm:()=>({ready:Promise.resolve(),
        append:async(id,end,raw)=>{writes.push({id,end,bytes:raw.length,nonzero:raw.some(v=>v!==0)});},
        flush(){},pause(){},resume(){},close(){closed++;}})};
      const source=new AudioContext({sampleRate:48000}),osc=source.createOscillator(),stream=source.createMediaStreamDestination();
      let out;
      try{
        osc.connect(stream);osc.start();await source.resume();
        out=await WebRtcNativeAudio.open({onUnavailable:message=>failures.push(message)});out.attach(stream.stream);
        await new Promise(resolve=>setTimeout(resolve,800));const before=writes.length;
        out.pause();await new Promise(resolve=>setTimeout(resolve,250));const paused=writes.length;
        out.resume();await new Promise(resolve=>setTimeout(resolve,350));out.close();
        return {before,paused,total:writes.length,nonzero:writes.some(v=>v.nonzero),first:writes[0],closed,failures};
      }finally{out?.close();osc.stop();await source.close();}
    });
    assert(result.before>=2);assert.equal(result.paused,result.before);assert(result.total>result.paused);
    assert(result.nonzero);assert.equal(result.first.bytes,4800);assert.equal(result.first.end,4800);
    assert.equal(result.closed,1);assert.deepEqual(result.failures,[]);
    const reply=await page.evaluate(async()=>{
      const rate=24000,seconds=8,data=new ArrayBuffer(44+rate*seconds*2),view=new DataView(data);
      const text=(offset,value)=>[...value].forEach((c,i)=>view.setUint8(offset+i,c.charCodeAt(0)));
      text(0,'RIFF');view.setUint32(4,data.byteLength-8,true);text(8,'WAVE');text(12,'fmt ');view.setUint32(16,16,true);
      view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,rate,true);view.setUint32(28,rate*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);text(36,'data');view.setUint32(40,data.byteLength-44,true);
      for(let n=0;n<rate*seconds;n++)view.setInt16(44+n*2,Math.sin(n/rate*2*Math.PI*660)*8192,true);
      const url=URL.createObjectURL(new Blob([data],{type:'audio/wav'})),audio=new Audio(url),levels=[];
      document.body.append(audio);const watcher=WebRtcNativeAudio.watchElement(audio,{onActivity:v=>levels.push(v)});
      const wait=async check=>{const until=performance.now()+4000;while(!check()){if(performance.now()>until)throw Error('Reply observation timed out');await new Promise(r=>setTimeout(r,25));}};
      try{
        await audio.play();await wait(()=>levels.some(v=>v>.05));const first=audio.currentTime;
        audio.pause();await wait(()=>levels.at(-1)===0);const pause=audio.currentTime;
        await new Promise(r=>setTimeout(r,200));const stable=Math.abs(audio.currentTime-pause)<.05;
        const count=levels.length;await audio.play();await wait(()=>levels.slice(count).some(v=>v>.05));
        audio.muted=true;await wait(()=>levels.at(-1)===0);const mutedCount=levels.length;
        audio.muted=false;await wait(()=>levels.slice(mutedCount).some(v=>v>.05));
        // Replacing a sound source with silence must clear the earlier jaw level.
        for(let n=44;n<data.byteLength;n++)view.setUint8(n,0);
        const silence=URL.createObjectURL(new Blob([data],{type:'audio/wav'}));audio.src=silence;await audio.play();
        await new Promise(r=>setTimeout(r,350));const silent=levels.at(-1)===0;
        watcher.close();const close=levels.at(-1)===0,stillPlaying=!audio.paused;
        audio.pause();URL.revokeObjectURL(silence);return {first,stable,silent,close,stillPlaying};
      }finally{watcher.close();audio.pause();audio.remove();URL.revokeObjectURL(url);}
    });
    assert(reply.first>0);assert(reply.stable);assert(reply.silent);assert(reply.close);assert(reply.stillPlaying,'Closing observation must not stop the sole HTML audio owner');
    console.log('Actual encoded HTML reply: decoded level, pause/resume/mute, silent source replacement and cosmetic-only close passed; native bridge/phone acceptance separate.');
    console.log('Chromium zero-output worklet:48k source ->24k native PCM, pause/resume and single close passed. Android/device acceptance remains separate.');
  }finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
