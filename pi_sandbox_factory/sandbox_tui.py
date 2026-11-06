"""Terminal interface for Pi Sandbox Factory."""
import json
import copy
import asyncio
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import pyfiglet
import shutil
from typing import Optional

from . import sandbox
from .folders_ui import FolderFields
from .tui_widgets import Checkbox
from . import sandbox_skills
from . import registry, model_providers, updates, web_access, network_groups
from .sandbox_options import DEFAULTS, SKILLS, PROFILE_SKILLS, options, endpoint_rule, memory_limit, write_json

try:
    from textual import on, work
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.screen import ModalScreen, Screen
    from textual.theme import Theme
    from textual.widgets import (Button, Collapsible, DataTable, Footer, Header,
                                 Input, Label, RichLog, Select, Static, TextArea, OptionList)
except ImportError as error:
    raise SystemExit('Install Pi Sandbox Factory with pipx install git+https://github.com/kyuz0/pi-sandbox-factory.git.') from error

def profile_titles():
    return registry.choices('profile')
DEFAULT_SETTINGS = {'profile': 'base', 'model_providers': {'local':{}}, 'workspace_parent': '', 'network': 'allowlist',
                    'engine': 'podman', 'memory': '8g', 'subagents': False, 'env_file': '',
                    'pi_config': '', 'skill_repo': '', 'skill_path': '', 'open_editor': True,
                    'local_model_ports': '8000', 'options': DEFAULTS}


def safe_text(value):
    return ''.join(c for c in str(value) if c.isprintable() or c in '\n\t')


def defaults_path():
    return Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'pi-sandbox-factory/cockpit.json'


def search_keys_path():
    return defaults_path().with_name('web-access-keys.json')


def save_defaults_with_search(defaults, value, keys):
    path = search_keys_path()
    previous = json.loads(path.read_text()) if path.exists() and not path.is_symlink() else None
    defaults['options'] = options(defaults.get('options'))
    defaults['options']['web_access'] = web_access.save_keys(path, value, keys)
    try:
        write_json(defaults_path(), defaults)
    except OSError:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            write_json(path, previous)
        raise
    return defaults


def save_web_defaults(value, keys):
    return save_defaults_with_search(load_defaults(), value, keys)


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


def preset(profile, defaults):
    value = {**defaults, 'profile': profile, 'options': options(defaults.get('options'))}
    value['options'] = dict(value['options'])
    value['options']['disabled_skills'] = list(value['options']['disabled_skills'])
    rules = [f'local-model.internal:{p}' for p in sandbox.local_model_ports(value['local_model_ports'])] if value.get('local_model_ports') else []
    value['allowlist'] = '\n'.join(rules)
    return value


def copy_draft(record, state_root):
    """Copy declarative settings, never private state or credential file paths."""
    config = copy.deepcopy(record['config'])
    value = copy.deepcopy(DEFAULT_SETTINGS)
    for field in ('engine', 'network', 'memory', 'subagents', 'local_model_ports',
                  'model_providers', 'advisors', 'extra_skills', 'extra_folders'):
        if field in config:
            value[field] = copy.deepcopy(config[field])
    value.update(profile=config['profile']['path'], options=options(config.get('options')),
                 name='', workspace='', workspace_parent='', env_file='', pi_config='', working_directory='.',
                 reuse_from=record['name'], reused_profile=copy.deepcopy(config['profile']))
    value['allowlist'] = (Path(state_root) / record['name'] / 'allowlist.txt').read_text()
    for row in value['options']['web_access']['providers'].values():
        row['has_key'] = False
    return value


class Service:
    """Subprocess argument lists only; keys are sent to the container over stdin."""
    def __init__(self, state):
        self.state = Path(state)

    def command(self, *args):
        return [sys.executable, '-m', 'pi_sandbox_factory', '--state-dir', str(self.state), *args]

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

    def search_status(self, name):
        result = subprocess.run(self.command('web-key', name, '--status'), text=True, capture_output=True)
        return json.loads(result.stdout) if result.returncode == 0 else None

    def search_keys(self, name):
        result = subprocess.run(self.command('web-key', name, '--export-keys'), text=True, capture_output=True)
        if result.returncode:
            raise ValueError('Could not read saved search keys. Make sure the sandbox is running.')
        return json.loads(result.stdout)

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
            folder_file = Path(temp) / 'folders.json'
            write_json(folder_file, draft.get('extra_folders', []))
            args += ['--folders-file', str(folder_file), '--working-directory', draft.get('working_directory', '.')]
            if draft.get('reuse_from'):
                args += ['--reuse-from', draft['reuse_from']]
                for skill in draft.get('remove_skills', []):
                    args += ['--omit-skill', skill]
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
            providers=Path(temp)/'providers.json'
            write_json(providers,draft.get('model_providers',{'local':{}}))
            args += ['--providers-file',str(providers)]
            for provider in draft.get('advisors', {}).get('providers', []):
                args += ['--advisor', provider]
            if draft['subagents']:
                args += ['--subagents']
            self.run(args, log)
        self.run(['build', name], log)
        self.run(['up', name], log)
        self.setup(name, draft, key, log)
        if draft.get('advisors', {}).get('providers'):
            log('Advisors added. Return to Settings → Advisors to sign in; no login has been performed.')

    def setup(self, name, draft, key, log):
        if key:
            result = subprocess.run(self.command('web-key', name, '--keys-stdin'), input=json.dumps(key), text=True, capture_output=True)
            if result.returncode:
                raise ValueError('Could not save the search API key. Configure it with the web-key command.')
            log('Search API keys saved in the sandbox.')
        if (draft.get('local_model_ports') or draft.get('model_providers')) and not draft['open_editor']:
            self.run(['configure', name], log)
    def provider(self, name, provider, action, key, log):
        args=['configure', name, '--provider', provider]
        if action in ('status','preview'):args+=['--'+action]
        if key is not None:args+=['--key-stdin']
        result=subprocess.run(self.command(*args),input=key or '',capture_output=True,text=True)
        if result.returncode:raise ValueError('Provider operation failed. Check its settings and network access.')
        log(safe_text(result.stdout))
        if action not in ('status','preview'):
            log('Reload an open Pi/Pendant session before selecting newly discovered models.')

    def update(self, name, draft, key, log):
        changes = {k: draft[k] for k in ('network', 'memory', 'subagents', 'env_file', 'options')}
        changes['local_model_ports'] = draft.get('local_model_ports')
        changes['model_providers'] = draft.get('model_providers', {'local':{}})
        changes.update(skill_source=draft.get('skill_repo', ''), skill_path=draft.get('skill_path', ''),
                       remove_skills=draft.get('remove_skills', []))
        changes['allowlist'] = draft['allowlist'] if draft['network'] == 'allowlist' else ''
        with tempfile.TemporaryDirectory(prefix='pi-sandbox-settings-') as temp:
            path = Path(temp) / 'settings.json'
            write_json(path, changes)
            self.run(['update', name, '--settings-file', str(path)], log)
        self.setup(name, draft, key, log)

    def folders(self, name, settings, log):
        with tempfile.TemporaryDirectory(prefix='sandbox-folders-') as temp:
            path = Path(temp) / 'settings.json'
            write_json(path, settings)
            self.run(['update', name, '--settings-file', str(path)], log)

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


class WebsiteGroups(Vertical):
    DEFAULT_CSS = "WebsiteGroups { height: auto; }"

    def __init__(self, names):
        super().__init__()
        self.names = names

    def compose(self):
        with Collapsible(title='Website categories · optional', collapsed=True):
            yield Static('Categories allow HTTP/HTTPS access. Lists update automatically from V2Fly and UT1 Toulouse.', classes='section-intro')
            for prefix, title in [('dev-', 'Developer services · V2Fly'), ('ut1-', 'Topics · UT1 Toulouse')]:
                yield Label(title, classes='group-title')
                for name, group in network_groups.catalog().items():
                    if name.startswith(prefix):
                        with Vertical(classes='setting'):
                            yield Checkbox(group['title'], value=name in self.names, id='category-' + name)
                            yield Static(group['description'], classes='setting-help checkbox-help')

    def on_mount(self):
        self.update_title()

    @on(Checkbox.Changed)
    def update_title(self):
        count = len(self.selected())
        self.query_one(Collapsible).title = 'Website categories · ' + (f'{count} selected' if count else 'optional')

    def selected(self):
        return [name for name in network_groups.catalog() if self.query_one('#category-' + name, Checkbox).value]


