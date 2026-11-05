import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from vscode_pi_sandbox import sandbox
from vscode_pi_sandbox import sandbox_ssh as ssh
from vscode_pi_sandbox.sandbox_tui import GITHUB_HOSTS, PIP_HOSTS, preset_rules, preset_allowed

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
                with patch('vscode_pi_sandbox.sandbox_ssh.subprocess.run',return_value=response):
                    with self.assertRaisesRegex(ValueError,'Marked'):ssh.trusted_keys('host',22,file)

    def test_known_host_lookup_does_not_scan_or_accept_new_hosts(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'known_hosts';file.touch()
            with patch('vscode_pi_sandbox.sandbox_ssh.subprocess.run',return_value=SimpleNamespace(returncode=1,stdout='')) as run:
                with self.assertRaises(ssh.MissingHostKey):ssh.trusted_keys('example.test',2222,file)
                self.assertEqual(run.call_args.args[0],['ssh-keygen','-F','[example.test]:2222','-f',str(file)])

    def test_foreign_key_volume_blocks_lifecycle(self):
        calls=[]
        def run(args,**kwargs):
            calls.append(args);return SimpleNamespace(returncode=0,stdout=json.dumps([{'Labels':{sandbox.LABEL:'other'}}]))
        with patch.object(sandbox,'inspect',return_value=None),patch.object(sandbox,'run',side_effect=run):
            with self.assertRaisesRegex(ValueError,'unrelated'):ssh.down({'name':'test','engine':'podman'},remove=True)
        self.assertTrue(all('inspect' in call for call in calls))

    def test_github_preset_preserves_other_destinations_and_has_no_wildcards(self):
        original='local-model.internal:8000\npypi.org:443\n'
        enabled=preset_rules(original,True,GITHUB_HOSTS)
        self.assertTrue(preset_allowed(enabled,GITHUB_HOSTS))
        self.assertEqual(preset_rules(enabled,True,GITHUB_HOSTS),enabled)
        disabled=preset_rules(enabled,False,GITHUB_HOSTS)
        self.assertIn('local-model.internal:8000',disabled)
        self.assertIn('pypi.org:443',disabled)
        self.assertFalse(preset_allowed(disabled,GITHUB_HOSTS))
        self.assertFalse(any('*' in h for h,p in GITHUB_HOSTS))

    def test_github_does_not_enable_ssh_or_private_credentials(self):
        self.assertTrue(all(port==443 for _,port in GITHUB_HOSTS))
        self.assertNotIn(('ssh.github.com',443),GITHUB_HOSTS)
        self.assertFalse(GITHUB_HOSTS & PIP_HOSTS)
