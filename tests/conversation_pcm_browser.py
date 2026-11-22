"""Canonical shell/player, real PCM output and ahead preparation; controlled IO."""
import asyncio,base64,hashlib,json,mimetypes,math,re,struct,sys,threading,time
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlsplit,parse_qs
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1];WEB=ROOT/'dashboard/web';sys.path.insert(0,str(ROOT))
from dashboard.speech import speech_part
TEXT=('Primero conservamos las palabras y el orden de esta lectura. Después preparamos la parte siguiente mientras suena la actual. '*10)
SOURCE={'id':'native:1','kind':'integrator_answer','revision':'a'*64,'sequence':1,'text_sha256':hashlib.sha256(TEXT.encode()).hexdigest(),'text_characters':len(TEXT),'preview':TEXT[:80],'label':'Fixture reply','current':True}
parts={};offset=0
while offset<len(TEXT):
    part=speech_part({**SOURCE,'offset':offset,'text':TEXT[offset:],'next_offset':None})
    parts[offset]=part;offset=part['next_offset'] if part['next_offset'] is not None else len(TEXT)
requests=[]
class Server(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        path=urlsplit(self.path).path
        if path=='/':
            body=(WEB/'index.html').read_text();body=re.sub(r'\s*<script src="(?:https://telegram.org[^"\n]*|assets/app.js)" defer></script>','',body)
            body=body.replace('<body>','<body class="conversation-mode standalone-conversation">').replace('<section id="conversation" hidden','<section id="conversation"');data=body.encode();mime='text/html'
        elif path.startswith('/assets/'):
            file=WEB/path.removeprefix('/assets/');data=file.read_bytes();mime=mimetypes.guess_type(file)[0] or 'application/octet-stream'
        else:self.send_error(404);return
        self.send_response(200);self.send_header('Content-Type',mime);self.end_headers();self.wfile.write(data)
    def do_POST(self):
        if self.path!='/api/interaction/audio':self.send_error(404);return
        request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));offset=request['offset'];part=parts[offset]
        assert request['source']==SOURCE['id'] and request['revision']==SOURCE['revision'] and request['stream'] and request['speech_provider']=='openai'
        requests.append({'offset':offset,'received_at':time.monotonic(),'received_epoch_ms':time.time()*1000})
        self.send_response(200)
        headers={'Content-Type':'application/x-ndjson','X-Audio-Encoding':'pcm_s16le','X-Speech-Provider':'openai','X-Presentation-Source':SOURCE['id'],'X-Presentation-Revision':SOURCE['revision'],'X-Presentation-Offset':str(offset),'X-Presentation-End-Offset':str(offset+len(part['text'])),'X-Presentation-Next-Offset':str(part['next_offset']) if part['next_offset'] is not None else '', 'X-Presentation-Text-Sha256':hashlib.sha256(part['text'].encode()).hexdigest()}
        for key,value in headers.items():self.send_header(key,value)
        self.end_headers();time.sleep(.25)
        raw=b''.join(struct.pack('<h',int(5000*math.sin(2*math.pi*440*n/24000))) for n in range(24000))
        for sequence,start in enumerate(range(0,len(raw),12000)):
            block=raw[start:start+12000]
            self.wfile.write((json.dumps({'type':'audio','sequence':sequence,'data':base64.b64encode(block).decode(),'sha256':hashlib.sha256(block).hexdigest()})+'\n').encode());self.wfile.flush();time.sleep(.015)
        self.wfile.write((json.dumps({'type':'end','audio_bytes':len(raw),'audio_sha256':hashlib.sha256(raw).hexdigest(),'format':{'encoding':'pcm_s16le','sample_rate_hz':24000,'channels':1}})+'\n').encode());self.wfile.flush()
