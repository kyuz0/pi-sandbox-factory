import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pi_sandbox_factory import git_settings, sandbox
from pi_sandbox_factory.sandbox_options import options


class GitIdentityTests(unittest.TestCase):
    def test_optional_identity_validates_without_synthesizing_a_user(self):
        self.assertIsNone(options()['git_identity'])
        self.assertEqual(options({'git_identity': {'name': ' Developer ', 'email': 'dev@example.test'}})['git_identity']['name'], 'Developer')
        for value in ({}, {'name': '', 'email': 'dev@example.test'}, {'name': 'A\nB', 'email': 'a@b'},
                      {'name': 'A <B>', 'email': 'a@b'}, {'name': 'A', 'email': 'a b@c'},
                      {'name': 'A', 'email': 'a\0@b'}, {'name': 'A', 'email': 'missing'},
                      {'name': True, 'email': 'a@b'}, {'name': 'A', 'email': 'a@b', 'sign': True},
                      {'name': ',;"\'', 'email': 'a@b'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                options({'git_identity': value})

    def test_ssh_form_saves_only_the_identity_option_and_keeps_other_choices(self):
        from pi_sandbox_factory.sandbox_tui import Service
        service = Service(Path('/tmp/unused-factory-state'))
        value = {'name': 'Fixture Author', 'email': 'fixture@example.test'}
        saved = []
        def run(args, log):
            saved.append(json.loads(Path(args[-1]).read_text()))
        with patch.object(service, 'config', return_value={'options': {'browser': True, 'approval': 'manual'}}), \
                patch.object(service, 'run', side_effect=run):
            service.ssh_settings('demo', {'hosts': []}, lambda text: None, value)
            service.ssh_settings('demo', {'hosts': []}, lambda text: None, None)
        self.assertEqual(saved[0]['options']['git_identity'], value)
        self.assertTrue(saved[0]['options']['browser'])
        self.assertEqual(saved[0]['options']['approval'], 'manual')
        self.assertIsNone(saved[1]['options']['git_identity'])

    def test_rendered_git_config_quotes_name_and_email_as_data(self):
        value = {'name': 'Déveloper "Example"; # \\ team', 'email': 'dev@example.test'}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'identity.gitconfig'
            path.write_text(git_settings.config(value))
            for key in ('name', 'email'):
                result = subprocess.check_output(['git', 'config', '--file', str(path), 'user.' + key], text=True).strip()
                self.assertEqual(result, value[key])
            path.write_text(git_settings.config(None))
            self.assertEqual(subprocess.run(['git', 'config', '--file', str(path), '--get', 'user.name'], capture_output=True).returncode, 1)

    def test_saved_options_generate_the_readonly_identity_file(self):
        source = sandbox.ROOT / 'containers/dev'
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            config = {'common': {'path': str(source)}, 'options': {'git_identity': {'name': 'Developer', 'email': 'dev@example.test'}}}
            sandbox.prepare_options(config, state)
            self.assertEqual(json.loads((state / 'options.json').read_text())['git_identity']['name'], 'Developer')
            self.assertIn('dev@example.test', (state / 'git-identity.gitconfig').read_text())
            config['options']['git_identity'] = None
            sandbox.prepare_options(config, state)
            self.assertNotIn('user', (state / 'git-identity.gitconfig').read_text())
