"""Exercise the old manager's real upgrade and both supported installers.

python tests/integration.py --baseline OLD_CHECKOUT --application NEW_CHECKOUT --output OUTPUT
Sources must be clean Git checkouts. All installations and data live under OUTPUT.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import shutil
import subprocess
import sys
import termios
import struct
import xml.etree.ElementTree as ET

OLD_URL = 'https://github.com/kyuz0/pi-sandbox-factory.git'
NEW_URL = 'https://github.com/kyuz0/ai-sandbox-factory.git'


def execute(command, env, log):
    with log.open('ab') as stream:
        subprocess.run([str(value) for value in command], env=env, cwd='/tmp',
                       stdout=stream, stderr=subprocess.STDOUT, check=True)


def output(command, env):
    return subprocess.check_output([str(value) for value in command], env=env, cwd='/tmp', text=True)


def terminal(command, env, log):
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 120, 0, 0))
    process = subprocess.Popen([str(value) for value in command], env=env, cwd='/tmp',
                               stdin=slave, stdout=slave, stderr=slave)
    os.close(slave)
    received = bytearray();confirmed = False
    try:
        with log.open('wb') as stream:
            while True:
                ready, _, _ = select.select([master], [], [], 1)
                if ready:
                    try:
                        data = os.read(master, 65536)
                    except OSError:
                        break
                    if not data:
                        break
                    received.extend(data);stream.write(data);stream.flush()
                    if not confirmed and b'Press Enter to continue' in received:
                        os.write(master, b'\r');confirmed = True
                elif process.poll() is not None:
                    break
        if process.wait():
            raise RuntimeError(f'Terminal command failed; see {log}')
    finally:
        os.close(master)
        if process.poll() is None:
            process.terminate();process.wait()
    return received.decode(errors='replace')


def rewrite(path, baseline, application):
    path.write_text(f'[url "{baseline.as_uri()}"]\n\tinsteadOf = {OLD_URL}\n'
                    f'[url "{application.as_uri()}"]\n\tinsteadOf = {NEW_URL}\n')


def seed(home):
    roots = [home / relative / 'pi-sandbox-factory' for relative in
             ('.local/state', '.config', '.local/share', '.cache')]
    for index, root in enumerate(roots):
        root.mkdir(parents=True)
        (root / 'receipt').write_bytes(bytes([index, 0, 255]))
    initialized = home / '.config/ai-sandbox-factory/packages'
    initialized.mkdir(parents=True)
    (initialized / 'registry.lock').touch()
    cache = home / '.cache/ai-sandbox-factory';cache.mkdir(parents=True)
    (cache / 'new-download').write_text('keep the new cache')
    state = roots[0] / 'saved-example';state.mkdir()
    (state / 'config.json').write_text(json.dumps({'name': 'saved-example', 'engine': 'podman',
         'workspace': '/tmp/example-project', 'profile': {'name': 'base'}}))
    return roots


def check_data(roots):
    for index, old in enumerate(roots):
        new = old.with_name('ai-sandbox-factory')
        if index == 3:
            assert old.is_dir() and not old.is_symlink(), old
            assert (old / 'receipt').read_bytes() == bytes([index, 0, 255])
            assert (new / 'new-download').read_text() == 'keep the new cache'
        else:
            assert old.is_symlink() and new.is_dir(), old
            assert (new / 'receipt').read_bytes() == bytes([index, 0, 255])


def environment(root):
    home = root / 'home';home.mkdir(parents=True)
    env = dict(os.environ, HOME=str(home), PIPX_HOME=str(root / 'pipx'),
               PIPX_BIN_DIR=str(root / 'bin'), PIPX_MAN_DIR=str(root / 'man'),
               GIT_CONFIG_GLOBAL=str(root / 'gitconfig'), UV_NO_GITHUB_FAST_PATH='1', UV_LINK_MODE='hardlink', UV_CACHE_DIR=str(root.parent / 'uv-cache'),
               PIP_CACHE_DIR=str(root.parent / 'pip-cache'), XDG_CONFIG_HOME=str(home / '.config'),
               XDG_DATA_HOME=str(home / '.local/share'), XDG_CACHE_HOME=str(home / '.cache'))
    # GitHub's API sees published main; local fixtures must resolve refs through Git's URL rewrite.
    env['PATH'] = str(root / 'bin') + os.pathsep + os.environ['PATH']
    return home, env


def pipx_case(kind, root, args):
    home, env = environment(root)
    config = Path(env['GIT_CONFIG_GLOBAL'])
    rewrite(config, args.baseline, args.application)
    log = root / 'install.log'
    execute(['pipx', 'install', '--python', args.python, 'git+' + OLD_URL], env, log)
    roots = seed(home)
    rewrite(config, args.bridge, args.application)
    old_python = root / 'pipx/venvs/pi-sandbox-factory/bin/python'
    old = root / 'bin/pi-sandbox-factory'
    new = root / 'bin/ai-sandbox-factory'
    if kind == 'in-app':
        # Execute the shipped old upgrade method and its exact module relaunch.
        # The suspension context is a terminal concern; use a no-op for this driver.
        code = """
