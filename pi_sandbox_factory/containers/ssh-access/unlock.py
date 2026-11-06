"""Load only the private companion key, constrained to declared users/host identities."""
import json
import os
from pathlib import Path
import subprocess
import sys

settings = json.loads(Path('/etc/ssh-access/targets.json').read_text())
args = ['ssh-add', '-H', '/etc/ssh-access/known_hosts', '-t', '8h']
for host in settings:
    args += ['-h', host['user'] + '@' + host['alias']]
if not settings:
    raise SystemExit('No SSH destinations configured')
args += ['/private/id_key']
# An existing grant must not outlive a changed target configuration.
subprocess.run(['ssh-add', '-D'], check=True)
result = subprocess.run(args, env={**os.environ, 'SSH_ASKPASS_REQUIRE': 'never'})
sys.exit(result.returncode)
