import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.telemetry import UsageLog, usage_context


class UsageLogTest(unittest.TestCase):
    def test_business_context_is_captured_at_start_and_error_is_redacted(self):
        with tempfile.TemporaryDirectory() as temp:
            model_path, op_path = Path(temp) / "models.jsonl", Path(temp) / "operations.jsonl"
            with patch.dict(os.environ, {"MODEL_USAGE_LOG": str(model_path), "OPERATION_LOG": str(op_path)}):
                log = UsageLog("model")
                with self.assertRaises(TimeoutError):
                    with usage_context(operation="practice.grade", session_id=8, question_id=3,
                                       api_key="secret", response="private answer"):
                        log.on_chat_model_start({}, [], run_id="run")
                        raise TimeoutError("private API secret")
                # Some callback implementations finish after the surrounding context exits.
                log.on_llm_error(TimeoutError("private API secret"), run_id="run")
            model, operation = json.loads(model_path.read_text()), json.loads(op_path.read_text())
            self.assertEqual(model["context"]["session_id"], 8)
            self.assertEqual(model["context"]["question_id"], 3)
            self.assertEqual(model["context"]["operation_id"], operation["context"]["operation_id"])
            self.assertEqual(operation["status"], "error")
            self.assertNotIn("private", model_path.read_text() + op_path.read_text())
            self.assertNotIn("secret", model_path.read_text() + op_path.read_text())

    def test_records_usage_and_configured_cost_without_prompt_content(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "usage.jsonl"
            with patch.dict(os.environ, {"MODEL_USAGE_LOG": str(path),
                                        "MODEL_INPUT_COST_PER_MILLION": "1",
                                        "MODEL_OUTPUT_COST_PER_MILLION": "2",
                                        "MODEL_COST_CURRENCY": "USD"}):
                log = UsageLog("test-model")
                log.on_chat_model_start({}, [["private prompt"]], run_id="one")
                log.on_llm_end(SimpleNamespace(llm_output={"token_usage": {
                    "prompt_tokens": 1000, "completion_tokens": 500}}, generations=[]), run_id="one")
                log.on_chat_model_start({}, [], run_id="two")
                log.on_llm_error(TimeoutError("secret key"), run_id="two")
            raw = path.read_text()
            records = [json.loads(line) for line in raw.splitlines()]
            self.assertEqual(records[0]["estimated_cost"], 0.002)
            self.assertEqual(records[0]["model_calls"], 1)
            self.assertGreaterEqual(records[0]["latency_ms"], 0)
            self.assertEqual(records[1]["error_type"], "TimeoutError")
            self.assertIsNone(records[1]["estimated_cost"])
            self.assertNotIn("private prompt", raw)
            self.assertNotIn("secret key", raw)


if __name__ == "__main__":
    unittest.main()
