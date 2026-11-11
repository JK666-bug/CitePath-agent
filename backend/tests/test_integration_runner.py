"""Synthetic protocol checks; these are not live API observations."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluation.__main__ import main
from evaluation.integration import (ApiClient, IntegrationFailure, NoRedirects,
                                    OwnedApiProcess, check_rounds,
                                    development_documents, local_api_url,
                                    run_integration)


def preflight(ready=True):
    return {"status": "prerequisites_available" if ready else "blocked", "checks": [
        {"name": name, "ready": ready} for name in
        ("model_configuration", "mysql_listener", "milvus_listener", "api_health")]}


class ProtocolClient:
    """A deliberately small persisted API double with two real protocol rounds."""
    def __init__(self, url, *, first_pass=False, duplicate_corrupts=False):
        self.requests = []
        self.first_pass = first_pass
        self.duplicate_corrupts = duplicate_corrupts
        self.responses = {}
        self.plan = {"version": 1, "chapters": [{"id": 5, "sources": [{"document_id": 2}]}],
                     "tasks": [{"id": "read-5", "kind": "Reading", "status": "Scheduled"}]}
        self.state = {"id": 9, "status": "open", "round_number": 1, "passing_threshold": .8,
                      "round_results": [], "round_question_count": 1, "answered_count": 0,
                      "question": self.question(1), "report": None}

    @staticmethod
    def question(number):
        return {"id": number, "kind": "mcq", "prompt": "Choose a statement",
                "concept_name": "Sequences", "response": ""}

    def request(self, method, path, payload=None, pdf=None):
        self.requests.append({"method": method, "path": path})
        if path == "/api/register":
            return {"id": 11}
        if path == "/api/courses":
            return {"id": 4}
        if path.endswith("/documents"):
            return {"document_id": 2 if len(self.plan["chapters"]) == 1 else 3, "ingest_status": "complete"}
        if path.endswith("/plan/tasks/read-5/complete"):
            self.plan["tasks"][0]["status"] = "Completed"
            self.plan["version"] += 1
            return {"plan": copy.deepcopy(self.plan)}
        if path.endswith("/plan"):
            if payload and payload.get("update_materials"):
                self.plan["chapters"].append({"id": 6, "sources": [{"document_id": 3}]})
                self.plan["version"] += 1
            return {"status": "ready", "plan": copy.deepcopy(self.plan), "material_update": {"new_page_count": 5}}
        if path.endswith("/practice"):
            return copy.deepcopy(self.state)
        if path.endswith("/draft"):
            self.state["question"]["response"] = payload["response"]
            return {"saved": True}
        if path.endswith("/answer"):
            number = payload["question_id"]
            if number in self.responses:
                if self.duplicate_corrupts:
                    self.state["round_results"][0]["correct_count"] = 1
                return copy.deepcopy(self.state)
            self.responses[number] = payload["response"]
            passed = self.first_pass
            self.state["round_results"].append({"round_number": number, "correct_count": int(passed),
                "total": 1, "passed": passed, "weak_concepts": [] if passed else ["Sequences"]})
            if passed or number == 2:
                self.state.update(status="finished", question=None, answered_count=1,
                    report={"outcome": f"passed_round_{number}" if passed else "failed_after_2",
                            "passed": passed, "questions": [{"question_id": key, "response": value}
                                                           for key, value in self.responses.items()],
                            "wrong": [] if passed else [{"question_id": 1}]})
            else:
                self.state.update(round_number=2, question=self.question(2))
            return copy.deepcopy(self.state)
        if path.endswith("/questions") or path == "/api/logout":
            return {}
        if path.endswith("/practice/9") or path.endswith("/explanation/retry"):
            return copy.deepcopy(self.state)
        raise AssertionError((method, path))


class IntegrationRunnerTest(unittest.TestCase):
    def run_protocol(self, **kwargs):
        first_pass = kwargs.pop("first_pass", False)
        duplicate_corrupts = kwargs.pop("duplicate_corrupts", False)
        with patch("evaluation.integration.development_documents", return_value={2: Path("l2.pdf"), 3: Path("l3.pdf")}):
            return run_integration(allow_create=True, prerequisite_check=lambda _: preflight(),
                client_factory=lambda url: ProtocolClient(url, first_pass=first_pass,
                                                         duplicate_corrupts=duplicate_corrupts), **kwargs)

    def test_local_origin_and_redirect_guards_prevent_credential_forwarding(self):
        for url in ("https://example.com", "http://localhost:9000/api", "http://x:secret@localhost", "http://localhost?token=x"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                local_api_url(url)
        self.assertEqual(local_api_url("http://127.0.0.1:8000/"), "http://127.0.0.1:8000")
        with self.assertRaisesRegex(IntegrationFailure, "redirect"):
            NoRedirects().redirect_request(None, None, 307, "redirect", {}, "https://elsewhere.test")

    def test_blocked_preflight_and_missing_create_flag_never_mutate(self):
        for ready, allow, expected in ((False, True, "blocked"), (True, False, "not_run")):
            with patch("evaluation.integration.ApiClient.request") as request:
                result = run_integration(allow_create=allow, prerequisite_check=lambda _: preflight(ready))
                self.assertEqual(result["status"], expected)
                self.assertFalse(result["mutation_requests_sent"])
                request.assert_not_called()

    def test_two_round_protocol_includes_recovery_qa_and_material_preservation(self):
        result = self.run_protocol(include_new_materials=True)
        self.assertEqual(result["status"], "completed", result.get("failure"))
        self.assertTrue(result["synthetic"])
        self.assertFalse(result["formal_evaluation_run"])
        self.assertIsNone(result["official_accepted"])
        self.assertEqual(result["actual_round_count"], 2)
        names = {row["name"] for row in result["checks"] if row["status"] == "passed"}
        self.assertTrue({"draft_and_question_restored", "duplicate_submission_preserves_saved_result",
                        "independent_qa_preserves_practice_state", "material_update_preserves_completed_task",
                        "explanation_retry_preserves_official_result", "material_update_preserves_finished_practice"} <= names)
        self.assertFalse(result["cleanup_performed"])
        self.assertNotIn("password", json.dumps(result))
        self.assertNotIn("Choose a statement", json.dumps(result))

    def test_first_round_pass_does_not_claim_second_round_execution(self):
        result = self.run_protocol(first_pass=True)
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["round_2_observed"])
        self.assertIn({"name": "second_round_execution", "status": "not_run",
                       "reason": "The actual first round passed; this run does not establish second-round execution"}, result["checks"])

    def test_duplicate_corruption_is_a_failed_observation(self):
        result = self.run_protocol(duplicate_corrupts=True)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure"]["code"], "duplicate_submission_preserves_saved_result")

    def test_answer_limit_and_invalid_fixture_stop_before_further_mutation(self):
        result = self.run_protocol(max_answers=1)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(sum(row["path"].endswith("/answer") for row in result["requests"]), 2)  # original + idempotence probe
        result = self.run_protocol(answers=["invalid"])
        self.assertFalse(result["mutation_requests_sent"])

    def test_forbidden_third_round_and_rounded_pass_are_rejected(self):
        client = ProtocolClient("http://localhost")
        state = copy.deepcopy(client.state)
        state["round_number"] = 3
        with self.assertRaises(IntegrationFailure):
            check_rounds(state, .8)
        state = copy.deepcopy(client.state)
        state["round_results"] = [{"round_number": 1, "correct_count": 3, "total": 4, "passed": True}]
        with self.assertRaisesRegex(IntegrationFailure, "unrounded"):
            check_rounds(state, .8)
        state.update(status="finished", round_number=1, report={"outcome": "failed_after_2"})
        state["round_results"][0]["passed"] = False
        with self.assertRaisesRegex(IntegrationFailure, "before_required_second_round"):
            check_rounds(state, .8)

    def test_restart_detects_changed_persisted_question_content(self):
        from evaluation.integration import practice_snapshot
        state = ProtocolClient("http://localhost").state
        before = practice_snapshot(state)
        state["question"]["prompt"] = "Unexpected regenerated question"
        self.assertNotEqual(practice_snapshot(state), before)

    def test_only_owned_api_process_can_be_restarted(self):
        with self.assertRaisesRegex(IntegrationFailure, "no_owned_api"):
            OwnedApiProcess("http://127.0.0.1:8123").restart()
        fake = unittest.mock.Mock()
        fake.poll.return_value = None
        process = OwnedApiProcess("http://127.0.0.1:8123")
        process.process = fake
        process.stop()
        fake.terminate.assert_called_once()
        self.assertIsNone(process.process)

    def test_owned_start_failure_is_cleaned_up_and_shutdown_failure_fails_report(self):
        setup = preflight()
        setup["status"] = "blocked"
        setup["checks"][-1]["ready"] = False
        process = unittest.mock.Mock()
        process.start.side_effect = IntegrationFailure("managed_api_exited_during_start")
        result = run_integration(allow_create=True, manage_api_process=True,
                                 prerequisite_check=lambda _: setup, process_factory=lambda _: process)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["mutation_requests_sent"])
        process.stop.assert_called_once()
        process.stop.side_effect = OSError("private runtime detail")
        result = run_integration(allow_create=True, manage_api_process=True,
                                 prerequisite_check=lambda _: setup, process_factory=lambda _: process)
        self.assertEqual(result["failure"]["code"], "owned_api_shutdown_failed")
        self.assertNotIn("private runtime detail", json.dumps(result))

    def test_development_corpus_failure_stops_before_creating_account(self):
        with patch("evaluation.integration.development_documents", side_effect=IntegrationFailure("development_pdf_checksum_mismatch")):
            result = run_integration(allow_create=True, prerequisite_check=lambda _: preflight())
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["mutation_requests_sent"])

    def test_original_corpus_only_selects_checksum_verified_development_pdfs(self):
        from evaluation.integration import ROOT
        selected = development_documents(ROOT / "data/mit-6.006-spring-2020/corpus.json")
        self.assertEqual(set(selected), {2, 3})

    def test_cli_writes_blocked_status_without_claiming_a_pass(self):
        with tempfile.TemporaryDirectory() as temp, patch("evaluation.integration.run_integration", return_value={
                "status": "blocked", "formal_evaluation_run": False}) as run:
            path = Path(temp) / "run.json"
            self.assertEqual(main(["live-integration", "--output", str(path)]), 2)
            self.assertEqual(json.loads(path.read_text())["status"], "blocked")
            self.assertFalse(run.call_args.kwargs["allow_create"])


if __name__ == "__main__":
    unittest.main()
