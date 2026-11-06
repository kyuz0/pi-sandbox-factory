#!/usr/bin/env python3
"""Exercise the real sandbox with a synthetic host-loopback inference server."""
from pathlib import Path
import json
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
a=p.parse_args()
if a.web_providers: a.web_access=True
RUNTIME=a.artifacts or Path(tempfile.mkdtemp(prefix='pi-sandbox-factory-check-'))
RUNTIME.mkdir(parents=True,exist_ok=True)
DEV='pi-sandbox-factory-'+a.name
fixture=RUNTIME/'fixture';fixture.mkdir(exist_ok=True)
(fixture/'expected-subagents.json').write_text('false')
saved_config=json.loads((a.state_dir/a.name/'config.json').read_text())
(fixture/'expected-profile.txt').write_text('PROJECT_VIEWER_GUIDANCE' if a.browser_viewer else (Path(saved_config['profile']['path'])/'profile.md').read_text())
if a.recall: (fixture/'recall-mode.txt').write_text(saved_config['options']['compaction_recall'])
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
try:
 for _ in range(100):
  try:
   with socket.create_connection(('127.0.0.1',a.port),timeout=1):break
  except OSError:time.sleep(.05)
 else:raise RuntimeError('Fixture failed to start')
 config={'providers':{'fixture':{'baseUrl':f'http://local-model.internal:{a.port}/v1','api':'openai-completions','apiKey':'fixture-key','models':[{'id':'fixture-model','contextWindow':32000,'maxTokens':4096}]}}}
 code="from pathlib import Path;import sys;p=Path('/home/node/.pi/agent/models.json');p.write_text(sys.stdin.read());p.chmod(0o600)"
 subprocess.run(['podman','exec','-i',DEV,'python3','-c',code],input=json.dumps(config),text=True,check=True)
 if a.browser_viewer:
  subprocess.run(['podman','exec',DEV,'node','/opt/betterwright/check.mjs'],check=True)
 elif not a.web_access and not a.folders and not a.recall:
  subprocess.run([sys.executable,str(ROOT/'sandbox.py'),'--state-dir',str(a.state_dir),'check',a.name,'--allowed-url',f'http://local-model.internal:{a.port}/v1/models'],check=True)
 checks = [('check_security_rpc.py',['python3','-']),('check_automation_rpc.py',['python3','-']),('check_pendant_worker.cjs',['node','-'])]
 if a.recall:
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
   subprocess.run(['podman','exec','-i',DEV,*command],input=(ROOT/'tests'/file).read_text(),text=True,check=True)
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
 if reviews.exists():
  if a.web_access: assert len(reviews.read_text().splitlines()) == 6, 'Only the three explicit fetches in each client should invoke the reviewer'
  assert not any(json.loads(line)['question'] for line in reviews.read_text().splitlines()), 'Question tool unexpectedly invoked the reviewer'
 if a.folders:
  prompts = [json.loads(line) for line in (fixture/'folder-prompts.jsonl').read_text().splitlines()]
  assert len(prompts) == 22, len(prompts)
  print('PASS both clients received the mounted-folder map with project prompt overrides', flush=True)
 print('PASS Pi/Pendant recall integration' if a.recall else 'PASS Pi/Pendant folder integration' if a.folders else 'PASS Pi/Pendant browser viewer integration' if a.browser_viewer else 'PASS Pendant startup and questions; no question review calls' if a.pendant_questions_only else 'PASS Pi/Pendant web access integration' if a.web_access else 'PASS real Pi/Pendant security, Goal, scheduling and transport using fixture replies',flush=True)
finally:
 if saved_search is not None:
  subprocess.run(['podman','exec','-i',DEV,'python3','-c',search_writer],input=saved_search,text=True,check=True)
 server.terminate();server.wait(timeout=20)
 if saved_models is None:
  subprocess.run(['podman','exec',DEV,'rm','-f','/home/node/.pi/agent/models.json'],check=True)
 else:
  subprocess.run(['podman','exec','-i',DEV,'python3','-c',code],input=saved_models,text=True,check=True)
