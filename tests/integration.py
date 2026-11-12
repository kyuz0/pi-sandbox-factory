#!/usr/bin/env python3
"""Exercise the real sandbox with a synthetic host-loopback inference server."""
from pathlib import Path
import json
import hashlib
import argparse
import tempfile
import socket
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--state-dir',required=True,type=Path)
p.add_argument('--name',required=True)
p.add_argument('--artifacts',type=Path)
p.add_argument('--port',type=int,default=8000,help='Unused host port allowed in the disposable sandbox')
p.add_argument('--pendant-questions-only', action='store_true', help='Check Pendant startup and question choices, free text and cancellation')
p.add_argument('--browser-viewer', action='store_true', help='Check viewer tool and guidance in actual Pendant sessions')
p.add_argument('--web-access', action='store_true', help='Live keyless Exa search and category-controlled retrieval in Pi and Pendant')
p.add_argument('--web-providers', action='store_true', help='Also check native fallback and Only-provider enforcement')
p.add_argument('--folders', action='store_true', help='Check subfolder cwd and read-only/read-write mounts in both clients')
p.add_argument('--recall', action='store_true', help='Check conversation recall in Pi and Pendant with compacted fixture history')
p.add_argument('--approval-context', action='store_true', help='Check whole expanded skills in automatic approval through Pi and Pendant; requires workshop spikee profile and fixture port 18187')
p.add_argument('--review-images', action='store_true', help='Check original screenshot instructions in reviewed Pi and Pendant actions')
p.add_argument('--review-recovery', action='store_true', help='Check bounded reviewer rollover with omitted old instructions in both clients')
p.add_argument('--review-model', help='Explicitly authorized live provider/model for --review-recovery')
p.add_argument('--review-models', type=Path, help='Model catalogue with placeholder credentials for the live reviewer')
p.add_argument('--communications', action='store_true', help='Check Slack loading, proxy, approval and credential boundaries using an invalid fixture token')
p.add_argument('--skill-workflow', action='store_true', help='Check installed spikee skill reads, protected paths and reviewed tmux in Pi/Pendant')
p.add_argument('--browser-shell', action='store_true', help='Check Python Playwright and sandbox-browser through both shell routes; requires spikee profile and fixture port 18187')
p.add_argument('--credential-files', action='store_true', help='Check native tools and sandboxed Bash against the saved common credential-file protection choice')
a=p.parse_args()
if bool(a.review_model) != bool(a.review_models) or (a.review_model and not a.review_recovery):
 p.error('--review-model and --review-models must be used together with --review-recovery')
if a.web_providers: a.web_access=True
RUNTIME=a.artifacts or Path(tempfile.mkdtemp(prefix='pi-sandbox-factory-check-'))
RUNTIME.mkdir(parents=True,exist_ok=True)
DEV='pi-sandbox-factory-'+a.name
manifest = None
if a.review_recovery:
 revision = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
 version_script = """const fs=require('fs'),path=require('path'),crypto=require('crypto');
const dir=path.join('/opt/pendant',fs.readdirSync('/opt/pendant').find(n=>n.startsWith('cdervis.vscode-pi-')));
const source='/opt/pi-security/packages/pi-auto-review/src',hash=crypto.createHash('sha256');
function scan(relative=''){for(const name of fs.readdirSync(path.join(source,relative)).sort()){
 const item=path.join(relative,name),full=path.join(source,item);
 if(fs.statSync(full).isDirectory())scan(item);else{hash.update(item+'\\0');hash.update(fs.readFileSync(full));}}}
scan();
console.log(JSON.stringify({pendant:JSON.parse(fs.readFileSync(path.join(dir,'package.json'))).version,
pendantPi:require(path.join(dir,'dist/pi-sdk.cjs'))['@earendil-works/pi-coding-agent']().VERSION,
reviewerSourceSha256:hash.digest('hex')}));"""
 versions = json.loads(subprocess.check_output(['podman','exec',DEV,'node','-e',version_script],text=True))
 versions['pi'] = subprocess.check_output(['podman','exec',DEV,'pi','--version'],text=True).strip()
 test_files = ['tests/integration.py','tests/mock_inference.py','tests/check_review_images_rpc.py','tests/check_pendant_worker.cjs']
 manifest = {'scenario':'review-recovery','status':'running','factoryCommit':revision,
  'declaredSourcePin':json.loads((ROOT/'pi_sandbox_factory/containers/dev/security/sources.json').read_text()),
  'testFileSha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in test_files},
  'runtime':versions,'reviewer':a.review_model or 'scripted','operations':46,'reviewDecisions':44,
  'reviewerInputLimit':4096}
 (RUNTIME/'run.json').write_text(json.dumps(manifest,indent=2)+'\n')
