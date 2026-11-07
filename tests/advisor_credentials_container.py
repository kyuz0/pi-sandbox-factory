"""Check credential copies in a disposable companion; host sign-ins require opt-in."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pi_sandbox_factory import sandbox as core, sandbox_advisors as advisors
from pi_sandbox_factory import advisor_credentials as credentials

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--host-logins', action='store_true', help='Copy this user’s host logins and run account/model status checks; no inference')
args = parser.parse_args()

with tempfile.TemporaryDirectory(prefix='advisor-import-') as temporary:
    state = Path(temporary)
    config = dict(name=state.name, engine='podman', uid=os.getuid(), gid=os.getgid(),
                  advisors={'providers': list(credentials.LABELS)})
    worker = advisors.names(config)[0]
    def execute(command, **kwargs):
        return subprocess.run(['podman','exec',worker,*command], capture_output=True, text=True, **kwargs)
    try:
        advisors.build(config)
        advisors.up(config, state)
        fixtures = {'codex': '{"tokens":{"access_token":"synthetic-codex"}}',
                    'claude': '{"claudeAiOauth":{"accessToken":"synthetic-claude"}}',
                    'agy': '{"token":"synthetic-antigravity"}'}
        for provider, payload in fixtures.items():
            with patch.object(credentials, 'read_host', return_value=payload):
                credentials.import_from_host(config, state, provider)
        advisors.down(config)
        advisors.up(config, state)
        for provider, relative in [('codex','.codex/auth.json'), ('claude','.claude/.credentials.json')]:
            check = execute(['python3','-c',
                'import pathlib,stat,sys; p=pathlib.Path(sys.argv[1]); assert stat.S_IMODE(p.stat().st_mode)==0o600; print(p.read_text(),end="")',
                '/home/node/'+relative])
            assert check.returncode == 0 and check.stdout == fixtures[provider], provider
        keyring = execute(['secret-tool','lookup','service','gemini','username','antigravity'])
        assert keyring.returncode == 0 and keyring.stdout.strip() == fixtures['agy']
        data = core.inspect(config, worker)
        assert data['HostConfig']['NetworkMode'] == 'none'
        assert not any(m['Destination'] == '/workspace' for m in data['Mounts'])
        assert {m['Source'] for m in data['Mounts'] if m['Type'] == 'bind'} == {str(state/'advisor/config.json')}
        assert not any('-home:' in arg for arg in advisors.mounts(config))
        print('PASS: three credential stores, private file permissions, restart persistence and separate storage', flush=True)
        if args.host_logins:
            for provider in credentials.LABELS:
                credentials.import_from_host(config, state, provider)
            codex = execute(['advisor-codex','-c','cli_auth_credentials_store="file"','login','status'], timeout=60)
            assert codex.returncode == 0 and 'ChatGPT' in codex.stdout + codex.stderr, 'Codex did not recognize the imported login'
            print('PASS: Codex recognizes the copied ChatGPT login', flush=True)
            claude = execute(['advisor-claude','auth','status'], timeout=60)
            assert claude.returncode == 0 and json.loads(claude.stdout).get('loggedIn'), 'Claude did not recognize the imported login'
            print('PASS: Claude recognizes the copied subscription login', flush=True)
            agy = execute(['agy','models'], timeout=120)
            assert agy.returncode == 0 and 'gemini' in agy.stdout.lower(), 'Antigravity could not load its model catalogue with the imported login'
            print('PASS: Antigravity loads its model catalogue with the copied keyring login', flush=True)
    finally:
        advisors.down(config, remove=True)
        advisors.delete_volumes(config)
