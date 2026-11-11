"""Host differences; sandbox processes always run in Linux containers."""
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import subprocess
import sys
from urllib.parse import urlsplit


def is_mac():
    return platform.system() == 'Darwin'


def is_wsl():
    return platform.system() == 'Linux' and 'microsoft' in platform.release().lower()


def python_command(module, *args):
    """Start our Python code without importing modules from the workspace."""
    package_root = str(Path(__file__).resolve().parent.parent)
    bootstrap = (f"import sys; sys.path.insert(0, {package_root!r}); "
                 f"from runpy import run_module; run_module({module!r}, run_name='__main__')")
    return [sys.executable, '-I', '-c', bootstrap, *args]


def windows_drive(path):
    parts = Path(path).parts
    return len(parts) >= 3 and parts[1] == 'mnt' and len(parts[2]) == 1 and parts[2].isalpha()


def comparison_path(path):
    path = Path(path).resolve()
    return Path(str(path).casefold()) if is_mac() or (is_wsl() and windows_drive(path)) else path


def needs_mount_check(config):
    paths = [config['workspace'], config.get('pi_config'),
             *(row['source'] for row in config.get('extra_folders', []))]
    return is_mac() or (is_wsl() and any(windows_drive(p) for p in paths if p))


def automatic_address():
    if platform.system() == 'Darwin' or is_wsl():
        return 'sbx-' + secrets.token_hex(12) + '.localhost'
    return '127.' + '.'.join(str(secrets.randbelow(254) + 1) for _ in range(3))


def listen_address(address):
    return '127.0.0.1' if address.endswith('.localhost') else address


