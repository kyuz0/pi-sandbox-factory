"""Shared hosted-provider forms for creation and live sandbox settings."""
import asyncio
import subprocess
from textual import on, work
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option
from . import hosted_models
from .tui_widgets import Feedback


class ProviderDialog(ModalScreen):
    BINDINGS = [('escape', 'cancel', 'Cancel')]
    DEFAULT_CSS = '''
    ProviderDialog, ModelDialog { align: center middle; }
    .model-dialog { width: 88; max-width: 94%; height: 24; max-height: 95%; padding: 1 2; background: #34383d; border: solid #f2b544; }
    .model-fields { height: 1fr; min-height: 1; }
    .model-dialog Static { height: auto; }
    .provider-specific { height: auto; }
    '''

    def __init__(self, value=None):
        super().__init__()
        self.value = dict(value or {})

    def compose(self):
        v = self.value
        with Vertical(classes='model-dialog'):
            yield Label('Connect a model provider', classes='title')
            with VerticalScroll(classes='model-fields'):
                with Vertical(classes='setting'):
                    yield Label('Provider')
                    yield Select([(v,k) for k,v in hosted_models.PROVIDERS.items()], value=v.get('provider','openrouter'), allow_blank=False, disabled=bool(v.get('provider')), id='hosted-provider')
                with Vertical(id='azure-fields', classes='provider-specific'):
                    with Vertical(classes='setting'):
                        yield Label('Azure / Foundry endpoint')
                        yield Input(v.get('endpoint',''), placeholder='https://RESOURCE.openai.azure.com/openai/v1', id='hosted-endpoint')
                        yield Static('Use the inference endpoint from your Azure deployment.', classes='setting-help')
                with Vertical(id='bedrock-fields', classes='provider-specific'):
                    with Vertical(classes='setting'):
                        yield Label('AWS region')
                        yield Input(v.get('region',''), placeholder='eu-west-1', id='hosted-region')
                    with Vertical(classes='setting'):
                        yield Label('Authentication')
                        yield Select([('Bedrock bearer token','bearer'),('AWS access keys','iam')], value=v.get('method','bearer'), allow_blank=False, id='hosted-method')
                with Vertical(id='hosted-key-field', classes='setting'):
                    yield Label('API key / bearer token')
                    yield Input(v.get('key',''), password=True, id='hosted-key')
                    yield Static('Leave empty to keep the saved key.' if v.get('has_key') else 'Stored in a separate inference container; Pi and editor extensions receive no key.', classes='setting-help')
                with Vertical(id='iam-fields', classes='provider-specific'):
                    for field, label in [('access_key','AWS access key ID'),('secret_key','AWS secret access key'),('session_token','AWS session token · for temporary credentials')]:
                        with Vertical(classes='setting'):
                            yield Label(label)
                            yield Input(v.get(field,''), password=True, id='hosted-'+field)
                    yield Static('Leave all three empty to keep saved AWS keys. Temporary credentials must be replaced when they expire.', classes='setting-help')
                yield Static('', id='hosted-destinations', markup=False, classes='setting-help')
            yield Feedback('', id='hosted-error', markup=False, classes='error')
            with Horizontal(classes='buttons dialog-actions'):
                yield Button('Cancel', id='hosted-cancel')
                yield Button('Save', id='hosted-save', variant='primary')

    def on_mount(self): self.sync()

    @on(Select.Changed)
    def sync(self):
        provider = self.query_one('#hosted-provider', Select).value
        self.query_one('.model-dialog').styles.height = 44 if provider == 'amazon-bedrock' else 32 if provider == 'azure' else 26
        iam = provider == 'amazon-bedrock' and self.query_one('#hosted-method', Select).value == 'iam'
        self.query_one('#azure-fields').display = provider == 'azure'
        self.query_one('#bedrock-fields').display = provider == 'amazon-bedrock'
        self.query_one('#iam-fields').display = iam
        self.query_one('#hosted-key-field').display = not iam
        self.query_one('#hosted-destinations', Static).update('Factory connects the inference service and allows pi.dev for Pi’s model catalogue.')

    def action_cancel(self): self.dismiss(None)

    @on(Button.Pressed)
    def pressed(self,event):
        event.stop()
        if event.button.id == 'hosted-cancel': self.action_cancel()
        elif event.button.id == 'hosted-save':
            try:
                value = {**self.value, 'provider': self.query_one('#hosted-provider',Select).value,
                         'method': self.query_one('#hosted-method',Select).value}
                for field in ('key','access_key','secret_key','session_token','endpoint','region'):
                    value[field] = self.query_one('#hosted-'+field,Input).value.strip()
                value = hosted_models.validate(value)
                if not value.get('configured') and not value.get('has_key'):
                    if value['provider'] == 'amazon-bedrock' and value['method'] == 'iam':
                        if not value['access_key'] or not value['secret_key']: raise ValueError('Enter the AWS access key and secret key.')
                    elif not value['key']: raise ValueError('Enter an API key.')
                self.dismiss(value)
            except ValueError as error:
                self.query_one('#hosted-error',Static).update(str(error))


