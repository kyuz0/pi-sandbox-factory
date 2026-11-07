import asyncio
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pi_sandbox_factory import sandbox
from pi_sandbox_factory.sandbox_tui import Cockpit, Confirm, NewSandbox, SettingsForm, Operation, DEFAULT_SETTINGS, Service, SettingsMenu
from textual.widgets import Input, Button, DataTable, Checkbox, TextArea, OptionList

class FakeService:
    def __init__(self,records): self.records=records;self.calls=[]
    def inventory(self):return copy.deepcopy(self.records)
    def start(self,name,log):self.calls.append(['start',name]);log('ready')
    def run(self,args,log):
        self.calls.append(args);log('done')
        if args[0]=='delete':self.records=[r for r in self.records if r['name']!=args[1]]
    def create(self,draft,key,log):self.calls.append(['create',draft]);log('created')
    def update(self,name,draft,key,log):self.calls.append(['update',name,draft]);log('updated')
    def provider(self,name,provider,mode,key,log):self.calls.append(['provider',name,provider,mode,key]);log('Provider ready')
    def models(self,name,mode,log):self.calls.append(['models',name,mode]);log('Model catalogue')

class TUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.runner=asyncio.Runner()
    @classmethod
    def tearDownClass(cls):cls.runner.close()
    def _callTestMethod(self,method):self.runner.run(method())
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.search_keys=patch('pi_sandbox_factory.sandbox_tui.search_keys_path', return_value=self.root/'web-access-keys.json');self.search_keys.start()
        self.defaults=patch('pi_sandbox_factory.sandbox_tui.load_defaults',side_effect=lambda:copy.deepcopy(DEFAULT_SETTINGS));self.defaults.start()
        self.update_check=patch('pi_sandbox_factory.updates.available_update',return_value=None);self.update_check.start()
        self.records=[]
        for name in ['alpha','beta']:
            state=self.root/name;state.mkdir();(state/'allowlist.txt').write_text('local-model.internal:8000\n')
            c=dict(name=name,engine='podman',network='allowlist',workspace=str(self.root/'files'/name),
                   profile=sandbox.load_profile('base'),local_model_ports='8000',memory='8g',subagents=False)
            self.records.append(dict(name=name,profile='base',engine='podman',dev='running',proxy='running',workspace=c['workspace'],config=c))
    def tearDown(self):self.update_check.stop();self.defaults.stop();self.search_keys.stop();self.tmp.cleanup()
    async def ready(self,app,pilot):
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

    async def settings_page(self, app, pilot, action="configuration"):
        await pilot.click('#settings');await pilot.pause()
        menu=app.screen.query_one('#settings-actions',OptionList)
        menu.highlighted=next(i for i, (_, key) in enumerate(SettingsMenu.ACTIONS) if key == action);menu.focus()
        await pilot.press('enter');await pilot.pause()

    async def delete_menu(self, app, pilot):
        await pilot.click('#more');await pilot.pause()
        menu=app.screen.query_one('#more-actions',OptionList)
        menu.highlighted=5;menu.focus()
        await pilot.press('enter');await pilot.pause()

    async def test_banner_and_update_notice_fit_small_and_large_terminals(self):
        for size in ((80,24),(120,40)):
            app=Cockpit(self.root,FakeService(self.records))
            async with app.run_test(size=size) as pilot:
                await self.ready(app,pilot)
                with patch('pi_sandbox_factory.updates.pipx_install',return_value=True), patch('pi_sandbox_factory.sandbox_tui.shutil.which',return_value='/bin/pipx'):
                    app.show_update('2099.1.1.1')
                await pilot.pause()
                title=app.query_one('#title-banner')
                self.assertEqual(title.content_region.height,1 if size[0]==80 else 9)
                self.assertEqual(title.styles.padding.top,1)
                self.assertFalse(app.query_one('#application-update-run',Button).disabled)
                self.assertLess(app.query_one('#new').region.bottom,size[1])
                self.assertLess(app.query_one('#more').region.bottom,size[1])
                self.assertGreaterEqual(app.query_one('#sandboxes').region.height,5)
                self.assertIn('pipx upgrade pi-sandbox-factory',str(app.query_one('#application-update-message').render()))
                self.assertTrue(await pilot.click('#settings'))
                await pilot.pause()
                self.assertEqual(type(app.screen).__name__,'SettingsMenu')

    async def test_update_requires_confirmation_and_reports_failure(self):
        from contextlib import nullcontext
        import subprocess
        app=Cockpit(self.root,FakeService([]))
        async with app.run_test(size=(100,36)) as pilot:
            await self.ready(app,pilot)
            with patch('pi_sandbox_factory.updates.pipx_install',return_value=True), patch('pi_sandbox_factory.sandbox_tui.shutil.which',return_value='/bin/pipx'):
                app.show_update('2099.1.1.1')
            await pilot.pause()
            with patch.object(app,'suspend',return_value=nullcontext()), patch('pi_sandbox_factory.sandbox_tui.subprocess.run',side_effect=subprocess.CalledProcessError(1,['pipx'])) as run:
                await pilot.click('#application-update-run');await pilot.pause()
                self.assertIsInstance(app.screen,Confirm)
                await pilot.click('#cancel');await pilot.pause()
                run.assert_not_called()
                await pilot.click('#application-update-run');await pilot.pause()
                await pilot.click('#yes');await pilot.pause()
                run.assert_called_once_with(('pipx','upgrade','pi-sandbox-factory'),check=True)
                self.assertIn('Upgrade failed',str(app.query_one('#application-update-message').render()))
                self.assertFalse(app.query_one('#application-update-run',Button).disabled)

    async def test_successful_update_relaunches_and_source_install_disables_button(self):
        from contextlib import nullcontext
        from pi_sandbox_factory import updates
        app=Cockpit(self.root,FakeService([]))
        async with app.run_test(size=(100,36)) as pilot:
            await self.ready(app,pilot)
            with patch('pi_sandbox_factory.updates.pipx_install',return_value=False):
                app.show_update('2099.1.1.1')
            self.assertTrue(app.query_one('#application-update-run',Button).disabled)
            with patch.object(app,'suspend',return_value=nullcontext()), patch('pi_sandbox_factory.sandbox_tui.subprocess.run'), patch.object(app,'exit') as finish:
                app.upgrade(True)
                finish.assert_called_once_with(result=updates.RELAUNCH)

    async def test_new_shortcut_works_while_search_has_focus(self):
        for records in ([], self.records):
            with self.subTest(empty=not records):
                # Search includes workspace paths; random temporary names can contain 'n'.
                records = copy.deepcopy(records)
                for record in records:
                    record['workspace'] = '/work/' + record['name']
                app = Cockpit(self.root, FakeService(records))
                async with app.run_test(size=(80,24)) as pilot:
                    await self.ready(app, pilot)
                    search = app.query_one('#search', Input)
                    search.focus()
                    await pilot.press('n')
                    self.assertEqual(search.value, 'n')
                    details = str(app.query_one('#details').render())
                    self.assertIn('F2', details)
                    self.assertIn('No matching' if records else 'No sandboxes yet', details)
                    await pilot.press('f2')
                    await pilot.pause()
                    self.assertIsInstance(app.screen, NewSandbox)
                    screen = app.screen
                    await pilot.press('f2')
                    self.assertIs(app.screen, screen)
                    await pilot.press('escape')
                    await pilot.pause()
                    self.assertEqual(app.query_one('#search', Input).value, 'n')
                    await pilot.click('#new')
                    await pilot.pause()
                    self.assertIsInstance(app.screen, NewSandbox)

    async def test_advisors_live_in_settings_and_allow_initial_setup(self):
        from pi_sandbox_factory.sandbox_tui import AdvisorsScreen
        service=FakeService(self.records)
        service.advisors=lambda name,settings,log:service.calls.append(['advisors',name,settings])
        app=Cockpit(self.root,service)
        async with app.run_test(size=(100,36)) as pilot:
            await self.ready(app,pilot)
            await self.settings_page(app,pilot,action="advisors")
            self.assertIsInstance(app.screen,AdvisorsScreen)
            self.assertTrue(app.screen.query_one('#advisor-login-codex',Button).disabled)
            self.assertLess(app.screen.query_one('#advisor-login-codex',Button).region.bottom, 34)
            self.assertIn('only after the advisor has been added', str(app.screen.query_one('#advisor-login-help').render()))
            app.screen.query_one('#advisor-codex',Checkbox).value=True
            await pilot.pause()
            self.assertTrue(app.screen.query_one('#advisor-login-codex',Button).disabled)
            app.screen.query_one('#advisor-codex',Checkbox).value=False
            app.screen.query_one('#advisor-agy',Checkbox).value=True
            await pilot.click('#advisor-apply');await pilot.pause()
            self.assertIsInstance(app.screen,Confirm)
            await pilot.click('#yes');await self.ready(app,pilot)
            self.assertEqual(service.calls[0][0:2],['advisors','alpha'])
            self.assertEqual(service.calls[0][2]['providers'],['agy'])
            self.assertEqual(service.calls[0][2]['agy_model'],'')
            await pilot.press('q')

    async def test_advisor_worker_can_start_after_settings_screen_closes(self):
        from pi_sandbox_factory.sandbox_tui import AdvisorsScreen
        service = FakeService(self.records)
        service.advisors = lambda name, settings, log: service.calls.append(['advisors', name])
        app = Cockpit(self.root, service)
        # Hold the worker until Textual has removed the settings screen.
        with patch.object(Operation, 'on_mount', return_value=None):
            async with app.run_test(size=(100, 36)) as pilot:
                await self.ready(app, pilot)
                screen = AdvisorsScreen(self.records[0])
                await app.push_screen(screen)
                await pilot.pause()
                screen.query_one('#advisor-codex', Checkbox).value = True
                await pilot.click('#advisor-apply')
                await pilot.pause()
                await pilot.click('#yes')
                await self.ready(app, pilot)
                self.assertIsNone(screen.parent)
                operation = app.screen
                self.assertIsInstance(operation, Operation)
                operation.execute()
                await self.ready(app, pilot)
                self.assertFalse(operation.failed)
                self.assertEqual(service.calls, [['advisors', 'alpha']])

    async def test_models_without_provider_plugins(self):
        from pi_sandbox_factory.sandbox_tui import ModelsScreen
        from textual.widgets import Select
        self.records[0]['config']['model_providers'] = []
        service = FakeService(self.records)
        app = Cockpit(self.root, service)
        async with app.run_test(size=(80, 24)) as pilot:
            await self.ready(app, pilot)
            await app.push_screen(ModelsScreen(self.records[0]))
            await pilot.pause()
            self.assertIs(app.screen.query_one('#model-provider', Select).value, Select.NULL)
            for action in ('status', 'preview', 'refresh', 'auth'):
                self.assertTrue(app.screen.query_one('#provider-' + action, Button).disabled)
            self.assertFalse(app.screen.query_one('#configuration', Button).disabled)
            self.assertEqual(service.calls, [])
            await pilot.press('escape')
            self.assertNotIsInstance(app.screen, ModelsScreen)

    async def test_models_refresh_selected_provider(self):
        from pi_sandbox_factory.sandbox_tui import ModelsScreen
        from textual.widgets import Select
        self.records[0]['config']['model_providers'] = [
            {'name': 'local', 'manifest': {'description': 'Local models'}}]
        service = FakeService(self.records)
        app = Cockpit(self.root, service)
        async with app.run_test(size=(120, 40)) as pilot:
            await self.ready(app, pilot)
            await app.push_screen(ModelsScreen(self.records[0]))
            await pilot.pause()
            self.assertEqual(app.screen.query_one('#model-provider', Select).value, 'local')
            await pilot.click('#provider-refresh')
            await self.ready(app, pilot)
            self.assertEqual(service.calls, [['provider', 'alpha', 'local', 'refresh', None]])

    async def test_saved_codex_advisor_enables_login(self):
        self.records[0]['config']['advisors'] = {'providers': ['codex']}
        app = Cockpit(self.root, FakeService(self.records))
        async with app.run_test(size=(100,36)) as pilot:
            await self.ready(app, pilot)
            await self.settings_page(app, pilot, action="advisors")
            self.assertFalse(app.screen.query_one('#advisor-login-codex', Button).disabled)
            self.assertTrue(app.screen.query_one('#advisor-login-agy', Button).disabled)
            self.assertTrue(app.screen.query_one('#advisor-login-claude', Button).disabled)
            await pilot.press('q')

    async def test_claude_login_and_settings_at_small_terminal(self):
        from textual.widgets import Select
        self.records[0]['config']['advisors'] = {'providers':['claude']}
        service=FakeService(self.records)
        service.advisors=lambda name,settings,log:service.calls.append(['advisors',name,settings])
        app=Cockpit(self.root,service)
        async with app.run_test(size=(80,24)) as pilot:
            await self.ready(app,pilot)
            await self.settings_page(app,pilot,action="advisors")
            self.assertFalse(app.screen.query_one('#advisor-login-claude',Button).disabled)
            self.assertTrue(app.screen.query_one('#advisor-login-codex',Button).disabled)
            app.screen.query_one('#advisor-claude-model',Input).value='claude-sonnet-test'
            app.screen.query_one('#advisor-claude-effort',Select).value='high'
            await pilot.click('#advisor-apply');await pilot.pause()
            await pilot.click('#yes');await self.ready(app,pilot)
            self.assertEqual(service.calls[0][2]['providers'],['claude'])
            self.assertEqual(service.calls[0][2]['claude_model'],'claude-sonnet-test')
            self.assertEqual(service.calls[0][2]['claude_effort'],'high')
            await pilot.press('q')

    async def test_repository_setup_and_key_display(self):
        from pi_sandbox_factory.sandbox_tui import SSHScreen
        from pi_sandbox_factory.repository_ui import RepositorySetup, PublicKey
        from textual.widgets import Collapsible
        for size in ((80, 24), (120, 40), (220, 50)):
            service = FakeService(self.records)
            app = Cockpit(self.root, service)
            async with app.run_test(size=size) as pilot:
                await self.ready(app, pilot)
                await app.push_screen(SSHScreen(self.records[0]))
                self.assertTrue(app.screen.query_one('#ssh-generate-key', Button).disabled)
                await app.push_screen(RepositorySetup(), app.screen.add_repository)
                await pilot.pause()
                app.screen.query_one('#repository-url', Input).value = 'https://github.com/team/project'
                await pilot.pause()
                button = app.screen.query_one('#repository-add', Button)
                self.assertGreaterEqual(button.region.x, 0)
                self.assertLess(button.region.bottom, size[1])
                await pilot.click('#repository-add');await pilot.pause()
                self.assertEqual(app.screen.query_one('#ssh-hosts', TextArea).text, 'repository git github.com 22')
                # Existing aliases must not silently switch hosts.
                app.screen.add_repository({'line': 'repository git gitlab.com 22'})
                self.assertEqual(app.screen.query_one('#ssh-hosts', TextArea).text, 'repository git github.com 22')
                with patch.object(service, 'ssh_key', create=True, return_value='ssh-ed25519 AAAA fixture'):
                    await app.push_screen(PublicKey('alpha', generate=True))
                    await pilot.pause();await app.workers.wait_for_complete();await pilot.pause()
                    self.assertEqual(app.screen.query_one('#key-public', TextArea).text, 'ssh-ed25519 AAAA fixture')
                    self.assertFalse(app.screen.query_one('#key-copy', Button).disabled)
                    self.assertLess(app.screen.query_one('#key-copy').region.bottom, size[1])
                    with patch.object(app, 'copy_to_clipboard') as copy_key:
                        await pilot.click('#key-copy')
                        copy_key.assert_called_once_with('ssh-ed25519 AAAA fixture')
                    await pilot.press('escape')
                with patch.object(service, 'ssh_key', create=True, side_effect=ValueError('Unlock first')):
                    await app.push_screen(PublicKey('alpha'))
                    await pilot.pause();await app.workers.wait_for_complete();await pilot.pause()
                    self.assertTrue(app.screen.query_one('#key-copy', Button).disabled)
                    self.assertIn('Unlock first', str(app.screen.query_one('#key-status').render()))
                    await pilot.press('escape')
                await pilot.press('escape')

    async def test_ssh_settings_keep_key_import_separate(self):
        from pi_sandbox_factory.sandbox_tui import SSHScreen
        service=FakeService(self.records);app=Cockpit(self.root,service)
        async with app.run_test(size=(100,36)) as pilot:
            await self.ready(app,pilot);await self.settings_page(app,pilot,action="ssh-settings")
            self.assertIsInstance(app.screen,SSHScreen)
            self.assertTrue(app.screen.query_one('#ssh-import-key',Button).disabled)
            self.assertEqual(app.screen.query_one('#ssh-key-file',Input).value,'')
            await pilot.press('escape');await pilot.pause()
            self.assertFalse(service.calls)
            await pilot.press('q')

    async def test_selection_delete_cancel_and_preserved_other_entry(self):
        service=FakeService(self.records);app=Cockpit(self.root,service)
        async with app.run_test(size=(100,32)) as pilot:
            await self.ready(app,pilot)
            table=app.query_one(DataTable);self.assertEqual(table.row_count,2)
            table.move_cursor(row=1);await pilot.pause()
            await self.delete_menu(app,pilot)
            self.assertIsInstance(app.screen,Confirm);self.assertIn('beta',app.screen.message)
            self.assertIn('workspace',app.screen.message)
            await pilot.click('#cancel');await pilot.pause();self.assertFalse(service.calls)
            await self.delete_menu(app,pilot);await pilot.click('#yes');await self.ready(app,pilot)
            self.assertEqual(service.calls,[['delete','beta']])
            await pilot.click('#operation-back');await self.ready(app,pilot)
            self.assertEqual([r['name'] for r in app.records],['alpha'])
            await pilot.press('q')

    async def test_create_from_is_visible_and_copies_settings_without_credentials(self):
        from pi_sandbox_factory.sandbox_tui import CreateFromSandbox, WebAccessForm
        from textual.widgets import Select
        record = self.records[0]
        record['config'].update(
            memory='16g', subagents=True, env_file='/private/keys.env', pi_config='/private/pi',
            options={'browser': True, 'goals': False, 'website_groups': ['dev-python'],
                     'web_access': {'enabled': True, 'providers': {'exa': {'has_key': True}}}},
            advisors={'providers': ['claude'], 'claude_model': 'opus', 'claude_effort': 'high'})
        original = copy.deepcopy(record)
        service = FakeService(self.records)
        service.search_keys = lambda name: self.fail('Keys must require explicit selection')
        workspace = self.root / 'new-project'
        workspace.mkdir()
        app = Cockpit(self.root, service)
        with patch('pi_sandbox_factory.web_access.saved_keys', return_value={'exa': 'workstation-key'}) as defaults:
            async with app.run_test(size=(80,24)) as pilot:
                await self.ready(app,pilot)
                button = app.query_one('#create-from', Button)
                self.assertFalse(button.disabled)
                self.assertLessEqual(button.region.right,80)
                self.assertTrue(await pilot.click('#create-from'))
                await pilot.pause()
                self.assertIsInstance(app.screen,CreateFromSandbox)
                self.assertEqual(app.screen.query_one('#copy-source',Select).value,'alpha')
                self.assertFalse(app.screen.query_one('#copy-keys',Checkbox).value)
                self.assertTrue(await pilot.click('#copy-continue'))
                await pilot.pause()
                self.assertIsInstance(app.screen,NewSandbox)
                self.assertEqual(app.screen.query_one('#workspace',Input).value,'')
                self.assertEqual(app.screen.query_one('#name',Input).value,'')
                app.screen.query_one('#workspace',Input).value=str(workspace)
                await pilot.pause()
                app.screen.query_one('#name',Input).value='copied-agent'
                await pilot.click('#continue'); await pilot.pause()
                self.assertIsInstance(app.screen,SettingsForm, str(app.screen.query_one('#new-error').render()) if isinstance(app.screen,NewSandbox) else '')
                self.assertEqual(app.screen.query_one(WebAccessForm).keys,{})
                defaults.assert_not_called()
                self.assertTrue(app.screen.query_one('#browser',Checkbox).value)
                self.assertEqual(app.screen.query_one('#env-file',Input).value,'')
                self.assertEqual(app.screen.query_one('#pi-config',Input).value,'')
                with patch('pi_sandbox_factory.sandbox.choose_engine',return_value='podman'):
                    await pilot.click('#apply'); await self.ready(app,pilot)
                draft = service.calls[0][1]
                self.assertEqual(draft['reuse_from'],'alpha')
                self.assertEqual(draft['name'],'copied-agent')
                self.assertEqual(draft['memory'],'16g')
                self.assertEqual(draft['advisors']['claude_model'],'opus')
                self.assertEqual(draft['options']['website_groups'],['dev-python'])
                self.assertEqual(record,original)

    async def test_create_from_copies_keys_only_when_selected_and_handles_stopped_source(self):
        from pi_sandbox_factory.sandbox_tui import WebAccessForm
        from textual.widgets import Select
        self.records[0]['config']['options']={'web_access':{'enabled':True,'providers':{'exa':{'has_key':True}}}}
        self.records[1]['dev']='exited'
        service=FakeService(self.records)
        from unittest.mock import Mock
        service.search_keys=Mock(return_value={'exa':{'endpoint':'','key':'synthetic'}})
        app=Cockpit(self.root,service)
        async with app.run_test(size=(100,36)) as pilot:
            await self.ready(app,pilot)
            await pilot.click('#create-from');await pilot.pause()
            app.screen.query_one('#copy-source',Select).value='beta';await pilot.pause()
            self.assertTrue(app.screen.query_one('#copy-keys',Checkbox).disabled)
            app.screen.query_one('#copy-source',Select).value='alpha';await pilot.pause()
            app.screen.query_one('#copy-keys',Checkbox).value=True
            await pilot.click('#copy-continue');await pilot.pause()
            service.search_keys.assert_called_once_with('alpha')
            self.assertEqual(app.screen.search_keys,{'exa':'synthetic'})
            await pilot.press('escape');await pilot.pause()
            self.assertFalse(service.calls)

    async def test_create_from_disabled_for_empty_inventory(self):
        app=Cockpit(self.root,FakeService([]))
        async with app.run_test(size=(80,24)) as pilot:
            await self.ready(app,pilot)
            self.assertTrue(app.query_one('#create-from',Button).disabled)

    async def test_create_uses_user_name_workspace_and_ports(self):
        service=FakeService([]);app=Cockpit(self.root,service)
        workspace=self.root/'my-files';workspace.mkdir()
        async with app.run_test(size=(100,42)) as pilot:
            await self.ready(app,pilot);await pilot.click('#new');await pilot.pause()
            self.assertIsInstance(app.screen,NewSandbox)
            app.screen.query_one('#workspace',Input).value=str(workspace);await pilot.pause()
            app.screen.query_one('#name',Input).value='my-agent'
            await pilot.click('#continue');await pilot.pause()
            self.assertIsInstance(app.screen,SettingsForm)
            self.assertFalse(app.screen.query('#pip-preset, #npm-preset, #github-preset'))
            for category in ('dev-python', 'dev-npmjs', 'dev-github'):
                app.screen.query_one('#category-'+category,Checkbox).value=True
            app.screen.query_one('#model-ports',Input).value='8002-8003'
            app.screen.query_one('#new-advisor-codex',Checkbox).value=True
            app.screen.query_one('#new-advisor-agy',Checkbox).value=True
            app.screen.query_one('#new-advisor-claude',Checkbox).value=True
            with patch('pi_sandbox_factory.sandbox.choose_engine',return_value='podman'):
                await pilot.click('#apply');await self.ready(app,pilot)
            self.assertIsInstance(app.screen,Operation)
            draft=service.calls[0][1]
            self.assertEqual(draft['name'],'my-agent');self.assertEqual(draft['workspace'],str(workspace))
            self.assertEqual(draft['allowlist'],'local-model.internal:8002\nlocal-model.internal:8003')
            self.assertEqual(draft['local_model_ports'],'8002-8003')
            self.assertEqual(draft['options']['website_groups'],['dev-python','dev-npmjs','dev-github'])
            self.assertEqual(draft['advisors']['providers'], ['codex', 'claude', 'agy'])
            await pilot.press('q')

    async def test_settings_and_models_follow_selection(self):
        service=FakeService(self.records);app=Cockpit(self.root,service)
        async with app.run_test(size=(100,42)) as pilot:
            await self.ready(app,pilot);app.query_one(DataTable).move_cursor(row=1);await pilot.pause()
            await self.settings_page(app,pilot)
            form=app.screen;self.assertIsInstance(form,SettingsForm)
            form.query_one('#model-ports',Input).value='8080'
            with patch('pi_sandbox_factory.sandbox.choose_engine',return_value='podman'):
                await pilot.click('#apply');await pilot.pause()
            self.assertIsInstance(app.screen,Confirm);await pilot.click('#yes');await self.ready(app,pilot)
            self.assertEqual(service.calls[0][0:2],['update','beta'])
            self.assertEqual(service.calls[0][2]['local_model_ports'],'8080')
            await pilot.click('#operation-back');await self.ready(app,pilot)
            app.query_one(DataTable).move_cursor(row=1);await pilot.pause()
            await self.settings_page(app,pilot,action="models")
            await pilot.click('#provider-preview');await self.ready(app,pilot)
            self.assertEqual(service.calls[-1],['provider','beta','local','preview',None])
            await pilot.press('q')

    async def test_home_controls_fit_and_theme_is_gold(self):
        app=Cockpit(self.root,FakeService(self.records))
        async with app.run_test(size=(80,24)) as pilot:
            await self.ready(app,pilot);self.assertEqual(app.theme,'cockpit-gold')
            for name in ['open','launch-with','settings','new','create-from','more','packages']:
                b=app.query_one('#'+name,Button)
                self.assertLessEqual(b.region.right,80,name);self.assertLessEqual(b.region.bottom,23,name)
            self.assertEqual(len(app.query('#home Button')),7)
            app.save_screenshot(filename='sandbox-home-declutter.svg',path='/tmp')
            await self.settings_page(app,pilot,action="network-settings")
            self.assertLessEqual(app.screen.query_one('#apply-network',Button).region.bottom,23)
            app.save_screenshot(filename='sandbox-network-declutter.svg',path='/tmp')
            await pilot.press('escape');await pilot.pause()
            await pilot.press('q')

    async def test_open_with_pi_uses_terminal_and_returns_to_manager(self):
        from contextlib import nullcontext
        import subprocess
        service=FakeService(self.records)
        service.command=Service(self.root).command
        app=Cockpit(self.root,service)
        async with app.run_test(size=(80,24)) as pilot:
            await self.ready(app,pilot)
            app.query_one(DataTable).move_cursor(row=1)
            with patch.object(app,'suspend',return_value=nullcontext()) as suspend, \
                 patch('pi_sandbox_factory.sandbox_tui.subprocess.run',return_value=subprocess.CompletedProcess([],0)) as run:
                await pilot.click('#launch-with');await pilot.pause()
                choices=app.screen.query_one('#editor-choices',OptionList)
                choices.highlighted=1;choices.focus()
                await pilot.press('enter');await self.ready(app,pilot)
                suspend.assert_called_once()
                run.assert_called_once_with(service.command('pi','beta'),check=False)
            self.assertEqual(len(app.screen_stack),1)
            self.assertEqual(app.selected_name(),'beta')
            app.query_one(DataTable).focus()
            await pilot.press('enter');await self.ready(app,pilot)
            self.assertEqual(service.calls,[['start','beta'],['open','beta','--editor','browser']])

    async def test_missing_model_is_completed_with_warning(self):
        app=Cockpit(self.root,FakeService(self.records))
        async with app.run_test(size=(80,24)) as pilot:
            await self.ready(app,pilot)
            app.push_screen(Operation('Opening sandbox',lambda log:log('Model status: Not connected. The sandbox is ready.')))
            await pilot.pause();await self.ready(app,pilot)
            self.assertTrue(app.screen.finished)
            self.assertFalse(app.screen.failed)
            self.assertTrue(app.screen.model_disconnected)
            self.assertTrue(app.screen.query_one('#operation-status').has_class('disconnected'))
            await pilot.press('escape');await self.ready(app,pilot)
            self.assertEqual(len(app.screen_stack),1)
            await pilot.press('q')


    async def test_network_action_applies_to_selected_sandbox(self):
        service=FakeService(self.records);app=Cockpit(self.root,service)
        async with app.run_test(size=(100,42)) as pilot:
            await self.ready(app,pilot)
            app.query_one(DataTable).move_cursor(row=1)
            await self.settings_page(app,pilot,action="network-settings")
            field=app.screen.query_one('#allowlist',TextArea)
            legacy='local-model.internal:8000\npypi.org:443\nregistry.npmjs.org:443\ngithub.com:443'
            field.load_text(legacy)
            for category in ('dev-python', 'dev-npmjs', 'dev-github'):
                app.screen.query_one('#category-'+category,Checkbox).value=True
            await pilot.pause()
            self.assertEqual(field.text,legacy)
            self.assertFalse(app.screen.query('#pip-preset, #npm-preset, #github-preset'))
            await pilot.click('#apply-network');await self.ready(app,pilot)
            self.assertEqual(service.calls[0][:2],['network','beta'])
            self.assertEqual(service.calls[0][-4:],['--website-groups','dev-python','dev-npmjs','dev-github'])
            self.assertIsInstance(app.screen,Operation)

    async def test_contextual_actions_and_empty_selection(self):
        self.records[1]['dev']='exited'
        app=Cockpit(self.root,FakeService(self.records))
        async with app.run_test(size=(80,24)) as pilot:
            await self.ready(app,pilot)
            await pilot.click('#more');await pilot.pause()
            self.assertEqual(app.screen.actions[0],('Stop sandbox','stop'))
            await pilot.press('escape');await pilot.pause()
            app.query_one(DataTable).move_cursor(row=1)
            await pilot.click('#more');await pilot.pause()
            self.assertEqual(app.screen.actions[0],('Start sandbox','start'))
            await pilot.press('escape');await pilot.pause()
            app.query_one('#search',Input).value='no-match';await pilot.pause()
            for name in ('open','launch-with','settings','more'):
                self.assertTrue(app.query_one('#'+name,Button).disabled)
            self.assertFalse(app.query_one('#new',Button).disabled)


    async def test_automatic_approval_default_and_human_fallback_selection(self):
        from textual.widgets import Select, Static
        service=FakeService(self.records);app=Cockpit(self.root,service)
        async with app.run_test(size=(100,36)) as pilot:
            await self.ready(app,pilot);await self.settings_page(app,pilot)
            choice=app.screen.query_one('#approval',Select)
            self.assertEqual(choice.value,'automatic')
            self.assertIn('no approval dialogs',str(app.screen.query_one('#approval-help',Static).render()))
            choice.value='assisted';await pilot.pause()
            self.assertIn('ask you',str(app.screen.query_one('#approval-help',Static).render()))
            await pilot.press('escape');await pilot.press('q')


    async def test_recall_selection_is_saved_at_small_terminal(self):
        from textual.widgets import Select, Collapsible
        service=FakeService(self.records);app=Cockpit(self.root,service)
        async with app.run_test(size=(80,24)) as pilot:
            await self.ready(app,pilot);await self.settings_page(app,pilot)
            form=app.screen
            form.query_one('#skills-section',Collapsible).collapsed=False
            choice=form.query_one('#compaction-recall',Select)
            self.assertEqual(choice.value,'lite')
            await pilot.pause();choice.focus();choice.scroll_visible(animate=False);await pilot.pause()
            await pilot.press('enter','down','enter');await pilot.pause()
            self.assertEqual(choice.value,'full')
            with patch('pi_sandbox_factory.sandbox.choose_engine',return_value='podman'):
                draft,_=form.collect()
            self.assertEqual(draft['options']['compaction_recall'],'full')
            choice.value='off'
            with patch('pi_sandbox_factory.sandbox.choose_engine',return_value='podman'):
                draft,_=form.collect()
            self.assertEqual(draft['options']['compaction_recall'],'off')

    async def test_package_install_at_small_terminal(self):
        service=FakeService(self.records);app=Cockpit(self.root,service)
        async with app.run_test(size=(80,24)) as pilot:
            await self.ready(app,pilot);await pilot.click('#packages');await pilot.pause()
            await pilot.click('#package-install');await pilot.pause()
            app.screen.query_one('#package-name',Input).value='reporting'
            app.screen.query_one('#package-source',Input).value=str(self.root)
            app.screen.query_one('#package-subdir',Input).value='profiles/reporting'
            button=app.screen.query_one('#package-add',Button)
            button.scroll_visible(animate=False);await pilot.pause()
            self.assertTrue(await pilot.click('#package-add'))
            await self.ready(app,pilot)
            self.assertEqual(service.calls[-1],['profile','add','reporting',str(self.root),'--subdir','profiles/reporting'])
            self.assertIsInstance(app.screen,Operation)

    async def test_saved_unregistered_provider_remains_in_configuration(self):
        from pi_sandbox_factory import registry
        provider={'name':'company','settings':{'endpoint':'https://models.example.com/v1'},
                  'manifest':{'description':'Company models','settings':{'endpoint':{'type':'text','network':True},'key':{'type':'secret'}}}}
        self.records[0]['config']['model_providers']=[provider]
        service=FakeService(self.records);app=Cockpit(self.root,service)
        with patch.object(registry,'choices',side_effect=lambda kind:{'base':'Generic tools'} if kind=='profile' else {'local':'Local models'}):
            async with app.run_test(size=(80,24)) as pilot:
                await self.ready(app,pilot);await self.settings_page(app,pilot)
                form=app.screen
                self.assertTrue(form.query_one('#source-company',Checkbox).value)
                self.assertEqual(form.query_one('#source-company-endpoint',Input).value,'https://models.example.com/v1')
                self.assertEqual(len(form.query('#source-company-key')),0)
                with patch('pi_sandbox_factory.sandbox.choose_engine',return_value='podman'):
                    draft,_=form.collect()
                self.assertEqual(draft['model_providers']['company'],provider['settings'])
                self.assertIn('models.example.com:443',draft['allowlist'])


