"""Authentication and lifecycle checks against a disposable browser-editor sandbox."""
import argparse
import http.client
import json
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
from urllib.parse import urlencode, urlsplit

from pi_sandbox_factory import browser_editor, editor_settings


def request(url, path='/?folder=/workspace', *, method='GET', body=None, headers=None, context=None):
    target = urlsplit(url)
    connection = (http.client.HTTPSConnection(target.hostname, target.port, context=context, timeout=20)
                  if context else http.client.HTTPConnection(target.hostname, target.port, timeout=20))
    try:
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def check(state, tls_address):
    previous = editor_settings.load(state)
    command = [sys.executable, '-m', 'pi_sandbox_factory', '--state-dir', str(state.parent),
               'browser-editor', state.name, '--background', '--no-open']
    def launch():
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        return browser_editor.runtime(state)
    def configure(value):
        browser_editor.stop(state)
        editor_settings.save(state, value)
        return launch()
    password = secrets.token_urlsafe(24)
    digest = editor_settings.password_hash(password)
    try:
        first = configure({})
        url = first['url']
        assert request(url)[0] == 200
        assert launch()['pid'] == first['pid']
        browser_editor.stop(state)
        restarted = launch()
        assert restarted['url'] == url and restarted['pid'] != first['pid']
        for headers in ({'Host': 'other.example'}, {'Origin': 'https://other.example'},
                        {'Sec-Fetch-Site': 'cross-site'}, {'Sec-Fetch-Site': 'same-site'}):
            assert request(url, headers=headers)[0] == 403
        print('PASS passwordless startup, repeat open, restart and origin checks', flush=True)

        protected = configure({'password_hash': digest})
        url = protected['url']
        status, headers, _ = request(url)
        assert status == 302 and '/login' in headers['Location']
        websocket = {'Connection': 'Upgrade', 'Upgrade': 'websocket',
                     'Sec-WebSocket-Key': 'dGhlIHNhbXBsZSBub25jZQ==', 'Sec-WebSocket-Version': '13'}
        assert request(url, '/', headers=websocket)[0] in (401, 403)
        status, headers, _ = request(url, '/login', method='POST', body=urlencode({'password': password}),
                                     headers={'Content-Type': 'application/x-www-form-urlencoded'})
        assert status == 302 and 'Set-Cookie' in headers
        cookie = headers['Set-Cookie'].split(';')[0]
        assert request(url, headers={'Cookie': cookie})[0] == 200
        assert request(url, headers={'Cookie': cookie, 'Origin': 'https://other.example'})[0] == 403
        print('PASS password login and anonymous HTTP/WebSocket rejection', flush=True)

        with tempfile.TemporaryDirectory(prefix='editor-tls-check-') as folder:
            cert, key = Path(folder) / 'cert.pem', Path(folder) / 'key.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                            '-subj', '/CN=Disposable editor test', '-addext', f'subjectAltName=IP:{tls_address}',
                            '-keyout', str(key), '-out', str(cert)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            key.chmod(0o600)
            info = configure({'address': tls_address, 'password_hash': digest,
                              'certificate': str(cert), 'private_key': str(key)})
            context = ssl.create_default_context(cafile=str(cert))
            status, headers, _ = request(info['url'], '/login', method='POST',
                                         body=urlencode({'password': password}),
                                         headers={'Content-Type': 'application/x-www-form-urlencoded'}, context=context)
            assert status == 302 and '; Secure' in headers['Set-Cookie']
            assert request(info['url'], headers={'Cookie': headers['Set-Cookie'].split(';')[0]}, context=context)[0] == 200
            assert request(info['url'], headers={'Origin': 'http://' + urlsplit(info['url']).netloc}, context=context)[0] == 403
            browser_editor.stop(state)
        print('PASS HTTPS login, verified certificate, Secure cookie and scheme validation', flush=True)

        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0)); occupied.listen()
            editor_settings.save(state, {'address': '127.0.0.1', 'port': occupied.getsockname()[1], 'password_hash': digest})
            result = subprocess.run(command, capture_output=True, text=True)
            assert result.returncode != 0 and browser_editor.runtime(state) is None
        print('PASS occupied port fails without leaving an editor running', flush=True)
    finally:
        browser_editor.stop(state)
        editor_settings.save(state, previous)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--tls-address', default='127.0.0.1', help='Interface IP for the temporary authenticated HTTPS listener')
    args = parser.parse_args()
    check(args.state_dir.expanduser().resolve() / args.name, args.tls_address)
