"""Exercise real Git/SSH against a disposable server with explicit permission fixtures."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid
from unittest.mock import patch

from pi_sandbox_factory import sandbox, sandbox_ssh as ssh

SERVER = '''FROM docker.io/library/debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server git python3 && rm -rf /var/lib/apt/lists/* \\
 && useradd -m -s /bin/sh git && usermod -p x git && mkdir -p /run/sshd
COPY access.py /usr/local/bin/git-access
RUN chmod 755 /usr/local/bin/git-access
CMD ["/usr/sbin/sshd", "-D", "-e", "-p", "2222", "-o", "PasswordAuthentication=no", "-o", "KbdInteractiveAuthentication=no", "-o", "AuthorizedKeysFile=/fixture/authorized_keys", "-o", "StrictModes=no"]
'''
ACCESS = '''#!/usr/bin/python3
import os, shlex
from pathlib import Path
args = shlex.split(os.environ.get('SSH_ORIGINAL_COMMAND', ''))
if len(args) != 2 or args[1] != '/home/git/project.git' or args[0] not in ('git-upload-pack', 'git-receive-pack'):
    raise SystemExit('Only the fixture repository is available')
if args[0] == 'git-receive-pack' and Path('/fixture/mode').read_text() == 'read':
    raise SystemExit('Read-only repository key')
os.execvp(args[0], args)
'''
HOOK = '''#!/usr/bin/python3
import subprocess, sys
from pathlib import Path
for line in sys.stdin:
    old, new, ref = line.split()
    if Path('/fixture/mode').read_text() == 'full':
        continue
    if not ref.startswith('refs/heads/pi-') or new == '0' * 40:
        raise SystemExit('Protected reference')
    if old != '0' * 40 and subprocess.run(['git', 'merge-base', '--is-ancestor', old, new]).returncode:
        raise SystemExit('Force push forbidden')
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dev-image', required=True)
    args = parser.parse_args()
    engine = 'podman'
    name = 'repo-check-' + uuid.uuid4().hex[:8]
    server = name + '-server'
    network = name + '-network'
    original_run = sandbox.run
    def fixture_run(argv, **kwargs):
        argv = list(argv)
        if len(argv) > 1 and argv[1] == 'run' and '--name' in argv and argv[argv.index('--name') + 1] == 'pi-sandbox-factory-' + name + '-ssh':
            argv[2:2] = ['--network', network]
        return original_run(argv, **kwargs)
    fixture_network = patch.object(sandbox, 'run', side_effect=fixture_run)
    server_image = 'localhost/factory-repository-ssh-test'
    def run(*cmd, check=True):
        return subprocess.run([str(c) for c in cmd], check=check, text=True, capture_output=True)
    with tempfile.TemporaryDirectory(prefix='factory-repository-') as temporary:
        root = Path(temporary)
        fixture = root / 'fixture'; fixture.mkdir(); fixture.chmod(0o755)
        state = root / 'state';state.mkdir()
        build = root / 'build';build.mkdir()
        (build / 'Dockerfile').write_text(SERVER)
        (build / 'access.py').write_text(ACCESS)
        (fixture / 'authorized_keys').touch();(fixture/'authorized_keys').chmod(0o644)
        (fixture / 'mode').write_text('read');(fixture/'mode').chmod(0o644)
        (fixture / 'hook').write_text(HOOK);(fixture/'hook').chmod(0o755)
        config = dict(name=name, engine=engine, uid=1000, gid=1000)
        try:
            print('Building the disposable SSH server and credential companion', flush=True)
            result = run(engine, 'build', '-t', server_image, build, check=False)
            if result.returncode:
                raise RuntimeError(result.stderr[-4000:])
            run(engine, 'network', 'create', '--internal', network)
            fixture_network.start()
            run(engine, 'run', '-d', '--name', server, '--network', network, '--security-opt=label=disable',
                '-v', str(fixture) + ':/fixture:ro', server_image)
            info = json.loads(run(engine, 'inspect', server).stdout)[0]
            address = next(iter(info['NetworkSettings']['Networks'].values()))['IPAddress']
            hostkey = run(engine, 'exec', server, 'cat', '/etc/ssh/ssh_host_ed25519_key.pub').stdout.split()
            config['ssh'] = {'hosts': [dict(alias='repository', user='git', hostname=address,
                port=2222, host_keys=[' '.join(hostkey[:2])])]}
            setup = '''set -eu
mkdir /home/git/source
cd /home/git/source
git init -q -b main
git config user.email fixture@example.test
git config user.name Fixture
printf 'first\\n' > sample.txt
git add . && git commit -qm first
git clone -q --bare . /home/git/project.git
cp /fixture/hook /home/git/project.git/hooks/pre-receive
'''
            run(engine, 'exec', '-u', 'git', server, 'sh', '-c', setup)
            ssh.build(config)
            public = ssh.repository_key(config, state, generate=True)
            assert public.startswith('ssh-ed25519 ')
            (fixture/'authorized_keys').write_text('command="/usr/local/bin/git-access",restrict ' + public + '\n')
            before = ssh.repository_key(config, state)
            try:
                ssh.repository_key(config, state, generate=True)
                raise AssertionError('Existing key replaced')
            except ValueError as error:
                assert 'already exists' in str(error), error
            assert ssh.repository_key(config, state) == before
            print('PASS generate/show/refuse replacement', flush=True)
            client = name + '-client'
            run(engine, 'run', '-d', '--name', client, '--network=none', '--userns=keep-id:uid=1000,gid=1000',
                '--cap-drop=ALL', '--security-opt=no-new-privileges', '--security-opt=label=disable',
                *ssh.mounts(config, state), '--entrypoint', 'sleep', args.dev_image, 'infinity')
            def git(command, succeeds=True):
                result = run(engine, 'exec', client, 'bash', '-c',
                    command, check=False)
                assert (result.returncode == 0) == succeeds, (command, result.stdout, result.stderr)
                return result
            git('git clone git@repository:/home/git/project.git /tmp/project')
            report = json.loads(run(engine, 'exec', '-e', 'SSH_AUTH_SOCK=', client, 'sandbox-ssh-status').stdout)
            assert report['state'] == 'key_loaded', report
            run(engine, 'exec', '-e', 'SSH_AUTH_SOCK=', client, 'git', '-C', '/tmp/project', 'ls-remote', 'origin', 'HEAD')
            run(engine, 'exec', client, 'python3', '/usr/local/lib/sandbox-bootstrap.py')
            worker = Path(__file__).with_name('check_pendant_worker.cjs').read_text()
            subprocess.run([engine, 'exec', '-i', client, 'sh', '-c', 'cat > /tmp/check-ssh-pendant.cjs'],
                           input=worker, text=True, check=True)
            result = subprocess.run([engine, 'exec', '-i', '-e', 'SSH_AUTH_SOCK=', client, 'python3', '-'],
                input=Path(__file__).with_name('check_ssh_clients.py').read_text(), text=True, capture_output=True)
            assert result.returncode == 0, (result.stdout, result.stderr)
            print(result.stdout, end='', flush=True)
            git('cd /tmp/project && git config user.email fixture@example.test && git config user.name Fixture && '
                'git checkout -b pi-test && echo second >> sample.txt && git commit -qam second && git push origin pi-test', succeeds=False)
            print('PASS read-only clone allowed, push rejected', flush=True)
            (fixture/'mode').write_text('contribute')
            git('cd /tmp/project && git push origin pi-test')
            for ref in ('HEAD:main', 'HEAD:other', 'HEAD:refs/tags/test', ':pi-test'):
                git('cd /tmp/project && git push origin ' + ref, succeeds=False)
            git('cd /tmp/project && git push --force origin HEAD~1:pi-test', succeeds=False)
            print('PASS permitted branch; main/new branch/tag/deletion/force push denied', flush=True)
            (fixture/'mode').write_text('full')
            git('cd /tmp/project && git push origin HEAD:main')
            print('PASS full-write key policy permits main update', flush=True)
            git('test ! -e /private/id_key && test ! -e /etc/sandbox-ssh/id_key')
            client_info=json.loads(run(engine, 'inspect', client).stdout)[0]
            assert not any(m['Destination']=='/private' for m in client_info['Mounts'])
            ssh.down(config, remove=True)
            ssh.up(config, state)
            assert ssh.repository_key(config, state) == public
            git('cd /tmp/project && git ls-remote origin HEAD')
            print('PASS private-volume isolation and key persistence after companion restart', flush=True)
            # Import a different fixture key and verify the agent drops the old identity.
            imported = root / 'imported-key'
            run('ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', imported)
            ssh.import_key(config, state, imported)
            replacement = ssh.repository_key(config, state)
            assert replacement != public
            assert replacement.split()[:2] == (root / 'imported-key.pub').read_text().split()[:2]
            git('cd /tmp/project && git ls-remote origin HEAD', succeeds=False)
            (fixture/'authorized_keys').write_text('command="/usr/local/bin/git-access",restrict ' + replacement + '\n')
            git('cd /tmp/project && git ls-remote origin HEAD')
            print('PASS import replaces the key and revokes the old signing identity', flush=True)
            run(engine, 'exec', client, 'ssh-add', '-D')
            result = run(engine, 'exec', client, 'sandbox-ssh-status', check=False)
            assert result.returncode == 2 and json.loads(result.stdout)['state'] == 'no_unlocked_key', result
            git('cd /tmp/project && git ls-remote origin HEAD', succeeds=False)
            ssh.unlock(config, state)
            git('cd /tmp/project && git ls-remote origin HEAD')
            print('PASS unloaded key diagnosed; companion unlock restores Git without client key files', flush=True)
        finally:
            run(engine, 'rm', '-f', name + '-client', server, check=False)
            ssh.down(config, remove=True)
            ssh.delete_volumes(config)
            fixture_network.stop()
            run(engine, 'network', 'rm', network, check=False)


if __name__ == '__main__':
    main()
