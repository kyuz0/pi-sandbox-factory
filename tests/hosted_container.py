"""Check the shipped Pi/Pendant runtimes with synthetic provider credentials."""
import argparse
import json
from pathlib import Path
import subprocess
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', required=True, help='A built Factory development image')
    parser.add_argument('--inference-image', required=True)
    args = parser.parse_args()
    name = 'factory-hosted-check-' + uuid.uuid4().hex[:10]
    volume = name + '-home'
    root = Path(__file__).resolve().parents[1]
    script = (root / 'pi_sandbox_factory/providers/hosted-models.mjs').read_text()
    def call(**value):
        result = subprocess.run(['podman','exec','-i','--user','node',name,'node','--input-type=module','-e',script],
                                input=json.dumps(value),text=True,capture_output=True,timeout=75)
        reply = json.loads(result.stdout)
        if result.returncode: raise RuntimeError(reply)
        return reply
    import sys, tempfile, shutil, base64, time
    sys.path.insert(0,str(root))
    from pi_sandbox_factory import inference
    broker=name+'-inference';socket=broker+'-socket';keys=broker+'-keys'
    folder=Path(tempfile.mkdtemp(prefix='factory-native-inference-'))
    config={'hosted_connections':{'openrouter':{},'together':{},'azure':{'endpoint':'https://fixture.openai.azure.com/openai/v1'},'amazon-bedrock':{'region':'eu-west-1','method':'iam'}}}
    try:
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=127.0.0.1','-addext','subjectAltName=IP:127.0.0.1','-keyout',str(folder/'tls.key'),'-out',str(folder/'tls.crt')],check=True,capture_output=True)
        shutil.copy(root/'tests/inference_fixture.mjs',folder/'server.mjs')
        routes=inference.routes(config)
        for route in routes.values():route['origin']='https://127.0.0.1:18444'
        (folder/'routes.json').write_text(json.dumps(routes))
        subprocess.run(['podman','run','-d','--name',name,'--network','none','--userns=keep-id:uid=1000,gid=1000',
                        '--user','1000:1000','--volume',volume+':/home/node','--volume',socket+':/run/inference:ro',
                        '--entrypoint','sleep',args.image,'infinity'],check=True,capture_output=True)
        frames = r"""
const {EventStreamCodec}=require('/usr/local/lib/node_modules/@earendil-works/pi-coding-agent/node_modules/@smithy/core/event-streams');
const codec=new EventStreamCodec(x=>Buffer.from(x).toString(),x=>Buffer.from(x));
const events=[['messageStart',{role:'assistant'}],['contentBlockDelta',{contentBlockIndex:0,delta:{text:'OK'}}],['contentBlockStop',{contentBlockIndex:0}],['messageStop',{stopReason:'end_turn'}],['metadata',{usage:{inputTokens:1,outputTokens:1,totalTokens:2},metrics:{latencyMs:1}}]];
console.log(Buffer.concat(events.map(([type,body])=>Buffer.from(codec.encode({headers:{':message-type':{type:'string',value:'event'},':event-type':{type:'string',value:type},':content-type':{type:'string',value:'application/json'}},body:Buffer.from(JSON.stringify(body))})))).toString('base64'));
"""
        encoded=subprocess.run(['podman','exec','-i',name,'node'],input=frames,text=True,check=True,capture_output=True).stdout
        (folder/'bedrock.bin').write_bytes(base64.b64decode(encoded))
        subprocess.run(['podman','run','-d','--name',broker,'--network','none','--userns=keep-id:uid=1000,gid=1000','--user','1000:1000','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges',
                        '-v',keys+':/private:z','-v',socket+':/run/inference:z','-v',str(folder)+':/fixture:ro,Z','-e','NODE_EXTRA_CA_CERTS=/fixture/tls.crt',args.inference_image,'node','/fixture/server.mjs'],check=True,capture_output=True)
        for provider in config['hosted_connections']:
            credential={'accessKeyId':'fixture-access','secretAccessKey':'fixture-secret','sessionToken':'fixture-session'} if provider=='amazon-bedrock' else {'key':'private-fixture-'+provider}
            subprocess.run(['podman','exec','-i',broker,'node','/app/credentials.mjs','/private/credentials.json'],input=json.dumps({'id':provider,'auth':routes[provider]['auth']['type'],'origin':routes[provider]['origin'],'credentials':credential}),text=True,check=True,capture_output=True)
        for _ in range(80):
            if subprocess.run(['podman','exec',name,'test','-S','/run/inference/proxy.sock'],capture_output=True).returncode==0:break
            time.sleep(.25)
        subprocess.run(['podman','exec','-d',name,'socat','TCP-LISTEN:19431,bind=127.0.0.1,reuseaddr,fork','UNIX-CONNECT:/run/inference/proxy.sock'],check=True,capture_output=True)
        for provider,connection in config['hosted_connections'].items():
            reply=call(action='configure',provider=provider,endpoint=inference.client_url(provider,connection),region=connection.get('region',''))
            assert reply['configured']
            assert call(action='catalogue',provider=provider)['models']
            print('PASS configuration/catalogue:',provider,flush=True)
        call(action='select',provider='azure',model='gpt-4o',deployment='team-gpt')
        call(action='test',provider='openrouter',model='anthropic/claude-haiku-4.5')
        try:
            call(action='test',provider='azure',model='gpt-4o',deployment='missing')
        except RuntimeError as error:
            assert 'DeploymentNotFound' in str(error),str(error)
        else:
            raise AssertionError('Missing deployment was accepted')
        print('PASS bounded connection test and actionable provider errors',flush=True)
        bedrock=call(action='catalogue',provider='amazon-bedrock')['models']
        base=next(m for m in bedrock if 'claude' in m['id'])['id']
        call(action='select',provider='amazon-bedrock',model=base,profile_id='arn:aws:bedrock:eu-west-1:123456789012:application-inference-profile/fixture')
        subprocess.run(['podman','exec','-i','--user','node',name,'node'],input=(root/'tests/check_hosted_runtime.cjs').read_text(),text=True,check=True,timeout=150)
        for provider in ['openrouter','together','azure','amazon-bedrock']:call(action='remove',provider=provider)
        assert not any(p['configured'] for p in call(action='status')['providers'])
        print('PASS connection removal')
    finally:
        subprocess.run(['podman','rm','-f',name,broker],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        subprocess.run(['podman','volume','rm',volume,socket,keys],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        shutil.rmtree(folder)


if __name__ == '__main__': main()
