"""Feedback may be recovered without changing any already saved grade."""
import copy
import json
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext, contextmanager
from unittest.mock import MagicMock, patch

from agent import exam, practice
from db import feedback


SOURCES = [{"document_id": 6, "page_number": 12}]
QUESTION = {"id": 7, "answer_id": 21, "kind": "short", "concept_name": "Trees",
            "prompt": "Explain trees.", "answer": "A rooted connected structure.",
            "rubric_json": ["One", "Two", "Three", "Four", "Five"],
            "sources_json": SOURCES, "response": "partial response", "correct": False,
            "explanation": "", "explanation_status": "failed", "explanation_attempts": 1}


class FeedbackGradeIsolationTest(unittest.TestCase):
    def test_practice_grade_is_saved_before_a_failed_explanation(self):
        events = []
        with patch.object(practice, "_grade_shorts", return_value={7: [0, 1, 2]}) as grade, \
                patch.object(practice, "save_answer", side_effect=lambda *args: events.append(("grade", args))) as save, \
                patch.object(practice, "begin_explanation_attempt", side_effect=lambda *args: events.append(("begin", args))), \
                patch.object(practice, "_explain", side_effect=TimeoutError("private provider error")), \
                patch.object(practice, "complete_explanation_attempt", side_effect=lambda *args: events.append(("complete", args))):
            practice._grade_and_store(1, {"id": 9, "course_id": 2}, QUESTION, "partial response")
        grade.assert_called_once()
        save.assert_called_once_with(7, "partial response", False, 3, 5, "", [0, 1, 2])
        self.assertEqual([event[0] for event in events], ["grade", "begin", "complete"])
        self.assertEqual(events[-1][1], ("practice", 9, 7, None))

    def test_correct_practice_answer_never_requests_remedial_feedback(self):
        with patch.object(practice, "_grade_shorts", return_value={7: [0, 1, 2, 3]}), \
                patch.object(practice, "save_answer") as save, \
                patch.object(practice, "_attempt_practice_explanation") as explanation:
            practice._grade_and_store(1, {"id": 9}, QUESTION, "good answer")
        self.assertTrue(save.call_args.args[2])
        explanation.assert_not_called()

    def test_exam_official_result_is_finished_before_feedback_and_partial_failure_is_retriable(self):
        source = {"status": "open", "questions": [QUESTION]}
        result = {"status": "finished", "score": 0, "passed": False}
        events = []
        with patch.object(exam, "exam_lock", side_effect=lambda *args: nullcontext()), \
                patch("db.exams.get_owned_exam", return_value=source), \
                patch.object(exam, "_save_drafts"), \
                patch.object(exam, "_exam_case_answers", return_value=""), \
                patch.object(exam, "_grade_shorts", return_value={7: []}) as grader, \
                patch.object(exam, "finish_exam", side_effect=lambda *args: events.append("finished") or result), \
                patch.object(exam, "begin_explanation_attempt", side_effect=lambda *args: events.append("feedback began")), \
                patch.object(exam, "_explain", side_effect=TimeoutError("private secret")), \
                patch.object(exam, "complete_explanation_attempt") as complete, \
                patch.object(exam, "open_exam", return_value=result):
            actual = exam.submit_exam(1, 2, 3, [{"question_id": 7, "response": "wrong"}])
        self.assertEqual(actual, result)
        self.assertEqual(events, ["finished", "feedback began"])
        complete.assert_called_once_with("exam", 3, 7, None)
        grader.assert_called_once()


