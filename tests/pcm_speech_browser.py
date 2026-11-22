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
        result=await page.evaluate('''async()=>{
          const assert=(ok,text)=>{if(!ok)throw Error(text);};
          const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
          const hash=async raw=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(v=>v.toString(16).padStart(2,'0')).join('');
          const raw=new Uint8Array(24000*.4*2),samples=new DataView(raw.buffer);
          for(let n=0;n<raw.length/2;n++)samples.setInt16(n*2,4096,true);
          let writer,cancelled=false;
          const body=new ReadableStream({start(c){writer=c;},cancel(){cancelled=true;}});
          const frame=async()=>writer.enqueue(new TextEncoder().encode(JSON.stringify({type:'audio',sequence:0,data:btoa(String.fromCharCode(...raw)),sha256:await hash(raw)})+'\\n'));
          const response=new Response(body,{headers:{'x-audio-encoding':'pcm_s16le'}});
          const controller=new AbortController(),stream=SpeechStream.open(response,controller.signal);
          const element=document.querySelector('audio'),audio=PcmSpeech.mount(element);
          const started=performance.now();await frame();audio.src=stream.url;
          await stream.ready();audio.muted=false;await audio.play();
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
          assert(audio.ended&&Math.abs(audio.currentTime-.4)<.002,'Wrong completed media position');
          const completion=await stream.done;assert(completion.complete&&completion.blob.type==='audio/wav','Same-audio fallback WAV unavailable');
          const bytes=new Uint8Array(await completion.blob.arrayBuffer());assert(bytes.length===raw.length+44,'PCM fallback changed source length');
          stream.cancel();audio.removeAttribute('src');
          const bounded=[PcmSpeech.open(),PcmSpeech.open(),PcmSpeech.open()];let refused=false;
          try{PcmSpeech.open();}catch{refused=true;}assert(refused,'Unbounded prepared PCM players');for(const item of bounded)item.cancel();
          let closed=false;const waiting=new Response(new ReadableStream({cancel(){closed=true;}}),{headers:{'x-audio-encoding':'pcm_s16le'}});
          const abort=new AbortController(),pending=SpeechStream.open(waiting,abort.signal);abort.abort();await pending.done;
          assert(closed,'Cancel did not close original stream');
          source.disconnect();for(const track of capture.getTracks())track.stop();await observed.close();
          return {first_nonzero_browser_pcm_ms:first,terminal_waited_until_after_playback:true,pause_silence:true,exact_pcm_bytes:raw.length,complete_duration_seconds:.4,cancellation:true,prepared_players_max:3,hardware_hearing:'not_observed'};
        }''')
        print(json.dumps(result,indent=2));await browser.close()
asyncio.run(main())
