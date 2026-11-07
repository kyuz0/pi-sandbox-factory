import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pi_sandbox_factory import hosted_models as h, sandbox, inference


class HostedModelsTests(unittest.TestCase):
    def test_routing_and_secret_separation(self):
        values = [dict(provider='openrouter',key='fixture'),dict(provider='together',key='fixture'),
                  dict(provider='azure',endpoint='https://sample.services.ai.azure.com/openai/v1',key='fixture'),
                  dict(provider='amazon-bedrock',region='eu-west-1',method='iam',access_key='fixture',secret_key='fixture')]
        connections = {v['provider']:h.connection(v) for v in values}
        self.assertNotIn('fixture', json.dumps(connections))
        rules=h.destinations(connections)
        self.assertEqual(rules, [('pi.dev',443)])
        policy=sandbox.network_policy({'hosted_connections':connections},[('docs.example',443)])
        self.assertIn('docs.example',policy)
        for host in ['openrouter.ai','api.together.xyz','sample.services.ai.azure.com','bedrock-runtime.eu-west-1.amazonaws.com']:
            self.assertNotIn(host,policy)
        self.assertEqual(set(inference.routes({'hosted_connections':connections})),set(connections))

    def test_validation(self):
        invalid=[dict(provider='unknown'),dict(provider='openrouter',key='!cat secrets'),dict(provider='together',key='$KEY'),
                 dict(provider='azure',endpoint='https://user:key@azure.example'),dict(provider='azure',endpoint='http://azure.example'),
                 dict(provider='amazon-bedrock',region='eu-west-1',method='iam',access_key='alone'),
                 dict(provider='amazon-bedrock',region='bad host',method='bearer'),
                 dict(provider='amazon-bedrock',region='eu-west-1',method='iam',session_token='alone')]
        for value in invalid:
            with self.subTest(value=value),self.assertRaises(ValueError):h.validate(value)

    def test_rpc_uses_stdin_and_masks_native_error(self):
        config={'name':'fixture','engine':'podman'}
        with patch.object(sandbox,'inspect',return_value={'State':{'Running':True}}),patch.object(subprocess,'run',return_value=subprocess.CompletedProcess([],0,'{"configured":true}','')) as run:
            h.request(config,'configure',provider='openrouter',key='private-fixture')
        args=run.call_args.args[0]
        self.assertNotIn('private-fixture',str(args))
        self.assertIn('private-fixture',run.call_args.kwargs['input'])
        with patch.object(sandbox,'inspect',return_value={}),self.assertRaises(ValueError):h.request(config,'status')
        with patch.object(sandbox,'inspect',return_value={'State':{'Running':True}}),patch.object(subprocess,'run',return_value=subprocess.CompletedProcess([],1,'','secret failure')):
            with self.assertRaisesRegex(ValueError,'Could not read Pi'):h.request(config,'status')

    def test_failed_credential_import_restores_previous_routes(self):
        with tempfile.TemporaryDirectory() as temp:
            config={'name':'fixture','engine':'podman','network':'allowlist','hosted_connections':{'openrouter':{}}}
            before=copy.deepcopy(config)
            with patch.object(sandbox,'update_network') as network, patch.object(h,'request',return_value={}), \
                 patch.object(inference,'up') as up, patch.object(inference,'credentials',side_effect=ValueError('missing key')):
                with self.assertRaises(ValueError):h.save(config,temp,{'provider':'together','key':''})
            self.assertEqual(up.call_count,2)
            self.assertEqual(up.call_args.args[0],before)
            network.assert_not_called()
            self.assertEqual(config,before)
            self.assertFalse((Path(temp)/'config.json').exists())

    def test_profile_region_and_deployment_validation(self):
        config={'hosted_connections':{'amazon-bedrock':{'region':'eu-west-1'}}}
        with self.assertRaises(ValueError):h.select(config,'azure','gpt-4o')
        with self.assertRaises(ValueError):h.select(config,'amazon-bedrock','model',profile_id='arn:aws:bedrock:us-east-1:123:inference-profile/x')
        with patch.object(h,'request',return_value={'ok':True}) as request:
            h.select(config,'amazon-bedrock','model',profile_id='arn:aws:bedrock:eu-west-1:123:inference-profile/x',test=True)
            self.assertEqual(request.call_args.args[1],'test')

    def test_service_saves_and_removes_using_saved_configuration(self):
        from pi_sandbox_factory.sandbox_tui import Service
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'fixture'
            state.mkdir()
            config = {'name': 'fixture', 'engine': 'podman', 'network': 'unrestricted'}
            (state / 'config.json').write_text(json.dumps(config))
            service = Service(temp)
            with patch.object(h, 'request', return_value={'configured': True}) as request, patch.object(inference,'up'), patch.object(inference,'down'), patch.object(inference,'credentials',return_value={}) as credentials:
                service.hosted_save('fixture', {'provider': 'openrouter', 'key': 'private-fixture'})
                saved = service.config('fixture')
                self.assertEqual(saved['hosted_connections'], {'openrouter': {}})
                self.assertNotIn('private-fixture', (state / 'config.json').read_text())
                self.assertNotIn('state_path', saved)
                self.assertEqual(credentials.call_args.args[2]['credentials'],{'key':'private-fixture'})
                self.assertNotIn('private-fixture',str(request.call_args_list))
                self.assertEqual(request.call_args.kwargs['endpoint'],'http://127.0.0.1:19431/r/openrouter/api/v1')
                service.hosted_remove('fixture', 'openrouter')
                self.assertEqual(service.config('fixture')['hosted_connections'], {})
                self.assertEqual(request.call_args.args[1], 'remove')

    def test_stopped_sandbox_has_actionable_error(self):
        with patch.object(sandbox, 'inspect', return_value={'State': {'Running': False}}), patch.object(subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'Start the sandbox'):
                h.request({'name': 'fixture', 'engine': 'podman'}, 'status')
            run.assert_not_called()

    def test_plugin_key_goes_only_to_companion(self):
        from pi_sandbox_factory import model_providers
        config={'name':'test','engine':'podman','state_path':'/tmp/fixture','model_providers':[
            {'name':'company','manifest':{'inference':{'origin':'https://models.example','auth':{'type':'bearer'}}}}]}
        with patch.object(inference,'credentials') as credentials,patch.object(sandbox,'run',return_value=subprocess.CompletedProcess([],0,'{"state":"ready","message":"configured"}')) as run:
            model_providers.configure(config,provider='company',secret='private-fixture')
        self.assertEqual(credentials.call_args.args[2]['credentials'],{'key':'private-fixture'})
        self.assertNotIn('private-fixture',str(run.call_args))

    def test_failed_start_restores_previous_routes(self):
        config={'name':'fixture','engine':'podman','hosted_connections':{'openrouter':{}}}
        with tempfile.TemporaryDirectory() as temp,patch.object(h,'request',return_value={}),patch.object(inference,'up',side_effect=[ValueError('startup failed'),None]) as up:
            with self.assertRaisesRegex(ValueError,'startup failed'):h.save(config,temp,{'provider':'together','key':'fixture'})
            self.assertEqual(up.call_args.args[0],config)
