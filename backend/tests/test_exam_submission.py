"""Submission serialization protects saved answers and the official result."""
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import patch

from agent.exam import submit_exam


class ExamSubmissionTest(unittest.TestCase):
    def test_overlapping_submissions_reuse_first_official_result_without_regrading(self):
        lock = threading.Lock()
        model_started = threading.Event()
        finish_model = threading.Event()
        exam = {"status": "open", "questions": [
            {"id": 7, "kind": "short", "rubric_json": '["a", "b", "c"]'},
        ]}
        result = {"status": "finished", "score": 100, "passed": True}
        answers = [{"question_id": 7, "response": "first answer"}]

        @contextmanager
        def serialized(*_):
            with lock:
                yield

        def grade(*_):
            model_started.set()
            if not finish_model.wait(5):
                raise TimeoutError("Test did not release model")
            return {7: [0, 1, 2]}

        def finish(*_):
            exam["status"] = "finished"
            return result

        with patch("agent.exam.exam_lock", serialized), \
                patch("db.exams.get_owned_exam", return_value=exam), \
                patch("agent.exam._save_drafts") as drafts, \
                patch("agent.exam._grade_shorts", side_effect=grade) as model, \
                patch("agent.exam._explain", return_value={}), \
                patch("agent.exam._report", return_value=result), \
                patch("agent.exam.finish_exam", side_effect=finish) as publish, \
                patch("agent.exam.public_exam", return_value=result):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(submit_exam, 1, 2, 3, answers)
                self.assertTrue(model_started.wait(5))
                second = pool.submit(submit_exam, 1, 2, 3, [{"question_id": 7, "response": "different answer"}])
                finish_model.set()
                self.assertEqual(first.result(timeout=5), result)
                self.assertEqual(second.result(timeout=5), result)
            model.assert_called_once()
            publish.assert_called_once()
            drafts.assert_called_once_with(1, 2, 3, answers)


if __name__ == "__main__":
    unittest.main()
