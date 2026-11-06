"""Authenticated loopback viewer for a single owned sandbox's Chromium sessions."""
import asyncio
import base64
import fcntl
import hashlib
import hmac
import html
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import time

HELPER = '/opt/betterwright/viewer.mjs'
ID = r'[a-f0-9]{32}'


def route(head, host, key):
    """Validate before starting any container process. Return session, path, headers."""
    lines = head.decode('ascii').split('\r\n')
    method, target, version = lines.pop(0).split(' ')
    if method != 'GET' or version != 'HTTP/1.1':
        raise ValueError('GET with HTTP/1.1 is required')
    headers = {}
    for line in lines:
        if not line:
            continue
        name, value = line.split(':', 1)
        if not re.fullmatch(r'[A-Za-z0-9-]+', name) or name.lower() in headers:
            raise ValueError('Invalid headers')
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('Invalid header value')
        headers[name.lower()] = value.strip()
    if headers.get('host') != host or any(k in headers for k in ('content-length', 'transfer-encoding')):
        raise ValueError('Invalid request')
    if headers.get('origin', 'http://' + host) != 'http://' + host:
        raise ValueError('Invalid origin')
    match = re.fullmatch(r'/v/(' + ID + r')/([a-f0-9]{64})/([^?#]*)(?:\?[^#]*)?', target)
    if not match:
        raise ValueError('Invalid path')
    session, token, path = match.groups()
    expected = hmac.new(key.encode(), session.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(token, expected):
        raise ValueError('Invalid token')
    upgrade = headers.get('upgrade', '').lower() == 'websocket'
    if upgrade:
        if (headers.get('origin') != 'http://' + host or
                not re.fullmatch(r'devtools/page/[A-Fa-f0-9]+', path) or
                headers.get('sec-websocket-version') != '13' or
                not re.fullmatch(r'[A-Za-z0-9+/]{22}==', headers.get('sec-websocket-key', ''))):
            raise ValueError('Invalid WebSocket request')
    elif path and (not path.startswith('devtools/') or
                   not re.fullmatch(r'[a-zA-Z0-9_./-]+', path) or
                   any(part in ('.', '..', '') for part in path.split('/')) or
                   path.startswith(('devtools/browser/', 'devtools/page/'))):
        raise ValueError('Invalid asset path')
    return session, path, headers, upgrade


class Viewer:
    def __init__(self, engine, container, key):
        self.engine, self.container, self.key = engine, container, key
        self.host = ''
        self.connections = set()
        self.processes = set()

    async def connector(self, session):
        proc = await asyncio.create_subprocess_exec(
            self.engine, 'exec', '-i', '--user', 'node', self.container,
            'node', HELPER, 'connect', session, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        self.processes.add(proc)
        return proc

    async def finish(self, proc):
        if proc is None:
            return
        if proc.stdin:
            proc.stdin.close()
        if proc.returncode is None:
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), 5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        self.processes.discard(proc)

    async def index(self, session, base):
        proc = await self.connector(session)
        try:
            proc.stdin.write(b'GET /json/list HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n')
            await proc.stdin.drain()
            raw = await asyncio.wait_for(proc.stdout.readuntil(b'\r\n\r\n'), 15)
            if not raw.startswith(b'HTTP/1.1 200 '):
                raise ValueError('Browser is unavailable')
            length = re.search(rb'(?im)^content-length:\s*(\d+)', raw)
            if not length or int(length[1]) > 1024 * 1024:
                raise ValueError('Invalid tab list')
            tabs = json.loads(await asyncio.wait_for(proc.stdout.readexactly(int(length[1])), 15))
            rows = []
            for tab in tabs:
                target = tab.get('id', '')
                if tab.get('type') != 'page' or not re.fullmatch(r'[A-Fa-f0-9]+', target):
                    continue
                ws = self.host + base + 'devtools/page/' + target
                href = base + 'devtools/inspector.html?ws=' + ws
                rows.append(f'<li><a href="{html.escape(href, quote=True)}">{html.escape(tab.get("title") or "Untitled tab")}</a><br><small>{html.escape(tab.get("url", ""))}</small></li>')
            return ('<!doctype html><meta charset="utf-8"><title>Sandbox browser</title>'
                    '<meta name="viewport" content="width=device-width"><style>'
                    'body{font:18px system-ui;max-width:55rem;margin:3rem auto;padding:1rem}'
                    'li{margin:1.5rem 0}small{overflow-wrap:anywhere}</style>'
                    '<h1>Sandbox browser</h1><p>Select a tab to view and interact with it. '
                    'Use the screencast panel in DevTools; its top-left toggle shows the page.</p>'
                    '<p><a href="' + base + '">Reload tab list</a></p><ul>' + ''.join(rows) +
                    '</ul><p>This link grants control of this browser session. Keep it private.</p>').encode()
        finally:
            await self.finish(proc)

    async def handle(self, reader, writer):
        if len(self.connections) >= 32:
            writer.close()
            return
        task = asyncio.current_task()
        self.connections.add(task)
        proc = None
        started = False
        try:
            head = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 10)
            if len(head) > 16384:
                raise ValueError('Headers too large')
            session, path, headers, upgrade = route(head, self.host, self.key)
            if not path:
                token = hmac.new(self.key.encode(), session.encode(), hashlib.sha256).hexdigest()
                body = await self.index(session, f'/v/{session}/{token}/')
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n'
                             b"Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'\r\n"
                             b'Referrer-Policy: no-referrer\r\nCache-Control: no-store\r\nConnection: close\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
                await writer.drain()
                return
            proc = await self.connector(session)
            request = f'GET /{path} HTTP/1.1\r\nHost: 127.0.0.1\r\n'
            if upgrade:
                request += ('Connection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Version: 13\r\n'
                            'Sec-WebSocket-Key: ' + headers['sec-websocket-key'] + '\r\n')
            else:
                request += 'Connection: close\r\n'
            proc.stdin.write((request + '\r\n').encode())
            await proc.stdin.drain()
            # Forward neither cookies nor Origin. Chromium sees a local connection.
            response = await asyncio.wait_for(proc.stdout.readuntil(b'\r\n\r\n'), 20)
            status, *lines = response[:-4].split(b'\r\n')
            fields = {}
            for line in lines:
                name, sep, value = line.partition(b':')
                if not sep:
                    raise ValueError('Invalid browser response')
                fields.setdefault(name.lower(), []).append(value.strip())
            if upgrade:
                accept = base64.b64encode(hashlib.sha1((headers['sec-websocket-key'] +
                    '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
                if not status.startswith(b'HTTP/1.1 101 ') or fields.get(b'sec-websocket-accept') != [accept]:
                    raise ValueError('Invalid browser WebSocket response')
                response = (b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                            b'Sec-WebSocket-Accept: ' + accept + b'\r\n\r\n')
            else:
                length, ctype = fields.get(b'content-length', []), fields.get(b'content-type', [])
                if (not status.startswith(b'HTTP/1.1 200 ') or len(length) != 1 or
                        not re.fullmatch(rb'\d{1,9}', length[0]) or int(length[0]) > 32 * 1024 * 1024 or
                        len(ctype) != 1 or not re.fullmatch(rb'[\w.+-]+/[\w.+-]+(; ?charset=[\w-]+)?', ctype[0])):
                    raise ValueError('Invalid asset response')
                remaining = int(length[0])
                csp = ("default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; "
                       "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                       "font-src 'self'; connect-src 'self' ws://" + self.host + "; "
                       "worker-src 'self' blob:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
                response = (b'HTTP/1.1 200 OK\r\nContent-Type: ' + ctype[0] + b'\r\nContent-Length: ' + length[0] +
                            b'\r\nX-Content-Type-Options: nosniff\r\nReferrer-Policy: no-referrer\r\n'
                            b'Cache-Control: no-store\r\nConnection: close\r\nContent-Security-Policy: ' + csp.encode() + b'\r\n\r\n')
            writer.write(response)
            await writer.drain()
            started = True
            async def outward():
                while data := await proc.stdout.read(65536):
                    writer.write(data)
                    await writer.drain()
            if upgrade:
                async def inward():
                    while data := await reader.read(65536):
                        proc.stdin.write(data)
                        await proc.stdin.drain()
                tasks = [asyncio.create_task(inward()), asyncio.create_task(outward())]
                try:
                    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for child in tasks:
                        child.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
            else:
                # Never read further client bytes; forward exactly one framed response.
                while remaining:
                    data = await asyncio.wait_for(proc.stdout.read(min(65536, remaining)), 30)
                    if not data:
                        raise ValueError('Incomplete asset response')
                    writer.write(data)
                    await writer.drain()
                    remaining -= len(data)
        except (ValueError, UnicodeError, asyncio.IncompleteReadError, asyncio.LimitOverrunError,
                asyncio.TimeoutError, ConnectionError, OSError):
            if not started:
                writer.write(b'HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n')
        finally:
            await self.finish(proc)
            writer.close()
            self.connections.discard(task)

    async def serve(self, ready, stopping):
        address = '127.' + '.'.join(str(secrets.randbelow(254) + 1) for _ in range(3))
        server = await asyncio.start_server(self.handle, address, 0, limit=16384)
        self.host = address + ':' + str(server.sockets[0].getsockname()[1])
        proc = await asyncio.create_subprocess_exec(
            self.engine, 'exec', '-i', '--user', 'node', self.container, 'node', HELPER,
            'set-descriptor', stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE)
        _, error = await proc.communicate(json.dumps({'origin': 'http://' + self.host, 'key': self.key}).encode())
        if proc.returncode:
            server.close()
            raise RuntimeError(error.decode().strip())
        ready()
        waiter = await asyncio.create_subprocess_exec(self.engine, 'wait', self.container,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            await waiter.wait()
        finally:
            stopping()
            server.close()
            for task in list(self.connections):
                task.cancel()
            await asyncio.gather(*self.connections, return_exceptions=True)
            for child in list(self.processes):
                await self.finish(child)
            if waiter.returncode is None:
                waiter.terminate()
                await waiter.wait()
            await server.wait_closed()


def ensure_viewer(engine, container):
    """Start once per immutable container id; its lifetime follows the container."""
    if engine not in ('podman', 'docker') or not re.fullmatch(r'[a-f0-9]{64}', container):
        raise ValueError('Invalid viewer container')
    runtime = Path(tempfile.gettempdir()) / f'vscode-pi-viewers-{os.getuid()}'
    runtime.mkdir(mode=0o700, exist_ok=True)
    info = runtime.lstat()
    if not runtime.is_dir() or runtime.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('Browser viewer runtime directory must be private')
    started = subprocess.check_output([engine, 'inspect', '--format', '{{.State.StartedAt}}', container], text=True).strip()
    # Child holds the lock and acknowledges only after descriptor delivery.
    import selectors
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), engine, container,
                             str(runtime / (container + '.lock')), started],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
    with selectors.DefaultSelector() as selector:
        selector.register(proc.stdout, selectors.EVENT_READ)
        if not selector.select(30):
            proc.terminate()
            raise ValueError('Browser viewer did not start within 30 seconds')
        result = proc.stdout.readline().decode().strip()
    proc.stdout.close()
    if result != 'ready':
        proc.wait(timeout=5)
        raise ValueError('Browser viewer could not start: ' + result)


def main():
    engine, container, lock_path, started = sys.argv[1:]
    marker = 'ready:' + started
    with open(lock_path, 'a+') as lock:
        for _ in range(120):
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                lock.seek(0)
                if lock.read() == marker:
                    print('ready', flush=True)
                    return
                time.sleep(0.25)
        else:
            raise RuntimeError('Another browser viewer is still starting')
        lock.seek(0)
        lock.truncate()
        viewer = Viewer(engine, container, secrets.token_hex(32))
        # Notify the launcher and concurrent starts only when the server is ready.
        def ready():
            lock.write(marker)
            lock.flush()
            print('ready', flush=True)
            with open(os.devnull, 'w') as sink:
                os.dup2(sink.fileno(), 1)
                os.dup2(sink.fileno(), 2)
        def stopping():
            lock.seek(0)
            lock.truncate()
            lock.flush()
        async def serve():
            task = asyncio.current_task()
            for sig in (signal.SIGTERM, signal.SIGINT):
                asyncio.get_running_loop().add_signal_handler(sig, task.cancel)
            try:
                await viewer.serve(ready, stopping)
            except asyncio.CancelledError:
                pass
        asyncio.run(serve())



if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('error: ' + str(error), flush=True)
        sys.exit(1)