def open_url(url):
    if platform.system() == 'Darwin':
        command = ['open', url]
    elif is_wsl() and shutil.which('wslview'):
        command = ['wslview', url]
    elif is_wsl() and shutil.which('powershell.exe'):
        # Pass as a literal, never as an interpolated PowerShell expression.
        command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                   "Start-Process '" + url.replace("'", "''") + "'"]
    elif (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')) and shutil.which('xdg-open'):
        command = ['xdg-open', url]
    else:
        return
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def local_path(value):
    value = str(value)
    if is_wsl() and len(value) > 2 and value[1:3] in (':\\', ':/'):
        value = subprocess.check_output(['wslpath', '-u', value], text=True).strip()
    return Path(value).expanduser()


def control_path(state):
    # macOS Unix socket names are limited to 104 bytes, including the terminator.
    root = Path('/tmp') / f'psf-{os.getuid()}'
    root.mkdir(mode=0o700, exist_ok=True)
    info = root.lstat()
    if root.is_symlink() or not root.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('Editor control directory must be private: ' + str(root))
    name = hashlib.sha256(str(Path(state).resolve()).encode()).hexdigest()[:24]
    return root / (name + '.sock')


def check_engine(engine, expected=None, *, full=True):
    """Check the selected local Mac VM before touching any saved container."""
    if platform.system() != 'Darwin':
        return None
    if engine != 'podman':
        raise ValueError('On macOS, use rootless Podman Machine.')
    if os.environ.get('CONTAINER_HOST'):
        raise ValueError('Use a local Podman Machine connection, without CONTAINER_HOST.')
    connections = json.loads(subprocess.check_output(['podman', 'system', 'connection', 'list', '--format', 'json'], text=True))
    selected = os.environ.get('CONTAINER_CONNECTION')
    connection = next((c for c in connections if c['Name'] == selected), None) if selected else next((c for c in connections if c.get('Default')), None)
    uri = connection.get('URI', '') if connection else ''
    parsed = urlsplit(uri)
    if parsed.scheme != 'ssh' or parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Start a local Podman Machine and select its rootless connection with podman system connection default NAME.')
    if expected and expected != uri:
        raise ValueError('This sandbox belongs to a different Podman connection. Select its original connection before continuing.')
    if not full:
        return uri
    info = json.loads(subprocess.check_output(['podman', 'info', '--format', 'json'], text=True))
    if not info['host']['security']['rootless']:
        raise ValueError('Use rootless Podman Machine: podman machine set --rootful=false')
    from packaging.version import Version
    version = Version(info['version']['Version'])
    if version < Version('5.6'):
        raise ValueError('Podman Machine 5.6 or newer is required for additional build contexts. Update Podman and its machine.')
    return uri


def bind_mode(mode='ro'):
    # VirtioFS shares do not support relabeling the host's files with SELinux xattrs.
    return mode if is_mac() else mode + ',Z'


def gateway_labels():
    return ['--security-opt=label=disable'] if is_mac() else []


def check_model_gateway(config):
    """Check host-loopback support before starting Linux local-model containers."""
    if (is_mac() or config.get('engine') != 'podman'
            or not config.get('local_model_gateway')):
        return
    advice = ('Local models on Linux require pasta --map-host-loopback support '
              '(passt 2024_08_21.1d6142f or newer, or a distro backport). '
              'Upgrade the passt package, or disable "Connect to models on this host" '
              'when using OpenRouter or another hosted provider.')
    # Prefer Podman's selected helper, which may differ from PATH.
    executable = None
    try:
        result = subprocess.run(['podman', 'info', '--format', '{{json .Host.Pasta}}'],
                                capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            info = json.loads(result.stdout)
            if isinstance(info, dict):
                executable = info.get('executable')
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    executable = executable or shutil.which('pasta')
    if not executable:
        raise ValueError('pasta was not found. ' + advice)
    try:
        result = subprocess.run([executable, '--help'], capture_output=True,
                                text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError('Could not check pasta at ' + executable + '. ' + advice) from error
    # Some releases write help to stderr or exit nonzero for --help.
    if '--map-host-loopback' not in result.stdout + result.stderr:
        raise ValueError('pasta at ' + executable + ' lacks --map-host-loopback. ' + advice)


def model_gateway_args():
    if platform.system() == 'Darwin':
        return ['--env', 'SANDBOX_MODEL_HOST=host.containers.internal']
    return ['--network=pasta:--map-host-loopback,169.254.1.2',
            '--add-host=local-model.internal:169.254.1.2']


def validate_data_path(path):
    """Protect host application state, including macOS aliases and Windows drives."""
    path = comparison_path(path)
    if platform.system() == 'Darwin':
        protected = [comparison_path(p) for p in ('/System', '/Library', '/Applications', '/etc', '/var', '/private/etc', '/private/var')]
        protected.append(comparison_path(Path.home() / 'Library'))
        if any(path == p or p in path.parents or path in p.parents for p in protected):
            raise ValueError('Choose a project or data folder, not macOS system or application state.')
    if is_wsl():
        parts = path.parts
        if windows_drive(path):
            rest = [p.lower() for p in parts[3:]]
            if (not rest or rest[0] in ('windows', 'program files', 'program files (x86)', 'programdata')
                    or (rest[0] == 'users' and (len(rest) < 3 or rest[2] == 'appdata' or rest[2].startswith('.')))):
                raise ValueError('Choose a Windows project folder, not a drive, user home or application state.')


def check_mounts(config, state, image):
    """Check VM sharing and ownership before starting long-lived containers."""
    import tempfile
    from contextlib import ExitStack
    paths = [(Path(config['workspace']), False),
             *[(Path(row['source']), row['read_only']) for row in config.get('extra_folders', [])],
             (Path(state) / 'runtime-config', True)]
    if config.get('pi_config'):
        paths.append((Path(config['pi_config']), True))
    command = ['podman', 'run', '--rm', '--network=none', '--cap-drop=ALL',
               '--entrypoint=python3', '--security-opt=label=disable', '--security-opt=no-new-privileges', '--userns=keep-id:uid=1000,gid=1000', '--user=1000:1000']
    checks, sources = [], []
    with ExitStack() as stack:
        for i, (path, readonly) in enumerate(paths):
            token = secrets.token_hex(16)
            if readonly:
                source = path
                expected = sorted(p.name for p in path.iterdir())[:32]
            else:
                source = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='.psf-mount-', dir=path)))
                (source / 'host').write_text(token)
                expected = token
            target = '/check' + str(i)
            command += ['--mount', f'type=bind,src={source},dst={target},' + ('ro' if readonly else 'rw')]
            checks.append([target, readonly, expected, token])
            sources.append(source)
        script = """
import errno, json, sys
from pathlib import Path
for target, readonly, expected, token in json.loads(sys.argv[1]):
    root = Path(target)
    if readonly:
        assert sorted(p.name for p in root.iterdir())[:32] == expected, 'Host folder contents differ in the VM'
    else:
        assert (root / 'host').read_text() == expected, 'Host file is not visible in the VM'
    probe = root / ('.psf-probe-' + token if readonly else 'container')
    try:
        probe.write_text(token)
    except OSError as error:
        if not readonly or error.errno != errno.EROFS: raise
    else:
        if readonly:
            probe.unlink()
            raise AssertionError('Read-only mount was writable')
"""
        result = subprocess.run(command + [image, '-c', script, json.dumps(checks)], capture_output=True, text=True)
        if result.returncode:
            advice = ('Keep them under your shared macOS home, or configure machine volumes.' if is_mac()
                      else 'Keep projects in the WSL filesystem, for example ~/Projects.')
            raise ValueError('Podman cannot use the selected folders with the required ownership and access. '
                             + advice + ' Details: ' + result.stderr[-1600:])
        for source, (_, readonly, _, token) in zip(sources, checks):
            if not readonly and (source / 'container').read_text() != token:
                raise ValueError('Container writes are not visible in the selected host folder.')
