import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import main
from evaluation.core import digest
from evaluation.runtime import load_frozen_manifest, verify_observed_runtime, verify_runtime
from tests.test_evaluation import sample_data


class RuntimeContractTest(unittest.TestCase):
    def setUp(self):
        self.user = {"id": 11, "username": "citepath_eval_reviewer"}
        main.app.dependency_overrides[main.current_user] = lambda: self.user
        self.addCleanup(main.app.dependency_overrides.clear)
        self.client = TestClient(main.app)

    def test_runtime_attestation_is_owned_and_has_no_model_key(self):
        row = {"id": 42, "sha256": "a" * 64, "page_count": 7, "active": True, "ingest_status": "complete"}
        summary = {"schema": "citepath-evaluation-runtime-v1", "model": "test-model", "source_sha256": {"main.py": "a" * 64}}
        with patch("main.document_inventory", return_value={"documents": [row, {**row, "id": 43, "active": False}]}) as inventory, \
                patch("evaluation.runtime.runtime_summary", return_value=summary), \
                patch("agent.llm.chat_model") as model:
            response = self.client.get("/api/courses/3/evaluation/runtime")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["documents"], [{"id": 42, "sha256": "a" * 64, "page_count": 7, "is_active": True, "ingest_status": "complete"}])
        inventory.assert_called_once_with(11, 3)
        model.assert_not_called()
        with patch("main.document_inventory", side_effect=LookupError("foreign owner")):
            self.assertEqual(self.client.get("/api/courses/3/evaluation/runtime").status_code, 404)

    def test_qa_evaluation_scope_is_validated_and_restricted_to_test_accounts(self):
        payload = {"question": "What is hashing?", "evaluation_context": {
            "evaluation_id": "evaluation-1", "system": "baseline", "item_id": "EV-01"}}
        with patch("main.answer_question", return_value={"answer": "Observed"}), patch("main.usage_context") as context:
            response = self.client.post("/api/courses/3/questions", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(context.call_args.kwargs["item_id"], "EV-01")
        self.user["username"] = "ordinary-user"
        with patch("main.answer_question") as answer:
            self.assertEqual(self.client.post("/api/courses/3/questions", json=payload).status_code, 403)
            answer.assert_not_called()
        payload["evaluation_context"]["system"] = "unscoped"
        self.assertEqual(self.client.post("/api/courses/3/questions", json=payload).status_code, 422)

    def test_runtime_refuses_source_drift_after_api_start(self):
        with patch("main.document_inventory", return_value={"documents": []}), \
                patch("evaluation.runtime.runtime_summary", return_value={"source_sha256": {"main.py": "new"}}), \
                patch.object(main.app.state, "runtime_identity", {"source_sha256": {"main.py": "loaded"}}, create=True):
            response = self.client.get("/api/courses/3/evaluation/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("loaded", response.text)

    def test_archive_keeps_original_and_inventory_restore_enforce_ownership(self):
        with patch("main.owns_document", return_value=True), patch("main.delete_document_rows", return_value={"ok": True, "document_id": 42, "archived": True}), \
                patch("main.delete_original_pdf") as original, patch("main.delete_segments") as vectors:
            response = self.client.delete("/api/courses/3/documents/42")
        self.assertTrue(response.json()["archived"])
        original.assert_not_called()
        vectors.assert_not_called()
        with patch("main.restore_document", side_effect=LookupError("foreign owner")) as restore:
            self.assertEqual(self.client.post("/api/courses/3/documents/42/restore").status_code, 404)
            restore.assert_called_once_with(11, 3, 42)
        with patch("main.restore_document", side_effect=RuntimeError("Indexing failed; restore again")):
            self.assertEqual(self.client.post("/api/courses/3/documents/42/restore").status_code, 502)


class FrozenRuntimeTest(unittest.TestCase):
    def test_manifest_byte_identity_and_observed_package_source_drift(self):
        data = sample_data()
        manifest = {"working_tree_dirty": False, "created_at": data["freeze"]["created_at"],
            "git_commit": data["freeze"]["git_commit"], "provider": "hku", "model": "test-model",
            "base_url_sha256": "c" * 64, "source_sha256": {"main.py": "d" * 64},
            "installed_packages": {"package": "1.0"}, "python": "3.12.0"}
        data["freeze"].update(provider="hku", base_url_sha256="c" * 64)
        for item in data["items"]:
            item["predictions"] = {"baseline": None, "full": None}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            data["freeze"]["manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(load_frozen_manifest(data, path), manifest)
            observed = {"schema": "citepath-evaluation-runtime-v1", **manifest,
                        "runtime_packages_sha256": digest(manifest["installed_packages"])}
            self.assertEqual(verify_observed_runtime(data, manifest, observed)["model"], "test-model")
            for field in ("source_sha256", "model", "base_url_sha256", "runtime_packages_sha256", "python"):
                changed = copy.deepcopy(observed)
                changed[field] = "drift"
                with self.subTest(field=field), self.assertRaises(ValueError):
                    verify_observed_runtime(data, manifest, changed)
            path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest identity"):
                load_frozen_manifest(data, path)


if __name__ == "__main__":
    unittest.main()
