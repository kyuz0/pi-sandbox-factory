"""Fixed SSH TCP relays and a separate OpenSSH agent. No remote command API."""
import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess

SOCKETS = Path('/run/ssh-access')
os.umask(0o077)

async def relay(reader, writer, host):
    remote = None
    async def pump(source, target):
        try:
            while data := await source.read(65536):
                target.write(data)
                await target.drain()
        finally:
            if target.can_write_eof():
                target.write_eof()
    try:
        upstream, remote = await asyncio.wait_for(asyncio.open_connection(host['hostname'], host['port']), 15)
        await asyncio.gather(pump(reader, remote), pump(upstream, writer))
    except (OSError, asyncio.TimeoutError, ConnectionError):
        pass
    finally:
        for connection in (writer, remote):
            if connection:
                connection.close()
                try: await connection.wait_closed()
                except OSError: pass

async def main():
    settings = json.loads(Path('/etc/ssh-access/targets.json').read_text())
    SOCKETS.mkdir(exist_ok=True)
    SOCKETS.chmod(0o700)
    for path in SOCKETS.glob('*.sock'):
        path.unlink()
    agent = subprocess.Popen(['ssh-agent', '-D', '-a', str(SOCKETS / 'agent.sock'), '-P', ''], stdout=subprocess.DEVNULL)
    servers = []
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)
    try:
        for _ in range(100):
            if agent.poll() is not None: raise RuntimeError('SSH agent exited')
            if (SOCKETS / 'agent.sock').exists(): break
            await asyncio.sleep(.05)
        else: raise RuntimeError('SSH agent socket unavailable')
        for host in settings:
            path = SOCKETS / (host['alias'] + '.sock')
            server = await asyncio.start_unix_server(lambda r,w,h=host: relay(r,w,h), path=path, limit=65536)
            path.chmod(0o600)
            servers.append(server)
        if Path('/private/id_key').exists():
            # Unencrypted keys load unattended; encrypted keys require Unlock in the manager.
            result = await asyncio.create_subprocess_exec('python3', '/opt/ssh-access/unlock.py', stdin=subprocess.DEVNULL,
                                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            await result.wait()
        print('SSH access ready', flush=True)
        while not stopped.is_set():
            if agent.poll() is not None: raise RuntimeError('SSH agent exited')
            try: await asyncio.wait_for(stopped.wait(), 1)
            except asyncio.TimeoutError: pass
    finally:
        for server in servers: server.close()
        await asyncio.gather(*(server.wait_closed() for server in servers))
        agent.terminate()
        try: agent.wait(timeout=5)
        except subprocess.TimeoutExpired: agent.kill(); agent.wait()

if __name__ == '__main__':
    asyncio.run(main())
