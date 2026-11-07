"""Host adapters run against fixtures; real OS validation is in TESTING.md."""
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pi_sandbox_factory import host_platform as host, editor_settings, browser_editor, folders


class HostTests(unittest.TestCase):
    def test_isolated_names_and_bind_addresses(self):
        for system, release in [('Darwin', '25.0'), ('Linux', '6.6-microsoft-standard-WSL2')]:
            with patch('platform.system', return_value=system), patch('platform.release', return_value=release):
                first, second = host.automatic_address(), host.automatic_address()
                self.assertRegex(first, r'^sbx-[a-f0-9]{24}\.localhost$')
                self.assertNotEqual(first, second)
                self.assertEqual(host.listen_address(first), '127.0.0.1')
                with tempfile.TemporaryDirectory() as folder:
                    state = Path(folder)
                    editor_settings.remember_connection(state, editor_settings.DEFAULTS, first, 54321)
                    self.assertEqual(editor_settings.connection(state, editor_settings.DEFAULTS), (first, 54321))
        with patch('platform.system', return_value='Linux'), patch('platform.release', return_value='6.12'):
            address = host.automatic_address()
            self.assertTrue(address.startswith('127.'))
            self.assertEqual(host.listen_address(address), address)

    def test_browser_launcher(self):
        url = 'http://sbx-' + 'a' * 24 + '.localhost:43210'
        with patch('platform.system', return_value='Darwin'), patch.object(host.subprocess, 'Popen') as spawn:
            host.open_url(url)
            self.assertEqual(spawn.call_args.args[0], ['open', url])
        with patch.object(host, 'is_wsl', return_value=True), patch('platform.system', return_value='Linux'), \
                patch.object(host.shutil, 'which', side_effect=lambda name: name == 'powershell.exe'), \
                patch.object(host.subprocess, 'Popen') as spawn:
            host.open_url(url)
            self.assertEqual(spawn.call_args.args[0][-1], "Start-Process '" + url + "'")

    def test_windows_path_conversion_and_private_folders(self):
        with patch.object(host, 'is_wsl', return_value=True), patch.object(host.subprocess, 'check_output', return_value='/mnt/c/Users/test/Project\n') as convert:
            self.assertEqual(host.local_path(r'C:\Users\test\Project'), Path('/mnt/c/Users/test/Project'))
            self.assertEqual(convert.call_args.args[0][:2], ['wslpath', '-u'])
            for path in ('/mnt/c', '/mnt/c/Windows', '/mnt/c/Users', '/mnt/c/Users/test',
                         '/mnt/c/Users/test/AppData/Local', '/mnt/c/Users/test/.ssh'):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    host.validate_data_path(path)
            host.validate_data_path('/mnt/c/Users/test/Project')

    def test_mac_private_paths_and_short_control_socket(self):
        with patch('platform.system', return_value='Darwin'):
            for path in ('/System/Library', '/SYSTEM/library', str(Path.home() / 'library/Keychains'), '/etc', '/var/log', '/private', '/private/etc', str(Path.home() / 'Library/Keychains')):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    host.validate_data_path(path)
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / ('long-state-path-' * 12)
            sock = host.control_path(state)
            self.assertLess(len(os.fsencode(sock)), 104)
            self.assertEqual(sock.parent.stat().st_mode & 0o777, 0o700)
            self.assertNotEqual(sock, host.control_path(Path(folder) / 'different'))

    def test_machine_connection_rootless_and_version(self):
        uri = 'ssh://core@127.0.0.1:53111/run/user/1000/podman/podman.sock'
        connection = json.dumps([dict(Name='podman-machine-default', URI=uri, Default=True)])
        def check(info, expected=None):
            with patch('platform.system', return_value='Darwin'), patch.dict(os.environ, {}, clear=True), \
                    patch.object(host.subprocess, 'check_output', side_effect=[connection, json.dumps(info)]):
                return host.check_engine('podman', expected)
        info = dict(host=dict(security=dict(rootless=True)), version=dict(Version='5.6.2'))
        self.assertEqual(check(info), uri)
        with self.assertRaisesRegex(ValueError, 'different Podman'):
            check(info, 'ssh://other')
        info['host']['security']['rootless'] = False
        with self.assertRaisesRegex(ValueError, 'rootless'):
            check(info)
        info['host']['security']['rootless'] = True
        info['version']['Version'] = '5.5.0'
        with self.assertRaisesRegex(ValueError, '5.6'):
            check(info)
        with patch('platform.system', return_value='Linux'), patch.object(host.subprocess, 'check_output') as call:
            host.check_engine('podman')
            call.assert_not_called()

    def test_model_route_and_archive_architecture(self):
        with patch('platform.system', return_value='Darwin'):
            self.assertEqual(host.model_gateway_args(), ['--env', 'SANDBOX_MODEL_HOST=host.containers.internal'])
            self.assertEqual(host.bind_mode(), 'ro')
            self.assertEqual(host.gateway_labels(), ['--security-opt=label=disable'])
        with patch('platform.system', return_value='Linux'):
            self.assertIn('--network=pasta:--map-host-loopback,169.254.1.2', host.model_gateway_args())
            self.assertEqual(host.bind_mode(), 'ro,Z')
            self.assertEqual(host.gateway_labels(), [])
        self.assertIn('linux-amd64', browser_editor.release('x86_64')[0])
        self.assertIn('linux-arm64', browser_editor.release('aarch64')[0])
        self.assertNotEqual(browser_editor.release('x86_64')[1], browser_editor.release('aarch64')[1])
        with self.assertRaises(ValueError):
            browser_editor.release('unsupported')

    def test_helpers_ignore_workspace_python_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('json', 'asyncio', 'runpy', 'pi_sandbox_factory'):
                (root / (name + '.py')).write_text("raise RuntimeError('WORKSPACE CODE EXECUTED')")
            env = {**os.environ, 'PYTHONPATH': str(root)}
            result = subprocess.run(host.python_command('pi_sandbox_factory', '--help'),
                                    cwd=root, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('usage: pi-sandbox-factory', result.stdout)

    def test_case_insensitive_host_boundaries(self):
        with patch.object(host, 'is_mac', return_value=True):
            self.assertTrue(folders.overlaps(Path('/Users/Alice/State'), Path('/users/alice/state/secrets')))
            self.assertFalse(folders.overlaps(Path('/Users/Alice/State'), Path('/Users/Alice/Project')))
        with patch.object(host, 'is_mac', return_value=False), patch.object(host, 'is_wsl', return_value=False):
            self.assertFalse(folders.overlaps(Path('/tmp/State'), Path('/tmp/state')))
        with patch.object(host, 'is_mac', return_value=False), patch.object(host, 'is_wsl', return_value=True):
            self.assertTrue(folders.overlaps(Path('/mnt/c/Users/Alice/State'), Path('/mnt/c/users/alice/state/secrets')))

    def test_vm_mount_check_selection(self):
        config = dict(workspace='/home/test/project', extra_folders=[])
        with patch.object(host, 'is_mac', return_value=True):
            self.assertTrue(host.needs_mount_check(config))
        with patch.object(host, 'is_mac', return_value=False), patch.object(host, 'is_wsl', return_value=False):
            self.assertFalse(host.needs_mount_check(config))
        with patch.object(host, 'is_mac', return_value=False), patch.object(host, 'is_wsl', return_value=True):
            self.assertFalse(host.needs_mount_check(config))
            self.assertTrue(host.needs_mount_check({**config, 'pi_config': '/mnt/c/Users/test/pi'}))
            self.assertTrue(host.needs_mount_check({**config, 'extra_folders': [dict(source='/mnt/c/Data')]}))

    def test_vm_loopback_addresses(self):
        digest = editor_settings.password_hash('test-password-long')
        with patch.object(host, 'is_mac', return_value=True):
            self.assertEqual(editor_settings.validate()['address'], '')
            self.assertEqual(editor_settings.validate(dict(address='127.0.0.1', password_hash=digest))['address'], '127.0.0.1')
            with self.assertRaisesRegex(ValueError, 'automatic addressing'):
                editor_settings.validate(dict(address='127.2.3.4', password_hash=digest))
        with patch.object(host, 'is_mac', return_value=False), patch.object(host, 'is_wsl', return_value=False):
            self.assertEqual(editor_settings.validate(dict(address='127.2.3.4', password_hash=digest))['address'], '127.2.3.4')
