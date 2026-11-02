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
a=p.parse_args()
RUNTIME=a.artifacts or Path(tempfile.mkdtemp(prefix='local-ai-sandbox-check-'))
RUNTIME.mkdir(parents=True,exist_ok=True)
DEV='local-ai-sandbox-'+a.name
fixture=RUNTIME/'fixture';fixture.mkdir(exist_ok=True)
(fixture/'expected-subagents.json').write_text('false')
(fixture/'expected-profile.txt').write_text((ROOT/'profiles/base/profile.md').read_text())
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
try:
 for _ in range(100):
  try:
   with socket.create_connection(('127.0.0.1',a.port),timeout=1):break
  except OSError:time.sleep(.05)
 else:raise RuntimeError('Fixture failed to start')
 config={'providers':{'fixture':{'baseUrl':f'http://local-model.internal:{a.port}/v1','api':'openai-completions','apiKey':'fixture-key','models':[{'id':'fixture-model','contextWindow':32000,'maxTokens':4096}]}}}
 code="from pathlib import Path;import sys;p=Path('/home/node/.pi/agent/models.json');p.write_text(sys.stdin.read());p.chmod(0o600)"
 subprocess.run(['podman','exec','-i',DEV,'python3','-c',code],input=json.dumps(config),text=True,check=True)
 subprocess.run([sys.executable,str(ROOT/'sandbox.py'),'--state-dir',str(a.state_dir),'check',a.name,'--allowed-url',f'http://local-model.internal:{a.port}/v1/models'],check=True)
 for file,command in [('check_security_rpc.py',['python3','-']),('check_automation_rpc.py',['python3','-']),('check_pendant_worker.cjs',['node','-'])]:
  print('RUN',file,flush=True)
  subprocess.run(['podman','exec','-i',DEV,*command],input=(ROOT/'tests'/file).read_text(),text=True,check=True)
 print('PASS real Pi/Pendant security, Goal, scheduling and transport using fixture replies',flush=True)
finally:
 server.terminate();server.wait(timeout=20)
 if saved_models is None:
  subprocess.run(['podman','exec',DEV,'rm','-f','/home/node/.pi/agent/models.json'],check=True)
 else:
  subprocess.run(['podman','exec','-i',DEV,'python3','-c',code],input=saved_models,text=True,check=True)
