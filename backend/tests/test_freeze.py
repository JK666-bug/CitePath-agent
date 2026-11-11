import json
import os
import unittest
from unittest.mock import patch

from freeze_evaluation import manifest


class FreezeManifestTest(unittest.TestCase):
    def test_full_runtime_sources_can_be_frozen_without_serialization_errors_or_keys(self):
        with patch.dict(os.environ, {"HKU_API_KEY": "private-test-secret-do-not-export"}):
            result = manifest()
        serialized = json.dumps(result, allow_nan=False)
        self.assertNotIn("private-test-secret", serialized)
        self.assertEqual(result["evaluation_status"], "not_run")
        self.assertIn("db/feedback.py", result["source_sha256"])
        self.assertIn("evaluation/core.py", result["source_sha256"])
        self.assertIn("agent/report_text.py", result["source_sha256"])
        self.assertTrue(all(len(value) == 64 for value in result["source_sha256"].values()))


if __name__ == "__main__":
    unittest.main()
