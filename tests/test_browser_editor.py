"""Boundary checks for the browser editor relay."""
import asyncio
import hashlib
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from pi_sandbox_factory import browser_editor as editor

HOST = '127.12.34.56:12345'


FAKE_SERVER = r"""
import os, sys
stream = sys.stdin.buffer
while True:
    head = b''
    while not head.endswith(b'\r\n\r\n'):
        line = stream.readline()
        if not line: sys.exit()
        head += line
    length = next((int(line.split(b':',1)[1]) for line in head.split(b'\r\n') if line.lower().startswith(b'content-length:')), 0)
    body = stream.read(length)
    if b'Upgrade: websocket' in head:
        os.write(1, b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n')
        while True:
            data = os.read(0, 65536)
            if not data: sys.exit()
            os.write(1, data)
    elif b' /echo ' in head:
        os.write(1, b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(body)).encode() + b'\r\nSet-Cookie: fixture=value; HttpOnly\r\n\r\n' + body)
    elif b' /chunked ' in head:
        os.write(1, b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\nOK\r\n3\r\nend\r\n0\r\nX-Trailer: yes\r\n\r\n')
    elif head.startswith(b'HEAD '):
        os.write(1, b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n')
    else:
        os.write(1, b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK')
"""

def head(target='/', headers='', host=HOST):
    return f'GET {target} HTTP/1.1\r\nHost: {host}\r\n{headers}\r\n'.encode()