class WebAccessUITests(unittest.TestCase):
    setUpClass = classmethod(TUITests.setUpClass.__func__)
    tearDownClass = classmethod(TUITests.tearDownClass.__func__)
    _callTestMethod = TUITests._callTestMethod
    setUp = TUITests.setUp
    tearDown = TUITests.tearDown
    ready = TUITests.ready
    async def test_web_settings_keep_key_out_of_saved_options(self):
        from pi_sandbox_factory.sandbox_tui import WebAccessForm, SearchProviderDialog, preset
        from textual.widgets import Select
        app = Cockpit(self.root, FakeService([]))
        async with app.run_test(size=(80,24)) as pilot:
            await self.ready(app, pilot)
            draft = preset('base', DEFAULT_SETTINGS)
            draft.update(name='web', workspace=str(self.root), local_model_ports=None)
            app.push_screen(SettingsForm(draft))
            await pilot.pause()
            form = app.screen
            web = form.query_one(WebAccessForm)
            web.query_one('#web-enabled', Checkbox).value = True
            web.query_one('#web-add', Button).press()
            await pilot.pause()
            self.assertIsInstance(app.screen, SearchProviderDialog)
            app.screen.query_one('#search-provider-name', Select).value = 'brave'
            await pilot.pause()
            app.screen.query_one('#search-key', Input).value = 'synthetic-test-key'
            app.screen.query_one('#search-save', Button).press()
            await pilot.pause()
            value, keys = form.collect()
            self.assertEqual(keys, {'brave': 'synthetic-test-key'})
            self.assertNotIn('synthetic-test-key', json.dumps(value))
            self.assertEqual(value['options']['web_access']['mode'], 'auto')
            self.assertTrue(value['options']['web_access']['providers']['brave']['has_key'])
            web.query_one('#web-mode', Select).value = 'brave'
            await pilot.pause()
            web.query_one('#web-edit-brave', Button).press()
            await pilot.pause()
            app.screen.query_one('#search-remove', Button).press()
            await pilot.pause()
            self.assertIsInstance(app.screen, SearchProviderDialog)
            self.assertIn('Choose another search mode', str(app.screen.query_one('#search-provider-error').render()))
            # Remove a key explicitly; an inactive selected provider cannot be applied.
            app.screen.query_one('#search-remove-key', Checkbox).value = True
            app.screen.query_one('#search-save', Button).press()
            await pilot.pause()
            with self.assertRaisesRegex(ValueError, 'Configure a search provider'):
                form.collect()
            web.query_one('#web-mode', Select).value = 'auto'
            await pilot.pause()
            value, keys = form.collect()
            self.assertEqual(keys, {'brave': ''})
            self.assertFalse(value['options']['web_access']['providers']['brave']['has_key'])
            web.query_one('#web-add', Button).press()
            await pilot.pause()
            app.screen.query_one('#search-provider-name', Select).value = 'searxng'
            await pilot.pause()
            self.assertFalse(app.screen.query_one('#search-key-field').display)
            app.screen.query_one('#search-endpoint', Input).value = 'https://search.example.net'
            app.screen.query_one('#search-save', Button).press()
            await pilot.pause()
            value, _ = form.collect()
            self.assertEqual(value['options']['web_access']['providers']['searxng']['endpoint'], 'https://search.example.net')

    async def test_save_web_defaults_preserves_other_defaults_and_keys_stay_private(self):
        from pi_sandbox_factory.sandbox_tui import WebAccessForm, preset
        from textual.widgets import Select
        app = Cockpit(self.root, FakeService([]))
        with patch('pi_sandbox_factory.sandbox_tui.defaults_path', return_value=self.root / 'cockpit.json'):
            async with app.run_test(size=(80,24)) as pilot:
                await self.ready(app, pilot)
                draft = preset('base', DEFAULT_SETTINGS)
                draft.update(name='web', workspace=str(self.root), local_model_ports=None)
                app.push_screen(SettingsForm(draft))
                await pilot.pause()
                web = app.screen.query_one(WebAccessForm)
                web.query_one('#web-enabled', Checkbox).value = True
                await web.provider_saved(('brave', {'endpoint': '', 'model': '', 'has_key': True}, 'test-default-brave'))
                web.query_one('#web-save-defaults', Button).press()
                await pilot.pause()
                saved = json.loads((self.root / 'cockpit.json').read_text())
                self.assertEqual(saved['memory'], DEFAULT_SETTINGS['memory'])
                self.assertNotIn('test-default-brave', json.dumps(saved))
                keyfile = self.root / 'web-access-keys.json'
                self.assertEqual(keyfile.stat().st_mode & 0o777, 0o600)
                self.assertEqual(json.loads(keyfile.read_text())['brave']['key'], 'test-default-brave')
                self.assertTrue(app.defaults['options']['web_access']['providers']['brave']['has_key'])

    async def test_copy_search_settings_without_keys_does_not_use_default_keys(self):
        from pi_sandbox_factory.sandbox_tui import WebAccessForm, CopyWebAccess, preset
        from pi_sandbox_factory import web_access
        source = self.records[0]
        source['config']['options'] = {'web_access': {'enabled': True, 'mode': 'auto',
            'providers': {'exa': {}, 'brave': {'has_key': True}}}}
        defaults = web_access.settings(source['config']['options']['web_access'])
        web_access.save_keys(self.root/'web-access-keys.json', defaults, {'brave': 'default-key'})
        app = Cockpit(self.root, FakeService(self.records))
        async with app.run_test(size=(80,24)) as pilot:
            await self.ready(app, pilot)
            draft = preset('base', DEFAULT_SETTINGS)
            draft['options']['web_access'] = defaults
            draft.update(name='new', workspace=str(self.root), local_model_ports=None)
            app.push_screen(SettingsForm(draft))
            await pilot.pause()
            form = app.screen
            web = form.query_one(WebAccessForm)
            self.assertEqual(web.keys['brave'], 'default-key')
            web.query_one('#web-copy', Button).press()
            await pilot.pause()
            self.assertIsInstance(app.screen, CopyWebAccess)
            app.screen.query_one('#copy-web-keys', Checkbox).value = False
            app.screen.query_one('#copy-web-apply', Button).press()
            await pilot.pause()
            value, keys = form.collect()
            self.assertEqual(keys['brave'], '')
            self.assertFalse(value['options']['web_access']['providers']['brave']['has_key'])
            self.assertNotIn('default-key', str(keys))
            self.assertTrue(source['config']['options']['web_access']['providers']['brave']['has_key'])
            source['dev'] = 'exited'
            web.query_one('#web-copy', Button).press()
            await pilot.pause()
            # Inventory is a snapshot; use its displayed state when selecting the source.
            app.screen.records['alpha']['dev'] = 'exited'
            app.screen.source_changed()
            self.assertTrue(app.screen.query_one('#copy-web-keys', Checkbox).disabled)
            self.assertFalse(app.screen.query_one('#copy-web-keys', Checkbox).value)

    async def test_edit_copy_without_keys_keeps_matching_target_key(self):
        from pi_sandbox_factory.sandbox_tui import WebAccessForm, preset
        from pi_sandbox_factory import web_access
        app = Cockpit(self.root, FakeService(self.records))
        async with app.run_test(size=(80,24)) as pilot:
            await self.ready(app, pilot)
            draft = preset('base', DEFAULT_SETTINGS)
            draft.update(name='alpha', workspace=str(self.root), local_model_ports=None)
            draft['options']['web_access'] = {'enabled': True, 'mode': 'auto', 'providers': {'exa': {}, 'brave': {'has_key': True}}}
            app.push_screen(SettingsForm(draft, editing=True))
            await pilot.pause()
            web = app.screen.query_one(WebAccessForm)
            copied = web_access.settings({'enabled': True, 'providers': {'exa': {}, 'brave': {}}})
            await web.copied((copied, None))
            value, keys = app.screen.collect()
            self.assertTrue(value['options']['web_access']['providers']['brave']['has_key'])
            self.assertNotIn('brave', keys)  # No key replacement or deletion queued.

    async def test_missing_runtime_key_is_not_displayed_as_configured(self):
        from pi_sandbox_factory.sandbox_tui import WebAccessForm, preset
        service = FakeService(self.records)
        service.search_status = lambda name: {'exa': False, 'brave': False}
        app = Cockpit(self.root, service)
        async with app.run_test(size=(80,24)) as pilot:
            await self.ready(app, pilot)
            draft = preset('base', DEFAULT_SETTINGS)
            draft.update(name='alpha', workspace=str(self.root), local_model_ports=None)
            draft['options']['web_access'] = {'enabled': True, 'providers': {'exa': {}, 'brave': {'has_key': True}}}
            app.push_screen(SettingsForm(draft, editing=True))
            await pilot.pause(); await app.workers.wait_for_complete(); await pilot.pause()
            web = app.screen.query_one(WebAccessForm)
            self.assertFalse(web.providers['brave']['has_key'])

    async def test_network_category_selection_reaches_cli(self):
        app = Cockpit(self.root, FakeService(self.records))
        async with app.run_test(size=(80,24)) as pilot:
            await self.ready(app, pilot)
            app.perform_action('network-settings')
            await pilot.pause()
            app.screen.query_one('#category-ut1-press', Checkbox).value = True
            app.screen.query_one('#apply-network', Button).press()
            await pilot.pause()
            await app.workers.wait_for_complete()
            call = app.service.calls[-1]
            self.assertEqual(call[-2:], ['--website-groups', 'ut1-press'])

if __name__ == '__main__':
    unittest.main()
