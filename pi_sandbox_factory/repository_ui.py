"""Repository SSH setup and public-key display; permissions remain server-side."""
from textual import on, work
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Collapsible, Input, Label, Static, TextArea

from . import host_platform, sandbox_ssh, git_settings
from .tui_widgets import Feedback, Checkbox


class GitIdentityFields(Vertical):
    DEFAULT_CSS = '''
    GitIdentityFields { height: auto; }
    GitIdentityFields #git-identity-fields { height: auto; margin: 0 0 0 2; }
    GitIdentityFields #git-identity-fields.-identity-disabled { opacity: 50%; }
    GitIdentityFields > .git-identity-note { height: auto; margin: 1 0 0 0; }
    '''

    def __init__(self, value=None, defaults=False, setup=False):
        super().__init__()
        self.value = value
        self.defaults = defaults
        self.setup = setup

    def compose(self):
        with Vertical(classes='setting'):
            yield Checkbox('Set Git commit identity', value=self.value is not None, id='git-identity-enabled')
            yield Static(('Author for commits in new sandboxes.' if self.defaults else 'Author for commits in this sandbox.')
                         + ' Applied over global Git values at startup; repository-local settings take precedence. SSH keys authenticate separately.', classes='setting-help checkbox-help')
        with Vertical(id='git-identity-fields'):
            with Vertical(classes='setting'):
                yield Label('Commit author name')
                yield Input((self.value or {}).get('name', ''), id='git-author-name')
            with Vertical(classes='setting'):
                yield Label('Commit author email')
                yield Input((self.value or {}).get('email', ''), id='git-author-email')
                yield Static('Use an address you want recorded in Git history.', classes='setting-help')
                yield Feedback('', id='git-identity-error', markup=False)
        if self.setup:
            yield Static('Configure each sandbox’s SSH destinations and keys in Settings → SSH & Git.' if self.defaults else
                         'Configure SSH destinations and keys after creation in Settings → SSH & Git.',
                         classes='setting-help git-identity-note')

    def on_mount(self):
        self.sync_fields()

    @on(Checkbox.Changed, '#git-identity-enabled')
    def sync_fields(self):
        enabled = self.query_one('#git-identity-enabled', Checkbox).value
        for field in self.query(Input):
            field.disabled = not enabled
        self.query_one('#git-identity-fields').set_class(not enabled, '-identity-disabled')
        section = next((node for node in self.ancestors if isinstance(node, Collapsible)), None)
        if section:
            title = str(section.title).split(' · ')[0]
            section.title = title + ' · ' + ('commit identity ' if title == 'SSH & Git' else '') + ('set' if enabled else 'not set')

    @on(Input.Changed)
    def clear_error(self, event):
        event.input.remove_class('-invalid')
        self.query_one(Feedback).update('')

    def collect(self):
        self.query_one(Feedback).update('')
        if not self.query_one('#git-identity-enabled', Checkbox).value:
            return None
        try:
            return git_settings.identity({'name': self.query_one('#git-author-name', Input).value.strip(),
                                          'email': self.query_one('#git-author-email', Input).value.strip()})
        except ValueError as error:
            section = next((node for node in self.ancestors if isinstance(node, Collapsible)), None)
            if section:
                section.collapsed = False
            self.query_one(Feedback).update('Error: ' + str(error))
            invalid = '#git-author-name' if not self.query_one('#git-author-name', Input).value.strip() or 'name' in str(error) else '#git-author-email'
            self.query_one(invalid, Input).add_class('-invalid')
            self.call_after_refresh(self.query_one(Feedback).scroll_visible, animate=False)
            raise