class HostedProviders(Vertical):
    DEFAULT_CSS = '''
    HostedProviders, .hosted-list { height: auto; }
    .hosted-row { height: auto; margin-bottom: 1; padding: 1 2; background: #24292f; }
    .hosted-row Static { height: auto; }
    .hosted-row .buttons { height: auto; min-height: 1; }
    '''

    def __init__(self, name=None, changes=None):
        super().__init__()
        self.sandbox_name = name
        self.changes = dict(changes or {})
        self.saved = {}
        self.busy = False

    def compose(self):
        yield Static('Hosted model services', classes='group-title')
        yield Vertical(classes='hosted-list', id='hosted-list')
        with Vertical(classes='setting'):
            yield Button('Connect provider…', id='hosted-add')
            yield Static('Choose a model after the sandbox starts.' if not self.sandbox_name else 'Choose a default model for new Pi and Pendant chats. Reopen an existing client after changing its connection.', classes='setting-help')
        yield Static('',id='hosted-message',markup=False, classes='setting-help')

    async def on_mount(self):
        self.query_one('#hosted-message').display = False
        if self.sandbox_name and hasattr(self.app.service, 'hosted_request'): self.load()
        else: await self.render_rows()

    @work(exclusive=True, group='hosted-load')
    async def load(self):
        try:
            reply = await asyncio.to_thread(self.app.service.hosted_request, self.sandbox_name, 'status')
            self.saved = {r['provider']: r for r in reply['providers'] if r['configured']}
            await self.render_rows()
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            self.show_message(str(error))

    def show_message(self, text):
        message = self.query_one('#hosted-message', Static)
        message.update(text)
        message.display = bool(text)

    async def render_rows(self):
        target = self.query_one('#hosted-list',Vertical)
        await target.remove_children()
        for provider, value in {**self.saved, **self.changes}.items():
            row = Vertical(classes='hosted-row')
            await target.mount(row)
            await row.mount(Static(hosted_models.PROVIDERS[provider],markup=False))
            buttons = Horizontal(classes='buttons')
            await row.mount(buttons)
            await buttons.mount(Button('Connection…',name='edit:'+provider), Button('Remove',name='remove:'+provider))
            if self.sandbox_name: await buttons.mount(Button('Choose model…',name='model:'+provider))
        self.query_one('#hosted-add',Button).disabled = self.busy

    @on(Button.Pressed)
    def pressed(self,event):
        event.stop()
        if self.busy: return
        action = event.button.name or event.button.id
        if action == 'hosted-add': self.app.push_screen(ProviderDialog(), self.changed)
        elif action.startswith('edit:'):
            provider = action.split(':')[1]
            self.app.push_screen(ProviderDialog({**self.saved,**self.changes}[provider]), self.changed)
        elif action.startswith('remove:'):
            provider = action.split(':')[1]
            if self.sandbox_name:
                from .sandbox_tui import Confirm
                self.app.push_screen(Confirm('Remove '+hosted_models.PROVIDERS[provider]+' credentials and its provider network rules?', 'Remove'), lambda yes: self.remove(provider) if yes else None)
            else:
                self.changes.pop(provider,None); self.call_later(self.render_rows)
        elif action.startswith('model:'):
            self.app.push_screen(ModelDialog(self.sandbox_name,action.split(':')[1]))

    def changed(self,value):
        if value is None: return
        if self.sandbox_name: self.save(value)
        else:
            self.changes[value['provider']] = value
            self.call_later(self.render_rows)

    @work(exclusive=True,group='hosted-change')
    async def save(self,value):
        self.busy = True
        self.show_message('Saving connection…')
        try:
            reply = await asyncio.to_thread(self.app.service.hosted_save,self.sandbox_name,value)
            self.saved[value['provider']] = reply
            self.show_message('Connection saved. Choose a model to use.')
            await self.render_rows()
            self.app.push_screen(ModelDialog(self.sandbox_name,value['provider']))
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            self.show_message(str(error))
        finally:
            self.busy = False
            self.query_one('#hosted-add',Button).disabled = False

    @work(exclusive=True,group='hosted-change')
    async def remove(self,provider):
        self.busy = True
        try:
            await asyncio.to_thread(self.app.service.hosted_remove,self.sandbox_name,provider)
            self.saved.pop(provider,None)
            await self.render_rows()
            self.show_message('Connection removed. Choose another default model if needed.')
        except (ValueError, OSError, subprocess.SubprocessError) as error: self.show_message(str(error))
        finally:
            self.busy = False
            self.query_one('#hosted-add',Button).disabled = False


