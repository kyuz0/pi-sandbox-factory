"""Opt-in code-server prototype: container editor, authenticated loopback browser UI."""
import asyncio
import fcntl
import hashlib
import json
from pathlib import Path
import re
import secrets
import signal
import subprocess
import urllib.request

VERSION = '4.145.2'
SHA256 = '2f6db6c3e8b733dd6b3aeee83532e148b2bae2e392353ba85452d03572348962'
ARCHIVE = f'code-server-{VERSION}-linux-amd64.tar.gz'
URL = f'https://github.com/coder/code-server/releases/download/v{VERSION}/{ARCHIVE}'
INSTALL = f'/opt/pi-browser-editor-{VERSION}'
SOCKET = '/home/node/.local/share/pi-browser-editor/editor.sock'


def active(state):
    """The host lock prevents opening desktop VS Code during a browser session."""
    with (state / 'browser-editor.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
        except BlockingIOError:
            return True


def checked_archive(cache, supplied=None):
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = Path(supplied).expanduser().resolve() if supplied else cache / ARCHIVE
    if not path.exists():
        if supplied:
            raise ValueError('Browser editor archive does not exist')
        print(f'Downloading code-server {VERSION} (226 MiB)…', flush=True)
        temporary = cache / (ARCHIVE + '.' + secrets.token_hex(8))
        try:
            with urllib.request.urlopen(URL, timeout=60) as response, temporary.open('xb') as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
            verify_archive(temporary)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    try:
        verify_archive(path)
    except ValueError:
        if not supplied:
            path.unlink(missing_ok=True)
        raise
    return path


def verify_archive(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    if digest.hexdigest() != SHA256:
        raise ValueError('Browser editor archive checksum does not match the pinned release')


def validate_head(head, host):
    """Validate browser origin and authority before creating the fixed connector."""
    if len(head) > 16384:
        raise ValueError('Headers too large')
    lines = head.decode('ascii').split('\r\n')
    method, target, version = lines.pop(0).split(' ')
    if (not re.fullmatch('[A-Z]+', method) or version != 'HTTP/1.1' or
            not target.startswith('/') or target.startswith('//') or
            any(ord(c) < 33 or ord(c) == 127 for c in target)):
        raise ValueError('Invalid request')
    headers = {}
    for line in lines:
        if not line:
            continue
        name, value = line.split(':', 1)
        name = name.lower()
        if (not re.fullmatch('[a-z0-9-]+', name) or name in headers or
                any(ord(c) < 32 and c != '\t' or ord(c) == 127 for c in value)):
            raise ValueError('Invalid headers')
        headers[name] = value.strip()
    if headers.get('host') != host or headers.get('origin', 'http://' + host) != 'http://' + host:
        raise ValueError('Invalid host or origin')
    if any(k == 'forwarded' or k.startswith('x-forwarded-') for k in headers):
        raise ValueError('Forwarded headers are not accepted')


class Relay:
    """A byte relay to one fixed container socket; authentication belongs to code-server."""
    def __init__(self, container):
        if not re.fullmatch('[a-f0-9]{64}', container):
            raise ValueError('Expected immutable container ID')
        self.container = container
        self.host = ''
        self.tasks = set()

    async def connector(self):
        return await asyncio.create_subprocess_exec(
            'podman', 'exec', '-i', '--user', 'node', self.container,
            'socat', 'STDIO', 'UNIX-CONNECT:' + SOCKET,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=True)

    async def handle(self, reader, writer):
        if len(self.tasks) >= 32:
            writer.close()
            return
        task = asyncio.current_task()
        self.tasks.add(task)
        process = None
        pumps = []
        try:
            head = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 10)
            validate_head(head, self.host)
            process = await self.connector()
            process.stdin.write(head)
            await process.stdin.drain()

            async def pump(source, target):
                while data := await source.read(65536):
                    target.write(data)
                    await target.drain()
            # After validating the first head, preserve HTTP keep-alive and WebSocket bytes.
            # Browser connections stay on one origin; code-server authenticates each request.
            pumps = [asyncio.create_task(pump(reader, process.stdin)),
                     asyncio.create_task(pump(process.stdout, writer))]
            await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
        except (ValueError, UnicodeError, OSError, ConnectionError, asyncio.TimeoutError,
                asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            if process is None:
                writer.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                try:
                    await writer.drain()
                except ConnectionError:
                    pass
        finally:
            for child in pumps:
                child.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            if process is not None:
                process.stdin.close()
                if process.returncode is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass
                await process.wait()
            writer.close()
            self.tasks.discard(task)

    async def close(self):
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)


async def serve(container, cwd, password):
    task = asyncio.current_task()
    for signum in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(signum, task.cancel)
    relay = Relay(container)
    address = '127.' + '.'.join(str(secrets.randbelow(254) + 1) for _ in range(3))
    server = await asyncio.start_server(relay.handle, address, 0, limit=16384)
    relay.host = address + ':' + str(server.sockets[0].getsockname()[1])
    editor = None
    try:
        helper = (Path(__file__).parent / 'containers/editor/launch.py').read_text()
        editor = await asyncio.create_subprocess_exec('podman', 'exec', '-i', '--user', 'node',
            container, 'python3', '-u', '-c', helper, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, start_new_session=True)
        editor.stdin.write((json.dumps({'binary': INSTALL + '/bin/code-server',
                                      'cwd': cwd, 'authority': relay.host, 'password_hash': hashlib.sha256(password.encode()).hexdigest()}) + '\n').encode())
        await editor.stdin.drain()
        ready = await asyncio.wait_for(editor.stdout.readline(), 60)
        if ready != b'ready\n':
            raise ValueError('Browser editor did not start; see the error above')
        print(f'\nBrowser editor: http://{relay.host}\nPassword: {password}\n'
              'Open this URL in a separate browser profile and enter the password.\n'
              'Keep this terminal open. Ctrl+C stops the browser editor.\n', flush=True)
        # The attached exec exits when its container stops.
        await editor.wait()
        if editor.returncode not in (None, 0):
            raise ValueError('Browser editor stopped; see the error above')
    finally:
        server.close()
        await relay.close()
        await server.wait_closed()
        if editor is not None:
            editor.stdin.close()
            try:
                await asyncio.wait_for(editor.wait(), 10)
            except asyncio.TimeoutError:
                editor.terminate()
                await editor.wait()


def open_browser_editor(config, state, archive=None):
    from . import sandbox, folders
    if config['engine'] != 'podman':
        raise ValueError('The browser editor prototype requires rootless Podman on x86_64 Linux')
    current = sandbox.inspect(config, sandbox.names(config)[0])
    if not current or not current['State']['Running']:
        raise ValueError('Start the sandbox before opening its browser editor')
    container = current['Id']
    with (state / 'browser-editor.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('This sandbox already has a browser editor open') from None
        rootless = subprocess.check_output(['podman', 'info', '--format', '{{.Host.Security.Rootless}}'], text=True).strip()
        if rootless != 'true':
            raise ValueError('The browser editor prototype requires rootless Podman')
        arch = subprocess.check_output(['podman', 'exec', container, 'uname', '-m'], text=True).strip()
        if arch != 'x86_64':
            raise ValueError('The browser editor prototype currently supports x86_64 only')
        binary = INSTALL + '/bin/code-server'
        if subprocess.run(['podman', 'exec', container, 'test', '-x', binary]).returncode:
            path = checked_archive(state.parent / '.browser-editor-downloads', archive)
            staging = INSTALL + '.install-' + secrets.token_hex(8)
            subprocess.run(['podman', 'exec', '--user', '0', container,
                            'mkdir', '-m', '755', staging], check=True)
            try:
                with path.open('rb') as source:
                    subprocess.run(['podman', 'exec', '-i', '--user', '0', container,
                        'tar', '-xz', '--no-same-owner', '--strip-components=1', '-C', staging],
                        stdin=source, check=True)
                subprocess.run(['podman', 'exec', '--user', '0', container,
                                'mv', '-T', staging, INSTALL], check=True)
            finally:
                subprocess.run(['podman', 'exec', '--user', '0', container, 'rm', '-rf', staging],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if config.get('local_model_ports') or config.get('model_providers'):
            sandbox.initialize_models(config)
        (state / 'browser-editor.enabled').touch(mode=0o600)
        try:
            asyncio.run(serve(container, folders.container_cwd(config), secrets.token_urlsafe(32)))
        except (KeyboardInterrupt, asyncio.CancelledError):
            print('\nBrowser editor stopped.')
