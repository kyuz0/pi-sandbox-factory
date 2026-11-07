import asyncio
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from textual.widgets import Button, Input, OptionList, Select, Static
from pi_sandbox_factory.sandbox_tui import Cockpit, DEFAULT_SETTINGS, ModelsScreen, SettingsForm, preset
from pi_sandbox_factory.models_ui import HostedProviders, ModelDialog, ProviderDialog
from test_tui import FakeService


class ModelService(FakeService):
    def hosted_request(self, name, action, **values):
        if action == 'status': return {'providers':[{'provider':'openrouter','configured':True,'has_key':True}]}
        return {'models':[{'id':'model-1','name':'Example model','api':'openai-completions','contextWindow':128000,
                          'maxTokens':8192,'input':['text','image'],'reasoning':True}], 'warning':''}
    def hosted_select(self,*args,**kwargs): self.calls.append((args,kwargs))
    def hosted_test(self,*args,**kwargs): self.calls.append(('test',args,kwargs));return {'ok':True}


class HostedUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.runner=asyncio.Runner()
    @classmethod
    def tearDownClass(cls): cls.runner.close()
    def _callTestMethod(self,method): self.runner.run(method())

    async def test_create_edit_model_selection_and_small_terminal(self):
        for size in [(80,24),(120,40),(220,50)]:
            with tempfile.TemporaryDirectory() as temp, patch('pi_sandbox_factory.updates.available_update',return_value=None), patch('pi_sandbox_factory.sandbox_tui.load_defaults',side_effect=lambda:copy.deepcopy(DEFAULT_SETTINGS)):
                service=ModelService([]);app=Cockpit(Path(temp),service)
                async with app.run_test(size=size) as pilot:
                    await pilot.pause();await app.workers.wait_for_complete()
                    draft=preset('base',copy.deepcopy(DEFAULT_SETTINGS));draft.update(name='test',workspace=temp)
                    await app.push_screen(SettingsForm(draft,section='hosted-section'));await pilot.pause()
                    form=app.screen.query_one(HostedProviders)
                    form.query_one('#hosted-add',Button).focus();await pilot.press('enter');await pilot.pause()
                    self.assertIsInstance(app.screen,ProviderDialog)
                    app.screen.query_one('#hosted-provider',Select).value='amazon-bedrock';await pilot.pause()
                    app.screen.query_one('#hosted-method',Select).value='iam';await pilot.pause()
                    self.assertTrue(app.screen.query_one('#hosted-secret_key',Input).password)
                    save=app.screen.query_one('#hosted-save',Button)
                    self.assertLess(save.region.bottom,size[1])
                    save.focus();await pilot.press('enter');await pilot.pause()
                    self.assertIn('region',str(app.screen.query_one('#hosted-error',Static).render()))
                    await pilot.press('escape');await pilot.pause();self.assertFalse(form.changes)
                    form.query_one('#hosted-add',Button).focus();await pilot.press('enter');await pilot.pause()
                    app.screen.query_one('#hosted-key',Input).value='fixture-key'
                    app.screen.query_one('#hosted-save',Button).focus();await pilot.press('enter');await pilot.pause()
                    self.assertEqual(form.changes['openrouter']['key'],'fixture-key')
                    await pilot.press('escape');await pilot.pause()
                    await app.push_screen(ModelsScreen({'name':'test','config':{'model_providers':[]}}));await pilot.pause();await app.workers.wait_for_complete();await pilot.pause()
                    await app.push_screen(ModelDialog('test','azure'));await pilot.pause();await app.workers.wait_for_complete();await pilot.pause()
                    self.assertTrue(app.screen.query_one('#model-save',Button).disabled)
                    self.assertTrue(app.screen.query_one('#model-test',Button).disabled)
                    app.screen.query_one('#model-results',OptionList).highlighted=0;await pilot.pause()
                    app.screen.query_one('#model-deployment',Input).value='my-deployment'
                    app.screen.query_one('#model-test',Button).focus();await pilot.press('enter');await pilot.pause();await app.workers.wait_for_complete();await pilot.pause()
                    self.assertEqual(service.calls[-1][0],'test')
                    app.screen.query_one('#model-save',Button).focus();await pilot.press('enter');await pilot.pause();await app.workers.wait_for_complete();await pilot.pause()
                    self.assertEqual(service.calls[-1][1]['deployment'],'my-deployment')
