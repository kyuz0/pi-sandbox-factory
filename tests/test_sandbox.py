from contextlib import closing, redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from vscode_pi_sandbox import sandbox


class LifecycleTestCase(unittest.TestCase):
    """Core lifecycle fixtures exclude companions, tested in their own suites."""
    def setUp(self):
        for module in (sandbox.sandbox_advisors, sandbox.sandbox_ssh):
            for name in ('check_ownership', 'down', 'delete_volumes'):
                patcher=patch.object(module,name)
                patcher.start();self.addCleanup(patcher.stop)


class PolicyTests(unittest.TestCase):
    def test_network_update_preserves_dev_and_rolls_back_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)
            (state/'allowlist.txt').write_text('example.com:443')
            (state/'squid.conf').write_text('old policy')
            inode=(state/'squid.conf').stat().st_ino
            config={'name':'test','engine':'podman','network':'allowlist'}
            with patch.object(sandbox,'inspect',return_value={'State':{'Running':True}}), patch.object(sandbox,'restart_existing') as restart, patch.object(sandbox,'ensure_gateway') as ready:
                sandbox.update_network(config,state,'pypi.org:443')
                restart.assert_called_once_with(config,sandbox.names(config)[1])
                self.assertEqual((state/'squid.conf').stat().st_ino,inode)
                self.assertEqual((state/'allowlist.txt').read_text(),'pypi.org:443')
                ready.side_effect=[RuntimeError('failed'),None]
                with self.assertRaises(RuntimeError):sandbox.update_network(config,state,'files.pythonhosted.org:443')
                self.assertEqual((state/'allowlist.txt').read_text(),'pypi.org:443')

    def test_network_update_rejects_removing_model_port_before_mutation(self):
        config={'name':'test','engine':'podman','network':'allowlist','local_model_ports':'8000'}
        with patch.object(sandbox,'inspect') as inspect:
            with self.assertRaises(ValueError):sandbox.update_network(config,Path('/unused'),'pypi.org:443')
            inspect.assert_not_called()


    def test_supervised_gateway_does_not_use_a_persistent_pid_file(self):
        config = sandbox.squid_config([('example.com', 443)])
        self.assertIn('pid_filename none\n', config)
        self.assertNotIn('/tmp/squid.pid', config)

    def test_saved_gateway_upgrade_preserves_policy_inode_and_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            path = state / 'squid.conf'
            expected = sandbox.squid_config([('example.com', 443)])
            path.write_text(expected.replace('pid_filename none', 'pid_filename /tmp/squid.pid'))
            path.chmod(0o640)
            before = path.stat()
            sandbox.upgrade_gateway_config(state)
            self.assertEqual(path.read_text(), expected)
            self.assertEqual(path.stat().st_ino, before.st_ino)
            self.assertEqual(path.stat().st_mode, before.st_mode)
            with patch.object(Path, 'write_text') as write:
                sandbox.upgrade_gateway_config(state)
                write.assert_not_called()

    def test_gateway_upgrade_leaves_custom_pid_directive_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            path = state / 'squid.conf'
            original = 'pid_filename /run/custom.pid\nhttp_access deny all\n'
            path.write_text(original)
            sandbox.upgrade_gateway_config(state)
            self.assertEqual(path.read_text(), original)

    def test_network_mode_is_explicit_and_old_configs_remain_restricted(self):
        self.assertEqual(sandbox.network_mode({}), 'allowlist')
        self.assertEqual(sandbox.network_mode({'network': 'unrestricted'}), 'unrestricted')
        with self.assertRaises(ValueError):
            sandbox.network_mode({'network': 'host'})

    def test_unrestricted_creation_rejects_misleading_allowlist(self):
        args = sandbox.argparse.Namespace(profile='base', network='unrestricted',
                                          allowlist=None, allow_domain=['example.com:443'])
        with self.assertRaisesRegex(ValueError, 'cannot be combined'):
            sandbox.create(args, Path('/unused'))

    def test_exact_hosts_work_without_address_class_exceptions(self):
        rules = sandbox.parse_rules('API.Example.com:443 # inference\nllm.lan:8000\n')
        self.assertEqual(rules, [('api.example.com', 443), ('llm.lan', 8000)])
        config = sandbox.squid_config(rules)
        self.assertNotIn('nonpublic', config)
        self.assertNotIn(' dst ', config)
        for i in range(2):
            self.assertLess(config.index('http_access deny !sandbox_hosts'),
                            config.index(f'http_access allow host_{i} port_{i}'))
        self.assertTrue(config.endswith('http_access deny all\n'))

    def test_old_private_suffix_is_compatible_and_has_no_special_semantics(self):
        self.assertEqual(sandbox.parse_rules('llm.lan:8000 private\nllm.lan:8000'),
                         sandbox.parse_rules('llm.lan:8000'))

    def test_reject_policy_injection_and_broad_rules(self):
        for text in ('*.example.com:443', '.example.com:443', 'example.com:0',
                     'example.com:65536', 'example.com:443 allow all', '127.0.0.1:443',
                     'https://example.com:443', 'example.com:443\nhttp_access allow all',
                     '-example.com:443', 'example..com:443', 'example.com.:443'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                sandbox.parse_rules(text)

    def test_empty_allowlist_denies_everything(self):
        config = sandbox.squid_config([])
        self.assertNotIn('http_access allow', config)
        self.assertTrue(config.endswith('http_access deny all\n'))

    def test_model_endpoint_must_be_explicitly_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'models.json').write_text('{"providers":{"test":{"baseUrl":"https://api.example.com/v1"}}}')
            sandbox.validate_models(path, [('api.example.com', 443)])
            with self.assertRaises(ValueError):
                sandbox.validate_models(path, [('example.com', 443)])
            with self.assertRaises(ValueError):
                sandbox.validate_models(path, [('api.example.com', 80)])

    def test_shared_config_can_include_blocked_providers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'models.json').write_text('{"providers":{"local":{"baseUrl":"http://localhost:8000/v1"}}}')
            rules = [('allowed.example.com', 443)]
            sandbox.validate_models(path, rules, strict=False)
            config = sandbox.squid_config(rules)
            self.assertNotIn('localhost', config)
            self.assertNotIn('8000', config)

    def test_env_is_literal_and_cannot_override_proxy_or_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'env'
            path.write_text('INFERENCE_API_KEY=a-key-with-$symbols\n')
            sandbox.validate_env(path)
            for text in ('HTTPS_PROXY=http://evil', 'NODE_OPTIONS=--require=/workspace/pwn.js',
                         'HOME=/workspace', 'BARE_VARIABLE', 'export API_KEY=abc',
                         'SANDBOX_NETWORK_MODE=unrestricted', 'SANDBOX_SUBAGENTS=1',
                         'PI_SANDBOX_CONTAINER=0', 'PI_AUTO_REVIEW_ALLOW_UNTRUSTED_DEV=1'):
                path.write_text(text)
                with self.subTest(text=text), self.assertRaises(ValueError):
                    sandbox.validate_env(path)


