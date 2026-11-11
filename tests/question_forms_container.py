"""Check question-form toggles in installed Pi and the shipped Pendant worker, offline."""
import argparse
import json
from pathlib import Path
import subprocess
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', required=True, help='An existing Factory development image')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    name = 'factory-question-forms-' + uuid.uuid4().hex[:10]

    def run(*args, **kwargs):
        return subprocess.run(['podman', *args], check=True, text=True, **kwargs)

    try:
        run('run', '-d', '--name', name, '--network', 'none',
            '--userns=keep-id:uid=1000,gid=1000', '--user', '1000:1000',
            '--entrypoint', 'sleep', args.image, 'infinity', capture_output=True)
        for source, target in [('pi_sandbox_factory/containers/dev/bootstrap.py', 'bootstrap.py'),
                               ('tests/check_question_forms.mjs', 'check.mjs'),
                               ('tests/check_pendant_worker.cjs', 'pendant.cjs')]:
            run('cp', str(root / source), name + ':/tmp/' + target)
        baseline = None
        for enabled in (None, False, False, True):
            choice = {} if enabled is None else {'question_forms': enabled}
            run('exec', '-i', '--user', 'root', name, 'python3', '-c',
                "from pathlib import Path; import sys; Path('/opt/sandbox/options.json').write_text(sys.stdin.read())",
                input=json.dumps(choice))
            run('exec', name, 'python3', '/tmp/bootstrap.py')
            settings = json.loads(run('exec', name, 'cat', '/home/node/.pi/agent/settings.json', capture_output=True).stdout)
            security = [p for p in settings['extensions'] if '/pi-security/' in p]
            if baseline is None:
                baseline = security
            assert baseline == security, 'Question switch changed security extensions'
            assert any('/pi-auto-review/' in p for p in security), 'Automatic reviewer missing'
            assert any('/pi-permission-system/' in p for p in security), 'Permission system missing'
            run('exec', name, 'node', '/tmp/check.mjs')
            run('exec', name, 'node', '/tmp/pendant.cjs', '--question-forms-only')
        print('PASS default, disable, repeated disable, re-enable; security extensions unchanged')
    finally:
        subprocess.run(['podman', 'rm', '-f', '-v', name], check=False, capture_output=True)


if __name__ == '__main__':
    main()
