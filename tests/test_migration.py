import hashlib
import io
import os
from pathlib import Path
import socket
import stat
import tempfile
import unittest
from unittest.mock import patch

import pi_factory_migration as launcher
from pi_factory_migration import paths


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        self.pairs = paths.locations(self.home, {})

    def tearDown(self):
        self.temp.cleanup()

    def seed(self):
        for index, (old, new) in enumerate(self.pairs):
            old.mkdir(parents=True)
            (old / 'receipt').write_bytes(bytes([index, 0, 255]))
            (old / 'receipt').chmod(0o600)

    def test_moves_default_data_and_retains_absolute_references_and_permissions(self):
        self.seed()
        old, new = self.pairs[0]
        snapshot = old / 'example/profiles/snapshot'
        snapshot.mkdir(parents=True)
        (snapshot / 'manifest.json').write_text('{}')
        (old / 'example/config.json').write_text(str(snapshot))
        paths.migrate(self.pairs)
        for index, (old, new) in enumerate(self.pairs):
            self.assertTrue(old.is_symlink())
            self.assertTrue(new.is_dir())
            self.assertEqual((new / 'receipt').read_bytes(), bytes([index, 0, 255]))
            self.assertEqual((old / 'receipt').read_bytes(), (new / 'receipt').read_bytes())
            self.assertEqual(stat.S_IMODE((new / 'receipt').stat().st_mode), 0o600)
        self.assertTrue((snapshot / 'manifest.json').is_file())
        self.assertEqual((self.pairs[0][1] / 'example/config.json').read_text(), str(snapshot))
        self.assertEqual(paths.migrate(self.pairs), [])

    def test_abrupt_exit_between_rename_and_link_is_recovered(self):
        from pi_factory_migration import journal
        self.seed()
        journal.write(journal.location(self.pairs), self.pairs)
        old, new = self.pairs[0]
        old.rename(new)  # State left by termination immediately after rename.
        paths.migrate(self.pairs)
        for old, new in self.pairs:
            self.assertTrue(old.is_symlink())
            self.assertEqual((old / 'receipt').read_bytes(), (new / 'receipt').read_bytes())
        self.assertFalse(journal.location(self.pairs).exists())

    def test_custom_xdg_roots_and_duplicate_roots(self):
        env = {'XDG_CONFIG_HOME': str(self.home / 'config with spaces'),
               'XDG_DATA_HOME': str(self.home / 'data'),
               'XDG_CACHE_HOME': str(self.home / 'cache')}
        pairs = paths.locations(self.home, env)
        self.assertEqual(pairs[1][0], self.home / 'config with spaces/pi-sandbox-factory')
        env = {key: str(self.home / '.local/state') for key in env}
        self.assertEqual(len(paths.locations(self.home, env)), 1)

    def test_destination_conflict_changes_nothing(self):
        self.seed()
        self.pairs[-1][1].mkdir()
        with self.assertRaisesRegex(ValueError, 'both locations exist'):
            paths.migrate(self.pairs)
        for old, _ in self.pairs:
            self.assertFalse(old.is_symlink())
            self.assertTrue((old / 'receipt').exists())

    def test_foreign_symlink_is_not_followed_or_moved(self):
        old, _ = self.pairs[0]
        old.parent.mkdir(parents=True)
        unrelated = self.home / 'other'; unrelated.mkdir()
        old.symlink_to(unrelated)
        with self.assertRaisesRegex(ValueError, 'link to'):
            paths.migrate(self.pairs)
        self.assertEqual(old.resolve(), unrelated)

    def test_failure_and_keyboard_interrupt_restore_every_original_directory(self):
        for failure in (OSError('simulated link failure'), KeyboardInterrupt()):
            with self.subTest(error=type(failure).__name__):
                self.seed()
                original = Path.symlink_to
                calls = 0
                def fail_second(path, *args, **kwargs):
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        raise failure
                    return original(path, *args, **kwargs)
                with patch.object(Path, 'symlink_to', fail_second), self.assertRaises(type(failure)):
                    paths.migrate(self.pairs)
                for old, new in self.pairs:
                    self.assertFalse(old.is_symlink())
                    self.assertFalse(new.exists())
                    self.assertTrue((old / 'receipt').is_file())
                    (old / 'receipt').unlink();old.rmdir()

    def test_live_editor_socket_remains_reachable_under_both_paths(self):
        old, new = self.pairs[0]
        state = old / 'example';state.mkdir(parents=True)
        (state / 'browser-editor-runtime.json').write_text('{}')
        root = Path('/tmp') / f'psf-{os.getuid()}'
        root.mkdir(mode=0o700, exist_ok=True)
        previous = root / (hashlib.sha256(str(state.resolve()).encode()).hexdigest()[:24] + '.sock')
        current = root / (hashlib.sha256(str((new / 'example').resolve()).encode()).hexdigest()[:24] + '.sock')
        try:
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(previous));server.listen()
                paths.migrate(self.pairs)
                for target in (previous, current):
                    with socket.socket(socket.AF_UNIX) as client:
                        client.connect(str(target))
                        connection, _ = server.accept()
                        with connection:
                            client.sendall(b'status');self.assertEqual(connection.recv(32), b'status')
        finally:
            previous.unlink(missing_ok=True);current.unlink(missing_ok=True)

    def test_existing_application_receives_every_argument_without_reinstall(self):
        arguments = ['--state-dir', str(self.home / 'custom state'), 'list', '--json']
        with patch.object(launcher.Path, 'home', return_value=self.home), \
                patch.object(launcher, 'application', return_value=['/example/bin/ai-sandbox-factory']), \
                patch.object(launcher, 'install') as install, \
                patch.object(launcher.os, 'execvpe') as execute:
            launcher.run(arguments)
        install.assert_not_called()
        self.assertEqual(execute.call_args.args[:2],
                         ('/example/bin/ai-sandbox-factory', ['/example/bin/ai-sandbox-factory', *arguments]))

    def test_forwarding_does_not_consume_a_tool_argument_named_yes(self):
        args = ['exec', 'example', '--', 'printf', '--yes']
        with patch.object(launcher.Path, 'home', return_value=self.home), \
                patch.object(launcher, 'application', return_value=['/example/bin/ai-sandbox-factory']), \
                patch.object(launcher.os, 'execvpe') as execute:
            launcher.run(args)
        self.assertEqual(execute.call_args.args[1][1:], args)

    def test_failed_install_keeps_all_data_at_original_paths(self):
        self.seed()
        with patch.object(launcher.Path, 'home', return_value=self.home), \
                patch.object(launcher, 'application', return_value=None), \
                patch.object(launcher, 'install', side_effect=RuntimeError('installer exited 19')), \
                patch.dict(os.environ, {key: '' for key in ('XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME')}), \
                self.assertRaisesRegex(RuntimeError, 'installer exited 19'):
            launcher.run(['--yes', '--version'])
        for old, new in self.pairs:
            self.assertTrue((old / 'receipt').is_file())
            self.assertFalse(old.is_symlink())
            self.assertFalse(new.exists())

    def test_noninteractive_first_launch_explains_how_to_confirm(self):
        with patch.object(launcher.Path, 'home', return_value=self.home), \
                patch.object(launcher, 'application', return_value=None), \
                patch.object(launcher.sys.stdin, 'isatty', return_value=False), \
                patch.object(launcher, 'install') as install, \
                self.assertRaisesRegex(ValueError, 'terminal.*--yes'):
            launcher.run(['--version'])
        install.assert_not_called()


if __name__ == '__main__':
    unittest.main()
