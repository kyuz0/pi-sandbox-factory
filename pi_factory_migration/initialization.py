"""Recognize empty directories created by ordinary registry reads, not user data."""
from contextlib import ExitStack
import fcntl
import os
from pathlib import Path
import stat


def disposable(path):
    if not path.is_dir() or path.is_symlink():
        return False
    for item in (path, *path.rglob('*')):
        info = item.lstat()
        if info.st_uid != os.getuid():
            return False
        if stat.S_ISDIR(info.st_mode):
            continue
        if (stat.S_ISREG(info.st_mode) and item.relative_to(path) == Path('packages/registry.lock')
                and info.st_size == 0):
            continue
        return False
    return True


def clear(path):
    """Remove only verified empty initialization, under its normal registry lock."""
    if not disposable(path):
        raise ValueError(f'{path} now contains settings or other data; nothing was overwritten.')
    with ExitStack() as stack:
        lock = path / 'packages/registry.lock'
        if lock.exists():
            stream = stack.enter_context(open(lock, 'r+b'))
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            if stream.seek(0, os.SEEK_END) or lock.stat().st_ino != os.fstat(stream.fileno()).st_ino:
                raise ValueError(f'{lock} changed during migration; it was not removed.')
        if not disposable(path):
            raise ValueError(f'{path} changed during migration; nothing was overwritten.')
        if lock.exists():
            lock.unlink()
        directories = [item for item in path.rglob('*') if item.is_dir()]
        for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
            directory.rmdir()
        path.rmdir()
