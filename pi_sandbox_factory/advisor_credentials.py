"""One-time host sign-in copies into the isolated advisor companion."""
import json
import os
from pathlib import Path
import subprocess

from . import sandbox_advisors

LABELS = {'codex': 'Codex (OpenAI)', 'claude': 'Claude (Anthropic)', 'agy': 'Antigravity (Google)'}


def read_host(provider):
    """Read only the selected provider's login; never import settings or sessions."""
    try:
        if provider == 'agy':
            result = subprocess.run(['secret-tool', 'lookup', 'service', 'gemini', 'username', 'antigravity'],
                                    capture_output=True, text=True, timeout=20)
            if result.returncode or not result.stdout.strip():
                raise ValueError('Sign in to Antigravity on the host and unlock its keyring first.')
            value = json.loads(result.stdout)
            if not isinstance(value, dict) or not value.get('token'):
                raise ValueError('The host Antigravity sign-in format is not supported.')
            return json.dumps(value)
        if provider == 'codex':
            home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
            value = json.loads((home / 'auth.json').read_text())
            if not isinstance(value, dict) or not isinstance(value.get('tokens'), dict) or not value['tokens'].get('access_token'):
                raise ValueError('Sign in to Codex with a ChatGPT account using file credential storage first.')
            return json.dumps({k: value[k] for k in ('auth_mode', 'tokens', 'last_refresh') if k in value})
        if provider == 'claude':
            home = Path(os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude')))
            value = json.loads((home / '.credentials.json').read_text())
            if not isinstance(value, dict) or not isinstance(value.get('claudeAiOauth'), dict) or not value['claudeAiOauth'].get('accessToken'):
                raise ValueError('Sign in to Claude on the host with a subscription first.')
            return json.dumps({'claudeAiOauth': value['claudeAiOauth']})
        raise ValueError('Choose Codex, Claude or Antigravity.')
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        raise ValueError(f'Cannot read the host {LABELS[provider]} sign-in. Use the advisor sign-in button instead.') from None


_WRITE_FILE = """
import os, sys, tempfile
from pathlib import Path
path = Path(sys.argv[1])
path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
fd, temporary = tempfile.mkstemp(dir=path.parent)
try:
    with os.fdopen(fd, 'w') as stream:
        stream.write(sys.stdin.read())
    os.replace(temporary, path)
finally:
    Path(temporary).unlink(missing_ok=True)
"""


def import_from_host(config, state, provider):
    if provider not in LABELS or provider not in config.get('advisors', {}).get('providers', []):
        raise ValueError('Add this advisor before copying its host sign-in.')
    payload = read_host(provider)
    sandbox_advisors.up(config, state)
    command = [config['engine'], 'exec', '-i', sandbox_advisors.names(config)[0]]
    if provider == 'agy':
        command += ['secret-tool', 'store', '--label=Antigravity CLI',
                    'service', 'gemini', 'username', 'antigravity']
    else:
        target = '/home/node/.codex/auth.json' if provider == 'codex' else '/home/node/.claude/.credentials.json'
        command += ['python3', '-c', _WRITE_FILE, target]
    try:
        result = subprocess.run(command, input=payload, text=True, capture_output=True, timeout=30)
        if result.returncode:
            raise ValueError('Could not save the sign-in in the advisor container. Try again or use its sign-in button.')
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('Could not reach the advisor credential store. Try again or use its sign-in button.') from None