class FeedbackRetryTest(unittest.TestCase):
    def test_simultaneous_retry_requests_invoke_the_explanation_model_once(self):
        question = copy.deepcopy(QUESTION)
        mutex = threading.Lock()
        model_started, model_finished = threading.Event(), threading.Event()

        @contextmanager
        def lock(*args):
            with mutex:
                yield

        def recover(*args):
            model_started.set()
            self.assertTrue(model_finished.wait(5))
            question.update(explanation="The cited source is page 12.", explanation_status="ready")

        with patch.object(practice, "get_owned_session", return_value={"id": 9, "chapter_id": 3}), \
                patch.object(practice, "practice_lock", lock), \
                patch.object(practice, "explanation_question", side_effect=lambda *args: copy.deepcopy(question)), \
                patch.object(practice, "load_chapter", return_value={"concepts": []}), \
                patch.object(practice, "present_session", return_value={"status": "finished", "round_number": 2}), \
                patch.object(practice, "_attempt_practice_explanation", side_effect=recover) as model:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(practice.retry_practice_explanation, 1, 2, 9, 7)
                self.assertTrue(model_started.wait(5))
                second = pool.submit(practice.retry_practice_explanation, 1, 2, 9, 7)
                model_finished.set()
                self.assertEqual(first.result(timeout=5), second.result(timeout=5))
        model.assert_called_once()

    def practice_retry(self, question):
        self.session = {"id": 9, "chapter_id": 3, "status": "finished"}
        self.snapshot = {"id": 9, "status": "finished", "round_results": [{"round_number": 2, "score": 60, "passed": False}]}
        return (
            patch.object(practice, "get_owned_session", return_value=self.session),
            patch.object(practice, "practice_lock", side_effect=lambda *args: nullcontext()),
            patch.object(practice, "explanation_question", return_value=question),
            patch.object(practice, "load_chapter", return_value={"concepts": []}),
            patch.object(practice, "present_session", return_value=self.snapshot),
        )

    def test_finished_practice_retry_does_not_grade_generate_or_advance_round(self):
        contexts = self.practice_retry(copy.deepcopy(QUESTION))
        with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4], \
                patch.object(practice, "_attempt_practice_explanation") as retry, \
                patch.object(practice, "_grade_shorts") as grade, \
                patch.object(practice, "save_answer") as score, \
                patch.object(practice, "_ensure_question") as generate:
            result = practice.retry_practice_explanation(1, 2, 9, 7)
        retry.assert_called_once_with(9, QUESTION, QUESTION["response"])
        self.assertEqual(result, self.snapshot)
        grade.assert_not_called()
        score.assert_not_called()
        generate.assert_not_called()

    def test_ready_or_correct_feedback_retries_are_idempotent_without_a_model_call(self):
        for changes in ({"explanation_status": "ready", "explanation": "See page 12."}, {"correct": True}):
            with self.subTest(changes=changes):
                question = {**QUESTION, **changes}
                contexts = self.practice_retry(question)
                with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4], \
                        patch.object(practice, "_attempt_practice_explanation") as retry:
                    practice.retry_practice_explanation(1, 2, 9, 7)
                retry.assert_not_called()

    def test_unowned_session_is_rejected_before_model_and_missing_or_unsubmitted_question_is_rejected(self):
        with patch.object(practice, "get_owned_session", side_effect=LookupError("not owned")), \
                patch.object(practice, "_attempt_practice_explanation") as retry:
            with self.assertRaises(LookupError):
                practice.retry_practice_explanation(1, 2, 9, 7)
            retry.assert_not_called()
        for question, error in ((None, LookupError), ({**QUESTION, "answer_id": None}, ValueError)):
            contexts = self.practice_retry(question)
            with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4], \
                    patch.object(practice, "_attempt_practice_explanation") as retry:
                with self.assertRaises(error):
                    practice.retry_practice_explanation(1, 2, 9, 7)
                retry.assert_not_called()

    def test_exam_retry_uses_saved_response_and_skips_finished_success_on_repeat(self):
        question = copy.deepcopy(QUESTION)
        source = {"status": "finished", "questions": [question]}
        def recovered(*args):
            question.update(explanation="The cited fact is on page 12.", explanation_status="ready")
        with patch.object(exam, "exam_lock", side_effect=lambda *args: nullcontext()), \
                patch("db.exams.get_owned_exam", return_value=source), \
                patch.object(exam, "public_exam", return_value={"score": 0, "passed": False}), \
                patch.object(exam, "_attempt_exam_explanations", side_effect=recovered) as retry, \
                patch.object(exam, "_grade_shorts") as grade, patch.object(exam, "finish_exam") as save:
            first = exam.retry_exam_explanation(1, 2, 3, 7)
            second = exam.retry_exam_explanation(1, 2, 3, 7)
        self.assertEqual(first, second)
        self.assertEqual(retry.call_count, 1)
        grade.assert_not_called()
        save.assert_not_called()


