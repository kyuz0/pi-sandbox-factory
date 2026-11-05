import asyncio
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sandbox
from sandbox_tui import Cockpit, Confirm, NewSandbox, SettingsForm, Operation, DEFAULT_SETTINGS, Service
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
    def models(self,name,mode,log):self.calls.append(['models',name,mode]);log('Model catalogue')

class TUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.runner=asyncio.Runner()
    @classmethod
    def tearDownClass(cls):cls.runner.close()
    def _callTestMethod(self,method):self.runner.run(method())
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.defaults=patch('sandbox_tui.load_defaults',side_effect=lambda:copy.deepcopy(DEFAULT_SETTINGS));self.defaults.start()
        self.records=[]
        for name in ['alpha','beta']:
            state=self.root/name;state.mkdir();(state/'allowlist.txt').write_text('local-model.internal:8000\n')
            c=dict(name=name,engine='podman',network='allowlist',workspace=str(self.root/'files'/name),
                   profile=sandbox.load_profile('base'),local_model_ports='8000',memory='8g',subagents=False)
            self.records.append(dict(name=name,profile='base',engine='podman',dev='running',proxy='running',workspace=c['workspace'],config=c))
    def tearDown(self):self.defaults.stop();self.tmp.cleanup()
    async def ready(self,app,pilot):await app.workers.wait_for_complete();await pilot.pause()

    async def settings_page(self, app, pilot, index=2):
        await pilot.click('#settings');await pilot.pause()
        menu=app.screen.query_one('#settings-actions',OptionList)
        menu.highlighted=index;menu.focus()
        await pilot.press('enter');await pilot.pause()

    async def delete_menu(self, app, pilot):
        await pilot.click('#more');await pilot.pause()
        menu=app.screen.query_one('#more-actions',OptionList)
        menu.highlighted=6;menu.focus()
        await pilot.press('enter');await pilot.pause()

    async def test_advisors_live_in_settings_and_allow_initial_setup(self):
        from sandbox_tui import AdvisorsScreen
        service=FakeService(self.records)
        service.advisors=lambda name,settings,log:service.calls.append(['advisors',name,settings])
        app=Cockpit(self.root,service)
        async with app.run_test(size=(100,36)) as pilot:
            await self.ready(app,pilot)
            await self.settings_page(app,pilot,index=3)
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

    async def test_saved_codex_advisor_enables_login(self):
        self.records[0]['config']['advisors'] = {'providers': ['codex']}
        app = Cockpit(self.root, FakeService(self.records))
        async with app.run_test(size=(100,36)) as pilot:
            await self.ready(app, pilot)
            await self.settings_page(app, pilot, index=3)
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
            await self.settings_page(app,pilot,index=3)
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

    async def test_github_preset_in_network_editor(self):
        from sandbox_tui import GITHUB_HOSTS, preset_allowed
        app=Cockpit(self.root,FakeService(self.records))
        async with app.run_test(size=(100,36)) as pilot:
            await self.ready(app,pilot);await self.settings_page(app,pilot,index=0)
            await pilot.click('#github-preset');await pilot.pause()
            text=app.screen.query_one('#allowlist',TextArea).text
            self.assertTrue(preset_allowed(text,GITHUB_HOSTS))
            self.assertIn('local-model.internal:8000',text)
            await pilot.press('q')

    async def test_ssh_settings_keep_key_import_separate(self):
        from sandbox_tui import SSHScreen
        service=FakeService(self.records);app=Cockpit(self.root,service)
        async with app.run_test(size=(100,36)) as pilot:
            await self.ready(app,pilot);await self.settings_page(app,pilot,index=4)
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
            app.screen.query_one('#model-ports',Input).value='8002-8003'
            app.screen.query_one('#new-advisor-codex',Checkbox).value=True
            app.screen.query_one('#new-advisor-agy',Checkbox).value=True
            app.screen.query_one('#new-advisor-claude',Checkbox).value=True
            with patch('sandbox.choose_engine',return_value='podman'):
                await pilot.click('#apply');await self.ready(app,pilot)
            self.assertIsInstance(app.screen,Operation)
            draft=service.calls[0][1]
            self.assertEqual(draft['name'],'my-agent');self.assertEqual(draft['workspace'],str(workspace))
            self.assertEqual(draft['allowlist'],'local-model.internal:8002\nlocal-model.internal:8003')
            self.assertEqual(draft['local_model_ports'],'8002-8003')
            self.assertEqual(draft['advisors']['providers'], ['codex', 'agy', 'claude'])
            await pilot.press('q')

    async def test_settings_and_models_follow_selection(self):
        service=FakeService(self.records);app=Cockpit(self.root,service)
        async with app.run_test(size=(100,42)) as pilot:
            await self.ready(app,pilot);app.query_one(DataTable).move_cursor(row=1);await pilot.pause()
            await self.settings_page(app,pilot)
            form=app.screen;self.assertIsInstance(form,SettingsForm)
            form.query_one('#model-ports',Input).value='8080'
            with patch('sandbox.choose_engine',return_value='podman'):
                await pilot.click('#apply');await pilot.pause()
            self.assertIsInstance(app.screen,Confirm);await pilot.click('#yes');await self.ready(app,pilot)
            self.assertEqual(service.calls[0][0:2],['update','beta'])
            self.assertEqual(service.calls[0][2]['local_model_ports'],'8080')
            await pilot.click('#operation-back');await self.ready(app,pilot)
            app.query_one(DataTable).move_cursor(row=1);await pilot.pause()
            await self.settings_page(app,pilot,index=1)
            await pilot.click('#preview-models');await self.ready(app,pilot)
            self.assertEqual(service.calls[-1],['models','beta','preview'])
            await pilot.press('q')

    async def test_home_controls_fit_and_theme_is_gold(self):
        app=Cockpit(self.root,FakeService(self.records))
        async with app.run_test(size=(80,24)) as pilot:
            await self.ready(app,pilot);self.assertEqual(app.theme,'cockpit-gold')
            for name in ['open','settings','new','more']:
                b=app.query_one('#'+name,Button)
                self.assertLessEqual(b.region.right,80,name);self.assertLessEqual(b.region.bottom,23,name)
            self.assertEqual(len(app.query(Button)),4)
            app.save_screenshot(filename='sandbox-home-declutter.svg',path='/tmp')
            await self.settings_page(app,pilot,index=0)
            self.assertLessEqual(app.screen.query_one('#apply-network',Button).region.bottom,23)
            app.save_screenshot(filename='sandbox-network-declutter.svg',path='/tmp')
            await pilot.press('escape');await pilot.pause()
            await pilot.press('q')

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


    async def test_pip_preset_and_manual_rules_stay_in_sync(self):
        service=FakeService(self.records);app=Cockpit(self.root,service)
        async with app.run_test(size=(100,42)) as pilot:
            await self.ready(app,pilot);await self.settings_page(app,pilot)
            field=app.screen.query_one('#allowlist',TextArea)
            checkbox=app.screen.query_one('#pip-preset',Checkbox)
            self.assertFalse(checkbox.value)
            checkbox.value=True;await pilot.pause()
            self.assertIn('pypi.org:443',field.text)
            self.assertIn('files.pythonhosted.org:443',field.text)
            self.assertIn('local-model.internal:8000',field.text)
            field.load_text('pypi.org:443 # index\nfiles.pythonhosted.org:443\nexample.com:443');await pilot.pause()
            self.assertTrue(checkbox.value)
            checkbox.value=False;await pilot.pause()
            self.assertEqual(field.text,'example.com:443')
            field.load_text('pypi.org:443\nexample.com:443');await pilot.pause()
            self.assertFalse(checkbox.value)
            checkbox.value=True;await pilot.pause()
            self.assertEqual(field.text.count('pypi.org:443'),1)
            with patch('sandbox.choose_engine',return_value='podman'):
                draft, key=app.screen.collect()
            self.assertIn('files.pythonhosted.org:443',draft['allowlist'])
            self.assertIn('example.com:443',draft['allowlist'])

    async def test_npm_preset_preserves_other_rules_and_tracks_manual_edits(self):
        service=FakeService(self.records);app=Cockpit(self.root,service)
        async with app.run_test(size=(100,42)) as pilot:
            await self.ready(app,pilot);await self.settings_page(app,pilot)
            field=app.screen.query_one('#allowlist',TextArea)
            checkbox=app.screen.query_one('#npm-preset',Checkbox)
            self.assertFalse(checkbox.value)
            checkbox.value=True;await pilot.pause()
            self.assertIn('registry.npmjs.org:443',field.text)
            self.assertIn('local-model.internal:8000',field.text)
            field.load_text('registry.npmjs.org:443 # packages\npypi.org:443\nexample.com:443');await pilot.pause()
            self.assertTrue(checkbox.value)
            checkbox.value=False;await pilot.pause()
            self.assertEqual(field.text,'pypi.org:443\nexample.com:443')
            field.load_text('registry.npmjs.org:443\npypi.org:443');await pilot.pause()
            self.assertTrue(checkbox.value)
            with patch('sandbox.choose_engine',return_value='podman'):
                draft, key=app.screen.collect()
            self.assertIn('registry.npmjs.org:443',draft['allowlist'])

    async def test_network_action_applies_to_selected_sandbox(self):
        service=FakeService(self.records);app=Cockpit(self.root,service)
        async with app.run_test(size=(100,42)) as pilot:
            await self.ready(app,pilot)
            app.query_one(DataTable).move_cursor(row=1)
            await self.settings_page(app,pilot,index=0)
            app.screen.query_one('#pip-preset',Checkbox).value=True
            app.screen.query_one('#npm-preset',Checkbox).value=True
            await pilot.pause()
            field=app.screen.query_one('#allowlist',TextArea)
            self.assertIn('registry.npmjs.org:443',field.text)
            field.load_text(field.text.replace('registry.npmjs.org:443',''));await pilot.pause()
            self.assertFalse(app.screen.query_one('#npm-preset',Checkbox).value)
            app.screen.query_one('#npm-preset',Checkbox).value=True
            await pilot.pause()
            await pilot.click('#apply-network');await self.ready(app,pilot)
            self.assertEqual(service.calls[0][:2],['network','beta'])
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
            for name in ('open','settings','more'):
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

if __name__=='__main__':unittest.main()
