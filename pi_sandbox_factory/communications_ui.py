"""Channel settings shared by sandbox creation and editing."""
import asyncio
from textual import on, work
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Collapsible, Input, Label, Link, Static
from .tui_widgets import Checkbox
from . import communications


class SlackCredentials(ModalScreen):
    BINDINGS = [Binding('escape', 'cancel', 'Cancel')]
    DEFAULT_CSS = '''
    SlackCredentials { align: center middle; }
    #slack-dialog { width: 76; max-width: 94%; height: 90%; max-height: 32; padding: 1 2; background: #34383d; border: solid #f2b544; }
    #slack-fields { height: 1fr; min-height: 1; }
    #slack-dialog Static { height: auto; }
    #slack-dialog Link { margin-bottom: 1; }
    #slack-error { margin-top: 1; }
    #slack-dialog .token-remove { margin: 1 0 0 2; }
    '''

    def __init__(self, changes, status):
        super().__init__()
        self.changes, self.status = dict(changes), status

    def compose(self):
        with Vertical(id='slack-dialog'):
            yield Label('Slack credentials', classes='title')
            with VerticalScroll(id='slack-fields'):
                yield Static('Create a Slack app and install it in your workspace. Invite its bot to the channels Pi should access.', classes='section-intro')
                yield Link('Slack setup guide', url='https://github.com/kyuz0/pi-sandbox-factory/blob/main/docs/communications.md')
                for field, label in [('botToken', 'Bot token · xoxb-'), ('userToken', 'User token for search · xoxp- (optional)')]:
                    with Vertical(classes='setting'):
                        yield Label(label)
                        yield Input(self.changes.get(field, ''), password=True, id='slack-' + field)
                        saved = bool(self.changes.get(field)) or bool((self.status or {}).get(field))
                        help_text = ('Token ready to save.' if self.changes.get(field) else
                                     'Saved token present. Leave empty to keep it.' if saved else
                                     'Leave empty to keep a previously saved token.' if self.status is None else
                                     'Required to connect Slack.' if field == 'botToken' else 'Only needed for message search.')
                        yield Static(help_text, classes='setting-help')
                        if saved or self.status is None or field in self.changes:
                            yield Checkbox('Remove saved token', value=field in self.changes and not self.changes[field], id='slack-clear-' + field, classes='token-remove')
            yield Static('', id='slack-error', markup=False)
            with Horizontal(classes='buttons dialog-actions'):
                yield Button('Cancel', id='slack-cancel')
                yield Button('Save', id='slack-save', variant='primary')

    def action_cancel(self):
        self.dismiss(None)

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        if event.button.id == 'slack-cancel':
            self.action_cancel()
        elif event.button.id == 'slack-save':
            changes = dict(self.changes)
            for field, prefix in [('botToken', 'xoxb-'), ('userToken', 'xoxp-')]:
                token = self.query_one('#slack-' + field, Input).value.strip()
                remove = self.query('#slack-clear-' + field)
                if remove and remove.first(Checkbox).value:
                    if token:
                        self.query_one('#slack-error', Static).update('Enter a replacement token or select Remove saved token.')
                        return
                    changes[field] = ''
                elif token:
                    if not token.startswith(prefix) or any(c.isspace() for c in token) or len(token) > 16000:
                        self.query_one('#slack-error', Static).update('Enter a ' + prefix + ' token without spaces.')
                        return
                    changes[field] = token
            self.dismiss(changes)


class CommunicationsForm(Vertical):
    DEFAULT_CSS = '''
    CommunicationsForm { height: auto; }
    #slack-controls { height: auto; align-vertical: middle; }
    #slack-controls Checkbox { width: 1fr; }
    #slack-controls Button { margin-left: 2; }
    '''

    def __init__(self, value, defaults=False, changes=None):
        super().__init__()
        self.value = communications.settings(value)
        self.defaults = defaults
        self.changes = dict(changes or {})
        self.status = {}

    def compose(self):
        with Collapsible(title='Communications · Off', collapsed=True, id='communications-section'):
            with Vertical(classes='setting'):
                with Horizontal(id='slack-controls'):
                    yield Checkbox('Slack', value=self.value['slack'], id='slack-enabled')
                    yield Button('Configure…', id='slack-configure', disabled=self.defaults)
                yield Static('Read channels and threads, search messages, download files and send replies from Pi.', classes='setting-help checkbox-help')
                yield Static('', id='slack-status', markup=False, classes='setting-help checkbox-help')

    def on_mount(self):
        if getattr(self.screen, 'editing', False):
            self.status = None
            self.refresh_status(self.screen.draft['name'])
        self.sync()

    @work(exclusive=True)
    async def refresh_status(self, name):
        service = self.app.service
        if hasattr(service, 'communication_status'):
            try:
                self.status = await asyncio.to_thread(service.communication_status, name)
            except (ValueError, OSError):
                self.status = None
            self.sync()

    @on(Checkbox.Changed, '#slack-enabled')
    def sync(self):
        enabled = self.query_one('#slack-enabled', Checkbox).value
        self.query_one('#communications-section', Collapsible).title = 'Communications · ' + ('Slack' if enabled else 'Off')
        self.query_one('#slack-configure', Button).disabled = self.defaults or (not enabled and not getattr(self.screen, 'editing', False))
        status = dict(self.status or {})
        status.update({key: bool(value) for key, value in self.changes.items()})
        text = ('Enter tokens separately in each sandbox.' if self.defaults else
                'Bot token configured' if status.get('botToken') else
                'Start the sandbox to check saved tokens.' if self.status is None and 'botToken' not in self.changes else
                'Configure a bot token to connect Slack.')
        if status.get('userToken'):
            text += ' · Search token configured'
        self.query_one('#slack-status', Static).update(text if enabled else '')

    @on(Button.Pressed, '#slack-configure')
    def configure(self, event):
        event.stop()
        self.app.push_screen(SlackCredentials(self.changes, self.status), self.configured)

    def configured(self, changes):
        if changes is not None:
            self.changes = changes
            self.sync()

    def collect(self):
        enabled = self.query_one('#slack-enabled', Checkbox).value
        changes = dict(self.changes) if enabled or getattr(self.screen, 'editing', False) else {}
        return {'slack': enabled}, changes
