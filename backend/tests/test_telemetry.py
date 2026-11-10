import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.telemetry import UsageLog


class UsageLogTest(unittest.TestCase):
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
