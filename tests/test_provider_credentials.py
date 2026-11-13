"""Provider credentials are collected separately and saved before discovery."""
import copy
import io
import json
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pi_sandbox_factory import browser_editor, inference, model_providers, sandbox
from pi_sandbox_factory.sandbox_tui import DEFAULT_SETTINGS, Service, preset


class ProviderCredentialsTests(unittest.TestCase):
    def config(self):
        return {'name': 'demo', 'engine': 'podman',
                'model_providers': [{'name': 'company', 'manifest': {'inference': {
                    'origin': 'https://models.example.com', 'auth': {'type': 'bearer'}}}}]}

    def test_missing_key_does_not_block_model_initialization_or_run_adapter(self):
        for action in ('refresh', 'preview', 'status'):
            with self.subTest(action=action), \
                 patch.object(inference, 'credentials', return_value={'configured': []}) as credentials, \
                 patch.object(sandbox, 'run') as run, redirect_stdout(io.StringIO()) as output:
                if action == 'refresh':
                    sandbox.initialize_models(self.config(), Path('/tmp/fixture'))
                else:
                    model_providers.configure(self.config(), Path('/tmp/fixture'), action)
                run.assert_not_called()
                credentials.assert_called_once_with(self.config(), Path('/tmp/fixture'), {'status': True})
                self.assertIn('company: needs-auth', output.getvalue())
                self.assertIn('Settings → Models', output.getvalue())

    def test_configured_key_still_runs_discovery_and_preserves_errors(self):
        with patch.object(inference, 'credentials', return_value={'configured': ['company']}), \
             patch.object(sandbox, 'run', return_value=subprocess.CompletedProcess(
                 [], 0, '{"state":"error","message":"Discovery unavailable"}')) as run:
            with self.assertRaisesRegex(ValueError, 'Discovery unavailable'):
                model_providers.configure(self.config(), Path('/tmp/fixture'))
            self.assertEqual(json.loads(run.call_args.kwargs['input']), {'id': 'company', 'action': 'refresh'})

    def test_saved_config_launches_and_discovery_use_explicit_state_directory(self):
        commands = (['open', 'demo', '--editor', 'browser'],
                    ['browser-editor', 'demo', '--background', '--no-open'],
                    ['open', 'demo', '--editor', 'pi'],
                    ['open', 'demo', '--editor', 'desktop'],
                    ['pi', 'demo', '--', '--continue'],
                    ['configure', 'demo'], ['configure', 'demo', '--preview'],
                    ['configure', 'demo', '--status'],
                    ['create', 'demo', '--workspace', '/workspace', '--start'],
                    ['create', 'demo', '--workspace', '/workspace', '--start', '--open'])
        for command in commands:
            for configured in (False, True):
                with self.subTest(command=command, configured=configured), tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
                    state = Path(tmp) / 'demo'
                    state.mkdir()
                    config = self.config()
                    config['workspace'] = tmp
                    config['options'] = {'browser': False}
                    saved = json.dumps(config)
                    (state / 'config.json').write_text(saved)
                    stack.enter_context(patch('sys.argv', ['pi-sandbox-factory', '--state-dir', tmp, *command]))
                    for name in ('create', 'build', 'up'):
                        stack.enter_context(patch.object(sandbox, name))
                    stack.enter_context(patch.object(sandbox, 'inspect', return_value={
                        'State': {'Running': True}, 'Id': 'a' * 64}))
                    stack.enter_context(patch('shutil.which', return_value='/usr/bin/code'))
                    stack.enter_context(patch.object(browser_editor.host_platform, 'check_engine'))
                    stack.enter_context(patch.object(browser_editor.subprocess, 'check_output',
                        side_effect=lambda args, **kw: 'true' if args[1] == 'info' else 'x86_64'))
                    stack.enter_context(patch.object(browser_editor.subprocess, 'run',
                        return_value=subprocess.CompletedProcess([], 0)))
                    background = stack.enter_context(patch.object(browser_editor, 'start_background'))
                    credentials = stack.enter_context(patch.object(inference, 'credentials',
                        return_value={'configured': ['company'] if configured else []}))
                    run = stack.enter_context(patch.object(sandbox, 'run', return_value=
                        subprocess.CompletedProcess([], 0, '{"state":"ready","message":"Connected"}')))
                    stack.enter_context(redirect_stdout(io.StringIO()))
                    sandbox.main()
                    credentials.assert_called_once_with(config, state, {'status': True})
                    adapter_calls = [c for c in run.call_args_list if '/opt/sandbox/provider-runner.mjs' in c.args[0]]
                    self.assertEqual(len(adapter_calls), int(configured))
                    if configured:
                        action = 'status' if '--status' in command else 'preview' if '--preview' in command else 'refresh'
                        self.assertEqual(json.loads(adapter_calls[0].kwargs['input']), {'id': 'company', 'action': action})
                    if 'browser' in command or command[0] == 'browser-editor' or '--open' in command:
                        background.assert_called_once()
                    self.assertEqual((state / 'config.json').read_text(), saved)

    def test_editor_discovery_error_prevents_launch_without_changing_saved_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            config = self.config()
            before = copy.deepcopy(config)
            with patch.object(sandbox, 'up'), \
                 patch.object(inference, 'credentials', return_value={'configured': ['company']}), \
                 patch.object(sandbox, 'run', return_value=subprocess.CompletedProcess(
                     [], 0, '{"state":"error","message":"Discovery unavailable"}')) as run:
                with self.assertRaisesRegex(ValueError, 'Discovery unavailable'):
                    sandbox.open_selected(config, state, 'pi')
                self.assertEqual(run.call_count, 1)
            self.assertEqual(config, before)

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