from contextlib import nullcontext
import os,sys
from pathlib import Path
from pi_sandbox_factory import sandbox_tui,updates,host_platform
app=sandbox_tui.Cockpit(Path(sys.argv[1]));app.suspend=lambda:nullcontext()
app.push_screen=lambda screen:print(screen.heading,screen.message,flush=True)
app.upgrade(True)
assert app.return_value==updates.RELAUNCH, 'Old updater did not request a relaunch'
os.environ.update(TEXTUAL_SCREENSHOT='1',TEXTUAL_SCREENSHOT_LOCATION=sys.argv[2],TEXTUAL_SCREENSHOT_FILENAME='handoff.svg')
os.execv(sys.executable,host_platform.python_command('pi_sandbox_factory','--state-dir',sys.argv[1],'tui'))
"""
        text = terminal([old_python, '-I', '-c', code, roots[0], root], env, root / 'handoff.log')
        capture = root / 'handoff.svg'
        assert capture.exists(), capture
        rendered = ''.join(ET.parse(capture).getroot().itertext()).replace('\u00a0', ' ')
        assert 'AI Sandbox Factory' in rendered, capture
    else:
        execute(['pipx', 'upgrade-all'], env, log)
        text = terminal([old, '--version'], env, root / 'handoff.log')
        assert 'Press Enter to continue' in text
    check_data(roots)
    listing = json.loads(output(['pipx', 'list', '--json'], env))['venvs']
    assert set(listing) == {'pi-sandbox-factory', 'ai-sandbox-factory'}, listing.keys()
    assert listing['pi-sandbox-factory']['metadata']['main_package']['apps'] == ['pi-sandbox-factory']
    assert listing['ai-sandbox-factory']['metadata']['main_package']['apps'] == ['ai-sandbox-factory']
    execute(['pipx', 'upgrade', 'pi-sandbox-factory'], env, log)
    for command in ([old, '--version'], [new, '--version'],
                    [old, 'profile', 'list'], [new, 'provider', 'list']):
        execute(command, env, log)
    for command in (old, new):
        quiet = dict(env, PATH=str(root / 'bin'))
        result = subprocess.run([str(command), 'list', '--json'], env=quiet, cwd='/tmp', capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)[0]['name'] == 'saved-example'
        assert result.stderr.strip() == 'Warning: cannot query podman; container status is unknown', result.stderr
    execute(['pipx', 'uninstall', 'pi-sandbox-factory'], env, log)
    assert new.is_file() and not old.exists()
    execute([new, '--version'], env, log)
    check_data(roots)
    print(f'{kind}: old upgrade, prompt, install, data, module handoff, quiet scripts, repeat run and uninstall passed', flush=True)
    shutil.rmtree(root / 'pipx')


def pip_case(root, args):
    home, env = environment(root)
    rewrite(Path(env['GIT_CONFIG_GLOBAL']), args.baseline, args.application)
    execute([args.python, '-m', 'venv', root / 'venv'], env, root / 'install.log')
    python = root / 'venv/bin/python';old = root / 'venv/bin/pi-sandbox-factory'
    execute([python, '-m', 'pip', 'install', 'git+' + OLD_URL], env, root / 'install.log')
    roots = seed(home)
    rewrite(Path(env['GIT_CONFIG_GLOBAL']), args.bridge, args.application)
    execute([python, '-m', 'pip', 'install', '--upgrade', 'git+' + OLD_URL], env, root / 'install.log')
    execute([old, '--yes', '--version'], env, root / 'handoff.log')
    check_data(roots)
    execute([python, '-I', '-m', 'ai_sandbox_factory', 'profile', 'list'], env, root / 'handoff.log')
    execute([python, '-m', 'pip', 'uninstall', '-y', 'pi-sandbox-factory'], env, root / 'install.log')
    execute([python, '-I', '-m', 'ai_sandbox_factory', '--version'], env, root / 'handoff.log')
    print('pip: both distributions coexist; removing the old launcher preserves the new application and data', flush=True)
    shutil.rmtree(root / 'venv')


def user_site_case(root, args):
    home, env = environment(root)
    env['PYTHONUSERBASE'] = str(home / 'user-packages')
    rewrite(Path(env['GIT_CONFIG_GLOBAL']), args.bridge, args.application)
    log = root / 'install.log'
    execute([args.python, '-m', 'venv', '--system-site-packages', root / 'venv'], env, log)
    python = root / 'venv/bin/python'
    execute([python, '-m', 'pip', 'install', '--user', 'git+' + OLD_URL, 'git+' + NEW_URL], env, log)
    roots = seed(home)
    old = home / 'user-packages/bin/pi-sandbox-factory'
    execute([old, '--yes', '--version'], env, root / 'handoff.log')
    check_data(roots)
    print('pip-user: user-site application launch and data migration passed', flush=True)
    shutil.rmtree(root / 'venv')
    shutil.rmtree(home / 'user-packages')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--application', type=Path, required=True)
    parser.add_argument('--bridge', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--only', choices=['in-app', 'upgrade-all', 'pip', 'pip-user'])
    args = parser.parse_args()
    for name in ('baseline', 'application', 'bridge', 'output'):
        setattr(args, name, getattr(args, name).resolve())
    for source in (args.baseline, args.application, args.bridge):
        if not (source / '.git').exists():
            parser.error(f'{source} must be a Git checkout, not an unversioned source export')
    args.output.mkdir(parents=True, exist_ok=True)
    for kind in ('in-app', 'upgrade-all'):
        if not args.only or args.only == kind:
            pipx_case(kind, args.output / kind, args)
    if not args.only or args.only == 'pip':
        pip_case(args.output / 'pip', args)

    if not args.only or args.only == 'pip-user':
        user_site_case(args.output / 'pip-user', args)
