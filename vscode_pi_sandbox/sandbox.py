#!/usr/bin/env python3
"""Native Linux Docker/Podman sandbox; no Compose or host Python packages needed."""
import argparse
from . import sandbox_skills
from . import sandbox_extensions
from . import sandbox_advisors
from . import sandbox_ssh
from . import registry, model_providers, browser_viewer
from contextlib import closing
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from types import SimpleNamespace
from .sandbox_options import options, memory_limit, permissions, write_json, guidance

ROOT = Path(__file__).resolve().parent
LABEL = 'io.vscode-pi-sandbox.name'
PI_VERSION = '1.4.0'
PENDANT_VERSION = '0.94.2'
RUNTIME_ENV = {
    'HTTP_PROXY': 'http://127.0.0.1:3128', 'HTTPS_PROXY': 'http://127.0.0.1:3128',
    'http_proxy': 'http://127.0.0.1:3128', 'https_proxy': 'http://127.0.0.1:3128',
    'NO_PROXY': 'localhost,127.0.0.1,::1', 'no_proxy': 'localhost,127.0.0.1,::1',
    'NODE_USE_ENV_PROXY': '1',
}


def tree_digest(path):
    digest = hashlib.sha256()
    for file in sorted(path.rglob('*')):
        if any(part in {'.git', '__pycache__'} for part in file.relative_to(path).parts):
            continue
        if file.is_symlink():
            raise ValueError(f'Profile/build contexts must not contain symlinks: {file}')
        if file.is_file():
            digest.update(str(file.relative_to(path)).encode() + b'\0' + file.read_bytes() + b'\0')
    return digest.hexdigest()[:16]


def load_profile(value):
    candidate = registry.resolve('profile', value)
    path = directory(candidate)
    metadata = json.loads((path / 'profile.json').read_text())
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,39}', metadata.get('name', '')):
        raise ValueError('profile.json requires a lowercase name (letters, digits, hyphens)')
    for filename in ('Dockerfile', 'profile.md'):
        if not (path / filename).is_file():
            raise ValueError(f'Profile is missing {filename}: {path}')
    profile = {'name': metadata['name'], 'description': metadata.get('description', ''),
               'path': str(path), 'digest': tree_digest(path), 'registry_name': value}
    if 'git_source' in metadata:
        source = metadata['git_source']
        if (not isinstance(source, str) or not source
                or source.startswith('-') or any(c.isspace() for c in source)):
            raise ValueError('git_source must be a Git repository URL without whitespace')
        if (path / 'source').exists():
            raise ValueError('git_source profiles must reserve source/ for fetched files')
        profile['git_source'] = source
    return profile


def snapshot_profile(profile, state):
    if profile.get('git_source'):
        state.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.profile-', dir=state) as temp:
            staging = Path(temp) / 'profile'
            checkout = Path(temp) / 'checkout'
            shutil.copytree(profile['path'], staging,
                            ignore=shutil.ignore_patterns('.git', '__pycache__'))
            # Authenticate on the host; never put Git credentials or metadata in images.
            run(['git', 'clone', '--recurse-submodules', '--', profile['git_source'], str(checkout)])
            tree_digest(checkout)  # Reject symlinked build inputs before copying.
            shutil.copytree(checkout, staging / 'source',
                            ignore=shutil.ignore_patterns('.git', '__pycache__'))
            revision = run(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], capture=True).stdout.strip()
            submodules = run(['git', '-C', str(checkout), 'submodule', 'status', '--recursive'],
                             capture=True).stdout
            (staging / 'source-revisions.json').write_text(json.dumps(
                {'commit': revision, 'submodules': [
                    {'commit': line[1:41], 'path': line[42:].split(' (', 1)[0]}
                    for line in submodules.splitlines()]}, indent=2) + '\n')
            digest = tree_digest(staging)
            destination = state / 'profiles' / digest
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(staging), destination)
            # A saved snapshot builds offline from its fetched inputs. Only an explicit
            # recreate --profile fetches a new source version.
            return {key: value for key, value in dict(profile, path=str(destination),
                    digest=digest, source_commit=revision).items() if key != 'git_source'}
    destination = state / 'profiles' / profile['digest']
    if not destination.exists():
        shutil.copytree(profile['path'], destination,
                        ignore=shutil.ignore_patterns('.git', '__pycache__'))
    return dict(profile, path=str(destination))


def selected_profile(config):
    return config.get('profile') or load_profile('base')


def common_profile():
    path = ROOT / 'containers/dev'
    return dict(name='common', path=str(path), digest=tree_digest(path),
                **json.loads((path / 'package-source.json').read_text()))


def run(argv, capture=False, check=True, **kwargs):
    return subprocess.run([str(x) for x in argv], check=check, text=True,
                          stdout=subprocess.PIPE if capture else None, **kwargs)


def directory(value):
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError(f'Not a directory: {path}')
    if any(c in str(path) for c in ':,\n\r'):
        raise ValueError('Mount paths must not contain colons, commas, or newlines')
    return path


def parse_rules(text):
    rules = []
    for number, line in enumerate(text.splitlines(), 1):
        words = line.split('#', 1)[0].split()
        if not words:
            continue
        # Accept the old suffix for existing policy files; it no longer changes
        # behavior. An explicitly allowed hostname may resolve to any address.
        if len(words) > 2 or (len(words) == 2 and words[1] != 'private'):
            raise ValueError(f'Allowlist line {number}: expected hostname:port')
        match = re.fullmatch(r'([a-zA-Z0-9.-]+):([0-9]+)', words[0])
        if not match:
            raise ValueError(f'Allowlist line {number}: use an exact hostname:port')
        host, port = match[1].lower(), int(match[2])
        if (len(host) > 253 or '.' not in host or not 1 <= port <= 65535
                or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', p)
                       for p in host.split('.'))):
            raise ValueError(f'Allowlist line {number}: invalid hostname or port')
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError('Use DNS names, not literal IP addresses, in the allowlist')
        rule = (host, port)
        if rule not in rules:
            rules.append(rule)
    return rules


