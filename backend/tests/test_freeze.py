import json
import os
import unittest
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from freeze_evaluation import manifest


class FreezeManifestTest(unittest.TestCase):
    def test_manifest_writer_uses_portable_lf_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            subprocess.run([sys.executable, "freeze_evaluation.py", "--output", str(path)],
                           cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True)
            raw = path.read_bytes()
            self.assertNotIn(b"\r\n", raw)
            self.assertEqual(json.loads(raw)["evaluation_status"], "not_run")

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