class ExplanationValidationTest(unittest.TestCase):
    def test_missing_source_body_blocks_the_model_instead_of_inventing_feedback(self):
        with patch.object(exam, "_page_bodies", return_value={}), patch.object(exam, "_ask") as model:
            with self.assertRaisesRegex(RuntimeError, "source pages"):
                exam._explain([QUESTION], [{"question_id": 7, "response": "wrong"}])
            model.assert_not_called()

    def test_incomplete_or_unexpected_model_ids_remain_missing_not_placeholder_success(self):
        wrong = [{"question_id": 7, "response": "wrong"}]
        for reply in (None, {}, {"explanations": []}, {"explanations": [{"id": 8, "explanation": "bad"}]},
                      {"explanations": [{"id": 7, "explanation": ""}]},
                      {"explanations": [{"id": 7, "explanation": "fact"}, {"id": 7, "explanation": "duplicate"}]}):
            with self.subTest(reply=reply), patch.object(exam, "_page_bodies", return_value={(6, 12): "A tree has a root."}), \
                    patch.object(exam, "_ask", return_value=reply):
                self.assertEqual(exam._explain([QUESTION], wrong), {})

    def test_only_requested_wrong_answers_are_explained(self):
        with patch.object(exam, "_page_bodies", return_value={(6, 12): "A tree has a root."}), \
                patch.object(exam, "_ask", return_value={"explanations": [{"id": 7, "explanation": "A tree has a root (page 12)."}]}):
            actual = exam._explain([QUESTION, {**QUESTION, "id": 8}], [{"question_id": 7, "response": "wrong"}])
        self.assertEqual(actual, {7: "A tree has a root (page 12)."})


class FeedbackStorageTest(unittest.TestCase):
    def test_placeholder_is_pending_and_old_real_explanation_is_ready(self):
        self.assertEqual(feedback.feedback_fields({"correct": False, "explanation": feedback.PLACEHOLDER})["explanation_status"], "pending")
        self.assertEqual(feedback.feedback_fields({"correct": False, "explanation": "A cited fact."})["explanation_status"], "ready")
        self.assertEqual(feedback.feedback_fields({"correct": True})["explanation_status"], "not_required")

    def test_report_feedback_update_cannot_change_grades_rounds_outcome_or_timestamps(self):
        original = {"outcome": "failed_after_2", "passed": False, "rounds": [{"round_number": 1, "score": 50, "passed": False},
                    {"round_number": 2, "score": 60, "passed": False}], "finished_at": "2026-11-11 10:00:00",
                    "question_count": 8, "correct_count": 4, "wrong": [{"question_id": 7, "correct": False, "concept_name": "Trees"}],
                    "questions": [{"question_id": 7, "correct": False, "response": "wrong", "points_hit": 1}]}
        before = copy.deepcopy(original)
        result = feedback.with_feedback(original, 7, {"explanation": "Fact on page 12.", "explanation_status": "ready",
                            "explanation_attempts": 2, "correct": True, "points_hit": 5, "response": "changed"})
        self.assertEqual(original, before)
        for key in ("outcome", "passed", "rounds", "finished_at", "question_count", "correct_count"):
            self.assertEqual(result[key], before[key])
        self.assertFalse(result["questions"][0]["correct"])
        self.assertEqual(result["questions"][0]["response"], "wrong")
        self.assertEqual(result["questions"][0]["points_hit"], 1)
        self.assertEqual(result["wrong"][0]["explanation_status"], "ready")

    def test_storage_rejects_mismatched_container_before_updating_the_answer(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None
        with patch.object(feedback, "connect", return_value=connection):
            with self.assertRaises(LookupError):
                feedback.complete_explanation_attempt("practice", 9, 7, "fact")
        self.assertFalse(any(call.args[0].lstrip().startswith("UPDATE") for call in cursor.execute.call_args_list))
        connection.rollback.assert_called_once()

    def test_begin_attempt_persists_pending_report_and_attempt_counter_for_interruption(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        report = {"outcome": "failed_after_2", "rounds": [{"round_number": 2, "score": 0}],
                  "wrong": [{"question_id": 7, "concept_name": "Trees", "explanation_status": "failed", "explanation_attempts": 1}]}
        cursor.fetchone.side_effect = [{**QUESTION, "container_id": 9}, {"report_json": json.dumps(report)}]
        with patch.object(feedback, "connect", return_value=connection):
            feedback.begin_explanation_attempt("practice", 7)
        saved = json.loads(cursor.execute.call_args_list[-1].args[1][0])
        self.assertEqual(saved["wrong"][0]["explanation_status"], "pending")
        self.assertEqual(saved["wrong"][0]["explanation_attempts"], 2)
        self.assertEqual(saved["rounds"], report["rounds"])
        connection.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