class SearchProviderDialog(ModalScreen):
    BINDINGS = [('escape', 'cancel', 'Cancel')]
    DEFAULT_CSS = """
    SearchProviderDialog { align: center middle; background: #000000 70%; }
    #search-provider-dialog { width: 72; max-width: 95%; height: 90%; max-height: 32; padding: 1 2; background: #34383d; border: solid #f2b544; }
    #search-provider-dialog Static { height: auto; }
    #search-provider-fields { height: 1fr; }
    """

    def __init__(self, providers, name=None, selected_mode='auto'):
        super().__init__()
        self.providers, self.provider_name, self.selected_mode = providers, name, selected_mode
        self.original = providers.get(name, {})

    def compose(self):
        choices = [name for name in web_access.SERVICES if name == self.provider_name or name not in self.providers]
        name = self.provider_name or choices[0]
        with Vertical(id='search-provider-dialog'):
            yield Label('Edit search provider' if self.provider_name else 'Add search provider', classes='title')
            with VerticalScroll(id='search-provider-fields'):
                yield Label('Search provider')
                yield Select([(web_access.SERVICES[n][0], n) for n in choices], value=name, allow_blank=False, disabled=bool(self.provider_name), id='search-provider-name')
                with Vertical(id='search-endpoint-field', classes='setting'):
                    yield Label('Endpoint URL')
                    yield Input(self.original.get('endpoint', ''), id='search-endpoint')
                    yield Static('', id='search-endpoint-help', classes='setting-help')
                with Vertical(id='search-model-field', classes='setting'):
                    yield Label('Search model · optional')
                    yield Input(self.original.get('model', ''), id='search-model')
                with Vertical(id='search-key-field', classes='setting'):
                    yield Static('', id='search-key-status', classes='setting-help')
                    yield Label('API key · leave empty to keep the saved key' if self.original.get('has_key') else 'API key', id='search-key-label')
                    yield Input(password=True, id='search-key')
                    yield Checkbox('Remove saved key', id='search-remove-key')
            yield Static('', id='search-provider-error', markup=False)
            with Horizontal(classes='buttons dialog-actions'):
                yield Button('Cancel', id='search-cancel')
                if self.provider_name:
                    yield Button('Remove provider', id='search-remove')
                yield Button('Save', id='search-save', variant='primary')

    def on_mount(self):
        self.sync_fields()

    @on(Select.Changed, '#search-provider-name')
    def sync_fields(self):
        name = self.query_one('#search-provider-name', Select).value
        self.query_one('#search-endpoint-field').display = name in ('openai', 'searxng')
        self.query_one('#search-model-field').display = name == 'openai'
        self.query_one('#search-key-field').display = name != 'searxng'
        self.query_one('#search-endpoint-help', Static).update('Required: your SearXNG server URL.' if name == 'searxng' else 'Optional: a custom OpenAI Responses URL.')
        self.query_one('#search-remove-key', Checkbox).display = bool(self.original.get('has_key'))
        self.query_one('#search-key-status', Static).update('API key configured' if self.original.get('has_key') else 'No API key required' if name == 'exa' else 'API key missing · inactive')

    def action_cancel(self):
        self.dismiss(None)

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        if event.button.id == 'search-cancel':
            self.dismiss(None)
            return
        name = self.query_one('#search-provider-name', Select).value
        if event.button.id == 'search-remove':
            if name == self.selected_mode:
                self.query_one('#search-provider-error', Static).update('Choose another search mode before removing this provider.')
            else:
                self.dismiss((name, None, None))
            return
        try:
            endpoint = self.query_one('#search-endpoint', Input).value.strip() if name in ('openai', 'searxng') else ''
            has_key = self.original.get('has_key', False) and endpoint == self.original.get('endpoint', '')
            key = None
            if name != 'searxng':
                entered = self.query_one('#search-key', Input).value.strip()
                removed = self.query_one('#search-remove-key', Checkbox).value
                if removed and entered:
                    raise ValueError('Enter a replacement key or select Remove saved key.')
                if entered or removed:
                    key = '' if removed else entered
                    has_key = bool(key)
            row = web_access.provider_settings(name, {'endpoint': endpoint, 'has_key': has_key,
                'model': self.query_one('#search-model', Input).value if name == 'openai' else ''})
            self.dismiss((name, row, key))
        except ValueError as error:
            self.query_one('#search-provider-error', Static).update(str(error))


class CopyWebAccess(ModalScreen):
    BINDINGS = [('escape', 'cancel', 'Cancel')]
    DEFAULT_CSS = """
    CopyWebAccess { align: center middle; background: #000000 70%; }
    #copy-web-dialog { width: 72; max-width: 95%; height: auto; max-height: 95%; padding: 1 2; background: #34383d; border: solid #f2b544; }
    #copy-web-dialog Static { height: auto; }
    """

    def __init__(self, records):
        super().__init__()
        self.records = {record['name']: record for record in records}

    def compose(self):
        with VerticalScroll(id='copy-web-dialog'):
            yield Label('Copy web access from sandbox')
            yield Select([(name, name) for name in self.records], value=next(iter(self.records)), allow_blank=False, id='copy-web-source')
            yield Checkbox('Include search API keys', value=True, id='copy-web-keys')
            yield Static('', id='copy-web-help', markup=False)
            yield Static('', id='copy-web-error', markup=False)
            with Horizontal(classes='buttons dialog-actions'):
                yield Button('Cancel', id='copy-web-cancel')
                yield Button('Copy configuration', id='copy-web-apply', variant='primary')

    def on_mount(self):
        self.source_changed()

    @on(Select.Changed, '#copy-web-source')
    def source_changed(self):
        record = self.records[self.query_one('#copy-web-source', Select).value]
        checkbox = self.query_one('#copy-web-keys', Checkbox)
        checkbox.disabled = record['dev'] != 'running'
        checkbox.value = not checkbox.disabled
        self.query_one('#copy-web-help', Static).update(
            'Start this sandbox to include its saved API keys.' if checkbox.disabled else
            'Copies provider settings and selected keys into this form. The source sandbox is unchanged.')

    def action_cancel(self):
        self.dismiss(None)

    @on(Button.Pressed)
    async def pressed(self, event):
        event.stop()
        if event.button.id == 'copy-web-cancel':
            self.dismiss(None)
            return
        button = self.query_one('#copy-web-apply', Button)
        button.disabled = True
        try:
            record = self.records[self.query_one('#copy-web-source', Select).value]
            value = web_access.settings(options(record['config'].get('options'))['web_access'])
            include_keys = self.query_one('#copy-web-keys', Checkbox).value
            keys = {}
            if include_keys:
                stored = await asyncio.to_thread(self.app.service.search_keys, record['name'])
                keys = web_access.matching_keys(stored, value)
            for name, row in value['providers'].items():
                row['has_key'] = bool(keys.get(name))
                if name != 'searxng':
                    keys.setdefault(name, '')  # Clear matching credentials in an edited target sandbox.
            self.dismiss((value, keys if include_keys else None))
        except (OSError, ValueError) as error:
            self.query_one('#copy-web-error', Static).update(str(error))
            button.disabled = False


