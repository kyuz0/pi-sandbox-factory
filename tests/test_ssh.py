import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from pi_sandbox_factory import sandbox
from pi_sandbox_factory import sandbox_ssh as ssh

HOST={'alias':'build','hostname':'192.0.2.10','port':22,'user':'demo','host_keys':['ssh-ed25519 AAAA']}

class SSHTests(unittest.TestCase):
    def test_exact_ips_ipv6_and_hostnames(self):
        for name in ['192.0.2.10','2001:db8::1','build.example.test','build']:
            self.assertEqual(ssh.validate({'hosts':[{**HOST,'hostname':name}]})['hosts'][0]['hostname'],name)
        for name in ['*.example.test','host;touch /tmp/x','-bad','a..b','user@host','host:22']:
            with self.assertRaises(ValueError):ssh.validate({'hosts':[{**HOST,'hostname':name}]})

    def test_rejects_shell_control_in_all_target_fields(self):
        for field,value in [('alias','a/../x'),('user','root;true'),('port',True),('host_keys',['@cert-authority * ssh-ed25519 AAAA'])]:
            with self.assertRaises(ValueError):ssh.validate({'hosts':[{**HOST,field:value}]})
        with self.assertRaises(ValueError):ssh.validate({'hosts':[HOST,HOST]})
        with self.assertRaises(ValueError):ssh.validate({'hosts':[{**HOST,'command':'sh'}]})

    def test_no_credentials_or_engine_socket_in_client_mounts(self):
        config={'name':'demo','ssh':{'hosts':[HOST]}}
        mounts=' '.join(ssh.mounts(config,Path('/tmp/state')))
        self.assertIn('/run/ssh-access:ro',mounts)
        self.assertNotIn('-keys:',mounts)
        self.assertNotIn('/private',mounts)
        self.assertNotIn('podman.sock',mounts)
        self.assertEqual(ssh.mounts({'name':'demo'},Path('/tmp/state')),[])

    def test_client_pins_identity_and_uses_only_fixed_relay(self):
        config=ssh.client_config([HOST])
        for text in ['StrictHostKeyChecking yes','HostKeyAlias build','ForwardAgent no','BatchMode yes','ClearAllForwardings yes','UNIX-CONNECT:/run/ssh-access/build.sock','IdentityFile none']:
            self.assertIn(text,config)
        self.assertNotIn('/private',config)

    def test_marked_host_keys_are_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'known_hosts';file.touch()
            for marker in ['@revoked','@cert-authority']:
                response=SimpleNamespace(returncode=0,stdout=f'{marker} host ssh-ed25519 AAAA\n')
                with patch('pi_sandbox_factory.sandbox_ssh.subprocess.run',return_value=response):
                    with self.assertRaisesRegex(ValueError,'Marked'):ssh.trusted_keys('host',22,file)

    def test_known_host_lookup_does_not_scan_or_accept_new_hosts(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'known_hosts';file.touch()
            with patch('pi_sandbox_factory.sandbox_ssh.subprocess.run',return_value=SimpleNamespace(returncode=1,stdout='')) as run:
                with self.assertRaises(ssh.MissingHostKey):ssh.trusted_keys('example.test',2222,file)
                self.assertEqual(run.call_args.args[0],['ssh-keygen','-F','[example.test]:2222','-f',str(file)])

    def test_foreign_key_volume_blocks_lifecycle(self):
        calls=[]
        def run(args,**kwargs):
            calls.append(args);return SimpleNamespace(returncode=0,stdout=json.dumps([{'Labels':{sandbox.LABEL:'other'}}]))
        with patch.object(sandbox,'inspect',return_value=None),patch.object(sandbox,'run',side_effect=run):
            with self.assertRaisesRegex(ValueError,'unrelated'):ssh.down({'name':'test','engine':'podman'},remove=True)
        self.assertTrue(all('inspect' in call for call in calls))


class RepositorySetupTests(unittest.TestCase):
    def test_repository_urls_and_subgroups(self):
        value = ssh.repository_destination('https://github.com/owner/project.git')
        self.assertEqual(value, {'line': 'repository git github.com 22',
            'settings_url': 'https://github.com/owner/project/settings/keys',
            'clone': 'git clone git@repository:owner/project.git'})
        value = ssh.repository_destination('https://git.example.com/group/team/project/')
        self.assertEqual(value['settings_url'], 'https://git.example.com/group/team/project/-/settings/repository')
        self.assertEqual(value['line'], 'repository git git.example.com 22')

    def test_repository_urls_reject_injection_and_ambiguous_paths(self):
        for value in ('http://github.com/a/b', 'https://user:secret@github.com/a/b',
                      'https://github.com/a/b?tab=x', 'https://github.com/a/b#x',
                      'https://github.com/a/b/tree/main', 'https://github.com/a/../b',
                      'https://github.com/-a/b', 'https://github.com/a/b%0AProxyCommand',
                      'https://github.com/a/b\nProxyCommand touch x', 'https://github.com:443/a/b'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ssh.repository_destination(value)

    def test_key_inside_additional_mount_is_rejected_before_container_access(self):
        with tempfile.TemporaryDirectory() as temp:
            key = Path(temp) / 'key';key.write_text('fixture-private-key')
            config = {'name': 'example', 'ssh': {'hosts': [HOST]},
                      'extra_folders': [{'source': temp, 'name': 'shared', 'read_only': True}]}
            with patch.object(ssh, 'up') as up:
                with self.assertRaisesRegex(ValueError, 'outside all shared folders'):
                    ssh.import_key(config, Path(temp), key)
                up.assert_not_called()

    def test_generated_private_key_is_not_replaced_and_has_private_permissions(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('ssh_key', sandbox.ROOT / 'containers/ssh-access/key.py')
        module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            module.generate(root)
            key = root / 'id_key'
            original = key.read_bytes()
            self.assertEqual(key.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(ValueError, 'already exists'):
                module.generate(root)
            self.assertEqual(key.read_bytes(), original)
            key.unlink();key.symlink_to(root/'missing')
            with self.assertRaises(ValueError):module.generate(root)
            self.assertFalse((root/'missing').exists())

    def test_public_half_comes_from_unlocked_agent_not_imported_metadata(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('ssh_key', sandbox.ROOT / 'containers/ssh-access/key.py')
        module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with patch.object(module.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='ssh-ed25519 AAAA test\n')) as run:
            self.assertEqual(module.public_key(), 'ssh-ed25519 AAAA test')
            self.assertEqual(run.call_args.args[0], ['ssh-add', '-L'])
        with patch.object(module.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='')):
            with self.assertRaisesRegex(ValueError, 'Unlock'):module.public_key()