async def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),Server);threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        async with async_playwright() as p:
            browser=await p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox','--autoplay-policy=no-user-gesture-required'])
            page=await browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            await page.goto(f'http://127.0.0.1:{server.server_port}/?view=conversation&client=standalone');await page.wait_for_function('!!window.Conversation')
            await page.evaluate('''async ({source,parts,text})=>{
              window.fixtureRoutes=[];const api=async route=>{fixtureRoutes.push(route);
                const url=new URL(route,'http://fixture/');
                if(url.pathname==='/interaction/part'){const at=Number(url.searchParams.get('offset'));return {...source,...parts[at]};}
                if(url.pathname!='/interaction')return {binding:'fixture',csrf:'fixture',items:[],goal_controls:[],more:false};
                return {binding:'fixture',csrf:'fixture',items:[source],newest:{delivery:0,native:1,matrix:0},more:false,can_listen:true,can_speak:false,can_stream_speech:true,openai_can_stream_speech:true,can_openai_conversation:true,voice_services_default:'openai',goal_controls:[]};
              };
              const mount=PcmSpeech.mount;PcmSpeech.mount=base=>window.fixtureAudio=mount(base);
              const ui=Conversation.mount({api,headers:()=>({'X-Dashboard-CSRF':'fixture'}),setCsrf(){},modeChanged(){},standalone:true});ui.identity('fixture');ui.authenticated();document.querySelector('#conversation-open').click();await ui.refresh(true);
              window.pcmEvents=[];window.speechParts=Object.keys(parts).length;
              const audio=document.querySelector('#conversation-audio'),ctx=new AudioContext({sampleRate:24000});await ctx.resume();
              audio.addEventListener('ended',()=>pcmEvents.push({type:'ended',at:performance.now()}));
              audio.addEventListener('playing',()=>{
                if(fixtureAudio.muted)return;
                const stream=fixtureAudio.captureStream(),input=ctx.createMediaStreamSource(stream),analyser=ctx.createAnalyser();analyser.fftSize=256;input.connect(analyser);const data=new Float32Array(256),began=performance.now();
                const timer=setInterval(()=>{analyser.getFloatTimeDomainData(data);if(data.some(v=>Math.abs(v)>.01)){pcmEvents.push({type:'nonzero',at:performance.now()});clearInterval(timer);input.disconnect();for(const track of stream.getTracks())track.stop();}else if(performance.now()-began>3000){clearInterval(timer);throw Error('No actual PCM output');}},5);
              });
            }''',{'source':SOURCE,'parts':{str(k):v for k,v in parts.items()},'text':TEXT})
            await page.locator('button[title="Listen to this reply"]').first.click(timeout=3000)
            await page.wait_for_function("pcmEvents.filter(v=>v.type==='ended').length===speechParts",timeout=15000)
            result=await page.evaluate('({epoch:performance.timeOrigin,events:pcmEvents,state:document.querySelector("#conversation-audio-state").textContent})')
            assert not errors,errors
            starts=[e['at'] for e in result['events'] if e['type']=='nonzero'];ends=[e['at'] for e in result['events'] if e['type']=='ended']
            assert len(starts)==len(parts)==len(requests),(result,requests)
            gaps=[round(starts[n+1]-ends[n],2) for n in range(len(ends)-1)]
            assert all(0<=gap<650 for gap in gaps),gaps
            assert [v['offset'] for v in requests]==list(parts),requests
            # Next HTTP preparation is admitted before preceding audio's end;
            # verify using offsets/events clocks mapped by this process/page.
            assert all(requests[n+1]['received_epoch_ms']<result['epoch']+ends[n] for n in range(len(requests)-1)),requests
            print(json.dumps({'canonical_parts':len(parts),'offsets':[v['offset'] for v in requests],'inter_block_gaps_ms':gaps,'actual_nonzero_PCM_parts':len(starts),'ahead_preparation':True,'hardware_hearing':'not_observed'},indent=2));await browser.close()
    finally:server.shutdown();server.server_close()
asyncio.run(main())
