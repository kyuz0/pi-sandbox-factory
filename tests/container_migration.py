"""Check live/restarted bind mounts and private volume data across migration on Linux.

python tests/container_migration.py --image LOCALLY_BUILT_FACTORY_IMAGE
Only the test's own container and volume are removed.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pi_factory_migration.paths import locations, migrate


def run(*command):
    return subprocess.check_output(command, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    name = 'factory-migration-test-' + uuid.uuid4().hex[:12]
    volume = name + '-chats'
    created_container = created_volume = False
    with tempfile.TemporaryDirectory(prefix='factory-migration-mounts-') as directory:
        home = Path(directory)
        pairs = locations(home, {})
        old, new = pairs[0]
        state = old / 'example'
        folder = state / 'runtime-config'
        folder.mkdir(parents=True)
        (folder / 'receipt').write_text('before migration')
        (state / 'options.json').write_text('{"preserved":true}')
        before = (folder.stat().st_uid, folder.stat().st_gid, folder.stat().st_mode)
        try:
            run('podman', 'volume', 'create', volume);created_volume = True
            run('podman', 'run', '-d', '--name', name, '--label', 'io.ai-sandbox-factory.test=migration',
                '--network', 'none', '--read-only', '--userns', 'keep-id',
                '--user', f'{os.getuid()}:{os.getgid()}',
                '-v', f'{folder}:/mounted:ro,Z', '-v', f'{state / "options.json"}:/options.json:ro,Z',
                '-v', f'{volume}:/private-chats:U', '--entrypoint', '/bin/sh', args.image,
                '-c', 'trap \"exit 0\" TERM; while :; do sleep 1 & wait $!; done')
            created_container = True
            run('podman', 'exec', name, 'sh', '-c', 'printf saved-chat > /private-chats/chat.jsonl')
            identity = run('podman', 'inspect', '--format', '{{.Id}}', name)
            assert run('podman', 'exec', name, 'cat', '/mounted/receipt') == 'before migration'
            migrate(pairs)
            assert old.is_symlink() and new.is_dir()
            assert run('podman', 'exec', name, 'cat', '/mounted/receipt') == 'before migration'
            (new / 'example/runtime-config/receipt').write_text('after migration')
            assert run('podman', 'exec', name, 'cat', '/mounted/receipt') == 'after migration'
            assert run('podman', 'exec', name, 'cat', '/options.json') == '{"preserved":true}'
            run('podman', 'restart', name)
            assert run('podman', 'inspect', '--format', '{{.Id}}', name) == identity
            assert run('podman', 'exec', name, 'cat', '/mounted/receipt') == 'after migration'
            assert run('podman', 'exec', name, 'cat', '/private-chats/chat.jsonl') == 'saved-chat'
            assert (folder.stat().st_uid, folder.stat().st_gid, folder.stat().st_mode) == before
            print(json.dumps({'running_mounts': 'pass', 'restarted_original_container': 'pass',
                              'private_volume_data': 'pass', 'host_ownership': 'unchanged'}))
        finally:
            if created_container:
                subprocess.run(['podman', 'rm', '-f', name], check=True, stdout=subprocess.DEVNULL)
            if created_volume:
                subprocess.run(['podman', 'volume', 'rm', volume], check=True, stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