def squid_config(rules):
    lines = [
        'http_port 127.0.0.1:3128',
        'visible_hostname vscode-pi-sandbox-gateway',
        # The entrypoint supervises Squid directly. A persistent PID file can
        # mistake a reused container PID for the previous process after a crash.
        'pid_filename none',
        'cache_log /dev/stderr',
        'access_log stdio:/dev/stdout',
        'cache_store_log none',
        'cache deny all',
        'coredump_dir /tmp',
        'shutdown_lifetime 1 seconds',
        'forwarded_for delete',
        'via off',
        'acl sandbox_methods method GET HEAD POST PUT PATCH DELETE OPTIONS CONNECT',
        'http_access deny !sandbox_methods',
        # Reject unknown names before forwarding, so denied requests cause no DNS.
    ]
    if rules:
        lines += ['acl sandbox_hosts dstdomain -n ' + ' '.join(sorted({r[0] for r in rules})),
                  'http_access deny !sandbox_hosts']
    else:
        return '\n'.join(lines + ['http_access deny all', ''])
    for i, (host, port) in enumerate(rules):
        lines += [f'acl host_{i} dstdomain -n {host}', f'acl port_{i} port {port}']
    for i, _ in enumerate(rules):
        lines.append(f'http_access allow host_{i} port_{i}')
    return '\n'.join(lines + ['http_access deny all', ''])


def validate_models(config, rules, strict=True):
    models = config / 'models.json'
    if not models.is_file():
        raise ValueError(f'Missing {models}')
    providers = json.loads(models.read_text()).get('providers', {})
    allowed = set(rules)
    for name, provider in providers.items():
        if 'baseUrl' not in provider:
            continue
        url = urlsplit(provider['baseUrl'])
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
            raise ValueError(f'Provider {name}: baseUrl must be an HTTP(S) URL without credentials')
        target = (url.hostname, url.port or (443 if url.scheme == 'https' else 80))
        if target not in allowed:
            if strict:
                raise ValueError(f'Provider {name}: add {target[0]}:{target[1]} to the allowlist')
            print(f'Provider {name}: {target[0]}:{target[1]} remains blocked by the network policy.')


def validate_env(path):
    # Never source the file in a shell. Limit it to credentials and provider options.
    if not path:
        return
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, sep, _ = line.partition('=')
        if not sep or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
            raise ValueError('Env file must contain literal UPPERCASE_NAME=value entries')
        if (key in {'HOME', 'PATH', 'ENV', 'BASH_ENV', 'LD_PRELOAD', 'LD_LIBRARY_PATH',
                    'NODE_OPTIONS', 'NODE_USE_ENV_PROXY', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
                    'SSH_AUTH_SOCK', 'PI_ADVISOR_SOCKET', 'SANDBOX_NETWORK_MODE', 'SANDBOX_SUBAGENTS', 'SANDBOX_APPROVAL_MODE', 'PI_SANDBOX_CONTAINER', 'PI_AUTO_REVIEW_ALLOW_UNTRUSTED_DEV'}
                or any(x in key for x in ('PROXY', 'PI_CODING_AGENT_DIR'))):
            raise ValueError(f'{key} is controlled by the sandbox, not the credentials file')


def choose_engine(requested, quiet=False):
    if requested != 'auto':
        if requested == 'docker':
            version = run(['docker', '--version'], capture=True).stdout.lower()
            if 'podman' in version:
                if not quiet:
                    print('The docker command is a Podman wrapper; using rootless Podman mode.')
                return 'podman'
        return requested
    for engine in ('podman', 'docker'):
        if shutil.which(engine):
            return engine
    raise ValueError('Install Podman or Docker first')


def names(config):
    prefix = 'vscode-pi-sandbox-' + config['name']
    return prefix, prefix + '-proxy', prefix + '-socket', prefix + '-home'


def image_names(config):
    profile = selected_profile(config)
    suffix = ('-' + hashlib.sha256(json.dumps([s['digest'] for s in config['extra_skills']]).encode()).hexdigest()[:12]) if config.get('extra_skills') else ''
    if options(config.get('options'))['browser']:
        suffix += '-browser'
    if 'model_providers' in config:
        suffix += '-models-' + model_providers.digest(config)
    return (f'localhost/vscode-pi-sandbox-dev:{profile["name"]}-{base_tag(config)}-{profile["digest"]}{suffix}',
            'localhost/vscode-pi-sandbox-proxy:1')


def network_mode(config):
    mode = config.get('network', 'allowlist')
    if mode not in ('allowlist', 'unrestricted'):
        raise ValueError(f'Invalid saved network mode: {mode}')
    return mode


def base_tag(config):
    digest = config.get('common', {}).get('digest') or tree_digest(ROOT / 'containers/dev')
    identity = f'{PI_VERSION}-{PENDANT_VERSION}-{config["uid"]}-{config["gid"]}-' + digest
    return hashlib.sha256(identity.encode()).hexdigest()[:16]


def build(config):
    dev, proxy = image_names(config)
    profile = selected_profile(config)
    if tree_digest(Path(profile['path'])) != profile['digest']:
        raise ValueError('Saved profile was modified; select its source again with recreate --profile')
    common = config['common']
    if tree_digest(Path(common['path'])) != common['digest']:
        raise ValueError('Saved common image inputs were modified; use recreate --profile to refresh them')
    base = f'localhost/vscode-pi-sandbox-base:{base_tag(config)}'
    engine = config['engine']
    run([engine, 'build', '-t', proxy, ROOT / 'containers/proxy'])
    with sandbox_extensions.build_contexts(common['path']) as contexts:
        run([engine, 'build', '-t', base, *contexts, '--build-arg', f'USER_UID={config["uid"]}',
             '--build-arg', f'USER_GID={config["gid"]}', '--build-arg', f'PI_VERSION={PI_VERSION}',
             '--build-arg', f'PENDANT_VERSION={PENDANT_VERSION}', common['path']])
    browser = options(config.get('options'))['browser']
    has_providers = 'model_providers' in config
    tools = dev + '-tools' if config.get('extra_skills') or browser or has_providers else dev
    run([engine, 'build', '-t', tools, '--build-arg', f'BASE_IMAGE={base}', profile['path']])
    if browser:
        target = dev + '-browser' if config.get('extra_skills') or has_providers else dev
        run([engine, 'build', '-t', target, '--build-arg', f'BASE_IMAGE={tools}',
             Path(common['path']) / 'browser'])
        tools = target
    if has_providers:
        target = dev + '-models' if config.get('extra_skills') else dev
        model_providers.build(config, tools, target)
        tools = target
    sandbox_ssh.build(config)
    sandbox_advisors.build(config)
    sandbox_skills.build(config, dev, SimpleNamespace(run=run, tree_digest=tree_digest), base_image=tools)


def inspect(config, name):
    result = run([config['engine'], 'container', 'inspect', name], capture=True,
                 check=False, stderr=subprocess.DEVNULL)
    if result.returncode:
        return None
    data = json.loads(result.stdout)[0]
    if data['Config'].get('Labels', {}).get(LABEL) != config['name']:
        raise ValueError(f'Refusing to manage an unrelated container named {name}')
    return data


