"""Synthetic adapter tests exercise checkpoint/fairness guards, not live quality."""
import copy
import json
import tempfile
import unittest
import os
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

from evaluation.core import digest, _workflow_runs, validate_dataset
from evaluation.workflows import collect_workflows, MySQLPracticeAdapter, response_for
from tests.test_evaluation import sample_data


class ControllerAdapter:
    synthetic = True

    def __init__(self):
        self.sessions = {}
        self.counter = 0
        self.prepared = 0
        self.corrupt_clone = False
        self.fail_second = False

    def verify_configuration(self, data, bindings):
        return {"provider": "hku", "model": data["freeze"]["model"], "base_url_sha256": "f" * 64}

    def validate_pair(self, pair):
        pass

    def supports(self, name):
        return False

    def create(self, fixture, threshold):
        self.counter += 1
        self.sessions[self.counter] = {"status": "open", "round_number": 1,
            "passing_threshold": threshold, "round_results": [], "report": None, "bank": []}
        return self.counter

    def prepare_shared(self, fixture, session, answers):
        self.prepared += 1
        self.sessions[session]["bank"] = [{"question_id": session * 10, "round_number": 1,
            "concept_name": "Hashing", "kind": "short", "prompt": "Explain hashing", "answer": "A map",
            "rubric": ["Map"], "options": [], "source_content": [[1, "page-hash"]], "response": "An uncertain answer",
            "correct": False, "points_hit": 0, "points_total": 1, "rubric_hits": [],
            "explanation": "Observed feedback", "explanation_status": "ready", "explanation_error": None,
            "explanation_attempts": 1}]

    def clone_first(self, fixture, session, bank):
        if not self.sessions[session]["bank"]:
            self.sessions[session]["bank"] = copy.deepcopy(bank)
            self.sessions[session]["bank"][0]["question_id"] = session * 10
        if self.corrupt_clone:
            self.sessions[session]["bank"][0]["explanation"] = "Changed feedback"

    def state(self, fixture, session):
        return copy.deepcopy(self.sessions[session])

    def advance(self, fixture, session, variant):
        state = self.sessions[session]
        if state["round_results"]:
            return
        state["round_results"] = [{"round_number": 1, "correct_count": 0, "total": 1, "passed": False, "weak_concepts": ["Hashing"]}]
        if variant == "baseline":
            state.update(status="finished", report={"outcome": "failed"})
        else:
            state["round_number"] = 2
            state["bank"].append({**state["bank"][0], "question_id": session * 10 + 1, "round_number": 2})

    def finish_second(self, fixture, session, answers):
        if self.fail_second:
            raise RuntimeError("private model token must not be logged")
        state = self.sessions[session]
        state["round_results"].append({"round_number": 2, "correct_count": 1, "total": 1, "passed": True, "weak_concepts": []})
        state.update(status="finished", report={"outcome": "passed_round_2"})

    def reopen(self, fixture, session, variant):
        return self.state(fixture, session)

    def duplicate(self, fixture, session, variant):
        return {"grading_calls": 0}

    def ask(self, fixture, question):
        return None


def cohort(count=1, name="normal"):
    data = sample_data()
    transitions = ["start", "round1_generated", "round1_submitted", "round1_scored"]
    data["items"] = [{"id": f"WF-{number:02}", "kind": "workflow", "lecture": 2, "question": "Exercise a saved workflow",
        "scenario": {"name": name, "passing_threshold": .8, "round1": {"correct": 0, "total": 1}, "round2": {"result": "pass"}},
        "expected": {"baseline": {"transitions": transitions + ["finished"], "final_state": "failed", "actions": []},
                     "full": {"transitions": transitions + ["round2_generated", "round2_submitted", "round2_scored", "finished"],
                              "final_state": "passed_round_2", "actions": []}},
        "predictions": {"baseline": None, "full": None}} for number in range(1, count + 1)]
    bindings = {"dataset_sha256": digest(data), "configuration_sha256": data["freeze"]["manifest_sha256"], "cases": {}}
    identity = 0
    for item in data["items"]:
        bindings["cases"][item["id"]] = {}
        for repeat in range(1, 4):
            pair = {}
            for role in ("shared", "baseline", "full"):
                identity += 1
                pair[role] = {"user_id": identity, "course_id": identity, "chapter_id": identity}
            bindings["cases"][item["id"]][str(repeat)] = pair
    return data, bindings