class RepositorySetup(ModalScreen):
    BINDINGS = [('escape', 'cancel', 'Cancel')]
    DEFAULT_CSS = """
    RepositorySetup { align: center middle; background: #000000 70%; }
    RepositorySetup > Vertical { width: 86; max-width: 95%; height: 24; max-height: 95%; padding: 1 2; background: $panel; border: solid $primary; }
    RepositorySetup VerticalScroll { height: 1fr; }
    RepositorySetup Static { height: auto; }
    RepositorySetup .dialog-actions { height: auto; margin-top: 1; }
    """

    def compose(self):
        with Vertical():
            yield Label('Repository SSH setup', classes='title')
            with VerticalScroll():
                with Vertical(classes='setting'):
                    yield Label('GitHub or GitLab project URL')
                    yield Input(placeholder='https://github.com/owner/project', id='repository-url')
                    yield Static('Self-hosted GitLab is supported. For custom SSH ports, edit Destinations after adding.', classes='setting-help')
                with Vertical(classes='setting', id='repository-clone'):
                    yield Label('Clone inside the sandbox')
                    yield Static('', id='repository-preview', markup=False)
                with Vertical(classes='setting'):
                    yield Button('Open deploy-key settings', id='repository-settings', disabled=True)
                    yield Static('For read-only access, register a separate deploy key with write access disabled.', classes='setting-help')
                yield Feedback('', id='repository-error', classes='error', markup=False)
            with Horizontal(classes='dialog-actions'):
                yield Button('Cancel', id='repository-cancel')
                yield Button('Add destination', id='repository-add', variant='primary')

    def on_mount(self):
        self.preview()

    def value(self):
        return sandbox_ssh.repository_destination(self.query_one('#repository-url', Input).value.strip())

    @on(Input.Changed, '#repository-url')
    def preview(self):
        try:
            value = self.value()
            self.query_one('#repository-error', Static).update('')
            self.query_one('#repository-preview', Static).update(value['clone'])
            self.query_one('#repository-clone').display = True
            self.query_one('#repository-settings', Button).disabled = False
        except ValueError:
            self.query_one('#repository-preview', Static).update('')
            self.query_one('#repository-clone').display = False
            self.query_one('#repository-settings', Button).disabled = True

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        if event.button.id == 'repository-cancel':
            self.action_cancel()
            return
        try:
            value = self.value()
            if event.button.id == 'repository-settings':
                host_platform.open_url(value['settings_url'])
            elif event.button.id == 'repository-add':
                self.dismiss(value)
        except (ValueError, OSError) as error:
            self.query_one('#repository-error', Static).update(str(error))

    def action_cancel(self):
        self.dismiss(None)


class PublicKey(ModalScreen):
    BINDINGS = [('escape', 'close', 'Close')]
    DEFAULT_CSS = """
    PublicKey { align: center middle; background: #000000 70%; }
    PublicKey > Vertical { width: 86; max-width: 95%; height: 19; max-height: 95%; padding: 1 2; background: $panel; border: solid $primary; }
    PublicKey VerticalScroll { height: 1fr; }
    PublicKey #key-public { height: 5; min-height: 5; max-height: 5; }
    PublicKey Static { height: auto; }
    PublicKey .dialog-actions { height: auto; margin-top: 1; }
    """

    def __init__(self, name, generate=False):
        super().__init__()
        self.sandbox_name, self.generate = name, generate
        self.public_key = ''
        self.busy = True

    def compose(self):
        with Vertical():
            yield Label('SSH public key', classes='title')
            with VerticalScroll():
                with Vertical(classes='setting'):
                    yield Static('Generating a key in the SSH companion…' if self.generate else 'Reading the unlocked key…', id='key-status', markup=False)
                    yield TextArea(read_only=True, highlight_cursor_line=False, id='key-public')
                    yield Static('The Git server sets this key’s permissions. For read-only repository access, register a separate deploy key with write access disabled.', classes='setting-help')
            with Horizontal(classes='dialog-actions'):
                yield Button('Close', id='key-close', disabled=True)
                yield Button('Copy public key', id='key-copy', disabled=True, variant='primary')

    def on_mount(self):
        self.load_key()

    @work(thread=True, exit_on_error=False)
    def load_key(self):
        app = self.app
        try:
            public = app.service.ssh_key(self.sandbox_name, self.generate)
            app.call_from_thread(self.loaded, public, '')
        except Exception as error:
            app.call_from_thread(self.loaded, '', str(error))

    def loaded(self, public, error):
        self.busy = False
        self.public_key = public
        self.query_one('#key-public', TextArea).load_text(public)
        self.query_one('#key-status', Static).update(error or 'Public key ready. Its private key stays in the SSH companion.')
        self.query_one('#key-close', Button).disabled = False
        self.query_one('#key-copy', Button).disabled = not bool(public)

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        if event.button.id == 'key-copy':
            self.app.copy_to_clipboard(self.public_key)
            self.notify('Public key sent to the terminal clipboard.')
        elif event.button.id == 'key-close':
            self.action_close()

    def action_close(self):
        if not self.busy:
            self.dismiss(None)