def list_sandboxes(state_root, structured=False):
    configs = []
    for path in sorted(state_root.glob('*/config.json')):
        try:
            config = json.loads(path.read_text())
            profile = config.get('profile') or {'name': 'base'}
            if (config.get('name') != path.parent.name
                    or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,39}', config['name'])
                    or config.get('engine') not in ('podman', 'docker')
                    or not isinstance(config.get('workspace'), str)
                    or not isinstance(profile.get('name'), str)):
                raise ValueError('Invalid saved configuration')
            configs.append((config, profile['name']))
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            print(f'Warning: cannot read sandbox configuration for {path.parent.name}', file=sys.stderr)
            configs.append(({'name': path.parent.name}, '-'))
    if not configs:
        print('[]' if structured else f'No saved sandboxes in {state_root}')
        return

    # Query each saved engine once. Missing containers and an unavailable engine
    # are different states; listing must remain useful when the engine is offline.
    statuses = {}
    for engine in sorted({c['engine'] for c, _ in configs if 'engine' in c}):
        try:
            result = run([engine, 'ps', '--all', '--format',
                          '{{.Names}}\t{{.State}}\t{{.Label "' + LABEL + '"}}'],
                         capture=True, check=False, stderr=subprocess.DEVNULL)
            if result.returncode:
                raise ValueError('Engine unavailable')
            containers = {}
            for line in result.stdout.splitlines():
                name, status, owner = line.split('\t')
                containers[name] = (status, owner)
            statuses[engine] = containers
        except (OSError, ValueError):
            statuses[engine] = None
            print(f'Warning: cannot query {engine}; container status is unknown', file=sys.stderr)

    inventory = []
    rows = [('NAME', 'PROFILE', 'ENGINE', 'DEV', 'PROXY', 'WORKSPACE')]
    for config, profile in configs:
        engine = config.get('engine')
        states = []
        for name in names(config)[:2]:
            if engine is None:
                status = 'invalid config'
            elif statuses[engine] is None:
                status = 'unknown'
            elif name not in statuses[engine]:
                status = 'missing'
            else:
                status, owner = statuses[engine][name]
                if owner != config['name']:
                    status = 'unrelated'
            states.append(status)
        if config.get('network') == 'unrestricted' and states[1] == 'missing':
            states[1] = 'not used'
        inventory.append(dict(name=config['name'], profile=profile, engine=engine, dev=states[0],
                              proxy=states[1], workspace=config.get('workspace'), config=config))
        rows.append((config['name'], profile, engine or '-', *states, config.get('workspace', '-')))
    if structured:
        print(json.dumps(inventory))
        return
    # Keep paths and other saved values from introducing terminal control codes.
    rows = [tuple(''.join(c if c.isprintable() else '?' for c in cell) for cell in row) for row in rows]
    widths = [max(len(row[i]) for row in rows) for i in range(5)]
    for row in rows:
        print('  '.join(cell.ljust(widths[i]) if i < 5 else cell for i, cell in enumerate(row)))


def restart_existing(config, name):
    # Podman can return an error from stop after successfully clearing stale
    # conmon state. Verify the resulting state before deciding whether to start.
    if not inspect(config, name):
        raise ValueError(f'Container disappeared during recovery: {name}')
    run([config['engine'], 'stop', '--time', '10', name], capture=True, check=False,
        stderr=subprocess.PIPE)
    current = inspect(config, name)
    if not current or current['State']['Running']:
        raise ValueError(f'Could not stop {name} safely; inspect with {config["engine"]} logs {name}')
    run([config['engine'], 'start', name])


def resume_existing(config, name, current):
    if current['State']['Running']:
        # Metadata can survive a crash even though the OCI runtime is stopped.
        result = run([config['engine'], 'exec', name, 'true'], capture=True,
                     check=False, stderr=subprocess.PIPE)
        if result.returncode == 0:
            return
        if 'not running' not in (result.stderr or '').lower():
            raise ValueError(f'Cannot execute in {name}; inspect with {config["engine"]} logs {name}. '
                             'The container was not restarted.')
        print(f'Recovering stale running state: {name}')
        restart_existing(config, name)
    else:
        run([config['engine'], 'start', name])


def ensure_gateway(config):
    try:
        wait_gateway(config)
    except ValueError:
        _, proxy, _, _ = names(config)
        print(f'Recovering unresponsive gateway: {proxy}; network requests may be interrupted')
        restart_existing(config, proxy)
        try:
            wait_gateway(config)
        except ValueError as exc:
            raise ValueError(f'{exc}. Automatic gateway recovery was attempted once; '
                             'workspace and home volumes were preserved.') from exc


def upgrade_gateway_config(state):
    """Make saved launcher configurations safe to resume after an abrupt stop."""
    path = state / 'squid.conf'
    if not path.is_file():
        return
    original = path.read_text()
    updated = re.sub(r'(?m)^pid_filename /tmp/squid\.pid$', 'pid_filename none', original)
    if updated != original:
        # Keep the inode and SELinux label: an existing container bind-mounts
        # this file, so atomic replacement would leave it seeing the old copy.
        path.write_text(updated)
        print('Updated gateway configuration for restart-safe startup.')


