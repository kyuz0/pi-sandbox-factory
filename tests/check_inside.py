"""Live boundary check, piped into the development container by sandbox.py check."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys


def curl(url, *options):
    return subprocess.run(['curl', '--silent', '--show-error', '--max-time', '15',
                           '--output', '/dev/null', '--write-out', '%{http_code}',
                           *options, url], text=True, capture_output=True)


def require(condition, message):
    if not condition:
        raise AssertionError(message)
    print('PASS ' + message, flush=True)


require(os.getuid() != 0, 'development process is not root')
status = Path('/proc/self/status').read_text()
require('CapEff:\t0000000000000000' in status, 'no effective Linux capabilities')
require('NoNewPrivs:\t1' in status, 'no-new-privileges enforced')
mode = os.environ.get('SANDBOX_NETWORK_MODE', 'allowlist')
if mode == 'allowlist':
    interfaces = json.loads(subprocess.check_output(['ip', '-j', 'link'], text=True))
    require({x['ifname'] for x in interfaces} == {'lo'}, 'only loopback networking exists')
    for host in ('1.1.1.1', '169.254.169.254', '192.168.1.1', '2606:4700:4700::1111'):
        try:
            connection = socket.create_connection((host, 443), timeout=2)
        except OSError:
            print('PASS direct connection blocked: ' + host)
        else:
            connection.close()
            raise AssertionError('Direct connection succeeded: ' + host)
    try:
        socket.getaddrinfo('unlisted-dns-check.invalid', 443)
    except OSError:
        print('PASS direct DNS lookup blocked')
    else:
        raise AssertionError('Unexpected direct DNS result')
    for url in ('http://unlisted.invalid/', 'https://unlisted.invalid/',
                'http://169.254.169.254/', 'https://1.1.1.1/',
                'https://example.com.evil.invalid/', 'https://example.com:444/'):
        result = curl(url, '--proxy', 'http://127.0.0.1:3128', '--noproxy', '')
        # curl reports CONNECT rejection through stderr, and HTTP rejection as status.
        require(result.stdout == '403' or '403' in result.stderr,
                'proxy rejects ' + url)
    allowed = curl(sys.argv[1])
    require(allowed.returncode == 0 and allowed.stdout not in ('000', '403', '502', '503', '504'),
            'allowed endpoint reachable: ' + sys.argv[1] + ' (HTTP ' + allowed.stdout + ')')
    direct = curl(sys.argv[1], '--noproxy', '*')
    require(direct.returncode != 0, 'removing proxy configuration does not bypass isolation')
else:
    require(mode == 'unrestricted', 'recognized unrestricted network mode')
    require(not Path('/run/egress/proxy.sock').exists(), 'unrestricted mode has no allowlist proxy socket')
    require(not any(os.environ.get(key) for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy')),
            'unrestricted mode does not inherit allowlist proxy variables')
    result = curl(sys.argv[1], '--noproxy', '*')
    require(result.returncode == 0 and result.stdout not in ('000', '502', '503', '504'),
            'unrestricted container reaches the requested endpoint directly')
try:
    with open('/pi-config/.sandbox-write-check', 'x'):
        pass
except OSError:
    print('PASS seed configuration cannot be modified from the sandbox')
else:
    os.unlink('/pi-config/.sandbox-write-check')
    raise AssertionError('Shared configuration was writable')
require(not Path('/var/run/docker.sock').exists() and not Path('/run/podman/podman.sock').exists(),
        'no container engine socket mounted')
models = Path('/home/node/.pi/agent/models.json')
require(models.is_file() and not models.is_symlink() and os.access(models, os.W_OK),
        'models.json is a private writable regular file')
require(models.stat().st_mode & 0o077 == 0, 'models.json permissions are owner-only')
require(bool(list(Path('/home/node/.vscode-server/extensions').glob('cdervis.vscode-pi-*/package.json'))),
        'Pendant extension preloaded')
pi_package = Path('/usr/local/lib/node_modules/@earendil-works/pi-coding-agent')
pi_binary = json.loads((pi_package / 'package.json').read_text())['bin']['pi']
require(Path('/usr/local/bin/pi').resolve() == pi_package / pi_binary,
        'Pi executable is the original installed CLI without a wrapper')
subprocess.run(['node', '/usr/local/bin/pi', '--version'], check=True)
tmux = subprocess.run(['tmux', '-V'], check=True, text=True, capture_output=True)
require(tmux.stdout.startswith('tmux '), 'tmux installed for every Pi sandbox')
security_check = Path('/opt/pi-security/check.mjs')
if security_check.exists():
    subprocess.run(['node', '--experimental-strip-types', str(security_check), sys.argv[1]], check=True)
profile_check = Path('/opt/sandbox/profile-check.py')
document_check = Path('/opt/document-tools/check.py')
if document_check.exists():
    for interpreter in ('/usr/bin/python3', 'python3', 'python'):
        subprocess.run([interpreter, str(document_check)], check=True)
    subprocess.run(['bash', '-lc', 'python /opt/document-tools/check.py'], check=True)
if profile_check.exists():
    subprocess.run(['python3', str(profile_check), sys.argv[1]], check=True)
print('All live checks passed.')