class ProfileTests(unittest.TestCase):
    def test_git_sources_snapshot_recorded_submodules_without_git_metadata(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'GIT_ALLOW_PROTOCOL': 'file'}):
            root = Path(tmp)
            library, upstream, profile = [root / name for name in ('library', 'upstream', 'profile')]
            def git(path, *args):
                return subprocess.check_output(['git', '-C', str(path), *args], text=True,
                                               stderr=subprocess.DEVNULL).strip()
            for repo in (library, upstream):
                repo.mkdir()
                git(repo, 'init')
                git(repo, 'config', 'user.email', 'fixture@example.com')
                git(repo, 'config', 'user.name', 'Fixture')
                (repo / 'README.md').write_text('original')
                git(repo, 'add', '.')
                git(repo, 'commit', '-m', 'fixture')
            git(upstream, 'submodule', 'add', str(library), 'library')
            git(upstream, 'commit', '-am', 'record library')
            profile.mkdir()
            (profile / 'profile.json').write_text(json.dumps(
                {'name': 'fixture', 'git_source': str(upstream)}))
            (profile / 'Dockerfile').write_text('ARG BASE_IMAGE\nFROM ${BASE_IMAGE}\n')
            (profile / 'profile.md').write_text('fixture')
            loaded = sandbox.load_profile(str(profile))
            saved = sandbox.snapshot_profile(loaded, root / 'state')
            snapshot = Path(saved['path'])
            self.assertEqual((snapshot / 'source/library/README.md').read_text(), 'original')
            self.assertFalse(any(p.name == '.git' for p in snapshot.rglob('*')))
            self.assertEqual(saved['digest'], sandbox.tree_digest(snapshot))
            self.assertEqual(saved['source_commit'], git(upstream, 'rev-parse', 'HEAD'))
            self.assertNotIn('git_source', saved)
            self.assertFalse((profile / 'source').exists())
            (library / 'README.md').write_text('new library')
            git(library, 'commit', '-am', 'update library')
            # New library HEAD must not override the revision recorded by the profile.
            same = sandbox.snapshot_profile(loaded, root / 'state')
            self.assertEqual(same['digest'], saved['digest'])
            (upstream / 'README.md').write_text('new source')
            git(upstream, 'commit', '-am', 'update source')
            updated = sandbox.snapshot_profile(loaded, root / 'state')
            self.assertNotEqual(updated['digest'], saved['digest'])
            self.assertEqual((snapshot / 'source/README.md').read_text(), 'original')
            (upstream / 'unsafe').symlink_to('/etc/hostname')
            git(upstream, 'add', 'unsafe')
            git(upstream, 'commit', '-m', 'symlink fixture')
            with self.assertRaises(ValueError):
                sandbox.snapshot_profile(loaded, root / 'state')
            self.assertFalse(any((root / 'state').glob('.profile-*')))

    def test_snapshot_keeps_original_files_when_source_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, state = Path(tmp) / 'source', Path(tmp) / 'state'
            source.mkdir()
            (source / 'profile.json').write_text('{"name":"custom"}')
            (source / 'Dockerfile').write_text('ARG BASE_IMAGE\nFROM ${BASE_IMAGE}\n')
            (source / 'profile.md').write_text('Original instructions')
            saved = sandbox.snapshot_profile(sandbox.load_profile(str(source)), state)
            (source / 'profile.md').write_text('Changed instructions')
            self.assertEqual((Path(saved['path']) / 'profile.md').read_text(), 'Original instructions')
            self.assertNotEqual(saved['digest'], sandbox.load_profile(str(source))['digest'])

    def test_custom_profiles_cannot_hide_files_outside_context_with_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            (source / 'profile.json').write_text('{"name":"custom"}')
            (source / 'Dockerfile').write_text('ARG BASE_IMAGE\nFROM ${BASE_IMAGE}\n')
            (source / 'profile.md').symlink_to('/etc/hostname')
            with self.assertRaises(ValueError):
                sandbox.load_profile(str(source))

    def test_profile_images_have_distinct_identity_and_missing_profile_uses_base(self):
        common = {'uid': 1000, 'gid': 1000}
        base = dict(common, profile=sandbox.load_profile('base'))
        alternate = dict(common, profile={**sandbox.load_profile('base'), 'digest':'different-profile'})
        self.assertNotEqual(sandbox.image_names(base)[0], sandbox.image_names(alternate)[0])
        self.assertEqual(sandbox.image_names(common), sandbox.image_names(base))


