"""Project managed search providers and private keys into Pi's configuration."""
import hashlib
import json
import os
from pathlib import Path
import sys

FIELDS = {'exa': 'exaApiKey', 'openai': 'openaiApiKey', 'brave': 'braveApiKey', 'tavily': 'tavilyApiKey'}


def identity(name, row):
    return hashlib.sha256(json.dumps([name, row.get('endpoint', '')]).encode()).hexdigest()


def write(path, value):
    if path.is_symlink():
        raise ValueError('Search configuration must be a regular file')
    temporary = path.with_suffix('.new')
    temporary.unlink(missing_ok=True)
    with open(temporary, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as stream:
        json.dump(value, stream, indent=2)
    temporary.replace(path)


def configure(agent, runtime, updates=None, status_only=False, export_keys=False):
    selection = json.loads((runtime / 'web-providers.json').read_text())
    key_path = agent / 'sandbox-web-keys.json'
    config_path = agent / 'web-search.json'
    for path in (key_path, config_path):
        if path.is_symlink():
            raise ValueError('Search configuration must be a regular file')
    keys = json.loads(key_path.read_text()) if key_path.exists() else {}
    providers = selection['providers']
    # Old keyed Exa and keyless Exa now share one provider identity.
    for name, row in providers.items():
        if name == 'exa' and identity(name, row) not in keys:
            old = identity('exa-api', row)
            if old in keys:
                keys[identity(name, row)] = keys.pop(old)
    if updates is not None:
        if not isinstance(updates, dict):
            raise ValueError('Expected provider names and API keys')
        for name, key in updates.items():
            if name not in providers or name not in FIELDS:
                raise ValueError('Choose a configured provider that accepts an API key')
            if not isinstance(key, str) or len(key) > 16384 or any(ord(c) < 32 or ord(c) == 127 for c in key):
                raise ValueError('Invalid API key')
        for name, key in updates.items():
            token = identity(name, providers[name])
            if key.strip():
                keys[token] = key.strip()
            else:
                keys.pop(token, None)
        write(key_path, keys)
    statuses = {name: bool(keys.get(identity(name, row))) for name, row in providers.items()}
    if export_keys:
        return {name: {'endpoint': row['endpoint'], 'key': keys[identity(name, row)]}
                for name, row in providers.items() if statuses[name]}
    if status_only:
        return statuses
    base = json.loads((runtime / 'web-search.json').read_text())
    active = [name for name, row in providers.items()
              if selection['enabled'] and selection['mode'] in ('auto', name)
              and (name == 'exa' or (bool(row['endpoint']) if name == 'searxng' else (row['has_key'] and statuses[name])))]
    base['webSearch']['allowedProviders'] = active
    # Remove settings for inactive providers, including credentials saved for later use.
    for field in (*FIELDS.values(), 'openaiResponsesUrl', 'openaiSearchModel', 'searxngBaseUrl'):
        base.pop(field, None)
    for name in active:
        row = providers[name]
        if name == 'searxng':
            base['searxngBaseUrl'] = row['endpoint']
        if name == 'openai':
            if row['endpoint']:
                base['openaiResponsesUrl'] = row['endpoint']
            if row['model']:
                base['openaiSearchModel'] = row['model']
        key = keys.get(identity(name, row))
        if key and name in FIELDS and row['has_key']:
            # Upstream accepts executable credential sources; UI keys are literal strings.
            base[FIELDS[name]] = '$' + key if key.startswith(('!', '$')) else key
    marker = agent / 'sandbox-web-config.json'
    fingerprint = hashlib.sha256(json.dumps(base, sort_keys=True).encode()).hexdigest()
    if marker.is_symlink():
        raise ValueError('Search configuration must be a regular file')
    if updates is not None or not marker.exists() or marker.read_text().strip().strip(chr(34)) != fingerprint or not config_path.exists():
        write(config_path, base)
        write(marker, fingerprint)
    return statuses


if __name__ == '__main__':
    os.umask(0o077)
    updates = None
    if '--keys-stdin' in sys.argv:
        raw = sys.stdin.read(100001)
        if len(raw) > 100000:
            raise ValueError('Search credentials too large')
        updates = json.loads(raw)
    statuses = configure(Path('/home/node/.pi/agent'), Path('/opt/pi-security/config'), updates, '--status' in sys.argv, '--export-keys' in sys.argv)
    print(json.dumps(statuses))
