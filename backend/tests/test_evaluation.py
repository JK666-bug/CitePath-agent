"""Synthetic evaluator checks. These fixtures are never final evaluation evidence."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluation.__main__ import adjudication_template, import_predictions, main
from evaluation.core import (digest, distribution, evaluate, prepare_labels,
                             summarize_usage, validate_dataset)

SOURCE = {"document_id": "dev-2", "page_number": 1}
FREEZE = {"manifest_sha256": "a" * 64, "git_commit": "b" * 40,
          "created_at": "2026-11-11T00:00:00+08:00", "model": "test-model"}


def prediction(**fields):
    return {"collected_at": "2026-11-11T01:00:00+08:00",
            "configuration_sha256": FREEZE["manifest_sha256"], "model": FREEZE["model"], **fields}


def sample_data():
    mcq = {"id": "m", "kind": "mcq", "lecture": 2, "question": "Which statement?",
           "response": "A", "answer_key": "A", "options": ["Fact", "Other", "Third", "Fourth"],
           "sources": [SOURCE], "predictions": {v: prediction(correct=True) for v in ("baseline", "full")}}
    short = {"id": "s", "kind": "short", "lecture": 2, "question": "Explain the structure.",
             "response": "Four facts", "rubric": ["One", "Two", "Three", "Four", "Five"],
             "sources": [SOURCE], "predictions": {v: prediction(correct=True) for v in ("baseline", "full")}}
    evidence = {"id": "e", "kind": "evidence", "lecture": 2, "question": "What is the fact?",
                "sources": [SOURCE], "reference_points": ["The fact"],
                "predictions": {v: prediction(answer="A fact.", refused=False,
                                               claims=[{"id": "c", "text": "A fact.", "citations": [SOURCE]}])
                                for v in ("baseline", "full")}}
    return {"schema": "citepath-evaluation-v1", "evaluation_id": "synthetic-test", "split": "development",
            "synthetic": True, "freeze": FREEZE,
            "documents": [{"id": "dev-2", "lecture": 2, "sha256": "c" * 64,
                           "page_count": 2, "teaching_pages": [1]}],
            "items": [mcq, short, evidence]}


def human_labels(data):
    template, _ = prepare_labels(data)
    result = []
    for name in ("human-a", "human-b"):
        doc = copy.deepcopy(template)
        doc.update(annotator_id=name, independent=True, label_origin="human")
        for label in doc["labels"]:
            if "correct" in label:
                label["correct"] = True
            elif "hits" in label:
                label["hits"] = [0, 1, 2, 3]
            else:
                label.update(supported=True, answer_correct=True, claims_complete=True,
                             reference_point_hits=[0], claim_support={"c": True}, irrelevant_citations=[])
            if "question_audit" in label:
                label["question_audit"] = {key: True for key in label["question_audit"]}
        result.append(doc)
    return result


def final_data():
    prototype = sample_data()
    items = []
    for kind, count, origin in (("mcq", 20, prototype["items"][0]),
                                ("short", 40, prototype["items"][1]),
                                ("evidence", 40, prototype["items"][2])):
        for number in range(count):
            item = copy.deepcopy(origin)
            item.update(id=f"{kind}-{number:02d}", lecture=4)
            item["sources"] = [{"document_id": "final-4", "page_number": 1}]
            for pred in item["predictions"].values():
                for claim in pred.get("claims") or []:
                    claim["citations"] = copy.deepcopy(item["sources"])
            if kind == "evidence" and number >= 30:
                item["reference_points"] = []
                for pred in item["predictions"].values():
                    pred.update(answer="The notes do not support this question.", refused=True, claims=[])
            items.append(item)
    for number in range(20):
        expected = {"transitions": ["start", "finish"], "final_state": "finished"}
        item = {"id": f"workflow-{number:02d}", "kind": "workflow", "lecture": 4,
                "question": "A synthetic controller scenario", "expected": {v: expected for v in ("baseline", "full")},
                "predictions": {v: prediction(runs=[{"repeat": repeat, **expected,
                                    "round_count": 1 if v == "baseline" else 2,
                                    "third_round": False, "duplicate_scoring": False, "qa_score_changed": False,
                                    "grading_feedback_latency_ms": 10 * repeat} for repeat in (1, 2, 3)])
                                for v in ("baseline", "full")}}
        items.append(item)
    data = {**prototype, "split": "final", "items": items,
            "documents": [{"id": "final-4", "lecture": 4, "sha256": "d" * 64,
                           "page_count": 2, "teaching_pages": [1]}]}
    annotations = human_labels(data)
    for doc in annotations:
        for label in doc["labels"]:
            if label["item_id"].startswith("evidence-") and int(label["item_id"].split("-")[1]) >= 30:
                label.update(supported=False, answer_correct=True, reference_point_hits=[], claim_support={})
    return data, annotations


class EvaluationMetricsTest(unittest.TestCase):
    def test_blank_templates_and_predictions_remain_pending(self):
        data = sample_data()
        for item in data["items"]:
            item["predictions"] = {"baseline": None, "full": None}
        template, workitems = prepare_labels(data)
        report = evaluate(data, [template, copy.deepcopy(template)])
        self.assertIsNone(report["official_accepted"])
        self.assertEqual(report["status"], "pending")
        self.assertIsNone(report["variants"]["full"]["short_agreement"]["value"])
        self.assertFalse(template["independent"])
        self.assertEqual(template["label_origin"], "unassigned")
        self.assertNotIn("predictions", workitems["items"][0])
        self.assertNotIn("answer_key", workitems["items"][0])

    def test_exact_eighty_percent_and_separate_false_pass_false_failure(self):
        data = sample_data()
        labels = human_labels(data)
        report = evaluate(data, labels)
        self.assertEqual(report["variants"]["full"]["short_agreement"]["value"], 1)
        for doc in labels:
            next(label for label in doc["labels"] if label["item_id"] == "s")["hits"] = [0, 1, 2]
        metric = evaluate(data, labels)["variants"]["full"]["short_agreement"]
        self.assertEqual(metric["false_passes"], 1)
        self.assertEqual(metric["false_failures"], 0)
        for doc in labels:
            next(label for label in doc["labels"] if label["item_id"] == "s")["hits"] = [0, 1, 2, 3]
        data["items"][1]["predictions"]["full"]["correct"] = False
        for doc in labels:
            doc["dataset_sha256"] = digest(data)
        metric = evaluate(data, labels)["variants"]["full"]["short_agreement"]
        self.assertEqual(metric["false_passes"], 0)
        self.assertEqual(metric["false_failures"], 1)

    def test_missing_and_attribution_citations_fail_even_when_human_support_true(self):
        for citations, field in (([], "missing_citation_claims"),
                                 ([{"document_id": "dev-2", "page_number": 2}], "invalid_citation_claims")):
            data = sample_data()
            data["items"][2]["predictions"]["full"]["claims"][0]["citations"] = citations
            metric = evaluate(data, human_labels(data))["variants"]["full"]["citation_support"]
            self.assertEqual(metric["value"], 0)
            self.assertEqual(metric[field], 1)
            self.assertFalse(metric["target_met"])

    def test_supported_refusal_is_an_answer_failure(self):
        data = sample_data()
        data["items"][2]["predictions"]["full"].update(refused=True, claims=[], answer="No answer")
        labels = human_labels(data)
        for doc in labels:
            if doc["labels"][-1]["variant"] == "full":
                doc["labels"][-1]["claim_support"] = {}
        metrics = evaluate(data, labels)["variants"]["full"]
        self.assertEqual(metrics["unsupported_refusal"]["supported_questions_refused"], 1)
        self.assertEqual(metrics["answer_correctness"]["value"], 0)
        self.assertEqual(metrics["reference_answer_point_coverage"]["value"], 0)

    def test_human_disagreement_is_pending_until_both_members_review_resolution(self):
        data, labels = sample_data(), human_labels(sample_data())
        labels[1]["labels"][0]["correct"] = False
        report = evaluate(data, labels)
        self.assertEqual(report["annotation_disagreements"], 1)
        self.assertIsNone(report["variants"]["full"]["mcq_agreement"]["value"])
        template, differences = adjudication_template(data, labels)
        self.assertEqual(len(differences), 1)
        self.assertEqual(template["labels"], [])
        resolution = {**copy.deepcopy(labels[0]["labels"][0]), "reason": "Both members checked source page 1."}
        template.update(adjudicator_id="human-a", labels=[resolution])
        metric = evaluate(data, labels, template)["variants"]["full"]["mcq_agreement"]
        self.assertEqual(metric["value"], 1)
        template["reviewed_by"] = ["human-a"]
        with self.assertRaisesRegex(ValueError, "Both original"):
            evaluate(data, labels, template)

    def test_twenty_workflows_three_repeats_and_prohibited_errors(self):
        data, labels = final_data()
        report = evaluate(data, labels)
        workflow = report["variants"]["full"]["workflow"]
        self.assertTrue(workflow["target_met"])
        self.assertEqual(workflow["runs_completed"], 60)
        self.assertIsNone(report["official_accepted"], "Synthetic evidence must never become an official result")
        data["items"][-1]["predictions"]["full"]["runs"][0]["round_count"] = 3
        for doc in labels:
            doc["dataset_sha256"] = digest(data)
        workflow = evaluate(data, labels)["variants"]["full"]["workflow"]
        self.assertFalse(workflow["target_met"])
        self.assertIn("third_round", workflow["prohibited_errors"][0]["errors"])
        self.assertEqual(workflow["repeats"][0]["passed"], 19)

    def test_different_failed_scenarios_across_repeats_cannot_hide_below_eighteen(self):
        data, labels = final_data()
        workflows = [item for item in data["items"] if item["kind"] == "workflow"]
        for repeat in (1, 2, 3):
            for offset in (0, 1):
                item = workflows[(repeat - 1) * 2 + offset]
                item["predictions"]["full"]["runs"][repeat - 1]["final_state"] = "unexpected"
        for document in labels:
            document["dataset_sha256"] = digest(data)
        workflow = evaluate(data, labels)["variants"]["full"]["workflow"]
        self.assertEqual([row["passed"] for row in workflow["repeats"]], [18, 18, 18])
        self.assertEqual(workflow["scenarios_passed"], 14)
        self.assertEqual(workflow["scenarios_failed"], 6)
        self.assertFalse(workflow["target_met"])
        self.assertTrue(all("target_met" not in row for row in workflow["repeats"]))

    def test_missing_repeat_is_pending_and_an_observed_failure_already_fails_scenario(self):
        data, labels = final_data()
        item = data["items"][-1]
        item["predictions"]["full"]["runs"].pop()
        for document in labels:
            document["dataset_sha256"] = digest(data)
        workflow = evaluate(data, labels)["variants"]["full"]["workflow"]
        self.assertEqual(workflow["scenarios_pending"], 1)
        self.assertIsNone(workflow["target_met"])
        item["predictions"]["full"]["runs"][0]["final_state"] = "unexpected"
        for document in labels:
            document["dataset_sha256"] = digest(data)
        workflow = evaluate(data, labels)["variants"]["full"]["workflow"]
        self.assertEqual(workflow["scenarios_failed"], 1)
        self.assertEqual(workflow["scenario_results"][-1]["repeats_observed"], 2)
        self.assertIsNone(workflow["target_met"])

    def test_every_prohibited_error_in_either_variant_defeats_official_acceptance(self):
        # Eligibility is deliberately exercised with a contrived in-memory fixture;
        # this test data is never exported as human or live evaluation evidence.
        for variant in ("baseline", "full"):
            for prohibited in ("third_round", "duplicate_scoring", "qa_score_changed"):
                with self.subTest(variant=variant, prohibited=prohibited):
                    data, labels = final_data()
                    data["synthetic"] = False
                    item = data["items"][-1]
                    item["predictions"][variant]["runs"][0][prohibited] = True
                    for document in labels:
                        document["dataset_sha256"] = digest(data)
                    report = evaluate(data, labels)
                    self.assertEqual(report["status"], "complete")
                    self.assertFalse(report["official_accepted"])
                    self.assertEqual(report["variants"]["full"]["workflow"]["scenarios_passed"], 20 if variant == "baseline" else 19)
                    self.assertEqual(report["prohibited_errors"][0]["variant"], variant)
                    self.assertIn(prohibited, report["prohibited_errors"][0]["errors"])

    def test_two_ordinary_failed_scenarios_still_meet_eighteen_of_twenty_target(self):
        data, labels = final_data()
        data["synthetic"] = False
        workflows = [item for item in data["items"] if item["kind"] == "workflow"]
        for item in workflows[-2:]:
            item["predictions"]["full"]["runs"][0]["final_state"] = "unexpected"
        for document in labels:
            document["dataset_sha256"] = digest(data)
        report = evaluate(data, labels)
        self.assertEqual(report["variants"]["full"]["workflow"]["scenarios_passed"], 18)
        self.assertTrue(report["variants"]["full"]["workflow"]["target_met"])
        self.assertTrue(report["official_accepted"])

    def test_required_actual_actions_are_pending_when_missing_and_fail_when_mismatched(self):
        data, labels = final_data()
        item = next(item for item in data["items"] if item["kind"] == "workflow")
        item["expected"]["full"] = {**item["expected"]["full"],
                                      "actions": ["submit_round_1", "repeat_saved_submission", "verify_score_unchanged"]}

        def scenario():
            for document in labels:
                document["dataset_sha256"] = digest(data)
            return evaluate(data, labels)["variants"]["full"]["workflow"]["scenario_results"][0]

        self.assertEqual(scenario()["status"], "pending")
        for run in item["predictions"]["full"]["runs"]:
            run["actions"] = ["submit_round_1"]
        self.assertEqual(scenario()["status"], "failed")
        for run in item["predictions"]["full"]["runs"]:
            run["actions"] = list(item["expected"]["full"]["actions"])
        self.assertEqual(scenario()["status"], "passed")

    def test_freeze_split_stale_labels_and_invalid_hits_are_rejected(self):
        data = sample_data()
        labels = human_labels(data)
        labels[0]["dataset_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "different frozen dataset"):
            evaluate(data, labels)
        labels = human_labels(data)
        labels[0]["labels"][1]["hits"] = [True]
        with self.assertRaisesRegex(ValueError, "Invalid or duplicate"):
            evaluate(data, labels)
        data["documents"][0]["lecture"] = 4
        with self.assertRaisesRegex(ValueError, "splits"):
            validate_dataset(data)

    def test_before_freeze_or_different_model_cannot_be_formal_observation(self):
        for change in ({"collected_at": "2026-11-10T00:00:00+08:00"}, {"model": "other"}):
            data = sample_data()
            data["items"][0]["predictions"]["full"].update(change)
            with self.assertRaises(ValueError):
                evaluate(data)


class EvaluationToolsTest(unittest.TestCase):
    def test_unknown_usage_and_currency_mismatch_are_not_zero_cost(self):
        usage = summarize_usage([{"model_calls": 1, "latency_ms": 10, "estimated_cost": .1,
                                  "cost_currency": "USD", "input_tokens": 20},
                                 {"model_calls": 1, "latency_ms": None, "estimated_cost": None}])
        self.assertIsNone(usage["estimated_cost"]["total"])
        self.assertEqual(usage["estimated_cost"]["known_subtotal"], .1)
        self.assertEqual(usage["latency_ms"]["unknown"], 1)
        self.assertEqual(distribution([1, 2, 3, 4, 5])["p95"], 5)

    def test_prediction_import_binds_snapshot_and_refuses_overwrite(self):
        data = sample_data()
        data["items"][0]["predictions"]["full"] = None
        records = {"dataset_sha256": digest(data), "records": [{"item_id": "m", "variant": "full", "prediction": prediction(correct=True)}]}
        collected = import_predictions(data, records)
        self.assertTrue(collected["items"][0]["predictions"]["full"]["correct"])
        self.assertIsNone(data["items"][0]["predictions"]["full"])
        records["dataset_sha256"] = digest(collected)
        with self.assertRaisesRegex(ValueError, "cannot be overwritten"):
            import_predictions(collected, records)

    def test_cli_creates_blank_labels_and_pending_report_without_any_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dataset = root / "dataset.json"
            dataset.write_text(json.dumps(sample_data()), encoding="utf-8")
            self.assertEqual(main(["labels", str(dataset), "--output-dir", str(root / "labels")]), 0)
            self.assertEqual(main(["score", str(dataset), "--output", str(root / "report.json")]), 0)
            self.assertIsNone(json.loads((root / "report.json").read_text())["official_accepted"])
            self.assertEqual(main(["score", str(dataset), "--output", str(root / "strict.json"), "--require-complete"]), 2)
            self.assertEqual(main(["labels", str(dataset), "--output-dir", str(root / "labels")]), 1)

    def test_preflight_missing_services_records_blocked_without_model_call(self):
        from evaluation.live import preflight_report
        with patch.dict(os.environ, {"HKU_API_KEY": ""}), \
                patch("evaluation.live.socket.create_connection", side_effect=OSError), \
                patch("evaluation.live.urllib.request.urlopen", side_effect=OSError):
            report = preflight_report()
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["model_invoked"])
        self.assertFalse(report["formal_evaluation_run"])


if __name__ == "__main__":
    unittest.main()
