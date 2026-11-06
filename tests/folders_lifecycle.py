"""Check folder changes in an explicitly disposable sandbox with reference/output mounts."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pi_sandbox_factory import sandbox

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--state-dir', type=Path, required=True)
parser.add_argument('--name', required=True)
args = parser.parse_args()
state = args.state_dir / args.name
config = json.loads((state / 'config.json').read_text())
engine, dev = config['engine'], sandbox.names(config)[0]
reference = next(r for r in config['extra_folders'] if r['name'] == 'reference')
output = next(r for r in config['extra_folders'] if r['name'] == 'output')
assert reference['read_only'] and not output['read_only']


def inside(*command, check=True):
    return subprocess.run([engine, 'exec', dev, *command], capture_output=True, text=True, check=check)


def cid():
    return sandbox.inspect(config, dev)['Id']


original_id = cid()
labels = {r['source']: subprocess.check_output(['ls', '-Zd', r['source']], text=True) for r in config['extra_folders']}
inside('sh', '-c', 'printf PRIVATE_KEEP > /home/node/folder-private-marker')
result = inside('touch', '/mnt/reference/outer-denied', check=False)
assert result.returncode != 0 and 'Read-only' in result.stderr, result
assert inside('mount', '-o', 'remount,rw', '/mnt/reference', check=False).returncode != 0
inside('sh', '-c', 'printf HOST_OWNER_OK > /mnt/output/owner.txt')
assert (Path(output['source']) / 'owner.txt').stat().st_uid == os.getuid()
for source, label in labels.items():
    assert subprocess.check_output(['ls', '-Zd', source], text=True) == label
print('PASS outer read-only enforcement, refused remount, host ownership and unchanged SELinux labels', flush=True)

sandbox.apply_settings(config, state, {'working_directory': '.'})
assert cid() == original_id
saved = json.loads((state / 'config.json').read_text())
assert json.loads((state / 'attached-container.json').read_text())['workspaceFolder'] == '/workspace'
command = [sys.executable, '-m', 'pi_sandbox_factory', '--state-dir', str(args.state_dir), 'exec', args.name, '--', 'pwd']
assert subprocess.check_output(command, text=True).strip() == '/workspace'
sandbox.apply_settings(saved, state, {'working_directory': 'app'})
assert cid() == original_id
assert subprocess.check_output(command, text=True).strip() == '/workspace/app'
print('PASS starting-folder edits change CLI cwd and editor configuration without recreation', flush=True)

# A missing source must fail before stopping the existing sandbox.
bad = dict(output, source=str(Path(output['source']) / 'missing'))
try:
    sandbox.apply_settings(config, state, {'extra_folders': [reference, bad]})
except ValueError:
    pass
else:
    raise AssertionError('Missing source accepted')
assert cid() == original_id

# Remove a mount, verify private state, then change the remaining mount to read-only.
sandbox.apply_settings(config, state, {'extra_folders': [output]})
saved = json.loads((state / 'config.json').read_text())
assert cid() != original_id
assert inside('test', '-e', '/mnt/reference/readme.txt', check=False).returncode != 0
assert (Path(reference['source']) / 'readme.txt').is_file()
assert inside('cat', '/home/node/folder-private-marker').stdout == 'PRIVATE_KEEP'
sandbox.apply_settings(saved, state, {'extra_folders': [dict(output, read_only=True)]})
assert inside('touch', '/mnt/output/changed-mode-denied', check=False).returncode != 0
assert inside('cat', '/mnt/output/owner.txt').stdout == 'HOST_OWNER_OK'
assert inside('cat', '/home/node/folder-private-marker').stdout == 'PRIVATE_KEEP'
print('PASS mount removal and read-only changes preserve host files and private state', flush=True)
