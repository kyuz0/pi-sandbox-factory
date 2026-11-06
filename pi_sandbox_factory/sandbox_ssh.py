"""Host-managed SSH destinations and private keys, isolated from the development container."""
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


def validate(value):
    if not isinstance(value, dict) or set(value) - {'hosts'} or not isinstance(value.get('hosts', []), list):
        raise ValueError('SSH settings require a hosts list')
    hosts = value.get('hosts', [])
    if len(hosts) > 32: raise ValueError('At most 32 SSH destinations are supported')
    seen = set()
    for host in hosts:
        if not isinstance(host, dict) or set(host) != {'alias','hostname','port','user','host_keys'}:
            raise ValueError('Each SSH destination needs alias, hostname, port, user and trusted host_keys')
        alias = host['alias']
        if not isinstance(alias, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}', alias) or alias in seen:
            raise ValueError('SSH aliases must be unique, 1–64 letters, digits, dots, hyphens or underscores')
        seen.add(alias)
        name = host['hostname']
        if not isinstance(name, str) or not name or len(name) > 253: raise ValueError('Invalid SSH hostname')
        try: ipaddress.ip_address(name)
        except ValueError:
            if any(not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', part) for part in name.split('.')):
                raise ValueError('Use an exact IP address or hostname for SSH')
        if not isinstance(host['user'], str) or not re.fullmatch(r'[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,63}', host['user']):
            raise ValueError('Invalid SSH username')
        if type(host['port']) is not int or not 1 <= host['port'] <= 65535: raise ValueError('Invalid SSH port')
        keys = host['host_keys']
        if not isinstance(keys, list) or not keys or any(not isinstance(k, str) or not re.fullmatch(r'(?:ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)) [A-Za-z0-9+/]+={0,2}', k) for k in keys):
            raise ValueError('Supply trusted plain OpenSSH host public keys; wildcard/CA entries are not accepted')
    return {'hosts': hosts}


class MissingHostKey(ValueError): pass

def trusted_keys(hostname, port, known_hosts):
    target = hostname if port == 22 else f'[{hostname}]:{port}'
    if not Path(known_hosts).expanduser().is_file(): raise MissingHostKey('Known hosts file not found')
    result = subprocess.run(['ssh-keygen', '-F', target, '-f', str(Path(known_hosts).expanduser())], capture_output=True, text=True)
    if result.returncode not in (0, 1): raise ValueError('Could not read the selected known_hosts file')
    keys = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if not fields or fields[0].startswith('#'): continue
        if fields[0].startswith('@'): raise ValueError('Marked host-key entries need explicit review; import a trusted plain host key')
        if len(fields) >= 3: keys.append(' '.join(fields[1:3]))
    if not keys: raise MissingHostKey(f'No trusted host key for {hostname}. Verify this host from your host terminal first.')
    return sorted(set(keys))


def parse_hosts(text, known_hosts):
    hosts = []
    for line in text.splitlines():
        fields = line.split('#',1)[0].split()
        if not fields: continue
        if len(fields) not in (3,4): raise ValueError('Use: alias username hostname-or-IP [port]')
        alias,user,hostname = fields[:3]
        try: port = int(fields[3]) if len(fields) == 4 else 22
        except ValueError: raise ValueError('SSH port must be a number')
        # Validate targets before passing them to OpenSSH helpers.
        item = {'alias':alias,'user':user,'hostname':hostname,'port':port,'host_keys':['ssh-ed25519 AAAA']}
        validate({'hosts':[item]})
        item['host_keys'] = trusted_keys(hostname,port,known_hosts)
        hosts.append(item)
    return validate({'hosts':hosts})


def import_aliases(aliases, ssh_config=None):
    hosts = []
    for alias in aliases.split():
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}', alias): raise ValueError('Invalid SSH alias')
        args = ['ssh'] + (['-F',str(Path(ssh_config).expanduser())] if ssh_config else []) + ['-G',alias]
        result = subprocess.run(args, capture_output=True, text=True, check=True)
        config = {}
        for line in result.stdout.splitlines():
            key,_,value = line.partition(' '); config.setdefault(key,[]).append(value)
        if config.get('proxyjump',['none'])[0] != 'none' or config.get('proxycommand',['none'])[0] != 'none':
            raise ValueError('SSH jump/proxy configurations are not supported; declare a directly reachable destination')
        hostname,user,port = config['hostname'][0],config['user'][0],int(config['port'][0])
        keys = []
        for path in config.get('userknownhostsfile',['~/.ssh/known_hosts'])[0].split():
            try: keys += trusted_keys(config.get('hostkeyalias',[hostname])[0],port,path)
            except MissingHostKey: pass
        if not keys: raise ValueError(f'No trusted host key for {alias}; verify it in your host terminal first')
        hosts.append({'alias':alias,'hostname':hostname,'user':user,'port':port,'host_keys':sorted(set(keys))})
    return validate({'hosts':hosts})


def enabled(config): return bool(config.get('ssh',{}).get('hosts'))


def names(config):
    prefix = 'pi-sandbox-factory-' + config['name'] + '-ssh'
    return prefix, prefix+'-socket', prefix+'-keys'


def image(config):
    from . import sandbox as core
    return f'localhost/pi-sandbox-factory-ssh:{config["uid"]}-{config["gid"]}-{core.tree_digest(core.ROOT / "containers/ssh-access")}'


def build(config):
    if not enabled(config): return
    from . import sandbox as core
    core.run([config['engine'],'build','-t',image(config),'--build-arg',f'USER_UID={config["uid"]}',
              '--build-arg',f'USER_GID={config["gid"]}',core.ROOT/'containers/ssh-access'])


