import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pi_sandbox_factory import folders, sandbox
from pi_sandbox_factory.sandbox_tui import Cockpit, FoldersScreen, NewSandbox, SettingsForm, DEFAULT_SETTINGS, copy_draft
from pi_sandbox_factory.folders_ui import FolderFields, FolderEditor
from textual.widgets import Input, Button, Checkbox


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'project'
        self.workspace.mkdir()
        (self.workspace / 'app').mkdir()
        self.extra = self.root / 'reference'
        self.extra.mkdir()
        self.state = self.root / 'state'
        self.state.mkdir()
        self.config = dict(workspace=str(self.workspace), working_directory='app', engine='podman', extra_folders=[])

    def validate(self, rows, **kwargs):
        return folders.validate(rows, self.workspace, self.state, **kwargs)

    def test_pi_cli_starts_discovers_and_launches_in_starting_folder(self):
        config=dict(self.config, name='example', local_model_ports='8000')
        state=self.state/'example';state.mkdir()
        (state/'config.json').write_text(json.dumps(config))
        argv=['pi-sandbox-factory','--state-dir',str(self.state),'pi','example','--','--continue']
        calls=[]
        with patch('sys.argv',argv), \
             patch.object(sandbox,'up',side_effect=lambda *a:calls.append('up')), \
             patch.object(sandbox,'initialize_models',side_effect=lambda *a:calls.append('models')), \
             patch('sys.stdin.isatty',return_value=True), \
             patch.object(sandbox,'run',side_effect=lambda args:calls.append(args)):
            sandbox.main()
        self.assertEqual(calls[:2],['up','models'])
        self.assertEqual(calls[2],['podman','exec','--workdir','/workspace/app','-it',
                                   sandbox.names(config)[0],'pi','--continue'])
        with patch('sys.argv',argv), patch.object(sandbox,'up',side_effect=ValueError('start failed')), \
             patch.object(sandbox,'run') as run:
            with self.assertRaisesRegex(ValueError,'start failed'):sandbox.main()
            run.assert_not_called()

    def test_starting_folder_resolution(self):
        self.assertEqual(folders.container_cwd(self.config), '/workspace/app')
        self.assertEqual(folders.working_directory(self.workspace), '.')
        (self.workspace / 'alias').symlink_to(self.workspace / 'app')
        self.assertEqual(folders.working_directory(self.workspace, 'alias'), 'app')
        (self.workspace / 'escape').symlink_to(self.extra)
        (self.workspace / 'file').touch()
        for value in ('..', '/etc', 'app/../../etc', 'escape', 'missing', 'file'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                folders.working_directory(self.workspace, value)

    def test_mount_paths_modes_and_aliases(self):
        rows = self.validate([dict(source=str(self.extra))])
        self.assertEqual(rows[0]['name'], 'reference')
        self.assertTrue(rows[0]['read_only'])
        for engine, flag in [('podman', 'bind-nonrecursive'), ('docker', 'bind-recursive=disabled')]:
            args = folders.mounts(dict(self.config, engine=engine, extra_folders=rows))
            self.assertEqual(args, ['--mount', f'type=bind,src={self.extra},dst=/mnt/reference,{flag},ro'])
        rows[0]['read_only'] = False
        self.assertTrue(folders.mounts(dict(self.config, extra_folders=rows))[1].endswith(',rw'))
        self.assertEqual(folders.suggested_name(self.extra, rows), 'reference-2')

    def test_sources_and_overlaps(self):
        child = self.extra / 'child'; child.mkdir()
        hidden = self.root / '.ssh'; hidden.mkdir()
        invalid = ['/', str(Path.home()), '/etc', str(self.workspace), str(self.workspace / 'app'), str(self.state), str(self.root), str(self.root / 'missing')]
        for source in invalid:
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.validate([dict(source=source)])
        for name in ('../bad', 'data/path', 'with space', 'UPPER'):
            with self.assertRaises(ValueError):
                self.validate([dict(source=str(self.extra), name=name)])
        with self.assertRaises(ValueError):
            self.validate([dict(source=str(self.extra)), dict(source=str(child))])
        with self.assertRaises(ValueError):
            self.validate([dict(source=str(self.extra), read_only='false')])
        for name in ('comma,ro', 'line\nbreak', 'double"quote'):
            bad = self.root / name; bad.mkdir()
            with self.assertRaises(ValueError): self.validate([dict(source=str(bad))])
        (self.root / 'comma-alias').symlink_to(self.root / 'comma,ro')
        with self.assertRaises(ValueError): self.validate([dict(source=str(self.root / 'comma-alias'))])
        with patch.object(Path, 'home', return_value=self.root):
            with self.assertRaises(ValueError): self.validate([dict(source=str(hidden))])

    def test_saved_source_replacement_and_private_seed(self):
        rows = self.validate([dict(source=str(self.extra))])
        original = self.root / 'original'
        self.extra.rename(original)
        self.extra.symlink_to(original)
        with self.assertRaises(ValueError): self.validate(rows, saved=True)
        with self.assertRaises(ValueError):
            self.validate([dict(source=str(original))], private_paths=[original])

    def test_directional_permissions_keep_secret_denials(self):
        config = dict(self.config, extra_folders=self.validate([dict(source=str(self.extra))]))
        template = json.loads((sandbox.ROOT / 'containers/dev/security/config/permissions.json').read_text())
        original = copy.deepcopy(template['permission']['path'])
        result = folders.permissions(template, config)['permission']
        self.assertEqual(result['external_directory_read']['/mnt/reference/*'], 'allow')
        self.assertEqual(result['external_directory_write']['/mnt/reference/*'], 'deny')
        self.assertEqual(result['external_directory_write']['/workspace/*'], 'allow')
        self.assertEqual(result['path'], original)
        self.assertNotIn('/mnt/reference2/*', result['external_directory_read'])
        self.assertNotIn(str(self.root), folders.guidance(config))

    def test_cwd_update_preserves_container_and_private_state(self):
        state = self.state / 'demo'; state.mkdir()
        (state / 'private-marker').write_text('keep')
        with patch.object(sandbox, 'down') as down, patch.object(sandbox, 'build') as build:
            sandbox.apply_settings(self.config, state, {'working_directory': '.'})
        down.assert_not_called(); build.assert_not_called()
        self.assertEqual(json.loads((state / 'attached-container.json').read_text())['workspaceFolder'], '/workspace')
        self.assertEqual((state / 'private-marker').read_text(), 'keep')
        with patch.object(sandbox, 'down') as down, self.assertRaises(ValueError):
            sandbox.apply_settings(self.config, state, {'working_directory': 'missing'})
        down.assert_not_called()

    def test_copy_keeps_mounts_but_resets_starting_folder(self):
        config = dict(self.config, profile={'path': '/profile'}, extra_folders=self.validate([dict(source=str(self.extra))]))
        state = self.state / 'source'; state.mkdir(); (state / 'allowlist.txt').write_text('')
        draft = copy_draft(dict(config=config, name='source'), self.state)
        self.assertEqual(draft['working_directory'], '.')
        self.assertEqual(draft['extra_folders'], config['extra_folders'])
        self.assertIsNot(draft['extra_folders'], config['extra_folders'])
        self.assertNotIn('extra_folders', DEFAULT_SETTINGS)

    def test_folder_screen_add_edit_remove_at_80_columns(self):
        async def check():
            class Service:
                def inventory(self): return []
            with patch('pi_sandbox_factory.updates.available_update', return_value=None), patch('pi_sandbox_factory.sandbox_tui.load_defaults', return_value=copy.deepcopy(DEFAULT_SETTINGS)):
                app = Cockpit(self.state, Service())
                async with app.run_test(size=(80, 24)) as pilot:
                    await app.workers.wait_for_complete()
                    await app.push_screen(FoldersScreen(dict(name='test', config=self.config)))
                    await pilot.pause()
                    await pilot.click('#folder-add')
                    await pilot.pause()
                    self.assertIsInstance(app.screen, FolderEditor)
                    app.screen.query_one('#folder-source', Input).value = str(self.extra)
                    await pilot.click('#folder-save')
                    await pilot.pause()
                    fields = app.screen.query_one(FolderFields)
                    self.assertTrue(fields.rows[0]['read_only'])
                    await pilot.click('#folder-edit-0')
                    await pilot.pause()
                    app.screen.query_one('#folder-read-only', Checkbox).value = False
                    await pilot.click('#folder-save')
                    await pilot.pause()
                    self.assertFalse(fields.collect()['extra_folders'][0]['read_only'])
                    for button in app.screen.query(Button):
                        self.assertLessEqual(button.region.right, 80)
                    app.screen.query_one('#folder-remove-0', Button).press()
                    await pilot.pause()
                    self.assertEqual(fields.rows, [])
        asyncio.run(check())

    def test_creation_passes_selected_workspace_to_folder_review(self):
        async def check():
            class Service:
                def inventory(self): return []
            with patch('pi_sandbox_factory.updates.available_update', return_value=None), patch('pi_sandbox_factory.sandbox_tui.load_defaults', return_value=copy.deepcopy(DEFAULT_SETTINGS)):
                app = Cockpit(self.state, Service())
                async with app.run_test(size=(80, 24)) as pilot:
                    await app.workers.wait_for_complete()
                    for path, create in [(self.workspace, False), (self.root / 'new-project', True)]:
                        await app.push_screen(NewSandbox())
                        app.screen.query_one('#workspace', Input).value = str(path)
                        app.screen.query_one('#name', Input).value = 'new-example'
                        app.screen.query_one('#mkdir', Checkbox).value = create
                        app.screen.query_one('#continue', Button).press()
                        await pilot.pause()
                        self.assertIsInstance(app.screen, SettingsForm)
                        fields = app.screen.query_one(FolderFields)
                        self.assertEqual(fields.config['workspace'], str(path))
                        self.assertEqual(fields.collect()['working_directory'], '.')
                        if not create:
                            fields.query_one('#working-directory', Input).value = 'app'
                            self.assertEqual(fields.collect()['working_directory'], 'app')
                        app.pop_screen(); app.pop_screen()
                        await pilot.pause()
        asyncio.run(check())
