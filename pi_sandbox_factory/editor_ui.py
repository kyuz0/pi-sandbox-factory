"""Shared editor controls for sandbox creation and settings."""
import secrets

from textual import on
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets.option_list import Option
from textual.widgets import Button, Collapsible, Footer, Header, Input, Label, OptionList, Select, Static

from . import editor_settings
from .tui_widgets import Checkbox, Feedback


class EditorFields(Vertical):
    DEFAULT_CSS = '''
    EditorFields, #editor-connection, #editor-password-fields, #editor-tls-fields { height: auto; }
    #editor-password-fields { margin-top: 1; margin-left: 2; padding-right: 1; }
    #editor-show-password { margin-top: 1; }
    #editor-generate { background: #424850; color: #f1f3f5; }
    '''

    def __init__(self, value=None, *, desktop_allowed=True, connection_settings=True):
        super().__init__()
        self.value = editor_settings.validate(value)
        self.desktop_allowed = desktop_allowed
        self.connection_settings = connection_settings

    def compose(self):
        with Vertical(classes='setting'):
            yield Label('Open sandbox with')
            yield Select([(title, key) for key, title in editor_settings.MODES.items() if self.desktop_allowed or key != 'desktop'],
                         value=self.value['mode'], allow_blank=False, id='editor-mode')
            yield Static('', id='editor-description', classes='setting-help')
            if not self.desktop_allowed:
                yield Static('VS Code on host requires a separate sandbox after browser-editor use.', classes='setting-help')
        if not self.connection_settings:
            return
        with Collapsible(title='Browser connection', collapsed=True, id='editor-connection'):
            with Vertical(classes='setting'):
                yield Label('Listen address · empty means automatic localhost')
                yield Input(self.value['address'], id='editor-address')
                yield Static('A custom address requires a password. Leave empty for local-only access.', classes='setting-help')
            with Vertical(classes='setting'):
                yield Label('Port · leave empty to choose automatically')
                yield Input(str(self.value['port']) if self.value['port'] else '', id='editor-port')
            with Vertical(classes='setting'):
                yield Checkbox('Require a password', value=bool(self.value['password_hash']), id='editor-auth')
                with Vertical(id='editor-password-fields'):
                    yield Label('Password · leave empty to keep the saved password' if self.value['password_hash'] else 'Password')
                    with Horizontal(classes='path-row'):
                        yield Input(password=True, id='editor-password')
                        yield Button('Generate', id='editor-generate')
                    yield Checkbox('Show password', id='editor-show-password')
            with Vertical(id='editor-tls-fields'):
                yield Static('Access from another computer requires a password and HTTPS for Pendant to work.', classes='section-intro')
                with Vertical(classes='setting'):
                    yield Label('HTTPS certificate file on this host')
                    yield Input(self.value.get('certificate', ''), id='editor-certificate')
                with Vertical(classes='setting'):
                    yield Label('HTTPS private key file on this host')
                    yield Input(self.value.get('private_key', ''), id='editor-private-key')
                    yield Static('Use a certificate trusted by the connecting browser for the listen address.', classes='setting-help')

    def on_mount(self):
        self.sync()

    @on(Select.Changed, '#editor-mode')
    @on(Checkbox.Changed, '#editor-auth')
    @on(Input.Changed, '#editor-address')
    @on(Input.Changed, '#editor-port')
    def sync(self):
        import ipaddress
        mode = self.query_one('#editor-mode', Select).value
        self.query_one('#editor-description', Static).update({
            'browser': 'The editor and its extensions run inside the sandbox.',
            'pi': 'Run Pi in this terminal. Exit Pi to return to the manager.',
            'desktop': 'Opens VS Code on this computer. Host-side extensions have host access.',
        }[mode])
        for section in self.screen.query('#editor-section'):
            section.title = 'Editor · ' + editor_settings.MODES[mode]
        if not self.connection_settings:
            return
        self.query_one('#editor-connection').display = mode == 'browser'
        self.query_one('#editor-password-fields').display = self.query_one('#editor-auth', Checkbox).value
        try:
            remote = not ipaddress.ip_address(self.query_one('#editor-address', Input).value or '127.0.0.1').is_loopback
        except ValueError:
            remote = True
        self.query_one('#editor-tls-fields').display = remote
        address = self.query_one('#editor-address', Input).value.strip()
        password = self.query_one('#editor-auth', Checkbox).value
        self.query_one('#editor-connection', Collapsible).title = ('Browser connection · ' +
            ('custom address' if address else 'localhost') + (' · password' if password else ' · no password'))

    @on(Checkbox.Changed, '#editor-show-password')
    def show_password(self, event):
        self.query_one('#editor-password', Input).password = not event.value

    @on(Button.Pressed, '#editor-generate')
    def generate(self, event):
        event.stop()
        self.query_one('#editor-password', Input).value = secrets.token_urlsafe(24)
        self.query_one('#editor-show-password', Checkbox).value = True

    def collect(self):
        mode = self.query_one('#editor-mode', Select).value
        if not self.connection_settings:
            return editor_settings.validate({'mode': mode})
        if mode != 'browser':
            return editor_settings.validate({**self.value, 'mode': mode})
        def text(name): return self.query_one('#editor-' + name, Input).value.strip()
        try:
            port = int(text('port') or '0')
        except ValueError:
            raise ValueError('Enter a numeric editor port, or leave it empty for automatic selection') from None
        digest = ''
        if self.query_one('#editor-auth', Checkbox).value:
            password = self.query_one('#editor-password', Input).value
            digest = editor_settings.password_hash(password) if password else self.value['password_hash']
            if not digest:
                raise ValueError('Enter or generate an editor password')
        value = editor_settings.validate(dict(mode=mode, address=text('address'), port=port, password_hash=digest,
            certificate=text('certificate'), private_key=text('private-key')))
        editor_settings.tls_context(value)
        return value


