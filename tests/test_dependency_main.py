import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('dependency_main', Path(__file__).resolve().parents[1]/'scripts/check_dependency_main.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class DependencyMainTests(unittest.TestCase):
    def test_shipped_git_dependencies_are_covered(self):
        pins = gate.dependency_pins(Path(__file__).resolve().parents[1])
        self.assertEqual(set(pins), {'kyuz0/pi-packages', 'kyuz0/pi-advisor', 'kyuz0/pi-local-model-manager', 'kyuz0/pi-slack', 'juicesharp/rpiv-mono'})

    def test_main_ancestor_and_tip_pass_but_branch_only_commits_fail(self):
        for status in ('ahead', 'identical', 'behind', 'diverged', None):
            with self.subTest(status=status), contextlib.redirect_stdout(io.StringIO()):
                calls = []
                def fetch(url):
                    calls.append(url)
                    return {'status': status}
                if status in ('ahead', 'identical'):
                    gate.check_main({'owner/project': 'a'*40}, fetch)
                else:
                    with self.assertRaisesRegex(ValueError, 'not on main'):
                        gate.check_main({'owner/project': 'a'*40}, fetch)
                self.assertEqual(calls, ['https://api.github.com/repos/owner/project/compare/'+'a'*40+'...main'])

    def test_archive_pin_must_match_manifest_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dev = root/'pi_sandbox_factory/containers/dev'
            (dev/'security').mkdir(parents=True)
            (dev/'extensions.lock.json').write_text('{"extensions":{}}')
            (dev/'security/sources.json').write_text(json.dumps({'test': {'commit':'a'*40,'url':'https://codeload.github.com/owner/project/tar.gz/'+'b'*40}}))
            with self.assertRaisesRegex(ValueError, 'does not match'):
                gate.dependency_pins(root)