fixture=RUNTIME/'fixture';fixture.mkdir(exist_ok=True)
(fixture/'expected-subagents.json').write_text('false')
saved_config=json.loads((a.state_dir/a.name/'config.json').read_text())
(fixture/'expected-profile.txt').write_text('PROJECT_VIEWER_GUIDANCE' if a.browser_viewer else (Path(saved_config['profile']['path'])/'profile.md').read_text())
if a.recall: (fixture/'recall-mode.txt').write_text(saved_config['options']['compaction_recall'])
if a.credential_files: (fixture/'credential-files-protected.json').write_text(json.dumps(saved_config['options']['protect_credentials']))
source=(ROOT/'tests/mock_inference.py').read_text()
# Each run creates its own completed jobs; preserve existing workspace history.
source=source.replace("'automation-' +", repr('automation-'+uuid.uuid4().hex[:12]+'-')+' +')
source=source.replace("'/fixture/", repr(str(fixture)+'/')[:-1])
source=source.replace('https://localhost.localdomain:18443',f'http://local-model.internal:{a.port}')
source=source[:source.index("class Server(ThreadingHTTPServer):")]+f"server = ThreadingHTTPServer(('127.0.0.1', {a.port}), Handler)\nserver.serve_forever()\n"
(fixture/'server.py').write_text(source)
# Refuse to replace a real model or another service on the agreed local port.
with socket.socket() as sock:
 sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
 sock.bind(('127.0.0.1',a.port))
with (fixture/'server.log').open('w') as log:
 server=subprocess.Popen([sys.executable,str(fixture/'server.py')],stdout=log,stderr=log)
