import json
from pathlib import Path
import unittest
from pi_sandbox_factory.sandbox_options import permissions, guidance

TEMPLATE = json.loads((Path(__file__).resolve().parents[1] / 'pi_sandbox_factory/containers/dev/security/config/permissions.json').read_text())

class SkillPermissionTests(unittest.TestCase):
    def test_installed_reads_match_native_scope(self):
        result = permissions(TEMPLATE, {})['permission']
        for root in ('/opt', '/usr', '/etc/fonts', '/etc/ssl'):
            self.assertEqual(result['external_directory_read'][root], 'allow')
            self.assertEqual(result['external_directory_read'][root+'/*'], 'allow')
        self.assertEqual(result['external_directory'], 'ask')
        self.assertNotIn('external_directory_write', result)

    def test_protected_paths_are_preserved(self):
        result = permissions(TEMPLATE, {})['permission']
        self.assertEqual(result['path'], TEMPLATE['permission']['path'])
        self.assertEqual(result['path']['/opt/pi-security/*'], 'deny')
        self.assertEqual(result['path']['*.env'], 'deny')

    def test_common_credentials_can_be_read_and_written_when_protection_is_disabled(self):
        result = permissions(TEMPLATE, {'protect_credentials': False})['permission']
        for pattern in ('*.pem', '*.key', '*.env', '*.env.*'):
            self.assertNotIn(pattern, result['path'])
        self.assertEqual(result['path']['*.env.example'], 'allow')
        self.assertNotIn('path_write', result)
        self.assertEqual(result['path']['/opt/pi-security/*'], 'deny')

    def test_credential_guidance_matches_saved_choice(self):
        protected = guidance({'protect_credentials': True})
        unprotected = guidance({'protect_credentials': False})
        self.assertIn('protected from agent reads', protected)
        self.assertIn('may read and write common credential files', unprotected)
        self.assertIn('agent may change them', unprotected)

    def test_explicit_read_restrictions_are_preserved(self):
        source = json.loads(json.dumps(TEMPLATE))
        source['permission']['external_directory_read'] = {'/opt/*':'deny', '/usr/*':'ask'}
        result = permissions(source, {})['permission']['external_directory_read']
        self.assertEqual(result['/opt/*'], 'deny')
        self.assertEqual(result['/usr/*'], 'ask')
        self.assertNotIn('external_directory_read', TEMPLATE['permission'])

    def test_explicit_surface_wide_rule_is_preserved(self):
        for action in ('deny','ask','allow'):
            source = json.loads(json.dumps(TEMPLATE))
            source['permission']['external_directory_read'] = action
            self.assertEqual(permissions(source, {})['permission']['external_directory_read'],action)

    def test_only_literal_absolute_roots_are_expanded(self):
        source = {'permission':{}, 'piInfrastructureReadPaths':['relative','~/.pi','/opt/*']}
        self.assertEqual(permissions(source, {})['permission']['external_directory_read'], {})

    def test_review_modes_retain_shell_review_when_inner_disabled(self):
        for mode in ('automatic','assisted','manual'):
            result=permissions(TEMPLATE, {'approval':mode,'inner_sandbox':False})
            self.assertEqual(result['permission']['bash'], 'ask')
            self.assertEqual(result['permission']['external_directory'], 'ask')

    def test_guidance_explains_shells_temp_network_and_tmux(self):
        for mode in ('automatic','assisted','manual'):
            text=guidance({'approval':mode})
            for phrase in ('Use bash_escalate for tmux', '$TMPDIR', 'separate network namespace', 'outer network allowlist', 'Read installed skill instructions'):
                self.assertIn(phrase,text)

    def test_off_mode_does_not_offer_unavailable_escalation(self):
        text=guidance({'approval':'off'})
        self.assertIn('bash_escalate is unavailable',text)
        self.assertNotIn('Use bash_escalate for tmux',text)

    def test_no_inner_shell_does_not_claim_socket_block(self):
        text=guidance({'inner_sandbox':False})
        self.assertNotIn('inner sandbox blocks Unix sockets',text)
        self.assertNotIn('Each bash call has its own temporary directory',text)
