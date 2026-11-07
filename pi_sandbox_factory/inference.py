"""Manage the credential companion; the development container receives only its socket."""
import hashlib
import fcntl
import json
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit

PORT = 19431
SENTINEL = 'factory-inference'


def names(config):
    name = 'pi-sandbox-factory-' + config['name'] + '-inference'
    return name, name + '-socket', name + '-keys'


def routes(config):
    """Declare the exact upstream operations available to this sandbox."""
    result = {}
    def op(method, path, query=None):
        return {'method': method, 'path': path, **({'query': query} if query else {})}
    for provider, value in config.get('hosted_connections', {}).items():
        auth = {'type': 'bearer'}
        if provider == 'openrouter':
            origin = 'https://openrouter.ai'
            operations = [op('POST', '/api/v1/chat/completions'), op('POST', '/api/v1/responses'),
                          op('POST', '/api/v1/messages', {'beta': ['true']}),
                          {**op('POST', '/api/v1/v1/messages', {'beta': ['true']}), 'upstreamPath': '/api/v1/messages'},
                          op('GET', '/api/v1/models'), op('GET', '/api/v1/models/user')]
        elif provider == 'together':
            origin = 'https://api.together.xyz'
            operations = [op('POST', '/v1/chat/completions'), op('GET', '/v1/models')]
        elif provider == 'azure':
            endpoint = urlsplit(value['endpoint'])
            origin = f'{endpoint.scheme}://{endpoint.netloc}'
            prefix = endpoint.path.rstrip('/') or '/openai/v1'
            auth = {'type': 'header', 'header': 'api-key'}
            operations = [op('POST', prefix + '/responses', {'api-version': ['v1']}),
                          op('POST', prefix + '/chat/completions', {'api-version': ['v1']}),
                          op('GET', prefix + '/models', {'api-version': ['v1']})]
        elif provider == 'amazon-bedrock':
            region = value['region']
            suffix = 'amazonaws.com.cn' if region.startswith('cn-') else 'amazonaws.com'
            origin = f'https://bedrock-runtime.{region}.{suffix}'
            if value.get('method') == 'iam':
                auth = {'type': 'sigv4', 'region': region}
            operations = [op('POST', '/model/{model}/converse-stream')]
        else:
            raise ValueError('Unknown hosted provider.')
        result[provider] = {'origin': origin, 'auth': auth, 'operations': operations}
    for row in config.get('model_providers', []):
        route = row['manifest'].get('inference')
        if route:
            if row['name'] in result:
                raise ValueError('Duplicate inference connection: ' + row['name'])
            result[row['name']] = route
    return result


def enabled(config):
    return bool(routes(config))


def image():
    from . import sandbox
    source = sandbox.ROOT / 'containers/inference'
    digest = hashlib.sha256(b''.join((source / f).read_bytes() for f in
        ('Dockerfile', 'package.json', 'package-lock.json', 'broker.mjs', 'credentials.mjs'))).hexdigest()[:16]
    return 'localhost/pi-sandbox-factory-inference:' + digest


def build(config):
    if not enabled(config):
        return
    from . import sandbox
    tag = image()
    if subprocess.run([config['engine'], 'image', 'inspect', tag], capture_output=True).returncode:
        result = subprocess.run([config['engine'], 'build', '-t', tag,
            str(sandbox.ROOT / 'containers/inference')], capture_output=True, text=True)
        if result.returncode:
            raise ValueError('Could not build the inference service. Check registry access and retry.')


def check_ownership(config):
    from . import sandbox
    worker, *volumes = names(config)
    sandbox.inspect(config, worker)
    for volume in volumes:
        result = subprocess.run([config['engine'], 'volume', 'inspect', volume], capture_output=True, text=True)
        if not result.returncode and json.loads(result.stdout)[0].get('Labels', {}).get(sandbox.LABEL) != config['name']:
            raise ValueError('Refusing to manage unrelated inference volume: ' + volume)


