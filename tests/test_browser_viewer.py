import asyncio
import hashlib
import hmac
import unittest
from unittest.mock import AsyncMock

from vscode_pi_sandbox.browser_viewer import Viewer, route

KEY = 'b' * 64
SESSION = 'a' * 32
TOKEN = hmac.new(KEY.encode(), SESSION.encode(), hashlib.sha256).hexdigest()
BASE = f'/v/{SESSION}/{TOKEN}/'
HOST = '127.0.0.1:43210'


def request(path='', headers='', host=HOST):
    return f'GET {BASE}{path} HTTP/1.1\r\nHost: {host}\r\n{headers}\r\n'.encode()


class RouteTests(unittest.TestCase):
    def test_index_assets_and_websocket(self):
        self.assertEqual(route(request(), HOST, KEY)[1], '')
        self.assertEqual(route(request('devtools/entrypoints/inspector/inspector.js'), HOST, KEY)[1],
                         'devtools/entrypoints/inspector/inspector.js')
        headers = (f'Origin: http://{HOST}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                   'Sec-WebSocket-Version: 13\r\nSec-WebSocket-Key: aaaaaaaaaaaaaaaaaaaaaa==\r\n')
        self.assertTrue(route(request('devtools/page/ABC123', headers), HOST, KEY)[3])

    def test_reject_invalid_requests(self):
        invalid = [request(host='evil.test'), request().replace(TOKEN.encode(), b'0'*64),
                   request(headers='Origin: https://evil.test\r\n'),
                   request(headers=f'Host: {HOST}\r\n'),
                   request(headers='Content-Length: 0\r\n'),
                   request(headers='Transfer-Encoding: chunked\r\n'),
                   request(headers='X-Test: bad\x00value\r\n'),
                   request('devtools/page/ABC123', 'Upgrade: websocket\r\n'),
                   request('json/list'), request('devtools/browser/ABC'),
                   request('devtools/../json/list'), request('devtools/%2e%2e/json/list'),
                   request('devtools//inspector.html'), request('devtools\\inspector.html'),
                   request().replace(b'GET ', b'POST ')]
        for head in invalid:
            with self.subTest(head=head), self.assertRaises(ValueError):
                route(head, HOST, KEY)


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.viewer = Viewer('podman', 'c'*64, KEY)
        self.server = await asyncio.start_server(self.viewer.handle, '127.0.0.1', 0, limit=16384)
        self.port = self.server.sockets[0].getsockname()[1]
        self.viewer.host = f'127.0.0.1:{self.port}'

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    async def send(self, data):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
        writer.write(data)
        await writer.drain()
        result = await asyncio.wait_for(reader.read(), 5)
        writer.close()
        await writer.wait_closed()
        return result

    async def test_rejected_requests_do_not_spawn_connector(self):
        self.viewer.connector = AsyncMock(side_effect=AssertionError('Must not spawn'))
        for path in ('json/list', 'devtools/browser/ABC', '../', 'devtools/%2e%2e/json/list'):
            response = await self.send(request(path, host=self.viewer.host))
            self.assertIn(b'403 Forbidden', response)
        response = await self.send(request(host=self.viewer.host).replace(TOKEN.encode(), b'0'*64))
        self.assertIn(b'403 Forbidden', response)
        self.viewer.connector.assert_not_called()

    async def test_only_first_request_forwarded(self):
        # This subprocess acts as a TCP connector, returning the request it received.
        async def connect(session):
            proc = await asyncio.create_subprocess_exec(
                'python3', '-c', 'import sys; b=b"";\nwhile not b.endswith(b"\\r\\n\\r\\n"): b+=sys.stdin.buffer.read(1)\n'
                'sys.stdout.buffer.write(b"HTTP/1.1 200 OK\\r\\nContent-Type: text/plain\\r\\nSet-Cookie: drop-me\\r\\nReporting-Endpoints: drop-me\\r\\nRefresh: drop-me\\r\\nContent-Length: "+str(len(b)).encode()+b"\\r\\n\\r\\n"+b)',
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
            self.viewer.processes.add(proc)
            return proc
        self.viewer.connector = connect
        data = request('devtools/inspector.html?ws=ignored',
                       'Cookie: secret\r\nAuthorization: secret\r\n', self.viewer.host)
        data += b'GET /json/close/victim HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n'
        response = await self.send(data)
        self.assertIn(b'200 OK', response)
        self.assertIn(b'GET /devtools/inspector.html HTTP/1.1', response)
        self.assertNotIn(b'/json/close', response)
        self.assertNotIn(b'secret', response)
        self.assertNotIn(b'drop-me', response)
        self.assertNotIn(b'ws=ignored', response)
        self.assertFalse(self.viewer.processes)
