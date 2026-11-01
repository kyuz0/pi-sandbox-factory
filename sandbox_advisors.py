"""Optional advisor companion: private login state, bounded socket API, separate egress."""
import json
import hashlib
import sandbox_extensions
from pathlib import Path
import re
import subprocess
import sys
import time

HOSTS = {
    'codex': ['auth.openai.com:443', 'chatgpt.com:443', 'api.openai.com:443'],
    'agy': ['accounts.google.com:443', 'oauth2.googleapis.com:443',
            'cloudcode-pa.googleapis.com:443', 'daily-cloudcode-pa.googleapis.com:443',
            'antigravity.google:443', 'antigravity.google.com:443', 'aicode.googleapis.com:443',
            'www.googleapis.com:443', 'auth.cloud.google:443'],
}


def validate(value):
    if not isinstance(value, dict) or set(value) - {'providers', 'agy_model', 'agy_quota_group', 'agy_effort', 'extra_hosts', 'max_calls'}:
        raise ValueError('Invalid advisor settings')
    providers = value.get('providers', [])
    if not isinstance(providers, list) or any(not isinstance(p, str) or p not in HOSTS for p in providers) or len(set(providers)) != len(providers):
        raise ValueError('Choose Codex and/or Antigravity')
    result = dict(value, providers=providers)
    if 'agy' in providers:
        model = value.get('agy_model', '')
        if not isinstance(model, str):
            raise ValueError('Antigravity model ID must be text')
        if model and not re.fullmatch(r'gemini[a-zA-Z0-9._-]{1,120}', model, re.I):
            raise ValueError('Enter the exact Gemini model ID from agy models')
        if model and (not isinstance(value.get('agy_quota_group'), str) or not value['agy_quota_group'].strip()):
            raise ValueError('Enter the Antigravity quota group shown by /usage')
        if value.get('agy_effort', 'medium') not in ('low', 'medium', 'high'):
            raise ValueError('Antigravity effort must be low, medium or high')
    calls = value.get('max_calls')
    if calls is not None and (type(calls) is not int or calls < 1):
        raise ValueError('Advisor calls per session must be a positive integer or null')
    import sandbox as core
    if not isinstance(value.get('extra_hosts', ''), str):
        raise ValueError('Additional advisor hosts must be text')
    core.parse_rules(value.get('extra_hosts', ''))
    return result


def enabled(config):
    return bool(config.get('advisors', {}).get('providers'))


def names(config):
    prefix = 'local-ai-sandbox-' + config['name'] + '-advisor'
    return prefix, prefix + '-proxy', prefix + '-socket', prefix + '-home', prefix + '-egress'


def source_path(config):
    import sandbox as core
    saved = Path(config.get('common', {}).get('path', core.ROOT / 'containers/dev'))
    return saved if (saved / 'extensions.lock.json').exists() else core.ROOT / 'containers/dev'


def image(config):
    import sandbox as core
    lock = sandbox_extensions.read_lock(source_path(config))['pi-advisor']
    digest = core.tree_digest(core.ROOT / 'containers/advisor') + hashlib.sha256(json.dumps(lock, sort_keys=True).encode()).hexdigest()[:12]
    return f'localhost/local-ai-sandbox-advisor:{config["uid"]}-{config["gid"]}-{digest}'


def build(config):
    if not enabled(config):
        return
    import sandbox as core
    with sandbox_extensions.build_contexts(source_path(config), names=['pi-advisor']) as contexts:
        core.run([config['engine'], 'build', '-t', image(config), *contexts, '-f', core.ROOT / 'containers/advisor/Dockerfile',
                  '--build-arg', f'USER_UID={config["uid"]}', '--build-arg', f'USER_GID={config["gid"]}', core.ROOT / 'containers'])


def provider_config(settings):
    providers = {}
    for provider in settings['providers']:
        if provider == 'codex':
            providers[provider] = {'executable': '/usr/local/bin/advisor-codex', 'codexHome': '/home/node/.codex', 'sharedHome': True}
        else:
            providers[provider] = {'executable': '/usr/local/bin/agy', 'models': {'default': {
                'id': settings.get('agy_model', ''), 'quotaGroup': settings.get('agy_quota_group', ''), 'effort': settings.get('agy_effort', 'medium')}}}
            if not settings.get('agy_model'):
                providers[provider].update(models={}, setupOnly=True)
    return {'provider': settings['providers'][0], 'providers': providers,
            'billingMode': 'subscription', 'containerRuntime': True, 'maxCallsPerSession': settings.get('max_calls')}


def rules(settings):
    import sandbox as core
    text = '\n'.join(host for provider in settings['providers'] for host in HOSTS[provider]) + '\n' + settings.get('extra_hosts', '')
    return list(dict.fromkeys(core.parse_rules(text)))


