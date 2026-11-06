import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pi_sandbox_factory import communications, sandbox
from pi_sandbox_factory.sandbox_options import options

helper = Path(sandbox.ROOT)/'containers/dev/communications-config.py'
spec = importlib.util.spec_from_file_location('communication_keys', helper)
keys = importlib.util.module_from_spec(spec)
spec.loader.exec_module(keys)


class CommunicationsTests(unittest.TestCase):
    def test_settings_network_and_approval(self):
        self.assertEqual(communications.settings(), {'slack': False})
        for value in ({'telegram': True}, {'slack': 'yes'}, []):
            with self.assertRaises(ValueError): communications.settings(value)
        enabled = options({'communications': {'slack': True}})
        text = sandbox.network_policy({'options': enabled}, [])
        self.assertIn('slack.com', text)
        self.assertIn('files.slack.com', text)
        self.assertNotIn('slack.com', sandbox.network_policy({}, []))
        self.assertNotIn('http_access allow all', text)

    def test_private_keys_keep_replace_remove_and_permissions(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self.assertEqual(keys.update(home), {'botToken': False, 'userToken': False})
            keys.update(home, {'botToken': 'xoxb-fixture', 'userToken': 'xoxp-fixture'})
            keys.update(home, {'userToken': ''})
            path = keys.credentials_path(home)
            self.assertEqual(json.loads(path.read_text()), {'botToken': 'xoxb-fixture', 'userToken': ''})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            for value in ({'botToken':'wrong'}, {'userToken':None}, {'botToken':'xoxb-hello\nworld'}, {'unknown':''}):
                with self.assertRaises(ValueError): keys.update(home, value)
            self.assertEqual(keys.update(home), {'botToken': True, 'userToken': False})
            target=home/'outside'; target.write_text('unchanged'); path.unlink(); path.symlink_to(target)
            with self.assertRaises(ValueError): keys.update(home, {'botToken':''})
            self.assertEqual(target.read_text(), 'unchanged')

    def test_credentials_do_not_enter_options_or_copies(self):
        with self.assertRaises(ValueError): options({'communications': {'slack': True, 'botToken':'secret'}})
        from pi_sandbox_factory.sandbox_tui import copy_draft
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp); (state/'source').mkdir(); (state/'source/allowlist.txt').write_text('slack.com:443')
            config={'profile':{'path':'base'}, 'options':options({'communications':{'slack':True}}),
                    '_communication_keys': {'botToken':'secret'}}
            copied=copy_draft({'name':'source','config':config}, state)
            self.assertTrue(copied['options']['communications']['slack'])
            self.assertNotIn('secret', json.dumps(copied))

    def test_legacy_environment_cannot_expose_slack_tokens(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'credentials.env'
            for name in ('SLACK_BOT_TOKEN','SLACK_USER_TOKEN','SLACK_CREDENTIALS_FILE'):
                path.write_text(name+'=fixture\n')
                with self.assertRaisesRegex(ValueError, 'Communications'):
                    sandbox.validate_env(path)
