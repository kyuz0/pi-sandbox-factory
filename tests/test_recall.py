"""Recall selection and permission contract."""
import json
import unittest
from pi_sandbox_factory import sandbox
from pi_sandbox_factory.sandbox_options import options, permissions

class RecallTests(unittest.TestCase):
    def test_default_and_validation(self):
        self.assertEqual(options()['compaction_recall'], 'lite')
        for mode in ('lite', 'full', 'off'):
            self.assertEqual(options({'compaction_recall': mode})['compaction_recall'], mode)
        for mode in ('auto', None, True):
            with self.assertRaises(ValueError):
                options({'compaction_recall': mode})

    def test_history_tools_do_not_require_review(self):
        template = json.loads((sandbox.ROOT / 'containers/dev/security/config/permissions.json').read_text())
        for mode in ('automatic', 'assisted', 'manual'):
            rules = permissions(template, {'approval': mode})['permission']
            for tool in ('history_grep', 'history_expand', 'history_recall'):
                self.assertEqual(rules[tool], 'allow')
