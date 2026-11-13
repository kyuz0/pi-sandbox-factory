#!/usr/bin/env python3
"""Check Microsoft sign-in category rules with a disposable real Squid gateway.

Uses public sign-in discovery/CDN requests without credentials. Does not change
saved sandboxes. Requires a built Factory proxy image, curl and Podman/Docker.
"""
import argparse,json,subprocess,sys,tempfile,time,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pi_sandbox_factory import network_groups,sandbox
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--engine',default='podman',choices=['podman','docker'])
p.add_argument('--proxy-image',default='localhost/pi-sandbox-factory-proxy:1')
a=p.parse_args();name='factory-auth-category-check-'+uuid.uuid4().hex[:10]
def engine(*args,**kw):
 return subprocess.run([a.engine,*args],text=True,capture_output=True,check=True,**kw)
try:
 with tempfile.TemporaryDirectory(prefix='factory-auth-category-') as temp:
  root=Path(temp)
  policy=sandbox.squid_config([('127.0.0.1',18081)],network_groups.snapshots(['auth-microsoft']))
  # Publish only this test listener on host loopback. ACL contents are unchanged.
  (root/'squid.conf').write_text(policy.replace('http_port 127.0.0.1:3128','http_port 0.0.0.0:3128'))
  (root/'redirect.http').write_bytes(b'HTTP/1.1 302 Found\r\nLocation: https://unselected.invalid/\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
  engine('create','--name',name,'-p','127.0.0.1::3128','--add-host','aadcdn.msauth.net:127.0.0.1',
   '--entrypoint','/usr/bin/tini',a.proxy_image,'--','/usr/sbin/squid','-N','-f','/tmp/category.conf')
  engine('cp',str(root/'squid.conf'),name+':/tmp/category.conf')
  engine('cp',str(root/'redirect.http'),name+':/tmp/redirect.http')
  engine('start',name)
  endpoint='http://'+engine('port',name,'3128/tcp').stdout.strip()
  engine('exec','-d',name,'socat','TCP-LISTEN:18081,bind=127.0.0.1,reuseaddr,fork','EXEC:/bin/cat /tmp/redirect.http')
  def request(url,follow=False):
   return subprocess.run(['curl','--noproxy','','--proxy',endpoint,'--connect-timeout','15','--max-time','60',
    '-sS','-o','/dev/null','-w','%{http_connect} %{http_code}',*(['-L'] if follow else []),url],capture_output=True,text=True)
  deadline=time.monotonic()+30
  while time.monotonic()<deadline:
   result=request('https://unselected.invalid')
   if result.stdout.startswith('403 '):break
   time.sleep(.1)
  else:raise AssertionError('Test gateway did not become ready: '+result.stderr)
  for url in ('https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration',
              'https://aadcdn.msftauth.net/'):
   result=request(url);assert result.returncode==0 and result.stdout.startswith('200 '),(url,result.stdout,result.stderr)
   print('PASS allowed Microsoft endpoint:',url,flush=True)
  for url in ('https://login.microsoftonline.com.attacker.invalid/',
              'https://unselected.invalid/', 'https://graph.microsoft.com/v1.0/me',
              'https://login.microsoftonline.com:8443/', 'https://aadcdn.msauth.net/'):
   result=request(url);assert result.stdout.startswith('403 '),(url,result.stdout,result.stderr)
  print('PASS misleading suffix, unselected site, Graph API, nonstandard port and private destination denied',flush=True)
  result=request('http://127.0.0.1:18081/')
  assert result.returncode==0 and result.stdout=='000 302',(result.stdout,result.stderr)
  result=request('http://127.0.0.1:18081/',follow=True)
  assert result.stdout.startswith('403 '),(result.stdout,result.stderr)
  print('PASS explicit local port and blocked redirect destination',flush=True)
except BaseException:
 logs=subprocess.run([a.engine,'logs','--tail','12',name],text=True,capture_output=True)
 print(logs.stdout+logs.stderr,flush=True)
 raise
finally:
 subprocess.run([a.engine,'rm','-f',name],capture_output=True)
