"""Editor selection, private connection settings and terminal layout."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Button, Collapsible, Footer, Input, OptionList, Select, Static
from pi_sandbox_factory import editor_settings
from pi_sandbox_factory.editor_ui import EditorFields, EditorScreen, OpenWith
from pi_sandbox_factory.sandbox_tui import Cockpit, Operation
from pi_sandbox_factory.tui_widgets import Checkbox
from test_tui import FakeService


class EditorUI(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'demo'
        self.state.mkdir()
        for name in ('available_update',):
            mock = patch('pi_sandbox_factory.updates.' + name, return_value=None)
            mock.start(); self.addCleanup(mock.stop)
        self.app = Cockpit(self.root, FakeService([]))

    async def ready(self, pilot):
        await pilot.pause()
        await self.app.workers.wait_for_complete()
        await pilot.pause()

    async def test_default_connection_password_and_layout(self):
        for size in ((80, 24), (120, 40)):
            self.app = Cockpit(self.root, FakeService([]))
            async with self.app.run_test(size=size) as pilot:
                await self.ready(pilot)
                await self.app.push_screen(EditorScreen('demo'))
                await pilot.pause()
                screen = self.app.screen
                fields = screen.query_one(EditorFields)
                self.assertEqual(fields.collect(), editor_settings.DEFAULTS)
                screen.query_one('#editor-connection', Collapsible).collapsed = False
                screen.query_one('#editor-auth', Checkbox).value = True
                await pilot.pause()
                screen.query_one('#editor-password').scroll_visible(animate=False)
                await pilot.pause()
                password = screen.query_one('#editor-password', Input)
                generate = screen.query_one('#editor-generate', Button)
                self.assertEqual(password.region.height, 3)
                self.assertEqual(generate.region.height, password.region.height)
                self.assertEqual(generate.region.y, password.region.y)
                await pilot.click('#editor-generate')
                await pilot.pause()
                self.assertGreaterEqual(len(password.value), 24)
                self.assertFalse(password.password)
                self.assertLess(generate.region.right, screen.query_one('#editor-connection').content_region.right)
                self.assertTrue(fields.collect()['password_hash'].startswith('$argon2id$'))
                save = screen.query_one('#editor-save')
                actions = screen.query_one('.wizard-actions')
                self.assertEqual(save.region.right, actions.content_region.right)
                self.assertLess(save.region.bottom, screen.query_one(Footer).region.y)
                self.app.save_screenshot(filename=f'editor-settings-{size[0]}.svg', path='/tmp')
                await pilot.press('escape')
                self.assertFalse((self.state / 'editor.json').exists())

    async def test_save_without_recreating_and_password_stays_masked(self):
        async with self.app.run_test(size=(80, 24)) as pilot:
            await self.ready(pilot)
            await self.app.push_screen(EditorScreen('demo'))
            await pilot.pause()
            screen = self.app.screen
            screen.query_one('#editor-auth', Checkbox).value = True
            screen.query_one('#editor-password', Input).value = 'synthetic-password-only'
            with patch('pi_sandbox_factory.browser_editor.stop') as stop:
                await pilot.click('#editor-save')
                await self.ready(pilot)
                stop.assert_called_once_with(self.state)
            self.assertIsInstance(self.app.screen, Operation)
            self.assertFalse(self.app.screen.failed)
            self.assertEqual(self.app.service.calls, [])
            value = editor_settings.load(self.state)
            await pilot.press('escape')
            await self.app.push_screen(EditorScreen('demo'))
            await pilot.pause()
            password = self.app.screen.query_one('#editor-password', Input)
            self.assertEqual(password.value, '')
            self.assertTrue(password.password)
            self.assertEqual(self.app.screen.query_one(EditorFields).collect(), value)
            with patch('pi_sandbox_factory.browser_editor.stop') as stop:
                await pilot.click('#editor-save'); await pilot.pause()
                stop.assert_not_called()

    async def test_defaults_show_only_the_client_and_summary_updates(self):
        from pi_sandbox_factory.sandbox_tui import DEFAULT_SETTINGS, SettingsForm, preset
        import copy
        async with self.app.run_test(size=(80, 24)) as pilot:
            await self.ready(pilot)
            await self.app.push_screen(SettingsForm(preset('base', copy.deepcopy(DEFAULT_SETTINGS)), defaults=True))
            await pilot.pause()
            screen = self.app.screen
            self.assertFalse(screen.query('#editor-address, #editor-password, #editor-connection'))
            screen.query_one('#editor-mode', Select).value = 'pi'
            await pilot.pause()
            self.assertEqual(screen.query_one('#editor-section', Collapsible).title, 'Editor · Pi CLI')
            self.assertEqual(screen.query_one(EditorFields).collect(), {**editor_settings.DEFAULTS, 'mode': 'pi'})

    async def test_remote_validation_and_mode_selection(self):
        async with self.app.run_test(size=(80, 24)) as pilot:
            await self.ready(pilot)
            await self.app.push_screen(EditorScreen('demo'))
            await pilot.pause()
            screen = self.app.screen
            screen.query_one('#editor-address', Input).value = '192.0.2.1'
            await pilot.pause()
            self.assertTrue(screen.query_one('#editor-tls-fields').display)
            await pilot.click('#editor-save'); await pilot.pause()
            self.assertIn('password', str(screen.query_one('#editor-error', Static).render()))
            screen.query_one('#editor-address', Input).value = ''
            screen.query_one('#editor-mode', Select).value = 'pi'
            await pilot.pause()
            self.assertFalse(screen.query_one('#editor-connection').display)
            self.assertEqual(screen.query_one(EditorFields).collect()['mode'], 'pi')
            await pilot.press('escape')
            (self.state / 'browser-editor.enabled').touch()
            result = []
            await self.app.push_screen(OpenWith(desktop_allowed=False), result.append)
            await pilot.pause()
            menu = self.app.screen.query_one(OptionList)
            self.assertTrue(menu.get_option_at_index(2).disabled)
            menu.highlighted = 1; menu.focus()
            await pilot.press('enter'); await pilot.pause()
            self.assertEqual(result, ['pi'])