class ModelDialog(ModalScreen):
    BINDINGS = [('escape','cancel','Cancel')]
    DEFAULT_CSS = '''
    ModelDialog { align: center middle; }
    ModelDialog #model-results { height: 8; margin-bottom: 1; }
    ModelDialog .model-dialog { width: 96; max-width: 94%; height: 94%; max-height: 44; padding: 1 2; background: #34383d; border: solid #f2b544; }
    ModelDialog .model-fields { height: 1fr; min-height: 1; }
    ModelDialog Static { height: auto; }
    '''

    def __init__(self,name,provider):
        super().__init__()
        self.sandbox_name, self.provider = name,provider
        self.models = []; self.filtered = []; self.busy = False

    def compose(self):
        with Vertical(classes='model-dialog'):
            yield Label('Choose a model · '+hosted_models.PROVIDERS[self.provider],classes='title')
            with VerticalScroll(classes='model-fields'):
                with Vertical(classes='setting'):
                    yield Label('Search Pi’s model catalogue')
                    yield Input(id='model-search')
                yield OptionList(id='model-results')
                yield Static('',id='model-details',markup=False,classes='setting')
                if self.provider == 'azure':
                    with Vertical(classes='setting'):
                        yield Label('Azure deployment name for the selected model')
                        yield Input(id='model-deployment')
                        yield Static('Select the underlying model above, then enter its deployment name from Azure.',classes='setting-help')
                if self.provider == 'amazon-bedrock':
                    with Vertical(classes='setting'):
                        yield Label('Bedrock model / inference profile ID or ARN · optional')
                        yield Input(id='model-profile')
                        yield Static('Leave empty to use the exact catalogue ID. For a custom profile, select its underlying model above.',classes='setting-help')
                yield Static('The catalogue supplies model capabilities and limits.',classes='section-intro')
                with Vertical(classes='setting'):
                    yield Button('Refresh catalogue',id='model-refresh')
                with Vertical(classes='setting'):
                    yield Button('Test selected model · sends a short request',id='model-test',disabled=True)
            yield Static('Loading catalogue…',id='model-error',markup=False)
            with Horizontal(classes='buttons dialog-actions'):
                yield Button('Cancel',id='model-cancel')
                yield Button('Use as default',id='model-save',variant='primary',disabled=True)

    def on_mount(self): self.load(True)
    def action_cancel(self):
        if not self.busy: self.dismiss(None)

    @work(exclusive=True,group='catalogue')
    async def load(self,refresh=False):
        self.query_one('#model-error',Static).update('Refreshing catalogue…' if refresh else 'Loading catalogue…')
        try:
            reply = await asyncio.to_thread(self.app.service.hosted_request,self.sandbox_name,'catalogue',provider=self.provider,refresh=refresh)
            self.models = reply['models']
            self.filter_models()
            self.query_one('#model-error',Static).update(reply.get('warning',''))
        except (ValueError, OSError, subprocess.SubprocessError) as error: self.query_one('#model-error',Static).update(str(error))

    @on(Input.Changed,'#model-search')
    def filter_models(self):
        text = self.query_one('#model-search',Input).value.lower()
        self.filtered = [m for m in self.models if text in (m['id']+' '+m['name']).lower()]
        results = self.query_one('#model-results',OptionList)
        results.clear_options()
        results.add_options([Option(m['name']+' · '+m['id'],id=str(i)) for i,m in enumerate(self.filtered)])
        results.display = bool(self.filtered)
        results.highlighted = None
        self.query_one('#model-test',Button).disabled = True
        self.query_one('#model-save',Button).disabled = True
        self.query_one('#model-details',Static).update('Select a model to see its limits.' if self.filtered else 'No matching model. Refresh the catalogue or configure an unlisted model in Pendant.')

    @on(OptionList.OptionHighlighted,'#model-results')
    def highlighted(self,event):
        model = self.filtered[event.option_index]
        self.query_one('#model-details',Static).update(f"{model['contextWindow']:,} context tokens · {model['maxTokens']:,} output tokens · " + ', '.join(model['input']) + (' · reasoning' if model['reasoning'] else ''))
        self.query_one('#model-save',Button).disabled = False
        self.query_one('#model-test',Button).disabled = False

    @on(Button.Pressed)
    def pressed(self,event):
        event.stop()
        if self.busy: return
        if event.button.id == 'model-cancel': self.action_cancel()
        elif event.button.id == 'model-refresh': self.load(True)
        elif event.button.id in ('model-save','model-test'): self.apply(event.button.id == 'model-test')

    @work(exclusive=True,group='model-save')
    async def apply(self,test):
        index = self.query_one('#model-results',OptionList).highlighted
        if index is None: return
        self.busy = True
        self.query_one('#model-error',Static).update('Testing…' if test else 'Saving…')
        try:
            model = self.filtered[index]['id']
            fields = {}
            if self.provider == 'azure': fields['deployment'] = self.query_one('#model-deployment',Input).value.strip()
            if self.provider == 'amazon-bedrock': fields['profile_id'] = self.query_one('#model-profile',Input).value.strip()
            # Test uses the same deployment/profile mapping as selection, without changing the default.
            if test:
                await asyncio.to_thread(self.app.service.hosted_test,self.sandbox_name,self.provider,model,**fields)
                self.query_one('#model-error',Static).update('The model responded successfully.')
            else:
                await asyncio.to_thread(self.app.service.hosted_select,self.sandbox_name,self.provider,model,**fields)
                self.dismiss(model)
        except (ValueError, OSError, subprocess.SubprocessError) as error: self.query_one('#model-error',Static).update(str(error))
        finally: self.busy = False