def check_ownership(config):
    from . import sandbox as core
    worker,*volumes=names(config)
    core.inspect(config,worker)
    for volume in volumes:
        r=core.run([config['engine'],'volume','inspect',volume],capture=True,check=False,stderr=subprocess.DEVNULL)
        if r.returncode==0 and (json.loads(r.stdout)[0].get('Labels') or {}).get(core.LABEL)!=config['name']:
            raise ValueError('Refusing to manage unrelated SSH volume: '+volume)


def client_config(hosts):
    lines=[]
    for h in hosts:
        lines += [f'Host {h["alias"]}',f'  HostName {h["hostname"]}',f'  User {h["user"]}',f'  Port {h["port"]}',
                  f'  HostKeyAlias {h["alias"]}',f'  ProxyCommand socat - UNIX-CONNECT:/run/ssh-access/{h["alias"]}.sock',
                  '  IdentityAgent /run/ssh-access/agent.sock','  IdentityFile none',
                  '  UserKnownHostsFile /etc/sandbox-ssh/known_hosts','  StrictHostKeyChecking yes',
                  '  PasswordAuthentication no','  KbdInteractiveAuthentication no','  BatchMode yes',
                  '  ForwardAgent no','  ClearAllForwardings yes']
    return '\n'.join(lines)+ '\n'


def up(config,state):
    if not enabled(config): return
    from . import sandbox as core
    hosts=validate(config['ssh'])['hosts'];check_ownership(config)
    worker,socket,keys=names(config);engine=config['engine'];target=state/'ssh';target.mkdir(exist_ok=True,mode=0o700)
    (target/'targets.json').write_text(json.dumps(hosts));(target/'targets.json').chmod(0o644)
    (target/'known_hosts').write_text(''.join(f'{h["alias"]} {key}\n' for h in hosts for key in h['host_keys']))
    (target/'known_hosts').chmod(0o644)
    (target/'config').write_text(client_config(hosts));(target/'config').chmod(0o644)
    for volume in (socket,keys):
        if core.run([engine,'volume','inspect',volume],capture=True,check=False,stderr=subprocess.DEVNULL).returncode:
            core.run([engine,'volume','create','--label',f'{core.LABEL}={config["name"]}',volume])
    existing=core.inspect(config,worker)
    if existing: core.resume_existing(config,worker,existing)
    else:
        args=[engine,'run','-d','--name',worker,'--label',f'{core.LABEL}={config["name"]}',
              '--cap-drop=ALL','--security-opt=no-new-privileges','--security-opt=label=disable','--memory=128m','--pids-limit=64',
              '--user',f'{config["uid"]}:{config["gid"]}','-v',f'{socket}:/run/ssh-access','-v',f'{keys}:/private',
              '-v',f'{target}:/etc/ssh-access:ro']
        if engine=='podman':args+=['--userns=keep-id:uid=1000,gid=1000']
        core.run(args+[image(config)])
    for _ in range(80):
        r=core.run([engine,'exec',worker,'test','-S','/run/ssh-access/'+hosts[-1]['alias']+'.sock'],capture=True,check=False,stderr=subprocess.DEVNULL)
        if r.returncode==0:return
        time.sleep(.25)
    raise ValueError('SSH service did not become ready; inspect its container logs')


def mounts(config,state):
    if not enabled(config):return []
    return ['-v',f'{names(config)[1]}:/run/ssh-access:ro','-v',f'{state / "ssh"}:/etc/sandbox-ssh:ro',
            '--env','SSH_AUTH_SOCK=/run/ssh-access/agent.sock']


def down(config,remove=False):
    from . import sandbox as core
    check_ownership(config);worker=names(config)[0]
    if core.inspect(config,worker):core.run([config['engine'],'rm','-f',worker] if remove else [config['engine'],'stop',worker])


def delete_volumes(config):
    from . import sandbox as core
    check_ownership(config)
    for volume in names(config)[1:]:
        if core.run([config['engine'],'volume','inspect',volume],capture=True,check=False,stderr=subprocess.DEVNULL).returncode==0:
            core.run([config['engine'],'volume','rm',volume])


def unlock(config,state):
    if not enabled(config):raise ValueError('Configure SSH destinations first')
    from . import sandbox as core
    up(config,state)
    tty=['-it'] if sys.stdin.isatty() else ['-i']
    core.run([config['engine'],'exec']+tty+[names(config)[0],'python3','/opt/ssh-access/unlock.py'])


def import_key(config,state,path):
    if not enabled(config):raise ValueError('Configure SSH destinations first')
    source=Path(path).expanduser().resolve(strict=True)
    if not source.is_file() or not 0 < source.stat().st_size <= 65536:raise ValueError('Select an SSH private key file under 64 KiB')
    for field in ('workspace', 'pi_config'):
        if config.get(field):
            exposed = Path(config[field]).resolve()
            if source == exposed or exposed in source.parents:
                raise ValueError('Choose a key outside the workspace and shared Pi configuration; those paths are visible to the agent')
    from . import sandbox as core
    up(config,state)
    # No key bytes in argv, environment, logs, project state, or the development container.
    script="import os,sys;from pathlib import Path;os.umask(0o077);p=Path('/private/id_key.new');p.unlink(missing_ok=True);f=p.open('xb');f.write(sys.stdin.buffer.read(65537));f.close();p.replace('/private/id_key')"
    with source.open('rb') as stream:
        core.run([config['engine'],'exec','-i',names(config)[0],'python3','-c',script],stdin=stream)
    print('Key imported into the private SSH companion. Unlocking for the declared destinations.',flush=True)
    unlock(config,state)
