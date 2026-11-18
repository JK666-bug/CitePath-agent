import unittest
from contextlib import nullcontext
from unittest.mock import patch

from agent.exam import _grade_shorts, submit_exam
from grading.score import choice_correct, exam_pass, percent, points_pass


class ScoreBoundaryTest(unittest.TestCase):
    def test_choice_matches_the_whole_selected_option(self):
        for expected in "ABCD":
            for given in "ABCD":
                self.assertEqual(choice_correct(given.lower(), expected), given == expected)
        for invalid in ("Apple", "A and B", "AB", "", "1"):
            self.assertFalse(choice_correct(invalid, "A"))

    def test_short_answer_exact_boundary(self):
        self.assertTrue(points_pass(4, 5))
        self.assertFalse(points_pass(3, 5))
        self.assertFalse(points_pass(79, 100))

    def test_chapter_thresholds_below_equal_and_above(self):
        for threshold in (0.7, 0.8, 0.9):
            boundary = int(threshold * 100)
            with self.subTest(threshold=threshold):
                self.assertFalse(exam_pass(boundary - 1, 100, threshold))
                self.assertTrue(exam_pass(boundary, 100, threshold))
                self.assertTrue(exam_pass(boundary + 1, 100, threshold))
        self.assertEqual(percent(159, 200), 80)
        self.assertFalse(exam_pass(159, 200))

    def test_invalid_counts_and_thresholds_cannot_produce_a_score(self):
        for args in ((0, 0), (1, 0), (-1, 5), (6, 5), (True, 5)):
            for function in (points_pass, exam_pass, percent):
                with self.subTest(args=args, function=function):
                    with self.assertRaises(ValueError):
                        function(*args)
        for threshold in (0, -0.1, 1.1, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                exam_pass(4, 5, threshold)


class ModelGradeValidationTest(unittest.TestCase):
    def setUp(self):
        self.short = [({"id": 7}, "student answer", ["a", "b", "c", "d", "e"])]
        lock = patch("agent.exam.exam_lock", side_effect=lambda *_: nullcontext())
        lock.start()
        self.addCleanup(lock.stop)

    def test_explicit_empty_hits_is_a_valid_failed_answer(self):
        with patch("agent.exam._ask", return_value={"grades": [{"id": 7, "hits": []}]}):
            self.assertEqual(_grade_shorts(self.short), {7: []})

    def test_complete_hits(self):
        with patch("agent.exam._ask", return_value={"grades": [{"id": 7, "hits": [0, 1, 2, 3]}]}):
            self.assertEqual(_grade_shorts(self.short), {7: [0, 1, 2, 3]})

    def test_incomplete_or_invalid_model_results_are_not_incorrect_answers(self):
        invalid = [None, {}, {"grades": []}, {"grades": "bad"},
                   {"grades": [{"id": 7}]}, {"grades": [{"id": "7", "hits": []}]},
                   {"grades": [{"id": 7, "hits": [True]}]},
                   {"grades": [{"id": 7, "hits": [5]}]},
                   {"grades": [{"id": 7, "hits": [0, 0]}]},
                   {"grades": [{"id": 8, "hits": []}]},
                   {"grades": [{"id": 7, "hits": []}, {"id": 7, "hits": []}]}]
        for reply in invalid:
            with self.subTest(reply=reply), patch("agent.exam._ask", return_value=reply):
                with self.assertRaises(RuntimeError):
                    _grade_shorts(self.short)

    def test_missing_rubric_does_not_call_model(self):
        with patch("agent.exam._ask") as ask:
            with self.assertRaises(ValueError):
                _grade_shorts([({"id": 7}, "answer", [])])
            ask.assert_not_called()

    def test_failure_preserves_draft_and_does_not_publish_official_score(self):
        exam = {"status": "open", "questions": [{"id": 7, "kind": "short", "rubric_json": '["a", "b", "c"]'}]}
        answers = [{"question_id": 7, "response": "answer"}]
        with patch("db.exams.get_owned_exam", return_value=exam), \
                patch("agent.exam._save_drafts") as drafts, \
                patch("agent.exam._exam_case_answers", return_value=""), \
                patch("agent.exam._ask", return_value=None), \
                patch("agent.exam.finish_exam") as finish:
            with self.assertRaises(RuntimeError):
                submit_exam(1, 2, 3, answers)
            drafts.assert_called_once_with(1, 2, 3, answers)
            finish.assert_not_called()

    def test_empty_exam_is_rejected_before_model_or_score(self):
        with patch("db.exams.get_owned_exam", return_value={"status": "open", "questions": []}), \
                patch("agent.exam._ask") as ask, patch("agent.exam.finish_exam") as finish:
            with self.assertRaises(ValueError):
                submit_exam(1, 2, 3, [])
            ask.assert_not_called()
            finish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
