"""Exercise real sandbox lifecycle and key rotation with synthetic credentials."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pi_sandbox_factory import sandbox, inference, hosted_models


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dev-image',required=True,help='Development image with the current entrypoint')
    parser.add_argument('--proxy-image',default='localhost/pi-sandbox-factory-proxy:1')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='factory-inference-lifecycle-') as temp:
        root=Path(temp);workspace=root/'workspace';workspace.mkdir()
        name='inference-'+root.name.rsplit('-',1)[-1];state=root/'state'/name
        (root/'providers.json').write_text('{}')
        config=None
        try:
            subprocess.run([sys.executable,'-m','pi_sandbox_factory','--state-dir',str(state.parent),'create',name,
                '--workspace',str(workspace),'--engine','podman','--allow-domain','pi.dev:443',
                '--providers-file',str(root/'providers.json'),'--editor','pi'],check=True,capture_output=True,text=True)
            config=json.loads((state/'config.json').read_text())
            with patch.object(sandbox,'image_names',return_value=(args.dev_image,args.proxy_image)):
                sandbox.up(config,state)
            dev=sandbox.inspect(config,sandbox.names(config)[0])
            assert dev['HostConfig']['NetworkMode']=='none'
            value={'provider':'openrouter','key':'private-lifecycle-fixture'}
            hosted_models.save(config,state,value)
            config=json.loads((state/'config.json').read_text())
            before=sandbox.inspect(config,inference.names(config)[0])
            assert before['HostConfig']['ReadonlyRootfs'] and not before['HostConfig'].get('PortBindings')
            # Rotating or retaining a key must not interrupt streams by replacing the service.
            hosted_models.save(config,state,{**value,'key':'replacement-lifecycle-fixture'})
            hosted_models.save(config,state,{**value,'key':''})
            assert sandbox.inspect(config,inference.names(config)[0])['Id']==before['Id']
            assert inference.credentials(config,state,{'status':True})['configured']==['openrouter']
            assert sandbox.inspect(config,sandbox.names(config)[0])['Id']==dev['Id']
            public=(state/'config.json').read_text()+(state/'inference/routes.json').read_text()+json.dumps(before)
            client=subprocess.run(['podman','exec',sandbox.names(config)[0],'cat','/home/node/.pi/agent/auth.json','/home/node/.pi/agent/models.json'],check=True,capture_output=True,text=True).stdout
            assert 'lifecycle-fixture' not in public+client
            assert 'factory-inference' in client
            assert not any(m.get('Name')==inference.names(config)[2] for m in dev['Mounts'])
            inference.down(config)
            hosted_models.remove(config,state,'openrouter')
            assert not inference.enabled(json.loads((state/'config.json').read_text()))
            print('PASS production startup, isolated key import, key rotation without restart, native placeholder, stopped-service removal',flush=True)
        finally:
            if config:sandbox.delete(config,state)
        assert workspace.exists()
        print('PASS deletion removes private state and volumes while preserving workspace',flush=True)

if __name__=='__main__':main()