def up(config, state):
    from . import sandbox
    from .sandbox_options import write_json
    worker, socket, keys = names(config)
    check_ownership(config)
    def volume(name):
        if subprocess.run([config['engine'], 'volume', 'inspect', name], capture_output=True).returncode:
            subprocess.run([config['engine'], 'volume', 'create', '--label', f'{sandbox.LABEL}={config["name"]}', name], check=True, capture_output=True)
    volume(socket)
    if not enabled(config):
        return
    build(config)
    # Validate with the same parser used by the service before replacing a working route.
    validation = subprocess.run([config['engine'], 'run', '--rm', '-i', '--network=none',
        '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges', image(),
        'node', '--input-type=module', '-e',
        "import {compileRoutes} from '/app/broker.mjs';let text='';for await(const chunk of process.stdin)text+=chunk;try{compileRoutes(JSON.parse(text));}catch{process.exitCode=1;}"],
        input=json.dumps(routes(config)), text=True, capture_output=True)
    if validation.returncode:
        raise ValueError('Invalid inference routes. Check the provider endpoint and its declared operations.')
    volume(keys)
    target = Path(state) / 'inference'
    target.mkdir(exist_ok=True, mode=0o700)
    write_json(target / 'routes.json', routes(config))
    # Routes contain no keys and are readable by the mapped container user.
    (target / 'routes.json').chmod(0o644)
    identity = hashlib.sha256((json.dumps(routes(config), sort_keys=True) + image()).encode()).hexdigest()
    existing = sandbox.inspect(config, worker)
    if existing and existing.get('Config',{}).get('Labels',{}).get('io.pi-sandbox-factory.inference') != identity:
        subprocess.run([config['engine'], 'rm', '-f', worker], check=True, capture_output=True)
        existing = None
    if existing:
        sandbox.resume_existing(config, worker, existing)
    else:
        args = [config['engine'], 'run', '-d', '--name', worker, '--label', f'{sandbox.LABEL}={config["name"]}',
                '--label', 'io.pi-sandbox-factory.inference=' + identity,
                '--cap-drop=ALL', '--security-opt=no-new-privileges',
                '--read-only', '--memory=256m', '--pids-limit=64', '--user', f'{config["uid"]}:{config["gid"]}',
                '-v', socket + ':/run/inference:z', '-v', keys + ':/private:z', '-v', str(target) + ':/config:ro,Z']
        if config['engine'] == 'podman':
            args += ['--userns=keep-id:uid=1000,gid=1000']
        subprocess.run(args + [image()], check=True, capture_output=True)
    for _ in range(80):
        result = subprocess.run([config['engine'], 'exec', worker, 'node', '-e',
            "const http=require('http');const r=http.get({socketPath:'/run/inference/proxy.sock',path:'/'},s=>{s.resume();s.on('end',()=>process.exit(s.statusCode===404?0:1));});r.on('error',()=>process.exit(1));r.setTimeout(1000,()=>process.exit(1));"], capture_output=True)
        if not result.returncode:
            return
        time.sleep(.25)
    raise ValueError('Inference service did not start. Check its container logs.')


def credentials(config, state, request):
    from . import sandbox
    worker = names(config)[0]
    info = sandbox.inspect(config, worker)
    if not info or not info.get('State', {}).get('Running'):
        raise ValueError('Start the inference service before configuring credentials.')
    # Kernel locks release on process exit, including interrupted imports.
    with (Path(state) / 'inference' / 'credentials.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = subprocess.run([config['engine'], 'exec', '-i', worker, 'node', '/app/credentials.mjs', '/private/credentials.json'],
                                input=json.dumps(request), text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError('Could not update inference credentials.')
    return json.loads(result.stdout)


def mounts(config):
    return ['-v', names(config)[1] + ':/run/inference:ro']


def down(config, remove=False):
    from . import sandbox
    check_ownership(config)
    worker = names(config)[0]
    if sandbox.inspect(config, worker):
        subprocess.run([config['engine'], 'rm', '-f', worker] if remove else [config['engine'], 'stop', worker], check=True, capture_output=True)


def delete_volumes(config):
    check_ownership(config)
    for volume in names(config)[1:]:
        if not subprocess.run([config['engine'], 'volume', 'inspect', volume], capture_output=True).returncode:
            subprocess.run([config['engine'], 'volume', 'rm', volume], check=True, capture_output=True)


def client_url(provider, connection):
    prefix = {'openrouter': '/api/v1', 'together': '/v1', 'amazon-bedrock': ''}.get(provider)
    if provider == 'azure':
        prefix = urlsplit(connection['endpoint']).path.rstrip('/') or '/openai/v1'
    return f'http://127.0.0.1:{PORT}/r/{provider}' + prefix
