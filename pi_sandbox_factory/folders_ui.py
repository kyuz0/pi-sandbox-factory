"""Folder controls shared by creation and sandbox settings."""
import copy
from pathlib import Path

from textual import on
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from . import folders
from .tui_widgets import Checkbox, Feedback


class FolderEditor(ModalScreen):
    DEFAULT_CSS = '''
    FolderEditor { align: center middle; background: #000000 70%; }
    FolderEditor > Vertical { width: 70; max-width: 95%; height: 28; max-height: 95%; padding: 1 2; background: $panel; border: solid $primary; }
    FolderEditor #folder-fields { height: 1fr; min-height: 5; }
    FolderEditor Static { height: auto; }
    FolderEditor Input { margin-bottom: 1; }
    FolderEditor Horizontal { height: auto; margin-top: 1; }
    FolderEditor Button { margin-right: 1; }
    '''
    BINDINGS = [('escape', 'cancel', 'Cancel')]

    def __init__(self, row, rows, workspace, state_root, private_paths=()):
        super().__init__()
        self.row, self.rows, self.workspace, self.state_root = row, rows, workspace, state_root
        self.private_paths = private_paths

    def compose(self):
        with Vertical():
            yield Label('Edit folder' if self.row else 'Add host folder', classes='title')
            with VerticalScroll(id='folder-fields'):
                yield Label('Folder on your computer')
                yield Input((self.row or {}).get('source', ''), placeholder='~/Documents/reference', id='folder-source')
                with Vertical(classes='setting'):
                    yield Label('Name under /mnt · leave empty to use the folder name')
                    yield Input((self.row or {}).get('name', ''), id='folder-name')
                    yield Static('', id='folder-preview', markup=False, classes='setting-help')
                yield Checkbox('Read-only', value=(self.row or {}).get('read_only', True), id='folder-read-only')
            yield Feedback('', id='folder-error', classes='error', markup=False)
            with Horizontal(classes='dialog-actions'):
                yield Button('Cancel', id='folder-cancel')
                yield Button('Save folder', id='folder-save', variant='primary')

    def on_mount(self):
        self.preview()

    @on(Input.Changed)
    def preview(self):
        source = self.query_one('#folder-source', Input).value.strip()
        name = self.query_one('#folder-name', Input).value.strip() or folders.suggested_name(source, self.rows)
        preview = self.query_one('#folder-preview', Static)
        preview.display = bool(source)
        preview.update('Available in the sandbox at /mnt/' + name)

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        if event.button.id == 'folder-cancel':
            self.dismiss(None)
        elif event.button.id == 'folder-save':
            row = dict(source=self.query_one('#folder-source', Input).value.strip(),
                       name=self.query_one('#folder-name', Input).value.strip(),
                       read_only=self.query_one('#folder-read-only', Checkbox).value)
            try:
                result = folders.validate(self.rows + [row], self.workspace, self.state_root, private_paths=self.private_paths)
                self.dismiss(result[-1])
            except (ValueError, OSError) as error:
                feedback = self.query_one('#folder-error', Static)
                feedback.update(str(error))
                self.query_one('#folder-fields').scroll_home(animate=False)

    def action_cancel(self):
        self.dismiss(None)


class FolderFields(Vertical):
    DEFAULT_CSS = '''
    FolderFields { height: auto; }
    FolderFields #folder-rows { height: auto; }
    FolderFields .mount-row { height: auto; margin: 0 0 1 0; padding: 1 2; background: #24292f; }
    FolderFields .mount-row Static { height: auto; }
    FolderFields .mount-buttons { height: auto; margin-top: 1; }
    FolderFields Button { margin-right: 1; }
    FolderFields .mount-help { margin: 0; }
    FolderFields #working-directory { margin-bottom: 1; }
    '''

    def __init__(self, config, state_root):
        super().__init__()
        self.config, self.state_root = config, state_root
        self.rows = copy.deepcopy(config.get('extra_folders', []))

    def compose(self):
        yield Static('Main workspace: ' + str(self.config['workspace']) + ' → /workspace', markup=False, classes='section-intro')
        yield Label('Start Pi and VS Code in · relative to /workspace')
        yield Input(self.config.get('working_directory', '.'), placeholder='.', id='working-directory')
        yield Label('Additional host folders')
        yield Vertical(id='folder-rows')
        with Vertical(classes='setting'):
            yield Button('Add folder…', id='folder-add')
            yield Static('Separately mounted filesystems inside an added folder are not included.', markup=False, classes='setting-help mount-help')

    async def on_mount(self):
        await self.refresh_rows()

    async def refresh_rows(self):
        target = self.query_one('#folder-rows', Vertical)
        await target.remove_children()
        for index, row in enumerate(self.rows):
            label = '/mnt/' + row['name'] + ' · ' + ('read-only' if row['read_only'] else 'read and write')
            await target.mount(Vertical(Static(label, markup=False), Static(row['source'], markup=False),
                Horizontal(Button('Edit', id=f'folder-edit-{index}'), Button('Remove', id=f'folder-remove-{index}'), classes='mount-buttons'), classes='mount-row'))

    @on(Button.Pressed)
    async def pressed(self, event):
        action = event.button.id or ''
        if not action.startswith('folder-'):
            return
        event.stop()
        if action.startswith('folder-remove-'):
            self.rows.pop(int(action.rsplit('-', 1)[1]))
            await self.refresh_rows()
        elif action == 'folder-add' or action.startswith('folder-edit-'):
            index = None if action == 'folder-add' else int(action.rsplit('-', 1)[1])
            row = None if index is None else self.rows[index]
            others = [r for i, r in enumerate(self.rows) if i != index]
            async def saved(result):
                if result is not None:
                    if index is None:
                        self.rows.append(result)
                    else:
                        self.rows[index] = result
                    await self.refresh_rows()
            self.app.push_screen(FolderEditor(row, others, self.config['workspace'], self.state_root, [self.config.get('pi_config')]), saved)

    def collect(self, private_paths=None):
        value = self.query_one('#working-directory', Input).value.strip() or '.'
        if self.config.get('mkdir') and not Path(self.config['workspace']).exists() and value == '.':
            cwd = '.'
        else:
            cwd = folders.working_directory(self.config['workspace'], value)
        return dict(working_directory=cwd, extra_folders=folders.validate(
            self.rows, self.config['workspace'], self.state_root,
            private_paths=private_paths if private_paths is not None else [self.config.get('pi_config')]))
