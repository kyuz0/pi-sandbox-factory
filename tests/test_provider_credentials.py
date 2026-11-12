"""Provider credentials are collected separately and saved before discovery."""
import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pi_sandbox_factory import inference, model_providers, sandbox
from pi_sandbox_factory.sandbox_tui import DEFAULT_SETTINGS, Service, preset


class ProviderCredentialsTests(unittest.TestCase):
    def config(self):
        return {'name': 'demo', 'engine': 'podman', 'state_path': '/tmp/fixture',
                'model_providers': [{'name': 'company', 'manifest': {'inference': {
                    'origin': 'https://models.example.com', 'auth': {'type': 'bearer'}}}}]}

    def test_missing_key_does_not_block_model_initialization_or_run_adapter(self):
        for action in ('refresh', 'preview', 'status'):
            with self.subTest(action=action), \
                 patch.object(inference, 'credentials', return_value={'configured': []}) as credentials, \
                 patch.object(sandbox, 'run') as run, redirect_stdout(io.StringIO()) as output:
                if action == 'refresh':
                    sandbox.initialize_models(self.config())
                else:
                    model_providers.configure(self.config(), action)
                run.assert_not_called()
                credentials.assert_called_once_with(self.config(), Path('/tmp/fixture'), {'status': True})
                self.assertIn('company: needs-auth', output.getvalue())
                self.assertIn('Settings → Models', output.getvalue())

    def test_configured_key_still_runs_discovery_and_preserves_errors(self):
        with patch.object(inference, 'credentials', return_value={'configured': ['company']}), \
             patch.object(sandbox, 'run', return_value=subprocess.CompletedProcess(
                 [], 0, '{"state":"error","message":"Discovery unavailable"}')) as run:
            with self.assertRaisesRegex(ValueError, 'Discovery unavailable'):
                model_providers.configure(self.config())
            self.assertEqual(json.loads(run.call_args.kwargs['input']), {'id': 'company', 'action': 'refresh'})

    def test_creation_keeps_keys_out_of_files_and_imports_before_discovery(self):
        for open_editor in (False, True):
            with self.subTest(open_editor=open_editor), tempfile.TemporaryDirectory() as tmp:
                service = Service(tmp)
                draft = preset('base', copy.deepcopy(DEFAULT_SETTINGS))
                draft.update(name='demo', workspace='/workspace', open_editor=open_editor,
                             model_providers={'company': {}}, _provider_keys={'company': 'synthetic-secret'})
                calls = []
                def run(args, log):
                    calls.append(args[0])
                    if args[0] == 'create':
                        for flag in ('--providers-file', '--options-file', '--folders-file'):
                            self.assertNotIn('synthetic-secret', Path(args[args.index(flag) + 1]).read_text())
                def provider(name, provider, action, key, log):
                    self.assertEqual(calls[-1], 'up')
                    self.assertEqual((name, provider, action, key), ('demo', 'company', 'refresh', 'synthetic-secret'))
                    calls.append('credential')
                output = []
                with patch.object(service, 'run', side_effect=run), patch.object(service, 'provider', side_effect=provider):
                    service.create(draft, None, output.append)
                self.assertEqual(calls, ['create', 'build', 'up', 'credential'] + ([] if open_editor else ['configure']))
                self.assertNotIn('synthetic-secret', str(output))
                for file in Path(tmp).rglob('*.json'):
                    self.assertNotIn('synthetic-secret', file.read_text())
