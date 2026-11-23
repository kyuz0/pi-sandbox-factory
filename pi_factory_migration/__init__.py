"""Install and forward the original Factory command to AI Sandbox Factory."""
from contextlib import contextmanager
from importlib import metadata
import os
from pathlib import Path
import shutil
import site
import sysconfig
import stat
import subprocess
import sys

from .paths import locations, migrate, plan
from .journal import recover

URL = 'git+https://github.com/kyuz0/ai-sandbox-factory.git'
NOTICE = ('Pi Sandbox Factory is now AI Sandbox Factory. '
          'Use ai-sandbox-factory next time; pi-sandbox-factory still works.')


def application():
    # A pip installation may put both packages in this Python environment.
    try:
        distribution = metadata.distribution('ai-sandbox-factory')
        if distribution.locate_file('ai_sandbox_factory/__main__.py').is_file():
            if Path(distribution.locate_file('')).resolve() == Path(site.getusersitepackages()).resolve():
                scripts = Path(sysconfig.get_path('scripts', scheme=sysconfig.get_preferred_scheme('user')))
                executable = scripts / 'ai-sandbox-factory'
                if not executable.is_file():
                    raise RuntimeError(f'AI Sandbox Factory is installed in your user site, but {executable} is missing. '
                                       'Reinstall ai-sandbox-factory in that environment. No data was moved.')
                return [str(executable)]
            return [sys.executable, '-I', '-m', 'ai_sandbox_factory']
    except metadata.PackageNotFoundError:
        pass
    directory = os.environ.get('PIPX_BIN_DIR')
    pipx = shutil.which('pipx')
    if not directory and pipx and (Path(sys.prefix) / 'pipx_metadata.json').is_file():
        result = subprocess.run([pipx, 'environment', '--value', 'PIPX_BIN_DIR'],
                                capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError(f'Cannot find the pipx applications directory: pipx environment exited '
                               f'with status {result.returncode}. ' + (result.stderr.strip() or result.stdout.strip()))
        directory = result.stdout.strip()
    candidate = Path(directory or Path.home() / '.local/bin') / 'ai-sandbox-factory'
    executable = str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else shutil.which('ai-sandbox-factory')
    return [executable] if executable else None


@contextmanager
def migration_lock():
    import fcntl
    directory = Path.home() / '.local/state'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / '.ai-sandbox-factory-migration.lock'
    flags = os.O_CREAT | os.O_RDWR | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError(f'Migration lock must be private and owned by you: {path}')
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def install():
    if (Path(sys.prefix) / 'pipx_metadata.json').is_file():
        executable = shutil.which('pipx')
        if not executable:
            raise ValueError('pipx was not found. Install pipx, then run pi-sandbox-factory again.')
        command = [executable, 'install', URL]
    else:
        command = [sys.executable, '-m', 'pip', 'install', URL]
    # Leave the installer's complete diagnostics visible, including its exit status.
    result = subprocess.run(command, check=False, stdout=sys.stderr)
    if result.returncode:
        raise RuntimeError(f'AI Sandbox Factory installation exited with status {result.returncode}. '
                           'The installer output is above. Your Factory data has not been moved; retry pi-sandbox-factory.')


def run(arguments=None):
    args = list(sys.argv[1:] if arguments is None else arguments)
    consent = args[:1] == ['--yes']
    if consent:
        args.pop(0)
    if os.name != 'posix':
        raise ValueError('Run Factory inside WSL2 on Windows. Linux and macOS use this launcher directly.')
    interactive = sys.stdin.isatty() and sys.stderr.isatty()
    with migration_lock():
        pairs = locations()
        recover(pairs)
        moves = plan(pairs)
        target = application()
        if not target or moves:
            print('Pi Sandbox Factory has moved to AI Sandbox Factory, which supports Pi, Codex, Claude Code and Antigravity.', file=sys.stderr)
            if not target:
                print('This will install AI Sandbox Factory.', file=sys.stderr)
            for old, new in moves:
                print(f'Move {old} → {new}', file=sys.stderr)
            if moves:
                print('Project files and saved chats are kept. Compatibility links preserve existing sandbox paths.', file=sys.stderr)
            if not consent:
                if not interactive:
                    raise ValueError('Run pi-sandbox-factory in a terminal to confirm migration, or pass --yes for an unattended migration.')
                print('Press Enter to continue, or Ctrl+C to cancel: ', end='', file=sys.stderr, flush=True)
                input()
            if not target:
                install()
                target = application()
                if not target:
                    raise RuntimeError('The installer finished, but ai-sandbox-factory was not found in this environment or on PATH. '
                                       'Your Factory data has not been moved. If pipx reported an existing installation, run '
                                       'pipx reinstall ai-sandbox-factory to restore its command, then retry.')
            migrate(pairs)
    environment = dict(os.environ)
    if sys.stdout.isatty() and sys.stderr.isatty():
        environment['AI_FACTORY_STARTUP_NOTICE'] = NOTICE
    os.execvpe(target[0], [*target, *args], environment)


def main():
    try:
        run()
    except (KeyboardInterrupt, EOFError):
        print('\nMigration cancelled. Existing Factory data was kept.', file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        # Keep the exception class, cause and traceback: migration must be diagnosable.
        import traceback
        traceback.print_exc()
        print(f'Migration did not complete: {type(error).__name__}: {error}', file=sys.stderr)
        raise SystemExit(1)
