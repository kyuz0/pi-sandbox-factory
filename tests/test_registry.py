import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pi_sandbox_factory import registry, sandbox, model_providers


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"SANDBOX_REGISTRY_DIR": str(self.root / "registry")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.source = self.root / "package"
        self.source.mkdir()
        (self.source / "profile.json").write_text(
            json.dumps({"version": 1, "name": "sample", "description": "Sample tools"})
        )
        (self.source / "Dockerfile").write_text("ARG BASE_IMAGE\nFROM ${BASE_IMAGE}\nUSER node\n")
        (self.source / "profile.md").write_text("Use the sample tools.")

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.source), *args], check=True, capture_output=True, text=True
        ).stdout.strip()

    def commit(self):
        self.git("add", ".")
        self.git(
            "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "fixture"
        )
        return self.git("rev-parse", "HEAD")

    def test_git_install_update_and_existing_snapshot_survives_removal(self):
        self.git("init", "-q", "-b", "main")
        first = self.commit()
        row = registry.add("profile", "sample", str(self.source))
        self.assertEqual(row["commit"], first)
        state = self.root / "state"
        state.mkdir()
        snapshot = sandbox.snapshot_profile(sandbox.load_profile("sample"), state)
        (self.source / "profile.md").write_text("Updated tools.")
        second = self.commit()
        self.assertEqual(
            Path(registry.resolve("profile", "sample"), "profile.md").read_text(),
            "Use the sample tools.",
        )
        registry.update("profile", "sample")
        self.assertEqual(registry.installed("profile")["sample"]["commit"], second)
        registry.remove("profile", "sample")
        self.assertEqual(Path(snapshot["path"], "profile.md").read_text(), "Use the sample tools.")
        self.assertEqual(sandbox.tree_digest(Path(snapshot["path"])), snapshot["digest"])
        self.assertFalse((Path(snapshot["path"]) / ".git").exists())

    def test_pinned_commit_does_not_follow_branch(self):
        self.git("init", "-q", "-b", "main")
        first = self.commit()
        registry.add("profile", "sample", str(self.source), first)
        (self.source / "profile.md").write_text("changed")
        self.commit()
        self.assertEqual(registry.update("profile", "sample")["commit"], first)

    def test_named_branch_installs_and_updates_without_following_default(self):
        self.git("init", "-q", "-b", "main")
        self.commit()
        self.git("checkout", "-qb", "tools")
        (self.source / "profile.md").write_text("Branch tools.")
        first = self.commit()
        self.git("checkout", "-q", "main")
        row = registry.add("profile", "sample", str(self.source), "tools")
        self.assertEqual(row["commit"], first)
        self.git("checkout", "-q", "tools")
        (self.source / "profile.md").write_text("New branch tools.")
        second = self.commit()
        self.git("checkout", "-q", "main")
        self.assertEqual(registry.update("profile", "sample")["commit"], second)

    def test_failed_update_keeps_previous_registration(self):
        registry.add("profile", "sample", str(self.source))
        before = registry.installed("profile")
        (self.source / "Dockerfile").unlink()
        with self.assertRaises(ValueError):
            registry.update("profile", "sample")
        self.assertEqual(registry.installed("profile"), before)

    def test_rejects_symlinks_mutated_cache_duplicate_and_reserved_names(self):
        (self.source / "link").symlink_to("/etc/passwd")
        with self.assertRaises(ValueError):
            registry.add("profile", "sample", str(self.source))
        (self.source / "link").unlink()
        row = registry.add("profile", "sample", str(self.source))
        with self.assertRaises(ValueError):
            registry.add("profile", "sample", str(self.source))
        with self.assertRaises(ValueError):
            registry.add("profile", "base", str(self.source))
        (Path(row["path"]) / "profile.md").write_text("tampered")
        with self.assertRaises(ValueError):
            registry.resolve("profile", "sample")

    def test_sources_reject_embedded_passwords_and_git_command_transports(self):
        for source in (
            "ext::sh -c whatever",
            "https://token@example.com/repo.git",
            "ssh://user:password@example.com/repo",
            "-bad",
            "file:///etc",
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                registry.source_url(source)
        self.assertEqual(
            registry.source_url("git@git.example.com:team/repo.git"),
            "git@git.example.com:team/repo.git",
        )

    def test_monorepo_plugins_install_and_update_independently(self):
        plugin = self.source / "profiles" / "sample"
        plugin.mkdir(parents=True)
        for filename in ("profile.json", "profile.md", "Dockerfile"):
            (self.source / filename).rename(plugin / filename)
        other = self.source / "other"
        other.mkdir()
        (other / "provider.json").write_text(
            json.dumps({"name": "company", "version": 1, "entry": "adapter.mjs"})
        )
        (other / "adapter.mjs").write_text("export async function run() {}")
        (self.source / "README.md").write_text("Repository overview")
        self.git("init", "-q", "-b", "main")
        first = self.commit()
        row = registry.add("profile", "sample", str(self.source), subdir="profiles/sample")
        provider = registry.add("provider", "company", str(self.source), subdir="other")
        registry.add("profile", "pinned", str(self.source), first, subdir="profiles/sample")
        self.assertEqual(row["commit"], first)
        self.assertEqual(row["subdir"], "profiles/sample")
        self.assertEqual(
            {p.name for p in Path(row["path"]).iterdir()},
            {"profile.json", "profile.md", "Dockerfile"},
        )
        self.assertFalse((Path(provider["path"]) / "profiles").exists())
        (plugin / "profile.md").write_text("Updated sample")
        second = self.commit()
        updated = registry.update("profile", "sample")
        self.assertEqual(updated["commit"], second)
        self.assertEqual(updated["subdir"], "profiles/sample")
        self.assertEqual(Path(updated["path"], "profile.md").read_text(), "Updated sample")
        self.assertEqual(registry.installed("provider")["company"], provider)
        self.assertEqual(registry.update("profile", "pinned")["commit"], first)
        (plugin / "Dockerfile").unlink()
        self.commit()
        with self.assertRaises(ValueError):
            registry.update("profile", "sample")
        self.assertEqual(registry.installed("profile")["sample"], updated)

    def test_local_subdirectory_rejects_escape_and_symlink_components(self):
        for path in ("../package", "/tmp", "missing"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                registry.add("profile", "sample", str(self.source), subdir=path)
        (self.source / "link").symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            registry.add("profile", "sample", str(self.source), subdir="link")
        (self.source / "link").unlink()
        row = registry.add("profile", "sample", str(self.root), subdir="package")
        self.assertEqual(row["subdir"], "package")
        self.assertTrue(Path(row["path"], "Dockerfile").exists())

    def test_git_subdirectory_rejects_symlink_escape(self):
        self.git("init", "-q", "-b", "main")
        (self.source / "link").symlink_to(self.root, target_is_directory=True)
        self.commit()
        with self.assertRaisesRegex(ValueError, "symlinks"):
            registry.add("profile", "sample", str(self.source), subdir="link/package")

    def test_cli_passes_subdirectory_to_registry(self):
        with (
            patch(
                "sys.argv",
                [
                    "pi-sandbox-factory",
                    "profile",
                    "add",
                    "sample",
                    str(self.source),
                    "--subdir",
                    "tools/sample",
                ],
            ),
            patch.object(registry, "add", return_value={"name": "sample", "commit": "abc"}) as add,
        ):
            sandbox.main()
        add.assert_called_once_with(
            "profile", "sample", str(self.source), None, subdir="tools/sample"
        )

    def provider(self):
        (self.source / "adapter.mjs").write_text(
            'export async function run(){return {state:"ready",message:"fixture"}}'
        )
        info = {
            "version": 1,
            "name": "sample",
            "entry": "adapter.mjs",
            "settings": {"endpoint": {"type": "text", "network": True}, "key": {"type": "secret"}},
            "network": [],
        }
        (self.source / "provider.json").write_text(json.dumps(info))
        registry.add("provider", "sample", str(self.source))

    def test_provider_snapshots_network_and_secret_boundaries(self):
        self.provider()
        state = self.root / "state"
        state.mkdir()
        values = {"sample": {"endpoint": "https://models.example.com/v1"}}
        rows = model_providers.prepare(values, state)
        config = {"network": "allowlist", "model_providers": rows}
        with self.assertRaises(ValueError):
            model_providers.validate_network(config, [])
        model_providers.validate_network(config, [("models.example.com", 443)])
        with self.assertRaises(ValueError):
            model_providers.prepare({"sample": {"key": "secret"}}, state)
        with self.assertRaises(ValueError):
            model_providers.prepare({"sample": {"unknown": "x"}}, state)
        registry.remove("provider", "sample")
        self.assertTrue(Path(rows[0]["path"], "adapter.mjs").is_file())

    def test_manifest_rejects_external_entry_and_resources(self):
        self.provider()
        info = json.loads((self.source / "provider.json").read_text())
        for changes in (
            {"entry": "../adapter.mjs"},
            {"extensions": ["/etc/example"]},
            {"version": 2},
        ):
            (self.source / "provider.json").write_text(json.dumps(dict(info, **changes)))
            with self.assertRaises(ValueError):
                registry.manifest("provider", self.source)

    def test_builtin_local_and_generic_profile_always_available(self):
        self.assertIn("base", registry.choices("profile"))
        self.assertIn("local", registry.choices("provider"))
        self.assertTrue((registry.resolve("provider", "local") / "adapter.mjs").is_file())

    def test_builtin_resources_work_through_symlinked_installation_paths(self):
        alias = self.root / "lib64"
        alias.symlink_to(Path(registry.__file__).parent, target_is_directory=True)
        with patch.object(registry, "__file__", str(alias / "registry.py")):
            info = registry.manifest("provider", alias / "providers/local")
        self.assertEqual(info["name"], "local")

    def test_provider_selection_changes_image_identity(self):
        config = {"name": "demo", "uid": 1000, "gid": 1000}
        first = sandbox.image_names(config)[0]
        rows = model_providers.prepare({"local": {}}, self.root / "state")
        self.assertNotEqual(first, sandbox.image_names(dict(config, model_providers=rows))[0])

    def test_provider_update_is_explicit_and_removal_keeps_saved_settings_editable(self):
        self.provider()
        values = {"sample": {"endpoint": "https://models.example.com/v1"}}
        rows = model_providers.prepare(values, self.root / "state")
        (self.source / "adapter.mjs").write_text(
            'export async function run(){return {state:"ready",message:"new"}}'
        )
        registry.update("provider", "sample")
        same = model_providers.prepare(values, self.root / "state", saved=rows)
        self.assertEqual(same[0]["digest"], rows[0]["digest"])
        updated = model_providers.prepare(values, self.root / "state", saved=rows, refresh=True)
        self.assertNotEqual(updated[0]["digest"], rows[0]["digest"])
        registry.remove("provider", "sample")
        values["sample"]["endpoint"] = "https://another.example.com/v1"
        retained = model_providers.prepare(values, self.root / "state", saved=updated, refresh=True)
        self.assertEqual(retained[0]["digest"], updated[0]["digest"])
        self.assertEqual(retained[0]["settings"], values["sample"])

    def test_profile_alias_survives_snapshot(self):
        registry.add("profile", "my-tools", str(self.source))
        saved = sandbox.snapshot_profile(sandbox.load_profile("my-tools"), self.root / "state")
        self.assertEqual(saved["registry_name"], "my-tools")
        self.assertEqual(saved["name"], "sample")

    def test_provider_network_edit_rejected_before_runtime_mutation(self):
        self.provider()
        rows = model_providers.prepare(
            {"sample": {"endpoint": "https://models.example.com/v1"}}, self.root / "state"
        )
        with patch.object(sandbox, "inspect") as inspect:
            with self.assertRaisesRegex(ValueError, "Allow provider destinations"):
                sandbox.update_network(
                    {"network": "allowlist", "model_providers": rows},
                    self.root / "state",
                    "example.com:443",
                )
            inspect.assert_not_called()

    def test_runtime_error_is_not_reported_as_success(self):
        config = {"name": "test", "engine": "podman", "model_providers": [{"name": "sample", "manifest": {}}]}
        with patch.object(
            sandbox,
            "run",
            return_value=subprocess.CompletedProcess(
                [], 0, json.dumps({"state": "error", "message": "Endpoint missing"})
            ),
        ):
            with self.assertRaisesRegex(ValueError, "Endpoint missing"):
                model_providers.configure(config, self.root / 'state')