class WorkflowCollectionTest(unittest.TestCase):
    def test_reference_policies_create_responses_instead_of_injecting_grades(self):
        mcq = {"kind": "mcq", "prompt": "Choose", "answer": "B"}
        short = {"kind": "short", "prompt": "Explain", "rubric_json": ["A map", "Collision handling"]}
        self.assertEqual(response_for(mcq, {"policy": "reference"}, 1), "B")
        self.assertEqual(response_for(mcq, {"policy": "wrong_reference"}, 1), "A")
        self.assertEqual(response_for(short, {"policy": "reference"}, 1), "A map; Collision handling")
        self.assertIsInstance(response_for(short, {"policy": "wrong_reference"}, 1), str)
        with self.assertRaisesRegex(ValueError, "Unknown recorded"):
            response_for(short, {"policy": "inject_pass"}, 1)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def run_collection(self, data, bindings, adapter, **kwargs):
        return collect_workflows(data, bindings=bindings, answers={"short": "An uncertain answer"},
                                 checkpoint_dir=self.directory, adapter=adapter, allow_create_sessions=True, **kwargs)

    def test_dry_default_does_not_verify_or_create_database_sessions(self):
        data, bindings = cohort()
        result = collect_workflows(data, bindings=bindings, answers={}, checkpoint_dir=self.directory)
        self.assertEqual(result["status"], "not_run")
        self.assertEqual(result["records"], [])
        self.assertFalse(list(self.directory.iterdir()))

    def test_twenty_scenarios_three_repeats_have_120_traces_and_60_shared_rounds(self):
        data, bindings = cohort(20)
        adapter = ControllerAdapter()
        result = self.run_collection(data, bindings, adapter)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["synthetic"])
        self.assertEqual(result["records"], [])
        self.assertEqual(len(result["run_statuses"]), 120)
        self.assertEqual(adapter.prepared, 60)
        self.assertEqual(adapter.counter, 180)
        by_id = {item["id"]: item for item in data["items"]}
        for row in result["controller_records"]:
            runs = _workflow_runs(by_id[row["item_id"]], row["variant"], row["prediction"])
            self.assertTrue(all(run["passed"] is True for run in runs))
        before = (adapter.prepared, adapter.counter)
        resumed = self.run_collection(data, bindings, adapter)
        self.assertEqual((adapter.prepared, adapter.counter), before)
        self.assertEqual(resumed["controller_records"][0]["prediction"]["runs"], result["controller_records"][0]["prediction"]["runs"])

    def test_changed_feedback_or_grade_never_becomes_a_passing_formal_record(self):
        data, bindings = cohort()
        adapter = ControllerAdapter()
        adapter.corrupt_clone = True
        result = self.run_collection(data, bindings, adapter)
        self.assertEqual(result["status"], "pending")
        self.assertTrue(all(row["status"] == "failed" for row in result["run_statuses"]))
        self.assertEqual(result["records"], [])

    def test_partial_failure_resumes_without_regrading_first_round_or_losing_baseline(self):
        data, bindings = cohort()
        adapter = ControllerAdapter()
        adapter.fail_second = True
        first = self.run_collection(data, bindings, adapter)
        self.assertEqual(first["status"], "pending")
        self.assertEqual(adapter.prepared, 3)
        self.assertNotIn("private model token", json.dumps(first))
        adapter.fail_second = False
        second = self.run_collection(data, bindings, adapter)
        self.assertEqual(second["status"], "completed")
        self.assertEqual(adapter.prepared, 3)

    def test_known_prohibited_mutation_survives_later_collection_failure(self):
        data, bindings = cohort(name="independent_qa")
        adapter = ControllerAdapter()
        def corrupt_and_fail(fixture, question):
            for state in adapter.sessions.values():
                if state["bank"]:
                    state["bank"][0]["correct"] = True
            raise RuntimeError("simulated connection failure after a forbidden write")
        adapter.ask = corrupt_and_fail
        result = self.run_collection(data, bindings, adapter)
        known = [run for row in result["controller_records"] for run in row["prediction"]["runs"]]
        self.assertTrue(any(run["qa_score_changed"] is True for run in known))
        scored = _workflow_runs(data["items"][0], "baseline", result["controller_records"][0]["prediction"])
        self.assertTrue(any("qa_score_changed" in run["prohibited_errors"] for run in scored))

    def test_legitimate_followup_after_completed_qa_is_not_reported_as_qa_mutation(self):
        data, bindings = cohort(name="independent_qa")
        adapter = ControllerAdapter()
        adapter.fail_second = True
        result = self.run_collection(data, bindings, adapter)
        full = next(row for row in result["controller_records"] if row["variant"] == "full")
        self.assertTrue(all(run["qa_score_changed"] is False for run in full["prediction"]["runs"]))

    def test_history_carryover_and_binding_changes_are_rejected(self):
        data, bindings = cohort()
        bindings["cases"]["WF-01"]["2"] = bindings["cases"]["WF-01"]["1"]
        adapter = ControllerAdapter()
        with self.assertRaisesRegex(ValueError, "history cannot carry"):
            self.run_collection(data, bindings, adapter)
        self.assertEqual(adapter.counter, 0)

    def test_unavailable_real_restart_and_fault_adapters_stay_pending(self):
        data, bindings = cohort(name="process_restart")
        adapter = ControllerAdapter()
        result = self.run_collection(data, bindings, adapter)
        self.assertEqual(adapter.prepared, 0)
        self.assertEqual(result["status"], "pending")
        self.assertTrue(all(row["status"] == "not_run" for row in result["run_statuses"]))

    def test_exact_count_mismatch_fails_even_if_transition_shape_matches(self):
        data, bindings = cohort()
        data["items"][0]["scenario"]["round1"]["correct"] = 1
        bindings["dataset_sha256"] = digest(data)
        result = self.run_collection(data, bindings, ControllerAdapter())
        row = result["controller_records"][0]
        observed = _workflow_runs(data["items"][0], row["variant"], row["prediction"])
        self.assertTrue(all(run["passed"] is False for run in observed))

    def test_synthetic_traces_cannot_be_imported_into_real_cohort(self):
        data, bindings = cohort()
        result = self.run_collection(data, bindings, ControllerAdapter())
        real = copy.deepcopy(data)
        real["synthetic"] = False
        real["items"][0]["predictions"]["baseline"] = result["controller_records"][0]["prediction"]
        with self.assertRaisesRegex(ValueError, "Synthetic observations"):
            validate_dataset(real)

    def test_changed_checkpoint_bytes_cannot_silently_replace_saved_runs(self):
        data, bindings = cohort()
        adapter = ControllerAdapter()
        self.run_collection(data, bindings, adapter)
        path = self.directory / "WF-01-1.json"
        stored = json.loads(path.read_text())
        stored["payload"]["runs"]["baseline"]["final_state"] = "invented"
        path.write_text(json.dumps(stored))
        with self.assertRaisesRegex(ValueError, "checkpoint content"):
            self.run_collection(data, bindings, adapter)

    def test_duplicate_after_final_runs_after_second_round_not_before_it(self):
        data, bindings = cohort(name="duplicate_after_final")
        adapter = ControllerAdapter()
        events = []
        original = adapter.duplicate
        def duplicate(fixture, session, variant):
            events.append((variant, adapter.state(fixture, session)["status"]))
            return original(fixture, session, variant)
        adapter.duplicate = duplicate
        result = self.run_collection(data, bindings, adapter)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(all(status == "finished" for variant, status in events))


