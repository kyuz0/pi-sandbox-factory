#!/usr/bin/env python3
"""Exercise rendered noVNC input in an explicitly disposable browser sandbox.

Uses regular Playwright because the Browser plugin is unavailable in this test
runtime. Only synthetic local pages and credentials are used; no site access.
"""
import argparse,hashlib,json,selectors,subprocess,time,urllib.request,urllib.error,sys
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pi_sandbox_factory import sandbox
from pi_sandbox_factory.browser_viewer import ensure_viewer
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--state-dir',type=Path,required=True)
parser.add_argument('--name',required=True)
parser.add_argument('--artifacts',type=Path,required=True)
args=parser.parse_args()
ARTIFACTS=args.artifacts;ARTIFACTS.mkdir(parents=True,exist_ok=False)
config=json.loads((args.state_dir/args.name/'config.json').read_text())
ENGINE=config['engine'];CONTAINER=sandbox.names(config)[0]
cid=sandbox.inspect(config,CONTAINER)['Id'];ensure_viewer(ENGINE,cid)
worker=subprocess.Popen([ENGINE,'exec','-i',CONTAINER,'node','--input-type=module','-e',
 Path(__file__).with_name('browser_interaction_fixture.mjs').read_text()],
 stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=(ARTIFACTS/'worker.log').open('w'),text=True)
checks={'status':'running','container':cid,'driverSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
 'fixtureSha256':hashlib.sha256(Path(__file__).with_name('browser_interaction_fixture.mjs').read_bytes()).hexdigest()}
