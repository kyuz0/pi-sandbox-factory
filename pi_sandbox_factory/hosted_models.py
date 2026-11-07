"""Configure native Pi models through the isolated inference companion."""
import copy
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

PROVIDERS = {'openrouter': 'OpenRouter', 'together': 'Together', 'azure': 'Azure / Foundry',
             'amazon-bedrock': 'AWS Bedrock'}
ENDPOINTS = {'openrouter': 'https://openrouter.ai/api/v1', 'together': 'https://api.together.xyz/v1'}


def validate(value):
    value = dict(value)
    provider = value.get('provider')
    if provider not in PROVIDERS:
        raise ValueError('Choose a supported provider.')
    for field in ('key', 'access_key', 'secret_key', 'session_token'):
        text = value.get(field, '').strip()
        if any(c in text for c in '\r\n\0') or text.startswith(('!', '$')):
            raise ValueError('Enter a literal credential, not a command or environment reference.')
        value[field] = text
    if provider == 'azure':
        url = urlsplit(value.get('endpoint', '').strip())
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('Enter the Azure HTTPS endpoint without credentials or a query string.')
        try:
            port = url.port
        except ValueError:
            raise ValueError('Invalid endpoint port.') from None
        if port not in (None, 443):
            raise ValueError('Use the Azure HTTPS endpoint on port 443.')
        value['endpoint'] = url.geturl().rstrip('/')
    if provider == 'amazon-bedrock':
        if not re.fullmatch(r'[a-z]{2}(?:-[a-z]+)+-\d+', value.get('region', '')):
            raise ValueError('Enter the AWS region, for example eu-west-1.')
        if value.get('method') not in ('bearer', 'iam'):
            raise ValueError('Choose bearer token or IAM credentials.')
        if bool(value['access_key']) != bool(value['secret_key']):
            raise ValueError('Enter both the AWS access key and secret key.')
        if value['session_token'] and not value['access_key']:
            raise ValueError('Enter all three temporary AWS credential fields together.')
    return value


def connection(value):
    """Only nonsecret routing information belongs in the host configuration."""
    value = validate(value)
    provider = value['provider']
    if provider == 'azure':
        return {'endpoint': value['endpoint']}
    if provider == 'amazon-bedrock':
        return {'region': value['region'], 'method': value['method']}
    return {}


def destinations(connections):
    # Inference goes through its companion. Pi fetches public model metadata here.
    return [('pi.dev', 443)] if connections else []


def request(config, action, **values):
    from . import sandbox
    dev = sandbox.names(config)[0]
    info = sandbox.inspect(config, dev)
    if not info or not info.get('State', {}).get('Running'):
        raise ValueError('Start the sandbox before configuring models.')
    script = Path(__file__).with_name('providers').joinpath('hosted-models.mjs').read_text()
    try:
        result = subprocess.run([config['engine'], 'exec', '-i', '--user', 'node', dev,
                                 'node', '--input-type=module', '-e', script],
                                input=json.dumps({'action': action, **values}), text=True,
                                capture_output=True, timeout=65)
    except subprocess.TimeoutExpired:
        raise ValueError('Provider operation timed out. Check connectivity and retry.') from None
    try:
        reply = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise ValueError('Could not read Pi configuration. Check that the sandbox is running.') from None
    if reply.get('error'):
        raise ValueError(reply['error'])
    if result.returncode:
        raise ValueError('Provider operation failed.')
    return reply


def save(config, state, value):
    from . import inference, sandbox
    from .sandbox_options import write_json
    value = validate(value)
    request(config, 'status')  # Check the client container before changing a connection.
    state = Path(state)
    updated = copy.deepcopy(config)
    provider = value['provider']
    saved = connection(value)
    updated.setdefault('hosted_connections', {})[provider] = saved
    credentials = ({'accessKeyId':value['access_key'], 'secretAccessKey':value['secret_key'], 'sessionToken':value['session_token']}
                   if provider == 'amazon-bedrock' and value['method'] == 'iam' else {'key':value['key']})
    route = inference.routes(updated)[provider]
    try:
        inference.up(updated, state)
        inference.credentials(updated, state, {'id':provider, 'origin':route['origin'], 'auth':route['auth']['type'], 'credentials':credentials})
    except Exception as failure:
        try:
            if inference.enabled(config): inference.up(config, state)
            else: inference.down(updated, remove=True)
        except Exception:
            raise ValueError('Could not configure the inference service or restore its previous connection. Start the sandbox and retry.') from failure
        raise
    # Save a recoverable connection before configuring the client; credentials stay in its companion.
    write_json(state / 'config.json', updated)
    if sandbox.network_mode(updated) == 'allowlist':
        sandbox.update_network(updated, state, (state / 'allowlist.txt').read_text())
    reply = request(updated, 'configure', provider=provider, endpoint=inference.client_url(provider,saved), region=saved.get('region',''))
    return {**reply, **saved}


def remove(config, state, provider):
    from . import inference, sandbox
    from .sandbox_options import write_json
    state = Path(state)
    inference.up(config, state)
    inference.credentials(config, state, {'id':provider, 'remove':True})
    updated = copy.deepcopy(config)
    updated.get('hosted_connections', {}).pop(provider, None)
    write_json(state / 'config.json', updated)
    if inference.enabled(updated): inference.up(updated, state)
    else: inference.down(config, remove=True)
    if sandbox.network_mode(updated) == 'allowlist':
        sandbox.update_network(updated, state, (state / 'allowlist.txt').read_text())
    request(updated, 'remove', provider=provider)


def select(config, provider, model, deployment='', profile_id='', test=False):
    if provider == 'azure' and not deployment:
        raise ValueError('Enter the Azure deployment name for this model.')
    if profile_id:
        if any(c.isspace() for c in profile_id) or any(c in profile_id for c in '\0'):
            raise ValueError('Enter the exact Bedrock model or inference profile ID.')
        if profile_id.startswith('arn:'):
            parts = profile_id.split(':', 5)
            if len(parts) != 6 or parts[2] != 'bedrock' or parts[3] != config.get('hosted_connections', {}).get(provider, {}).get('region'):
                raise ValueError('The profile ARN must use the configured AWS region.')
    return request(config, 'test' if test else 'select', provider=provider, model=model, deployment=deployment, profile_id=profile_id)
