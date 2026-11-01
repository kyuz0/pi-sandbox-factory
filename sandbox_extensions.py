"""Fetch immutable extension sources on the host, outside image build contexts."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager


def read_lock(common_path):
    path = Path(common_path) / 'extensions.lock.json'
    if not path.exists():
        return {}  # Saved older image inputs remain rebuildable.
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('extensions'), dict):
        raise ValueError('Invalid extension lock file')
    for name, source in value['extensions'].items():
        if not re.fullmatch(r'[a-z][a-z0-9-]+', name) or not isinstance(source, dict):
            raise ValueError('Invalid extension name')
        if set(source) != {'repository', 'commit'}:
            raise ValueError('Extension source needs repository and commit')
        if not re.fullmatch(r'[0-9a-f]{40}', source['commit']):
            raise ValueError('Extension sources require full commit IDs')
        if not re.fullmatch(r'(?:git@github\.com:|https://github\.com/)[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git', source['repository']):
            raise ValueError('Extension repository must be a GitHub Git URL')
    return value['extensions']


def cache_root():
    return Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'local-ai-sandboxes/extensions'


def archive(source, cache=None):
    """Git uses host authentication; only git-archive output reaches the builder."""
    root = Path(cache) if cache is not None else cache_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = hashlib.sha256(source['repository'].encode()).hexdigest()[:16]
    repo = root / key
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    def git(*args, capture=False):
        return subprocess.run(['git', '-C', str(repo), *args], env=env, check=True,
                              stdout=subprocess.PIPE if capture else None)
    if not repo.exists():
        repo.mkdir(mode=0o700)
        git('init', '--bare', '--quiet')
        git('remote', 'add', 'origin', source['repository'])
    if repo.is_symlink() or not repo.is_dir():
        raise ValueError('Extension cache must be a directory')
    remote = git('remote', 'get-url', 'origin', capture=True).stdout.decode().strip()
    if remote != source['repository']:
        raise ValueError('Extension cache origin changed')
    commit = source['commit']
    present = subprocess.run(['git', '-C', str(repo), 'cat-file', '-e', commit + '^{commit}'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not present:
        git('fetch', '--quiet', '--no-tags', '--depth=1', 'origin', commit)
    actual = git('rev-parse', commit + '^{commit}', capture=True).stdout.decode().strip()
    if actual != commit:
        raise ValueError('Extension revision did not match its lock')
    return git('archive', '--format=tar', commit, capture=True).stdout


def unpack(blob, destination):
    destination = Path(destination)
    destination.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:') as bundle:
        for entry in bundle.getmembers():
            path = PurePosixPath(entry.name)
            if path.is_absolute() or '..' in path.parts or '.git' in path.parts or not path.parts:
                raise ValueError('Unsafe path in extension archive')
            if entry.isdir():
                continue
            if not entry.isfile():
                raise ValueError('Extension archive must contain regular files')
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.extractfile(entry).read())
            target.chmod(0o755 if entry.mode & 0o111 else 0o644)


@contextmanager
def build_contexts(common_path, *, names=None, cache=None, fetch=archive):
    sources = read_lock(common_path)
    selected = list(sources) if names is None else list(names)
    with tempfile.TemporaryDirectory(prefix='local-ai-extensions-') as temp:
        args = []
        for name in selected:
            if name not in sources:
                raise ValueError('Missing extension source: ' + name)
            source = sources[name]
            print(f'Loading {name} at {source["commit"][:12]}', flush=True)
            target = Path(temp) / name
            unpack(fetch(source, cache), target)
            (target / 'source-commit').write_text(source['commit'] + '\n')
            args += ['--build-context', f'{name}={target}']
        yield args
