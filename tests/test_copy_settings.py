"""Creation reuses immutable packages without sharing private state."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pi_sandbox_factory import sandbox, model_providers
from pi_sandbox_factory.sandbox_tui import copy_draft, Service


class CopySettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.workspace = self.root / 'project'
        self.workspace.mkdir()
        skill = self.source / 'skills' / 'example'
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('---\nname: example\n---\nExample skill\n')
        self.config = dict(name='source', engine='podman', network='allowlist', memory='12g',
            subagents=True, local_model_ports=None, workspace='/source/project',
            env_file='/private/key.env', pi_config='/private/pi', ssh={'enabled': True},
            advisors={'providers': ['claude'], 'claude_model': 'opus', 'claude_effort': 'high'},
            profile=sandbox.snapshot_profile(sandbox.load_profile('base'), self.source),
            model_providers=model_providers.prepare({'local': {}}, self.source),
            extra_skills=[dict(name='example', repo='https://example.com/skills.git', folder='example',
                               commit='abc', path=str(skill), digest=sandbox.tree_digest(skill))],
            options={'browser': True, 'web_access': {'enabled': True, 'providers': {'exa': {'has_key': True}}}})
        (self.source / 'config.json').write_text(json.dumps(self.config))
        (self.source / 'allowlist.txt').write_text('example.com:443\n')
        (self.source / 'private-auth.json').write_text('PRIVATE_TEST_SENTINEL')

    def create(self, omit=()):
        args = SimpleNamespace(name='target', profile=self.config['profile']['path'], reuse_from='source',
            workspace=str(self.workspace), pi_config=None, env_file=None, memory='12g',
            engine='docker', allowlist=None, allow_domain=['example.com:443'], advisor=['claude'],
            omit_skill=list(omit))
        state = self.root / 'target'
        with patch.object(sandbox, 'choose_engine', return_value='docker'), \
             patch.object(sandbox.os, 'getuid', return_value=1000), \
             patch.object(sandbox.os, 'getgid', return_value=1000), \
             patch.object(model_providers.registry, 'resolve', side_effect=AssertionError('Must use saved packages')):
            sandbox.create(args, state)
        return state, json.loads((state / 'config.json').read_text())

    def test_independent_profile_provider_and_skill_survive_source_deletion(self):
        state, config = self.create()
        self.assertEqual(config['advisors']['claude_model'], 'opus')
        self.assertIsNone(config['env_file'])
        self.assertIsNone(config['pi_config'])
        self.assertNotIn('ssh', config)
        self.assertFalse((state / 'private-auth.json').exists())
        shutil.rmtree(self.source)
        for row in [config['profile'], *config['model_providers'], *config['extra_skills']]:
            self.assertTrue(Path(row['path']).is_relative_to(state))
            self.assertEqual(sandbox.tree_digest(Path(row['path'])), row['digest'])

    def test_omitted_skill_and_modified_skill(self):
        state, config = self.create(omit=['example'])
        self.assertEqual(config['extra_skills'], [])
        shutil.rmtree(state)
        Path(self.config['extra_skills'][0]['path'], 'SKILL.md').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'Source skill snapshot was modified'):
            self.create()
        self.assertFalse(state.exists())
        self.assertTrue(self.source.exists())

    def test_draft_excludes_private_paths_and_is_independent(self):
        original = copy.deepcopy(self.config)
        draft = copy_draft({'name': 'source', 'config': self.config}, self.root)
        for field in ('name', 'workspace', 'env_file', 'pi_config'):
            self.assertEqual(draft[field], '')
        self.assertNotIn('ssh', draft)
        self.assertFalse(draft['options']['web_access']['providers']['exa']['has_key'])
        draft['advisors']['providers'].clear()
        self.assertEqual(self.config, original)

    def test_service_passes_only_selected_resources_and_keys_separately(self):
        draft = copy_draft({'name': 'source', 'config': self.config}, self.root)
        draft.update(name='target', workspace=str(self.workspace), remove_skills=['example'], open_editor=False)
        service = Service(self.root)
        commands = []
        def run(args, log):
            commands.append(args)
            if args[0] == 'create':
                selected = json.loads(Path(args[args.index('--options-file') + 1]).read_text())
                self.assertNotIn('synthetic-key', json.dumps(selected))
        with patch.object(service, 'run', side_effect=run), patch.object(service, 'setup') as setup:
            service.create(draft, {'exa': 'synthetic-key'}, lambda _: None)
        self.assertIn('--reuse-from', commands[0])
        self.assertIn('--omit-skill', commands[0])
        self.assertNotIn('--env-file', commands[0])
        self.assertNotIn('--pi-config', commands[0])
        self.assertNotIn('synthetic-key', str(commands))
        self.assertEqual(setup.call_args.args[2], {'exa': 'synthetic-key'})
