"""Host sign-in import uses a narrow payload and never shares host storage."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pi_sandbox_factory import advisor_credentials as auth
from pi_sandbox_factory.sandbox_tui import Service, preset, DEFAULT_SETTINGS

class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, CODEX_HOME=str(self.root), CLAUDE_CONFIG_DIR=str(self.root))
        env.start(); self.addCleanup(env.stop)
        self.config = dict(name='test', engine='podman', advisors={'providers': list(auth.LABELS)})

    def test_file_imports_only_sign_in_fields(self):
        for provider, filename, value, expected in [
            ('codex', 'auth.json', {'tokens': {'access_token': 'synthetic'}, 'OPENAI_API_KEY': 'not-copied', 'auth_mode': 'chatgpt'}, {'tokens','auth_mode'}),
            ('claude', '.credentials.json', {'claudeAiOauth': {'accessToken':'synthetic'}, 'other':'not-copied'}, {'claudeAiOauth'}),
        ]:
            (self.root/filename).write_text(json.dumps(value))
            payload = auth.read_host(provider)
            self.assertEqual(set(json.loads(payload)), expected)
            self.assertNotIn('not-copied', payload)

    def test_missing_or_invalid_login_has_actionable_error(self):
        for value in [None, 'not-json', '[]', '{}', '{"OPENAI_API_KEY":"secret"}']:
            if value is not None: (self.root/'auth.json').write_text(value)
            with self.assertRaises(ValueError) as error: auth.read_host('codex')
            self.assertNotIn('secret', str(error.exception))

    @patch("platform.system", return_value="Linux")
    def test_antigravity_reads_only_its_keyring_entry(self, _system):
        with patch.object(auth.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='{"token":"synthetic"}')) as run:
            self.assertEqual(json.loads(auth.read_host('agy')), {'token':'synthetic'})
            self.assertEqual(run.call_args.args[0], ['secret-tool','lookup','service','gemini','username','antigravity'])
        with patch.object(auth.subprocess, 'run', side_effect=FileNotFoundError):
            with self.assertRaisesRegex(ValueError, 'sign-in button'): auth.read_host('agy')

    @patch.object(auth.host_platform, 'is_mac', return_value=True)
    def test_mac_keychain_logins_offer_container_sign_in(self, _mac):
        for provider in ('claude', 'agy'):
            with self.subTest(provider=provider):
                with self.assertRaisesRegex(ValueError, 'sign-in button'):
                    auth.read_host(provider)

    def test_disabled_provider_cannot_read_host_credentials(self):
        self.config['advisors']['providers'] = []
        with patch.object(auth, 'read_host') as read:
            with self.assertRaises(ValueError): auth.import_from_host(self.config, self.root, 'codex')
            read.assert_not_called()

    def test_payload_uses_stdin_and_never_command_arguments(self):
        for provider in auth.LABELS:
            with patch.object(auth, 'read_host', return_value='synthetic-secret'), \
                 patch.object(auth.sandbox_advisors, 'up') as up, \
                 patch.object(auth.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
                auth.import_from_host(self.config, self.root, provider)
                up.assert_called_once_with(self.config, self.root)
                self.assertEqual(run.call_args.kwargs['input'], 'synthetic-secret')
                self.assertNotIn('synthetic-secret', ' '.join(run.call_args.args[0]))
                self.assertNotIn('-v', run.call_args.args[0])

    def test_failed_container_write_does_not_disclose_stderr(self):
        with patch.object(auth, 'read_host', return_value='synthetic-secret'), \
             patch.object(auth.sandbox_advisors, 'up'), \
             patch.object(auth.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stderr='synthetic-secret')):
            with self.assertRaises(ValueError) as error: auth.import_from_host(self.config, self.root, 'codex')
            self.assertNotIn('synthetic-secret', str(error.exception))

    def test_file_writer_replaces_atomically_with_private_permissions(self):
        target = self.root/'private/auth.json'
        for payload in ['first', 'replacement']:
            subprocess.run([sys.executable, '-c', auth._WRITE_FILE, str(target)], input=payload, text=True, check=True)
            self.assertEqual(target.read_text(), payload)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode), 0o700)
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_creation_copies_only_explicitly_selected_sign_ins_after_start(self):
        service=Service(self.root)
        draft=preset('base', DEFAULT_SETTINGS)
        draft.update(name='demo', workspace='/workspace', profile='base', open_editor=False,
                     advisors={'providers':['codex','claude']}, _advisor_imports=['claude'])
        calls=[]
        with patch.object(service,'run',side_effect=lambda args,log:calls.append(args)), patch.object(service,'setup'):
            service.create(draft,'',lambda text:None)
        self.assertEqual([c[0] for c in calls], ['create','build','up','advisor-import'])
        self.assertEqual(calls[-1], ['advisor-import','demo','claude'])
