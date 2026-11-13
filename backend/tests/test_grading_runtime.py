"""Grading cannot bypass frozen runtime checks or invoke a model by default."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from evaluation.__main__ import main
from evaluation.core import digest
from evaluation.live import collect_grading
from evaluation.merge import merge_collections
from tests.test_evaluation import sample_data


class GradingRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.data = copy.deepcopy(sample_data())
        for item in self.data["items"]:
            item["predictions"] = {"baseline": None, "full": None}
        self.manifest = {
            "working_tree_dirty": False, "created_at": self.data["freeze"]["created_at"],
            "git_commit": self.data["freeze"]["git_commit"], "provider": "hku", "model": "test-model",
            "api_version": "frozen-api-version", "base_url_sha256": "c" * 64,
            "source_sha256": {"agent/exam.py": "d" * 64}, "python": "3.12.0",
            "installed_packages": {"example-package": "1.0"}, "model_cost_configuration": None,
        }
        self.manifest_path = self.root / "manifest.json"
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.data["freeze"].update(provider="hku", base_url_sha256="c" * 64,
                                   manifest_sha256=hashlib.sha256(self.manifest_path.read_bytes()).hexdigest())
        self.observed = {"schema": "citepath-evaluation-runtime-v1", **self.manifest,
                         "runtime_packages_sha256": digest(self.manifest["installed_packages"])}
        self.configuration = {"provider": "hku", "model": "test-model", "base_url_sha256": "c" * 64,
                              "key_configured": True}

    def test_default_dry_run_is_an_unchanged_copy_without_manifest_or_model(self):
        original = copy.deepcopy(self.data)
        with patch("agent.llm.chat_model") as client, patch("agent.exam._grade_shorts") as grade, \
                patch("evaluation.runtime.verify_runtime") as verify:
            result = collect_grading(self.data)
        self.assertEqual(result, original)
        self.assertIsNot(result, self.data)
        self.assertEqual(self.data, original)
        client.assert_not_called()
        grade.assert_not_called()
        verify.assert_not_called()

    def test_explicit_run_without_manifest_never_constructs_or_invokes_model(self):
        with patch("agent.llm.chat_model") as client, patch("agent.exam._grade_shorts") as grade:
            with self.assertRaisesRegex(ValueError, "manifest"):
                collect_grading(self.data, run=True)
        client.assert_not_called()
        grade.assert_not_called()

    def test_source_packages_api_version_python_cost_or_endpoint_drift_stops_before_model(self):
        for field in ("source_sha256", "runtime_packages_sha256", "api_version", "python",
                      "model_cost_configuration", "base_url_sha256"):
            observed = copy.deepcopy(self.observed)
            observed[field] = "changed"
            with self.subTest(field=field), \
                    patch("agent.llm.model_configuration", return_value=self.configuration), \
                    patch("evaluation.runtime.runtime_summary", return_value=observed), \
                    patch("agent.llm.chat_model") as client, patch("agent.exam._grade_shorts") as grade:
                with self.assertRaisesRegex(ValueError, "differ"):
                    collect_grading(self.data, manifest_path=self.manifest_path, run=True)
                client.assert_not_called()
                grade.assert_not_called()

    def test_changed_manifest_bytes_cannot_be_bypassed_by_matching_model_name(self):
        self.manifest_path.write_text("{}", encoding="utf-8")
        with patch("agent.llm.model_configuration", return_value=self.configuration), \
                patch("agent.llm.chat_model") as client, patch("agent.exam._grade_shorts") as grade:
            with self.assertRaisesRegex(ValueError, "manifest identity"):
                collect_grading(self.data, manifest_path=self.manifest_path, run=True)
        client.assert_not_called()
        grade.assert_not_called()

    def test_unreviewed_final_workflow_policy_blocks_grading_before_runtime_or_model(self):
        data = copy.deepcopy(self.data)
        data.update(split="final", synthetic=False, evaluation_protocol={"reviewed": False})
        data["documents"][0]["lecture"] = 4
        for item in data["items"]:
            item["lecture"] = 4
        data["items"].append({"id": "WF", "kind": "workflow", "lecture": 4,
            "question": "Protocol review is still pending",
            "expected": {variant: {"policy": "actual_grade_v1"} for variant in ("baseline", "full")},
            "predictions": {"baseline": None, "full": None}})
        with patch("agent.llm.model_configuration", return_value=self.configuration), \
                patch("evaluation.runtime.verify_runtime") as verify, \
                patch("agent.llm.chat_model") as client, patch("agent.exam._grade_shorts") as grade:
            with self.assertRaisesRegex(ValueError, "frozen metadata"):
                collect_grading(data, manifest_path=self.manifest_path, run=True)
        verify.assert_not_called()
        client.assert_not_called()
        grade.assert_not_called()

    def test_missing_selected_key_is_rejected_before_model_construction(self):
        with patch("agent.llm.model_configuration", return_value={**self.configuration, "key_configured": False}), \
                patch("agent.llm.chat_model") as client, patch("agent.exam._grade_shorts") as grade:
            with self.assertRaisesRegex(ValueError, "key is not configured"):
                collect_grading(self.data, manifest_path=self.manifest_path, run=True)
        client.assert_not_called()
        grade.assert_not_called()

    def test_attested_shared_grades_preserve_original_inputs_and_merge_binding(self):
        original = copy.deepcopy(self.data)
        with patch("agent.llm.model_configuration", return_value=self.configuration), \
                patch("evaluation.runtime.runtime_summary", return_value=self.observed), \
                patch("agent.llm.chat_model", return_value=SimpleNamespace(model_name="test-model")), \
                patch("agent.exam._grade_shorts", return_value={2: [0, 1, 2, 3]}) as grade:
            collected = collect_grading(self.data, manifest_path=self.manifest_path, run=True)
        self.assertEqual(self.data, original)
        grade.assert_called_once()
        for item in collected["items"][:2]:
            self.assertEqual(item["predictions"]["baseline"], item["predictions"]["full"])
            self.assertTrue(item["predictions"]["baseline"]["correct"])
            self.assertEqual(item["predictions"]["full"]["configuration_sha256"], self.data["freeze"]["manifest_sha256"])
        self.assertEqual(merge_collections(self.data, [collected]), collected)

    def test_cli_dry_run_exits_pending_and_writes_no_predictions(self):
        source, destination = self.root / "source.json", self.root / "dry.json"
        source.write_text(json.dumps(self.data), encoding="utf-8")
        with patch("agent.llm.chat_model") as client, patch("agent.exam._grade_shorts") as grade:
            code = main(["collect-grading", str(source), "--output", str(destination)])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(destination.read_text()), self.data)
        client.assert_not_called()
        grade.assert_not_called()

    def test_cli_blocks_missing_manifest_and_protects_manifest_existing_output_and_cohorts(self):
        source, destination = self.root / "source.json", self.root / "run.json"
        source.write_text(json.dumps(self.data), encoding="utf-8")
        protected = Path(__file__).resolve().parents[2] / "evaluation_assets/grading-output-must-not-be-written.json"
        self.assertFalse(protected.exists())
        before = self.manifest_path.read_bytes()
        destination.write_text("retained result", encoding="utf-8")
        with patch("agent.llm.chat_model") as client, patch("agent.exam._grade_shorts") as grade:
            for arguments in (
                ["--run", "--output", str(self.root / "missing-manifest.json")],
                ["--output", str(protected)],
                ["--manifest", str(self.manifest_path), "--output", str(self.manifest_path)],
                ["--output", str(destination)],
            ):
                with self.subTest(arguments=arguments):
                    self.assertEqual(main(["collect-grading", str(source), *arguments]), 1)
        self.assertFalse(protected.exists())
        self.assertFalse((self.root / "missing-manifest.json").exists())
        self.assertEqual(self.manifest_path.read_bytes(), before)
        self.assertEqual(destination.read_text(), "retained result")
        client.assert_not_called()
        grade.assert_not_called()


if __name__ == "__main__":
    unittest.main()