class EditorScreen(Screen):
    BINDINGS = [('escape', 'back', 'Back')]

    def __init__(self, name):
        super().__init__()
        self.sandbox_name = name

    def compose(self):
        yield Header()
        with VerticalScroll(classes='form'):
            yield Label('Editor · ' + self.sandbox_name, classes='title')
            state = self.app.state_root / self.sandbox_name
            yield EditorFields(editor_settings.load(state), desktop_allowed=not (state / 'browser-editor.enabled').exists())
            yield Static('Saving stops a running browser editor. Use Open on the sandbox list to reopen it.', classes='setting-help')
            yield Feedback('', id='editor-error', classes='error', markup=False)
        with Horizontal(classes='wizard-actions'):
            yield Button('Back', id='editor-back')
            yield Button('Save', id='editor-save', variant='primary')
        yield Footer()

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        if event.button.id == 'editor-back':
            self.action_back()
        elif event.button.id == 'editor-save':
            from . import browser_editor
            try:
                state = self.app.state_root / self.sandbox_name
                value = self.query_one(EditorFields).collect()
                if value == editor_settings.load(state):
                    self.action_back()
                    return
                from .sandbox_tui import Operation
                def apply(log):
                    browser_editor.stop(state)
                    editor_settings.save(state, value)
                    log('Editor settings saved. Use Open to launch with these settings.')
                self.app.pop_screen()
                self.app.push_screen(Operation('Saving editor settings', apply))
            except (ValueError, OSError) as error:
                self.query_one('#editor-error', Static).update(str(error))

    def action_back(self):
        self.app.pop_screen()


class OpenWith(ModalScreen):
    BINDINGS = [('escape', 'back', 'Back')]
    DEFAULT_CSS = 'OpenWith { align: center middle; background: #000000 70%; }'

    def __init__(self, *, desktop_allowed=True):
        super().__init__()
        self.desktop_allowed = desktop_allowed

    def compose(self):
        with Vertical(id='confirm-box'):
            yield Label('Open with')
            yield OptionList(*(Option(title, disabled=key == 'desktop' and not self.desktop_allowed)
                               for key, title in editor_settings.MODES.items()), id='editor-choices')
            if not self.desktop_allowed:
                yield Static('VS Code on host requires a separate sandbox after browser-editor use.', classes='setting-help')
            with Horizontal(classes='buttons dialog-actions'):
                yield Button('Cancel', id='editor-cancel')

    @on(OptionList.OptionSelected)
    def selected(self, event):
        self.dismiss(list(editor_settings.MODES)[event.option_index])

    @on(Button.Pressed)
    def cancel(self, event):
        event.stop()
        self.dismiss(None)

    def action_back(self):
        self.dismiss(None)
