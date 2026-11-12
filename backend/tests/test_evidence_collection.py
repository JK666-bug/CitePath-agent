"""Synthetic HTTP fixtures verify collection discipline, never model quality."""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from evaluation.core import digest, evaluate
from evaluation.evidence import QA_POLICY, collect_evidence


class EvidenceCollectionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.manifest = {
            "created_at": "2020-01-01T00:00:00+00:00", "git_commit": "b" * 40,
            "provider": "hku", "model": "test-model", "base_url_sha256": "d" * 64,
            "source_sha256": {"agent/qa.py": "e" * 64},
            "working_tree_dirty": False, "installed_packages": {"test-package": "1.0"}, "python": "3.12.0",
        }
        path = self.directory / "manifest.json"
        path.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.data = {
            "schema": "citepath-evaluation-v1", "evaluation_id": "evidence-tests",
            "split": "development", "synthetic": False,
            "freeze": {key: self.manifest[key] for key in ("created_at", "git_commit", "provider", "model", "base_url_sha256")},
            "documents": [{"id": "lecture2", "lecture": 2, "sha256": "c" * 64, "page_count": 3, "teaching_pages": [1, 2]}],
            "items": [{"id": "e1", "kind": "evidence", "lecture": 2, "question": "Explain the actual notes.",
                       "sources": [{"document_id": "lecture2", "page_number": 1}], "reference_points": ["Candidate fact"],
                       "predictions": {"baseline": None, "full": None}}],
        }
        self.data["freeze"]["manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.config = {"schema": "citepath-evidence-runtime-v1", "manifest_path": str(path), "qa_policy": QA_POLICY, "variants": {}}
        self.secrets = {}
        for variant, course_id, document_id in (("baseline", 1, 11), ("full", 2, 22)):
            user_env, password_env = "CITEPATH_" + variant.upper() + "_USER", "CITEPATH_" + variant.upper() + "_PASSWORD"
            self.secrets[user_env] = "citepath_eval_" + variant
            self.secrets[password_env] = "secret-password-" + variant
            self.config["variants"][variant] = {
                "api_url": "http://127.0.0.1:8000", "course_id": course_id,
                "username_env": user_env, "password_env": password_env,
                "documents": [{"frozen_document_id": "lecture2", "runtime_document_id": document_id,
                               "sha256": "c" * 64, "page_count": 3}],
            }
        from unittest.mock import patch
        self.environment = patch.dict(os.environ, self.secrets)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.requests = []
        self.client_count = 0
        self.runtime_change = None
        self.response_change = None
        self.fail_question = None
        self.factory = self.client_factory

    def client_factory(self, origin):
        self.client_count += 1
        owner = self

        class Client:
            def __init__(self):
                self.variant = None

            def request(self, method, path, payload=None):
                owner.requests.append((method, path, copy.deepcopy(payload)))
                if path == "/api/login":
                    self.variant = next(v for v in ("baseline", "full") if payload["username"] == "citepath_eval_" + v)
                    return {"id": 10, "username": payload["username"]}
                if path == "/api/logout":
                    return {"ok": True}
                spec = owner.config["variants"][self.variant]
                if path.endswith("/evaluation/runtime"):
                    result = {"schema": "citepath-evaluation-runtime-v1", **owner.manifest,
                              "runtime_packages_sha256": digest(owner.manifest["installed_packages"]),
                              "qa_policy": QA_POLICY, "course_id": spec["course_id"],
                              "documents": [{"id": spec["documents"][0]["runtime_document_id"], "sha256": "c" * 64,
                                             "page_count": 3, "ingest_status": "complete", "is_active": True}]}
                    if owner.runtime_change:
                        owner.runtime_change(result, self.variant)
                    return result
                if path.endswith("/questions"):
                    if owner.fail_question == self.variant:
                        raise RuntimeError("raw secret-password-baseline provider URL must never be logged")
                    result = {"qa_id": 99, "course_id": spec["course_id"], "question": payload["question"],
                              "answer": "The first observed fact.\n\nA second observed statement.", "refused": False,
                              "cited_pages": [{"document_id": spec["documents"][0]["runtime_document_id"], "page_number": 1}],
                              "web_sources": []}
                    if owner.response_change:
                        owner.response_change(result, self.variant)
                    return result
                raise AssertionError("Unexpected fixture request")

        return Client()

    def collect(self, **changes):
        return collect_evidence(self.data, self.config, run=True, checkpoint_dir=self.directory / "checkpoints",
                                client_factory=self.factory, **changes)

    def question_requests(self):
        return [row for row in self.requests if row[1].endswith("/questions")]

    def test_default_is_dry_and_does_not_construct_client_or_write_checkpoint(self):
        result = collect_evidence(self.data, self.config, client_factory=self.factory)
        self.assertEqual(result["report"]["status"], "not_run")
        self.assertEqual(result["dataset"], self.data)
        self.assertEqual(self.client_count, 0)
        self.assertFalse((self.directory / "checkpoints").exists())

    def test_actual_response_is_preserved_with_mapped_candidate_claims_and_scoped_context(self):
        before = copy.deepcopy(self.data)
        result = self.collect()
        self.assertEqual(result["report"]["status"], "completed")
        self.assertEqual(result["report"]["completed_predictions"], 2)
        self.assertEqual(self.data, before)
        self.assertTrue(result["dataset"]["synthetic"])
        self.assertIsNone(evaluate(result["dataset"])["official_accepted"])
        for variant in ("baseline", "full"):
            prediction = result["dataset"]["items"][0]["predictions"][variant]
            self.assertEqual(prediction["answer"], "The first observed fact.\n\nA second observed statement.")
            self.assertEqual([claim["text"] for claim in prediction["claims"]], ["The first observed fact.", "A second observed statement."])
            self.assertEqual(prediction["claims"][0]["citations"], [{"document_id": "lecture2", "page_number": 1}])
            self.assertTrue(prediction["human_review_required"])
            self.assertNotIn("supported", prediction)
        self.assertEqual([row[2]["evaluation_context"]["system"] for row in self.question_requests()], ["baseline", "full"])
        exported = json.dumps({"report": result["report"], "journal": result["journal"]})
        for secret in self.secrets.values():
            self.assertNotIn(secret, exported)

    def test_completed_resume_is_immutable_and_makes_no_http_requests(self):
        first = self.collect()
        files = {path.name: path.read_bytes() for path in (self.directory / "checkpoints").iterdir()}
        self.requests.clear()
        second = self.collect()
        self.assertEqual(second["report"]["status"], "completed")
        self.assertEqual(second["report"]["resumed_predictions"], 2)
        self.assertEqual(first["dataset"], second["dataset"])
        self.assertEqual(self.requests, [])
        self.assertEqual(files, {path.name: path.read_bytes() for path in (self.directory / "checkpoints").iterdir()})

    def test_uncertain_post_is_never_automatically_replayed_and_raw_error_is_not_logged(self):
        self.fail_question = "full"
        first = self.collect()
        self.assertEqual(first["report"]["status"], "failed")
        self.assertEqual(first["report"]["completed_predictions"], 1)
        self.assertNotIn("secret-password", json.dumps(first))
        self.assertIsNotNone(first["dataset"]["items"][0]["predictions"]["baseline"])
        self.requests.clear()
        self.fail_question = None
        second = self.collect()
        self.assertEqual(second["report"]["failure"]["code"], "uncertain_request_requires_manual_reconciliation")
        self.assertEqual(self.requests, [])
        self.assertTrue(second["dataset"]["synthetic"])

    def test_changed_original_dataset_or_configuration_cannot_resume(self):
        self.collect()
        for target, key, value in ((self.data, "evaluation_id", "different-cohort"),
                                   (self.config["variants"]["full"], "course_id", 3)):
            original = target[key]
            target[key] = value
            self.requests.clear()
            result = self.collect()
            self.assertEqual(result["report"]["failure"]["code"], "checkpoint_dataset_or_configuration_mismatch")
            self.assertEqual(self.requests, [])
            target[key] = original

    def test_runtime_provider_model_source_or_endpoint_drift_stops_before_any_question(self):
        for field, value in (("provider", "deepseek"), ("model", "other"), ("base_url_sha256", "f" * 64),
                             ("source_sha256", {"agent/qa.py": "f" * 64})):
            with self.subTest(field=field):
                self.runtime_change = lambda response, variant: response.update({field: value})
                result = self.collect()
                self.assertEqual(result["report"]["failure"]["code"], "runtime_configuration_differs_from_freeze")
                self.assertEqual(self.question_requests(), [])

    def test_corpus_hash_readiness_extra_documents_or_missing_mapping_stop_before_questions(self):
        for change in (lambda response, variant: response["documents"][0].update(sha256="f" * 64),
                       lambda response, variant: response["documents"][0].update(is_active=False),
                       lambda response, variant: response["documents"][0].update(ingest_status="failed"),
                       lambda response, variant: response["documents"].append({"id": 123})):
            self.runtime_change = change
            result = self.collect()
            self.assertEqual(result["report"]["status"], "failed")
            self.assertEqual(self.question_requests(), [])
        self.runtime_change = None
        self.config["variants"]["baseline"]["documents"] = []
        result = self.collect()
        self.assertEqual(result["report"]["failure"]["code"], "complete_frozen_corpus_mapping_required")

    def test_invalid_citations_remain_invalid_and_web_sources_do_not_become_lecture_evidence(self):
        def change(response, variant):
            response["cited_pages"] = [{"document_id": 777, "page_number": 1},
                                        {"document_id": 11 if variant == "baseline" else 22, "page_number": 3}]
            response["web_sources"] = [{"url": "https://public.invalid"}]
        self.response_change = change
        result = self.collect()
        self.assertEqual(result["report"]["status"], "completed")
        prediction = result["dataset"]["items"][0]["predictions"]["full"]
        self.assertEqual(prediction["claims"][0]["citations"], [{"document_id": "unmapped-runtime-document-777", "page_number": 1},
                                                                {"document_id": "lecture2", "page_number": 3}])
        self.assertTrue(prediction["external_sources_returned"])

    def test_refusal_preserves_actual_flag_and_answer_and_requires_review(self):
        self.response_change = lambda response, variant: response.update(answer="The notes do not cover this.", refused=True, cited_pages=[])
        result = self.collect()
        prediction = result["dataset"]["items"][0]["predictions"]["full"]
        self.assertTrue(prediction["refused"])
        self.assertEqual(prediction["answer"], "The notes do not cover this.")
        self.assertEqual(prediction["claims"], [])
        self.assertTrue(prediction["refusal_text_requires_claim_review"])

    def test_missing_credentials_and_existing_predictions_never_request_an_answer(self):
        name = self.config["variants"]["baseline"]["password_env"]
        old = os.environ.pop(name)
        try:
            result = self.collect()
            self.assertEqual(result["report"]["status"], "blocked")
            self.assertEqual(self.requests, [])
        finally:
            os.environ[name] = old
        self.data["items"][0]["predictions"]["baseline"] = {"answer": "Saved", "refused": False, "claims": []}
        result = self.collect()
        self.assertEqual(result["report"]["failure"]["code"], "existing_predictions_cannot_be_overwritten")
        self.assertEqual(self.requests, [])

    def test_manifest_tampering_is_detected_before_clients_or_checkpoints(self):
        Path(self.config["manifest_path"]).write_text("{}", encoding="utf-8")
        result = self.collect()
        self.assertEqual(result["report"]["failure"]["code"], "frozen_manifest_hash_mismatch")
        self.assertEqual(self.client_count, 0)
        self.assertFalse((self.directory / "checkpoints").exists())

    def test_separate_url_aliases_cannot_reuse_one_conversation_course(self):
        self.config["variants"]["full"].update(course_id=1, api_url="http://localhost:8000")
        result = self.collect()
        self.assertEqual(result["report"]["failure"]["code"], "separate_variant_courses_required")
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