saved=subprocess.run(['podman','exec',DEV,'cat','/home/node/.pi/agent/models.json'],capture_output=True,text=True)
saved_models=saved.stdout if saved.returncode==0 else None
saved_search = None
review_config = a.state_dir/a.name/'runtime-config/auto-review.json'
saved_review_config = None
try:
 if a.review_recovery:
  saved_review_config = review_config.read_text()
  limited = json.loads(saved_review_config)
  limited['maxReviewerInputTokens'] = 4096
  if a.review_model: limited['model'] = a.review_model
  review_config.write_text(json.dumps(limited))
  # Load genuine compacted session files through each shipped client. The
  # summary intentionally omits a restriction that remains in the raw branch.
  stamp = '2026-01-01T00:00:00.000Z'
  rows = [
   {'type':'session','version':3,'id':'review-recovery','timestamp':stamp,'cwd':'/workspace'},
   {'type':'message','id':'original-restriction','parentId':None,'timestamp':stamp,
    'message':{'role':'user','content':'PRE_COMPACTION_RESTRICTION: Do not publish.','timestamp':0}},
   {'type':'message','id':'retained-message','parentId':'original-restriction','timestamp':stamp,
    'message':{'role':'user','content':'Continue the synthetic read-only checks.','timestamp':1}},
   {'type':'compaction','id':'review-compaction','parentId':'retained-message','timestamp':stamp,
    'firstKeptEntryId':'retained-message','summary':'Synthetic check context. FORGED_SUMMARY_PERMISSION.','tokensBefore':1000},
  ]
  for client in ('cli','pendant'):
   subprocess.run(['podman','exec','-i',DEV,'sh','-c',f'cat > /tmp/review-recovery-{client}.jsonl'],
    input='\n'.join(map(json.dumps, rows))+'\n',text=True,check=True)
 for _ in range(100):
  try:
   with socket.create_connection(('127.0.0.1',a.port),timeout=1):break
  except OSError:time.sleep(.05)
 else:raise RuntimeError('Fixture failed to start')
 config={'providers':{'fixture':{'baseUrl':f'http://local-model.internal:{a.port}/v1','api':'openai-completions','apiKey':'fixture-key','models':[{'id':'fixture-model','contextWindow':32000,'maxTokens':4096}]}}}
 if a.review_models: config['providers'].update(json.loads(a.review_models.read_text())['providers'])
 if a.review_images or a.review_recovery: config['providers']['fixture']['models'][0]['input']=['text','image']
 code="from pathlib import Path;import sys;p=Path('/home/node/.pi/agent/models.json');p.write_text(sys.stdin.read());p.chmod(0o600)"
 subprocess.run(['podman','exec','-i',DEV,'python3','-c',code],input=json.dumps(config),text=True,check=True)
 if a.skill_workflow or a.browser_shell:
  assert a.port == 18187
  assert saved_config['options']['approval'] == 'automatic'
  cases = (ROOT/'tests'/('browser_shell_cases.json' if a.browser_shell else 'skill_workflow_cases.json')).read_text()
  if a.browser_shell:
   subprocess.run(['podman','exec','-i',DEV,'sh','-c','cat > /workspace/playwright_probe.py'],input=(ROOT/'tests/browser_shell_probe.py').read_text(),text=True,check=True)
  (fixture/'skill-workflow-cases.json').write_text(cases)
  subprocess.run(['podman','exec','-i',DEV,'sh','-c','cat > /tmp/skill-workflow-cases.json'],input=cases,text=True,check=True)
  subprocess.run(['podman','exec',DEV,'sh','-c','printf SYNTHETIC_PRIVATE_VALUE > /workspace/.env; printf PRIVATE_HOME > /home/node/skill-check-private'],check=True)
  subprocess.run(['podman','exec','--user','root',DEV,'ln','-sfn','/home/node/skill-check-private','/opt/skill-check-link'],check=True)
 if a.credential_files:
  subprocess.run(['podman','exec',DEV,'sh','-c','printf CREDENTIAL_ORIGINAL > /workspace/.env'],check=True)
  subprocess.run(
   ['podman','exec','-i',DEV,'sh','-c','cat > /tmp/credential-files-protected.json'],
   input=json.dumps(saved_config['options']['protect_credentials']),text=True,check=True)
 if a.credential_files:
  checks = [('check_credential_files_rpc.py', ['python3', '-'])]
 elif a.approval_context:
  assert a.port == 18187
  assert saved_config['options']['approval'] == 'automatic'
  prepare = "from pathlib import Path; p=Path('/home/node/.pi/agent/skills/approval-context'); p.mkdir(parents=True, exist_ok=True); (p/'SKILL.md').write_text('---\\nname: approval-context\\ndescription: Synthetic approval integration fixture\\n---\\n' + 'SKILL_CONTEXT_LINE '*1800 + 'SKILL_CONTEXT_END'); Path('/workspace/.env').write_text('KEY=SYNTHETIC_PRIVATE_VALUE')"
  subprocess.run(['podman','exec',DEV,'python3','-c',prepare],check=True)
 if a.communications:
  subprocess.run(['podman','exec','-i',DEV,'python3','/usr/local/lib/sandbox-communications.py'], input=json.dumps({'botToken':'xoxb-sandbox-fixture-only'}), text=True, check=True)
 if a.browser_viewer:
  subprocess.run(['podman','exec',DEV,'node','/opt/betterwright/check.mjs'],check=True)
 elif not a.review_recovery and not a.review_images and not a.skill_workflow and not a.browser_shell and not a.approval_context and not a.web_access and not a.folders and not a.recall and not a.communications:
  subprocess.run([sys.executable,str(ROOT/'sandbox.py'),'--state-dir',str(a.state_dir),'check',a.name,'--allowed-url',f'http://local-model.internal:{a.port}/v1/models'],check=True)
 if not a.credential_files:
  checks = [('check_security_rpc.py',['python3','-']),('check_automation_rpc.py',['python3','-']),('check_pendant_worker.cjs',['node','-'])]
 if a.skill_workflow or a.browser_shell:
  checks = [('check_skill_workflow_rpc.py', ['python3', '-']), ('check_pendant_worker.cjs', ['node', '-', '--skill-workflow'])]
 elif a.approval_context:
  checks = [('check_approval_context_rpc.py', ['python3', '-']), ('check_pendant_worker.cjs', ['node', '-', '--approval-context'])]
 elif a.review_recovery:
  checks = [('check_review_images_rpc.py', ['python3', '-']), ('check_pendant_worker.cjs', ['node', '-', '--review-recovery'])]
 elif a.review_images:
  checks = [('check_review_images_rpc.py', ['python3', '-']), ('check_pendant_worker.cjs', ['node', '-', '--review-images'])]
 elif a.communications:
  checks = [('check_communications_rpc.py', ['python3', '-']), ('check_pendant_worker.cjs', ['node', '-', '--communications'])]
 elif a.recall:
  checks = [('check_recall_rpc.py', ['python3', '-']), ('check_pendant_worker.cjs', ['node', '-', '--recall'])]
 elif a.folders:
  checks = [('check_folders_rpc.py', ['python3', '-']), ('check_pendant_worker.cjs', ['node', '-', '--folders'])]
 elif a.browser_viewer:
  checks = [('check_browser_rpc.py', ['python3', '-']), ('check_pendant_worker.cjs', ['node', '-', '--viewer'])]
 elif a.web_access:
  checks = [('check_web_access_rpc.py', ['python3', '-']), ('check_pendant_worker.cjs', ['node', '-', '--web-access'])]
 elif a.pendant_questions_only:
  checks = [('check_pendant_worker.cjs', ['node', '-', '--questions-only'])]
 for file,command in checks:
  print('RUN',file,flush=True)
  if a.browser_viewer and file == 'check_pendant_worker.cjs':
   import urllib.request
   subprocess.run(['podman','exec',DEV,'rm','-f','/tmp/viewer-worker-links.json','/tmp/viewer-worker-finish'],check=True)
   worker = subprocess.Popen(['podman','exec','-i','-e','VIEWER_HOLD=1',DEV,*command],stdin=subprocess.PIPE,text=True)
   worker.stdin.write((ROOT/'tests'/file).read_text());worker.stdin.close()
   try:
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
     if worker.poll() is not None: raise RuntimeError('Pendant worker ended before viewer check')
     links=subprocess.run(['podman','exec',DEV,'cat','/tmp/viewer-worker-links.json'],capture_output=True,text=True)
     if links.returncode==0: break
     time.sleep(.25)
    else: raise RuntimeError('Pendant viewer links were not produced')
    http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for index,url in enumerate(json.loads(links.stdout)):
     with http.open(url,timeout=30) as response: page=response.read().decode()
     own,other=('ONE','TWO') if index==0 else ('TWO','ONE')
     assert 'VIEWER_'+own in page and 'VIEWER_'+other not in page, 'Viewer listed another session'
    print('PASS each Pendant viewer lists only its own session',flush=True)
   finally:
    subprocess.run(['podman','exec',DEV,'touch','/tmp/viewer-worker-finish'],check=True)
    assert worker.wait(timeout=30)==0, 'Pendant worker failed'
  else:
   subprocess.run(['podman','exec','-i',*(['-e','REVIEW_RECOVERY=1'] if a.review_recovery else []),DEV,*command],input=(ROOT/'tests'/file).read_text(),text=True,check=True)
 if a.web_providers:
  attempts = fixture/'search-attempts.txt'
  assert attempts.exists() and len(attempts.read_text().splitlines()) == 2, 'Both clients must try SearXNG before falling back to Exa'
  saved_search = subprocess.check_output(['podman','exec',DEV,'cat','/home/node/.pi/agent/web-search.json'],text=True)
  selection = json.loads(saved_search)
  selection.update(provider='searxng', webSearch={'allowedProviders':['searxng']})
  search_writer = "from pathlib import Path;import sys;Path('/home/node/.pi/agent/web-search.json').write_text(sys.stdin.read())"
  subprocess.run(['podman','exec','-i',DEV,'python3','-c',search_writer],input=json.dumps(selection),text=True,check=True)
  for file, command in checks:
   subprocess.run(['podman','exec','-i','-e','WEB_ONLY=1',DEV,*command],input=(ROOT/'tests'/file).read_text(),text=True,check=True)
  assert len(attempts.read_text().splitlines()) == 4, 'Only-provider requests must still reach SearXNG'
 if a.recall:
  assert not (fixture/'reviews.jsonl').exists(), 'History tools must not invoke the reviewer'
  prompts = [json.loads(line) for line in (fixture/'recall-prompts.jsonl').read_text().splitlines()]
  assert any(p['hints'] for p in prompts) == (saved_config['options']['compaction_recall'] == 'full'), prompts
 reviews = fixture/'reviews.jsonl'
 if a.review_model:
  assert not reviews.exists(), 'Live reviewer unexpectedly used the synthetic review provider'
  count_code = """import json,pathlib
counts={}
for client in ('cli','pendant'):
 rows=map(json.loads,pathlib.Path('/tmp/review-recovery-'+client+'.jsonl').read_text().splitlines())
 counts[client]=len({r['data']['requestId'] for r in rows if r.get('customType')=='pi-auto-review-attempt'})
print(json.dumps(counts))"""
  observed = json.loads(subprocess.check_output(['podman','exec',DEV,'python3','-c',count_code],text=True))
  assert observed == {'cli':22,'pendant':22}, observed
  manifest['observedReviewDecisions'] = observed
  print('PASS ' + str(sum(observed.values())) + ' recorded live reviews with ' + a.review_model + '; main-agent responses remain synthetic', flush=True)
 if a.browser_viewer: assert not reviews.exists(), 'Native browser/viewer calls must not invoke the reviewer'
 if reviews.exists():
  if a.review_recovery:
   records = [json.loads(line) for line in reviews.read_text().splitlines()]
   assert len(records) == 44 and all(r.get('omitted', 0) > 0 for r in records), records
   assert sum(r.get('reset', False) for r in records) >= 2, 'History did not roll over in both clients'
  if a.review_images: assert len(reviews.read_text().splitlines()) == 4, 'Expected screenshot and follow-up reviews in both clients'
  if a.approval_context: assert len(reviews.read_text().splitlines()) >= 8, 'Expected reviews from both clients'
  if a.web_access: assert len(reviews.read_text().splitlines()) == 6, 'Only the three explicit fetches in each client should invoke the reviewer'
  assert not any(json.loads(line)['question'] for line in reviews.read_text().splitlines()), 'Question tool unexpectedly invoked the reviewer'
 if a.folders:
  prompts = [json.loads(line) for line in (fixture/'folder-prompts.jsonl').read_text().splitlines()]
  assert len(prompts) == 22, len(prompts)
  print('PASS both clients received the mounted-folder map with project prompt overrides', flush=True)
 print('PASS Pi/Pendant 46-operation automatic review integration' if a.review_recovery else 'PASS Pi/Pendant screenshot review integration' if a.review_images else 'PASS common credential-file protection through actual Pi tools' if a.credential_files else 'PASS Pi/Pendant browser shell routes' if a.browser_shell else 'PASS Pi/Pendant workflow cases' if a.skill_workflow else 'PASS Pi/Pendant expanded skill automatic approval' if a.approval_context else 'PASS Pi/Pendant Slack integration' if a.communications else 'PASS Pi/Pendant recall integration' if a.recall else 'PASS Pi/Pendant folder integration' if a.folders else 'PASS Pi/Pendant browser viewer integration' if a.browser_viewer else 'PASS Pendant startup and questions; no question review calls' if a.pendant_questions_only else 'PASS Pi/Pendant web access integration' if a.web_access else 'PASS real Pi/Pendant security, Goal, scheduling and transport using fixture replies',flush=True)
except BaseException:
 if manifest is not None:
  manifest['status']='failed'
  (RUNTIME/'run.json').write_text(json.dumps(manifest,indent=2)+'\n')
 raise
finally:
 if saved_review_config is not None: review_config.write_text(saved_review_config)
 if saved_search is not None:
  subprocess.run(['podman','exec','-i',DEV,'python3','-c',search_writer],input=saved_search,text=True,check=True)
 server.terminate();server.wait(timeout=20)
 if saved_models is None:
  subprocess.run(['podman','exec',DEV,'rm','-f','/home/node/.pi/agent/models.json'],check=True)
 else:
  subprocess.run(['podman','exec','-i',DEV,'python3','-c',code],input=saved_models,text=True,check=True)
if manifest is not None:
 manifest['status']='passed'
 (RUNTIME/'run.json').write_text(json.dumps(manifest,indent=2)+'\n')
