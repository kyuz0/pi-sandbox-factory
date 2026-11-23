"""Recover interrupted moves without guessing whether an existing folder is ours."""
import json
import os
from pathlib import Path
import stat
import tempfile
from . import initialization


def location(pairs):
    return pairs[0][0].parent / '.ai-sandbox-factory-migration.json'


def sync_directory(directory):
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def clear(path):
    path.unlink(missing_ok=True)
    sync_directory(path.parent)


def write(path, moves):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump([[str(old), str(new)] for old, new in moves], stream)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
            sync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)


def recover(pairs):
    path = location(pairs)
    if not os.path.lexists(path):
        return
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError(f'Cannot recover migration: {path} must be a private file owned by you.')
    saved = json.loads(path.read_text())
    allowed = [[str(old), str(new)] for old, new in pairs]
    if not isinstance(saved, list) or any(pair not in allowed for pair in saved):
        raise ValueError(f'Cannot recover migration: {path} contains unexpected source or destination paths.')
    for pair in saved:
        old, new = map(Path, pair)
        if not os.path.lexists(old) and new.is_dir() and not new.is_symlink():
            old.symlink_to(new.name, target_is_directory=True)
            sync_directory(old.parent)
        elif old.is_dir() and not old.is_symlink() and (not os.path.lexists(new) or initialization.disposable(new)):
            continue
        elif old.is_symlink() and old.resolve() == new.resolve() and new.is_dir():
            continue
        else:
            raise ValueError(f'Cannot recover migration between {old} and {new}: unexpected directory state. Neither was overwritten.')
    clear(path)
