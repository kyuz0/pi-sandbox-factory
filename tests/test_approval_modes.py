import json
from pathlib import Path
import tempfile
import unittest
from pi_sandbox_factory import sandbox
from pi_sandbox_factory.sandbox_options import options, permissions, guidance

class ApprovalModeTests(unittest.TestCase):
    def test_browser_vault_guard_is_independent_of_shell_and_common_file_settings(self):
        self.assertIs(options()['protect_browser_credentials'], True)
        template = {'permission': {'path': {'*.key': 'deny', '/private/other': 'deny'}}}
        for mode in ('automatic', 'assisted', 'manual', 'off'):
            for inner in (True, False):
                for protected in (True, False):
                    selected = {'approval': mode, 'inner_sandbox': inner, 'browser': True,
                                'protect_credentials': False, 'protect_browser_credentials': protected}
                    paths = permissions(template, selected)['permission']['path']
                    for pattern in ('/home/node/.betterwright/vault', '/home/node/.betterwright/vault/*'):
                        self.assertEqual(paths.get(pattern), 'deny' if protected else None)
                    self.assertEqual(paths['/private/other'], 'deny')
                    self.assertNotIn('*.key', paths)
                    text = guidance(selected)
                    self.assertEqual('saved Betterwright credential vault' in text, protected)
        self.assertNotIn('/home/node/.betterwright/vault', template['permission']['path'])
        with self.assertRaises(ValueError):
            options({'protect_browser_credentials': 'yes'})

    def test_selected_browser_runs_without_review_but_downloads_keep_their_policy(self):
        template = {'permission': {'*': 'ask', 'browser_download': 'ask'}}
        for mode in ('automatic', 'assisted', 'manual', 'off'):
            with self.subTest(mode=mode):
                result = permissions(template, {'approval': mode, 'browser': True})
                for name in ('browser', 'browser_login', 'browser_evidence'):
                    self.assertEqual(result['permission'][name], 'allow')
                self.assertEqual(result['permission']['browser_download'], 'ask')
        self.assertNotIn('browser', permissions(template, {'browser': False})['permission'])
        self.assertNotIn('browser', template['permission'])

    def test_default_is_automatic_and_assisted_is_explicit(self):
        self.assertEqual(options()['approval'], 'automatic')
        self.assertEqual(options({'approval':'assisted'})['approval'], 'assisted')
        for mode in ('automatic','assisted','manual','off'):
            result=permissions({'permission':{}}, {'approval':mode})
            self.assertEqual(result['authorizerChain'], ['pi-auto-review'] if mode in ('automatic','assisted') else [])
            self.assertTrue(guidance({'approval':mode}))

    def test_generated_settings_match_selected_mode(self):
        source=Path(__file__).resolve().parents[1]/'pi_sandbox_factory/containers/dev'
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)
            for mode in ('automatic','assisted','manual','off'):
                sandbox.prepare_options({'common':{'path':str(source)},'options':{'approval':mode}},state)
                config=json.loads((state/'runtime-config/auto-review.json').read_text())
                self.assertEqual(config['interactionMode'],'interactive' if mode=='assisted' else 'automatic')
                self.assertEqual(config['maxTokens'],32768)
                self.assertEqual(config['reasoning'],'low')

    def test_generated_sandbox_config_matches_credential_file_protection_choice(self):
        source=Path(__file__).resolve().parents[1]/'pi_sandbox_factory/containers/dev'
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)
            for protected in (True, False):
                sandbox.prepare_options({
                    'common':{'path':str(source)},
                    'options':{'protect_credentials':protected},
                },state)
                config=json.loads((state/'runtime-config/sandbox.json').read_text())
                self.assertIs(config['filesystem']['protectCommonCredentialFiles'],protected)
