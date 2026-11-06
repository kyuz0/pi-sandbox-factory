"""Write shared Pi/Pendant search settings; accept an optional key on stdin."""
import hashlib
import json
import os
from pathlib import Path
import sys

os.umask(0o077)
agent = Path('/home/node/.pi/agent')
selection = json.loads(Path('/opt/sandbox/options.json').read_text()).get('web_access') or {}
if not selection.get('enabled'):
    raise SystemExit(0)
identity = hashlib.sha256(json.dumps([selection['service'], selection.get('endpoint', '')]).encode()).hexdigest()
key_path = agent / 'sandbox-web-keys.json'
config_path = agent / 'web-search.json'
for path in (key_path, config_path):
    if path.is_symlink():
        raise ValueError('Search configuration must be a regular file')
keys = json.loads(key_path.read_text()) if key_path.exists() else {}
if '--key-stdin' in sys.argv:
    key = sys.stdin.read(16385).strip()
    if len(key) > 16384 or any(ord(c) < 32 or ord(c) == 127 for c in key):
        raise ValueError('Invalid API key')
    if key:
        keys[identity] = key
    else:
        keys.pop(identity, None)
    temporary = key_path.with_suffix('.new')
    temporary.unlink(missing_ok=True)
    with temporary.open('x') as stream:
        json.dump(keys, stream)
    temporary.replace(key_path)
base = json.loads(Path('/opt/pi-security/config/web-search.json').read_text())
field = {'exa-api': 'exaApiKey', 'openai': 'openaiApiKey', 'brave': 'braveApiKey', 'tavily': 'tavilyApiKey'}.get(selection['service'])
if field and identity in keys:
    key = keys[identity]
    # Upstream supports executable credential sources; keys entered here are literals.
    base[field] = '$' + key if key.startswith(('!', '$')) else key
# Preserve advanced choices until the manager's managed settings change.
marker = agent / 'sandbox-web-config.json'
fingerprint = hashlib.sha256(json.dumps(base, sort_keys=True).encode()).hexdigest()
if marker.is_symlink():
    marker.unlink()
if '--key-stdin' in sys.argv or not marker.exists() or marker.read_text() != fingerprint or not config_path.exists():
    temporary = config_path.with_suffix('.new')
    temporary.unlink(missing_ok=True)
    with temporary.open('x') as stream:
        json.dump(base, stream, indent=2)
        stream.write('\n')
    temporary.replace(config_path)
    if marker.is_symlink():
        marker.unlink()
    marker.write_text(fingerprint)
print('Web access configured. Reload an open Pi or Pendant session to use the settings.')
