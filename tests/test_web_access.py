import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pi_sandbox_factory import network_groups as groups, web_access, sandbox
from pi_sandbox_factory.sandbox_options import options


class WebAccessTests(unittest.TestCase):
    def test_service_permissions_follow_selection(self):
        exa = {'enabled': True}
        self.assertEqual(web_access.destinations(exa), [('mcp.exa.ai', 443), ('api.exa.ai', 443)])
        self.assertEqual(web_access.destinations({'enabled': True, 'service': 'exa-api'}), web_access.destinations(exa))
        config = web_access.extension_config(exa)
        self.assertEqual(config['webSearch']['allowedProviders'], ['exa'])
        self.assertEqual(config['fetchRouting']['providers'], ['http'])
        self.assertFalse(config['fetchRouting']['allowRemoteHostedProviders'])
        self.assertTrue(config['lockProxy'])
        self.assertEqual(config['proxy'], 'http://127.0.0.1:3128')
        self.assertNotIn('proxy', web_access.extension_config(exa, False))
        self.assertEqual(web_access.destinations({'enabled': False}), [])
        self.assertEqual(web_access.destinations({'enabled': True, 'service': 'searxng', 'endpoint': 'https://search.example.net:8443'}), [('search.example.net', 8443)])

    def test_auto_default_and_legacy_single_provider_migration(self):
        self.assertEqual(web_access.settings({'enabled': True})['mode'], 'auto')
        for name in ('exa', 'exa-api', 'openai', 'brave', 'tavily'):
            value = web_access.settings({'enabled': True, 'service': name})
            expected = 'exa' if name == 'exa-api' else name
            self.assertEqual(value['mode'], expected)
            self.assertEqual(list(value['providers']), [expected])
        with self.assertRaises(ValueError):
            web_access.settings({'mode': 'brave', 'providers': {'exa': {}}})

    def test_only_and_auto_project_eligible_providers_and_endpoints(self):
        value = {'enabled': True, 'mode': 'auto', 'providers': {
            'exa': {}, 'brave': {'has_key': True}, 'tavily': {},
            'openai': {'has_key': True, 'endpoint': 'https://search.example.com/v1/responses', 'model': 'search-model'},
            'searxng': {'endpoint': 'https://searx.example.com'}}}
        config = web_access.extension_config(value)
        self.assertEqual(config['provider'], 'auto')
        self.assertEqual(config['webSearch']['allowedProviders'], ['exa', 'brave', 'openai', 'searxng'])
        self.assertNotIn('searchRouting', config)
        self.assertEqual(config['openaiSearchModel'], 'search-model')
        self.assertNotIn(('api.tavily.com', 443), web_access.destinations(value))
        value['mode'] = 'brave'
        config = web_access.extension_config(value)
        self.assertEqual(config['webSearch']['allowedProviders'], ['brave'])
        self.assertNotIn('openaiResponsesUrl', config)
        self.assertEqual(web_access.destinations(value), [('api.search.brave.com', 443)])

    def test_private_keys_migrate_and_project_only_active_credentials(self):
        import runpy
        runtime_code = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'pi_sandbox_factory/containers/dev/web-access-config.py'))
        configure, identity = runtime_code['configure'], runtime_code['identity']
        with tempfile.TemporaryDirectory() as temp:
            agent = Path(temp) / 'agent'; agent.mkdir()
            runtime = Path(temp) / 'runtime'; runtime.mkdir()
            value = web_access.settings({'enabled': True, 'providers': {'exa': {'has_key': True}, 'brave': {'has_key': True},
                'openai': {'endpoint': 'https://search.example.com/v1/responses', 'has_key': True}}})
            def save():
                (runtime / 'web-providers.json').write_text(json.dumps(value))
                (runtime / 'web-search.json').write_text(json.dumps(web_access.extension_config(value)))
            save()
            # Existing keyed Exa survives the merged Exa option and old marker format.
            (agent / 'sandbox-web-keys.json').write_text(json.dumps({identity('exa-api', {}): 'old-exa'}))
            (agent / 'sandbox-web-config.json').write_text('old-fingerprint')
            statuses = configure(agent, runtime, {'brave': '!literal-key', 'openai': 'openai-test-key'})
            self.assertTrue(all(statuses.values()))
            config = json.loads((agent / 'web-search.json').read_text())
            self.assertEqual(config['exaApiKey'], 'old-exa')
            self.assertEqual(config['braveApiKey'], '$!literal-key')
            self.assertEqual(config['webSearch']['allowedProviders'], ['exa', 'brave', 'openai'])
            self.assertEqual((agent / 'sandbox-web-keys.json').stat().st_mode & 0o777, 0o600)
            value['mode'] = 'brave'; save(); configure(agent, runtime)
            config = json.loads((agent / 'web-search.json').read_text())
            self.assertEqual(config['webSearch']['allowedProviders'], ['brave'])
            self.assertNotIn('exaApiKey', config)
            self.assertNotIn('openaiApiKey', config)
            value['mode'] = 'auto'; save()
            configure(agent, runtime, {'brave': ''})
            config = json.loads((agent / 'web-search.json').read_text())
            self.assertEqual(config['webSearch']['allowedProviders'], ['exa', 'openai'])
            # A key for one custom endpoint must not be sent to its replacement.
            value['providers']['openai']['endpoint'] = 'https://other.example.com/v1/responses'
            save(); configure(agent, runtime)
            config = json.loads((agent / 'web-search.json').read_text())
            self.assertEqual(config['webSearch']['allowedProviders'], ['exa'])
            self.assertNotIn('openaiApiKey', config)
            value['enabled'] = False; save()
            configure(agent, runtime, {'brave': 'saved-for-later'})
            self.assertEqual(json.loads((agent / 'web-search.json').read_text())['webSearch']['allowedProviders'], [])
            with self.assertRaises(ValueError):
                configure(agent, runtime, {'unknown': 'key'})

    def test_reusable_keys_are_private_and_bound_to_endpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'web-access-keys.json'
            value = {'enabled': True, 'mode': 'auto', 'providers': {'exa': {}, 'brave': {},
                'openai': {'endpoint': 'https://search.example.com/responses'}}}
            value = web_access.save_keys(path, value, {'exa': 'fake-exa', 'brave': 'fake-brave', 'openai': 'fake-openai'})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn('fake-exa', json.dumps(value))
            self.assertEqual(web_access.saved_keys(path, value), {'exa': 'fake-exa', 'brave': 'fake-brave', 'openai': 'fake-openai'})
            value['providers']['openai']['endpoint'] = 'https://different.example.com/responses'
            self.assertNotIn('openai', web_access.saved_keys(path, value))
            value = web_access.save_keys(path, value, {'exa': 'replacement-exa'})
            self.assertFalse(value['providers']['brave']['has_key'])
            self.assertEqual(web_access.saved_keys(path, value), {'exa': 'replacement-exa'})

    def test_default_settings_failure_restores_saved_keys(self):
        from pi_sandbox_factory import sandbox_tui
        from pi_sandbox_factory.sandbox_options import write_json
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'cockpit.json'
            keyfile = path.with_name('web-access-keys.json')
            old = web_access.save_keys(keyfile, {'providers': {'exa': {}}}, {'exa': 'old-key'})
            original = keyfile.read_bytes()
            def fail_settings(target, value):
                if target == path:
                    raise OSError('Settings write failed')
                write_json(target, value)
            with patch.object(sandbox_tui, 'defaults_path', return_value=path), patch.object(sandbox_tui, 'write_json', side_effect=fail_settings):
                with self.assertRaises(OSError):
                    sandbox_tui.save_defaults_with_search(dict(sandbox_tui.DEFAULT_SETTINGS), old, {'exa': 'new-key'})
            self.assertEqual(keyfile.read_bytes(), original)
            keyfile.chmod(0o644)
            with self.assertRaises(ValueError):
                web_access.saved_keys(keyfile, old)

    def test_key_update_does_not_reactivate_a_stored_unused_key(self):
        value = {'enabled': True, 'providers': {'exa': {}, 'brave': {}, 'tavily': {'has_key': True}}}
        updated = web_access.update_key_status(value, {'exa': True, 'brave': True, 'tavily': False}, {'brave': 'new-key'})
        self.assertFalse(updated['providers']['exa']['has_key'])
        self.assertTrue(updated['providers']['brave']['has_key'])
        self.assertFalse(updated['providers']['tavily']['has_key'])

    def test_search_and_fetch_have_separate_permission_rules(self):
        policy = json.loads((Path(__file__).resolve().parents[1] /
            'pi_sandbox_factory/containers/dev/security/config/permissions.json').read_text())['permission']
        self.assertEqual(policy['web_search'], 'allow')
        self.assertEqual(policy['get_search_content'], 'allow')
        self.assertEqual(policy['fetch_content'], 'ask')
        self.assertEqual(policy['*'], 'ask')

    def test_reject_invalid_service_settings(self):
        for setting in ({'enabled': 'yes'}, {'service': 'invalid'}, {'providers': {'unknown': {}}},
                        {'endpoint': 'https://u:p@example.com'}, {'endpoint': 'https://example.com?a=1'},
                        {'service': 'openai', 'endpoint': 'https://example.com:99999'}):
            with self.assertRaises(ValueError):
                web_access.settings(setting)

    def test_category_selection_defaults_and_validation(self):
        self.assertFalse(options()['web_access']['enabled'])
        self.assertEqual(options()['website_groups'], [])
        self.assertEqual(options({'website_groups': ['dev-huggingface']})['website_groups'],
                         ['dev-huggingface'])
        self.assertEqual(groups.catalog()['dev-huggingface']['domains'],
                         ['.hf.co', '.hf.space', '.huggingface.co'])
        with self.assertRaises(ValueError):
            options({'website_groups': ['unknown']})
        with self.assertRaises(ValueError):
            options({'website_groups': ['dev-python', 'dev-python']})

    def test_updates_automatically_and_falls_back_offline(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(groups, 'fetch', return_value='python.org\nfull:docs.example.net\n'), patch.object(groups.time, 'time', return_value=100000):
                first = groups.snapshots(['dev-python'], cache=temp)
            self.assertEqual(first['dev-python']['domains'], ['.python.org', 'docs.example.net'])
            with patch.object(groups, 'fetch', side_effect=AssertionError('daily cache ignored')), patch.object(groups.time, 'time', return_value=100001):
                self.assertEqual(groups.snapshots(['dev-python'], cache=temp), first)
            with patch.object(groups, 'fetch', return_value='python.org\nnew.example.org\n'), patch.object(groups.time, 'time', return_value=200000):
                second = groups.snapshots(['dev-python'], cache=temp)
            self.assertIn('.new.example.org', second['dev-python']['domains'])
            warnings = []
            with patch.object(groups, 'fetch', side_effect=OSError('offline')), patch.object(groups.time, 'time', return_value=300000):
                self.assertEqual(groups.snapshots(['dev-python'], cache=temp, warn=warnings.append), second)
            self.assertIn('using the last available list', warnings[0])
            self.assertEqual(groups.snapshots([], cache=temp), {})

    def test_category_refresh_avoids_restart_when_membership_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            old = {'dev-python': {'domains': ['.python.org'], 'checked_at': 1}}
            new = {'dev-python': {'domains': ['.python.org'], 'checked_at': 2}}
            config = {'name': 'test', 'engine': 'podman', 'network': 'allowlist',
                      'options': {'website_groups': ['dev-python']}, 'website_groups': old}
            (state / 'allowlist.txt').write_text('')
            policy = sandbox.network_policy(config, [])
            (state / 'squid.conf').write_text(policy)
            with patch.object(groups, 'snapshots', return_value=new), \
                 patch.object(sandbox, 'inspect', return_value={'State': {'Running': True}}), \
                 patch.object(sandbox, 'restart_existing') as restart:
                updated = sandbox.update_network(config, state, '')
                restart.assert_not_called()
                self.assertEqual(updated['website_groups'], new)
                self.assertEqual((state / 'squid.conf').read_text(), policy)

    def test_category_refresh_rolls_back_when_gateway_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            old = {'dev-python': {'domains': ['.python.org']}}
            new = {'dev-python': {'domains': ['.python.org', '.example.org']}}
            config = {'name': 'test', 'engine': 'podman', 'network': 'allowlist',
                      'options': {'website_groups': ['dev-python']}, 'website_groups': old}
            (state / 'allowlist.txt').write_text('')
            policy = sandbox.network_policy(config, [])
            (state / 'squid.conf').write_text(policy)
            sandbox.write_json(state / 'config.json', config)
            with patch.object(groups, 'snapshots', return_value=new), \
                 patch.object(sandbox, 'inspect', return_value={'State': {'Running': True}}), \
                 patch.object(sandbox, 'restart_existing') as restart, \
                 patch.object(sandbox, 'ensure_gateway', side_effect=[RuntimeError('gateway failed'), None]):
                with self.assertRaisesRegex(RuntimeError, 'gateway failed'):
                    sandbox.update_network(config, state, '')
                self.assertEqual(restart.call_count, 2)
            self.assertEqual((state / 'squid.conf').read_text(), policy)
            self.assertEqual(json.loads((state / 'config.json').read_text()), config)

    def test_unwritable_cache_keeps_downloaded_or_saved_categories_usable(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / 'file'
            cache.write_text('not a directory')
            warnings = []
            with patch.object(groups, 'fetch', return_value='new.example.org'):
                downloaded = groups.snapshots(['dev-python'], cache=cache, warn=warnings.append)
            self.assertEqual(downloaded['dev-python']['domains'], ['.new.example.org'])
            self.assertIn('Could not cache', warnings[0])
            with patch.object(groups, 'fetch', side_effect=OSError('offline')):
                saved = groups.snapshots(['dev-python'], downloaded, cache=cache, warn=warnings.append)
            self.assertEqual(saved, downloaded)

    def test_recursive_v2fly_and_exact_hosts(self):
        source = {'python': 'include:shared\nfull:exact.example.org\nexample.net @ads\n', 'shared': 'domain:python.org\n'}
        self.assertEqual(groups.expand_v2fly('python', source.__getitem__), ['.python.org', 'exact.example.org', '.example.net'])
        for text in ('include:python', 'regexp:.*', 'include:shared @foo'):
            with self.assertRaises(ValueError):
                groups.expand_v2fly('python', lambda _: text)

    def test_policy_preserves_explicit_ports_and_does_not_grant_unknown_sites(self):
        category = {'python': {'domains': ['.python.org', '.docs.python.org', 'python.org']}}
        policy = sandbox.squid_config([('local-model.internal', 8000)], category)
        self.assertEqual(groups.collapse(category), ['.python.org'])
        self.assertIn('http_access deny !sandbox_hosts !category_hosts', policy)
        self.assertLess(policy.index('http_access allow host_0 port_0'), policy.index('http_access deny category_hosts category_private'))
        self.assertIn('http_access allow category_hosts category_https category_connect', policy)
        self.assertTrue(policy.endswith('http_access deny all\n'))
        self.assertNotIn('category_hosts', sandbox.squid_config([('local-model.internal', 8000)]))
        for invalid in ('.127.0.0.1', '.com', 'a\nallow all', '.bad..org'):
            with self.assertRaises(ValueError):
                groups.domain(invalid)

    def test_search_grants_are_derived_and_removable(self):
        config = {'options': {'web_access': {'enabled': True}}}
        self.assertIn('mcp.exa.ai', sandbox.network_policy(config, []))
        config['options']['web_access']['enabled'] = False
        self.assertNotIn('mcp.exa.ai', sandbox.network_policy(config, []))


if __name__ == '__main__':
    unittest.main()
