#!/usr/bin/env python3
"""Read token status or update private Slack credentials through stdin."""
import json
import os
from pathlib import Path
import sys


def credentials_path(home):
    directory = home / '.pi/agent/communications'
    if any(part.is_symlink() for part in (home / '.pi', home / '.pi/agent', directory)):
        raise ValueError('Credential directories must not be symlinks')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    path = directory / 'slack.json'
    if path.is_symlink():
        raise ValueError('Credential file must not be a symlink')
    return path


def update(home, changes=None):
    path = credentials_path(home)
    value = json.loads(path.read_text()) if path.exists() else {}
    if changes is not None:
        if not isinstance(changes, dict) or set(changes) - {'botToken', 'userToken'}:
            raise ValueError('Unknown Slack credential')
        for key, token in changes.items():
            prefix = 'xoxb-' if key == 'botToken' else 'xoxp-'
            if not isinstance(token, str) or len(token) > 16000 or (token and
                    (not token.startswith(prefix) or any(c.isspace() for c in token))):
                raise ValueError('Invalid Slack token format')
        value.update(changes)
        temporary = path.with_suffix('.new')
        temporary.unlink(missing_ok=True)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(value, output)
        temporary.replace(path)
    return {key: bool(value.get(key)) for key in ('botToken', 'userToken')}


if __name__ == '__main__':
    try:
        data = None if '--status' in sys.argv else json.loads(sys.stdin.read(32769))
        print(json.dumps(update(Path.home(), data)))
    except (ValueError, OSError):
        sys.exit('Could not access Slack credentials; check token format and private storage')