class WebAccessForm(Vertical):
    DEFAULT_CSS = """
    WebAccessForm, #web-fields, #web-provider-list { height: auto; }
    .search-provider-row { height: auto; min-height: 2; margin-bottom: 1; max-width: 48; }
    #web-fields > .buttons { margin-top: 0; }
    .search-provider-row Static { width: 1fr; height: auto; }
    """

    def __init__(self, value, defaults=False):
        super().__init__()
        self.value, self.defaults_mode = web_access.settings(value), defaults
        self.providers = self.value['providers']
        self.keys = {}

    def compose(self):
        with Collapsible(title='Web access · search and read pages', collapsed=True, id='web-section'):
            with Vertical(classes='setting'):
                yield Checkbox('Enable pi-web-access', value=self.value['enabled'], id='web-enabled')
                yield Static('Search provider endpoints are allowed automatically. Reading pages uses your network rules and website categories.', classes='setting-help checkbox-help')
            with Vertical(id='web-fields'):
                with Vertical(classes='setting'):
                    yield Label('Search mode')
                    yield Select(self.mode_choices(), value=self.value['mode'], allow_blank=False, id='web-mode')
                yield Vertical(id='web-provider-list')
                with Horizontal(classes='buttons'):
                    yield Button('Add provider', id='web-add')
                    yield Button('Copy from sandbox…', id='web-copy')
                with Vertical(classes='setting', id='web-defaults-setting'):
                    yield Button('Save as default web access', id='web-save-defaults')
                    yield Static('Includes API keys, stored privately on this workstation for new sandboxes.', classes='setting-help')
                yield Static('', id='web-active', markup=False, classes='setting-help')

    def copy_sources(self):
        current = self.screen.draft.get('name') if getattr(self.screen, 'editing', False) else None
        return [record for record in self.app.records if record['name'] != current
                and options(record['config'].get('options'))['web_access']['enabled']]

    async def copied(self, result):
        if result is None:
            return
        value, keys = result
        if keys is None:
            keys = {}
            for name, row in value['providers'].items():
                previous = self.providers.get(name, {})
                if getattr(self.screen, 'editing', False) and previous.get('endpoint') == row['endpoint']:
                    row['has_key'] = previous.get('has_key', False)
                    if name in self.keys:
                        keys[name] = self.keys[name]
                elif name != 'searxng':
                    keys[name] = ''
        self.value, self.keys = value, keys
        self.providers = self.value['providers']
        self.query_one('#web-enabled', Checkbox).value = self.value['enabled']
        mode = self.query_one('#web-mode', Select)
        mode.set_options(self.mode_choices())
        mode.value = self.value['mode']
        await self.refresh_providers()

    def mode_choices(self):
        return [('Automatic fallback', 'auto')] + [('Only ' + web_access.SERVICES[name][0], name) for name in self.providers]

    async def on_mount(self):
        if not getattr(self.screen, 'editing', False):
            supplied = getattr(self.screen, 'search_keys', None)
            self.keys = dict(supplied) if supplied is not None else web_access.saved_keys(search_keys_path(), self.value)
            for name, row in self.providers.items():
                row['has_key'] = bool(self.keys.get(name))
        await self.refresh_providers()
        self.sync_fields()
        self.query_one('#web-copy', Button).disabled = not self.copy_sources()
        self.query_one('#web-defaults-setting').display = not self.defaults_mode
        if getattr(self.screen, 'editing', False) and hasattr(self.app.service, 'search_status'):
            self.refresh_key_status(self.screen.draft['name'])

    @work(exclusive=True)
    async def refresh_key_status(self, name):
        original = {provider: dict(row) for provider, row in self.providers.items()}
        try:
            statuses = await asyncio.to_thread(self.app.service.search_status, name)
        except (OSError, ValueError):
            return
        if statuses is None:
            return
        for provider, row in self.providers.items():
            if row == original.get(provider) and provider not in self.keys:
                row['has_key'] = row['has_key'] and statuses.get(provider, False)
        await self.refresh_providers()

    async def refresh_providers(self):
        listing = self.query_one('#web-provider-list', Vertical)
        await listing.remove_children()
        mode = self.query_one('#web-mode', Select).value
        for name, row in self.providers.items():
            status = ('API key configured' if row['has_key'] else 'No API key required') if name == 'exa' else ('Server configured' if row['endpoint'] else 'Server URL missing · inactive') if name == 'searxng' else ('API key configured' if row['has_key'] else 'API key missing · inactive')
            if mode not in ('auto', name):
                status += ' · saved, not used'
            await listing.mount(Horizontal(Static(web_access.SERVICES[name][0] + '\n' + status, markup=False), Button('Edit', id='web-edit-' + name), classes='search-provider-row'))
        self.query_one('#web-add', Button).disabled = len(self.providers) == len(web_access.SERVICES)
        names = [web_access.SERVICES[n][0] for n, row in self.providers.items() if mode in ('auto', n) and web_access.ready(n, row)]
        self.query_one('#web-active', Static).update('Active providers: ' + (', '.join(names) or 'none'))
        self.sync_fields()

    @on(Checkbox.Changed, '#web-enabled')
    def sync_fields(self):
        enabled = self.query_one('#web-enabled', Checkbox).value
        self.query_one('#web-fields').display = enabled
        mode = self.query_one('#web-mode', Select).value
        self.query_one('#web-section', Collapsible).title = 'Web access · ' + (
            ('Automatic fallback' if mode == 'auto' else 'Only ' + web_access.SERVICES[mode][0]) if enabled else 'Off')

    @on(Select.Changed, '#web-mode')
    async def mode_changed(self):
        await self.refresh_providers()

    @on(Button.Pressed)
    async def edit_provider(self, event):
        button = event.button.id or ''
        if button == 'web-copy':
            event.stop()
            self.app.push_screen(CopyWebAccess(self.copy_sources()), self.copied)
            return
        if button == 'web-save-defaults':
            event.stop()
            try:
                value, keys = await self.defaults_selection()
                self.app.defaults = save_web_defaults(value, keys)
                self.notify('Web access defaults saved, including API keys.')
            except (OSError, ValueError) as error:
                self.notify(str(error), severity='error')
            return
        if button != 'web-add' and not button.startswith('web-edit-'):
            return
        event.stop()
        name = button.removeprefix('web-edit-') if button.startswith('web-edit-') else None
        self.app.push_screen(SearchProviderDialog(self.providers, name,
            self.query_one('#web-mode', Select).value), self.provider_saved)

    async def provider_saved(self, result):
        if result is None:
            return
        name, row, key = result
        old = self.providers.get(name)
        if row is None:
            self.providers.pop(name)
            self.keys.pop(name, None)
        else:
            self.providers[name] = row
            if old and old['endpoint'] != row['endpoint']:
                self.keys.pop(name, None)
            if key is not None:
                self.keys[name] = key
        mode = self.query_one('#web-mode', Select)
        selected = mode.value
        mode.set_options(self.mode_choices())
        mode.value = selected
        await self.refresh_providers()

    async def defaults_selection(self):
        value, pending = self.collect()
        keys = {}
        form = self.screen
        if isinstance(form, SettingsForm) and form.editing:
            needed = [name for name, row in value['providers'].items() if row['has_key'] and name not in pending]
            if needed:
                stored = await asyncio.to_thread(self.app.service.search_keys, form.draft['name'])
                keys.update(web_access.matching_keys(stored, value))
        keys.update(pending)
        missing = [web_access.SERVICES[name][0] for name, row in value['providers'].items()
                   if row['has_key'] and not keys.get(name)]
        if missing:
            raise ValueError('Enter API keys before saving defaults for: ' + ', '.join(missing))
        return value, keys

    def collect(self):
        value = web_access.settings({'enabled': self.query_one('#web-enabled', Checkbox).value,
            'mode': self.query_one('#web-mode', Select).value, 'providers': self.providers})
        if value['enabled'] and not web_access.active(value):
            raise ValueError('Configure a search provider with the required key or server URL.')
        return value, dict(self.keys)


class NetworkForm(Screen):
    BINDINGS = [('escape', 'back', 'Back')]

    def __init__(self, name, text, config=None):
        super().__init__()
        self.sandbox_name, self.rules = name, text
        self.config = config or {}

    def compose(self):
        yield Header()
        with VerticalScroll(classes='form'):
            yield Label('Network · ' + self.sandbox_name, classes='title')
            yield Static('Applying network changes restarts the gateway; active requests may need to reconnect. Development processes keep running.')
            yield WebsiteGroups(options(self.config.get('options'))['website_groups'])
            search = web_access.destinations(options(self.config.get('options'))['web_access'])
            if search:
                yield Static('Search service also allows: ' + ', '.join(f'{host}:{port}' for host, port in search), markup=False)
            yield Label('Additional allowed destinations · hostname:port')
            yield TextArea(self.rules, id='allowlist')
            with Collapsible(title='Import or export rules', collapsed=True):
                yield Label('Allowlist file path')
                yield Input(placeholder='~/network-rules.txt', id='network-file')
                with Horizontal(classes='buttons'):
                    yield Button('Import', id='network-import')
                    yield Button('Export', id='network-export')
            yield Static('', id='network-error')
        with Horizontal(classes='wizard-actions'):
            yield Button('Cancel', id='cancel-network')
            yield Button('Apply network', id='apply-network', variant='primary')
        yield Footer()

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
            groups = self.query_one(WebsiteGroups).selected()
            def apply(log):
                with tempfile.TemporaryDirectory(prefix='sandbox-network-') as tmp:
                    path = Path(tmp) / 'allowlist.txt'
                    path.write_text(text)
                    service.run(['network', self.sandbox_name, '--allowlist', str(path), '--website-groups', *groups], log)
            self.app.pop_screen()
            self.app.push_screen(Operation('Updating network · ' + self.sandbox_name, apply))

    def action_back(self):
        self.app.pop_screen()


class Confirm(ModalScreen[bool]):
    BINDINGS = [('escape', 'cancel', 'Cancel')]

    def action_cancel(self):
        self.dismiss(False)

    def __init__(self, message, action):
        super().__init__()
        self.message, self.action = message, action

    def compose(self):
        with Vertical(id='confirm-box'):
            yield Static(self.message, markup=False)
            with Horizontal(classes='buttons dialog-actions'):
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
                        ('Container shell', 'shell'),
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
    ACTIONS = [('Network · website categories and allowed destinations', 'network-settings'),
               ('Models · endpoints and discovery', 'models'),
               ('Configuration · resources, tools and network mode', 'configuration'),
               ('Advisors · Codex, Antigravity and Claude', 'advisors'),
               ('SSH · hosts and private key access', 'ssh-settings'),
               ('Folders · starting folder and host mounts', 'folders'),
               ('Web access · search providers and API keys', 'web-access')]

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