class RealAdapterProbeTest(unittest.TestCase):
    def test_usage_is_scoped_and_missing_prices_are_unknown_instead_of_zero(self):
        adapter = MySQLPracticeAdapter()
        adapter.frozen_data = {"evaluation_id": "usage-fixture"}
        base = {"status": "ok", "model_calls": 1, "input_tokens": 10, "output_tokens": 5,
                "estimated_cost": None, "cost_currency": None}
        rows = [{**base, "context": {"evaluation_id": "usage-fixture", "item_id": "WF-01", "repeat": 1, "system": system}}
                for system in ("shared_first_round", "full")]
        rows.append({**base, "model_calls": 999, "context": {"evaluation_id": "another-run", "system": "full"}})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            with patch.dict(os.environ, {"MODEL_USAGE_LOG": str(path)}):
                observed = adapter.recorded_usage("WF-01", 1, "full", extra_expected=True)
                self.assertEqual(observed["model_calls"], 2)
                self.assertEqual(observed["input_tokens"], 20)
                self.assertIsNone(observed["estimated_cost"])
                missing = adapter.recorded_usage("WF-02", 1, "full", extra_expected=True)
                self.assertNotIn("model_calls", missing)

    def test_injected_timeout_keeps_draft_and_retries_original_grader_once(self):
        from agent import practice as controller
        from db import practice as storage
        adapter = MySQLPracticeAdapter()
        fixture = {"user_id": 1, "course_id": 2, "chapter_id": 3}
        adapter.chapters[(1, 2, 3)] = {"concepts": [{"id": 4, "name": "Hashing"}]}
        session = {"id": 9, "course_id": 2, "drafts": {}, "round_results": []}
        question = {"id": 50, "kind": "short", "prompt": "Explain hashing", "rubric_json": ["Map"], "sources_json": []}
        answered = []
        def draft(_, identifier, response):
            session["drafts"][str(identifier)] = response
        with patch.object(storage, "practice_lock", return_value=nullcontext()), \
                patch.object(storage, "round_question_count", return_value=1), \
                patch.object(storage, "unanswered_question", side_effect=[question, None]), \
                patch.object(storage, "save_draft", side_effect=draft), \
                patch.object(storage, "get_owned_session", return_value=session), \
                patch.object(storage, "question_in_session", side_effect=lambda *_: {"answer_id": 1 if answered else None}), \
                patch.object(controller, "save_answer", side_effect=lambda *args: answered.append(args)), \
                patch.object(controller, "_grade_shorts", return_value={50: [0]}) as grader:
            events = adapter.prepare_shared(fixture, 9, {"short": "A map", "_inject_shared_timeout": True})
        self.assertEqual(session["drafts"]["50"], "A map")
        self.assertEqual(len(answered), 1)
        grader.assert_called_once()
        self.assertTrue(events["timeout_probe"]["real_retry_completed"])
        self.assertEqual(events["timeout_probe"]["injection_kind"], "controller_fault_not_provider_timeout")

    def test_owned_api_restart_reopens_same_question_and_draft(self):
        from evaluation.integration import ApiClient
        from db import practice as storage
        fixture = {"user_id": 1, "course_id": 2, "chapter_id": 3,
                   "username_env": "CITEPATH_PROBE_USER", "password_env": "CITEPATH_PROBE_PASSWORD"}
        adapter = MySQLPracticeAdapter()
        process = MagicMock()
        process.process = object()
        adapter.process = process
        adapter.process_url = "http://127.0.0.1:8011"
        adapter.frozen_data = adapter.frozen_manifest = {}
        before = {"id": 9, "status": "open", "round_number": 1, "passing_threshold": .8, "round_results": [],
                  "question": {"id": 50, "prompt": "Explain hashing", "kind": "short", "response": ""}}
        saved = copy.deepcopy(before)
        saved["question"]["response"] = "A map"
        client = MagicMock()
        client.request.side_effect = [{"id": 1, "username": "citepath_eval_probe"}, {}, before, {}, saved, saved, {}]
        with patch.dict(os.environ, {"CITEPATH_PROBE_USER": "citepath_eval_probe", "CITEPATH_PROBE_PASSWORD": "private-password"}), \
                patch.object(storage, "practice_lock", return_value=nullcontext()), \
                patch.object(storage, "store_round"), patch.object(adapter, "mapped_questions", return_value=[]), \
                patch("evaluation.integration.ApiClient", return_value=client), \
                patch("evaluation.runtime.verify_observed_runtime"):
            result = adapter.restart_probe(fixture, 9, [{"prompt": "Explain hashing", "kind": "short", "response": "A map"}])
        self.assertTrue(result["draft_and_questions_restored"])
        self.assertEqual(result["before_sha256"], result["after_sha256"])
        process.restart.assert_called_once()
        process.start.assert_not_called()
        self.assertNotIn("private-password", json.dumps(result))

    def test_wrong_pdf_hash_blocks_workflow_before_any_session_creation(self):
        adapter = MySQLPracticeAdapter()
        adapter.frozen_data = {"documents": [{"lecture": 2, "sha256": "a" * 64, "page_count": 2, "teaching_pages": [1]}]}
        fixture = {"user_id": 1, "course_id": 2, "chapter_id": 3}
        adapter.chapters[(1, 2, 3)] = {"pages": [{"document_id": 42, "page_number": 1}]}
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"is_active": 1, "content_hash": "b" * 64, "page_count": 2}
        with patch("db.connection.connect", return_value=connection), self.assertRaisesRegex(ValueError, "PDF differs"):
            adapter.validate_case({role: fixture for role in ("shared", "baseline", "full")}, {"lecture": 2})


if __name__ == "__main__":
    unittest.main()
