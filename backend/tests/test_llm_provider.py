"""Provider switching keeps telemetry and frozen evaluation identity consistent."""
import copy
import hashlib
import json
import os
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from agent import llm
from agent.telemetry import UsageLog
from evaluation.live import collect_grading, preflight_report
from freeze_evaluation import manifest


SETTINGS = {
    "LLM_PROVIDER": "hku", "HKU_API_KEY": "", "HKU_DEPLOYMENT": "", "HKU_API_VERSION": "",
    "DEEPSEEK_API_KEY": "", "DEEPSEEK_MODEL": "", "DEEPSEEK_BASE_URL": "",
}


class ProviderSwitchTest(unittest.TestCase):
    def setUp(self):
        self.settings = patch.dict(os.environ, SETTINGS)
        self.settings.start()
        self.addCleanup(self.settings.stop)

    def test_hku_constructor_preserves_headers_defaults_and_usage_callback(self):
        with patch.dict(os.environ, {"HKU_API_KEY": "unit-test-hku-key"}), \
                patch.object(llm, "AzureChatOpenAI") as azure, patch.object(llm, "ChatOpenAI") as other:
            result = llm.chat_model()
        self.assertIs(result, azure.return_value)
        other.assert_not_called()
        args = azure.call_args.kwargs
        self.assertEqual(args["model"], llm.DEFAULT_DEPLOYMENT)
        self.assertEqual(args["timeout"], 60)
        self.assertEqual(args["max_retries"], 1)
        self.assertEqual(args["default_headers"]["api-key"], "unit-test-hku-key")
        self.assertEqual(args["default_headers"]["Ocp-Apim-Subscription-Key"], "unit-test-hku-key")
        self.assertEqual(len(args["callbacks"]), 1)
        self.assertIsInstance(args["callbacks"][0], UsageLog)
        self.assertEqual(args["callbacks"][0].model, llm.DEFAULT_DEPLOYMENT)

    def test_deepseek_constructor_requires_only_its_key_and_keeps_tool_call_options(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "  DEEPSEEK  ", "DEEPSEEK_API_KEY": "unit-test-deepseek-key",
                                     "DEEPSEEK_MODEL": "custom-model", "DEEPSEEK_BASE_URL": "https://provider.invalid/v1///"}), \
                patch.object(llm, "ChatOpenAI") as client, patch.object(llm, "AzureChatOpenAI") as inactive:
            result = llm.chat_model()
        self.assertIs(result, client.return_value)
        inactive.assert_not_called()
        args = client.call_args.kwargs
        self.assertEqual(args["model"], "custom-model")
        self.assertEqual(args["base_url"], "https://provider.invalid/v1")
        self.assertEqual(args["timeout"], 120)
        self.assertEqual(args["temperature"], 0)
        self.assertEqual(args["max_retries"], 1)
        self.assertIs(args["use_responses_api"], False)
        self.assertEqual(args["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertEqual(len(args["callbacks"]), 1)
        self.assertIsInstance(args["callbacks"][0], UsageLog)
        self.assertEqual(args["callbacks"][0].model, "custom-model")

    def test_inactive_provider_key_cannot_satisfy_selected_provider(self):
        for settings, missing in (({"LLM_PROVIDER": "deepseek", "HKU_API_KEY": "unused"}, "DEEPSEEK_API_KEY"),
                                  ({"LLM_PROVIDER": "hku", "DEEPSEEK_API_KEY": "unused"}, "HKU_API_KEY")):
            with self.subTest(provider=settings["LLM_PROVIDER"]), patch.dict(os.environ, settings), \
                    patch.object(llm, "ChatOpenAI") as chat, patch.object(llm, "AzureChatOpenAI") as azure:
                with self.assertRaisesRegex(RuntimeError, missing):
                    llm.chat_model()
                chat.assert_not_called()
                azure.assert_not_called()

    def test_invalid_provider_is_rejected_without_constructing_any_client(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "unknown"}), \
                patch.object(llm, "ChatOpenAI") as chat, patch.object(llm, "AzureChatOpenAI") as azure:
            with self.assertRaisesRegex(RuntimeError, "Unsupported LLM_PROVIDER"):
                llm.chat_model()
            chat.assert_not_called()
            azure.assert_not_called()

    def test_configuration_uses_defaults_for_blank_settings_without_network_or_secret_export(self):
        secret_url = "https://private-user:private-password@provider.invalid/v1?token=private-query-token"
        values = {**SETTINGS, "LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "private-api-secret",
                  "DEEPSEEK_BASE_URL": secret_url, "DEEPSEEK_MODEL": " "}
        with patch.object(llm, "ChatOpenAI") as chat, patch.object(llm, "AzureChatOpenAI") as azure:
            result = llm.model_configuration(values)
        serialized = json.dumps(result)
        self.assertEqual(result["model"], llm.DEFAULT_DEEPSEEK_MODEL)
        self.assertEqual(result["api_version"], None)
        self.assertEqual(result["timeout"], 120)
        self.assertEqual(result["key_name"], "DEEPSEEK_API_KEY")
        self.assertTrue(result["key_configured"])
        self.assertEqual(result["base_url_sha256"], hashlib.sha256(secret_url.encode()).hexdigest())
        for secret in ("private-user", "private-password", "private-query-token", "private-api-secret"):
            self.assertNotIn(secret, serialized)
        chat.assert_not_called()
        azure.assert_not_called()

    def test_freeze_records_selected_model_timeout_and_endpoint_fingerprint(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "private-api-secret",
                                     "DEEPSEEK_MODEL": "custom-model",
                                     "DEEPSEEK_BASE_URL": "https://private-user:private-password@provider.invalid/v1?token=private-query-token"}), \
                patch.object(llm, "ChatOpenAI") as chat, patch.object(llm, "AzureChatOpenAI") as azure:
            result = manifest()
            configuration = llm.model_configuration()
        self.assertEqual(result["provider"], "deepseek")
        self.assertEqual(result["model"], "custom-model")
        self.assertEqual(result["deployment"], "custom-model")
        self.assertEqual(result["model_timeout_seconds"], 120)
        self.assertEqual(result["api_version"], None)
        self.assertEqual(result["base_url_sha256"], configuration["base_url_sha256"])
        for secret in ("private-api-secret", "private-user", "private-password", "private-query-token"):
            self.assertNotIn(secret, json.dumps(result))
        chat.assert_not_called()
        azure.assert_not_called()

    def test_preflight_accepts_selected_deepseek_key_without_invoking_a_model(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "private-api-secret"}), \
                patch("evaluation.live.socket.create_connection", side_effect=OSError), \
                patch("evaluation.live.runtime_imports", return_value=({}, "completed")), \
                patch("evaluation.live.api_health", return_value=False), \
                patch.object(llm, "ChatOpenAI") as chat, patch.object(llm, "AzureChatOpenAI") as azure:
            result = preflight_report()
        model_check = next(row for row in result["checks"] if row["name"] == "model_configuration")
        self.assertTrue(model_check["ready"])
        self.assertEqual(result["model_configuration"]["key_name"], "DEEPSEEK_API_KEY")
        self.assertFalse(result["model_invoked"])
        self.assertNotIn("private-api-secret", json.dumps(result))
        chat.assert_not_called()
        azure.assert_not_called()

    def test_preflight_unknown_provider_is_a_safe_blocked_result(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "unsupported-private-value"}), \
                patch("evaluation.live.socket.create_connection", side_effect=OSError), \
                patch("evaluation.live.runtime_imports", return_value=({}, "completed")), \
                patch("evaluation.live.api_health", return_value=False):
            result = preflight_report()
        model_check = next(row for row in result["checks"] if row["name"] == "model_configuration")
        self.assertFalse(model_check["ready"])
        self.assertEqual(result["status"], "blocked")
        self.assertNotIn("unsupported-private-value", json.dumps(result))