class FoldersScreen(Screen):
    BINDINGS = [('escape', 'back', 'Back')]

    def __init__(self, record):
        super().__init__()
        self.record = record

    def compose(self):
        yield Header()
        with VerticalScroll(classes='form'):
            yield Label('Folders · ' + self.record['name'], classes='title')
            yield FolderFields(self.record['config'], self.app.state_root)
            yield Static('Changing host mounts recreates the sandbox. Changing only the starting folder takes effect when you reopen Pi or VS Code.')
            yield Static('', id='folders-error', classes='error', markup=False)
        with Horizontal(classes='wizard-actions'):
            yield Button('Back', id='folders-back')
            yield Button('Apply', id='folders-apply', variant='primary')
        yield Footer()

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        if event.button.id == 'folders-back':
            self.action_back()
        elif event.button.id == 'folders-apply':
            try:
                selected = self.query_one(FolderFields).collect()
                def apply():
                    self.app.pop_screen()
                    self.app.push_screen(Operation('Updating folders', lambda log: self.app.service.folders(self.record['name'], selected, log)))
                if selected['extra_folders'] != self.record['config'].get('extra_folders', []):
                    self.app.push_screen(Confirm('Apply folder mounts? This recreates the sandbox and interrupts running processes.', 'Apply and recreate'), lambda yes: apply() if yes else None)
                else:
                    apply()
            except (ValueError, OSError) as error:
                self.query_one('#folders-error', Static).update(str(error))

    def action_back(self):
        self.app.pop_screen()


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
            yield Button('Back', id='ssh-back')
            yield Button('Apply', id='ssh-apply', variant='primary')
        yield Footer()

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        from . import sandbox_ssh
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
            yield Static('Ask Codex (OpenAI models), Antigravity (Gemini models) or Claude for advice from Pi. Login stays in a separate container.')
            yield Checkbox('Codex', value='codex' in providers, id='advisor-codex')
            yield Checkbox('Antigravity · Gemini', value='agy' in providers, id='advisor-agy')
            yield Checkbox('Claude', value='claude' in providers, id='advisor-claude')
            yield Static('Sign-in is available only after the advisor has been added to this sandbox. Select Apply, wait for setup to finish, then reopen Settings → Advisors to sign in. Applying settings restarts the sandbox; files and saved logins are preserved.', id='advisor-login-help')
            with Horizontal(classes='buttons'):
                yield Button('Sign in to Codex', id='advisor-login-codex', disabled='codex' not in providers)
                yield Button('Open Antigravity', id='advisor-login-agy', disabled='agy' not in providers)
            with Horizontal(classes='buttons'):
                yield Button('Sign in to Claude', id='advisor-login-claude', disabled='claude' not in providers)
                yield Button('Check advisors', id='advisor-check', disabled=not providers)
            with Collapsible(title='Antigravity model', collapsed=True):
                yield Label('Exact Gemini model ID · leave blank to sign in first')
                yield Input(settings.get('agy_model', ''), id='advisor-model')
                yield Label('Quota group · from /usage')
                yield Input(settings.get('agy_quota_group', ''), id='advisor-quota')
                yield Label('Effort matching that model')
                yield Select([(x.title(), x) for x in ('low', 'medium', 'high')], value=settings.get('agy_effort', 'medium'), allow_blank=False, id='advisor-effort')
            with Collapsible(title='Claude model', collapsed=True):
                yield Label('Model alias or exact ID · default sonnet')
                yield Input(settings.get('claude_model', 'sonnet'), id='advisor-claude-model')
                yield Label('Thinking effort')
                yield Select([(x.title(), x) for x in ('low', 'medium', 'high', 'xhigh', 'max')], value=settings.get('claude_effort', 'medium'), allow_blank=False, id='advisor-claude-effort')
                yield Static('Use /advisor status in Pi to refresh Claude subscription quota and reset times without a model call.')
            with Collapsible(title='Usage and network', collapsed=True):
                yield Label('Maximum calls per Pi session · blank for no limit')
                yield Input(str(settings.get('max_calls') or ''), id='advisor-calls', type='integer')
                yield Static('These destinations apply to the advisor’s separate gateway.')
                yield Label('Additional exact destinations · host:port, one per line')
                yield TextArea(settings.get('extra_hosts', ''), id='advisor-hosts')
        with Horizontal(classes='wizard-actions'):
            yield Button('Back', id='advisor-back')
            yield Button('Apply', id='advisor-apply', variant='primary')
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
            from . import sandbox_advisors
            try:
                calls = self.query_one('#advisor-calls', Input).value.strip()
                settings = sandbox_advisors.validate({
                    'providers': [p for p in ('codex', 'agy', 'claude') if self.query_one('#advisor-' + p, Checkbox).value],
                    'claude_model': self.query_one('#advisor-claude-model', Input).value.strip() or 'sonnet',
                    'claude_effort': self.query_one('#advisor-claude-effort', Select).value,
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
    BINDINGS=[('escape','back','Back')]
    def __init__(self,record):
        super().__init__();self.record=record
    def compose(self):
        rows=self.record['config'].get('model_providers',[{'name':'local','manifest':{}}])
        yield Header()
        with VerticalScroll(classes='form'):
            yield Label('Models · '+self.record['name'],classes='title')
            yield Static('Choose a model source to check or refresh. Add sources and edit their settings in Configuration.')
            yield Label('Model provider')
            yield Select([(r['manifest'].get('description',r['name']),r['name']) for r in rows],id='model-provider',allow_blank=not rows,value=rows[0]['name'] if rows else Select.BLANK)
            yield Label('Provider credential · when required')
            yield Input(password=True,id='provider-key')
            with Horizontal(classes='buttons'):
                yield Button('Status',id='provider-status')
                yield Button('Preview',id='provider-preview')
                yield Button('Refresh',id='provider-refresh')
            with Horizontal(classes='buttons'):
                yield Button('Configure credentials',id='provider-auth')
                yield Button('Configuration…',id='configuration')
        with Horizontal(classes='wizard-actions'):
            yield Button('Back',id='models-back')
        yield Footer()
    @on(Button.Pressed)
    def pressed(self,event):
        event.stop();action=event.button.id
        if action in ('configuration','models-back'):
            self.app.pop_screen()
            if action=='configuration':self.app.perform(action)
            return
        selected=self.query_one('#model-provider',Select).value
        if selected is Select.BLANK:return
        key=self.query_one('#provider-key',Input).value if action=='provider-auth' else None
        if action=='provider-auth' and not key.strip():self.notify('Enter the provider credential first.',severity='error');return
        self.query_one('#provider-key',Input).value=''
        service=self.app.service
        def task(log):
            service.provider(self.record['name'], selected, action.removeprefix('provider-'), key, log)
        self.app.pop_screen();self.app.push_screen(Operation('Provider · '+selected,task))
    def action_back(self):self.app.pop_screen()


class PackageRow(Vertical):
    def __init__(self, name, description, record=None):
        super().__init__(classes='package-row')
        self.package_name, self.description, self.record = name, description, record

    def compose(self):
        yield Static(self.description or self.package_name, classes='package-title', markup=False)
        if self.record is None:
            yield Static('Included with Pi Sandbox Factory', markup=False)
        else:
            yield Static('Local name: ' + self.package_name, markup=False)
            source = self.record['source']
            if self.record.get('subdir', '.') != '.':
                source += ' · ' + self.record['subdir']
            if self.record.get('ref'):
                source += ' · ' + self.record['ref']
            yield Static(source, markup=False)
            with Horizontal(classes='package-actions'):
                yield Button('Update', name='update')
                yield Button('Remove', name='remove')


class PackagesScreen(Screen):
    BINDINGS=[('escape','back','Back')]
    def compose(self):
        yield Header()
        with VerticalScroll(classes='form'):
            yield Label('Profiles and Providers',classes='title')
            with Vertical(classes='setting'):
                yield Static('Profiles add tools, skills and instructions. Providers configure the models Pi can use.')
            with Vertical(classes='setting'):
                yield Label('Show installed')
                yield Select([('Profiles','profile'),('Providers','provider')],value='profile',allow_blank=False,id='package-kind')
            yield Vertical(id='package-list')
            yield Static('Package updates apply when you create a sandbox or update its sources.', classes='setting-help')
        with Horizontal(classes='wizard-actions'):
            yield Button('Back',id='packages-back')
            yield Button('Install profile…',id='package-install',variant='primary')
        yield Footer()

    async def on_mount(self):
        await self.show_packages()

    async def on_screen_resume(self):
        if self.is_mounted:
            await self.show_packages()

    @on(Select.Changed,'#package-kind')
    async def changed(self):
        await self.show_packages()

    async def show_packages(self):
        kind=self.query_one('#package-kind',Select).value
        if kind is Select.BLANK:return
        self.query_one('#package-install',Button).label='Install '+kind+'…'
        listing=self.query_one('#package-list',Vertical)
        await listing.remove_children()
        installed=registry.installed(kind)
        await listing.mount(*(PackageRow(name, description, installed.get(name))
                              for name, description in registry.choices(kind).items()))

    def run_package_action(self, kind, action, name):
        service=self.app.service
        self.app.push_screen(Operation(action.capitalize()+' '+kind+' · '+name,
                                       lambda log:service.run([kind,action,name],log),
                                       back_label='Back to profiles and providers'))

    @on(Button.Pressed)
    def pressed(self,event):
        event.stop()
        if event.button.id=='packages-back':self.action_back();return
        kind=self.query_one('#package-kind',Select).value
        if event.button.id=='package-install':
            self.app.push_screen(InstallPackage(kind));return
        row=event.button.parent.parent
        if not isinstance(row,PackageRow):return
        name,action=row.package_name,event.button.name
        if action=='remove':
            self.app.push_screen(Confirm('Remove '+kind+' “'+name+'”? Existing sandboxes keep their saved copy.', 'Remove'),
                                 lambda yes:self.run_package_action(kind,action,name) if yes else None)
        elif action=='update':
            self.run_package_action(kind,action,name)

    def action_back(self):self.app.pop_screen()


class InstallPackage(Screen):
    BINDINGS=[('escape','back','Cancel')]

    def __init__(self, kind):
        super().__init__()
        self.kind=kind

    def compose(self):
        yield Header()
        with VerticalScroll(classes='form'):
            yield Label('Install '+self.kind,classes='title')
            with Vertical(classes='setting'):
                yield Label('Git URL or local folder')
                yield Input(id='package-source')
            with Vertical(classes='setting'):
                yield Label('Local name')
                yield Input(placeholder='reporting' if self.kind=='profile' else 'company',id='package-name')
            with Collapsible(title='Repository subfolder and revision', collapsed=True):
                with Vertical(classes='setting'):
                    yield Label('Subfolder in the repository · optional')
                    yield Input(placeholder='profiles/reporting',id='package-subdir')
                with Vertical(classes='setting'):
                    yield Label('Tag, branch or commit · optional')
                    yield Input(id='package-ref')
            yield Static('Install only profiles and providers you trust; they contain executable code.',classes='setting-help')
            yield Static('',id='package-error',markup=False)
        with Horizontal(classes='wizard-actions'):
            yield Button('Cancel',id='package-cancel')
            yield Button('Install',id='package-add',variant='primary')
        yield Footer()

    @on(Button.Pressed)
    def pressed(self,event):
        event.stop()
        if event.button.id=='package-cancel':self.action_back();return
        name=self.query_one('#package-name',Input).value.strip()
        source=self.query_one('#package-source',Input).value.strip()
        ref=self.query_one('#package-ref',Input).value.strip()
        subdir=self.query_one('#package-subdir',Input).value.strip()
        try:
            if not registry.NAME.fullmatch(name) or name in ('base','local'):
                raise ValueError('Use a local name of 1–40 lowercase letters, digits or hyphens, starting with a letter. The names base and local are reserved.')
            if name in registry.choices(self.kind):
                raise ValueError('That name is already installed. Choose another name or update the existing '+self.kind+'.')
            source=registry.source_url(source)
            if Path(subdir).is_absolute() or '..' in Path(subdir).parts:
                raise ValueError('The subfolder must be inside the repository.')
            if ref.startswith('-') or any(c.isspace() for c in ref):
                raise ValueError('Enter a Git tag, branch or commit without spaces.')
        except ValueError as error:
            message=self.query_one('#package-error',Static)
            message.update(str(error));message.scroll_visible();return
        args=[self.kind,'add',name,source]
        if ref:args+=['--ref',ref]
        if subdir:args+=['--subdir',subdir]
        service=self.app.service
        self.app.pop_screen()
        self.app.push_screen(Operation('Install '+self.kind+' · '+name,lambda log:service.run(args,log),
                                       back_label='Back to profiles and providers'))

    def action_back(self):self.app.pop_screen()


class Operation(Screen):
    BINDINGS = [Binding('escape', 'back', 'Back')]

    def __init__(self, title, task, *, back_label='Back to sandboxes'):
        super().__init__()
        self.title, self.operation_task, self.finished = title, task, False
        self.back_label = back_label
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
        button.disabled, button.label = False, self.back_label
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
    BINDINGS = [('escape', 'cancel', 'Cancel')]

    def action_cancel(self):
        self.dismiss(None)

    def __init__(self, start):
        super().__init__()
        candidate = Path(start).expanduser()
        self.folder = candidate if candidate.is_dir() else Path.home()

    def compose(self):
        with Vertical(id='folder-box'):
            yield Label('Choose workspace folder', classes='title')
            yield Input(str(self.folder), id='folder-path')
            yield DataTable(id='folders', cursor_type='row')
            with Horizontal(classes='buttons'):
                yield Button('Up', id='folder-up')
                yield Button('Open folder', id='folder-open')
                yield Static('', classes='action-spacer')
                yield Button('Cancel', id='folder-cancel')
                yield Button('Use this folder', id='folder-use', variant='primary')

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


class CreateFromSandbox(ModalScreen):
    BINDINGS = [('escape', 'cancel', 'Cancel')]
    DEFAULT_CSS = """
    CreateFromSandbox { align: center middle; background: #000000 70%; }
    #copy-sandbox-dialog { width: 72; max-width: 95%; height: 95%; max-height: 28; padding: 1 2; background: #34383d; border: solid #f2b544; }
    #copy-sandbox-dialog Static { height: auto; margin-bottom: 1; }
    #copy-sandbox-fields { height: 1fr; }
    """

    def __init__(self, records, selected=None):
        super().__init__()
        self.records = {r['name']: r for r in records}
        self.selected = selected if selected in self.records else next(iter(self.records))

    def compose(self):
        with Vertical(id='copy-sandbox-dialog'):
            yield Label('Create from existing sandbox', classes='title')
            with VerticalScroll(id='copy-sandbox-fields'):
                yield Label('Copy settings from')
                yield Select([(name, name) for name in self.records], value=self.selected,
                             allow_blank=False, id='copy-source')
                yield Static('Copy its configuration, then choose a new name and workspace. Review the settings before creating.')
                yield Checkbox('Include search API keys', value=False, id='copy-keys')
                yield Static('', id='copy-keys-help', markup=False)
                yield Static('Sign in to models and advisors again; SSH keys, browser sessions and chat history are not copied.')
            yield Static('', id='copy-error', classes='error', markup=False)
            with Horizontal(classes='buttons dialog-actions'):
                yield Button('Cancel', id='copy-cancel')
                yield Button('Continue', id='copy-continue', variant='primary')

    def on_mount(self):
        self.source_changed()

    @on(Select.Changed, '#copy-source')
    def source_changed(self):
        record = self.records[self.query_one('#copy-source', Select).value]
        checkbox = self.query_one('#copy-keys', Checkbox)
        checkbox.value = False
        checkbox.disabled = record['dev'] != 'running'
        help_text = self.query_one('#copy-keys-help', Static)
        help_text.display = checkbox.disabled
        help_text.update('Start the source sandbox to copy search API keys.' if checkbox.disabled else '')

    def action_cancel(self):
        self.dismiss(None)

    @on(Button.Pressed)
    async def pressed(self, event):
        event.stop()
        if event.button.id == 'copy-cancel':
            self.action_cancel()
            return
        button = self.query_one('#copy-continue', Button)
        button.disabled = True
        try:
            record = self.records[self.query_one('#copy-source', Select).value]
            draft = copy_draft(record, self.app.state_root)
            keys = {}
            if self.query_one('#copy-keys', Checkbox).value:
                stored = await asyncio.to_thread(self.app.service.search_keys, record['name'])
                keys = web_access.matching_keys(stored, options(record['config'].get('options'))['web_access'])
            for name, row in draft['options']['web_access']['providers'].items():
                row['has_key'] = bool(keys.get(name))
            self.dismiss((draft, keys))
        except (OSError, ValueError, KeyError) as error:
            self.query_one('#copy-error', Static).update(safe_text(error))
            button.disabled = False


class NewSandbox(Screen):
    def __init__(self, draft=None, search_keys=None):
        super().__init__()
        self.copied_draft = draft
        self.search_keys = search_keys

    BINDINGS = [Binding('escape', 'back', 'Back')]

    def compose(self):
        settings = self.copied_draft or self.app.defaults
        profiles = profile_titles()
        if self.copied_draft:
            profiles[settings['profile']] = profiles.get(settings['reused_profile'].get('registry_name'), settings['reused_profile']['name']) + ' (from ' + settings['reuse_from'] + ')'
        yield Header()
        with VerticalScroll(classes='form'):
            yield Label('New sandbox · 1 of 2' + (' · from ' + settings['reuse_from'] if self.copied_draft else ''), classes='title', id='new-title')
            yield Label('Profile')
            yield Select([(v, k) for k, v in profiles.items()] + [('Custom profile…', 'custom')],
                         value=settings['profile'] if settings['profile'] in profiles else 'custom',
                         allow_blank=False, id='profile')
            with Vertical(id='custom-profile-fields'):
                yield Label('Custom profile folder')
                yield Input(id='custom-profile', placeholder='Folder containing profile.json, Dockerfile and profile.md')
            yield Label('Workspace')
            with Horizontal(classes='path-row'):
                yield Input(settings['workspace_parent'], id='workspace')
                yield Button('Browse', id='browse')
            yield Checkbox('Create this workspace folder if it does not exist', id='mkdir')
            yield Label('Sandbox name')
            yield Input(id='name')
            yield Static('', id='new-error', classes='error', markup=False)
        with Horizontal(classes='wizard-actions'):
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
                metadata = (self.copied_draft['reused_profile'] if self.copied_draft and profile == self.copied_draft['reused_profile']['path']
                            else sandbox.load_profile(profile))
                name = self.query_one('#name', Input).value.strip()
                if not re.fullmatch('[a-z0-9][a-z0-9-]{0,39}', name):
                    raise ValueError('Name: use 1–40 lowercase letters, digits or hyphens.')
                if (self.app.state_root / name).exists():
                    raise ValueError('That name already exists. Choose another name.')
                workspace_text = self.query_one('#workspace', Input).value.strip()
                if not workspace_text:
                    raise ValueError('Choose a workspace folder.')
                workspace = Path(workspace_text).expanduser().resolve()
                if workspace in (Path('/'), Path.home()):
                    raise ValueError('Choose a project folder, not your home folder or filesystem root.')
                if not workspace.exists():
                    if not self.query_one('#mkdir', Checkbox).value:
                        raise ValueError('Choose an existing workspace or enable folder creation.')
                elif not workspace.is_dir():
                    raise ValueError('Workspace is not a directory.')
                draft = copy.deepcopy(self.copied_draft) if self.copied_draft else preset(metadata['name'], self.app.defaults)
                draft.update(profile=profile, name=name, workspace=str(workspace),
                             mkdir=self.query_one('#mkdir', Checkbox).value)
                self.app.push_screen(SettingsForm(draft, search_keys=self.search_keys))
            except (OSError, ValueError) as error:
                self.query_one('#new-error', Static).update(str(error))

    def choose_folder(self, value):
        if value:
            self.query_one('#workspace', Input).value = value

    def action_back(self):
        self.app.pop_screen()


class SettingsForm(Screen):
    BINDINGS = [Binding('escape', 'back', 'Back')]

    def __init__(self, draft, editing=False, defaults=False, search_keys=None, section=None):
        super().__init__()
        self.draft, self.editing, self.defaults_mode = draft, editing, defaults
        self.initial_section = section
        self.search_keys = search_keys
        self.profile_name = (draft['reused_profile']['name'] if draft.get('reused_profile') and draft['profile'] == draft['reused_profile']['path']
                             else sandbox.load_profile(draft['profile'])['name'])

    def compose(self):
        value, selected = self.draft, options(self.draft.get('options'))
        yield Header()
        with VerticalScroll(classes='form'):
            yield Label('Defaults for new sandboxes' if self.defaults_mode else
                        ('Sandbox settings' if self.editing else 'Review sandbox · 2 of 2'), classes='title')
            yield Static(('Profile: ' + profile_titles().get(self.profile_name, self.profile_name)) +
                         ('' if self.defaults_mode else '\nWorkspace: ' + value['workspace']), markup=False)
            yield Checkbox('Connect to models on this host (rootless Podman)',
                           value=bool(value.get('local_model_ports')), id='local-models')
            with Vertical(classes='setting'):
                yield Label('Host model ports · comma-separated ports or ranges')
                yield Input(value.get('local_model_ports') or '8000', id='model-ports')
                yield Static('Inside the sandbox, local-model.internal reaches these ports on your computer.', classes='setting-help')
            configured=value.get('model_providers',{'local':{}})
            if isinstance(configured,list):configured={r['name']:r.get('settings',{}) for r in configured}
            saved_rows={r['name']:r for r in value.get('model_providers',[]) if isinstance(r,dict)}
            available=registry.choices('provider')
            available.update({name:row['manifest'].get('description',name) for name,row in saved_rows.items() if name not in available})
            self.provider_forms={}
            with Collapsible(title='Additional providers',collapsed=True):
                for name,label in available.items():
                    if name=='local':continue
                    info=saved_rows[name]['manifest'] if name in saved_rows else registry.manifest('provider',registry.resolve('provider',name))
                    self.provider_forms[name]=info
                    yield Checkbox(label,value=name in configured,id='source-'+name)
                    for key,spec in info.get('settings',{}).items():
                        if spec['type']=='secret':continue
                        yield Label(spec.get('label',key))
                        yield Input(configured.get(name,{}).get(key,spec.get('default','')),id='source-'+name+'-'+key)
                    if info.get('network'):yield Static('Required network access: '+', '.join(info['network']))
                yield Static('Install additional providers from the home screen’s Packages button. Enter credentials after creation in Settings → Models.')
            if not self.editing and not self.defaults_mode:
                with Collapsible(title='Folders · starting folder and host mounts', collapsed=not bool(value.get('extra_folders')), id='folders-section'):
                    yield FolderFields(value, self.app.state_root)
            if not self.editing and not self.defaults_mode:
                with Collapsible(title='Advisors · optional Codex / Antigravity / Claude', collapsed=True, id='new-advisors-section'):
                    providers = value.get('advisors', {}).get('providers', [])
                    yield Checkbox('Add Codex advisor', value='codex' in providers, id='new-advisor-codex')
                    yield Checkbox('Add Antigravity advisor · Gemini', value='agy' in providers, id='new-advisor-agy')
                    yield Checkbox('Add Claude advisor', value='claude' in providers, id='new-advisor-claude')
                    yield Static('Creates a separate advisor container. After creation, open Settings → Advisors to sign in. No host credentials are imported.', id='new-advisor-help')
            if self.defaults_mode:
                yield Label('Default profile')
                yield Select([(v, k) for k, v in profile_titles().items()], value=self.profile_name if self.profile_name in profile_titles() else 'base',
                             allow_blank=False, id='default-profile')
                yield Label('Workspace parent folder')
                yield Input(value.get('workspace_parent', ''), id='workspace-parent')
            with Collapsible(title='Network · ' + ('Restricted' if value['network'] == 'allowlist' else 'Unrestricted'), collapsed=True, id='network-section'):
                yield Label('Outer container network')
                yield Select([('Restricted — only allowed destinations', 'allowlist'),
                              ('Unrestricted — ordinary container network', 'unrestricted')],
                             value=value['network'], allow_blank=False, id='network')
                if self.editing and value['network'] == 'allowlist':
                    yield Static('Allowed destinations: Settings → Network. Changes there preserve the development container.')
                with Vertical(id='network-rules-fields'):
                    yield WebsiteGroups(selected['website_groups'])
                    yield Label('Allowed destinations · one hostname:port per line; comments allowed')
                    yield TextArea(value.get('allowlist', ''), id='allowlist')
                    with Collapsible(title='Import or export rules', collapsed=True):
                        yield Label('Allowlist file path')
                        yield Input(id='rules-path')
                        with Horizontal(classes='buttons'):
                            yield Button('Import file', id='import-rules')
                            yield Button('Export file', id='export-rules')
                            yield Button('Profile defaults', id='reset-rules')
            yield WebAccessForm(selected['web_access'], self.defaults_mode)
            with Collapsible(title='Agent · ' + selected['approval'].capitalize() + ' approval · Inner sandbox ' + ('on' if selected['inner_sandbox'] else 'off'), collapsed=True, id='agent-section'):
                yield Checkbox('Use inner command sandbox', value=selected['inner_sandbox'], id='inner-sandbox')
                yield Label('Approval mode')
                yield Select([('Automatic — never ask for approval', 'automatic'),
                              ('Automatic with human fallback', 'assisted'),
                              ('Ask me — human approval', 'manual'), ('No approval prompts', 'off')],
                             value=selected['approval'], allow_blank=False, id='approval')
                yield Static('', id='approval-help', markup=False)
                yield Checkbox('Enable optional subagents', value=value['subagents'], id='subagents')
            with Collapsible(title='Skills and features', collapsed=True, id='skills-section'):
                with Vertical(classes='setting'):
                    yield Label('Conversation recall')
                    yield Select([('Lite — search history on demand', 'lite'),
                                  ('Full — automatic history hints', 'full'), ('Off', 'off')],
                                 value=selected['compaction_recall'], allow_blank=False, id='compaction-recall')
                    yield Static('Full adds automatic hints and may reduce prefix-cache reuse.', classes='setting-help')
                with Vertical(classes='setting'):
                    yield Checkbox('Browser · Betterwright', value=selected['browser'], id='browser')
                    yield Static('Adds a headless browser with a live viewer for you to see and interact with its pages.', classes='setting-help checkbox-help')
                for skill in PROFILE_SKILLS.get(self.profile_name, []):
                    yield Checkbox(SKILLS[skill][0], value=skill not in selected['disabled_skills'], id='skill-' + skill)
                for skill in value.get('extra_skills', []):
                    with Vertical(classes='setting'):
                        yield Checkbox(skill['name'] + ' — remote skill', value=True, id='extra-' + skill['name'])
                        yield Static(skill['repo'] + ' · ' + skill['commit'][:12], markup=False, classes='setting-help checkbox-help')
                yield Checkbox('Pendant goals', value=selected['goals'], id='goals')
                yield Checkbox('Scheduled prompts in the current chat', value=selected['scheduling'], id='scheduling')
                with Vertical(classes='setting'):
                    yield Label('Additional skill Git repository URL')
                    yield Input(value.get('skill_repo', ''), id='skill-repo')
                with Vertical(classes='setting'):
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
        with Vertical(classes='wizard-actions settings-actions'):
            yield Checkbox('Open VS Code after applying' if self.editing else 'Open VS Code after creation',
                           value=False if self.editing else value.get('open_editor', True), id='open-editor')
            with Horizontal(classes='action-buttons'):
                yield Button('Back', id='back')
                yield Button('Save defaults' if self.defaults_mode else
                             ('Apply and recreate' if self.editing else 'Create and start'), id='apply', variant='primary')
        yield Footer()

    def on_mount(self):
        self.approval_description()
        self.network_changed()
        self.local_models_changed()
        if self.initial_section:
            section = self.query_one('#' + self.initial_section, Collapsible)
            section.collapsed = False
            self.call_after_refresh(section.scroll_visible, top=True, animate=False)
            if self.initial_section == 'web-section':
                self.query_one('#web-enabled', Checkbox).focus()

    @on(Checkbox.Changed, '#local-models')
    def local_models_changed(self):
        self.query_one('#model-ports', Input).disabled = not self.query_one('#local-models', Checkbox).value

    def approval_description(self):
        mode = self.query_one('#approval', Select).value
        inner = self.query_one('#inner-sandbox', Checkbox).value
        if inner:
            text = 'Ordinary sandboxed commands run directly. '
            text += {'automatic': 'Review failures return to the agent; no approval dialogs.', 'assisted': 'Automatic review can ask you when it cannot decide.', 'manual': 'Boundary requests ask you.',
                     'off': 'Requests beyond the inner sandbox are refused.'}[mode]
        else:
            text = {'automatic': 'Shell commands use automatic review; failures return to the agent.', 'assisted': 'Shell commands use automatic review with human fallback.', 'manual': 'Shell commands ask you.',
                    'off': 'Commands run directly inside the devcontainer.'}[mode]
        self.query_one('#approval-help', Static).update(text + ' The outer container network policy still applies.')
        self.query_one('#agent-section', Collapsible).title = ('Agent · ' + str(mode).capitalize()
            + ' approval · Inner sandbox ' + ('on' if inner else 'off'))

    @on(Select.Changed, '#approval')
    @on(Checkbox.Changed, '#inner-sandbox')
    def approval_changed(self):
        self.approval_description()

    @on(Select.Changed, '#network')
    def network_changed(self):
        mode = self.query_one('#network', Select).value
        self.query_one('#network-section', Collapsible).title = 'Network · ' + ('Restricted' if mode == 'allowlist' else 'Unrestricted')
        self.query_one('#network-rules-fields').display = (mode == 'allowlist' and
            (not self.editing or self.draft['network'] != 'allowlist'))

    def collect(self):
        draft = dict(self.draft)
        def inp(id): return self.query_one('#' + id, Input).value.strip()
        def check(id): return self.query_one('#' + id, Checkbox).value
        draft['local_model_ports'] = inp('model-ports') if check('local-models') else None
        draft['model_providers'] = {'local':{}} if check('local-models') else {}
        provider_rules=[]
        for name,info in self.provider_forms.items():
            if check('source-'+name):
                settings={key:inp('source-'+name+'-'+key) for key,spec in info.get('settings',{}).items() if spec['type']!='secret'}
                draft['model_providers'][name]=settings
                provider_rules+=model_providers.required_rules([{'manifest':info,'settings':settings}])
        if draft['local_model_ports']:
            sandbox.local_model_ports(draft['local_model_ports'])
        if not self.editing and not self.defaults_mode:
            draft.update(self.query_one(FolderFields).collect(private_paths=[inp('pi-config')]))
        selected = options(draft.get('options'))
        selected['web_access'], key = self.query_one(WebAccessForm).collect()
        selected['website_groups'] = self.query_one(WebsiteGroups).selected()
        selected.update(approval=self.query_one('#approval', Select).value, inner_sandbox=check('inner-sandbox'),
                        goals=check('goals'), scheduling=check('scheduling'), browser=check('browser'),
                        compaction_recall=self.query_one('#compaction-recall', Select).value)
        selected['disabled_skills'] = [s for s in SKILLS if
            (s in PROFILE_SKILLS.get(self.profile_name, []) and not check('skill-' + s))
            or (s not in PROFILE_SKILLS.get(self.profile_name, []) and s in selected['disabled_skills'])]
        draft.update(network=self.query_one('#network', Select).value, memory=memory_limit(inp('memory')),
                     subagents=check('subagents'), options=options(selected), engine=self.query_one('#engine', Select).value,
                     env_file=inp('env-file') or None, pi_config=inp('pi-config') or None,
                     open_editor=check('open-editor'),
                     skill_repo=inp('skill-repo'), skill_path=inp('skill-path'))
        if not self.editing and not self.defaults_mode:
            from . import sandbox_advisors
            draft['advisors'] = sandbox_advisors.validate({**draft.get('advisors', {}), 'providers': [
                provider for provider in ('codex', 'agy', 'claude') if check('new-advisor-' + provider)]})
        draft['allowlist'] = self.query_one('#allowlist', TextArea).text if draft['network'] == 'allowlist' else ''
        # Local model ports are controlled by their labelled field; other rules stay intact.
        rules = [r for r in sandbox.parse_rules(draft['allowlist']) if r[0] != 'local-model.internal']
        if draft['local_model_ports']:
            rules += [('local-model.internal', p) for p in sandbox.local_model_ports(draft['local_model_ports'])]
            actual = sandbox.choose_engine(draft['engine'], quiet=True)
            sandbox.configure_local_gateway({'engine':actual, 'network':draft['network']}, draft['local_model_ports'], rules)
        if draft['network'] == 'allowlist':
            rules += [r for r in sandbox.parse_rules('\n'.join(provider_rules)) if r not in rules]
        if draft['network'] == 'allowlist' and not rules and not selected['website_groups'] and not selected['web_access']['enabled']:
            raise ValueError('Add an allowed destination or enable host-local models.')
        draft['allowlist'] = '\n'.join(f'{host}:{port}' for host,port in rules)
        sandbox.validate_env(draft['env_file'])
        draft['remove_skills'] = [s['name'] for s in draft.get('extra_skills', []) if not check('extra-' + s['name'])]
        if draft['skill_repo']:
            sandbox_skills.validate_source(draft['skill_repo'], draft['skill_path'])
        if bool(draft['skill_repo']) != bool(draft['skill_path']):
            raise ValueError('Specify both the skill repository and its folder.')
        return draft, key

    @on(Button.Pressed)
    async def pressed(self, event):
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
                    search, keys = await self.query_one(WebAccessForm).defaults_selection()
                    self.app.defaults = save_defaults_with_search(saved, search, keys)
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
            if draft.get('open_editor'):
                try:
                    service.run(['open', draft['name']], log)
                except (OSError, ValueError) as error:
                    log(f'Sandbox {"updated" if editing else "created"}, but VS Code could not open: {error}')
                    log('Use Open in VS Code on the sandbox list to try again.')
        self.app.pop_screen()
        if not editing:
            self.app.pop_screen()
        self.app.push_screen(Operation(('Updating ' if editing else 'Creating ') + draft['name'], task))

    def action_back(self):
        self.app.pop_screen()


def banner(version, compact=False):
    title = 'Pi Sandbox Factory' if compact else pyfiglet.figlet_format('Pi Sandbox Factory', font='big', width=120).rstrip()
    return f'[bold #f2b544]{title}[/]  [dim]v{version}[/]' if compact else f'[bold #f2b544]{title}[/]\n[dim]Pi and Pendant development environments · v{version}[/]'


class Cockpit(App):
    TITLE = 'Pi Sandbox Factory'
    BINDINGS = [Binding('f2', 'new', 'New sandbox', priority=True),
                Binding('n', 'new', 'New', show=False), Binding('r', 'refresh_inventory', 'Refresh'),
                Binding('slash', 'search', 'Search'), Binding('d', 'defaults', 'Defaults'), Binding('q', 'quit', 'Quit')]
    CSS = '''
    Screen { background: #171a1d; }
    Header { background: #f2b544; color: #171a1d; }
    Footer { background: #34383d; }
    .title { color: #f2b544; text-style: bold; margin: 0 0 1 0; }
    Label { margin: 0; height: auto; }
    .form { padding: 1 3; max-width: 112; }
    NewSandbox .form { padding: 0 3; }
    NewSandbox #new-title { margin-bottom: 0; }
    CreateFromSandbox .title, CreateFromSandbox #copy-source { margin-bottom: 0; }
    .form > Static { height: auto; margin-bottom: 1; }
    #package-list { height: auto; }
    .package-row { height: auto; padding: 1 2; margin-bottom: 1; background: #24292f; }
    .package-title { text-style: bold; }
    .package-actions { height: 1; margin-top: 1; }
    .package-actions Button { background: #34383d; padding: 0 2; }
    #package-error { color: $error; height: auto; }
    .setting { height: auto; margin-bottom: 1; }
    .setting > Checkbox, .setting > Input, .setting > Select { margin-bottom: 0; }
    .setting-help { height: auto; color: #b8bdc3; }
    .checkbox-help { padding-left: 4; }
    .section-intro { height: auto; margin-bottom: 1; }
    Input, Select { margin-bottom: 1; }
    TextArea { height: 9; margin-bottom: 1; }
    .group-title { text-style: bold; margin-bottom: 1; }
    Checkbox { height: 1; border: none; padding: 0; margin: 0 0 1 0; }
    Checkbox > .toggle--button { color: #f1f3f5; background: transparent; text-style: bold; }
    Checkbox.-on > .toggle--button { color: #f2b544; background: transparent; }
    Checkbox:focus > .toggle--label { color: #171a1d; background: #f2b544; text-style: bold underline; }
    Checkbox:focus > .toggle--button { color: #171a1d; background: #f2b544; }
    Button.-primary { background: #f2b544; color: #171a1d; }
    Button:focus { text-style: bold underline; }
    Collapsible { margin-bottom: 1; padding: 0; border: none; }
    .buttons { height: 1; min-height: 1; margin: 1 0; }
    .wizard-actions { dock: bottom; height: 3; padding: 1 3; margin-bottom: 1; max-width: 112; }
    .settings-actions { height: 5; padding: 1 3; }
    .action-buttons { height: 1; }
    .wizard-actions Button { min-width: 12; padding: 0 2; }
    .wizard-actions Button.-primary { dock: right; margin-right: 0; }
    .tall-terminal .wizard-actions { height: 5; }
    .tall-terminal .wizard-actions Button { height: 3; padding: 1 2; }
    .tall-terminal .settings-actions { height: 7; }
    .tall-terminal .action-buttons { height: 3; }
    .dialog-actions { align-horizontal: right; }
    .dialog-actions Button { min-width: 12; padding: 0 2; }
    .action-spacer { width: 1fr; height: 1; }
    Collapsible Button { background: #34383d; }
    Collapsible Button:hover { background: #454b52; }
    Button { height: 1; border: none; margin-right: 1; min-width: 8; }
    #custom-profile-fields, #network-rules-fields { height: auto; }
    #home > .buttons { margin: 0; }
    #home > .buttons Label { width: 1fr; }
    #network-error { height: auto; color: #b75b52; }
    .path-row { height: 3; }
    .path-row Input { width: 1fr; margin-bottom: 0; }
    .path-row Button { height: 3; padding: 1 0; margin-top: 0; }
    #mkdir { margin: 1 0 1 2; }
    .error { color: #b75b52; height: auto; }
    #title-banner { height: auto; padding: 0 2; }
    #application-update { display: none; height: auto; margin: 0 2; }
    #application-update-message { width: 1fr; height: auto; }
    #application-update-run { width: 14; margin: 0 0 0 1; }
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
    #confirm-box { width: 75; max-width: 95%; height: auto; max-height: 90%; padding: 1 2; background: #34383d; border: solid #f2b544; }
    #confirm-box Static { height: auto; }
    #confirm-box > Label { margin-bottom: 1; color: #f2b544; text-style: bold; }
    #confirm-box > OptionList { height: auto; max-height: 14; margin-bottom: 1; }
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
        self.version = updates.installed_version()
        self.available_version = None

    def compose(self):
        yield Header()
        yield Static(banner(self.version, compact=True), id='title-banner')
        with Horizontal(id='application-update'):
            yield Static('', id='application-update-message', markup=False)
            yield Button('Upgrade now', id='application-update-run', variant='primary')
        with Vertical(id='home'):
            with Horizontal(classes='buttons'):
                yield Label('Sandboxes', classes='title')
                yield Button('New sandbox', id='new')
                yield Button('Create from existing…', id='create-from', disabled=True)
                yield Button('Packages', id='packages')
            yield Label('Search sandboxes')
            yield Input(id='search')
            yield DataTable(id='sandboxes', cursor_type='row', zebra_stripes=True)
            yield Static('Choose a sandbox, or create your first one.', id='details', markup=False)
            yield Static('', id='home-error', markup=False)
            with Horizontal(classes='buttons'):
                yield Button('Open in VS Code', id='open', variant='primary')
                yield Button('Open Pi CLI', id='pi', tooltip='Use Pi in this terminal; return here when Pi exits.')
                yield Button('Settings', id='settings')
                yield Button('Actions…', id='more')
        yield Footer()

    def on_mount(self):
        self.query_one(DataTable).add_columns('Name', 'Status', 'Model sources', 'Network')
        self.refresh_inventory()
        self.check_update()
        self.resize_banner()

    def on_resize(self):
        if self.is_mounted:
            self.resize_banner()

    def resize_banner(self):
        self.set_class(self.size.height >= 32, 'tall-terminal')
        self.query_one('#title-banner', Static).update(banner(self.version, self.size.width < 100 or self.size.height < 32))

    @work(thread=True, exclusive=True, group='application-update', exit_on_error=False)
    def check_update(self):
        latest = updates.available_update(self.version)
        if latest:
            self.call_from_thread(self.show_update, latest)

    def show_update(self, latest):
        self.available_version = latest
        self.query_one('#application-update-message', Static).update(
            f'Version {latest} available. pipx upgrade pi-sandbox-factory')
        button = self.query_one('#application-update-run', Button)
        button.disabled = not (updates.pipx_install() and shutil.which('pipx'))
        button.tooltip = 'Available for pipx installations.' if button.disabled else None
        self.query_one('#application-update').display = True

    def confirm_update(self):
        self.push_screen(Confirm(
            f'Upgrade Pi Sandbox Factory to {self.available_version}?\n'
            'Runs pipx upgrade pi-sandbox-factory, then restarts this manager.\n'
            'Running sandboxes keep their installed software.', 'Upgrade'), self.upgrade)

    def upgrade(self, confirmed):
        if not confirmed:
            return
        try:
            with self.suspend():
                subprocess.run(updates.UPGRADE_COMMAND, check=True)
        except (OSError, subprocess.SubprocessError) as error:
            self.query_one('#application-update-message', Static).update(
                f'Upgrade failed: {error}. Retry or run pipx upgrade pi-sandbox-factory.')
        else:
            self.exit(result=updates.RELAUNCH)

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
        self.query_one('#create-from', Button).disabled = not records
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
            providers = config.get('model_providers', [])
            source_names = list(providers) if isinstance(providers, dict) else [row['name'] for row in providers]
            sources = (['Local ' + config['local_model_ports']] if config.get('local_model_ports') else [])
            sources += [name for name in source_names if name != 'local']
            table.add_row(*[safe_text(x) for x in (record['name'], record['dev'].capitalize(),
                          ', '.join(sources) or 'Not configured',
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
        text = ('No matching sandboxes. Clear the search or use New sandbox (F2).'
                if self.records else 'No sandboxes yet. Use New sandbox (F2) to create one.')
        if record:
            text = 'Workspace: ' + str(record.get('workspace') or 'Unavailable')
            text += '\nEngine: ' + str(record.get('engine') or 'Unknown')
            text += ' · Gateway: ' + str(record.get('proxy', 'Unknown'))
            text += ' · Profile: ' + str(record['profile'])
        self.query_one('#details', Static).update(safe_text(text))
        for action in ('open', 'pi', 'settings', 'more'):
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
        if action == 'application-update-run':
            self.confirm_update()
            return
        try:
            self.perform_action(action)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            self.notify(safe_text(error), severity='error')

    def copied_sandbox(self, result):
        if result is not None:
            draft, keys = result
            self.push_screen(NewSandbox(draft, keys))

    def perform_action(self, action):
        if action == 'create-from':
            if self.records:
                self.push_screen(CreateFromSandbox(self.records, self.selected_name()), self.copied_sandbox)
            return
        if action == 'packages':
            self.push_screen(PackagesScreen())
            return
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
        elif action == 'folders':
            self.push_screen(FoldersScreen(record))
        elif action == 'ssh-settings':
            self.push_screen(SSHScreen(record))
        elif action == 'advisors':
            self.push_screen(AdvisorsScreen(record))
        elif action == 'models':
            self.push_screen(ModelsScreen(record))
        elif action == 'network-settings':
            if config.get('network', 'allowlist') != 'allowlist':
                self.notify('Choose Restricted in Settings → Configuration → Network first.')
                return
            self.push_screen(NetworkForm(name, (self.state_root / name / 'allowlist.txt').read_text(), config))
        elif action in ('configuration', 'web-access'):
            if not record.get('engine'):
                self.notify('Repair the saved configuration before editing it.', severity='error')
                return
            value = {**DEFAULT_SETTINGS, **config, 'profile': config.get('profile', {}).get('registry_name', config.get('profile', {}).get('name', 'base')),
                     'options': options(config.get('options')), 'local_model_ports': config.get('local_model_ports')}
            # Custom profile names resolve to their recorded external snapshot.
            if value['profile'] not in profile_titles():
                value['profile'] = config['profile']['path']
            value['allowlist'] = (self.state_root / name / 'allowlist.txt').read_text()
            self.push_screen(SettingsForm(value, editing=True, section='web-section' if action == 'web-access' else None))
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
                    config.get('profile', {}).get('registry_name', config.get('profile', {}).get('name', 'base')) if config.get('profile', {}).get('registry_name',config.get('profile', {}).get('name')) in profile_titles()
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
            if command == 'pi':
                subprocess.run(self.service.command('pi', name), check=False)
            else:
                result = subprocess.run(self.service.command('up', name), check=False)
                if result.returncode == 0:
                    subprocess.run(self.service.command(command, name), check=False)
        self.refresh_inventory()


def launch(state_root):
    if Cockpit(state_root).run() == updates.RELAUNCH:
        os.execv(sys.executable, [sys.executable, '-m', 'pi_sandbox_factory',
                                 '--state-dir', str(state_root), 'tui'])
