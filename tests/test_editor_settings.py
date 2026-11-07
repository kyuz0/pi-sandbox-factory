"""Editor preferences stay separate from container configuration and copied secrets."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from argon2 import PasswordHasher
from pi_sandbox_factory import editor_settings as settings


class Preferences(unittest.TestCase):
    def test_browser_default_and_host_editor_boundary(self):
        self.assertEqual(settings.validate()['mode'], 'browser')
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            self.assertEqual(settings.load(state), settings.DEFAULTS)
            (state / 'browser-editor.enabled').touch()
            self.assertEqual(settings.load(state)['mode'], 'browser')
            with self.assertRaisesRegex(ValueError, 'separate sandbox'):
                settings.save(state, {'mode': 'desktop'})

    def test_password_hash_private_file_and_no_container_change(self):
        password = 'synthetic-editor-password'
        digest = settings.password_hash(password)
        self.assertTrue(PasswordHasher().verify(digest, password))
        self.assertNotEqual(digest, settings.password_hash(password))
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            (state / 'config.json').write_text('unchanged')
            value = settings.save(state, {'password_hash': digest})
            self.assertEqual(settings.load(state), value)
            self.assertEqual((state / 'editor.json').stat().st_mode & 0o777, 0o600)
            self.assertNotIn(password, (state / 'editor.json').read_text())
            self.assertEqual((state / 'config.json').read_text(), 'unchanged')
            self.assertEqual(settings.copy_choice(value), settings.DEFAULTS)

    def test_address_port_and_remote_authentication(self):
        for value in ({'address': '0.0.0.0'}, {'address': '::'}, {'address': 'example.com'},
                      {'port': -1}, {'port': 65536}, {'port': True}, {'mode': 'other'},
                      {'address': '192.0.2.1'}, {'password_hash': 'raw-password'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                settings.validate(value)
        digest = settings.password_hash('synthetic-remote-password')
        with self.assertRaisesRegex(ValueError, 'HTTPS'):
            settings.validate({'address': '192.0.2.1', 'password_hash': digest})
        value = settings.validate({'address': '192.0.2.1', 'password_hash': digest,
                                   'certificate': '/cert.pem', 'private_key': '/key.pem'})
        self.assertEqual(settings.copy_choice(value), settings.DEFAULTS)
        self.assertEqual(settings.authority('::1', 8000), '[::1]:8000')

    def test_private_loopback_address_and_port_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            address, port = settings.connection(state, settings.DEFAULTS)
            self.assertTrue(address.startswith('127.'))
            self.assertNotEqual(address, '127.0.0.1')
            self.assertEqual(port, 0)
            (state / 'editor-address.json').write_text(json.dumps({'automatic_address': address, 'address': address, 'port': 43210}))
            self.assertEqual(settings.connection(state, settings.DEFAULTS), (address, 43210))
            self.assertEqual(settings.connection(state, {**settings.DEFAULTS, 'port': 4444}), (address, 4444))
            settings.remember_connection(state, {'address': '127.0.0.1'}, '127.0.0.1', 5555)
            self.assertEqual(settings.connection(state, settings.DEFAULTS), (address, 0))

    def test_unsupported_platform_defaults_to_desktop(self):
        with patch('platform.machine', return_value='aarch64'):
            self.assertEqual(settings.default_mode(), 'desktop')
        self.assertEqual(settings.default_mode('docker'), 'desktop')
