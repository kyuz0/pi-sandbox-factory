import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import sandbox
import sandbox_advisors as advisors

class AdvisorTests(unittest.TestCase):
    def test_disabled_has_no_mount_or_provider_requirement(self):
        self.assertEqual(advisors.mounts({'name':'test'}), [])
        self.assertEqual(advisors.validate({}), {'providers':[]})

    def test_enable_before_antigravity_login(self):
        settings=advisors.validate({'providers':['agy']})
        provider=advisors.provider_config(settings)['providers']['agy']
        self.assertTrue(provider['setupOnly'])
        self.assertEqual(provider['models'], {})

    def test_explicit_gemini_model_and_quota_group(self):
        settings=advisors.validate({'providers':['agy'], 'agy_model':'gemini-test-high', 'agy_quota_group':'Gemini', 'agy_effort':'high'})
        self.assertEqual(advisors.provider_config(settings)['providers']['agy']['models']['default']['id'], 'gemini-test-high')
        with self.assertRaises(ValueError):advisors.validate({'providers':['agy'],'agy_model':'gemini-test'})

    def test_only_selected_providers_and_subscription_auth(self):
        config=advisors.provider_config(advisors.validate({'providers':['codex']}))
        self.assertEqual(set(config['providers']), {'codex'})
        self.assertEqual(config['billingMode'], 'subscription')
        self.assertTrue(config['providers']['codex']['sharedHome'])
        for providers in [['other'],['codex','codex'],['codex',{}]]:
            with self.assertRaises(ValueError):advisors.validate({'providers':providers})

    def test_rpc_mount_contains_no_credentials_or_container_engine(self):
        config={'name':'test','advisors':{'providers':['codex']}}
        args=advisors.mounts(config)
        self.assertIn('local-ai-sandbox-test-advisor-socket:/run/advisor:ro',args)
        self.assertFalse(any(x in ' '.join(args) for x in ['-home:', 'docker.sock', 'podman.sock']))

    def test_separate_network_rules_do_not_include_model_or_package_hosts(self):
        rules=advisors.rules({'providers':['codex']})
        self.assertIn(('auth.openai.com',443),rules)
        self.assertNotIn(('local-model.internal',8000),rules)
        self.assertNotIn(('pypi.org',443),rules)

    def test_volume_ownership_failure_precedes_mutation(self):
        calls=[]
        def run(args,**kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=0,stdout=json.dumps([{'Labels':{sandbox.LABEL:'someone-else'}}]))
        with patch.object(sandbox,'inspect',return_value=None),patch.object(sandbox,'run',side_effect=run):
            with self.assertRaisesRegex(ValueError,'unrelated'):advisors.down({'engine':'podman','name':'test'},remove=True)
        self.assertTrue(all('inspect' in c for c in calls))

    def test_invalid_limits_and_hosts(self):
        for value in [0,-1,True,'10']:
            with self.assertRaises(ValueError):advisors.validate({'max_calls':value})
        for host in ['*.example.com:443','https://example.com',None]:
            with self.assertRaises(ValueError):advisors.validate({'extra_hosts':host})