class CreationInterruptTests(LifecycleTestCase):
    def test_interrupt_during_either_source_fetch_cleans_state_and_allows_retry(self):
        profile = sandbox.load_profile('base')
        for interrupt_at in (1, 2):
            with self.subTest(fetch=interrupt_at), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                workspace = root / 'workspace'
                workspace.mkdir()
                (workspace / 'keep.txt').write_text('keep')
                state = root / 'interrupted-demo'
                args = sandbox.argparse.Namespace(profile='base', workspace=str(workspace), pi_config=None,
                    allowlist=None, allow_domain=['example.com:443'], env_file=None, engine='docker',
                    name=state.name, memory='4g')
                outcomes = [profile] * (interrupt_at - 1) + [KeyboardInterrupt()]
                with patch.object(sandbox, 'choose_engine', return_value='docker'), \
                     patch.object(sandbox.os, 'getuid', return_value=1000), \
                     patch.object(sandbox.os, 'getgid', return_value=1000), \
                     patch.object(sandbox, 'snapshot_profile', side_effect=outcomes):
                    with self.assertRaises(KeyboardInterrupt):
                        sandbox.create(args, state)
                self.assertFalse(state.exists())
                with patch.object(sandbox, 'choose_engine', return_value='docker'), \
                     patch.object(sandbox.os, 'getuid', return_value=1000), \
                     patch.object(sandbox.os, 'getgid', return_value=1000), \
                     patch.object(sandbox, 'snapshot_profile', return_value=profile):
                    sandbox.create(args, state)
                self.assertTrue((state / 'config.json').exists())
                self.assertEqual((workspace / 'keep.txt').read_text(), 'keep')

    def test_delete_recovers_missing_config_but_rejects_unrecognized_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'interrupted-demo'
            (state / 'profiles/source-snapshot').mkdir(parents=True)
            (state / '.profile-interrupted').mkdir()
            subprocess.run(['python3', str(sandbox.ROOT.parent / 'sandbox.py'), '--state-dir', tmp,
                            'delete', state.name], check=True, capture_output=True)
            self.assertFalse(state.exists())
            state.mkdir()
            (state / 'important.txt').write_text('keep')
            with self.assertRaises(ValueError):
                sandbox.delete_incomplete(state)
            self.assertEqual((state / 'important.txt').read_text(), 'keep')


class LocalModelSetupTests(unittest.TestCase):
    def test_ports_are_bounded_and_deduplicated(self):
        self.assertEqual(sandbox.local_model_ports('8000-8002,8001'), [8000,8001,8002])
        for value in ('0','65536','9000-8000','1-1000','8000,x'):
            with self.assertRaises(ValueError): sandbox.local_model_ports(value)

    def test_gateway_requires_exact_allowed_ports(self):
        c={'engine':'podman','network':'allowlist'}
        with self.assertRaises(ValueError): sandbox.configure_local_gateway(c,'8001',[('local-model.internal',8000)])
        sandbox.configure_local_gateway(c,'8001',[('local-model.internal',8001)])
        self.assertTrue(c['local_model_gateway'])
        sandbox.configure_local_gateway(c,None,[])
        self.assertFalse(c['local_model_gateway'])

    def test_gateway_rejects_unimplemented_engine_or_network(self):
        for engine,network in [('docker','allowlist'),('podman','unrestricted')]:
            with self.assertRaises(ValueError):
                sandbox.configure_local_gateway({'engine':engine,'network':network},'8000',[('local-model.internal',8000)])

    def test_configure_invokes_local_discovery(self):
        c={'engine':'podman','name':'example','state_path':'/tmp/example','local_model_ports':'8000'}
        with patch.object(sandbox,'up') as up,patch.object(sandbox,'run',return_value=subprocess.CompletedProcess([],0,'','')) as run:
            sandbox.configure_models(c)
        self.assertEqual(run.call_args.args[0][-1],'/opt/pi-local-model-manager/scripts/initialize-models.mjs')
        self.assertNotIn('-it',run.call_args.args[0])
        self.assertNotIn('pi',run.call_args.args[0])
        self.assertIn('vscode-pi-sandbox-example',run.call_args.args[0])

    def test_create_and_start_initializes_without_opening_an_editor(self):
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)/'example';state.mkdir()
            (state/'config.json').write_text(json.dumps({'name':'example','local_model_ports':'8000'}))
            calls=[]
            argv=['sandbox.py','--state-dir',temp,'create','example','--workspace','/project','--start']
            with patch('sys.argv',argv), patch.object(sandbox,'create',side_effect=lambda *a:calls.append('create')), \
                 patch.object(sandbox,'build',side_effect=lambda *a:calls.append('build')), \
                 patch.object(sandbox,'up',side_effect=lambda *a:calls.append('up')), \
                 patch.object(sandbox,'initialize_models',side_effect=lambda *a:calls.append('models')), \
                 patch.object(sandbox,'open_editor') as editor:
                sandbox.main()
            self.assertEqual(calls,['create','build','up','models']);editor.assert_not_called()

    def test_corrupt_configuration_blocks_editor_side_effects(self):
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)/'example';state.mkdir()
            config={'name':'example','engine':'podman','local_model_ports':'8000'}
            with patch.object(sandbox,'inspect',return_value={'State':{'Running':True}}), \
                 patch('shutil.which',return_value='/usr/bin/code'), \
                 patch.object(sandbox,'initialize_models',side_effect=ValueError('invalid configuration')) as initialize, \
                 patch.object(sandbox,'run') as run:
                with self.assertRaisesRegex(ValueError,'invalid configuration'):sandbox.open_editor(config,state)
            initialize.assert_called_once();run.assert_not_called()
            self.assertFalse((state/'vscode').exists())


    def test_missing_server_is_a_status_not_a_launcher_failure(self):
        config={'engine':'podman','name':'example','local_model_ports':'8000'}
        for code,error in [(3,'No usable local model'),(1,'No usable local model was discovered. Start the server.')]:
            with patch.object(sandbox,'run',return_value=subprocess.CompletedProcess([],code,'',error)), redirect_stdout(io.StringIO()) as output:
                self.assertFalse(sandbox.initialize_models(config))
            self.assertIn('Model status: Not connected',output.getvalue())
        with patch.object(sandbox,'run',return_value=subprocess.CompletedProcess([],1,'','Invalid models.json')):
            with self.assertRaisesRegex(ValueError,'Invalid models.json'):sandbox.initialize_models(config)



