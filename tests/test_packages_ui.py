"""Installed-package actions and installation navigation."""
import unittest
from unittest.mock import patch

from textual.widgets import Button, Collapsible, Input, Select, Static
from pi_sandbox_factory import registry
from pi_sandbox_factory.sandbox_tui import Cockpit, Confirm, InstallPackage, Operation, PackageRow, PackagesScreen
from test_tui import FakeService
import test_tui


class PackageUITests(unittest.TestCase):
    setUpClass = classmethod(test_tui.TUITests.setUpClass.__func__)
    tearDownClass = classmethod(test_tui.TUITests.tearDownClass.__func__)
    _callTestMethod = test_tui.TUITests._callTestMethod
    setUp = test_tui.TUITests.setUp
    tearDown = test_tui.TUITests.tearDown
    ready = test_tui.TUITests.ready

    async def test_installed_rows_actions_and_refresh(self):
        entries = {'company': {'description': 'Company models', 'source': 'https://example.com/providers.git', 'subdir': 'company', 'ref': 'main'}}
        service = FakeService([])
        original = service.run
        def run(args, log):
            original(args, log)
            if args[1] == 'remove': entries.pop(args[2])
        service.run = run
        app = Cockpit(self.root, service)
        with patch.object(registry, 'installed', side_effect=lambda kind: entries if kind == 'provider' else {}), patch.object(registry, 'choices', side_effect=lambda kind: {'base': 'Default Developer Sandbox'} if kind == 'profile' else {'local': 'Local models', **{k: v['description'] for k, v in entries.items()}}):
            async with app.run_test(size=(80, 24)) as pilot:
                await self.ready(app, pilot)
                await pilot.click('#packages'); await pilot.pause()
                listing = app.screen
                self.assertEqual(len(listing.query(PackageRow)), 1)
                self.assertEqual(len(listing.query(PackageRow).first().query(Button)), 0)
                listing.query_one('#package-kind', Select).value = 'provider'
                await pilot.pause()
                row = list(listing.query(PackageRow))[-1]
                update, remove = list(row.query(Button))
                update.focus(); update.scroll_visible(animate=False); await pilot.pause()
                await pilot.press('enter'); await self.ready(app, pilot)
                self.assertEqual(service.calls[-1], ['provider', 'update', 'company'])
                self.assertIsInstance(app.screen, Operation)
                await pilot.press('escape'); await pilot.pause()
                self.assertIs(app.screen, listing)
                self.assertEqual(listing.query_one('#package-kind', Select).value, 'provider')
                for confirm in (False, True):
                    row = list(listing.query(PackageRow))[-1]
                    remove = list(row.query(Button))[-1]
                    remove.focus(); remove.scroll_visible(animate=False); await pilot.pause()
                    await pilot.press('enter'); await pilot.pause()
                    self.assertIsInstance(app.screen, Confirm)
                    if not confirm:
                        await pilot.press('escape'); await pilot.pause()
                        self.assertEqual(len(service.calls), 1)
                    else:
                        await pilot.click('#yes'); await self.ready(app, pilot)
                        self.assertEqual(service.calls[-1], ['provider', 'remove', 'company'])
                        await pilot.press('escape'); await pilot.pause()
                self.assertEqual(len(listing.query(PackageRow)), 1)
                await pilot.click('#package-install'); await pilot.pause()
                self.assertEqual(app.screen.kind, 'provider')
                await pilot.press('escape'); await pilot.pause()
                self.assertIs(app.screen, listing)

    async def test_install_validation_and_optional_revision(self):
        service = FakeService([]); app = Cockpit(self.root, service)
        with patch.object(registry, 'installed', return_value={}):
            async with app.run_test(size=(80, 24)) as pilot:
                await self.ready(app, pilot)
                await pilot.click('#packages'); await pilot.pause()
                await pilot.click('#package-install'); await pilot.pause()
                form = app.screen
                await pilot.click('#package-add'); await pilot.pause()
                self.assertIs(app.screen, form)
                self.assertIn('local name', str(form.query_one('#package-error', Static).render()))
                self.assertEqual(service.calls, [])
                form.query_one('#package-name', Input).value = 'reporting'
                form.query_one('#package-source', Input).value = str(self.root)
                form.query_one('#package-subdir', Input).value = '../outside'
                await pilot.click('#package-add'); await pilot.pause()
                self.assertIn('inside', str(form.query_one('#package-error', Static).render()))
                form.query_one('#package-subdir', Input).value = 'profiles/reporting'
                form.query_one('#package-ref', Input).value = 'v1'
                await pilot.pause(0.3)
                await pilot.click('#package-add'); await self.ready(app, pilot)
                self.assertTrue(service.calls, str(form.query_one('#package-error', Static).render()) if app.screen is form else str(app.screen))
                self.assertEqual(service.calls[-1], ['profile', 'add', 'reporting', str(self.root), '--ref', 'v1', '--subdir', 'profiles/reporting'])
                await pilot.press('escape'); await pilot.pause()
                self.assertIsInstance(app.screen, PackagesScreen)

    async def test_package_pages_have_padded_reachable_actions(self):
        record = {'description': 'Reporting tools for a development team', 'source': 'https://example.com/' + 'long-repository-name/' * 8}
        for size in ((80, 24), (120, 40)):
            app = Cockpit(self.root, FakeService([]))
            with patch.object(registry, 'installed', return_value={'reporting': record}), patch.object(registry, 'choices', return_value={'base': 'Default Developer Sandbox', 'reporting': record['description']}):
                async with app.run_test(size=size) as pilot:
                    await self.ready(app, pilot)
                    await pilot.click('#packages'); await pilot.pause()
                    for primary_id in ('package-install', 'package-add'):
                        primary = app.screen.query_one('#'+primary_id, Button)
                        bar = app.screen.query_one('.wizard-actions')
                        self.assertEqual(primary.region.right, bar.content_region.right)
                        self.assertGreater(primary.region.y, bar.region.y)
                        self.assertLess(primary.region.bottom, app.screen.query_one('Footer').region.y)
                        self.assertEqual(primary.region.height, 3 if size[1] >= 32 else 1)
                        self.assertIs(app.screen.get_widget_at(primary.region.x, primary.region.y)[0], primary)
                        if primary_id == 'package-install':
                            await pilot.click('#package-install'); await pilot.pause()
                    app.screen.query_one(Collapsible).collapsed = False
                    field = app.screen.query_one('#package-ref', Input)
                    field.focus(); field.scroll_visible(animate=False); await pilot.pause()
                    self.assertLessEqual(field.region.bottom, app.screen.query_one('.wizard-actions').region.y)
                    await pilot.press('escape'); await pilot.pause()
                    self.assertIsInstance(app.screen, PackagesScreen)
