"""Actual receiving shell/CSS/adapter, synthetic UI state; no controllers/providers."""
import argparse,json,re,threading,mimetypes,time
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from playwright.sync_api import sync_playwright
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--web-root',type=Path,required=True)
parser.add_argument('--homemaker',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--chromium',required=True)
args=parser.parse_args()
WEB=args.web_root.resolve()
templates=json.loads((args.homemaker/'public/content/templates.json').read_text())
html=(WEB/'index.html').read_text()
html=re.sub(r'<script\b[^>]*>.*?</script>','',html,flags=re.S)
html=html.replace('</head>','<link rel="stylesheet" href="/provider.css"><script src="/assets/interface-appearance.js" defer></script></head>')
html=html.replace('<html lang="en">','<html lang="en" data-style-policy="inherit">')
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  if self.path=='/':data=html.encode();mime='text/html'
  elif self.path=='/provider.css':
   time.sleep(.15)
   data=b':root{--dm-background:#ffffff;--dm-surface:#ffffff;--dm-text:#111111;--dm-accent:#176241;color-scheme:light}';mime='text/css'
  elif self.path.startswith('/assets/'):
   p=(WEB/self.path.removeprefix('/assets/')).resolve()
   if not p.is_relative_to(WEB) or not p.is_file():self.send_error(404);return
   data=p.read_bytes();mime=mimetypes.guess_type(p)[0] or 'application/octet-stream'
  else:self.send_error(404);return
  self.send_response(200);self.send_header('Content-Type',mime);self.end_headers();self.wfile.write(data)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
results=[]
try:
 with sync_playwright() as w:
  browser=w.chromium.launch(executable_path=args.chromium,args=['--no-sandbox'])
  try:
   for width in (1440,375,320):
    page=browser.new_page(viewport={'width':width,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.add_init_script('''window.roleReadyAt=null;const nativeSet=CSSStyleDeclaration.prototype.setProperty;CSSStyleDeclaration.prototype.setProperty=function(k,...args){const r=nativeSet.call(this,k,...args);if(k==='--dm-ui-text')window.roleReadyAt=performance.now();return r;};window.paintSamples=[];new PerformanceObserver(list=>{for(const e of list.getEntries()){const s=getComputedStyle(document.documentElement);paintSamples.push({name:e.name,paintAt:e.startTime,rolesAt:window.roleReadyAt,text:s.getPropertyValue('--dm-ui-text').trim(),bg:s.getPropertyValue('--dm-background').trim()});}}).observe({type:'paint',buffered:true});''')
    page.goto(f'http://127.0.0.1:{server.server_port}/');page.wait_for_timeout(80)
    samples=page.evaluate('paintSamples');assert samples and all(x['rolesAt'] is not None and x['rolesAt']<=x['paintAt'] and x['text']=='#111111' and x['bg']=='#ffffff' for x in samples),samples
    page.evaluate('''()=>{document.body.classList.add('standalone-conversation','conversation-mode');document.querySelector('#conversation').hidden=false;const t=document.querySelector('#conversation-message');t.disabled=false;t.value='A draft kept across styles 🤍';t.focus();t.setSelectionRange(2,8);document.querySelector('#conversation-compose').dataset.fixture='retained';}''')
    baseline=page.evaluate("document.body.innerHTML")
    for t in templates:
     page.evaluate('''t=>{for(const [k,v] of Object.entries({background:t.surface,surface:t.panelSurface||t.surface,text:t.foreground,accent:t.accent}))document.documentElement.style.setProperty('--dm-'+k,v);window.dispatchEvent(new Event('home-style:resolved'));}''',t)
     assert page.evaluate('document.body.innerHTML')==baseline,t['id']
     state=page.evaluate("()=>{const t=document.querySelector('#conversation-message');return [t.value,t.selectionStart,t.selectionEnd,document.activeElement.id,getComputedStyle(t).color]}")
     assert state[:4]==['A draft kept across styles 🤍',2,8,'conversation-message'],state
     assert state[4]!='rgba(0, 0, 0, 0)'
    before=page.evaluate("getComputedStyle(document.body).backgroundColor")
    page.evaluate("document.documentElement.style.setProperty('--dm-background','invalid');window.dispatchEvent(new Event('home-style:resolved'))")
    assert page.evaluate("getComputedStyle(document.body).backgroundColor")==before
    page.evaluate("document.documentElement.dataset.stylePolicy='authored';window.dispatchEvent(new Event('home-style:resolved'))")
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--dm-ui-text').trim()")==''
    assert not errors,errors
    results.append({'width':width,'palettes':len(templates),'first_paint_samples':samples,'draft_focus_selection_dom':'preserved','authored_overrides':'released'})
    page.close()
  finally:browser.close()
finally:server.shutdown();server.server_close()
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps({'scope':'Actual receiving candidate shell/materials with explicitly synthetic state. Controller journeys separately tested; no real authenticated/device acceptance.', 'cases':results},indent=2)+'\n')
print(json.dumps({'widths':len(results),'palette_transitions':sum(x['palettes'] for x in results),'result':'passed'}))
