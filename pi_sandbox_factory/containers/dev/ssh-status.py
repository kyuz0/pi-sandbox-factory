#!/usr/bin/python3
"""Report managed SSH routing and agent availability without exposing key material."""
import json
import os
from pathlib import Path
import subprocess


def status(targets=Path('/etc/sandbox-ssh/targets.json')):
    if not targets.is_file():
        return {'state': 'not_configured', 'action': 'If this ran in the inner sandbox, rerun through bash_escalate when available. Otherwise configure SSH destinations in Factory Settings.'}, 2
    hosts = json.loads(targets.read_text())
    destinations = [{key: host[key] for key in ('alias', 'user', 'hostname', 'port')} for host in hosts]
    result = subprocess.run(['ssh-add', '-l'], capture_output=True, timeout=5,
                            env={**os.environ, 'SSH_AUTH_SOCK': '/run/ssh-access/agent.sock'})
    if result.returncode == 0:
        state, action, code = 'key_loaded', 'Use Git/SSH normally with a configured alias; repository permissions are checked by the server.', 0
    elif result.returncode == 1:
        state, action, code = 'no_unlocked_key', 'Import a key in Factory Settings → SSH and repositories → SSH key, or unlock an existing key there. Do not generate keys in the development container.', 2
    else:
        state, action, code = 'agent_unavailable', 'If this ran in the inner sandbox, rerun through bash_escalate when available. If it already ran in the outer container, ask the user to check the SSH companion in Factory.', 3
    return {'state': state, 'destinations': destinations, 'action': action}, code


def report():
    try:
        return status()
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        return {'state': 'unavailable', 'action': 'If this ran in the inner sandbox, rerun through bash_escalate when available. Otherwise ask the user to check SSH settings in Factory; no key material was read.'}, 3


if __name__ == '__main__':
    result, code = report()
    print(json.dumps(result))
    raise SystemExit(code)