(ARTIFACTS/'run.json').write_text(json.dumps(checks,indent=2)+'\n')
http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
 with selectors.DefaultSelector() as selector:
  selector.register(worker.stdout,selectors.EVENT_READ)
  assert selector.select(180),'Browser fixture did not become ready'
 ready=json.loads(worker.stdout.readline());urls=[x['url'] for x in ready['browsers']]
 for i,url in enumerate(urls):
  html=http.open(url,timeout=30).read().decode();assert f'VIEWER_{i}' in html and f'VIEWER_{1-i}' not in html
 wrong=urls[0].replace(urls[0].split('/')[4],urls[1].split('/')[4])
 try:http.open(wrong,timeout=10);raise AssertionError('cross-session token accepted')
 except urllib.error.HTTPError as error:assert error.code==403
 def remote(expression,index=0,kind='main'):
  session=urls[index].split('/')[4]
  script="""import {chromium} from '/opt/betterwright/node_modules/playwright-core/index.mjs';import{readFile}from'node:fs/promises';const [port,path]=(await readFile('/home/node/.cache/pi-browser/SESSION/DevToolsActivePort','utf8')).trim().split('\\n');const browser=await chromium.connectOverCDP('ws://127.0.0.1:'+port+path);const pages=browser.contexts()[0].pages();let page;for(const candidate of pages)if(await candidate.title()===TITLE)page=candidate;if(!page)throw Error('Missing fixture page');console.log(JSON.stringify(await page.evaluate(EXPRESSION)));process.exit();""".replace('SESSION',session).replace('TITLE',json.dumps('Popup fixture' if kind=='popup' else 'Tab fixture' if kind=='tab' else 'VIEWER_'+str(index))).replace('EXPRESSION',expression)
  return json.loads(subprocess.check_output([ENGINE,'exec',CONTAINER,'node','--input-type=module','-e',script],text=True))
 def eventually(expr,value,index=0,kind='main',seconds=12):
  end=time.monotonic()+seconds
  while time.monotonic()<end:
   found=remote(expr,index,kind)
   if found==value:return
   time.sleep(.1)
  raise AssertionError((expr,found,value))
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=['--no-proxy-server']);context=browser.new_context(viewport={'width':1440,'height':1000});page=context.new_page();errors=[];connections=[]
  page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda message:errors.append(message.text) if message.type=='error' else None);page.on('websocket',lambda w:connections.append(w.url))
  start=time.monotonic();page.goto(urls[0]);assert page.title()=='Browser · VIEWER_0';page.wait_for_function("()=>document.querySelector('#screen').dataset.connected==='true'")
  canvas=page.locator('canvas')
  def geometry(selector,kind='main'):
   point="r.width/2"
   expression='()=>{const r=document.querySelector('+json.dumps(selector)+').getBoundingClientRect();return {x:screenX+(outerWidth-innerWidth)/2+r.x+'+point+',y:screenY+(outerHeight-innerHeight)+r.y+r.height/2}}'
   return remote(expression,kind=kind)
  def click(selector,kind='main'):
   b=geometry(selector,kind);c=canvas.bounding_box();size=canvas.evaluate('(c)=>({w:c.width,h:c.height})');page.mouse.click(c['x']+b['x']*c['width']/size['w'],c['y']+b['y']*c['height']/size['h'])
  eventually('()=>screen.width',1440);eventually('()=>screen.height',page.locator('#screen').evaluate('(e)=>e.clientHeight'))
  b=geometry('#block');page.wait_for_function("([x,y])=>{const c=document.querySelector('canvas'),p=c.getContext('2d').getImageData(x,y,1,1).data;return Math.abs(p[0])<12&&Math.abs(p[1]-136)<12&&Math.abs(p[2]-102)<12}",arg=[b['x'],b['y']])
  checks['firstVerifiedFrameSeconds']=time.monotonic()-start
  print('first verified frame seconds',checks['firstVerifiedFrameSeconds'],flush=True)
  click('#text');page.keyboard.press('Control+a');page.keyboard.press('Backspace');page.keyboard.type('Viewer test 123');eventually("()=>document.querySelector('#text').value",'Viewer test 123')
  click('#next');eventually("()=>document.querySelector('#result').textContent",'Next worked')
  page.set_viewport_size({'width':1200,'height':850});eventually('()=>screen.width',1200);eventually('()=>screen.height',page.locator('#screen').evaluate('(e)=>e.clientHeight'))
  print('PASS native input and resize',flush=True)
  click('#text');page.keyboard.press('Control+a');page.keyboard.press('Backspace')
  page.get_by_role('button',name='Paste text',exact=True).click();page.get_by_label('Clipboard text').fill('Clipboard round trip');page.get_by_role('button',name='Paste',exact=True).click();eventually("()=>document.querySelector('#text').value",'Clipboard round trip')
  page.keyboard.press('Control+a');page.keyboard.press('Control+c');page.get_by_role('button',name='Copy text',exact=True).wait_for();page.wait_for_function("()=>!document.querySelector('#copy').disabled")
  print('PASS explicit clipboard transfer',flush=True)
  page.get_by_role('button',name='Paste text',exact=True).click();page.get_by_label('Clipboard text').fill('x'*(256*1024+1));page.get_by_role('button',name='Paste',exact=True).click()
  assert 'too large' in page.get_by_role('heading').inner_text();assert len(connections)==1
  page.get_by_role('button',name='Close',exact=True).click()
  page.get_by_label('Observe',exact=True).check();assert page.get_by_role('button',name='Paste text').is_disabled();assert page.get_by_role('button',name='Copy text').is_disabled();click('#text');page.keyboard.type('SHOULD_NOT_TYPE');eventually("()=>document.querySelector('#text').value",'Clipboard round trip');page.get_by_label('Observe',exact=True).uncheck()
  click('#popup');eventually("()=>document.title",'Popup fixture',kind='popup');click('#username','popup');page.keyboard.type('synthetic@example.test');click('#next','popup');eventually("()=>document.querySelector('#result').textContent",'Signed in: synthetic@example.test')
  print('PASS observe and native popup completion',flush=True)
  click('#newtab');eventually('()=>document.title','Tab fixture',kind='tab')
  click('#text','tab');page.keyboard.type('Second tab');eventually("()=>document.querySelector('#text').value",'Second tab',kind='tab')
  c=canvas.bounding_box();size=canvas.evaluate('(c)=>({w:c.width,h:c.height})')
  page.mouse.click(c['x']+130*c['width']/size['w'],c['y']+18*c['height']/size['h']);click('#text');page.keyboard.press('Control+a');page.keyboard.type('First tab');eventually("()=>document.querySelector('#text').value",'First tab')
  page.mouse.click(c['x']+350*c['width']/size['w'],c['y']+18*c['height']/size['h']);click('#text','tab');page.keyboard.type(' again');eventually("()=>document.querySelector('#text').value",'Second tab again',kind='tab');eventually("()=>document.querySelector('#text').value",'First tab')
  print('PASS new tab and native tab switching',flush=True)
  for _ in range(4):
   page.get_by_role('button',name='Reconnect',exact=True).click();page.wait_for_function("()=>document.querySelector('#screen').dataset.connected==='true'")
  page.wait_for_timeout(1200);assert len(connections)==5,connections
  print('PASS reconnect without duplicate connections',flush=True)
  page.screenshot(path=str(ARTIFACTS/'desktop.png'))
  page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(500)
  assert canvas.bounding_box()['width']<=390
  eventually('()=>screen.width',1200)
  page.screenshot(path=str(ARTIFACTS/'small-window.png'));assert not errors,errors
  print('PASS native browser viewer functional checks',flush=True);browser.close()
 
 checks.update(status='passed',consoleErrors=errors,viewports=[[1440,1000],[1200,850],[390,844]])
except BaseException as error:
 checks.update(status='failed',failure=str(error))
 raise
finally:
 worker.stdin.close()
 try:worker.wait(timeout=30)
 except subprocess.TimeoutExpired:
  worker.terminate();worker.wait(timeout=10)
 (ARTIFACTS/'run.json').write_text(json.dumps(checks,indent=2)+'\n')
