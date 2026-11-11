import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from pi_sandbox_factory import host_platform as host, sandbox


class PastaCompatibilityTests(unittest.TestCase):
    config = {'engine': 'podman', 'local_model_gateway': True}

    def test_supported_helper_selected_by_podman_including_backports(self):
        for code, stdout, stderr in [(0, '--map-host-loopback ADDR', ''),
                                     (1, '', '--map-host-loopback ADDR')]:
            with self.subTest(code=code), patch.object(host, 'is_mac', return_value=False), \
                    patch.object(host.subprocess, 'run', side_effect=[
                        subprocess.CompletedProcess([], 0, json.dumps({'executable': '/opt/pasta'}), ''),
                        subprocess.CompletedProcess([], code, stdout, stderr)]) as run:
                host.check_model_gateway(self.config)
                self.assertEqual(run.call_args_list[1].args[0], ['/opt/pasta', '--help'])

    def test_older_podman_without_helper_metadata_uses_path(self):
        with patch.object(host, 'is_mac', return_value=False), \
                patch.object(host.shutil, 'which', return_value='/usr/bin/pasta'), \
                patch.object(host.subprocess, 'run', side_effect=[
                    subprocess.CompletedProcess([], 125, '', 'unknown field'),
                    subprocess.CompletedProcess([], 0, '--map-host-loopback ADDR', '')]):
            host.check_model_gateway(self.config)

    def test_unsupported_helper_has_actionable_message(self):
        with patch.object(host, 'is_mac', return_value=False), \
                patch.object(host.subprocess, 'run', side_effect=[
                    subprocess.CompletedProcess([], 0, '{"executable":"/usr/bin/pasta"}', ''),
                    subprocess.CompletedProcess([], 0, '--no-map-gw', '')]):
            with self.assertRaisesRegex(ValueError, '2024_08_21.1d6142f') as error:
                host.check_model_gateway(self.config)
            self.assertIn('disable "Connect to models on this host"', str(error.exception))
            self.assertIn('Upgrade the passt package', str(error.exception))

    def test_missing_and_unreadable_helpers(self):
        with patch.object(host, 'is_mac', return_value=False), \
                patch.object(host.shutil, 'which', return_value=None), \
                patch.object(host.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'null', '')):
            with self.assertRaisesRegex(ValueError, 'pasta was not found'):
                host.check_model_gateway(self.config)
        for failure in (OSError('not executable'), subprocess.TimeoutExpired('pasta', 5)):
            with self.subTest(failure=failure), patch.object(host, 'is_mac', return_value=False), \
                    patch.object(host.subprocess, 'run', side_effect=[
                        subprocess.CompletedProcess([], 0, '{"executable":"/usr/bin/pasta"}', ''), failure]):
                with self.assertRaisesRegex(ValueError, 'Could not check pasta'):
                    host.check_model_gateway(self.config)

    def test_hosted_only_docker_and_mac_do_not_probe_pasta(self):
        for mac, config in [(False, {'engine':'podman'}),
                            (False, {'engine':'docker', 'local_model_gateway':True}),
                            (True, self.config)]:
            with self.subTest(mac=mac, config=config), patch.object(host, 'is_mac', return_value=mac), \
                    patch.object(host.subprocess, 'run') as run:
                host.check_model_gateway(config)
                run.assert_not_called()

    def test_failure_precedes_gateway_mutation_and_companion_start(self):
        config = {**self.config, 'name':'compat-check', 'network':'allowlist'}
        with patch.object(sandbox.folders, 'validate_config'), \
                patch.object(sandbox.sandbox_advisors, 'check_ownership'), \
                patch.object(sandbox.sandbox_ssh, 'check_ownership'), \
                patch.object(sandbox.inference, 'check_ownership'), \
                patch.object(sandbox, 'inspect', return_value=None), \
                patch.object(host, 'check_model_gateway', side_effect=ValueError('unsupported pasta')), \
                patch.object(sandbox, 'upgrade_gateway_config') as mutate, \
                patch.object(sandbox.inference, 'up') as start, \
                patch.object(sandbox, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'unsupported pasta'):
                sandbox.up(config, Path('/unused'))
            mutate.assert_not_called()
            start.assert_not_called()
            run.assert_not_called()
