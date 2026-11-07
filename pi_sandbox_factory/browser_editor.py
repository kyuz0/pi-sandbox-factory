"""Container-hosted code-server with configurable browser access and process supervision."""
import asyncio
import fcntl
import hashlib
import json
import os
import sys
import time
import select
from pathlib import Path
import re
import secrets
import signal
import subprocess
import urllib.request

from . import editor_settings
from .sandbox_options import write_json

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


def validate_head(head, host, scheme="http"):
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
    if headers.get('host') != host or headers.get('origin', scheme + '://' + host) != scheme + '://' + host:
        raise ValueError('Invalid host or origin')
    if headers.get('sec-fetch-site') in ('cross-site', 'same-site'):
        raise ValueError('Cross-site request')
    if 'expect' in headers or 'transfer-encoding' in headers or not headers.get('content-length', '0').isdigit():
        raise ValueError('Unsupported request framing')
    if any(k == 'forwarded' or k.startswith('x-forwarded-') for k in headers):
        raise ValueError('Forwarded headers are not accepted')
    return headers


class Relay:
    """A byte relay to one fixed container socket; authentication belongs to code-server."""
    def __init__(self, container):
        if not re.fullmatch('[a-f0-9]{64}', container):
            raise ValueError('Expected immutable container ID')
        self.container = container
        self.host = ''
        self.scheme = 'http'
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
        async def transfer(source, target, length):
            while length:
                data = await source.readexactly(min(length, 65536))
                target.write(data)
                await target.drain()
                length -= len(data)

        async def pump(source, target):
            while data := await source.read(65536):
                target.write(data)
                await target.drain()

        try:
            while True:
                head = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 60)
                headers = validate_head(head, self.host, self.scheme)
                if process is None:
                    process = await self.connector()
                process.stdin.write(head)
                await process.stdin.drain()
                await transfer(reader, process.stdin, int(headers.get('content-length', '0')))
                # Preserve keep-alive, checking each new request before forwarding it.
                while True:
                    response = await process.stdout.readuntil(b'\r\n\r\n')
                    lines = response.decode('latin1').split('\r\n')
                    status = int(lines[0].split()[1])
                    fields = {}
                    for i, line in enumerate(lines[1:], 1):
                        if line:
                            key, value = line.split(':', 1)
                            fields[key.lower()] = value.strip()
                            if key.lower() == 'set-cookie' and self.scheme == 'https':
                                lines[i] = line + '; Secure'
                    writer.write('\r\n'.join(lines).encode('latin1'))
                    await writer.drain()
                    if status == 101 or status >= 200:
                        break
                if status == 101:
                    if headers.get('upgrade', '').lower() != 'websocket':
                        raise ValueError('Unexpected protocol upgrade')
                    pumps = [asyncio.create_task(pump(reader, process.stdin)),
                             asyncio.create_task(pump(process.stdout, writer))]
                    await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
                    break
                if head.startswith(b'HEAD ') or status in (204, 304):
                    pass
                elif fields.get('transfer-encoding', '').lower() == 'chunked':
                    while True:
                        chunk = await process.stdout.readuntil(b'\r\n')
                        count = int(chunk.split(b';', 1)[0].strip(), 16)
                        writer.write(chunk)
                        if not count:
                            while True:
                                trailer = await process.stdout.readuntil(b'\r\n')
                                writer.write(trailer)
                                if trailer == b'\r\n':
                                    break
                            await writer.drain()
                            break
                        await transfer(process.stdout, writer, count + 2)
                elif 'content-length' in fields:
                    await transfer(process.stdout, writer, int(fields['content-length']))
                else:
                    await pump(process.stdout, writer)
                    break
                if headers.get('connection', '').lower() == 'close' or fields.get('connection', '').lower() == 'close':
                    break
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


