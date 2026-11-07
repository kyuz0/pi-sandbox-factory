"""Layout and navigation contracts for the terminal forms."""
import asyncio
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Button, Collapsible, Input, OptionList, Select, Static, RichLog
from pi_sandbox_factory import sandbox
from pi_sandbox_factory.sandbox_tui import (
    Cockpit, Confirm, DEFAULT_SETTINGS, FolderPicker, NewSandbox, SettingsForm,
    SettingsMenu, WebAccessForm, preset,
)
from pi_sandbox_factory.folders_ui import FolderEditor
from pi_sandbox_factory.tui_widgets import Checkbox
from test_tui import FakeService


class TUILayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.runner = asyncio.Runner()
    @classmethod
    def tearDownClass(cls): cls.runner.close()
    def _callTestMethod(self, method): self.runner.run(method())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'project'
        self.workspace.mkdir()
        state = self.root / 'demo'
        state.mkdir()
        (state / 'allowlist.txt').write_text('local-model.internal:8000\n')
        config = dict(name='demo', engine='podman', network='allowlist',
                      workspace=str(self.workspace), profile=sandbox.load_profile('base'),
                      local_model_ports='8000', memory='8g', subagents=False)
        self.record = dict(name='demo', profile='base', engine='podman', dev='running',
                           proxy='running', workspace=str(self.workspace), config=config)
        for target, kwargs in [
            ('pi_sandbox_factory.sandbox_tui.load_defaults', dict(side_effect=lambda: copy.deepcopy(DEFAULT_SETTINGS))),
            ('pi_sandbox_factory.sandbox_tui.search_keys_path', dict(return_value=self.root/'keys.json')),
            ('pi_sandbox_factory.updates.available_update', dict(return_value=None)),
        ]:
            mock = patch(target, **kwargs)
            mock.start()
            self.addCleanup(mock.stop)

    def app(self): return Cockpit(self.root, FakeService([self.record]))
    def draft(self):
        value = preset('base', copy.deepcopy(DEFAULT_SETTINGS))
        value.update(name='demo', workspace=str(self.workspace))
        return value

    async def ready(self, app, pilot):
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

    async def test_workspace_controls_align_and_remain_reachable(self):
        for size in ((80, 24), (120, 40)):
            app = self.app()
            async with app.run_test(size=size) as pilot:
                await self.ready(app, pilot)
                await pilot.press('f2')
                await pilot.pause()
                field = app.screen.query_one('#workspace', Input)
                browse = app.screen.query_one('#browse', Button)
                checkbox = app.screen.query_one('#mkdir', Checkbox)
                self.assertEqual(browse.region.y, field.region.y)
                self.assertEqual(browse.region.height, field.region.height)
                self.assertEqual(field.region.height, 3)
                self.assertEqual(checkbox.region.y, field.region.bottom + 1)
                self.assertEqual(checkbox.region.x, field.region.x + 2)
                primary = app.screen.query_one('#continue', Button)
                actions = app.screen.query_one('.wizard-actions')
                self.assertEqual(primary.region.right, actions.content_region.right)
                self.assertEqual(primary.region.height, 3 if size[1] >= 32 else 1)
                self.assertLess(primary.region.bottom, app.screen.query_one('Footer').region.y)
                app.screen.query_one('#name', Input).focus()
                await pilot.pause()
                self.assertLessEqual(app.screen.query_one('#name').region.bottom,
                                     app.screen.query_one('.wizard-actions').region.y)
                await pilot.press('escape')
                await pilot.press('q')

    async def test_folder_and_confirmation_dialogs_cancel_with_escape(self):
        app = self.app()
        async with app.run_test(size=(80, 24)) as pilot:
            await self.ready(app, pilot)
            result = []
            await app.push_screen(Confirm('Recreate this sandbox?', 'Recreate'), result.append)
            await pilot.press('escape')
            self.assertEqual(result, [False])
            await app.push_screen(FolderPicker(str(self.workspace)), result.append)
            await pilot.press('escape')
            self.assertIsNone(result[-1])
            await app.push_screen(FolderEditor(None, [], str(self.workspace), self.root))
            await pilot.pause()
            self.assertIsInstance(app.screen.query_one('#folder-read-only'), Checkbox)
            self.assertLess(app.screen.query_one('#folder-cancel').region.x,
                            app.screen.query_one('#folder-save').region.x)
            app.screen.query_one('#folder-error', Static).update('Cannot use this folder. ' * 12)
            await pilot.pause()
            save = app.screen.query_one('#folder-save', Button)
            self.assertLess(save.region.bottom, 24)
            self.assertIs(app.screen.get_widget_at(save.region.x, save.region.y)[0], save)
            await pilot.click('#folder-cancel')
            self.assertIs(app.screen, app.screen_stack[0])
            await pilot.press('q')

    async def test_web_access_is_discoverable_and_opens_its_controls(self):
        app = self.app()
        async with app.run_test(size=(80, 24)) as pilot:
            await self.ready(app, pilot)
            await pilot.click('#settings')
            menu = app.screen.query_one('#settings-actions', OptionList)
            menu.highlighted = next(i for i, (_, action) in enumerate(SettingsMenu.ACTIONS) if action == 'web-access')
            menu.focus()
            await pilot.press('enter')
            await pilot.pause()
            form = app.screen
            self.assertIsInstance(form, SettingsForm)
            self.assertTrue(form.editing)
            section = form.query_one('#web-section', Collapsible)
            self.assertFalse(section.collapsed)
            self.assertIn('Off', section.title)
            control = form.query_one('#web-enabled', Checkbox)
            self.assertGreaterEqual(control.region.y, 1)
            self.assertLess(control.region.bottom, form.query_one('.wizard-actions').region.y)
            control.value = True
            await pilot.pause()
            self.assertIn('Automatic fallback', section.title)
            web = form.query_one(WebAccessForm)
            self.assertTrue(web.collect()[0]['enabled'])
            await pilot.press('escape')
            await pilot.press('q')

    async def test_form_groups_and_disabled_fields_follow_selections(self):
        app = self.app()
        async with app.run_test(size=(120, 40)) as pilot:
            await self.ready(app, pilot)
            await app.push_screen(SettingsForm(self.draft()))
            form = app.screen
            form.query_one('#local-models', Checkbox).value = False
            await pilot.pause()
            self.assertTrue(form.query_one('#model-ports', Input).disabled)
            form.query_one('#network', Select).value = 'unrestricted'
            await pilot.pause()
            self.assertFalse(form.query_one('#network-rules-fields').display)
            form.query_one('#network', Select).value = 'allowlist'
            await pilot.pause()
            self.assertTrue(form.query_one('#network-rules-fields').display)
            form.query_one('#skills-section', Collapsible).collapsed = False
            await pilot.pause()
            recall = form.query_one('#compaction-recall', Select)
            help_text = recall.parent.query_one('.setting-help')
            self.assertEqual(help_text.region.y, recall.region.bottom)
            await pilot.press('escape')
            draft = self.draft()
            draft['options']['web_access']['enabled'] = True
            await app.push_screen(SettingsForm(draft, defaults=True))
            await pilot.pause()
            self.assertFalse(app.screen.query_one('#web-defaults-setting').display)
            await pilot.press('escape')
            await pilot.press('q')

    async def test_create_launches_editor_only_when_selected(self):
        for open_editor in (True, False):
            app = self.app()
            async with app.run_test(size=(80, 24)) as pilot:
                await self.ready(app, pilot)
                await app.push_screen(NewSandbox())
                draft = self.draft()
                draft['open_editor'] = open_editor
                await app.push_screen(SettingsForm(draft))
                app.screen.submit(draft, {})
                await self.ready(app, pilot)
                self.assertEqual(app.service.calls[0][0], 'create')
                self.assertEqual(['open', 'demo'] in app.service.calls, open_editor)
                self.assertTrue(app.screen.finished)
                self.assertFalse(app.screen.failed)
                await pilot.press('escape')
                await self.ready(app, pilot)
                await pilot.press('q')

    async def test_create_with_pi_opens_the_terminal_after_success(self):
        app = self.app()
        async with app.run_test(size=(80, 24)) as pilot:
            await self.ready(app, pilot)
            await app.push_screen(NewSandbox())
            draft = self.draft()
            draft['editor']['mode'] = 'pi'
            draft['open_editor'] = True
            await app.push_screen(SettingsForm(draft))
            with patch.object(app, 'interactive') as launch:
                app.screen.submit(draft, {})
                await self.ready(app, pilot)
                launch.assert_called_once_with('pi', 'demo')
            self.assertEqual([call[0] for call in app.service.calls], ['create'])
            self.assertTrue(app.screen.finished)
            self.assertFalse(app.screen.failed)

    async def test_editor_choice_stays_with_final_action(self):
        for size in ((80, 24), (120, 40)):
            for editing in (False, True):
                app = self.app()
                async with app.run_test(size=size) as pilot:
                    await self.ready(app, pilot)
                    await app.push_screen(SettingsForm(self.draft(), editing=editing))
                    await pilot.pause()
                    form = app.screen
                    choice = form.query_one('#open-editor', Checkbox)
                    actions = form.query_one('.wizard-actions')
                    apply = form.query_one('#apply', Button)
                    self.assertIs(choice.parent, actions)
                    self.assertEqual(apply.region.right, actions.content_region.right)
                    self.assertEqual(apply.region.height, 3 if size[1] >= 32 else 1)
                    self.assertEqual(choice.region.x, form.query_one('.form').content_region.x)
                    self.assertEqual(choice.region.x, form.query_one('#back').region.x)
                    self.assertEqual(choice.value, not editing)
                    self.assertGreaterEqual(choice.region.y, actions.region.y)
                    self.assertLess(choice.region.bottom, apply.region.y)
                    self.assertLess(apply.region.bottom, form.query_one('Footer').region.y)
                    self.assertGreater(choice.region.y, actions.region.y)
                    form.query_one('#web-section', Collapsible).collapsed = False
                    form.query_one('#web-section').scroll_visible(top=True, animate=False)
                    await pilot.pause()
                    self.assertGreaterEqual(choice.region.y, actions.region.y)
                    await pilot.press('escape')
                    await pilot.press('q')

    async def test_editor_failure_preserves_successful_creation(self):
        app = self.app()
        def fail_open(args, log):
            raise OSError('VS Code is not installed')
        app.service.run = fail_open
        async with app.run_test(size=(80, 24)) as pilot:
            await self.ready(app, pilot)
            await app.push_screen(NewSandbox())
            draft = self.draft()
            draft['open_editor'] = True
            await app.push_screen(SettingsForm(draft))
            app.screen.submit(draft, {})
            await self.ready(app, pilot)
            self.assertEqual(app.service.calls[0][0], 'create')
            self.assertTrue(app.screen.finished)
            self.assertFalse(app.screen.failed)
            output = '\n'.join(line.text for line in app.screen.query_one(RichLog).lines)
            self.assertIn('Sandbox created, but the editor could not open', output)
            self.assertIn('try again', output)
            await pilot.press('escape')
            await self.ready(app, pilot)
            await pilot.press('q')
