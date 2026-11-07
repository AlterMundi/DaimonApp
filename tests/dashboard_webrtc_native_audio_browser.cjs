// Actual Web Audio conversion graph; synthetic oscillator, no mic/provider/account.
// PLAYWRIGHT_MODULE and CHROMIUM_EXECUTABLE may select existing local tools.
const assert=require('node:assert/strict'),http=require('node:http'),fs=require('node:fs');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
  const server=http.createServer((req,res)=>{
    if(req.url==='/'){res.setHeader('Content-Type','text/html');res.end('<script src="/assets/webrtc-native-audio.js"></script>');return;}
    const name=req.url.split('/').pop();
    if(!['webrtc-native-audio.js','voice-output-pcm.js'].includes(name)){res.writeHead(404).end();return;}
    res.setHeader('Content-Type','application/javascript');res.end(fs.readFileSync('dashboard/web/'+name));
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
    console.log('Chromium zero-output worklet:48k source ->24k native PCM, pause/resume and single close passed. Android/device acceptance remains separate.');
  }finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
