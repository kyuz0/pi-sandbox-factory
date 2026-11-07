"""Exercise the inference credential boundary with disposable, offline containers."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', required=True, help='Built inference companion image')
    parser.add_argument('--dev-image', required=True, help='Built development image')
    args = parser.parse_args()
    name = 'factory-inference-test-' + uuid.uuid4().hex[:8]
    broker, client, socket, keys = [name + suffix for suffix in ('-broker', '-client', '-socket', '-keys')]
    def run(*command, **kwargs):
        return subprocess.run(['podman', *command], capture_output=True, text=True, check=True, **kwargs)
    base = ['--network=none', '--userns=keep-id:uid=1000,gid=1000', '--user=1000:1000',
            '--cap-drop=ALL', '--security-opt=no-new-privileges', '--security-opt=label=disable']
    with tempfile.TemporaryDirectory(prefix='factory-inference-test-') as temp:
        folder = Path(temp)
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
            '-subj', '/CN=127.0.0.1', '-addext', 'subjectAltName=IP:127.0.0.1',
            '-keyout', str(folder / 'tls.key'), '-out', str(folder / 'tls.crt')], check=True, capture_output=True)
        (folder / 'server.mjs').write_text('''
import https from 'node:https';
import fs from 'node:fs';
import {compileRoutes,createBroker} from '/app/broker.mjs';
import {readCredentials} from '/app/credentials.mjs';
const upstream=https.createServer({key:fs.readFileSync('/fixture/tls.key'),cert:fs.readFileSync('/fixture/tls.crt')},(req,res)=>{
 req.resume();req.on('end',()=>{
  const key=readCredentials('/private/credentials.json').sample?.key;
  if(!key||req.headers.authorization!=='Bearer '+key){res.writeHead(401);return res.end();}
  res.writeHead(200,{'content-type':'text/event-stream'});res.write('data: authenticated\\n\\n');setTimeout(()=>res.end('data: done\\n\\n'),30);
 });
});
await new Promise(resolve=>upstream.listen(18444,'127.0.0.1',resolve));
const routes=compileRoutes({sample:{origin:'https://127.0.0.1:18444',auth:{type:'bearer'},operations:[{method:'POST',path:'/v1/chat/completions'}]}});
const server=createBroker(routes,id=>readCredentials('/private/credentials.json')[id]);
fs.rmSync('/run/inference/proxy.sock',{force:true});server.listen('/run/inference/proxy.sock',()=>fs.chmodSync('/run/inference/proxy.sock',0o666));
''')
        probe = '''
const fs=require('fs'),http=require('http'),assert=require('assert/strict');
assert(!JSON.stringify(process.env).includes('hidden-inference-fixture'));
assert(!fs.existsSync('/private/credentials.json'));assert(!fs.existsSync('/fixture'));
const req=http.request({socketPath:'/run/inference/proxy.sock',path:'/r/sample/v1/chat/completions',method:'POST',headers:{authorization:'hostile',host:'attacker.invalid'}},res=>{
 let body='';res.on('data',chunk=>body+=chunk);res.on('end',()=>{assert.equal(res.statusCode,200);assert.equal(body,'data: authenticated\\n\\ndata: done\\n\\n');console.log('PASS agent request: authenticated stream, no key file/env, hostile headers replaced');});
});req.on('error',error=>{throw error;});req.end('{}');
'''
        try:
            run('run', '-d', '--name', broker, *base, '--read-only', '-v', keys + ':/private', '-v', socket + ':/run/inference',
                '-v', temp + ':/fixture:ro', '-e', 'NODE_EXTRA_CA_CERTS=/fixture/tls.crt', args.image, 'node', '/fixture/server.mjs')
            run('exec', '-i', broker, 'node', '/app/credentials.mjs', '/private/credentials.json',
                input=json.dumps({'id':'sample','origin':'https://127.0.0.1:18444','credentials':{'key':'hidden-inference-fixture'}}))
            run('run', '-d', '--name', client, *base, '-v', socket + ':/run/inference:ro', '--entrypoint', 'sleep', args.dev_image, 'infinity')
            def ready():
                for _ in range(80):
                    result = subprocess.run(['podman','exec',client,'test','-S','/run/inference/proxy.sock'], capture_output=True)
                    if result.returncode == 0:
                        return
                    time.sleep(.25)
                raise RuntimeError('Inference fixture did not start')
            ready()
            print(run('exec','-i',client,'node',input=probe).stdout, end='')
            info = json.loads(run('inspect',client).stdout)[0]
            assert info['HostConfig']['NetworkMode'] == 'none'
            assert not info['HostConfig'].get('PortBindings')
            assert all(m.get('Name') != keys for m in info['Mounts'])
            assert next(m for m in info['Mounts'] if m.get('Name') == socket)['RW'] is False
            assert 'hidden-inference-fixture' not in run('inspect',broker,client).stdout
            run('restart',broker)
            ready()
            print(run('exec','-i',client,'node',input=probe).stdout, end='')
            print('PASS isolated credentials volume, read-only socket, no published ports, restart persistence')
        finally:
            subprocess.run(['podman','rm','-f',client,broker],capture_output=True)
            subprocess.run(['podman','volume','rm',socket,keys],capture_output=True)


if __name__ == '__main__':
    main()
