import asyncio
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from textual.widgets import Button, Collapsible, Input, Static
from pi_sandbox_factory.sandbox_tui import Cockpit, DEFAULT_SETTINGS, SettingsForm, preset
from pi_sandbox_factory.communications_ui import CommunicationsForm, SlackCredentials
from pi_sandbox_factory.tui_widgets import Checkbox
from test_tui import FakeService


class CommunicationsUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.runner=asyncio.Runner()
    @classmethod
    def tearDownClass(cls): cls.runner.close()
    def _callTestMethod(self, method): self.runner.run(method())

    async def test_channel_controls_and_private_dialog(self):
        for size in ((80,24),(120,40)):
            with tempfile.TemporaryDirectory() as temp, patch('pi_sandbox_factory.updates.available_update',return_value=None), patch('pi_sandbox_factory.sandbox_tui.load_defaults',side_effect=lambda:copy.deepcopy(DEFAULT_SETTINGS)), patch('pi_sandbox_factory.sandbox_tui.search_keys_path',return_value=Path(temp)/'keys'):
                app=Cockpit(Path(temp),FakeService([]))
                async with app.run_test(size=size) as pilot:
                    await pilot.pause(); await app.workers.wait_for_complete()
                    draft=preset('base',copy.deepcopy(DEFAULT_SETTINGS));draft.update(name='test',workspace=temp)
                    await app.push_screen(SettingsForm(draft,section='communications-section'))
                    await pilot.pause()
                    form=app.screen.query_one(CommunicationsForm)
                    checkbox=form.query_one('#slack-enabled',Checkbox)
                    self.assertTrue(form.query_one('#slack-configure',Button).disabled)
                    checkbox.value=True
                    await pilot.pause()
                    self.assertFalse(form.query_one('#slack-configure',Button).disabled)
                    self.assertEqual(form.query_one('#communications-section',Collapsible).title,'Communications · Slack')
                    form.query_one('#slack-configure',Button).focus();await pilot.pause()
                    if Path('/tmp/pi-communications-check').exists():
                        app.save_screenshot('/tmp/pi-communications-check/channels-'+str(size[0])+'.svg')
                    await pilot.press('enter');await pilot.pause()
                    self.assertIsInstance(app.screen,SlackCredentials)
                    bot=app.screen.query_one('#slack-botToken',Input)
                    self.assertTrue(bot.password)
                    bot.value='wrong'
                    app.screen.query_one('#slack-save',Button).focus();await pilot.press('enter');await pilot.pause()
                    self.assertIn('xoxb-',str(app.screen.query_one('#slack-error',Static).render()))
                    save=app.screen.query_one('#slack-save',Button)
                    self.assertLess(save.region.bottom,size[1])
                    self.assertIs(app.screen.get_widget_at(save.region.x,save.region.y)[0],save)
                    if Path('/tmp/pi-communications-check').exists():
                        app.save_screenshot('/tmp/pi-communications-check/slack-'+str(size[0])+'.svg')
                    await pilot.press('escape');await pilot.pause()
                    self.assertEqual(form.changes,{})
                    form.query_one('#slack-configure',Button).focus();await pilot.press('enter');await pilot.pause()
                    app.screen.query_one('#slack-botToken',Input).value='xoxb-fixture'
                    app.screen.query_one('#slack-save',Button).focus();await pilot.press('enter');await pilot.pause()
                    self.assertEqual(form.collect(),({'slack':True},{'botToken':'xoxb-fixture'}))
                    self.assertNotIn('xoxb-fixture',str(form.value))
                    await pilot.press('escape');await pilot.pause();await pilot.press('q')

    async def test_edit_tokens_without_recreating_and_remove_while_disabled(self):
        with tempfile.TemporaryDirectory() as temp, patch('pi_sandbox_factory.updates.available_update',return_value=None), patch('pi_sandbox_factory.sandbox_tui.load_defaults',side_effect=lambda:copy.deepcopy(DEFAULT_SETTINGS)), patch('pi_sandbox_factory.sandbox_tui.search_keys_path',return_value=Path(temp)/'keys'):
            service=FakeService([])
            service.communication_status=lambda name: {'botToken':True,'userToken':False}
            service.save_communication_keys=lambda name, changes, log: service.calls.append(('keys',name,changes))
            app=Cockpit(Path(temp),service)
            async with app.run_test(size=(80,24)) as pilot:
                await pilot.pause();await app.workers.wait_for_complete()
                draft=preset('base',copy.deepcopy(DEFAULT_SETTINGS));draft.update(name='test',workspace=temp)
                draft['options']['communications']={'slack':False}
                await app.push_screen(SettingsForm(draft,editing=True,section='communications-section'))
                await pilot.pause();await app.workers.wait_for_complete();await pilot.pause()
                form=app.screen.query_one(CommunicationsForm)
                self.assertFalse(form.query_one('#slack-configure',Button).disabled)
                form.query_one('#slack-configure',Button).focus();await pilot.press('enter');await pilot.pause()
                bot=app.screen.query_one('#slack-botToken',Input)
                bot.value='xoxb-replacement'
                app.screen.query_one('#slack-clear-botToken',Checkbox).value=True
                app.screen.query_one('#slack-save',Button).focus();await pilot.press('enter');await pilot.pause()
                self.assertIn('replacement token or',str(app.screen.query_one('#slack-error',Static).render()))
                await pilot.pause(0.5)
                bot.value=''
                app.screen.query_one('#slack-save',Button).focus();await pilot.press('enter');await pilot.pause()
                self.assertEqual(form.collect(),({'slack':False},{'botToken':''}))
                proposed,_=app.screen.collect()
                self.assertTrue(app.screen.configuration_unchanged(proposed))
                changed=copy.deepcopy(proposed);changed['options']['communications']['slack']=True
                self.assertFalse(app.screen.configuration_unchanged(changed))
                app.screen.query_one('#apply',Button).focus();await pilot.press('enter');await pilot.pause()
                await app.workers.wait_for_complete();await pilot.pause()
                self.assertEqual(service.calls,[('keys','test',{'botToken':''})])
