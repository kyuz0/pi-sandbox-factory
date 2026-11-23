"""Move Factory's default folders while retaining existing absolute references."""
import hashlib
import os
from pathlib import Path
import stat
from . import journal

OLD = 'pi-sandbox-factory'
NEW = 'ai-sandbox-factory'


def locations(home=None, environment=None):
    home = Path.home() if home is None else Path(home)
    env = os.environ if environment is None else environment
    parents = [home / '.local/state',
               Path(env.get('XDG_CONFIG_HOME') or home / '.config').expanduser(),
               Path(env.get('XDG_DATA_HOME') or home / '.local/share').expanduser(),
               Path(env.get('XDG_CACHE_HOME') or home / '.cache').expanduser()]
    return list(dict.fromkeys((parent / OLD, parent / NEW) for parent in parents))


def plan(pairs):
    moves = []
    for old, new in pairs:
        if old.is_symlink():
            if old.resolve() == new.resolve() and new.is_dir():
                continue
            raise ValueError(f'Cannot migrate {old}: it is a link to {old.readlink()}. Neither location was changed.')
        if not old.exists():
            continue
        if not old.is_dir():
            raise ValueError(f'Cannot migrate {old}: expected a directory. It was not changed.')
        if os.path.lexists(new):
            raise ValueError(f'Cannot migrate {old} to {new}: both locations exist. Neither was changed. '
                             'Keep both folders and resolve the destination before retrying; this launcher never merges or overwrites them.')
        moves.append((old, new))
    return moves


def editor_links(moves):
    """Keep the old editor supervisor's live Unix socket reachable after a move."""
    root = Path('/tmp') / f'psf-{os.getuid()}'
    if not root.exists():
        return []
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError(f'Cannot preserve editor connections: {root} must be a private directory owned by you.')
    links = []
    for old, new in moves:
        for record in old.glob('*/browser-editor-runtime.json'):
            source = record.parent.resolve()
            target = (new / record.parent.name).resolve()
            old_socket = root / (hashlib.sha256(str(source).encode()).hexdigest()[:24] + '.sock')
            new_socket = root / (hashlib.sha256(str(target).encode()).hexdigest()[:24] + '.sock')
            if not old_socket.exists():
                continue
            info = old_socket.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                raise ValueError(f'Cannot preserve editor connection: {old_socket} is not a socket owned by you.')
            if new_socket.is_symlink() and new_socket.readlink() == Path(old_socket.name):
                continue
            if os.path.lexists(new_socket):
                raise ValueError(f'Cannot preserve editor connection: {new_socket} already exists. No data was moved.')
            links.append((new_socket, old_socket))
    return links


def migrate(pairs):
    journal.recover(pairs)
    moves = plan(pairs)
    if not moves:
        return []
    links = editor_links(moves)
    record = journal.location(pairs)
    journal.write(record, moves)
    moved, created_links = [], []
    try:
        for link, target in links:
            link.symlink_to(target.name)
            created_links.append(link)
        for old, new in moves:
            old.rename(new)
            moved.append((old, new))
            old.symlink_to(new.name, target_is_directory=True)
            journal.sync_directory(old.parent)
    except BaseException as error:
        failures = []
        for old, new in reversed(moved):
            try:
                if old.is_symlink() and old.resolve() == new.resolve():
                    old.unlink()
                new.rename(old)
            except OSError as undo:
                failures.append(f'{new} → {old}: {undo}')
        for link in reversed(created_links):
            try:
                link.unlink()
            except OSError as undo:
                failures.append(f'{link}: {undo}')
        if failures:
            raise RuntimeError(f'Migration failed: {error}. Some paths could not be restored: '
                               + '; '.join(failures) + '. No data was deleted.') from error
        journal.clear(record)
        raise
    journal.clear(record)
    return moves
