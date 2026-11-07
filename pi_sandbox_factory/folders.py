"""Workspace selection and explicit host-folder grants."""
import json
import os
from pathlib import Path
import re
from . import host_platform


def overlaps(first, second):
    first, second = map(host_platform.comparison_path, (first, second))
    return first == second or first in second.parents or second in first.parents


def working_directory(workspace, value='.'):
    if not isinstance(value, str) or Path(value).is_absolute() or '..' in Path(value).parts:
        raise ValueError('Starting folder must be a relative folder inside the workspace.')
    try:
        root = Path(workspace).resolve(strict=True)
        target = (root / value).resolve(strict=True)
    except OSError:
        raise ValueError('Starting folder does not exist. Choose it in Settings → Folders.') from None
    if not target.is_dir() or not target.is_relative_to(root):
        raise ValueError('Starting folder must be a directory inside the workspace.')
    return target.relative_to(root).as_posix()


def container_cwd(config):
    value = working_directory(config['workspace'], config.get('working_directory', '.'))
    return '/workspace' if value == '.' else '/workspace/' + value


def suggested_name(source, rows):
    base = re.sub(r'[^a-z0-9._-]+', '-', Path(source).name.lower()).strip('.-')[:28] or 'folder'
    used = {r['name'] for r in rows}
    name, index = base, 2
    while name in used:
        name = f'{base}-{index}'
        index += 1
    return name


def validate(rows, workspace, state_root, *, saved=False, private_paths=()):
    if not isinstance(rows, list):
        raise ValueError('Extra folders must be a list.')
    result = []
    home = host_platform.comparison_path(Path.home())
    protected = [Path(state_root).resolve(), *(Path(p).resolve() for p in private_paths if p)]
    system = [host_platform.comparison_path(p) for p in ('/etc', '/usr', '/boot', '/proc', '/sys', '/dev', '/run', '/var/lib', '/var/log', '/var/lock')]
    for row in rows:
        if not isinstance(row, dict) or set(row) - {'source', 'name', 'read_only'}:
            raise ValueError('Each extra folder needs a source, name and read_only setting.')
        raw = row.get('source', '')
        if not isinstance(raw, str) or not raw or (',' in raw or '"' in raw or any(ord(c) < 32 or ord(c) == 127 for c in raw)):
            raise ValueError('Choose a host folder whose path contains no commas, double quotes or control characters.')
        path = host_platform.local_path(raw)
        try:
            source = path.resolve(strict=True)
        except OSError:
            raise ValueError(f'Host folder is missing: {path}. Edit it in Settings → Folders.') from None
        if ',' in str(source) or '"' in str(source) or any(ord(c) < 32 or ord(c) == 127 for c in str(source)):
            raise ValueError('Host folder paths cannot contain commas, double quotes or control characters.')
        host_platform.validate_data_path(source)
        if not source.is_dir():
            raise ValueError(f'Host folder is not a directory: {path}')
        if (source.is_relative_to(Path('/tmp').resolve()) or source.is_relative_to(Path('/var/tmp').resolve())) and source.stat().st_uid != os.getuid():
            raise ValueError('Temporary host folders must belong to your user account.')
        if saved and source != path:
            raise ValueError(f'Host folder changed location: {path}. Edit it in Settings → Folders.')
        compared = host_platform.comparison_path(source)
        if compared == home or compared in home.parents or source in (Path('/tmp').resolve(), Path('/var').resolve()):
            raise ValueError('Choose a specific data folder, not a filesystem root or your whole home.')
        if any(overlaps(source, p) for p in protected) or any(compared == p or p in compared.parents for p in system):
            raise ValueError('System folders and private sandbox state cannot be mounted as data folders.')
        if compared.is_relative_to(home) and compared.relative_to(home).parts[0].startswith('.'):
            raise ValueError('Hidden home folders contain private application state; choose a data folder.')
        if overlaps(source, Path(workspace).resolve()) or any(overlaps(source, Path(r['source'])) for r in result):
            raise ValueError('Extra folders must not overlap the workspace or another extra folder.')
        name = row.get('name') or suggested_name(source, result)
        if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,31}', name):
            raise ValueError('Folder name must use 1–32 lowercase letters, digits, dots, underscores or hyphens.')
        if name in {r['name'] for r in result}:
            raise ValueError(f'Folder name already used: {name}')
        read_only = row.get('read_only', True)
        if type(read_only) is not bool:
            raise ValueError('read_only must be true or false.')
        result.append(dict(source=str(source), name=name, read_only=read_only))
    return result


def validate_config(config, state_root, *, saved=False):
    return validate(config.get('extra_folders', []), config['workspace'], state_root,
                    saved=saved, private_paths=[config.get('pi_config')])


def mounts(config):
    args = []
    recursion = 'bind-nonrecursive' if config['engine'] == 'podman' else 'bind-recursive=disabled'
    for row in config.get('extra_folders', []):
        args += ['--mount', f'type=bind,src={row["source"]},dst=/mnt/{row["name"]},{recursion}'
                 + (',ro' if row['read_only'] else ',rw')]
    return args


def roots(config):
    return [('/workspace', False)] + [('/mnt/' + r['name'], r['read_only']) for r in config.get('extra_folders', [])]


def permissions(value, config):
    permission = value['permission']
    for surface in ('external_directory_read', 'external_directory_write'):
        rules = permission.setdefault(surface, {})
        for path, read_only in roots(config):
            action = 'deny' if surface.endswith('write') and read_only else 'allow'
            rules[path] = action
            rules[path + '/*'] = action
    return value


def guidance(config):
    rows = ['\n## Mounted folders', '', 'The host has provided these container paths:']
    for path, read_only in roots(config):
        rows.append(f'- {json.dumps(path)}: ' + ('read-only' if read_only else 'read and write'))
    rows += ['', 'Use the session working directory as the starting folder. The full project remains at /workspace.',
             'Read-only mounts cannot be changed through command approval. Ask the user to change the folder settings if writing there is required.']
    return '\n'.join(rows) + '\n'