class Requests(unittest.TestCase):
    def test_browser_and_websocket_headers(self):
        editor.validate_head(head(), HOST)
        editor.validate_head(head('/?folder=/workspace', f'Origin: http://{HOST}\r\nUpgrade: websocket\r\n'), HOST)

    def test_foreign_origin_rebinding_and_invalid_headers(self):
        invalid = [head(host='attacker.test'), head(headers='Origin: https://attacker.test\r\n'),
                   head(headers='Origin: null\r\n'), head('https://attacker.test/'), head('//attacker.test/'),
                   head(headers=f'Host: {HOST}\r\n'), head(headers='Forwarded: host=attacker.test\r\n'),
                   head(headers='X-Forwarded-Host: attacker.test\r\n'), head(headers='X-Bad: x\x00y\r\n'),
                   head(headers='X-Large: ' + 'x' * 17000 + '\r\n'),
                   head(headers='Sec-Fetch-Site: cross-site\r\n'), head(headers='Sec-Fetch-Site: same-site\r\n'),
                   head(headers='Transfer-Encoding: chunked\r\n'), head(headers='Expect: 100-continue\r\n')]
        for request in invalid:
            with self.subTest(request=request[:100]), self.assertRaises(ValueError):
                editor.validate_head(request, HOST)

    def test_archive_integrity(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'archive'
            file.write_bytes(b'fixture')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                editor.verify_archive(file)
            with patch.object(editor, 'SHA256', hashlib.sha256(b'fixture').hexdigest()):
                self.assertEqual(editor.checked_archive(Path(folder), str(file)), file)

    def test_host_session_lock(self):
        import fcntl
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            self.assertFalse(editor.active(state))
            with (state / 'browser-editor.lock').open('a+') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                self.assertTrue(editor.active(state))
            self.assertFalse(editor.active(state))


class RelayChecks(unittest.IsolatedAsyncioTestCase):
    async def test_connector_is_fixed_and_container_id_required(self):
        with self.assertRaises(ValueError):
            editor.Relay('name; command')
        relay = editor.Relay('a' * 64)
        with patch.object(asyncio, 'create_subprocess_exec', new_callable=AsyncMock) as spawn:
            await relay.connector()
            self.assertEqual(spawn.call_args.args, ('podman', 'exec', '-i', '--user', 'node',
                'a' * 64, 'socat', 'STDIO', 'UNIX-CONNECT:' + editor.SOCKET))

    async def test_invalid_request_never_reaches_container(self):
        relay = editor.Relay('a' * 64)
        relay.connector = AsyncMock(side_effect=AssertionError('No exec for rejected request'))
        server = await asyncio.start_server(relay.handle, '127.0.0.1', 0, limit=16384)
        port = server.sockets[0].getsockname()[1]
        relay.host = f'127.0.0.1:{port}'
        try:
            reader, writer = await asyncio.open_connection('127.0.0.1', port)
            writer.write(head(host='attacker.test'))
            await writer.drain()
            self.assertIn(b'403 Forbidden', await reader.read())
            writer.close()
            await writer.wait_closed()
            relay.connector.assert_not_called()
        finally:
            server.close()
            await server.wait_closed()
            await relay.close()

    async def test_relay_preserves_http_body_and_websocket_bytes(self):
        relay = editor.Relay('a' * 64)
        async def connect():
            return await asyncio.create_subprocess_exec(sys.executable, '-u', '-c', FAKE_SERVER,
                                                       stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
        relay.connector = connect
        server = await asyncio.start_server(relay.handle, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        relay.host = f'127.0.0.1:{port}'
        try:
            reader, writer = await asyncio.open_connection('127.0.0.1', port)
            request = head('/?reconnectionToken=fixture', headers='Upgrade: websocket\r\nConnection: Upgrade\r\n', host=relay.host)
            writer.write(request)
            await writer.drain()
            self.assertIn(b'101 Switching Protocols', await reader.readuntil(b'\r\n\r\n'))
            writer.write(b'\x82\x03abc')
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(5), 5), b'\x82\x03abc')
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()
            await relay.close()

    async def test_keepalive_body_chunks_cookies_and_second_request_validation(self):
        relay = editor.Relay('a' * 64)
        async def connect():
            return await asyncio.create_subprocess_exec(sys.executable, '-u', '-c', FAKE_SERVER,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
        relay.connector = AsyncMock(side_effect=connect)
        relay.scheme = 'https'
        server = await asyncio.start_server(relay.handle, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        relay.host = f'127.0.0.1:{port}'
        reader, writer = await asyncio.open_connection('127.0.0.1', port)
        try:
            writer.write(head('/echo', 'Content-Length: 7\r\n', relay.host).replace(b'GET ', b'POST ', 1) + b'payload')
            await writer.drain()
            self.assertIn(b'HttpOnly; Secure', await reader.readuntil(b'\r\n\r\n'))
            self.assertEqual(await reader.readexactly(7), b'payload')
            writer.write(head('/chunked', host=relay.host))
            await writer.drain()
            self.assertIn(b'Transfer-Encoding: chunked', await reader.readuntil(b'\r\n\r\n'))
            self.assertEqual(await reader.readuntil(b'X-Trailer: yes\r\n\r\n'),
                b'2\r\nOK\r\n3\r\nend\r\n0\r\nX-Trailer: yes\r\n\r\n')
            writer.write(head(host=relay.host).replace(b'GET ', b'HEAD ', 1))
            await writer.drain()
            self.assertIn(b'200 OK', await reader.readuntil(b'\r\n\r\n'))
            writer.write(head(host='other.example'))
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.read(), 5), b'')
            relay.connector.assert_awaited_once()
        finally:
            writer.close()
            await writer.wait_closed()
            server.close()
            await server.wait_closed()
            await relay.close()

class ShutdownChecks(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_closes_active_browser_connection(self):
        import contextlib
        import io
        import sys
        spawn = asyncio.create_subprocess_exec
        processes = []

        async def fake_podman(*args, **kwargs):
            if 'socat' in args:
                command = [sys.executable, '-u', '-c', FAKE_SERVER]
            elif 'wait' in args:
                command = [sys.executable, '-c', 'import time; time.sleep(60)']
            else:
                command = [sys.executable, '-u', '-c',
                           'import sys; sys.stdin.readline(); print("ready"); sys.stdin.read()']
            process = await spawn(*command, **kwargs)
            processes.append(process)
            return process

        output = io.StringIO()
        loop = asyncio.get_running_loop()
        writer = None
        with patch.object(asyncio, 'create_subprocess_exec', fake_podman), \
                patch.object(loop, 'add_signal_handler'), contextlib.redirect_stdout(output):
            temporary = tempfile.TemporaryDirectory()
            state = Path(temporary.name)
            task = asyncio.create_task(editor.serve('a' * 64, '/workspace', editor.editor_settings.validate(), state))
            try:
                async def ready():
                    while 'Browser editor:' not in output.getvalue():
                        await asyncio.sleep(.01)
                await asyncio.wait_for(ready(), 5)
                authority = output.getvalue().split('http://')[1].splitlines()[0]
                host, port = authority.split(':')
                reader, writer = await asyncio.open_connection(host, int(port))
                request = head(host=authority)
                writer.write(request)
                await writer.drain()
                self.assertIn(b'200 OK', await reader.readuntil(b'\r\n\r\n'))
                self.assertEqual(await reader.readexactly(2), b'OK')
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 5)
                self.assertEqual(await asyncio.wait_for(reader.read(), 2), b'')
                self.assertTrue(all(p.returncode is not None for p in processes))
            finally:
                if writer:
                    writer.close()
                    await writer.wait_closed()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                temporary.cleanup()
                for process in processes:
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