class DeleteTests(LifecycleTestCase):
    def test_delete_removes_only_sandbox_resources_and_preserves_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state, workspace = root / 'delete-demo', root / 'workspace'
            state.mkdir()
            workspace.mkdir()
            (state / 'config.json').write_text('{}')
            (workspace / 'report.md').write_text('keep')
            config = {'name': state.name, 'engine': 'podman', 'workspace': str(workspace)}
            volume_names = sandbox.names(config)[2:]
            with patch.object(sandbox, 'inspect', return_value={'owned': True}), \
                 patch.object(sandbox, 'run') as run:
                run.return_value.stdout = '\n'.join(volume_names + ('unrelated-home',))
                sandbox.delete(config, state)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(commands[1:3], [['podman', 'rm', '-f', name] for name in sandbox.names(config)[:2]])
            self.assertEqual(commands[3:], [['podman', 'volume', 'rm', name] for name in volume_names])
            self.assertFalse(state.exists())
            self.assertEqual((workspace / 'report.md').read_text(), 'keep')

    def test_delete_keeps_state_when_ownership_or_engine_checks_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'delete-demo'
            state.mkdir()
            config = {'name': state.name, 'engine': 'podman', 'workspace': str(Path(tmp) / 'workspace')}
            with patch.object(sandbox, 'inspect', side_effect=[{}, ValueError('Unrelated proxy')]), \
                 patch.object(sandbox, 'run') as run:
                with self.assertRaises(ValueError):
                    sandbox.delete(config, state)
                run.assert_not_called()
            with patch.object(sandbox, 'inspect', return_value=None), \
                 patch.object(sandbox, 'run', side_effect=subprocess.CalledProcessError(1, ['podman', 'volume', 'ls'])):
                with self.assertRaises(subprocess.CalledProcessError):
                    sandbox.delete(config, state)
            self.assertTrue(state.exists())

    def test_delete_handles_already_removed_resources_and_rejects_nested_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'delete-demo'
            state.mkdir()
            config = {'name': state.name, 'engine': 'docker', 'workspace': str(state / 'workspace')}
            with self.assertRaises(ValueError):
                sandbox.delete(config, state)
            config['workspace'] = str(Path(tmp) / 'workspace')
            with patch.object(sandbox, 'inspect', return_value=None), patch.object(sandbox, 'run') as run:
                run.return_value.stdout = ''
                sandbox.delete(config, state)
                self.assertEqual(run.call_count, 1)
            self.assertFalse(state.exists())


class ListTests(unittest.TestCase):
    def save(self, root, name, engine='podman', profile='base'):
        folder = root / name
        folder.mkdir()
        config = {'name': name, 'engine': engine, 'workspace': '/absolute/path/to/project'}
        if profile is not None:
            config['profile'] = {'name': profile}
        (folder / 'config.json').write_text(json.dumps(config))
        return folder

    def test_list_shows_sorted_saved_sandboxes_and_both_container_states_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.save(root, 'stopped', profile=None)
            self.save(root, 'active', profile='custom-documents')
            self.save(root, 'created')
            output = io.StringIO()
            engine_output = ('vscode-pi-sandbox-active\trunning\tactive\n'
                             'vscode-pi-sandbox-active-proxy\texited\tactive\n'
                             'vscode-pi-sandbox-stopped\texited\tstopped\n'
                             'vscode-pi-sandbox-stopped-proxy\texited\tstopped\n')
            with redirect_stdout(output), patch.object(sandbox, 'run', return_value=
                    subprocess.CompletedProcess([], 0, engine_output)) as run:
                sandbox.list_sandboxes(root)
            lines = [line.split() for line in output.getvalue().splitlines()]
            self.assertEqual(lines[0], ['NAME', 'PROFILE', 'ENGINE', 'DEV', 'PROXY', 'WORKSPACE'])
            self.assertEqual(lines[1][:5], ['active', 'custom-documents', 'podman', 'running', 'exited'])
            self.assertEqual(lines[2][:5], ['created', 'base', 'podman', 'missing', 'missing'])
            self.assertEqual(lines[3][:5], ['stopped', 'base', 'podman', 'exited', 'exited'])
            self.assertTrue(all(line[-1] == '/absolute/path/to/project' for line in lines[1:]))
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0][:3], ['podman', 'ps', '--all'])

    def test_unavailable_engines_do_not_hide_saved_sandboxes_or_claim_missing_containers(self):
        for failure in (FileNotFoundError('engine absent'), subprocess.CompletedProcess([], 1, '')):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.save(root, 'demo')
                output, errors = io.StringIO(), io.StringIO()
                kwargs = {'side_effect': failure} if isinstance(failure, Exception) else {'return_value': failure}
                with redirect_stdout(output), redirect_stderr(errors), patch.object(sandbox, 'run', **kwargs):
                    sandbox.list_sandboxes(root)
                self.assertIn('demo', output.getvalue())
                self.assertEqual(output.getvalue().count('unknown'), 2)
                self.assertNotIn('missing', output.getvalue())
                self.assertIn('cannot query podman', errors.getvalue())

    def test_each_saved_engine_is_queried_and_foreign_container_ownership_is_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.save(root, 'docker-demo', engine='docker')
            self.save(root, 'podman-demo')
            output = io.StringIO()

            def run(argv, **kwargs):
                if argv[0] == 'docker':
                    return subprocess.CompletedProcess(argv, 0, 'vscode-pi-sandbox-docker-demo\trunning\tother\n')
                return subprocess.CompletedProcess(argv, 0, '')

            with redirect_stdout(output), patch.object(sandbox, 'run', side_effect=run) as commands:
                sandbox.list_sandboxes(root)
            self.assertIn('unrelated', output.getvalue())
            self.assertEqual([c.args[0][0] for c in commands.call_args_list], ['docker', 'podman'])

    def test_missing_or_empty_state_does_not_create_files_or_call_an_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            for root in (Path(tmp), Path(tmp) / 'missing'):
                with self.subTest(root=root), redirect_stdout(io.StringIO()) as output, \
                        patch.object(sandbox, 'run') as run:
                    sandbox.list_sandboxes(root)
                    self.assertIn('No saved sandboxes', output.getvalue())
                    run.assert_not_called()
            self.assertFalse((Path(tmp) / 'missing').exists())

    def test_bad_configuration_does_not_hide_valid_entries_or_print_its_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = self.save(root, 'broken')
            (folder / 'config.json').write_text('{"secret": "fixture-sensitive-value"')
            self.save(root, 'valid')
            (root / 'incomplete').mkdir()
            output, errors = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors), patch.object(sandbox, 'run', return_value=
                    subprocess.CompletedProcess([], 0, '')):
                sandbox.list_sandboxes(root)
            self.assertIn('invalid config', output.getvalue())
            self.assertIn('valid', output.getvalue())
            self.assertNotIn('incomplete', output.getvalue())
            self.assertIn('cannot read sandbox configuration for broken', errors.getvalue())
            self.assertNotIn('fixture-sensitive-value', output.getvalue() + errors.getvalue())

    def test_cli_accepts_no_name_and_uses_default_or_custom_state_root(self):
        for args, root in ((['sandbox.py', 'list'], Path.home() / '.local/state/vscode-pi-sandbox'),
                           (['sandbox.py', '--state-dir', '/tmp/custom-sandbox-state', 'list'],
                            Path('/tmp/custom-sandbox-state'))):
            with self.subTest(args=args), patch('sys.argv', args), patch.object(sandbox, 'list_sandboxes') as listing:
                sandbox.main()
                listing.assert_called_once_with(root.resolve())


