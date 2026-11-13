#!/usr/bin/env python3
"""Check private native displays and cleanup in an explicitly disposable sandbox."""
import argparse,json,subprocess,sys,time,selectors
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pi_sandbox_factory import sandbox
from pi_sandbox_factory.browser_viewer import ensure_viewer
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--state-dir',type=Path,required=True);p.add_argument('--name',required=True)
a=p.parse_args();config=json.loads((a.state_dir/a.name/'config.json').read_text())
engine=config['engine'];container=sandbox.names(config)[0];ensure_viewer(engine,sandbox.inspect(config,container)['Id'])
def inside(*command,check=True):
 return subprocess.run([engine,'exec',container,*command],check=check,text=True,capture_output=True)
def processes():
 rows={}
 for line in inside('ps','-eo','pid=,ppid=,stat=,comm=').stdout.splitlines():
  pid,parent,state,command=line.split(None,3);rows[int(pid)]=(int(parent),state,command)
 return rows
def descendants(owner):
 rows=processes();ids={owner}
 while True:
  found=ids|{pid for pid,(parent,_,_) in rows.items() if parent in ids}
  if found==ids:return {pid:rows[pid] for pid in ids if pid in rows}
  ids=found
def wait(check,message):
 end=time.monotonic()+15
 while time.monotonic()<end:
  if check():return
  time.sleep(.1)
 raise AssertionError(message)
for abrupt in (False,True):
 worker=subprocess.Popen([engine,'exec','-i',container,'node','--input-type=module','-e',
  Path(__file__).with_name('browser_interaction_fixture.mjs').read_text()],
  stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 try:
  with selectors.DefaultSelector() as selector:
   selector.register(worker.stdout,selectors.EVENT_READ)
   assert selector.select(180),'Browser fixture did not become ready'
  line=worker.stdout.readline();assert line,worker.stderr.read() if worker.poll() is not None else 'Fixture stdout closed'
  ready=json.loads(line);owner=ready['ownerPid'];ids=[row['url'].split('/')[4] for row in ready['browsers']]
  rows=descendants(owner);displays=[pid for pid,(_,_,command) in rows.items() if command=='Xvnc']
  assert len(displays)==2,rows
  inspect="""const fs=require('fs');const rows=IDS.map(id=>{const p='/home/node/.cache/pi-browser/'+id;const pref=JSON.parse(fs.readFileSync(p+'/Default/Preferences'));return {id,profile:fs.statSync(p).mode&511,authority:fs.statSync(p+'/Xauthority').mode&511,rfb:fs.statSync(p+'/vnc.sock').mode&511,bridge:fs.statSync(p+'/desktop.sock').mode&511,pref,display:fs.readFileSync(p+'/Xauthority').toString('hex')}});console.log(JSON.stringify(rows));""".replace('IDS',json.dumps(ids))
  details=json.loads(inside('node','-e',inspect).stdout)
  assert details[0]['display']!=details[1]['display'],'Displays share an authority cookie'
  for row in details:
   assert [row[x] for x in ('profile','authority','rfb','bridge')]==[448,384,384,384],row
   assert row['pref']['credentials_enable_service'] is False
   assert row['pref']['profile']['password_manager_enabled'] is False
  if not abrupt:
   def recover(kind):
    rows=descendants(owner)
    candidates=[pid for pid,(parent,_,command) in rows.items() if
     (parent==owner and command not in ('Xvnc','openbox','vncconfig','node') if kind=='Chromium' else command=='Xvnc')]
    target=next(pid for pid in candidates if ids[0] in inside('ps','-p',str(pid),'-o','args=').stdout)
    inside('kill','-KILL',str(target))
    # A queued tool call must recover in the existing owner without a fresh Pi session.
    worker.stdin.write(json.dumps({'code':"await page.setContent('<title>Recovered</title>');return await page.title()"})+'\n');worker.stdin.flush()
    with selectors.DefaultSelector() as selector:
     selector.register(worker.stdout,selectors.EVENT_READ)
     assert selector.select(90),'Browser recovery did not finish'
    response=json.loads(worker.stdout.readline());assert response.get('ok') and response.get('result')=='Recovered',response
    print('PASS recovery after '+kind+' death',flush=True)
   recover('Chromium');recover('Xvnc')
   rows=descendants(owner)
  # X11 and VNC must not expose TCP ports, even on container loopback.
  listeners=inside('ss','-lnt').stdout
  assert not __import__('re').search(r':(?:59|60)\d{2}\s',listeners),listeners
  if abrupt:inside('kill','-KILL',str(owner))
  else:worker.stdin.close()
  worker.wait(timeout=30)
  wait(lambda:not(set(rows)&set(processes())),'Browser descendants survived owner exit or were not reaped by tini')
  if not abrupt:
   for session in ids:assert inside('test','-e','/home/node/.cache/pi-browser/'+session,check=False).returncode!=0
  print('PASS', 'abrupt owner death and tini reaping' if abrupt else 'normal close and private profile removal',flush=True)
  print('PASS distinct private displays, authority cookies, sockets, password preferences and no display TCP listeners',flush=True)
 finally:
  if not worker.stdin.closed:worker.stdin.close()
  if worker.poll() is None:
   worker.terminate();worker.wait(timeout=15)
