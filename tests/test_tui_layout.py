"""Layout and navigation contracts for the terminal forms."""
import asyncio
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Button, Collapsible, Input, Label, OptionList, Select, Static, RichLog
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

    async def test_review_uses_terminal_width_with_padded_actions(self):
        for size in ((80, 24), (120, 40), (220, 50)):
            app = self.app()
            async with app.run_test(size=size) as pilot:
                await self.ready(app, pilot)
                await app.push_screen(SettingsForm(self.draft()))
                app.screen.query_one('#folders-section', Collapsible).collapsed = False
                await pilot.pause()
                form = app.screen.query_one('.form')
                actions = app.screen.query_one('.wizard-actions')
                primary = actions.query_one('Button.-primary', Button)
                self.assertEqual(form.region.width, size[0])
                self.assertEqual(actions.region.width, size[0])
                self.assertEqual(actions.content_region.x, 3)
                self.assertEqual(primary.region.right, size[0] - 3)
                self.assertLess(primary.region.bottom,
                                app.screen.query_one('Footer').region.y)
                await pilot.press('escape')
                await pilot.press('q')

    async def test_advisor_labels_order_and_explicit_copy_controls(self):
        from pi_sandbox_factory.advisors_ui import AdvisorChoices
        from pi_sandbox_factory.advisor_credentials import LABELS
        from pi_sandbox_factory.sandbox_tui import AdvisorsScreen
        for creation in (True, False):
            app = self.app()
            async with app.run_test(size=(120, 40)) as pilot:
                await self.ready(app, pilot)
                await app.push_screen(SettingsForm(self.draft()) if creation else AdvisorsScreen(self.record))
                if creation:
                    app.screen.query_one('#new-advisors-section', Collapsible).collapsed = False
                await pilot.pause()
                choices = app.screen.query_one(AdvisorChoices)
                prefix = 'new-advisor-' if creation else 'advisor-'
                fields = [choices.query_one('#' + prefix + p, Checkbox) for p in LABELS]
                self.assertEqual([str(field.label) for field in fields], list(LABELS.values()))
                self.assertEqual([field.region.y for field in fields], sorted(field.region.y for field in fields))
                copy = choices.query_one('#' + prefix + 'copy-claude', Checkbox)
                self.assertFalse(copy.value)
                self.assertFalse(copy.display)
                choices.query_one('#' + prefix + 'claude', Checkbox).value = True
                await pilot.pause()
                self.assertTrue(copy.display)
                self.assertFalse(copy.disabled)
                parent = choices.query_one('#' + prefix + 'claude', Checkbox)
                self.assertEqual(copy.region.x, parent.region.x + 2)
                self.assertEqual(copy.region.y, parent.region.bottom + 1)
                copy.value = True
                self.assertEqual(choices.imports(), ['claude'])
                if not creation:
                    self.assertFalse(app.screen.query_one('#advisor-claude-model').disabled)
                    self.assertTrue(app.screen.query_one('#advisor-model').disabled)
                    calls = []
                    app.service.advisors = lambda name, settings, log: calls.append(('save', settings['providers']))
                    app.service.run = lambda args, log: calls.append(args)
                    await pilot.click('#advisor-apply')
                    await pilot.pause()
                    await pilot.click('#yes')
                    await self.ready(app, pilot)
                    self.assertEqual(calls, [('save', ['claude']), ['advisor-import', 'demo', 'claude']])
                else:
                    choices.query_one('#' + prefix + 'claude', Checkbox).value = False
                    await pilot.pause()
                    self.assertFalse(copy.value)
                    self.assertEqual(choices.imports(), [])
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
            ports = form.query_one('#model-port-setting')
            self.assertEqual(form.query_one('#hosted-section').region.y, ports.region.bottom + 1)
            form.query_one('#network-section', Collapsible).collapsed = False
            await pilot.pause()
            categories = form.query_one('WebsiteGroups')
            destinations = next(label for label in form.query('Label') if str(label.render()).startswith('Additional allowed destinations'))
            self.assertGreaterEqual(destinations.region.y, categories.region.bottom)
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


    async def test_context_actions_and_modal_actions_have_padding(self):
        from pi_sandbox_factory.repository_ui import RepositorySetup
        from pi_sandbox_factory.sandbox_tui import SSHScreen
        for size in ((80, 24), (120, 40), (220, 50)):
            app = self.app()
            async with app.run_test(size=size) as pilot:
                await self.ready(app, pilot)
                await app.push_screen(SSHScreen(self.record))
                await pilot.pause()
                button = app.screen.query_one('#ssh-repository', Button)
                self.assertGreaterEqual(button.styles.padding.left + button.styles.line_pad, 2)
                self.assertGreaterEqual(button.styles.padding.right + button.styles.line_pad, 2)
                self.assertGreater(button.region.y, app.screen.query_one('#ssh-hosts').region.bottom)
                self.assertEqual(app.screen.query_one('#ssh-hosts').region.height, 5)
                await app.push_screen(RepositorySetup())
                await pilot.pause()
                actions = app.screen.query_one('.dialog-actions')
                save = app.screen.query_one('#repository-add', Button)
                cancel = app.screen.query_one('#repository-cancel', Button)
                self.assertEqual(save.region.right, actions.content_region.right)
                self.assertEqual(save.region.height, 3 if size[1] >= 32 else 1)
                self.assertEqual(cancel.region.height, save.region.height)
                self.assertGreater(cancel.region.x, actions.content_region.x)
                self.assertGreater(actions.region.y, app.screen.query_one('VerticalScroll').region.bottom)
                self.assertLess(save.region.bottom, size[1] - 1)
                self.assertNotEqual(cancel.styles.background, cancel.parent.parent.styles.background)

    async def test_permission_controls_and_subagents_are_in_their_sections(self):
        app = self.app()
        async with app.run_test(size=(120, 40)) as pilot:
            await self.ready(app, pilot)
            await app.push_screen(SettingsForm(self.draft()))
            app.screen.query_one('#agent-section', Collapsible).collapsed = False
            await pilot.pause()
            approval = app.screen.query_one('#approval', Select)
            help_text = app.screen.query_one('#approval-help', Static)
            subagents = app.screen.query_one('#subagents', Checkbox)
            self.assertIs(approval.parent, help_text.parent)
            self.assertEqual(help_text.region.y, approval.region.bottom)
            self.assertIn(app.screen.query_one('#skills-section', Collapsible), subagents.ancestors)
            questions = app.screen.query_one('#question-forms', Checkbox)
            self.assertTrue(questions.value)
            self.assertIn(app.screen.query_one('#skills-section', Collapsible), questions.ancestors)
            questions.value = False
            self.assertFalse(app.screen.collect()[0]['options']['question_forms'])
            credentials = app.screen.query_one('#protect-credentials', Checkbox)
            self.assertTrue(credentials.value)
            self.assertIn(app.screen.query_one('#agent-section', Collapsible), credentials.ancestors)
            credentials.value = False
            self.assertFalse(app.screen.collect()[0]['options']['protect_credentials'])
            self.assertTrue(str(app.screen.query_one('#agent-section', Collapsible).title).startswith('Permissions and sandbox'))

    async def test_labels_controls_and_feedback_do_not_create_empty_rows(self):
        from pi_sandbox_factory.sandbox_tui import CreateFromSandbox, Operation
        from pi_sandbox_factory.models_ui import ProviderDialog
        for size in ((80, 24), (120, 40)):
            app = self.app()
            async with app.run_test(size=size) as pilot:
                await self.ready(app, pilot)
                await app.push_screen(NewSandbox())
                await pilot.pause()
                labels = list(app.screen.query(Label))
                profile = app.screen.query_one('#profile')
                self.assertEqual(profile.region.y, labels[1].region.bottom)
                workspace = app.screen.query_one('#workspace')
                label = next(x for x in labels if str(x.render()) == 'Workspace')
                self.assertEqual(workspace.region.y, label.region.bottom)
                self.assertLessEqual(app.screen.query_one('#name').region.bottom,
                                     app.screen.query_one('.wizard-actions').region.y)
                await app.pop_screen()
                await app.push_screen(CreateFromSandbox([self.record]))
                await pilot.pause()
                self.assertEqual(app.screen.query_one('#copy-source').region.height, 3)
                await app.pop_screen()
                await app.push_screen(ProviderDialog())
                feedback = app.screen.query_one('#hosted-error', Static)
                self.assertFalse(feedback.display)
                feedback.update('Enter an API key.')
                await pilot.pause()
                self.assertTrue(feedback.display)
                self.assertTrue(feedback.has_class('error'))
                self.assertLess(app.screen.query_one('#hosted-save').region.bottom, size[1])
                feedback.update('')
                self.assertFalse(feedback.display)
                await app.pop_screen()
                await app.push_screen(Operation('Starting sandbox', lambda log: log('Ready.')))
                await self.ready(app, pilot)
                button = app.screen.query_one('#operation-back')
                bar = app.screen.query_one('.wizard-actions')
                self.assertIs(button.parent, bar)
                self.assertEqual(button.region.x, 3)
                self.assertGreater(button.region.y, bar.region.y)
                self.assertLess(button.region.bottom, app.screen.query_one('Footer').region.y)