class ProviderCollectionTest(unittest.TestCase):
    def setUp(self):
        self.settings = patch.dict(os.environ, {**SETTINGS, "LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "unit-test-key",
                                              "DEEPSEEK_MODEL": "custom-model"})
        self.settings.start()
        self.addCleanup(self.settings.stop)

    def dataset(self):
        configuration = llm.model_configuration()
        return {
            "schema": "citepath-evaluation-v1", "evaluation_id": "provider-collection-test",
            "split": "development", "synthetic": True,
            "freeze": {"manifest_sha256": "a" * 64, "git_commit": "b" * 40,
                       "created_at": "2020-01-01T00:00:00+00:00", "model": configuration["model"],
                       "provider": configuration["provider"], "base_url_sha256": configuration["base_url_sha256"]},
            "documents": [{"id": "lecture2", "lecture": 2, "sha256": "c" * 64, "page_count": 5}],
            "items": [
                {"id": "m", "kind": "mcq", "lecture": 2, "question": "Choose one.", "response": "B", "answer_key": "B",
                 "options": ["First option", "Second option", "Third option", "Fourth option"],
                 "sources": [{"document_id": "lecture2", "page_number": 1}], "predictions": {"baseline": None, "full": None}},
                {"id": "s", "kind": "short", "lecture": 2, "question": "Explain the structure.", "response": "Four facts.",
                 "rubric": ["One", "Two", "Three", "Four", "Five"], "sources": [{"document_id": "lecture2", "page_number": 1}],
                 "predictions": {"baseline": None, "full": None}},
            ],
        }

    def test_collection_reuses_actual_grader_result_for_both_variants_with_selected_identity(self):
        data = self.dataset()
        original = copy.deepcopy(data)
        with patch.object(llm, "chat_model", return_value=SimpleNamespace(model_name="custom-model")), \
                patch("agent.exam._grade_shorts", return_value={2: [0, 1, 2, 3]}) as grade, \
                patch("agent.telemetry.usage_context", side_effect=lambda **kwargs: nullcontext()):
            result = collect_grading(data)
        self.assertEqual(data, original)
        grade.assert_called_once()
        for item in result["items"]:
            self.assertEqual(item["predictions"]["baseline"], item["predictions"]["full"])
            self.assertTrue(item["predictions"]["full"]["correct"])
            self.assertEqual(item["predictions"]["full"]["provider"], "deepseek")
            self.assertEqual(item["predictions"]["full"]["base_url_sha256"], data["freeze"]["base_url_sha256"])

    def test_collection_rejects_provider_or_endpoint_drift_before_grading(self):
        for change in ({"provider": "hku"}, {"base_url_sha256": "f" * 64}, {"base_url_sha256": None}):
            data = self.dataset()
            data["freeze"].update(change)
            with self.subTest(change=change), \
                    patch.object(llm, "chat_model", return_value=SimpleNamespace(model_name="custom-model")), \
                    patch("agent.exam._grade_shorts") as grade:
                with self.assertRaises(ValueError):
                    collect_grading(data)
                grade.assert_not_called()


if __name__ == "__main__":
    unittest.main()
