"""Boundary checks for the opt-in browser editor relay."""
import asyncio
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from pi_sandbox_factory import browser_editor as editor

HOST = '127.12.34.56:12345'


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
                   head(headers='X-Large: ' + 'x' * 17000 + '\r\n')]
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
            return await asyncio.create_subprocess_exec('cat', stdin=asyncio.subprocess.PIPE,
                                                       stdout=asyncio.subprocess.PIPE)
        relay.connector = connect
        server = await asyncio.start_server(relay.handle, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        relay.host = f'127.0.0.1:{port}'
        try:
            reader, writer = await asyncio.open_connection('127.0.0.1', port)
            request = head('/?reconnectionToken=fixture', host=relay.host)
            writer.write(request + b'\x82\x03abc')
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(len(request) + 5), 5), request + b'\x82\x03abc')
            writer.close()
            await writer.wait_closed()
        finally:
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
                command = ['cat']
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
            task = asyncio.create_task(editor.serve('a' * 64, '/workspace', 'test'))
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
                self.assertEqual(await reader.readexactly(len(request)), request)
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
                for process in processes:
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
