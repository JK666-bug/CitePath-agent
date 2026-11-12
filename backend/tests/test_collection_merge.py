import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluation.__main__ import main
from evaluation.core import digest, _freeze_problems
from evaluation.merge import merge_collections
from evaluation.preparation import collection_templates
from tests.test_evaluation import sample_data


class CollectionMergeTest(unittest.TestCase):
    def setUp(self):
        observed = sample_data()
        self.original = copy.deepcopy(observed)
        for item in self.original["items"]:
            item["predictions"] = {"baseline": None, "full": None}
        self.grading = copy.deepcopy(self.original)
        self.evidence = copy.deepcopy(self.original)
        for index in (0, 1):
            self.grading["items"][index]["predictions"] = observed["items"][index]["predictions"]
        self.evidence["items"][2]["predictions"] = observed["items"][2]["predictions"]

    def test_complementary_collectors_merge_against_one_original_input(self):
        before = copy.deepcopy(self.original)
        result = merge_collections(self.original, [self.grading, self.evidence])
        self.assertEqual(self.original, before)
        self.assertTrue(all(prediction for item in result["items"] for prediction in item["predictions"].values()))

    def test_conflicting_outputs_and_changed_questions_are_rejected(self):
        changed = copy.deepcopy(self.grading)
        changed["items"][0]["predictions"]["baseline"]["correct"] = False
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            merge_collections(self.original, [self.grading, changed])
        changed = copy.deepcopy(self.evidence)
        changed["items"][0]["question"] = "Changed frozen input"
        with self.assertRaisesRegex(ValueError, "rewrote"):
            merge_collections(self.original, [changed])

    def test_actual_record_file_binds_original_digest_and_rejects_controller_results(self):
        record = {"schema": "collection", "dataset_sha256": digest(self.original), "records": [
            {"item_id": "m", "variant": "baseline", "prediction": self.grading["items"][0]["predictions"]["baseline"]}]}
        self.assertTrue(merge_collections(self.original, [record])["items"][0]["predictions"]["baseline"])
        record["controller_records"] = [{"fabricated": True}]
        with self.assertRaisesRegex(ValueError, "Controller observations"):
            merge_collections(self.original, [record])

    def test_synthetic_outputs_cannot_be_merged_into_real_cohort(self):
        real = copy.deepcopy(self.original)
        real["synthetic"] = False
        with self.assertRaisesRegex(ValueError, "Synthetic collections"):
            merge_collections(real, [self.grading])

    def test_templates_leave_all_runtime_ids_and_human_reviews_unfilled(self):
        templates = collection_templates(self.original, "manifest.json")
        for config in templates["evidence-runtime.template.json"]["variants"].values():
            self.assertIsNone(config["course_id"])
            self.assertTrue(all(document["runtime_document_id"] is None for document in config["documents"]))
        self.assertFalse(templates["preparation-status.json"]["human_review_completed"])
        self.assertIsNone(templates["preparation-status.json"]["official_accepted"])

    def test_final_actual_protocol_requires_human_review_and_both_frozen_hashes(self):
        from tests.test_evaluation import final_data
        data, _ = final_data()
        data["synthetic"] = False
        for item in data["items"]:
            item["predictions"] = {"baseline": None, "full": None}
            if item["kind"] == "workflow":
                item["expected"] = {variant: {"policy": "actual_grade_v1"} for variant in ("baseline", "full")}
        self.assertTrue(_freeze_problems(data))
        # Synthetic unit-test attestations exercise the gate only; no file or
        # human judgment is created and there are no observed predictions.
        data["evaluation_protocol"] = {"reviewed": True, "review_origin": "human", "reviewed_by": ["unit-a", "unit-b"],
                                       "chapter_mapping_sha256": "c" * 64, "response_policy_sha256": "d" * 64}
        self.assertEqual(_freeze_problems(data), [])
        data["evaluation_protocol"]["reviewed_by"] = ["unit-a", "unit-a"]
        self.assertTrue(_freeze_problems(data))

    def test_local_model_check_is_dry_without_explicit_run(self):
        from evaluation.local_models import smoke_local_models
        with patch("ingest.pdf_reader.read_pdf") as pdf, patch("vector.segments._embed") as embedding:
            result = smoke_local_models()
        self.assertEqual(result["status"], "not_run")
        self.assertFalse(result["llm_invoked"])
        pdf.assert_not_called()
        embedding.assert_not_called()

    def test_cli_dry_collection_and_binding_preparation_do_not_invoke_services(self):
        with tempfile.TemporaryDirectory() as directory, patch("agent.llm.chat_model") as model:
            root = Path(directory)
            source = root / "input.json"
            source.write_text(json.dumps(self.original), encoding="utf-8")
            templates = root / "bindings"
            self.assertEqual(main(["prepare-collection", str(source), "--manifest", str(root / "manifest.json"), "--output-dir", str(templates)]), 0)
            self.assertEqual(main(["collect-evidence", str(source), "--config", str(templates / "evidence-runtime.template.json"), "--output", str(root / "dry.json")]), 2)
            self.assertEqual(json.loads((root / "dry.json.report.json").read_text())["status"], "not_run")
            self.assertEqual(main(["prepare-collection", str(source), "--manifest", str(root / "manifest.json"), "--output-dir", str(templates)]), 1)
            model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
