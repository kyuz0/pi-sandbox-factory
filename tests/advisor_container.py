import sys,json,os,tempfile,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse
parser=argparse.ArgumentParser(description='Disposable advisor check; no accounts or inference')
parser.add_argument('--dev-image', required=True, help='A built VS Code Pi Sandbox development image with Pi/Pendant')
args=parser.parse_args()
from vscode_pi_sandbox import sandbox as core, sandbox_advisors as a
root=Path(tempfile.mkdtemp(prefix='advisor-check-'))
config={'name':root.name,'engine':'podman','uid':os.getuid(),'gid':os.getgid(),'workspace':str(root),'advisors':{'providers':['codex','agy','claude']}}
worker,proxy,socket,home,egress=a.names(config)
try:
 if core.run(['podman','image','inspect',core.image_names(config)[1]],capture=True,check=False,stderr=subprocess.DEVNULL).returncode:
  core.run(['podman','build','-t',core.image_names(config)[1],core.ROOT/'containers/proxy'])
 a.build(config)
 a.up(config,root)
 data=core.inspect(config,worker)
 assert data['HostConfig']['NetworkMode']=='none'
 assert not any(m['Destination']=='/workspace' for m in data['Mounts'])
 result=core.run(['podman','exec',worker,'node','--input-type=module','-e',"import {RemoteAdvisorService} from '/opt/advisor/lib/advisor/remote.mjs'; const c=new RemoteAdvisorService('/run/advisor/advisor.sock');console.log(JSON.stringify(await c.status({sessionId:'test',runIds:[]},{refreshQuota:false})));"],capture=True)
 value=json.loads(result.stdout);assert value['implementedProviders']==['codex','agy','claude']
 assert len(value['providers'])==3
 core.run(['podman','exec',worker,'dbus-send','--session','--print-reply','--dest=org.freedesktop.secrets','/org/freedesktop/secrets','org.freedesktop.DBus.Peer.Ping'],capture=True)
 # This is synthetic state, never a real login.
 core.run(['podman','exec',worker,'sh','-c','printf fixture > /home/node/credential-sentinel'])
 core.run(['podman','exec','-i',worker,'secret-tool','store','--label=Advisor fixture','advisor-test','fixture'],input='synthetic-secret')
 assert core.run(['podman','exec',worker,'secret-tool','lookup','advisor-test','fixture'],capture=True).stdout.strip()=='synthetic-secret'
 # Verify the actual Pendant worker loads the client, without asking a model.
 dev=worker+'-client'
 dev_image=args.dev_image
 core.run(['podman','run','-d','--name',dev,'--network=none','--cap-drop=ALL','--security-opt=no-new-privileges','--security-opt=label=disable','--userns=keep-id:uid=1000,gid=1000',
           '--env','SANDBOX_NETWORK_MODE=unrestricted','--env','PI_ADVISOR_SOCKET=/run/advisor/advisor.sock',
           '-v',f'{socket}:/run/advisor:ro',
           '-v',str(core.ROOT/'containers/dev/bootstrap.py')+':/usr/local/lib/sandbox-bootstrap.py:ro',
           '-v',str(core.ROOT.parent/'tests/check_pendant_worker.cjs')+':/tmp/pendant-advisor-test.cjs:ro',dev_image])
 try:
  import time
  for _ in range(80):
   if core.run(['podman','exec',dev,'test','-f','/tmp/vscode-pi-sandbox-ready'],capture=True,check=False).returncode==0:break
   time.sleep(.25)
  core.run(['podman','exec',dev,'node','/tmp/pendant-advisor-test.cjs','--advisor'])
 finally:core.run(['podman','rm','-f',dev])

 args=['podman','run','--rm','--network=none','--cap-drop=ALL','--security-opt=no-new-privileges','--security-opt=label=disable','--userns=keep-id:uid=1000,gid=1000','--user',f'{os.getuid()}:{os.getgid()}','-v',f'{socket}:/run/advisor:ro','--entrypoint','node',a.image(config),'--input-type=module','-e',"import{access}from'node:fs/promises';import{RemoteAdvisorService}from'/opt/advisor/lib/advisor/remote.mjs';try{await access('/home/node/credential-sentinel');throw Error('credential volume exposed')}catch(e){if(e.code!=='ENOENT')throw e}const c=new RemoteAdvisorService('/run/advisor/advisor.sock');const r=await c.state({sessionId:'peer',runIds:[]});if(r.runs.length)throw Error('unexpected runs');console.log('peer socket connected; credentials absent');"]
 core.run(args)
 core.run(['podman','exec',worker,'node','--input-type=module','-e',"import{sandboxInvocation}from'/opt/advisor/lib/advisor/agy.mjs';import{runProcess}from'/opt/advisor/lib/advisor/process.mjs';const i=await sandboxInvocation({executable:'/usr/local/bin/agy',containerRuntime:true},'/tmp/agy-check',['--version']);try{const r=await runProcess(i.command,i.args,{env:i.env,timeoutMs:30000});if(r.code!==0)throw Error(r.stderr);console.log('isolated Antigravity '+r.stdout)}finally{await i.close()}"],capture=True)
 core.run(['podman','exec',worker,'node','--input-type=module','-e',"import{inspect}from'/opt/advisor/lib/advisor/codex.mjs';console.log(await inspect({executable:'/usr/local/bin/advisor-codex',containerRuntime:true,sharedHome:true,codexHome:'/home/node/.codex'},'/tmp/codex-check'));"],capture=True)
 core.run(['podman','exec',worker,'node','--input-type=module','-e',"import{inspect}from'/opt/advisor/lib/advisor/claude.mjs';console.log(await inspect({executable:'/usr/local/bin/advisor-claude',containerRuntime:true,sharedHome:true,claudeHome:'/home/node/.claude'},'/tmp/claude-check'));"],capture=True)
 # A blocked destination must fail at the companion's gateway.
 denied=core.run(['podman','exec',worker,'curl','--silent','--show-error','--max-time','15','https://unlisted.invalid/'],capture=True,check=False,stderr=subprocess.PIPE)
 assert denied.returncode != 0 and '403' in denied.stderr
 # Simulate atomic credential renewal in an isolated, synthetic Codex home.
 renewal="""import{mkdir,writeFile,readFile}from'node:fs/promises';import{sandboxInvocation}from'/opt/advisor/lib/advisor/codex.mjs';import{runProcess}from'/opt/advisor/lib/advisor/process.mjs';const home='/tmp/refresh-fixture';await mkdir(home,{recursive:true});await writeFile(home+'/auth.json','synthetic-old');const inv=await sandboxInvocation({executable:'/usr/bin/python3',containerRuntime:true,sharedHome:true,codexHome:home,billingMode:'subscription'},'/tmp/ignored',['-c',"from pathlib import Path;p=Path('/state/auth.new');p.write_text('synthetic-refreshed');p.replace('/state/auth.json')"]);const r=await runProcess(inv.command,inv.args,{env:inv.env,timeoutMs:30000});if(r.code!==0)throw Error(r.stderr);if(await readFile(home+'/auth.json','utf8')!=='synthetic-refreshed')throw Error('renewal failed');console.log('PASS atomic credential renewal in private companion home');"""
 core.run(['podman','exec',worker,'node','--input-type=module','-e',renewal])
 a.down(config);a.up(config,root)
 assert core.run(['podman','exec',worker,'cat','/home/node/credential-sentinel'],capture=True).stdout=='fixture'
 assert core.run(['podman','exec',worker,'secret-tool','lookup','advisor-test','fixture'],capture=True).stdout.strip()=='synthetic-secret'
 print('PASS: companion and proxy; all three isolated CLIs; Pendant tools and remote usage; owner-only socket; credential volume separation; keyring and private state survive restart')
finally:
 for name in (worker,proxy):
  if core.inspect(config,name):
   logs=core.run(['podman','logs','--tail','12',name],capture=True,check=False,stderr=subprocess.STDOUT)
   print(name,logs.stdout)
 a.down(config,remove=True);a.delete_volumes(config)
 import shutil;shutil.rmtree(root)
