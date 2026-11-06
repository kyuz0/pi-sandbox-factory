"""Check viewer restart and cleanup in an explicitly disposable browser sandbox."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vscode_pi_sandbox import sandbox
from vscode_pi_sandbox.browser_viewer import ensure_viewer

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--state-dir', type=Path, required=True)
parser.add_argument('--name', required=True)
args = parser.parse_args()
state = args.state_dir / args.name
config = json.loads((state / 'config.json').read_text())
engine, container = config['engine'], sandbox.names(config)[0]
cid = sandbox.inspect(config, container)['Id']
http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def inside(*command, data=None, check=True):
    return subprocess.run([engine,'exec','-i',container,*command],input=data,text=True,
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=check)
def relay_pids():
    result = []
    for line in subprocess.check_output(['ps','-eo','pid,args'],text=True).splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[2].endswith('/browser_viewer.py') and fields[4] == cid:
            result.append(int(fields[0]))
    return result

def wait(predicate, message):
    for _ in range(100):
        if predicate(): return
        time.sleep(.1)
    raise AssertionError(message)

def link():
    return inside('node','--input-type=module','-e',
        "import {viewerLink} from '/opt/betterwright/viewer.mjs'; console.log(await viewerLink('" + session + "'));").stdout.strip()

def fetch(url, headers=None):
    with http.open(urllib.request.Request(url,headers=headers or {}),timeout=30) as response:
        return response.read().decode()

def refused(url, headers=None):
    try:
        fetch(url, headers)
    except urllib.error.HTTPError as error:
        assert error.code == 403
    else: raise AssertionError('Unsafe viewer request accepted')

inside('python3','-c',"from pathlib import Path;import sys;Path('/tmp/viewer-lifecycle.mjs').write_text(sys.stdin.read())",data='''
import {SandboxBrowser} from '/opt/betterwright/browser.mjs';
import {writeFile} from 'node:fs/promises';
const browser = new SandboxBrowser();
const result = await browser.run("await page.setContent('<title>Lifecycle marker</title><h1>Browser state survives viewer restart</h1>'); return await page.title()");
if (!result.ok) throw Error(JSON.stringify(result));
await writeFile('/tmp/viewer-lifecycle-url', await browser.viewerLink());
setInterval(()=>{},1000);
''')
subprocess.run([engine,'exec','-d',container,'node','/tmp/viewer-lifecycle.mjs'],check=True)
wait(lambda: inside('test','-f','/tmp/viewer-lifecycle-url',check=False).returncode == 0, 'Browser did not start')
url = inside('cat','/tmp/viewer-lifecycle-url').stdout.strip()
session = url.split('/')[4]
ensure_viewer(engine,cid)
assert link() == url, 'Opening an existing viewer changed its key'
assert len(relay_pids()) == 1
page = fetch(url)
assert 'Lifecycle marker' in page
for path in ('json/list','devtools/browser/ABC','devtools/../json/list','devtools/%2e%2e/json/list'):
    refused(url + path)
refused(url, {'Host':'evil.test'})
refused(url, {'Origin':'https://evil.test'})
refused(url.replace(url.split('/')[5], '0'*64))
# Keep a real WebSocket open during SIGTERM; shutdown must not wait for the UI.
parsed = urllib.parse.urlsplit(url)
target = re.search(r'devtools/page/([A-F0-9]+)',page)[1]
ws = socket.create_connection((parsed.hostname,parsed.port),timeout=10)
ws.sendall((f'GET {parsed.path}devtools/page/{target} HTTP/1.1\r\nHost: {parsed.netloc}\r\n'
            f'Origin: http://{parsed.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
            'Sec-WebSocket-Version: 13\r\nSec-WebSocket-Key: aaaaaaaaaaaaaaaaaaaaaa==\r\n\r\n').encode())
assert b'101 ' in ws.recv(4096)
os.kill(relay_pids()[0],signal.SIGTERM)
wait(lambda:not relay_pids(),'Viewer hung on active WebSocket')
ws.close()
ensure_viewer(engine,cid)
new_url=link()
assert new_url != url and 'Lifecycle marker' in fetch(new_url)
assert inside('sh','-c',"ps -eo args | grep '^node /opt/betterwright/viewer.mjs connect'",check=False).returncode != 0, 'Connector left running'
print('PASS repeated open, authenticated routes, WebSocket shutdown, key rotation and retained browser state')
sandbox.down(config)
wait(lambda:not relay_pids(),'Viewer remained after container stop')
subprocess.run([engine,'start',container],check=True,stdout=subprocess.DEVNULL)
stale = inside('node','--input-type=module','-e',
    "import {viewerLink} from '/opt/betterwright/viewer.mjs'; await viewerLink('"+session+"');",check=False)
assert stale.returncode != 0 and 'Reopen this sandbox' in stale.stderr
sandbox.up(config,state)
assert len(relay_pids()) == 1
print('PASS stop cleanup, stale boot rejection and launcher restart')