def up(config, state):
    engine = config['engine']
    dev, proxy, socket_volume, home_volume = names(config)
    restricted = network_mode(config) == 'allowlist'
    sandbox_advisors.check_ownership(config)
    sandbox_ssh.check_ownership(config)
    # Verify both ownership labels before starting or recovering either one.
    current = {name: inspect(config, name) for name in (proxy, dev)}
    if restricted:
        upgrade_gateway_config(state)
    active = (proxy, dev) if restricted else (dev,)
    if any(current[name] is None for name in active):
        dev_image, proxy_image = image_names(config)
        for name, tag in ((proxy, proxy_image), (dev, dev_image)):
            if name not in active:
                continue
            if current[name] is None and run([engine, 'image', 'inspect', tag], capture=True,
                                            check=False, stderr=subprocess.DEVNULL).returncode:
                raise ValueError('Images are missing; run the build command first')
    # Report blocked endpoints in an optional host seed; private models remain
    # writable inside the sandbox, and the proxy enforces their runtime policy.
    rules = parse_rules((state / 'allowlist.txt').read_text())
    if restricted and config.get('pi_config'):
        validate_models(Path(config['pi_config']), rules, strict=False)
    sandbox_advisors.up(config, state)
    sandbox_ssh.up(config, state)
    for name in active:
        if current[name]:
            resume_existing(config, name, current[name])
            if name == proxy:
                ensure_gateway(config)
            continue
        base = [engine, 'run', '-d', '--name', name, '--label', f'{LABEL}={config["name"]}',
                '--security-opt=no-new-privileges', '--pids-limit=512']
        if name == proxy:
            args = [
                '--cap-drop=ALL', '--cap-add=CHOWN', '--cap-add=SETUID', '--cap-add=SETGID',
                '--cap-add=DAC_OVERRIDE', '--memory=256m',
                '-v', f'{state / "squid.conf"}:/etc/squid/sandbox.conf:ro,Z',
                '-v', f'{socket_volume}:/run/egress:z',
            ]
            if config.get('local_model_gateway'):
                args += ['--network=pasta:--map-host-loopback,169.254.1.2',
                         '--add-host=local-model.internal:169.254.1.2']
            if any(host == 'host.docker.internal' for host, _ in rules):
                args += ['--add-host=host.docker.internal:host-gateway']
            run(base + args + [proxy_image])
            ensure_gateway(config)
        else:
            # Files moved into a running workspace retain their host SELinux
            # labels. Mount-time :z relabeling cannot make later imports usable.
            # Disable label separation only for the development container;
            # the gateway keeps its SELinux confinement and labeled volumes.
            args = ['--network=' + ('none' if restricted else 'bridge'), '--cap-drop=ALL',
                    '--security-opt=label=disable',
                    '--user', f'{config["uid"]}:{config["gid"]}',
                    '-v', f'{config["workspace"]}:/workspace:rw',
                    '-v', f'{home_volume}:/home/node']
            args += sandbox_advisors.mounts(config)
            args += sandbox_ssh.mounts(config, state)
            if config.get('memory'):
                args += ['--memory=' + memory_limit(config['memory'])]
            if 'options' in config:
                prepare_options(config, state)
                args += ['-v', f'{state / "runtime-config"}:/opt/pi-security/config:ro,Z',
                         '-v', f'{state / "options.json"}:/opt/sandbox/options.json:ro,Z']
            if restricted:
                args += ['-v', f'{socket_volume}:/run/egress:ro']
            if config.get('pi_config'):
                args += ['-v', f'{config["pi_config"]}:/pi-config:ro']
            if engine == 'podman':
                args += ['--userns=keep-id:uid=1000,gid=1000']
            if config.get('env_file'):
                validate_env(config['env_file'])
                args += ['--env-file', config['env_file']]
            runtime_env = RUNTIME_ENV if restricted else {'NODE_USE_ENV_PROXY': '1'}
            if config.get('local_model_gateway'):
                args += ['--env', 'LOCAL_MODEL_PORTS=' + config['local_model_ports']]
            args += ['--env', 'SANDBOX_NETWORK_MODE=' + network_mode(config)]
            args += ['--env', 'SANDBOX_SUBAGENTS=' + ('1' if config.get('subagents', False) else '0')]
            args += ['--env', 'SANDBOX_APPROVAL_MODE=' + options(config.get('options'))['approval']]
            for key, value in runtime_env.items():
                args += ['--env', f'{key}={value}']
            run(base + args + [dev_image])
    # Readiness also catches bootstrap failures (permissions, malformed settings).
    for _ in range(40):
        ready = 'test -f /home/node/.vscode-server/data/Machine/settings.json'
        entrypoint = Path(config.get('common', {}).get('path', '/nonexistent')) / 'entrypoint.sh'
        if 'options' in config and entrypoint.is_file() and '/tmp/vscode-pi-sandbox-ready' in entrypoint.read_text():
            ready += ' && test -f /tmp/vscode-pi-sandbox-ready'
        if restricted:
            ready += ' && test -S /run/egress/proxy.sock && echo >/dev/tcp/127.0.0.1/3128'
        result = run([engine, 'exec', dev, 'bash', '-c', ready], capture=True, check=False,
                     stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            if options(config.get('options'))['browser']:
                browser_viewer.ensure_viewer(engine, inspect(config, dev)['Id'])
            print(f'Ready: {dev}; workspace /workspace; engine {engine}; network {network_mode(config)}')
            return
        time.sleep(0.25)
    raise ValueError(f'Sandbox did not become ready; inspect with {engine} logs {dev}')


def wait_gateway(config):
    _, proxy, _, _ = names(config)
    for _ in range(40):
        result = run([config['engine'], 'exec', proxy, 'bash', '-c',
                      'test -S /run/egress/proxy.sock && echo >/dev/tcp/127.0.0.1/3128'],
                     capture=True, check=False, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            return
        time.sleep(0.25)
    raise ValueError(f'Gateway did not become ready; inspect with {config["engine"]} logs {proxy}')


def down(config, remove=False):
    for name in names(config)[:2]:
        inspect(config, name)
    sandbox_advisors.check_ownership(config)
    sandbox_ssh.check_ownership(config)
    sandbox_advisors.down(config, remove=remove)
    sandbox_ssh.down(config, remove=remove)
    for name in names(config)[:2]:
        if inspect(config, name):
            run([config['engine'], 'rm', '-f', name] if remove
                else [config['engine'], 'stop', name])
    # Named volumes are deliberately kept, including sessions and editor state.


def delete(config, state):
    if config['name'] != state.name:
        raise ValueError('Saved sandbox name does not match its state directory')
    workspace = Path(config['workspace']).resolve()
    if workspace == state or state in workspace.parents:
        raise ValueError('Refusing to delete state containing the host workspace')
    sandbox_advisors.check_ownership(config)
    sandbox_ssh.check_ownership(config)
    # Verify ownership of both containers before removing either one.
    for name in names(config)[:2]:
        inspect(config, name)
    # A checked listing also prevents discarding state when the engine is unavailable.
    volumes = set(run([config['engine'], 'volume', 'ls', '--format', '{{.Name}}'],
                      capture=True).stdout.splitlines())
    down(config, remove=True)
    for volume in names(config)[2:]:
        if volume in volumes:
            run([config['engine'], 'volume', 'rm', volume])
    sandbox_advisors.delete_volumes(config)
    sandbox_ssh.delete_volumes(config)
    shutil.rmtree(state)
    print(f'Deleted {config["name"]}: containers, private volumes, and saved state. Host workspace preserved.')


def delete_incomplete(state):
    # Creation fetches sources before writing config.json or creating containers.
    # Accept only that pre-configuration layout, not arbitrary directories.
    if not state.is_dir() or state.is_symlink():
        raise ValueError(f'No incomplete sandbox state directory: {state}')
    for entry in state.iterdir():
        if (not entry.is_dir() or entry.is_symlink()
                or not (entry.name == 'profiles' or entry.name.startswith('.profile-'))):
            raise ValueError('Missing config.json and unrecognized state contents; refusing automatic removal')
    shutil.rmtree(state)
    print(f'Deleted incomplete creation state for {state.name}. You can create it again.')


def local_model_ports(value):
    if not isinstance(value, str) or not value:
        raise ValueError('Enter local model ports, for example 8000 or 8000-8003')
    ports = set()
    for part in value.split(','):
        if not re.fullmatch(r'\d+(?:-\d+)?', part):
            raise ValueError('Invalid local model port range')
        ends = list(map(int, part.split('-')))
        start, end = ends[0], ends[-1]
        if start < 1 or end > 65535 or end < start or end-start >= 256:
            raise ValueError('Invalid local model port range (maximum 256 ports)')
        ports.update(range(start,end+1))
    if len(ports)>256:
        raise ValueError('At most 256 local model ports')
    return sorted(ports)


def configure_local_gateway(config, value, rules):
    config['local_model_ports'] = value or None
    config['local_model_gateway'] = bool(value)
    if not value:
        return
    if config['engine'] != 'podman' or network_mode(config) != 'allowlist':
        raise ValueError('Host-local models require rootless Podman with restricted networking')
    for port in local_model_ports(value):
        if ('local-model.internal',port) not in rules:
            raise ValueError(f'Add local-model.internal:{port} to the allowlist')


def create(args, state):
    profile = load_profile(args.profile)
    mode = getattr(args, 'network', 'allowlist')
    if mode == 'unrestricted' and (args.allowlist or args.allow_domain):
        raise ValueError('--network unrestricted cannot be combined with an allowlist')
    if mode == 'allowlist' and not (args.allowlist or args.allow_domain):
        raise ValueError('Allowlist networking requires --allowlist or --allow-domain')
    workspace = directory(args.workspace)
    shared = directory(args.pi_config) if args.pi_config else None
    if workspace == Path('/') or workspace == Path.home():
        raise ValueError('Select a project directory, not / or your home directory')
    pairs = [(workspace, state)]
    if shared:
        pairs += [(workspace, shared), (shared, state)]
    for first, second in pairs:
        if first == second or first in second.parents or second in first.parents:
            raise ValueError('Workspace, shared Pi config, and sandbox state must be separate, non-nested directories')
    policy_text = (Path(args.allowlist).expanduser().read_text() if args.allowlist
                   else '\n'.join(args.allow_domain) + '\n')
    rules = parse_rules(policy_text)
    if shared and mode == 'allowlist':
        validate_models(shared, rules, strict=False)
    env_file = str(Path(args.env_file).expanduser().resolve(strict=True)) if args.env_file else None
    validate_env(env_file)
    if state.exists():
        raise ValueError(f'Sandbox already exists: {state}; choose a new name')
    engine = choose_engine(args.engine)
    uid, gid = (1000, 1000) if engine == 'podman' else (os.getuid(), os.getgid())
    if engine == 'podman':
        result = run([engine, 'info', '--format', '{{.Host.Security.Rootless}}'], capture=True)
        if result.stdout.strip() != 'true':
            raise ValueError('Podman mode requires rootless Podman')
    if uid == 0:
        raise ValueError('Run the launcher as your normal user, not sudo/root')
    config = dict(name=args.name, engine=engine, uid=uid, gid=gid, workspace=str(workspace),
                  pi_config=str(shared) if shared else None, env_file=env_file, memory=memory_limit(args.memory),
                  network=mode, subagents=getattr(args, 'subagents', False))
    model_ports = getattr(args, 'local_model_ports', None)
    configure_local_gateway(config, model_ports, rules)
    if getattr(args, 'options_file', None):
        config['options'] = options(json.loads(Path(args.options_file).read_text()))
    if getattr(args, 'browser', False):
        config['options'] = options({**config.get('options', {}), 'browser': True})
    config['advisors'] = sandbox_advisors.validate({'providers': getattr(args, 'advisor', [])})
    state.mkdir(parents=True, mode=0o700)
    try:
        values = json.loads(Path(args.providers_file).read_text()) if getattr(args,'providers_file',None) else {name:{} for name in (getattr(args,'model_provider',None) or ['local'])}
        config['model_providers'] = model_providers.prepare(values, state)
        model_providers.validate_network(config, rules)
        config['profile'] = snapshot_profile(profile, state)
        config['common'] = snapshot_profile(common_profile(), state)
        if getattr(args, 'skill_source', None):
            config['extra_skills'] = [sandbox_skills.snapshot(args.skill_source, args.skill_path, state, SimpleNamespace(run=run, tree_digest=tree_digest))]
    except (Exception, KeyboardInterrupt):
        shutil.rmtree(state)  # This create owns the newly created, incomplete state.
        raise
    (state / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
    (state / 'allowlist.txt').write_text(policy_text)
    (state / 'squid.conf').write_text(squid_config(rules))
    attach = {'workspaceFolder': '/workspace', 'remoteUser': 'node',
              'extensions': ['cdervis.vscode-pi'],
              'settings': {'pendant.agentDir': '/home/node/.pi/agent'},
              'remoteEnv': {'SSH_AUTH_SOCK': '', 'GIT_ASKPASS': '',
                            'SSH_ASKPASS': ''}}
    (state / 'attached-container.json').write_text(json.dumps(attach, indent=2) + '\n')
    print(f'Created {state}\nProfile: {profile["name"]}. Network: {mode}; {len(rules)} hostname/port rules. Run build, then up.')



def prepare_options(config, state):
    selected = options(config.get('options'))
    write_json(state / 'options.json', selected)
    target = state / 'runtime-config'
    target.mkdir(exist_ok=True, mode=0o700)
    source = Path(config['common']['path']) / 'security/config'
    for path in source.glob('*.json'):
        value = json.loads(path.read_text())
        if path.name == 'auto-review.json':
            value['interactionMode'] = 'interactive' if selected['approval'] == 'assisted' else 'automatic'
        if path.name == 'permissions.json':
            value = permissions(value, selected)
        write_json(target / path.name, value)
    guide = target / 'security.md'
    guide.write_text(guidance(selected, config.get('subagents', False)))
    guide.chmod(0o600)


def apply_settings(config, state, changes):
    allowed = {'ssh', 'advisors', 'network', 'allowlist', 'memory', 'subagents', 'env_file', 'options', 'skill_source', 'skill_path', 'remove_skills', 'local_model_ports', 'model_providers'}
    if not isinstance(changes, dict) or set(changes) - allowed:
        raise ValueError('Unknown editable sandbox setting')
    updated = dict(config)
    updated.update({k: v for k, v in changes.items() if k not in ('allowlist', 'skill_source', 'skill_path', 'remove_skills')})
    updated['extra_skills'] = [s for s in config.get('extra_skills', []) if s['name'] not in changes.get('remove_skills', [])]
    if 'ssh' in updated:
        updated['ssh'] = sandbox_ssh.validate(updated['ssh'])
    if 'advisors' in updated:
        updated['advisors'] = sandbox_advisors.validate(updated['advisors'])
    updated['options'] = options(updated.get('options'))
    updated['memory'] = memory_limit(updated.get('memory'))
    if type(updated.get('subagents', False)) is not bool:
        raise ValueError('subagents must be a boolean')
    validate_env(updated.get('env_file'))
    text = changes.get('allowlist', (state / 'allowlist.txt').read_text())
    rules = parse_rules(text)
    configure_local_gateway(updated, updated.get('local_model_ports'), rules)
    if network_mode(updated) == 'unrestricted' and rules:
        raise ValueError('Unrestricted networking cannot include an active allowlist')
    if changes.get('skill_source'):
        added = sandbox_skills.snapshot(changes['skill_source'], changes.get('skill_path', '.'), state, SimpleNamespace(run=run, tree_digest=tree_digest))
        updated['extra_skills'] = [s for s in updated['extra_skills'] if s['name'] != added['name']] + [added]
    if 'model_providers' in changes:
        updated['model_providers'] = model_providers.prepare(changes['model_providers'], state, saved=config.get('model_providers', []))
    model_providers.validate_network(updated, rules)
    # Refresh common inputs so old sandboxes acquire configurable bootstrap.
    updated['common'] = snapshot_profile(common_profile(), state)
    build(updated)  # Leave the old running container intact if the build fails.
    print('Applying settings: recreating containers; saved workspace and home are preserved.')
    down(config, remove=True)
    write_json(state / 'config.json', updated)
    (state / 'allowlist.txt').write_text(text)
    (state / 'squid.conf').write_text(squid_config(rules))
    up(updated, state)


def update_network(config, state, text):
    if network_mode(config) != 'allowlist':
        raise ValueError('Use Settings to switch to restricted networking first.')
    rules = parse_rules(text)
    configure_local_gateway(dict(config), config.get('local_model_ports'), rules)
    model_providers.validate_network(config, rules)
    proxy = names(config)[1]
    current = inspect(config, proxy)  # Verify ownership before changing live policy.
    old_text = (state / 'allowlist.txt').read_text()
    old_policy = (state / 'squid.conf').read_text()
    try:
        # Preserve the inode of the bind-mounted policy file.
        (state / 'squid.conf').write_text(squid_config(rules))
        if current and current['State']['Running']:
            restart_existing(config, proxy)
            ensure_gateway(config)
        (state / 'allowlist.txt').write_text(text)
    except Exception:
        (state / 'squid.conf').write_text(old_policy)
        (state / 'allowlist.txt').write_text(old_text)
        if current and current['State']['Running']:
            restart_existing(config, proxy)
            ensure_gateway(config)
        raise
    print('Network rules updated. Development container and terminals preserved; gateway connections may need to reconnect.')


def initialize_models(config, preview=False):
    if 'model_providers' in config:
        model_providers.configure(config, 'preview' if preview else 'refresh')
        return True
    if not config.get('local_model_ports'):
        raise ValueError('Enable host-local models and choose their ports in Settings first')
    print('Discovering local models before opening an agent session…', flush=True)
    command = [config['engine'], 'exec', names(config)[0], 'node',
               '/opt/pi-local-model-manager/scripts/initialize-models.mjs']
    result = run(command + (['--preview'] if preview else []), capture=True, check=False, stderr=subprocess.PIPE)
    # Exit 3 is an expected disconnected state. Recognize the previous image's
    # exact diagnostic too, so an existing sandbox needs no disruptive rebuild.
    disconnected = result.returncode == 3 or (result.returncode == 1 and
        any(line.startswith('No usable local model was discovered.') for line in result.stderr.splitlines()))
    if result.stdout:
        print(result.stdout, end='' if result.stdout.endswith('\n') else '\n', flush=True)
    if disconnected:
        print('Model status: Not connected. The sandbox is ready; model chat is not available yet.', flush=True)
        print('Start the model server on the ports in Settings, then choose Refresh models in this manager.', flush=True)
        return False
    if result.returncode:
        raise ValueError('Model configuration failed: '+(result.stderr.strip() or f'exit {result.returncode}'))
    return True


def configure_models(config, preview=False):
    up(config, Path(config['state_path']))
    initialize_models(config, preview=preview)


def open_editor(config, state):
    dev = names(config)[0]
    current = inspect(config, dev)
    if not current or not current['State']['Running']:
        raise ValueError('Start the sandbox with up first')
    if options(config.get('options'))['browser']:
        browser_viewer.ensure_viewer(config['engine'], current['Id'])
    if not shutil.which('code'):
        raise ValueError('Install desktop VS Code and its code command first')
    # A separate user-data directory avoids inheriting host dotfiles extensions,
    # credential helpers, and user customizations into an agent workspace.
    if config.get('local_model_ports') or config.get('model_providers'):
        initialize_models(config)
    profile = state / 'vscode'
    settings = profile / 'User/settings.json'
    settings.parent.mkdir(parents=True, exist_ok=True)
    values = json.loads(settings.read_text()) if settings.exists() else {}
    values.update({'dev.containers.dockerPath': config['engine'],
                   'dev.containers.copyGitConfig': False,
                   'dev.containers.gitCredentialHelperConfigLocation': 'none',
                   'dev.containers.dockerCredentialHelper': False,
                   'dev.containers.mountWaylandSocket': False,
                   'dev.containers.defaultExtensions': [],
                   'extensions.autoUpdate': False,
                   'extensions.autoCheckUpdates': False,
                   'git.terminalAuthentication': False,
                   'chat.disableAIFeatures': True,
                   'workbench.startupEditor': 'none',
                   'workbench.welcomePage.experimentalOnboarding': False,
                   'workbench.welcomePage.walkthroughs.openOnInstall': False,
                   'window.restoreWindows': 'none',
                   'security.workspace.trust.enabled': True})
    values.setdefault('workbench.secondarySideBar.defaultVisibility', 'visible')
    settings.write_text(json.dumps(values, indent=2) + '\n')
    # View placement and Dev Containers' one-time attach acknowledgement use
    # native profile storage, not settings.json options.
    # Seed only a new profile; never edit a running editor's database or user layout.
    storage = profile / 'User/globalStorage/state.vscdb'
    if not storage.exists():
        storage.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(storage)) as database, database:
            database.execute('CREATE TABLE IF NOT EXISTS ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)')
            database.execute('INSERT OR IGNORE INTO ItemTable (key, value) VALUES (?, ?)',
                             ('views.customizations', json.dumps({
                                 'viewContainerLocations': {'workbench.view.extension.pendant-container': 2},
                                 'viewLocations': {}, 'viewContainerBadgeEnablementStates': {},
                             })))
            # Equivalent to "Got It" for attaching in this dedicated profile.
            # This does not grant workspace trust or acknowledge cloning warnings.
            database.execute('INSERT OR IGNORE INTO ItemTable (key, value) VALUES (?, ?)',
                             ('ms-vscode-remote.remote-containers', json.dumps({
                                 'userConfirmedAttachToContainerRequiresTrust': True,
                             })))
    attached = profile / 'User/globalStorage/ms-vscode-remote.remote-containers/nameConfigs' / (dev + '.json')
    attached.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(state / 'attached-container.json', attached)
    env = os.environ.copy()
    for key in ('SSH_AUTH_SOCK', 'GIT_ASKPASS', 'SSH_ASKPASS', 'VSCODE_IPC_HOOK_CLI'):
        env.pop(key, None)
    cmd = ['code', '--user-data-dir', str(profile), '--extensions-dir', str(state / 'vscode-extensions')]
    run(cmd + ['--install-extension', 'ms-vscode-remote.remote-containers'], env=env)
    # VS Code's attached-container authority is hex-encoded JSON.
    # Podman requires the actual name without Docker's inspect-output slash.
    authority = json.dumps({'containerName': dev}, separators=(',', ':')).encode().hex()
    run(cmd + ['--reuse-window', '--skip-welcome', '--folder-uri',
               f'vscode-remote://attached-container+{authority}/workspace'], env=env)


def main():
    parser = argparse.ArgumentParser(prog="vscode-pi-sandbox", description=__doc__)
    parser.add_argument('--state-dir', default=str(Path.home() / '.local/state/vscode-pi-sandbox'))
    sub = parser.add_subparsers(dest='command')
    parser.set_defaults(command='tui')
    sub.add_parser('tui', help='Open Sandbox Cockpit (requires Textual)')
    sub.add_parser('profiles', help='List available profiles')
    for kind in ('profile','provider'):
        package=sub.add_parser(kind,help='Manage installed '+kind+' packages')
        operations=package.add_subparsers(dest='package_action',required=True)
        operations.add_parser('list')
        add=operations.add_parser('add');add.add_argument('package_name');add.add_argument('source');add.add_argument('--ref')
        add.add_argument('--subdir', default='.', help='Plugin folder inside the source repository')
        for operation in ('update','remove','show'):
            item=operations.add_parser(operation);item.add_argument('package_name')
    listing = sub.add_parser('list', help='List saved sandboxes, container states, and workspace paths')
    listing.add_argument('--json', action='store_true', help='Structured saved inventory')
    new = sub.add_parser('create', help='Validate and save a new sandbox configuration')
    new.add_argument('name')
    new.add_argument('--profile', default='base', help='Installed profile name or custom profile directory (default: base)')
    new.add_argument('--workspace', required=True)
    new.add_argument('--model-provider', action='append', help='Installed provider name; repeat for multiple sources (default: local)')
    new.add_argument('--providers-file', help='JSON object mapping provider names to non-secret settings')
    new.add_argument('--pi-config',
                     help='Optional Pi agent directory: seed private models/settings/auth; share other resources read-only. Default: fresh private configuration')
    new.add_argument('--network', choices=['allowlist', 'unrestricted'], default='allowlist',
                     help='Outer container network policy (default: allowlist); unrestricted uses ordinary bridge networking')
    new.add_argument('--subagents', action='store_true',
                     help='Opt in to standard pi-subagents with the same review and Bash sandbox policy (default: disabled)')
    new.add_argument('--browser', action='store_true', help='Install optional Betterwright browser tools and dependencies (default: disabled)')
    policy = new.add_mutually_exclusive_group()
    policy.add_argument('--allowlist')
    policy.add_argument('--allow-domain', action='append', default=[], metavar='HOST:PORT',
                        help='Allow an exact hostname and port, whether it resolves publicly or privately; repeat as needed')
    new.add_argument('--env-file')
    new.add_argument('--engine', choices=['auto', 'podman', 'docker'], default='auto')
    new.add_argument('--memory', default=None, help='Optional memory limit, e.g. 8g; default: no explicit limit')
    new.add_argument('--skill-source', help='Additional skill Git repository URL')
    new.add_argument('--skill-path', default='.', help='Skill folder in the additional repository')
    new.add_argument('--advisor', action='append', choices=['codex', 'agy', 'claude'], default=[],
                     help='Add an advisor companion during creation; repeat for multiple advisors, sign in afterwards')
    new.add_argument('--options-file', help='JSON agent, skill and MCP settings')
    new.add_argument('--start', action='store_true', help='Build images and start after creation')
    new.add_argument('--local-model-ports', help='Host-loopback model ports, e.g. 8000 or 8000-8003; rootless Podman only')
    new.add_argument('--open', action='store_true', help='Open VS Code after startup; requires --start')
    descriptions = {
        'update': 'Validate, build and apply saved settings by recreating containers',
        'up': 'Resume containers and recover stale runtime or gateway state',
        'delete': 'Remove both containers, private volumes, and saved state; keep the host workspace',
        'configure': 'Check or refresh enabled model providers',
    }
    for command in ('update', 'build', 'up', 'down', 'delete', 'recreate', 'open', 'configure', 'shell', 'pi', 'exec', 'check', 'policy', 'network', 'advisor-login', 'advisor-check', 'ssh-import-key', 'ssh-unlock'):
        cmd = sub.add_parser(command, **({'help': descriptions[command]} if command in descriptions else {}))
        cmd.add_argument('name')
        if command == 'ssh-import-key':
            cmd.add_argument('--key-file', required=True)
        if command == 'advisor-login':
            cmd.add_argument('provider', choices=['codex', 'agy', 'claude'])
        if command == 'network':
            cmd.add_argument('--allowlist', required=True)
        if command == 'configure':
            cmd.add_argument('--preview', action='store_true', help='Read-only model discovery')
            cmd.add_argument('--provider', help='Configure one selected provider')
            cmd.add_argument('--key', action='store_true', help='Request a credential at a masked terminal prompt')
            cmd.add_argument('--key-stdin', action='store_true', help='Read a credential from stdin')
            cmd.add_argument('--status', action='store_true', help='Read provider status')
        if command == 'update':
            cmd.add_argument('--settings-file', required=True, help='JSON object with editable saved settings')
        if command in ('exec', 'pi'):
            cmd.add_argument('args', nargs=argparse.REMAINDER)
        if command == 'check':
            cmd.add_argument('--allowed-url', required=True)
        if command == 'policy':
            cmd.add_argument('--network', choices=['allowlist', 'unrestricted'], default='allowlist')
            cmd.add_argument('--allowlist')
        if command == 'recreate':
            cmd.add_argument('--profile', help='Select and build a new profile before replacing containers')
            cmd.add_argument('--browser', action=argparse.BooleanOptionalAction, default=None,
                             help='Enable or disable Betterwright; omitted preserves the saved choice')
            cmd.add_argument('--subagents', action=argparse.BooleanOptionalAction, default=None,
                             help='Enable or disable optional subagent orchestration; omitted preserves the saved choice')
    args = parser.parse_args()
    if args.command in ('profile','provider'):
        kind=args.command;action=args.package_action
        if action=='list':
            for name,description in registry.choices(kind).items(): print(f'{name}: {description}')
        elif action=='show':
            path=registry.resolve(kind,args.package_name)
            print(json.dumps(registry.installed(kind).get(args.package_name) or registry.manifest(kind,path),indent=2))
        elif action=='add':
            row=registry.add(kind,args.package_name,args.source,args.ref,subdir=args.subdir);print(f'Installed {row["name"]} at {row["commit"] or row["digest"]}')
        elif action=='update':
            row=registry.update(kind,args.package_name);print(f'Updated {row["name"]}. Existing sandboxes keep their saved snapshot until recreated.')
        else:
            registry.remove(kind,args.package_name);print('Registration removed. Existing sandboxes and their saved snapshots are preserved.')
        return
    if args.command == 'tui':
        from .sandbox_tui import launch
        launch(Path(args.state_dir).expanduser().resolve())
        return
    if args.command == 'list':
        list_sandboxes(Path(args.state_dir).expanduser().resolve(), **({'structured': True} if args.json else {}))
        return
    if args.command == 'profiles':
        for name,description in registry.choices('profile').items(): print(f'{name}: {description}')
        return
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,39}', args.name):
        parser.error('Name must be 1-40 lowercase letters, digits, or hyphens')
    state = Path(args.state_dir).expanduser().resolve() / args.name
    if args.command == 'create':
        if args.open and not args.start:
            parser.error('--open requires --start')
        create(args, state)
        if args.start:
            config = json.loads((state / 'config.json').read_text())
            build(config)
            up(config, state)
            if args.open:
                open_editor(config, state)
            elif config.get('local_model_ports') or config.get('model_providers'):
                initialize_models(config)
        return
    if args.command == 'delete' and not (state / 'config.json').exists():
        delete_incomplete(state)
        return
    config = json.loads((state / 'config.json').read_text())
    if args.command == 'build':
        if not config.get('common'):
            config['common'] = snapshot_profile(common_profile(), state)
            (state / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
        build(config)
    elif args.command == 'ssh-import-key':
        sandbox_ssh.import_key(config, state, args.key_file)
    elif args.command == 'ssh-unlock':
        sandbox_ssh.unlock(config, state)
    elif args.command == 'advisor-check':
        sandbox_advisors.check(config, state)
    elif args.command == 'advisor-login':
        sandbox_advisors.login(config, state, args.provider)
    elif args.command == 'up':
        up(config, state)
    elif args.command == 'down':
        down(config)
    elif args.command == 'delete':
        delete(config, state)
    elif args.command == 'update':
        apply_settings(config, state, json.loads(Path(args.settings_file).read_text()))
    elif args.command == 'recreate':
        if args.subagents is not None:
            config['subagents'] = args.subagents
        if args.browser is not None:
            config['options'] = options({**config.get('options', {}), 'browser': args.browser})
        if args.profile or args.subagents is not None or args.browser is not None:
            profile = config.get('profile')
            if args.profile or not profile:
                profile = snapshot_profile(load_profile(args.profile) if args.profile else selected_profile(config), state)
            updated = dict(config, profile=profile, common=snapshot_profile(common_profile(), state))
            if 'model_providers' in config:
                updated['model_providers'] = model_providers.prepare({p['name']:p['settings'] for p in config['model_providers']}, state, saved=config['model_providers'], refresh=True)
            build(updated)
            config = updated
        (state / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
        down(config, remove=True)
        up(config, state)
    elif args.command == 'open':
        open_editor(config, state)
    elif args.command == 'configure':
        config['state_path'] = str(state)
        if 'model_providers' not in config:
            configure_models(config, preview=args.preview)
        else:
            if (args.key or args.key_stdin) and not args.provider:parser.error('Choose --provider when supplying a credential')
            secret=None
            if args.key:
                import getpass
                secret=getpass.getpass('Provider key: ')
            elif args.key_stdin:
                secret=sys.stdin.read(65537).strip()
                if len(secret)>65536:parser.error('Credential input too large')
            up(config,state)
            model_providers.configure(config,'status' if args.status else 'preview' if args.preview else 'refresh',args.provider,secret)
    elif args.command == 'network':
        update_network(config, state, Path(args.allowlist).expanduser().read_text())
    elif args.command == 'policy':
        if args.network == 'unrestricted' and args.allowlist:
            parser.error('--network unrestricted cannot be combined with --allowlist')
        if args.network == 'allowlist' and not args.allowlist:
            parser.error('--allowlist is required for allowlist networking')
        text = Path(args.allowlist).expanduser().read_text() if args.allowlist else ''
        rules = parse_rules(text)
        if args.network == 'allowlist' and config.get('pi_config'):
            validate_models(Path(config['pi_config']), rules, strict=False)
        down(config, remove=True)
        config['network'] = args.network
        (state / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
        (state / 'allowlist.txt').write_text(text)
        (state / 'squid.conf').write_text(squid_config(rules))
        up(config, state)
    else:
        dev = names(config)[0]
        if args.command == 'check':
            source = (ROOT / 'checks/check_inside.py').read_text()
            run([config['engine'], 'exec', '-i', dev, 'python3', '-', args.allowed_url], input=source)
            if options(config.get('options'))['browser']:
                run([config['engine'], 'exec', dev, 'node', '/opt/betterwright/check.mjs', args.allowed_url])
        else:
            command = ['bash'] if args.command == 'shell' else getattr(args, 'args', [])
            if command[:1] == ['--']:
                command = command[1:]
            if args.command == 'pi':
                command = ['pi'] + command
            if not command:
                parser.error('exec requires a command after the sandbox name')
            tty = ['-it'] if sys.stdin.isatty() else ['-i']
            run([config['engine'], 'exec'] + tty + [dev] + command)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Interrupted.', file=sys.stderr)
        sys.exit(130)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
