"""Real browser PCM output, pause/cancel and finite streaming; synthetic I/O only."""
from pathlib import Path
import asyncio
import json
from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]
async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,
            args=['--no-sandbox','--autoplay-policy=no-user-gesture-required'])
        page=await browser.new_page()
        # Secure localhost origin supplies crypto.subtle without an external site.
        await page.route('http://localhost/**',lambda route:route.fulfill(body='<audio id="audio"></audio>',content_type='text/html'))
        await page.goto('http://localhost/')
        for name in ('pcm-speech.js','speech-stream.js'):
            await page.add_script_tag(content=(ROOT/'dashboard/web'/name).read_text())
        await page.evaluate('(source)=>window.fixturePcmSource=source',(ROOT/'dashboard/web/pcm-speech.js').read_text())
        result=await page.evaluate('''async()=>{
          const assert=(ok,text)=>{if(!ok)throw Error(text);};
          const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
          const hash=async raw=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(v=>v.toString(16).padStart(2,'0')).join('');
          const raw=new Uint8Array(24000*1.25*2),samples=new DataView(raw.buffer);
          for(let n=0;n<raw.length/2;n++)samples.setInt16(n*2,4096,true);
          let writer,cancelled=false;
          const body=new ReadableStream({start(c){writer=c;},cancel(){cancelled=true;}});
          let sequence=0;
          const frame=async part=>writer.enqueue(new TextEncoder().encode(JSON.stringify({
            type:'audio',sequence:sequence++,data:btoa(String.fromCharCode(...part)),sha256:await hash(part)
          })+'\\n'));
          const response=new Response(body,{headers:{'x-audio-encoding':'pcm_s16le'}});
          const controller=new AbortController(),stream=SpeechStream.open(response,controller.signal);
          const element=document.querySelector('audio'),audio=PcmSpeech.mount(element);
          const started=performance.now();await frame(raw.subarray(0,30000));audio.src=stream.url;
          let ready=false;const buffered=stream.ready().then(()=>{ready=true;});
          await wait(80);assert(!ready,'A short partial buffer must not start playback');
          await frame(raw.subarray(30000));await buffered;audio.muted=false;await audio.play();
          const observed=new AudioContext({sampleRate:24000});await observed.resume();
          const capture=audio.captureStream(),source=observed.createMediaStreamSource(capture),analyser=observed.createAnalyser();
          analyser.fftSize=256;source.connect(analyser);const pcm=new Float32Array(256);
          let first;for(let n=0;n<100;n++){analyser.getFloatTimeDomainData(pcm);if(pcm.some(v=>Math.abs(v)>.01)){first=performance.now()-started;break;}await wait(5);}
          assert(first!==undefined,'No nonzero PCM in actual browser output graph');
          assert(!audio.ended && !Number.isFinite(audio.duration),'Playback must precede terminal frame');
          audio.pause();const pausedAt=audio.currentTime;await wait(80);
          assert(audio.paused&&Math.abs(audio.currentTime-pausedAt)<.002,'Paused media position advanced');
          analyser.getFloatTimeDomainData(pcm);assert(pcm.every(v=>Math.abs(v)<.001),'Pause left audible PCM');
          const ended=new Promise(resolve=>element.addEventListener('ended',resolve,{once:true}));
          writer.enqueue(new TextEncoder().encode(JSON.stringify({type:'end',audio_bytes:raw.length,audio_sha256:await hash(raw),format:{encoding:'pcm_s16le',sample_rate_hz:24000,channels:1}})+'\\n'));writer.close();
          await audio.play();await Promise.race([ended,wait(2500).then(()=>{throw Error('PCM did not end');})]);
          assert(audio.ended&&Math.abs(audio.currentTime-1.25)<.002,'Wrong completed media position');
          const completion=await stream.done;assert(completion.complete&&completion.blob.type==='audio/wav','Same-audio fallback WAV unavailable');
          const bytes=new Uint8Array(await completion.blob.arrayBuffer());assert(bytes.length===raw.length+44,'PCM fallback changed source length');
          stream.cancel();audio.removeAttribute('src');
          const bounded=[PcmSpeech.open(),PcmSpeech.open(),PcmSpeech.open()];let refused=false;
          try{PcmSpeech.open();}catch{refused=true;}assert(refused,'Unbounded prepared PCM players');for(const item of bounded)item.cancel();
          let closed=false;const waiting=new Response(new ReadableStream({cancel(){closed=true;}}),{headers:{'x-audio-encoding':'pcm_s16le'}});
          const abort=new AbortController(),pending=SpeechStream.open(waiting,abort.signal);abort.abort();await pending.done;
          assert(closed,'Cancel did not close original stream');
          source.disconnect();for(const track of capture.getTracks())track.stop();await observed.close();
          // Drive the scheduler clock deterministically after verifying the
          // actual output graph. A late but still timely block must stay
          // contiguous; a true underrun must retain its scheduling lead.
          let clock=0;const starts=[],durations=[],scheduled=[];
          class FixtureContext {
            get currentTime(){return clock;}
            destination={};
            async resume(){}
            async suspend(){}
            createGain(){return {gain:{value:1},connect(){},disconnect(){}};}
            createBuffer(_channels,count){return {duration:count/24000,getChannelData:()=>new Float32Array(count)};}
            createBufferSource(){return {connect(){},disconnect(){},stop(){},start(at){starts.push(at);durations.push(this.buffer.duration);}};}
          }
          const NativeContext=window.AudioContext;
          window.AudioContext=FixtureContext;
          const id=setInterval;window.setInterval=fn=>{scheduled.push(fn);return 0;};
          try{
            const script=document.createElement('script');
            script.textContent=window.fixturePcmSource;document.head.append(script);
            const boundary=PcmSpeech.open(),block=new Uint8Array(4800);
            boundary.append(block);await boundary.play();
            clock=.130;boundary.append(block);
            clock=.320;boundary.append(block);
            assert(starts.length===2,'A single late block must not restart a drained stream');
            assert(Math.abs(starts[0]-.040)<.001 && Math.abs(starts[1]-.140)<.001,'A ready successor must not introduce a gap');
            clock=.420;boundary.append(block);
            assert(starts.length===2,'A second short block must not start another brief burst');
            clock=.540;boundary.append(new Uint8Array(48000));
            assert(Math.abs(starts[2]-.565)<.001,'A refilled stream starts with fresh scheduling lead');
            for(let i=3;i<starts.length;i++)assert(Math.abs(starts[i]-starts[i-1]-durations[i-1])<.001,'Refilled audio must be contiguous');
            boundary.cancel();
            starts.length=0;clock=1;
            const tail=PcmSpeech.open();tail.append(block);await tail.play();
            clock=1.300;tail.append(block);
            assert(starts.length===1,'Trailing audio waits for completion or enough data');
            tail.finish({audio_bytes:9600,format:{encoding:'pcm_s16le',sample_rate_hz:24000,channels:1}});
            assert(starts.length===2&&Math.abs(starts[1]-1.325)<.001,'A verified short final tail still plays');
            tail.cancel();
          }finally{window.AudioContext=NativeContext;window.setInterval=id;}
          return {first_nonzero_browser_pcm_ms:first,terminal_waited_until_after_playback:true,pause_silence:true,exact_pcm_bytes:raw.length,complete_duration_seconds:1.25,cancellation:true,contiguous_pcm_boundary:true,rebuffering_and_verified_tail:true,prepared_players_max:3,hardware_hearing:'not_observed'};
        }''')
        print(json.dumps(result,indent=2));await browser.close()
asyncio.run(main())
