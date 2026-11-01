"""Sandbox Cockpit: optional Textual UI over the shared sandbox launcher."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Optional

import sandbox
import sandbox_skills
from sandbox_options import DEFAULTS, SKILLS, PROFILE_SKILLS, options, endpoint_rule, memory_limit, write_json

try:
    from textual import on, work
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.screen import ModalScreen, Screen
    from textual.content import Content
    from textual.theme import Theme
    from textual.widgets import (Button, Checkbox as TextualCheckbox, Collapsible, DataTable, Footer, Header,
                                 Input, Label, RichLog, Select, Static, TextArea, OptionList)
except ImportError as error:
    raise SystemExit('Sandbox Cockpit needs Textual. Install requirements-tui.txt in a Python virtual environment.') from error

TITLES = {'base': 'Pi + Pendant · development and documents'}
DEFAULT_SETTINGS = {'profile': 'base', 'workspace_parent': '', 'network': 'allowlist',
                    'engine': 'podman', 'memory': '8g', 'subagents': False, 'env_file': '',
                    'pi_config': '', 'skill_repo': '', 'skill_path': '', 'open_editor': True,
                    'local_model_ports': '8000', 'options': DEFAULTS}


GITHUB_HOSTS = {(h, 443) for h in ('github.com', 'api.github.com', 'raw.githubusercontent.com', 'codeload.github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com')}


PIP_HOSTS = {('pypi.org', 443), ('files.pythonhosted.org', 443)}


def line_rules(line):
    try:
        return set(sandbox.parse_rules(line))
    except ValueError:
        return set()


def preset_allowed(text, hosts):
    return hosts <= set().union(*(line_rules(line) for line in text.splitlines()))


def preset_rules(text, enabled, hosts):
    lines = text.splitlines()
    if enabled:
        existing = set().union(*(line_rules(line) for line in lines))
        lines.extend(f'{host}:{port}' for host, port in sorted(hosts - existing))
    else:
        lines = [line for line in lines if not line_rules(line) & hosts]
    return '\n'.join(lines)


def pip_allowed(text): return preset_allowed(text, PIP_HOSTS)

def pip_rules(text, enabled): return preset_rules(text, enabled, PIP_HOSTS)


class Checkbox(TextualCheckbox):
    """Distinguish both states by shape, including in monochrome terminals."""
    @property
    def _button(self):
        return Content('[✓]' if self.value else '[ ]').stylize(self.get_visual_style('toggle--button'))


def safe_text(value):
    return ''.join(c for c in str(value) if c.isprintable() or c in '\n\t')


def defaults_path():
    return Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'local-ai-sandbox/cockpit.json'


def load_defaults():
    path = defaults_path()
    if not path.exists():
        return {**DEFAULT_SETTINGS, 'options': options()}
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or set(value) - DEFAULT_SETTINGS.keys():
        raise ValueError('Invalid cockpit defaults file')
    result = {**DEFAULT_SETTINGS, **value}
    result['options'] = options(result['options'])
    memory_limit(result['memory'])
    if result['local_model_ports']:
        sandbox.local_model_ports(result['local_model_ports'])
    return result


def burp_default(engine):
    actual = sandbox.choose_engine(engine, quiet=True)
    return 'http://' + ('host.containers.internal' if actual == 'podman' else 'host.docker.internal') + ':9877'


def preset(profile, defaults):
    value = {**defaults, 'profile': profile, 'options': options(defaults.get('options'))}
    value['options'] = dict(value['options'])
    value['options']['disabled_skills'] = list(value['options']['disabled_skills'])
    if profile == 'websec' and not value['options']['burp_url']:
        value['options']['burp_url'] = burp_default(value['engine'])
    if profile != 'websec':
        value['options']['burp_url'] = ''
    rules = [f'local-model.internal:{p}' for p in sandbox.local_model_ports(value['local_model_ports'])] if value.get('local_model_ports') else []
    if value['options']['burp_url']:
        rules.append(endpoint_rule(value['options']['burp_url']) + ' # Host Burp relay')
    value['allowlist'] = '\n'.join(rules)
    return value


class Service:
    """Subprocess argument lists only; keys are sent to the container over stdin."""
    def __init__(self, state):
        self.state = Path(state)

    def command(self, *args):
        return [sys.executable, str(sandbox.ROOT / 'sandbox.py'), '--state-dir', str(self.state), *args]

    def inventory(self):
        result = subprocess.run(self.command('list', '--json'), capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def run(self, args, log):
        log('› ' + ' '.join(str(x) for x in args))
        with subprocess.Popen(self.command(*args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, errors='replace') as process:
            for line in process.stdout:
                log(safe_text(line.rstrip()))
            if process.wait():
                raise ValueError('Operation failed. See the log above; saved state is retained for retry.')

    def start(self, name, log):
        config = self.config(name)
        dev, proxy = sandbox.names(config)[:2]
        required = [dev, proxy] if sandbox.network_mode(config) == 'allowlist' else [dev]
        # Existing containers can resume even after their original image tags are removed.
        if any(sandbox.inspect(config, container) is None for container in required):
            images = sandbox.image_names(config)
            needed = images if sandbox.network_mode(config) == 'allowlist' else images[:1]
            if any(subprocess.run([config['engine'], 'image', 'inspect', image],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode for image in needed):
                self.run(['build', name], log)
        self.run(['up', name], log)

    def config(self, name):
        return json.loads((self.state / name / 'config.json').read_text())

    def create(self, draft, key, log):
        name = draft['name']
        state = self.state / name
        if state.exists():
            raise ValueError('That sandbox name is already saved; choose another name.')
        with tempfile.TemporaryDirectory(prefix='pi-sandbox-cockpit-') as temp:
            selected = Path(temp) / 'options.json'
            write_json(selected, draft['options'])
            args = ['create', name, '--profile', draft['profile'], '--workspace', draft['workspace'],
                    '--engine', draft['engine'], '--options-file', str(selected)]
            if draft['network'] == 'allowlist':
                rules = Path(temp) / 'allowlist.txt'
                rules.write_text(draft['allowlist'])
                args += ['--allowlist', str(rules)]
            else:
                args += ['--network', 'unrestricted']
            for field, flag in [('memory', '--memory'), ('env_file', '--env-file'), ('pi_config', '--pi-config')]:
                if draft.get(field):
                    args += [flag, draft[field]]
            if draft.get('skill_repo'):
                args += ['--skill-source', draft['skill_repo'], '--skill-path', draft['skill_path']]
            if draft.get('local_model_ports'):
                args += ['--local-model-ports', draft['local_model_ports']]
            if draft['subagents']:
                args += ['--subagents']
            self.run(args, log)
        self.run(['build', name], log)
        self.run(['up', name], log)
        self.setup(name, draft, key, log)

    def setup(self, name, draft, key, log):
        if draft.get('local_model_ports') and not draft['open_editor']:
            self.run(['configure', name], log)
        if draft['options']['burp_url']:
            self.run(['exec', name, '--', 'websec-mcp', draft['options']['burp_url'],
                      '--transport', draft['options']['burp_transport']], log)
        if draft['open_editor']:
            self.run(['open', name], log)

    def update(self, name, draft, key, log):
        changes = {k: draft[k] for k in ('network', 'memory', 'subagents', 'env_file', 'options')}
        changes['local_model_ports'] = draft.get('local_model_ports')
        changes.update(skill_source=draft.get('skill_repo', ''), skill_path=draft.get('skill_path', ''),
                       remove_skills=draft.get('remove_skills', []))
        changes['allowlist'] = draft['allowlist'] if draft['network'] == 'allowlist' else ''
        with tempfile.TemporaryDirectory(prefix='pi-sandbox-settings-') as temp:
            path = Path(temp) / 'settings.json'
            write_json(path, changes)
            self.run(['update', name, '--settings-file', str(path)], log)
        self.setup(name, {**draft, 'options': {**draft['options'], 'burp_url': ''}}, key, log)

    def ssh_settings(self, name, settings, log):
        with tempfile.TemporaryDirectory(prefix='sandbox-ssh-') as temp:
            path = Path(temp) / 'settings.json'
            write_json(path, {'ssh': settings})
            self.run(['update', name, '--settings-file', str(path)], log)

    def advisors(self, name, settings, log):
        with tempfile.TemporaryDirectory(prefix='sandbox-advisors-') as temp:
            path = Path(temp) / 'settings.json'
            write_json(path, {'advisors': settings})
            self.run(['update', name, '--settings-file', str(path)], log)

    def models(self, name, mode, log):
        if mode not in ('preview', 'refresh'):
            raise ValueError('Unknown discovery action')
        self.start(name, log)
        self.run(['configure', name] + (['--preview'] if mode == 'preview' else []), log)
        if mode == 'refresh':
            log('In an already open Pi/Pendant session, refresh there too before selecting a model with /model.')


class NetworkForm(Screen):
    BINDINGS = [('escape', 'back', 'Back')]

    def __init__(self, name, text):
        super().__init__()
        self.sandbox_name, self.rules = name, text

    def compose(self):
        yield Header()
        with VerticalScroll(classes='form'):
            yield Label('Network · ' + self.sandbox_name)
            yield Static('Update allowed destinations without restarting the development container. The gateway restarts briefly; active requests may need to reconnect. Host model ports stay unchanged.')
            yield Checkbox('pip · Python packages from PyPI', value=pip_allowed(self.rules), id='pip-preset')
            yield Checkbox('GitHub · repositories, API and release downloads', value=preset_allowed(self.rules, GITHUB_HOSTS), id='github-preset')
            yield TextArea(self.rules, id='allowlist')
            with Collapsible(title='Import or export rules', collapsed=True):
                yield Input(placeholder='Allowlist file path', id='network-file')
                with Horizontal(classes='buttons'):
                    yield Button('Import', id='network-import')
                    yield Button('Export', id='network-export')
            yield Static('', id='network-error')
        with Horizontal(classes='wizard-actions'):
            yield Button('Cancel', id='cancel-network')
            yield Button('Apply network', id='apply-network', variant='primary')
        yield Footer()

    @on(Checkbox.Changed, '#github-preset')
    def toggle_github(self, event):
        field = self.query_one('#allowlist', TextArea)
        field.load_text(preset_rules(field.text, event.value, GITHUB_HOSTS))

    @on(Checkbox.Changed, '#pip-preset')
    def toggle_pip(self, event):
        field = self.query_one('#allowlist', TextArea)
        field.load_text(pip_rules(field.text, event.value))

    @on(TextArea.Changed, '#allowlist')
    def sync_pip(self):
        checkbox = self.query_one('#pip-preset', Checkbox)
        with checkbox.prevent(TextualCheckbox.Changed):
            checkbox.value = pip_allowed(self.query_one('#allowlist', TextArea).text)
        github = self.query_one('#github-preset', Checkbox)
        with github.prevent(TextualCheckbox.Changed):
            github.value = preset_allowed(self.query_one('#allowlist', TextArea).text, GITHUB_HOSTS)

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        if event.button.id == 'cancel-network':
            self.action_back()
        elif event.button.id in ('network-import', 'network-export'):
            try:
                value = self.query_one('#network-file', Input).value.strip()
                if not value:
                    raise ValueError('Enter an allowlist file path.')
                path = Path(value).expanduser()
                field = self.query_one('#allowlist', TextArea)
                if event.button.id == 'network-import':
                    text = path.read_text()
                    sandbox.parse_rules(text)
                    field.load_text(text)
                else:
                    path.write_text(field.text)
                self.notify('Rules imported' if event.button.id == 'network-import' else 'Rules exported')
            except (OSError, ValueError) as error:
                self.query_one('#network-error', Static).update(str(error))
        elif event.button.id == 'apply-network':
            text = self.query_one('#allowlist', TextArea).text
            try:
                sandbox.parse_rules(text)
            except ValueError as error:
                self.query_one('#network-error', Static).update(str(error))
                return
            service = self.app.service
            def apply(log):
                with tempfile.TemporaryDirectory(prefix='sandbox-network-') as tmp:
                    path = Path(tmp) / 'allowlist.txt'
                    path.write_text(text)
                    service.run(['network', self.sandbox_name, '--allowlist', str(path)], log)
            self.app.pop_screen()
            self.app.push_screen(Operation('Updating network · ' + self.sandbox_name, apply))

    def action_back(self):
        self.app.pop_screen()


class Confirm(ModalScreen[bool]):
    def __init__(self, message, action):
        super().__init__()
        self.message, self.action = message, action

    def compose(self):
        with Vertical(id='confirm-box'):
            yield Static(self.message, markup=False)
            with Horizontal(classes='buttons'):
                yield Button('Cancel', id='cancel', variant='primary')
                yield Button(self.action, id='yes', variant='error')

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        self.dismiss(event.button.id == 'yes')


class MoreActions(ModalScreen[Optional[str]]):
    BINDINGS = [('escape', 'cancel', 'Back')]

    def __init__(self, record):
        super().__init__()
        running = record['dev'] == 'running'
        self.sandbox_name = record['name']
        self.actions = [('Stop sandbox' if running else 'Start sandbox', 'stop' if running else 'start'),
                        ('Pi terminal', 'pi'), ('Container shell', 'shell'),
                        ('Test MCP connections', 'connections'), ('Container logs', 'logs'),
                        ('Update sources and recreate…', 'rebuild'), ('Delete sandbox…', 'delete')]

    def compose(self):
        with Vertical(id='confirm-box'):
            yield Label('Actions · ' + self.sandbox_name)
            yield OptionList(*[label for label, _ in self.actions], id='more-actions')
            yield Button('Cancel', id='more-cancel')

    @on(OptionList.OptionSelected)
    def selected(self, event):
        event.stop()
        self.dismiss(self.actions[event.option_index][1])

    @on(Button.Pressed)
    def cancel(self, event):
        event.stop()
        self.dismiss(None)

    def action_cancel(self):
        self.dismiss(None)


class SettingsMenu(ModalScreen[Optional[str]]):
    BINDINGS = [('escape', 'cancel', 'Back')]
    ACTIONS = [('Network · allowed destinations and package presets', 'network-settings'),
               ('Models · endpoints and discovery', 'models'),
               ('Configuration · resources, tools and network mode', 'configuration'),
               ('Advisors · Codex and Antigravity', 'advisors'),
               ('SSH · hosts and private key access', 'ssh-settings')]

    def __init__(self, name):
        super().__init__()
        self.sandbox_name = name

    def compose(self):
        with Vertical(id='confirm-box'):
            yield Label('Settings · ' + self.sandbox_name)
            yield OptionList(*[label for label, _ in self.ACTIONS], id='settings-actions')
            yield Button('Back', id='settings-back')

    @on(OptionList.OptionSelected)
    def selected(self, event):
        event.stop()
        self.dismiss(self.ACTIONS[event.option_index][1])

    @on(Button.Pressed)
    def back(self, event):
        event.stop()
        self.dismiss(None)

    def action_cancel(self):
        self.dismiss(None)


class SSHScreen(Screen):
    BINDINGS = [('escape', 'back', 'Back')]

    def __init__(self, record):
        super().__init__()
        self.record = record
        self.imported = None

    def compose(self):
        hosts = self.record['config'].get('ssh', {}).get('hosts', [])
        yield Header()
        with VerticalScroll(classes='form'):
            yield Label('SSH · ' + self.record['name'], classes='title')
            yield Static('Choose the hosts this sandbox can access. The private key stays in a separate container; Pi uses it through an SSH agent.')
            yield Label('Destinations · alias username hostname-or-IP port')
            yield TextArea('\n'.join(f'{h["alias"]} {h["user"]} {h["hostname"]} {h["port"]}' for h in hosts), id='ssh-hosts')
            with Collapsible(title='Import host SSH aliases', collapsed=True):
                yield Input(placeholder='Aliases from your ~/.ssh/config, separated by spaces', id='ssh-aliases')
                yield Button('Import destinations', id='ssh-import-aliases')
            with Collapsible(title='Host identity and private key', collapsed=True):
                yield Label('Trusted known_hosts file · used when applying manually entered destinations')
                yield Input(str(Path.home() / '.ssh/known_hosts'), id='ssh-known-hosts')
                yield Label('Private key file on your computer · never mounted in the development container')
                yield Input(placeholder='~/.ssh/id_ed25519', id='ssh-key-file')
                with Horizontal(classes='buttons'):
                    yield Button('Import key and unlock', id='ssh-import-key', disabled=not hosts)
                    yield Button('Unlock existing key', id='ssh-unlock', disabled=not hosts)
            yield Static('Apply destinations first, then import a key. Encrypted keys ask for their passphrase directly in your terminal. Removing all destinations disables access; deleting the sandbox also deletes its private key copy.')
        with Horizontal(classes='wizard-actions'):
            yield Button('Apply', id='ssh-apply', variant='primary')
            yield Button('Back', id='ssh-back')
        yield Footer()

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        import sandbox_ssh
        action = event.button.id
        name = self.record['name']
        try:
            if action == 'ssh-back': self.action_back()
            elif action == 'ssh-import-aliases':
                settings = sandbox_ssh.import_aliases(self.query_one('#ssh-aliases', Input).value, Path.home() / '.ssh/config')
                text = '\n'.join(f'{h["alias"]} {h["user"]} {h["hostname"]} {h["port"]}' for h in settings['hosts'])
                self.query_one('#ssh-hosts', TextArea).load_text(text)
                self.imported = (text, settings)
                self.notify('Imported destinations and existing trusted host keys. No private key imported.')
            elif action in ('ssh-import-key', 'ssh-unlock'):
                args = ['ssh-unlock', name]
                if action == 'ssh-import-key':
                    path = self.query_one('#ssh-key-file', Input).value.strip()
                    if not path: raise ValueError('Choose a private key file')
                    args = ['ssh-import-key', name, '--key-file', path]
                with self.app.suspend():
                    subprocess.run(self.app.service.command(*args), check=False)
            elif action == 'ssh-apply':
                text = self.query_one('#ssh-hosts', TextArea).text
                old = self.record['config'].get('ssh', {'hosts': []})
                old_text = '\n'.join(f'{h["alias"]} {h["user"]} {h["hostname"]} {h["port"]}' for h in old['hosts'])
                settings = (self.imported[1] if self.imported and self.imported[0] == text else
                            old if text == old_text else sandbox_ssh.parse_hosts(text, self.query_one('#ssh-known-hosts', Input).value))
                def apply(yes):
                    if not yes: return
                    self.app.pop_screen()
                    self.app.push_screen(Operation('SSH destinations · ' + name, lambda log: self.app.service.ssh_settings(name, settings, log)))
                self.app.push_screen(Confirm('Apply SSH destinations?\nActive sandbox processes restart. Workspace and private key are preserved.\nThe key will be restricted to these users and trusted host identities.', 'Apply'), apply)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            self.notify(safe_text(error), severity='error')

    def action_back(self): self.app.pop_screen()


class AdvisorsScreen(Screen):
    BINDINGS = [('escape', 'back', 'Back')]

    def __init__(self, record):
        super().__init__()
        self.record = record

    def compose(self):
        settings = self.record['config'].get('advisors', {})
        providers = settings.get('providers', [])
        yield Header()
        with VerticalScroll(classes='form'):
            yield Label('Advisors · ' + self.record['name'], classes='title')
            yield Static('Ask Codex (OpenAI models) or Antigravity (Gemini models) for advice from Pi. Login stays in a separate container.')
            yield Checkbox('Codex', value='codex' in providers, id='advisor-codex')
            yield Checkbox('Antigravity · Gemini', value='agy' in providers, id='advisor-agy')
            yield Static('Apply builds the companion and reconnects the sandbox. Workspace and login state are preserved. Then sign in below; no host credentials are imported.')
            with Horizontal(classes='buttons'):
                yield Button('Sign in to Codex', id='advisor-login-codex', disabled='codex' not in providers)
                yield Button('Open Antigravity', id='advisor-login-agy', disabled='agy' not in providers)
                yield Button('Check providers', id='advisor-check', disabled=not providers)
            with Collapsible(title='Antigravity model', collapsed=True):
                yield Label('Exact Gemini model ID · leave blank to sign in first')
                yield Input(settings.get('agy_model', ''), id='advisor-model')
                yield Label('Quota group · from /usage')
                yield Input(settings.get('agy_quota_group', ''), id='advisor-quota')
                yield Label('Effort matching that model')
                yield Select([(x.title(), x) for x in ('low', 'medium', 'high')], value=settings.get('agy_effort', 'medium'), allow_blank=False, id='advisor-effort')
            with Collapsible(title='Usage and network', collapsed=True):
                yield Label('Maximum calls per Pi session · blank for no limit')
                yield Input(str(settings.get('max_calls') or ''), id='advisor-calls', type='integer')
                yield Static('Provider hosts use a separate allowlist. These rules do not change the development container’s network.')
                yield Label('Additional exact destinations · host:port, one per line')
                yield TextArea(settings.get('extra_hosts', ''), id='advisor-hosts')
        with Horizontal(classes='wizard-actions'):
            yield Button('Apply', id='advisor-apply', variant='primary')
            yield Button('Back', id='advisor-back')
        yield Footer()

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        action = event.button.id
        name = self.record['name']
        if action == 'advisor-back':
            self.action_back()
        elif action == 'advisor-check':
            self.app.pop_screen()
            self.app.operation('Advisor login, models and quota · ' + name, ['advisor-check', name])
        elif action and action.startswith('advisor-login-'):
            provider = action.removeprefix('advisor-login-')
            with self.app.suspend():
                subprocess.run(self.app.service.command('advisor-login', name, provider), check=False)
        elif action == 'advisor-apply':
            import sandbox_advisors
            try:
                calls = self.query_one('#advisor-calls', Input).value.strip()
                settings = sandbox_advisors.validate({
                    'providers': [p for p in ('codex', 'agy') if self.query_one('#advisor-' + p, Checkbox).value],
                    'agy_model': self.query_one('#advisor-model', Input).value.strip(),
                    'agy_quota_group': self.query_one('#advisor-quota', Input).value.strip(),
                    'agy_effort': self.query_one('#advisor-effort', Select).value,
                    'max_calls': int(calls) if calls else None,
                    'extra_hosts': self.query_one('#advisor-hosts', TextArea).text,
                })
            except ValueError as error:
                self.notify(str(error), severity='error')
                return
            def apply(yes):
                if not yes:
                    return
                self.app.pop_screen()
                self.app.push_screen(Operation('Advisors · ' + name, lambda log: self.app.service.advisors(name, settings, log)))
            self.app.push_screen(Confirm('Apply advisor settings?\nActive sandbox processes restart. Workspace, home and advisor logins are preserved.', 'Apply'), apply)

    def action_back(self):
        self.app.pop_screen()


class ModelsScreen(Screen):
    BINDINGS = [('escape', 'back', 'Back')]

    def __init__(self, record):
        super().__init__()
        self.record = record

    def compose(self):
        config = self.record['config']
        yield Header()
        with VerticalScroll(classes='form'):
            yield Label('Models · ' + self.record['name'], classes='title')
            yield Static('Host ports: ' + str(config.get('local_model_ports') or 'Not configured'))
            yield Static('Connection not checked. Preview discovers models without saving; Refresh updates the saved model catalogue.')
            yield Static('Endpoint and host-port changes are in Configuration and require recreating containers.')
            with Horizontal(classes='buttons'):
                yield Button('Preview', id='preview-models', disabled=not config.get('local_model_ports'))
                yield Button('Refresh catalogue', id='refresh-models', disabled=not config.get('local_model_ports'))
                yield Button('Configuration…', id='configuration')
        with Horizontal(classes='wizard-actions'):
            yield Button('Back', id='models-back')
        yield Footer()

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        action = event.button.id
        self.app.pop_screen()
        if action != 'models-back':
            self.app.perform(action)

    def action_back(self):
        self.app.pop_screen()


class Operation(Screen):
    BINDINGS = [Binding('escape', 'back', 'Back')]

    def __init__(self, title, task):
        super().__init__()
        self.title, self.operation_task, self.finished = title, task, False
        self.failed = False
        self.model_disconnected = False

    def compose(self):
        yield Header()
        with Vertical(id='operation-body'):
            yield Static(self.title, id='operation-title', markup=False)
            yield Static('●  Running', id='operation-status')
            yield RichLog(id='operation-log', markup=False, wrap=True)
            yield Button('Working…', id='operation-back', disabled=True)
        yield Footer()

    def on_mount(self):
        self.query_one(RichLog).border_title = 'Output'
        self.execute()

    @work(thread=True, exit_on_error=False)
    def execute(self):
        def log(message):
            if 'Model status: Not connected.' in str(message):
                self.model_disconnected = True
            self.app.call_from_thread(self.query_one(RichLog).write, safe_text(message))
        try:
            self.operation_task(log)
            log('Finished.')
        except Exception as error:
            self.failed = True
            log(str(error))
        finally:
            self.operation_task = None  # Release the completed task.
            self.app.call_from_thread(self.complete)

    def complete(self):
        self.finished = True
        button = self.query_one('#operation-back', Button)
        button.disabled, button.label = False, 'Back to sandboxes'
        status = self.query_one('#operation-status', Static)
        status.update('●  Failed · see output below' if self.failed else
                      '●  Complete · model not connected' if self.model_disconnected else '●  Complete')
        status.add_class('failed' if self.failed else 'disconnected' if self.model_disconnected else 'complete')
        output = self.query_one(RichLog)
        output.styles.height = min(18, max(6, len(output.lines) + 2))

    @on(Button.Pressed)
    def back(self, event):
        event.stop()
        self.action_back()

    def action_back(self):
        if self.finished:
            self.app.pop_screen()
            self.app.refresh_inventory()


class FolderPicker(ModalScreen[Optional[str]]):
    """Browse directories without requiring a desktop file dialog."""
    def __init__(self, start):
        super().__init__()
        candidate = Path(start).expanduser()
        self.folder = candidate if candidate.is_dir() else Path.home()

    def compose(self):
        with Vertical(id='folder-box'):
            yield Label('Choose workspace folder')
            yield Input(str(self.folder), id='folder-path')
            yield DataTable(id='folders', cursor_type='row')
            with Horizontal(classes='buttons'):
                yield Button('Up', id='folder-up')
                yield Button('Open folder', id='folder-open')
                yield Button('Use this folder', id='folder-use', variant='primary')
                yield Button('Cancel', id='folder-cancel')

    def on_mount(self):
        self.query_one(DataTable).add_column('Folders')
        self.refresh_folders()

    def refresh_folders(self):
        table = self.query_one(DataTable)
        table.clear()
        self.query_one(Input).value = str(self.folder)
        try:
            for path in sorted(self.folder.iterdir()):
                if path.is_dir() and not path.name.startswith('.'):
                    table.add_row(safe_text(path.name), key=str(path))
        except OSError as error:
            self.notify(str(error), severity='error')

    @on(DataTable.RowSelected)
    def enter_folder(self, event):
        event.stop()
        self.folder = Path(event.row_key.value)
        self.refresh_folders()

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        action = event.button.id
        if action == 'folder-cancel':
            self.dismiss(None)
        elif action == 'folder-up':
            self.folder = self.folder.parent
            self.refresh_folders()
        elif action in ('folder-use', 'folder-open'):
            path = Path(self.query_one(Input).value).expanduser()
            if not path.is_dir():
                self.notify('Enter an existing folder.', severity='error')
            elif action == 'folder-use':
                self.dismiss(str(path.resolve()))
            else:
                self.folder = path
                self.refresh_folders()


class NewSandbox(Screen):
    BINDINGS = [Binding('escape', 'back', 'Back')]

    def compose(self):
        yield Header()
        with VerticalScroll(classes='form'):
            yield Label('New sandbox · 1 of 2', classes='title')
            yield Label('Profile')
            yield Select([(v, k) for k, v in TITLES.items()] + [('Custom profile…', 'custom')],
                         value=self.app.defaults['profile'] if self.app.defaults['profile'] in TITLES else 'custom',
                         allow_blank=False, id='profile')
            with Vertical(id='custom-profile-fields'):
                yield Label('Custom profile folder')
                yield Input(id='custom-profile', placeholder='Folder containing profile.json, Dockerfile and profile.md')
            yield Label('Workspace')
            with Horizontal(classes='path-row'):
                yield Input(self.app.defaults['workspace_parent'], id='workspace')
                yield Button('Browse', id='browse')
            yield Checkbox('Create this workspace folder if it does not exist', id='mkdir')
            yield Label('Sandbox name')
            yield Input(id='name')
            yield Static('', id='new-error', classes='error', markup=False)
            with Horizontal(classes='buttons'):
                yield Button('Cancel', id='cancel')
                yield Button('Continue', id='continue', variant='primary')
        yield Footer()

    def on_mount(self):
        self.profile_changed()

    @on(Select.Changed, '#profile')
    def profile_changed(self):
        self.query_one('#custom-profile-fields').display = self.query_one('#profile', Select).value == 'custom'

    @on(Input.Changed, '#workspace')
    def suggest_name(self, event):
        current = self.query_one('#name', Input)
        if not current.value or current.value == getattr(self, 'suggested', ''):
            self.suggested = re.sub('[^a-z0-9-]+', '-', Path(event.value).name.lower()).strip('-')[:40]
            current.value = self.suggested

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        if event.button.id == 'cancel':
            self.action_back()
        elif event.button.id == 'browse':
            self.app.push_screen(FolderPicker(self.query_one('#workspace', Input).value), self.choose_folder)
        elif event.button.id == 'continue':
            try:
                profile = self.query_one('#profile', Select).value
                if profile == 'custom':
                    profile = self.query_one('#custom-profile', Input).value
                metadata = sandbox.load_profile(profile)
                name = self.query_one('#name', Input).value.strip()
                if not re.fullmatch('[a-z0-9][a-z0-9-]{0,39}', name):
                    raise ValueError('Name: use 1–40 lowercase letters, digits or hyphens.')
                if (self.app.state_root / name).exists():
                    raise ValueError('That name already exists. Choose another name.')
                workspace = Path(self.query_one('#workspace', Input).value).expanduser().resolve()
                if workspace in (Path('/'), Path.home()):
                    raise ValueError('Choose a project folder, not your home folder or filesystem root.')
                if not workspace.exists():
                    if not self.query_one('#mkdir', Checkbox).value:
                        raise ValueError('Choose an existing workspace or enable folder creation.')
                elif not workspace.is_dir():
                    raise ValueError('Workspace is not a directory.')
                draft = preset(metadata['name'], self.app.defaults)
                draft.update(profile=profile, name=name, workspace=str(workspace),
                             mkdir=self.query_one('#mkdir', Checkbox).value)
                self.app.push_screen(SettingsForm(draft))
            except (OSError, ValueError) as error:
                self.query_one('#new-error', Static).update(str(error))

    def choose_folder(self, value):
        if value:
            self.query_one('#workspace', Input).value = value

    def action_back(self):
        self.app.pop_screen()


class SettingsForm(Screen):
    BINDINGS = [Binding('escape', 'back', 'Back')]

    def __init__(self, draft, editing=False, defaults=False):
        super().__init__()
        self.draft, self.editing, self.defaults_mode = draft, editing, defaults
        self.profile_name = sandbox.load_profile(draft['profile'])['name']

    def compose(self):
        value, selected = self.draft, options(self.draft.get('options'))
        yield Header()
        with VerticalScroll(classes='form'):
            yield Label('Defaults for new sandboxes' if self.defaults_mode else
                        ('Sandbox settings' if self.editing else 'Review sandbox · 2 of 2'), classes='title')
            yield Static(('Profile: ' + TITLES.get(self.profile_name, self.profile_name)) +
                         ('' if self.defaults_mode else '\nWorkspace: ' + value['workspace']), markup=False)
            yield Checkbox('Connect to models on this host (rootless Podman)',
                           value=bool(value.get('local_model_ports')), id='local-models')
            yield Label('Host model ports · comma-separated ports or ranges')
            yield Input(value.get('local_model_ports') or '8000', id='model-ports')
            yield Static('Inside the sandbox, local-model.internal reaches host loopback through the restricted gateway.')
            yield Checkbox('Open VS Code after creation' if not self.editing else 'Open VS Code after applying',
                           value=value.get('open_editor', True), id='open-editor')
            if self.defaults_mode:
                yield Label('Default profile')
                yield Select([(v, k) for k, v in TITLES.items()], value=self.profile_name if self.profile_name in TITLES else 'base',
                             allow_blank=False, id='default-profile')
                yield Label('Workspace parent folder')
                yield Input(value.get('workspace_parent', ''), id='workspace-parent')
            with Collapsible(title='Network · ' + ('Restricted' if value['network'] == 'allowlist' else 'Unrestricted'), collapsed=True, id='network-section'):
                yield Label('Outer container network')
                yield Select([('Restricted — only allowed destinations', 'allowlist'),
                              ('Unrestricted — ordinary container network', 'unrestricted')],
                             value=value['network'], allow_blank=False, id='network')
                if self.editing:
                    yield Static('Allowed destinations: Settings → Network. Changes there preserve the development container.')
                with Vertical(id='network-rules-fields'):
                    yield Checkbox('pip · Python packages from PyPI', value=pip_allowed(value.get('allowlist', '')), id='pip-preset')
                    yield Checkbox('GitHub · repositories, API and release downloads', value=preset_allowed(value.get('allowlist', ''), GITHUB_HOSTS), id='github-preset')
                    yield Static('Allows pypi.org:443 and files.pythonhosted.org:443. Git URLs and other package indexes need separate entries.')
                    yield Label('Edit allowed destinations in Settings → Network.' if self.editing else 'Allowed destinations · one hostname:port per line; comments allowed')
                    yield TextArea(value.get('allowlist', ''), id='allowlist')
                    with Horizontal(classes='buttons'):
                        yield Button('Import file', id='import-rules')
                        yield Button('Export file', id='export-rules')
                        yield Button('Profile defaults', id='reset-rules')
                    yield Label('Allowlist file path (for import/export)')
                    yield Input(id='rules-path')
            if self.profile_name == 'websec':
                with Collapsible(title='Burp MCP · host relay connection', collapsed=True):
                    yield Label('Endpoint')
                    yield Input(selected['burp_url'], id='burp-url')
                    yield Label('Transport')
                    yield Select([('SSE', 'sse'), ('Streamable HTTP', 'http')], value=selected['burp_transport'],
                                 allow_blank=False, id='burp-transport')
                    yield Static('Burp and its relay run on the host. Relay: 9877 → Burp: 9876.\n'
                                 'Saving configures the MCP client; it does not start Burp.')
            with Collapsible(title='Agent · ' + selected['approval'].capitalize() + ' approval · Inner sandbox ' + ('on' if selected['inner_sandbox'] else 'off'), collapsed=True, id='agent-section'):
                yield Checkbox('Use inner command sandbox', value=selected['inner_sandbox'], id='inner-sandbox')
                yield Label('Approval mode')
                yield Select([('Automatic — review requests needing approval', 'automatic'),
                              ('Ask me — human approval', 'manual'), ('No approval prompts', 'off')],
                             value=selected['approval'], allow_blank=False, id='approval')
                yield Static('', id='approval-help', markup=False)
                yield Checkbox('Enable optional subagents', value=value['subagents'], id='subagents')
            with Collapsible(title='Skills and features', collapsed=True):
                yield Checkbox('Browser · Betterwright', value=selected['browser'], id='browser')
                yield Static('Installs a headless browser and its dependencies. Uses the selected network policy; no extra destinations are allowed.')
                for skill in PROFILE_SKILLS.get(self.profile_name, []):
                    yield Checkbox(SKILLS[skill][0], value=skill not in selected['disabled_skills'], id='skill-' + skill)
                for skill in value.get('extra_skills', []):
                    yield Checkbox(skill['name'] + ' — remote skill', value=True, id='extra-' + skill['name'])
                    yield Static(skill['repo'] + ' · ' + skill['commit'][:12], markup=False)
                yield Checkbox('Goals', value=selected['goals'], id='goals')
                yield Checkbox('Scheduled prompts in the current chat', value=selected['scheduling'], id='scheduling')
                yield Static('Installed profile skills can be enabled or disabled. Add a remote skill below.')
                yield Label('Additional skill Git repository URL')
                yield Input(value.get('skill_repo', ''), id='skill-repo')
                yield Label('Skill folder in that repository (must contain SKILL.md)')
                yield Input(value.get('skill_path', ''), id='skill-path')
            with Collapsible(title='Advanced settings', collapsed=True):
                yield Label('Container engine')
                yield Select([('Automatic — prefer rootless Podman', 'auto'), ('Podman', 'podman'), ('Docker', 'docker')],
                             value=value.get('engine', 'auto'), allow_blank=False, id='engine', disabled=self.editing)
                yield Label('Memory limit · empty means no explicit limit')
                yield Input(value.get('memory') or '', id='memory')
                yield Label('Credentials environment file · optional path')
                yield Input(value.get('env_file') or '', id='env-file')
                yield Label('Seed Pi agent directory · optional, fresh configuration by default')
                yield Input(value.get('pi_config') or '', id='pi-config', disabled=self.editing)
            yield Static('', id='form-error', classes='error', markup=False)
        with Horizontal(classes='wizard-actions'):
            yield Button('Back', id='back')
            yield Button('Save defaults' if self.defaults_mode else
                         ('Apply and recreate' if self.editing else 'Create and start'), id='apply', variant='primary')
        yield Footer()

    def on_mount(self):
        self.approval_description()
        if self.editing and self.draft['network'] == 'allowlist':
            self.query_one('#network-rules-fields').display = False

    def approval_description(self):
        mode = self.query_one('#approval', Select).value
        inner = self.query_one('#inner-sandbox', Checkbox).value
        if inner:
            text = 'Ordinary sandboxed commands run directly. '
            text += {'automatic': 'Boundary requests use automatic review.', 'manual': 'Boundary requests ask you.',
                     'off': 'Requests beyond the inner sandbox are refused.'}[mode]
        else:
            text = {'automatic': 'Shell commands require automatic review.', 'manual': 'Shell commands ask you.',
                    'off': 'Commands run directly inside the devcontainer.'}[mode]
        self.query_one('#approval-help', Static).update(text + ' The outer container network policy still applies.')
        self.query_one('#agent-section', Collapsible).title = ('Agent · ' + str(mode).capitalize()
            + ' approval · Inner sandbox ' + ('on' if inner else 'off'))

    @on(Select.Changed, '#approval')
    @on(Checkbox.Changed, '#inner-sandbox')
    def approval_changed(self):
        self.approval_description()

    @on(Select.Changed, '#engine')
    def engine_changed(self, event):
        if self.profile_name != 'websec' or self.editing or event.value == self.draft.get('engine', 'auto'):
            return
        try:
            old = burp_default(self.draft.get('engine', 'auto'))
            new = burp_default(event.value)
            field = self.query_one('#burp-url', Input)
            if field.value == old:
                field.value = new
                rules = self.query_one('#allowlist', TextArea)
                rules.load_text(rules.text.replace(endpoint_rule(old), endpoint_rule(new)))
            self.draft['engine'] = event.value
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            self.notify(safe_text(error), severity='error')

    @on(Checkbox.Changed, '#github-preset')
    def toggle_github(self, event):
        field = self.query_one('#allowlist', TextArea)
        field.load_text(preset_rules(field.text, event.value, GITHUB_HOSTS))

    @on(Checkbox.Changed, '#pip-preset')
    def pip_preset_changed(self, event):
        field = self.query_one('#allowlist', TextArea)
        field.load_text(pip_rules(field.text, event.value))

    @on(TextArea.Changed, '#allowlist')
    def allowlist_changed(self):
        checkbox = self.query_one('#pip-preset', Checkbox)
        with checkbox.prevent(TextualCheckbox.Changed):
            checkbox.value = pip_allowed(self.query_one('#allowlist', TextArea).text)
        github = self.query_one('#github-preset', Checkbox)
        with github.prevent(TextualCheckbox.Changed):
            github.value = preset_allowed(self.query_one('#allowlist', TextArea).text, GITHUB_HOSTS)

    @on(Select.Changed, '#network')
    def network_changed(self):
        mode = self.query_one('#network', Select).value
        self.query_one('#network-section', Collapsible).title = 'Network · ' + ('Restricted' if mode == 'allowlist' else 'Unrestricted')

    def collect(self):
        draft = dict(self.draft)
        def inp(id): return self.query_one('#' + id, Input).value.strip()
        def check(id): return self.query_one('#' + id, Checkbox).value
        draft['local_model_ports'] = inp('model-ports') if check('local-models') else None
        if draft['local_model_ports']:
            sandbox.local_model_ports(draft['local_model_ports'])
        selected = options(draft.get('options'))
        selected.update(approval=self.query_one('#approval', Select).value, inner_sandbox=check('inner-sandbox'),
                        goals=check('goals'), scheduling=check('scheduling'), browser=check('browser'))
        selected['disabled_skills'] = [s for s in SKILLS if
            (s in PROFILE_SKILLS.get(self.profile_name, []) and not check('skill-' + s))
            or (s not in PROFILE_SKILLS.get(self.profile_name, []) and s in selected['disabled_skills'])]
        if self.profile_name == 'websec':
            selected.update(burp_url=inp('burp-url'), burp_transport=self.query_one('#burp-transport', Select).value)
        draft.update(network=self.query_one('#network', Select).value, memory=memory_limit(inp('memory')),
                     subagents=check('subagents'), options=options(selected), engine=self.query_one('#engine', Select).value,
                     env_file=inp('env-file') or None, pi_config=inp('pi-config') or None,
                     open_editor=check('open-editor'),
                     skill_repo=inp('skill-repo'), skill_path=inp('skill-path'))
        draft['allowlist'] = self.query_one('#allowlist', TextArea).text if draft['network'] == 'allowlist' else ''
        # Local model ports are controlled by their labelled field; other rules stay intact.
        rules = [r for r in sandbox.parse_rules(draft['allowlist']) if r[0] != 'local-model.internal']
        if draft['local_model_ports']:
            rules += [('local-model.internal', p) for p in sandbox.local_model_ports(draft['local_model_ports'])]
            actual = sandbox.choose_engine(draft['engine'], quiet=True)
            sandbox.configure_local_gateway({'engine':actual, 'network':draft['network']}, draft['local_model_ports'], rules)
        if draft['network'] == 'allowlist' and not rules:
            raise ValueError('Add an allowed destination or enable host-local models.')
        draft['allowlist'] = '\n'.join(f'{host}:{port}' for host,port in rules)
        sandbox.validate_env(draft['env_file'])
        key = ''
        draft['remove_skills'] = [s['name'] for s in draft.get('extra_skills', []) if not check('extra-' + s['name'])]
        if draft['skill_repo']:
            sandbox_skills.validate_source(draft['skill_repo'], draft['skill_path'])
        if bool(draft['skill_repo']) != bool(draft['skill_path']):
            raise ValueError('Specify both the skill repository and its folder.')
        return draft, key

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        action = event.button.id
        try:
            if action == 'back':
                self.action_back()
            elif action == 'reset-rules':
                value = preset(self.profile_name, {**self.app.defaults,
                               'local_model_ports': self.query_one('#model-ports', Input).value if self.query_one('#local-models', Checkbox).value else None})
                self.query_one('#allowlist', TextArea).load_text(value['allowlist'])
            elif action in ('import-rules', 'export-rules'):
                path = Path(self.query_one('#rules-path', Input).value).expanduser()
                if action == 'import-rules':
                    text = path.read_text()
                    sandbox.parse_rules(text)
                    self.query_one('#allowlist', TextArea).load_text(text)
                else:
                    path.write_text(self.query_one('#allowlist', TextArea).text)
                self.notify('Allowlist ' + ('imported' if action == 'import-rules' else 'exported'))
            elif action == 'apply':
                draft, key = self.collect()
                if self.defaults_mode:
                    saved = {k: draft[k] for k in DEFAULT_SETTINGS if k in draft}
                    saved['profile'] = self.query_one('#default-profile', Select).value
                    saved['workspace_parent'] = self.query_one('#workspace-parent', Input).value.strip()
                    write_json(defaults_path(), saved)
                    self.app.defaults = load_defaults()
                    self.app.pop_screen()
                    self.notify('Defaults saved for future sandboxes.')
                elif self.editing:
                    self.app.push_screen(Confirm('Apply settings to ' + draft['name'] + '?\n'
                        'This recreates its containers and interrupts active processes.\n'
                        'Workspace files and saved private configuration/sessions are preserved.', 'Apply and recreate'),
                        lambda yes: self.submit(draft, key) if yes else None)
                else:
                    self.submit(draft, key)
        except (OSError, ValueError) as error:
            self.query_one('#form-error', Static).update(str(error))

    def submit(self, draft, key):
        service = self.app.service
        editing = self.editing
        def task(log):
            if draft.get('mkdir'):
                Path(draft['workspace']).mkdir(parents=True, exist_ok=True)
            if editing:
                service.update(draft['name'], draft, key, log)
            else:
                service.create(draft, key, log)
        self.app.pop_screen()
        if not editing:
            self.app.pop_screen()
        self.app.push_screen(Operation(('Updating ' if editing else 'Creating ') + draft['name'], task))

    def action_back(self):
        self.app.pop_screen()


class Cockpit(App):
    TITLE = 'Local AI Sandboxes'
    BINDINGS = [Binding('n', 'new', 'New'), Binding('r', 'refresh_inventory', 'Refresh'),
                Binding('slash', 'search', 'Search'), Binding('d', 'defaults', 'Defaults'), Binding('q', 'quit', 'Quit')]
    CSS = '''
    Screen { background: #171a1d; }
    Header { background: #f2b544; color: #171a1d; }
    Footer { background: #34383d; }
    .title { color: #f2b544; text-style: bold; margin: 0 0 1 0; }
    Label { margin: 0; height: auto; }
    .form { padding: 1 3; }
    .form > Static { height: auto; margin-bottom: 1; }
    Input, Select { margin-bottom: 1; }
    TextArea { height: 9; }
    Checkbox { height: 1; border: none; padding: 0; margin: 0 0 1 0; }
    Checkbox > .toggle--button { color: #f1f3f5; background: transparent; text-style: bold; }
    Checkbox.-on > .toggle--button { color: #f2b544; background: transparent; }
    Checkbox:focus > .toggle--label { color: #171a1d; background: #f2b544; text-style: bold underline; }
    Checkbox:focus > .toggle--button { color: #171a1d; background: #f2b544; }
    Button.-primary { background: #f2b544; color: #171a1d; }
    Button:focus { text-style: bold underline; }
    Collapsible { margin-bottom: 1; padding: 0; border: none; }
    .buttons { height: 1; min-height: 1; margin: 1 0; }
    .wizard-actions { dock: bottom; height: 3; padding: 1 3; }
    Button { height: 1; border: none; margin-right: 1; min-width: 8; }
    #custom-profile-fields, #network-rules-fields { height: auto; }
    #home > .buttons Label { width: 1fr; }
    #network-error { height: auto; color: #b75b52; }
    .path-row { height: 3; }
    .path-row Input { width: 1fr; }
    .error { color: #b75b52; height: auto; }
    #home { padding: 1 2; }
    #sandboxes { height: 1fr; min-height: 5; }
    #details { height: auto; min-height: 3; padding: 1; }
    #home-error { height: auto; color: #b75b52; }
    #operation-body { width: 100%; max-width: 112; padding: 1 2; }
    #operation-title { height: auto; text-style: bold; margin-bottom: 1; }
    #operation-status { height: 1; color: #f2b544; margin-bottom: 1; }
    #operation-status.complete { color: #4f8a62; }
    #operation-status.failed { color: #b75b52; }
    #operation-log { height: 1fr; max-height: 24; min-height: 5; border: round #34383d; padding: 0 1; }
    #operation-back { margin: 1 0; width: 24; }
    Confirm, FolderPicker, MoreActions, SettingsMenu { align: center middle; background: #000000 70%; }
    #confirm-box { width: 75; height: auto; max-height: 90%; padding: 2; background: #34383d; border: solid #f2b544; }
    #confirm-box Static { height: auto; }
    #folder-box { width: 85%; height: 85%; padding: 1 2; background: #34383d; border: solid #f2b544; }
    #folders { height: 1fr; }
    '''

    def __init__(self, state_root, service=None):
        super().__init__()
        self.register_theme(Theme(
            name='cockpit-gold', primary='#f2b544', secondary='#8a5a00', accent='#f2b544',
            foreground='#f1f3f5', background='#171a1d', surface='#25292e', panel='#34383d',
            success='#4f8a62', warning='#f2b544', error='#b75b52', dark=True,
            variables={'footer-key-foreground': '#f2b544', 'border': '#8a5a00',
                       'block-cursor-foreground': '#171a1d', 'block-cursor-background': '#f2b544',
                       'block-cursor-text-style': 'bold', 'input-selection-background': '#8a5a00'}))
        self.theme = 'cockpit-gold'
        self.state_root = Path(state_root)
        self.service = service or Service(self.state_root)
        self.records = []
        self.defaults = load_defaults()

    def compose(self):
        yield Header()
        with Vertical(id='home'):
            with Horizontal(classes='buttons'):
                yield Label('Sandboxes', classes='title')
                yield Button('New sandbox', id='new')
            yield Label('Search sandboxes')
            yield Input(id='search')
            yield DataTable(id='sandboxes', cursor_type='row', zebra_stripes=True)
            yield Static('Choose a sandbox, or create your first one.', id='details', markup=False)
            yield Static('', id='home-error', markup=False)
            with Horizontal(classes='buttons'):
                yield Button('Open in VS Code', id='open', variant='primary')
                yield Button('Settings', id='settings')
                yield Button('Actions…', id='more')
        yield Footer()

    def on_mount(self):
        self.query_one(DataTable).add_columns('Name', 'Status', 'Models', 'Network')
        self.refresh_inventory()

    @work(thread=True, exclusive=True, group='inventory', exit_on_error=False)
    def refresh_inventory(self):
        try:
            records = self.service.inventory()
            self.call_from_thread(self.receive_inventory, records)
        except Exception as error:
            self.call_from_thread(self.query_one('#home-error', Static).update, safe_text(error))

    def action_refresh_inventory(self):
        self.refresh_inventory()

    def receive_inventory(self, records):
        self.records = records
        self.query_one('#home-error', Static).update('')
        self.render_records()

    def render_records(self):
        table = self.query_one(DataTable)
        selected = self.selected_name()
        table.clear()
        text = self.query_one('#search', Input).value.casefold()
        for record in self.records:
            if text not in (record['name'] + ' ' + record['profile'] + ' ' + (record.get('workspace') or '')).casefold():
                continue
            config = record['config']
            table.add_row(*[safe_text(x) for x in (record['name'], record['dev'].capitalize(),
                          'Not checked' if config.get('local_model_ports') else 'Not configured',
                          'Restricted' if config.get('network', 'allowlist') == 'allowlist' else 'Unrestricted')], key=record['name'])
        if selected in table.rows:
            table.move_cursor(row=table.get_row_index(selected))
        self.update_details()

    def selected_name(self):
        table = self.query_one(DataTable)
        if table.row_count and table.cursor_row < table.row_count:
            return str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        return None

    def selected(self):
        name = self.selected_name()
        return next((r for r in self.records if r['name'] == name), None)

    @on(Input.Changed, '#search')
    def filter_records(self):
        self.render_records()

    @on(DataTable.RowHighlighted)
    def highlighted(self):
        self.update_details()

    def update_details(self):
        record = self.selected()
        text = 'No matching sandboxes. Press N to create one.'
        if record:
            text = 'Workspace: ' + str(record.get('workspace') or 'Unavailable')
            text += '\nEngine: ' + str(record.get('engine') or 'Unknown')
            text += ' · Gateway: ' + str(record.get('proxy', 'Unknown'))
            text += ' · Profile: ' + str(record['profile'])
        self.query_one('#details', Static).update(safe_text(text))
        for action in ('open', 'settings', 'more'):
            self.query_one('#' + action, Button).disabled = record is None

    @on(DataTable.RowSelected)
    def open_selected(self):
        self.perform('open')

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        self.perform(event.button.id)

    def action_quit(self):
        if isinstance(self.screen, Operation) and not self.screen.finished:
            self.notify('Wait for the current operation to finish before closing the cockpit.')
            return
        self.exit()

    def check_action(self, action, parameters):
        if action in ('new', 'search', 'refresh_inventory', 'defaults'):
            return self.screen is self.screen_stack[0]
        return True

    def action_defaults(self):
        self.perform('defaults')

    def action_search(self):
        if self.screen is self.screen_stack[0]:
            self.query_one('#search', Input).focus()

    def action_new(self):
        if self.screen is self.screen_stack[0]:
            self.push_screen(NewSandbox())

    def perform(self, action):
        try:
            self.perform_action(action)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            self.notify(safe_text(error), severity='error')

    def perform_action(self, action):
        if action == 'new':
            self.action_new()
            return
        if action == 'defaults':
            self.push_screen(SettingsForm(preset(self.defaults['profile'], self.defaults), defaults=True))
            return
        record = self.selected()
        if not record:
            self.notify('Choose a sandbox first.')
            return
        name, config = record['name'], record['config']
        if action == 'more':
            self.push_screen(MoreActions(record), lambda choice: self.perform(choice) if choice else None)
        elif action == 'settings':
            self.push_screen(SettingsMenu(name), lambda choice: self.perform(choice) if choice else None)
        elif action == 'ssh-settings':
            self.push_screen(SSHScreen(record))
        elif action == 'advisors':
            self.push_screen(AdvisorsScreen(record))
        elif action == 'models':
            self.push_screen(ModelsScreen(record))
        elif action == 'network-settings':
            if config.get('network', 'allowlist') != 'allowlist':
                self.notify('Use Settings to switch to restricted networking first.')
                return
            self.push_screen(NetworkForm(name, (self.state_root / name / 'allowlist.txt').read_text()))
        elif action == 'configuration':
            if not record.get('engine'):
                self.notify('Repair the saved configuration before editing it.', severity='error')
                return
            value = {**DEFAULT_SETTINGS, **config, 'profile': config.get('profile', {}).get('name', 'base'),
                     'options': options(config.get('options')), 'local_model_ports': config.get('local_model_ports')}
            # Custom profile names resolve to their recorded external snapshot.
            if value['profile'] not in TITLES:
                value['profile'] = config['profile']['path']
            value['allowlist'] = (self.state_root / name / 'allowlist.txt').read_text()
            self.push_screen(SettingsForm(value, editing=True))
        elif action in ('preview-models', 'refresh-models'):
            mode = 'preview' if action == 'preview-models' else 'refresh'
            self.push_screen(Operation('Local models · ' + name, lambda log: self.service.models(name, mode, log)))
        elif action == 'delete':
            self.push_screen(Confirm('Delete ' + name + '?\nRemoves private credentials, configuration, sessions and editor state.\n'
                                     'The host workspace and shared images are preserved.', 'Delete sandbox'),
                             lambda yes: self.operation('Deleting ' + name, ['delete', name]) if yes else None)
        elif action in ('pi', 'shell'):
            self.interactive(action, name)
        elif action == 'open':
            self.push_screen(Operation('Opening ' + name, lambda log: self.open_ready(name, log)))
        elif action == 'connections':
            args = ['exec', name, '--', 'pi', 'mcp', 'list']
            self.operation('Checking configured MCP connections', args)
        elif action == 'logs':
            def logs(log):
                result = subprocess.run([config['engine'], 'logs', '--tail', '100', sandbox.names(config)[0]],
                                        capture_output=True, text=True)
                log(result.stdout + result.stderr)
            self.push_screen(Operation('Container logs · ' + name, logs))
        elif action == 'rebuild':
            self.push_screen(Confirm('Fetch current profile sources, build and recreate ' + name + '?\n'
                                     'Active processes are interrupted after the build. Saved files and home persist.', 'Update and recreate'),
                lambda yes: self.operation('Updating ' + name, ['recreate', name, '--profile',
                    config.get('profile', {}).get('name', 'base') if config.get('profile', {}).get('name') in TITLES
                    else config['profile']['path']]) if yes else None)
        elif action == 'start':
            self.push_screen(Operation('Starting ' + name, lambda log: self.service.start(name, log)))
        elif action == 'stop':
            self.operation('Stopping ' + name, ['down', name])

    def open_ready(self, name, log):
        self.service.start(name, log)
        self.service.run(['open', name], log)

    def operation(self, title, args):
        self.push_screen(Operation(title, lambda log: self.service.run(args, log)))

    def interactive(self, command, name):
        with self.suspend():
            result = subprocess.run(self.service.command('up', name), check=False)
            if result.returncode == 0:
                subprocess.run(self.service.command(command, name), check=False)
        self.refresh_inventory()


def launch(state_root):
    Cockpit(state_root).run()