class RecoveryTests(LifecycleTestCase):
    def setUp(self):
        super().setUp()
        self.config = {'name': 'demo', 'engine': 'podman'}
        self.dev, self.proxy, _, _ = sandbox.names(self.config)

    def container(self, running=True):
        return {'Config': {'Labels': {sandbox.LABEL: 'demo'}}, 'State': {'Running': running}}

    def test_unrestricted_container_has_no_proxy_or_proxy_environment(self):
        config = dict(self.config, network='unrestricted', uid=1000, gid=1000,
                      memory='4g', workspace='/absolute/path/to/project')
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / 'allowlist.txt').write_text('')
            with patch.object(sandbox, 'inspect', return_value=None), \
                    patch.object(sandbox, 'image_names', return_value=('dev-image', 'proxy-image')), \
                    patch.object(sandbox, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
                sandbox.up(config, state)
            starts = [call.args[0] for call in run.call_args_list if call.args[0][1] == 'run']
            self.assertEqual(len(starts), 1)
            command = starts[0]
            self.assertIn('--network=bridge', command)
            self.assertIn('--cap-drop=ALL', command)
            self.assertIn('--security-opt=no-new-privileges', command)
            self.assertIn('--security-opt=label=disable', command)
            self.assertIn('/absolute/path/to/project:/workspace:rw', command)
            self.assertIn('SANDBOX_NETWORK_MODE=unrestricted', command)
            self.assertIn('SANDBOX_SUBAGENTS=0', command)
            self.assertFalse(any(str(arg).startswith(('HTTP_PROXY=', 'HTTPS_PROXY=', 'http_proxy=', 'https_proxy='))
                                 or '/run/egress' in str(arg) for arg in command))
            self.assertNotIn(self.proxy, command)

    def test_selinux_label_separation_disabled_only_for_development_container(self):
        for engine in ('podman', 'docker'):
            with self.subTest(engine=engine):
                config = dict(self.config, engine=engine, network='allowlist', uid=1000, gid=1000,
                              memory='4g', workspace='/absolute/path/to/project',
                              pi_config='/absolute/path/to/agent')
                with tempfile.TemporaryDirectory() as tmp:
                    state = Path(tmp)
                    (state / 'allowlist.txt').write_text('example.com:443\n')
                    with patch.object(sandbox, 'inspect', return_value=None), \
                            patch.object(sandbox, 'validate_models'), \
                            patch.object(sandbox, 'image_names', return_value=('dev-image', 'proxy-image')), \
                            patch.object(sandbox, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
                        sandbox.up(config, state)
                    starts = [call.args[0] for call in run.call_args_list if call.args[0][1] == 'run']
                    self.assertEqual(len(starts), 2)
                    proxy, dev = starts
                    self.assertNotIn('--security-opt=label=disable', proxy)
                    self.assertIn(f'{state / "squid.conf"}:/etc/squid/sandbox.conf:ro,Z', proxy)
                    self.assertIn('--security-opt=label=disable', dev)
                    self.assertIn('--network=none', dev)
                    self.assertIn('--cap-drop=ALL', dev)
                    self.assertIn('--security-opt=no-new-privileges', dev)
                    self.assertIn('/absolute/path/to/project:/workspace:rw', dev)
                    self.assertIn('/absolute/path/to/agent:/pi-config:ro', dev)
                    self.assertFalse(any(arg.endswith((':z', ':Z', ',z', ',Z')) for arg in dev))

    def test_up_preserves_healthy_containers_without_requiring_image_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / 'allowlist.txt').write_text('example.com:443\n')
            with patch.object(sandbox, 'inspect', return_value=self.container()), \
                    patch.object(sandbox, 'image_names', side_effect=AssertionError('No image lookup needed')), \
                    patch.object(sandbox, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
                sandbox.up(self.config, state)
            self.assertTrue(run.call_args_list)
            self.assertTrue(all(call.args[0][1] == 'exec' for call in run.call_args_list))
            # Gateway readiness must be verified even when both containers exist.
            self.assertTrue(any(call.args[0][2] == self.proxy and 'proxy.sock' in call.args[0][-1]
                                for call in run.call_args_list))

    def test_up_recovers_stale_runtime_and_tolerates_stop_error_after_state_clears(self):
        for stale in (self.proxy, self.dev):
            with self.subTest(stale=stale), tempfile.TemporaryDirectory() as tmp:
                state = Path(tmp)
                (state / 'allowlist.txt').write_text('example.com:443\n')
                containers = {self.proxy: self.container(), self.dev: self.container()}
                repaired = False
                actions = []

                def run(argv, **kwargs):
                    nonlocal repaired
                    actions.append(argv)
                    if argv[1:3] == ['exec', stale] and argv[-1] == 'true' and not repaired:
                        return subprocess.CompletedProcess(argv, 255, '', 'OCI runtime: container is not running')
                    if argv[1] == 'stop':
                        containers[stale] = self.container(False)
                        return subprocess.CompletedProcess(argv, 125, '', 'conmon exited prematurely')
                    if argv[1] == 'start':
                        containers[stale] = self.container()
                        repaired = True
                    return subprocess.CompletedProcess(argv, 0, '', '')

                with patch.object(sandbox, 'inspect', side_effect=lambda config, name: containers[name]), \
                        patch.object(sandbox, 'run', side_effect=run):
                    sandbox.up(self.config, state)
                self.assertTrue(repaired)
                self.assertEqual([a for a in actions if a[1] == 'start'], [['podman', 'start', stale]])
                self.assertEqual([a[-1] for a in actions if a[1] == 'stop'], [stale])
                self.assertFalse(any(a[1] in ('rm', 'run', 'volume', 'build') for a in actions))

    def test_other_exec_failures_do_not_restart_a_running_container(self):
        for error in ('permission denied', 'container engine unavailable', 'resource temporarily unavailable'):
            with self.subTest(error=error), patch.object(sandbox, 'run', return_value=
                    subprocess.CompletedProcess([], 1, '', error)) as run:
                with self.assertRaisesRegex(ValueError, 'was not restarted'):
                    sandbox.resume_existing(self.config, self.dev, self.container())
                self.assertEqual(len(run.call_args_list), 1)

    def test_restart_requires_verified_stopped_state_and_matching_ownership(self):
        for after in (self.container(), None):
            with self.subTest(after=after), \
                    patch.object(sandbox, 'inspect', side_effect=[self.container(), after]), \
                    patch.object(sandbox, 'run', return_value=subprocess.CompletedProcess([], 1)) as run:
                with self.assertRaisesRegex(ValueError, 'Could not stop'):
                    sandbox.restart_existing(self.config, self.proxy)
                self.assertFalse(any(c.args[0][1] == 'start' for c in run.call_args_list))
        unrelated = self.container()
        unrelated['Config']['Labels'][sandbox.LABEL] = 'other'
        with patch.object(sandbox, 'run', return_value=
                subprocess.CompletedProcess([], 0, json.dumps([unrelated]))) as run:
            with self.assertRaisesRegex(ValueError, 'unrelated'):
                sandbox.restart_existing(self.config, self.proxy)
            self.assertEqual(len(run.call_args_list), 1)

    def test_up_checks_both_ownership_labels_before_any_recovery(self):
        with patch.object(sandbox, 'inspect', side_effect=[self.container(False), ValueError('unrelated')]), \
                patch.object(sandbox, 'upgrade_gateway_config') as upgrade, \
                patch.object(sandbox, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'unrelated'):
                sandbox.up(self.config, Path('/unused'))
            run.assert_not_called()
            upgrade.assert_not_called()

    def test_unresponsive_gateway_is_restarted_once_and_persistent_failure_is_reported(self):
        for succeeds in (True, False):
            results = [ValueError('Gateway did not become ready'), None if succeeds else ValueError('Still unavailable')]
            with self.subTest(succeeds=succeeds), \
                    patch.object(sandbox, 'wait_gateway', side_effect=results) as wait, \
                    patch.object(sandbox, 'restart_existing') as restart:
                if succeeds:
                    sandbox.ensure_gateway(self.config)
                else:
                    with self.assertRaisesRegex(ValueError, 'attempted once'):
                        sandbox.ensure_gateway(self.config)
                restart.assert_called_once_with(self.config, self.proxy)
                self.assertEqual(wait.call_count, 2)

    def test_gateway_gets_time_to_start_before_recovery(self):
        with patch.object(sandbox, 'run', side_effect=[subprocess.CompletedProcess([], 1),
                                                     subprocess.CompletedProcess([], 0)]), \
                patch.object(sandbox.time, 'sleep'), patch.object(sandbox, 'restart_existing') as restart:
            sandbox.ensure_gateway(self.config)
            restart.assert_not_called()


class EditorTests(unittest.TestCase):
    def test_open_attaches_directly_without_onboarding_or_another_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / 'attached-container.json').write_text('{"workspaceFolder":"/workspace"}')
            settings_file = state / 'vscode/User/settings.json'
            settings_file.parent.mkdir(parents=True)
            settings_file.write_text('{"editor.fontSize":16}')
            with patch.object(sandbox, 'inspect', return_value={'State': {'Running': True}}), \
                 patch.object(sandbox.shutil, 'which', return_value='/usr/bin/code'), \
                 patch.object(sandbox, 'run') as run, \
                 patch.dict(os.environ, {'SSH_AUTH_SOCK': '/host/agent', 'VSCODE_IPC_HOOK_CLI': '/host/editor'}):
                sandbox.open_editor({'name': 'editor-demo', 'engine': 'podman'}, state)
            command = run.call_args.args[0]
            self.assertIn('--reuse-window', command)
            self.assertIn('--skip-welcome', command)
            self.assertNotIn('--new-window', command)
            uri = command[command.index('--folder-uri') + 1]
            encoded = uri.split('attached-container+', 1)[1].split('/', 1)[0]
            # A slash-prefixed name fails Podman's lookup and triggers the picker.
            self.assertEqual(json.loads(bytes.fromhex(encoded)), {'containerName': 'vscode-pi-sandbox-editor-demo'})
            self.assertTrue(uri.endswith('/workspace'))
            settings = json.loads(settings_file.read_text())
            self.assertEqual(settings['dev.containers.dockerPath'], 'podman')
            self.assertEqual(settings['workbench.startupEditor'], 'none')
            self.assertFalse(settings['workbench.welcomePage.experimentalOnboarding'])
            self.assertEqual(settings['window.restoreWindows'], 'none')
            self.assertTrue(settings['security.workspace.trust.enabled'])
            self.assertEqual(settings['editor.fontSize'], 16)
            self.assertTrue(settings['chat.disableAIFeatures'])
            self.assertEqual(settings['workbench.secondarySideBar.defaultVisibility'], 'visible')
            storage = state / 'vscode/User/globalStorage/state.vscdb'
            with closing(sqlite3.connect(storage)) as database, database:
                extension_key = 'ms-vscode-remote.remote-containers'
                acknowledgement = json.loads(database.execute('SELECT value FROM ItemTable WHERE key=?', (extension_key,)).fetchone()[0])
                self.assertEqual(acknowledgement, {'userConfirmedAttachToContainerRequiresTrust': True})
                # Existing extension state must not be edited on reconnect,
                # even if the user resets their acknowledgement.
                existing_state = {'userConfirmedAttachToContainerRequiresTrust': False, 'otherState': 'preserved'}
                database.execute('UPDATE ItemTable SET value=? WHERE key=?', (json.dumps(existing_state), extension_key))
                layout = json.loads(database.execute("SELECT value FROM ItemTable WHERE key='views.customizations'").fetchone()[0])
                self.assertEqual(layout['viewContainerLocations']['workbench.view.extension.pendant-container'], 2)
                # A later user move must survive reconnecting.
                layout['viewContainerLocations']['workbench.view.extension.pendant-container'] = 0
                database.execute("UPDATE ItemTable SET value=? WHERE key='views.customizations'", (json.dumps(layout),))
            with patch.object(sandbox, 'inspect', return_value={'State': {'Running': True}}), \
                 patch.object(sandbox.shutil, 'which', return_value='/usr/bin/code'), \
                 patch.object(sandbox, 'run'):
                sandbox.open_editor({'name': 'editor-demo', 'engine': 'podman'}, state)
            with closing(sqlite3.connect(storage)) as database, database:
                self.assertEqual(json.loads(database.execute("SELECT value FROM ItemTable WHERE key='views.customizations'").fetchone()[0]), layout)
                self.assertEqual(json.loads(database.execute('SELECT value FROM ItemTable WHERE key=?', (extension_key,)).fetchone()[0]), existing_state)
            for variable in ('SSH_AUTH_SOCK', 'VSCODE_IPC_HOOK_CLI'):
                self.assertNotIn(variable, run.call_args.kwargs['env'])


class BootstrapTests(unittest.TestCase):
    def bootstrap(self, root, subagents=False):
        script = (sandbox.ROOT / 'containers/dev/bootstrap.py').read_text()
        for relative in ('sandbox/profile.md',):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('Profile guidance' if relative.endswith('profile.md') else '')
        for original, relative in (('/home/node', 'home'), ('/pi-config', 'shared'), ('/opt/pendant', 'pendant'),
                                   ('/opt/pi-security', 'security'),
                                   ('/opt/betterwright', 'betterwright'),
                                   ('/opt/rpiv-ask-user-question', 'ask'),
                                   ('/opt/sandbox', 'sandbox')):
            script = script.replace(original, str(root / relative))
        subprocess.run(['python3', '-c', script], check=True,
                       env=dict(os.environ, SANDBOX_SUBAGENTS='1' if subagents else '0'))

    def test_ask_loads_by_default_and_preserves_existing_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('shared', 'pendant', 'ask'):
                (root / name).mkdir(parents=True)
            extension = root / 'ask/index.ts'
            extension.touch()
            seed = {'packages': ['npm:@juicesharp/rpiv-ask-user-question@2.15.0', 'npm:other-package'],
                    'extensions': ['/custom/extension.ts'], 'defaultProvider': 'kept'}
            (root / 'shared/settings.json').write_text(json.dumps(seed))
            self.bootstrap(root)
            self.bootstrap(root)
            settings = json.loads((root / 'home/.pi/agent/settings.json').read_text())
            self.assertEqual(settings['extensions'].count(str(extension)), 1)
            self.assertIn('/custom/extension.ts', settings['extensions'])
            self.assertEqual(settings['packages'], ['npm:other-package'])
            self.assertEqual(settings['defaultProvider'], 'kept')
            self.assertEqual(json.loads((root / 'shared/settings.json').read_text()), seed)

    def test_native_goal_setting_preserves_preferences_and_tracks_launcher_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('shared', 'pendant', 'sandbox'):
                (root / name).mkdir()
            seed = {'enabled': True, 'maxAutonomousRuns': 12}
            (root / 'shared/pendant-goals.json').write_text(json.dumps(seed))
            choice = root / 'sandbox/options.json'
            for enabled in (False, True):
                choice.write_text(json.dumps({'goals': enabled}))
                self.bootstrap(root)
                target = root / 'home/.pi/agent/pendant-goals.json'
                self.assertFalse(target.is_symlink())
                self.assertEqual(json.loads(target.read_text()), {**seed, 'enabled': enabled})
                self.assertEqual(target.stat().st_mode & 0o077, 0)
            self.assertEqual(json.loads((root / 'shared/pendant-goals.json').read_text()), seed)

    def test_browser_registration_tracks_saved_choice_and_preserves_user_resources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('shared', 'pendant', 'sandbox', 'betterwright'):
                (root / name).mkdir()
            extension = root / 'betterwright/extension.mjs'
            extension.touch()
            (root / 'betterwright/browser.md').write_text('Browser guidance')
            choice = root / 'sandbox/options.json'
            choice.write_text(json.dumps({'browser': True}))
            self.bootstrap(root)
            settings_file = root / 'home/.pi/agent/settings.json'
            settings = json.loads(settings_file.read_text())
            self.assertIn(str(extension), settings['extensions'])
            settings['extensions'].append('/custom/extension.ts')
            settings['packages'] = ['npm:betterwright@2.8.9', 'npm:custom-package']
            settings_file.write_text(json.dumps(settings))
            choice.write_text(json.dumps({'browser': False}))
            self.bootstrap(root)
            settings = json.loads(settings_file.read_text())
            self.assertNotIn(str(extension), settings['extensions'])
            self.assertIn('/custom/extension.ts', settings['extensions'])
            self.assertEqual(settings['packages'], ['npm:custom-package'])
            self.assertNotIn('Browser guidance', (root / 'home/.pi/agent/APPEND_SYSTEM.md').read_text())

    def test_subagents_are_opt_in_and_can_be_disabled_without_losing_user_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('shared', 'pendant'):
                (root / name).mkdir()
            managed = [root / 'security/packages/pi-sandbox/src/container-subagents.ts',
                       root / 'security/node_modules/pi-subagents/index.js']
            for resource in managed:
                resource.parent.mkdir(parents=True, exist_ok=True)
                resource.touch()
            self.bootstrap(root)
            settings_file = root / 'home/.pi/agent/settings.json'
            self.assertFalse(set(map(str, managed)) & set(json.loads(settings_file.read_text())['extensions']))
            self.bootstrap(root, subagents=True)
            settings = json.loads(settings_file.read_text())
            self.assertTrue(set(map(str, managed)) <= set(settings['extensions']))
            settings['extensions'].append('/custom/extension.ts')
            settings['subagents']['agentScanDirs'].append('/custom/agents')
            settings['defaultProvider'] = 'kept'
            settings_file.write_text(json.dumps(settings))
            self.bootstrap(root)
            settings = json.loads(settings_file.read_text())
            self.assertFalse(set(map(str, managed)) & set(settings['extensions']))
            self.assertIn('/custom/extension.ts', settings['extensions'])
            self.assertEqual(settings['subagents']['agentScanDirs'], ['/custom/agents'])
            self.assertEqual(settings['defaultProvider'], 'kept')

    def test_automation_replaces_seeded_npm_registrations_without_duplicate_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('shared', 'pendant'):
                (root / name).mkdir()
            seed = {'packages': ['npm:pi-goal@0.1.7', {'source': 'npm:pi-schedule-prompt'},
                                 'npm:pi-sandbox', {'source': 'npm:@gotgenes/pi-permission-system', 'autoload': False},
                                 'npm:unrelated-package'], 'defaultProvider': 'kept',
                    'extensions': [str(root / 'security/node_modules/pi-goal/.pi/extensions/pi-goal/index.ts')],
                    'skills': [str(root / 'security/node_modules/pi-goal/skills')]}
            (root / 'shared/settings.json').write_text(json.dumps(seed))
            resources = ['security/node_modules/pi-goal/.pi/extensions/pi-goal/index.ts',
                         'security/packages/pi-session-schedule/index.mjs',
                         'security/node_modules/pi-goal/skills/SKILL.md']
            for relative in resources:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            self.bootstrap(root)
            self.bootstrap(root)
            settings = json.loads((root / 'home/.pi/agent/settings.json').read_text())
            self.assertEqual(settings['packages'], ['npm:unrelated-package'])
            self.assertEqual(settings['defaultProvider'], 'kept')
            self.assertNotIn(str(root / resources[0]), settings['extensions'])
            self.assertEqual(settings['extensions'].count(str(root / resources[1])), 1)
            self.assertNotIn(str(root / 'security/node_modules/pi-goal/skills'), settings['skills'])
            self.assertEqual(json.loads((root / 'shared/settings.json').read_text()), seed)

    def test_fresh_private_configuration_is_empty_and_preserves_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('shared', 'pendant'):
                (root / name).mkdir()
            self.bootstrap(root)
            agent = root / 'home/.pi/agent'
            models = agent / 'models.json'
            self.assertEqual(json.loads(models.read_text()), {'providers': {}})
            self.assertFalse(models.is_symlink())
            self.assertEqual(models.stat().st_mode & 0o077, 0)
            settings_file = agent / 'settings.json'
            settings = json.loads(settings_file.read_text())
            self.assertEqual(settings['extensions'], [])
            self.assertEqual(settings['skills'], [])
            settings['defaultProvider'] = 'custom'
            settings['skills'].append('/custom/skills')
            settings_file.write_text(json.dumps(settings))
            (agent / 'APPEND_SYSTEM.md').write_text('User instructions\n' + (agent / 'APPEND_SYSTEM.md').read_text())
            models.write_text('{"providers":{"custom":{}}}')
            self.bootstrap(root)
            self.assertIn('custom', json.loads(models.read_text())['providers'])
            settings = json.loads(settings_file.read_text())
            self.assertEqual(settings['defaultProvider'], 'custom')
            self.assertEqual(settings['skills'], ['/custom/skills'])
            self.assertIn('/custom/skills', settings['skills'])
            prompt = (agent / 'APPEND_SYSTEM.md').read_text()
            self.assertIn('User instructions', prompt)
            self.assertEqual(prompt.count('Profile guidance'), 1)

    def test_seed_and_legacy_models_links_become_private_without_host_transactions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shared = root / 'shared'
            shared.mkdir()
            (root / 'pendant').mkdir()
            (shared / 'models.json').write_text('{"providers":{"seed":{}}}')
            for suffix in ('lock', 'journal.json', 'backup.bak'):
                (shared / ('models.json.' + suffix)).write_text('host-only transaction')
            (shared / 'skills').mkdir()
            agent = root / 'home/.pi/agent'
            agent.mkdir(parents=True)
            for filename in ('models.json',):
                (agent / filename).symlink_to(shared / filename)
            self.bootstrap(root)
            for filename in ('models.json',):
                self.assertFalse((agent / filename).is_symlink())
                self.assertEqual((agent / filename).read_text(), (shared / filename).read_text())
                self.assertEqual((agent / filename).stat().st_mode & 0o077, 0)
            self.assertEqual((agent / 'skills').resolve(), shared / 'skills')
            self.assertFalse((agent / 'models.json.lock').exists())
            self.assertFalse((agent / 'models.json.journal.json').exists())
            self.assertFalse((agent / 'models.json.backup.bak').exists())
            (agent / 'models.json').write_text('{"providers":{"private":{}}}')
            self.bootstrap(root)
            self.assertIn('private', json.loads((agent / 'models.json').read_text())['providers'])
            self.assertIn('seed', json.loads((shared / 'models.json').read_text())['providers'])


if __name__ == '__main__':
    unittest.main()
