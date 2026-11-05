import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from vscode_pi_sandbox import sandbox_extensions as extensions


def bundle(name='package.json', content=b'{}', kind=tarfile.REGTYPE):
    blob = io.BytesIO()
    with tarfile.open(fileobj=blob, mode='w') as tar:
        entry = tarfile.TarInfo(name)
        entry.type = kind
        if kind == tarfile.REGTYPE:
            entry.size = len(content)
            tar.addfile(entry, io.BytesIO(content))
        else:
            entry.linkname = '/outside'
            tar.addfile(entry)
    return blob.getvalue()


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = {'repository': 'git@github.com:example/pi-extension.git', 'commit': 'a' * 40}

    def lock(self, sources):
        (self.root / 'extensions.lock.json').write_text(json.dumps({'version': 1, 'extensions': sources}))

    def test_saved_older_inputs_need_no_extension_contexts(self):
        with extensions.build_contexts(self.root) as args:
            self.assertEqual(args, [])

    def test_lock_requires_full_revision_and_explicit_repository(self):
        for change in [{'commit': 'main'}, {'repository': '-oProxyCommand=bad'}, {'extra': True}]:
            self.lock({'pi-extension': {**self.source, **change}})
            with self.assertRaises(ValueError): extensions.read_lock(self.root)

    def test_https_repository_supports_standard_host_git_authentication(self):
        self.lock({'pi-extension': {**self.source, 'repository': 'https://github.com/example/pi-extension.git'}})
        self.assertEqual(extensions.read_lock(self.root)['pi-extension']['commit'], self.source['commit'])

    def test_only_selected_dependency_is_loaded_and_context_removed(self):
        self.lock({'pi-first': self.source, 'pi-second': self.source})
        calls = []
        def fetch(source, cache):
            calls.append(source)
            return bundle()
        with extensions.build_contexts(self.root, names=['pi-second'], fetch=fetch) as args:
            self.assertEqual(len(calls), 1)
            self.assertEqual(args[0], '--build-context')
            self.assertTrue(args[1].startswith('pi-second='))
            context = Path(args[1].split('=', 1)[1])
            self.assertEqual((context / 'source-commit').read_text().strip(), self.source['commit'])
            self.assertEqual((context / 'package.json').read_text(), '{}')
            self.assertFalse((context / '.git').exists())
        self.assertFalse(context.exists())

    def test_missing_dependency_fails_before_build(self):
        self.lock({})
        with self.assertRaisesRegex(ValueError, 'Missing extension'):
            with extensions.build_contexts(self.root, names=['missing']): pass

    def test_archive_cannot_write_outside_context_or_include_git_metadata(self):
        for i, name in enumerate(['../escaped', '/absolute', '.git/config']):
            with self.assertRaises(ValueError): extensions.unpack(bundle(name), self.root / str(i))
        self.assertFalse((self.root / 'escaped').exists())

    def test_archive_links_are_rejected(self):
        with self.assertRaises(ValueError):
            extensions.unpack(bundle('linked', kind=tarfile.SYMTYPE), self.root / 'link')

    def test_existing_git_revision_exports_committed_files_without_fetch(self):
        import hashlib
        cache = self.root / 'cache'
        repo = cache / hashlib.sha256(self.source['repository'].encode()).hexdigest()[:16]
        repo.mkdir(parents=True)
        def git(*args):
            return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.DEVNULL).decode().strip()
        git('init', '-q')
        git('config', 'user.name', 'Fixture')
        git('config', 'user.email', 'fixture@example.test')
        git('remote', 'add', 'origin', self.source['repository'])
        (repo / 'package.json').write_text('{"name":"committed"}')
        git('add', 'package.json'); git('commit', '-qm', 'fixture')
        source = {**self.source, 'commit': git('rev-parse', 'HEAD')}
        (repo / 'package.json').write_text('{"name":"uncommitted"}')
        (repo / 'credentials.json').write_text('synthetic-only')
        exported = extensions.archive(source, cache)
        target = self.root / 'export'
        extensions.unpack(exported, target)
        self.assertEqual((target / 'package.json').read_text(), '{"name":"committed"}')
        self.assertFalse((target / 'credentials.json').exists())
        self.assertFalse((target / '.git').exists())
        git('remote', 'set-url', 'origin', 'git@github.com:other/repo.git')
        with self.assertRaisesRegex(ValueError, 'origin changed'): extensions.archive(source, cache)

    def test_repository_has_no_extension_implementations(self):
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / 'containers/dev/advisor').exists())
        self.assertFalse((root / 'containers/dev/local-model-manager').exists())
        for path in (root / 'containers').rglob('*'):
            if path.suffix in {'.js', '.mjs', '.ts'}:
                source = path.read_text()
                self.assertNotIn('registerTool(', source, str(path))
                self.assertNotIn('registerCommand(', source, str(path))
                self.assertNotIn('ExtensionAPI', source, str(path))
                self.assertNotIn('createPiExtension', source, str(path))


if __name__ == '__main__':
    unittest.main()