async def serve(container, cwd, preferences, state, ready=None):
    task = asyncio.current_task()
    for signum in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(signum, task.cancel)
    relay = Relay(container)
    address, port = editor_settings.connection(state, preferences)
    context = editor_settings.tls_context(preferences)
    relay.scheme = 'https' if context else 'http'
    try:
        server = await asyncio.start_server(relay.handle, address, port, ssl=context, limit=16384)
    except OSError:
        if preferences['port'] or not port:
            raise
        server = await asyncio.start_server(relay.handle, address, 0, ssl=context, limit=16384)
    port = server.sockets[0].getsockname()[1]
    relay.host = editor_settings.authority(address, port)
    editor = None
    try:
        helper = (Path(__file__).parent / 'containers/editor/launch.py').read_text()
        editor = await asyncio.create_subprocess_exec('podman', 'exec', '-i', '--user', 'node',
            container, 'python3', '-u', '-c', helper, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, start_new_session=True)
        editor.stdin.write((json.dumps({'binary': INSTALL + '/bin/code-server',
                                      'cwd': cwd, 'authority': relay.host, 'password_hash': preferences['password_hash']}) + '\n').encode())
        await editor.stdin.drain()
        status = await asyncio.wait_for(editor.stdout.readline(), 60)
        if status != b'ready\n':
            raise ValueError('Browser editor did not start; see the error above')
        (state / 'browser-editor.enabled').touch(mode=0o600)
        editor_settings.remember_connection(state, preferences, address, port)
        url = relay.scheme + '://' + relay.host
        write_json(state / 'browser-editor-runtime.json', {
            'pid': os.getpid(), 'start': process_start(os.getpid()), 'url': url,
            'container': container, 'preferences': preferences,
        })
        if ready:
            ready(url)
        else:
            print(f'Browser editor: {url}\nCtrl+C stops the browser editor.', flush=True)
        # The attached exec exits when its container stops.
        await editor.wait()
        if editor.returncode not in (None, 0):
            raise ValueError('Browser editor stopped; see the error above')
    finally:
        (state / 'browser-editor-runtime.json').unlink(missing_ok=True)
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


def open_browser_editor(config, state, archive=None, background=False, open_tab=True):
    from . import sandbox, folders
    if config['engine'] != 'podman':
        raise ValueError('The browser editor prototype requires rootless Podman on x86_64 Linux')
    current = sandbox.inspect(config, sandbox.names(config)[0])
    if not current or not current['State']['Running']:
        raise ValueError('Start the sandbox before opening its browser editor')
    container = current['Id']
    preferences = editor_settings.load(state)
    preferences = editor_settings.validate({**preferences, 'mode': 'browser'})
    with (state / 'browser-editor.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            info = runtime(state)
            if info and info['container'] == container and info['preferences'] == preferences:
                show_url(info['url'], open_tab)
                return
            if not info:
                raise ValueError('The browser editor is already starting; wait for it to finish.') from None
            raise ValueError('Browser editor settings changed. Stop it from Actions and reopen it.') from None
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
        if background:
            start_background(container, folders.container_cwd(config), preferences, state, open_tab)
        else:
            try:
                asyncio.run(serve(container, folders.container_cwd(config), preferences, state))
            except (KeyboardInterrupt, asyncio.CancelledError):
                print('\nBrowser editor stopped.')


def process_start(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def runtime(state):
    try:
        value = json.loads((state / 'browser-editor-runtime.json').read_text())
        return value if active(state) and process_start(value['pid']) == value['start'] else None
    except (OSError, ValueError, KeyError):
        return None


def stop(state):
    value = runtime(state)
    if not value:
        return
    try:
        fd = os.pidfd_open(value['pid'])
    except ProcessLookupError:
        return
    try:
        if process_start(value['pid']) == value['start']:
            signal.pidfd_send_signal(fd, signal.SIGTERM)
            if not select.select([fd], [], [], 15)[0]:
                raise ValueError('Browser editor is still stopping; see browser-editor.log')
    finally:
        os.close(fd)


def show_url(url, open_tab=True):
    print('Browser editor: ' + url, flush=True)
    if open_tab and (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        import shutil
        if shutil.which('xdg-open'):
            subprocess.Popen(['xdg-open', url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, start_new_session=True)


def start_background(container, cwd, preferences, state, open_tab):
    """Fork after installation; the child inherits the locked editor descriptor."""
    read_fd, write_fd = os.pipe()
    sys.stdout.flush()
    sys.stderr.flush()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        os.setsid()
        with open(os.devnull, 'r') as source, (state / 'browser-editor.log').open('w') as log:
            os.dup2(source.fileno(), 0)
            os.dup2(log.fileno(), 1)
            os.dup2(log.fileno(), 2)
        def ready(url):
            os.write(write_fd, (url + '\n').encode())
            os.close(write_fd)
        try:
            asyncio.run(serve(container, cwd, preferences, state, ready))
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(0)
    os.close(write_fd)
    try:
        if not select.select([read_fd], [], [], 75)[0]:
            os.kill(pid, signal.SIGTERM)
            os.waitpid(pid, 0)
            raise ValueError('Browser editor did not become ready; see browser-editor.log')
        url = os.read(read_fd, 4096).decode().strip()
        if not url.startswith(('http://', 'https://')):
            os.waitpid(pid, 0)
            raise ValueError('Browser editor failed to start; see ' + str(state / 'browser-editor.log'))
        show_url(url, open_tab)
    finally:
        os.close(read_fd)