def check_ownership(config):
    import sandbox as core
    for name in names(config)[:2]:
        core.inspect(config, name)
    for volume in names(config)[2:]:
        result = core.run([config['engine'], 'volume', 'inspect', volume], capture=True, check=False, stderr=subprocess.DEVNULL)
        if result.returncode == 0 and (json.loads(result.stdout)[0].get('Labels') or {}).get(core.LABEL) != config['name']:
            raise ValueError(f'Refusing to manage unrelated advisor volume: {volume}')


def up(config, state):
    if not enabled(config):
        return
    import sandbox as core
    settings = validate(config['advisors'])
    check_ownership(config)
    worker, proxy, socket, home, egress = names(config)
    engine = config['engine']
    for volume in (socket, home, egress):
        if core.run([engine, 'volume', 'inspect', volume], capture=True, check=False, stderr=subprocess.DEVNULL).returncode:
            core.run([engine, 'volume', 'create', '--label', f'{core.LABEL}={config["name"]}', volume])
    target = state / 'advisor'
    target.mkdir(exist_ok=True, mode=0o700)
    # Host directory is private; config itself is readable by the container user.
    (target / 'config.json').write_text(json.dumps(provider_config(settings), indent=2) + '\n')
    (target / 'config.json').chmod(0o644)
    (target / 'squid.conf').write_text(core.squid_config(rules(settings)))
    for name in (proxy, worker):
        existing = core.inspect(config, name)
        if existing:
            core.resume_existing(config, name, existing)
            continue
        args = [engine, 'run', '-d', '--name', name, '--label', f'{core.LABEL}={config["name"]}',
                '--security-opt=no-new-privileges', '--cap-drop=ALL', '--pids-limit=256']
        if name == proxy:
            args += ['--cap-add=CHOWN', '--cap-add=SETUID', '--cap-add=SETGID', '--cap-add=DAC_OVERRIDE', '--memory=256m',
                     '-v', f'{target / "squid.conf"}:/etc/squid/sandbox.conf:ro,Z', '-v', f'{egress}:/run/egress:z', core.image_names(config)[1]]
        else:
            args += ['--network=none', '--memory=2g', '--security-opt=label=disable',
                     '--user', f'{config["uid"]}:{config["gid"]}',
                     '-v', f'{home}:/home/node', '-v', f'{socket}:/run/advisor',
                     '-v', f'{egress}:/run/egress:ro', '-v', f'{target / "config.json"}:/etc/advisor/config.json:ro']
            if engine == 'podman':
                args += ['--userns=keep-id:uid=1000,gid=1000']
            for key, value in core.RUNTIME_ENV.items():
                args += ['--env', f'{key}={value}']
            args += [image(config)]
        core.run(args)
    for _ in range(80):
        result = core.run([engine, 'exec', worker, 'sh', '-c', 'test -S /run/advisor/advisor.sock && test -S /run/advisor-bus/bus'],
                          capture=True, check=False, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            return
        time.sleep(.25)
    raise ValueError(f'Advisor did not become ready; inspect {engine} logs {worker}')


def mounts(config):
    if not enabled(config):
        return []
    return ['-v', f'{names(config)[2]}:/run/advisor:ro', '--env', 'PI_ADVISOR_SOCKET=/run/advisor/advisor.sock']


def down(config, remove=False):
    import sandbox as core
    check_ownership(config)
    for name in names(config)[:2]:
        if core.inspect(config, name):
            core.run([config['engine'], 'rm', '-f', name] if remove else [config['engine'], 'stop', name])


def delete_volumes(config):
    import sandbox as core
    check_ownership(config)
    for volume in names(config)[2:]:
        if core.run([config['engine'], 'volume', 'inspect', volume], capture=True, check=False, stderr=subprocess.DEVNULL).returncode == 0:
            core.run([config['engine'], 'volume', 'rm', volume])


def login(config, state, provider):
    if provider not in config.get('advisors', {}).get('providers', []):
        raise ValueError('Enable this provider in Settings → Advisors first')
    if not sys.stdin.isatty():
        raise ValueError('Advisor login requires an interactive terminal')
    import sandbox as core
    up(config, state)
    core.run([config['engine'], 'exec', '-it', names(config)[0], '/opt/advisor/login.sh', provider])


def check(config, state):
    if not enabled(config):
        raise ValueError('Enable a provider in Settings → Advisors first')
    import sandbox as core
    up(config, state)
    worker = names(config)[0]
    for provider in config['advisors']['providers']:
        print('\n' + ('Codex' if provider == 'codex' else 'Antigravity'), flush=True)
        commands = ([['advisor-codex', '-c', 'cli_auth_credentials_store="file"', 'login', 'status']]
                    if provider == 'codex' else [['agy', 'models'], ['agy', '-p', '/usage', '--output-format', 'json']])
        for command in commands:
            result = core.run([config['engine'], 'exec', worker] + command, check=False)
            if result.returncode:
                print('Not ready. Sign in to this provider and check its allowed destinations.', flush=True)
                break
