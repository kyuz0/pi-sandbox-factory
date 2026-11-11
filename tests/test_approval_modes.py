import json
from pathlib import Path
import tempfile
import unittest
from pi_sandbox_factory import sandbox
from pi_sandbox_factory.sandbox_options import options, permissions, guidance

class ApprovalModeTests(unittest.TestCase):
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
