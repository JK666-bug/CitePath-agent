"""Deterministic workflow scenarios; no model, network, or database required."""
import copy
import threading
import unittest
from contextlib import ExitStack, contextmanager
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from agent import practice
from db import practice as storage


class PracticeMemory:
    def __init__(self, concept_count=5):
        self.chapter = {
            "id": 3, "title": "Lecture 2 development fixture",
            "concepts": [{"id": index, "name": f"Concept {index}"} for index in range(1, concept_count + 1)],
            "pages": [{"document_id": 6, "page_number": 12, "filename": "lecture2.pdf", "position": 1, "body": "Development facts"}],
        }
        self.session = None
        self.questions = []
        self.answers = {}
        self.progress = {}
        self.guard = threading.RLock()

    @contextmanager
    def lock(self, *args):
        with self.guard:
            yield

    def create(self, user, course, chapter, threshold):
        self.session = {
            "id": 9, "user_id": user, "course_id": course, "chapter_id": 3,
            "status": "open", "phase": "learn", "review_round": 1,
            "workflow_version": 2, "passing_threshold": str(threshold),
            "round_results": [], "drafts": {}, "report": None,
        }
        return 9

    def current(self, session_id):
        return next((copy.deepcopy(q) for q in self.questions if q["id"] not in self.answers), None)

    def write(self, concept, pages, kind, miss):
        return {
            "concept_id": concept["id"], "concept_name": concept["name"],
            "kind": kind, "prompt": f"Explain {concept['name']}",
            "options": ["Fact", "Wrong", "Other", "Another"] if kind == "mcq" else [],
            "answer": "A" if kind == "mcq" else "Facts",
            "rubric": [] if kind == "mcq" else ["One", "Two", "Three", "Four", "Five"],
            "sources": [{"document_id": 6, "page_number": 12, "filename": "lecture2.pdf", "position": 1}],
        }

    def store(self, session_id, round_number, questions):
        if any(q["review_round"] == round_number for q in self.questions):
            return
        for question in questions:
            self.questions.append({
                **copy.deepcopy(question), "id": len(self.questions) + 1,
                "review_round": round_number,
                "phase": "learn" if round_number == 1 else "review",
                "rubric_json": question["rubric"], "options_json": question["options"],
                "sources_json": question["sources"],
            })
        self.session["review_round"] = round_number
        self.session["phase"] = "learn" if round_number == 1 else "review"

    def save(self, question_id, response, correct, hit, total, explanation):
        if question_id in self.answers:
            raise AssertionError("Duplicate scoring")
        question = next(q for q in self.questions if q["id"] == question_id)
        self.answers[question_id] = {
            **copy.deepcopy(question), "question_id": question_id,
            "round_number": question["review_round"], "response": response,
            "correct": correct, "points_hit": hit, "points_total": total,
            "explanation": explanation,
        }

    def draft(self, session_id, question_id, response):
        self.session["drafts"][str(question_id)] = response

    def publish(self, session_id, report, closing=False):
        self.session["report"] = copy.deepcopy(report)
        if closing:
            self.session["status"] = "finished"

    def question(self, session_id, question_id):
        return {"id": question_id, "answer_id": question_id if question_id in self.answers else None} if any(q["id"] == question_id for q in self.questions) else None

    def patches(self, stack):
        bindings = {
            "load_chapter": lambda *args, **kwargs: copy.deepcopy(self.chapter),
            "practice_lock": self.lock,
            "open_session_id": lambda *args: 9 if self.session and self.session["status"] == "open" else None,
            "create_session": self.create,
            "get_owned_session": lambda *args: copy.deepcopy(self.session),
            "present_session": lambda *args: copy.deepcopy(self.session),
            "unanswered_question": self.current,
            "round_question_count": lambda sid, rnd: sum(q["review_round"] == rnd for q in self.questions),
            "load_session_attempts": lambda *args: copy.deepcopy(list(self.answers.values())),
            "save_round_results": lambda sid, results: self.session.update(round_results=copy.deepcopy(results)),
            "store_round": self.store,
            "save_answer": self.save,
            "save_draft": self.draft,
            "publish_session_report": self.publish,
            "progress_map": lambda *args: self.progress,
            "save_progress": lambda uid, cid, level, streak: self.progress.update({cid: {"level": level, "streak": streak}}),
            "question_in_session": self.question,
            "latest_miss": lambda *args: None,
            "_write_question": self.write,
            "_grade_shorts": lambda items: {q["id"]: list(range(1, 6)) if response == "correct" else [] for q, response, rubric in items},
            "_explain": lambda questions, wrong: {q["id"]: "Review the cited fact on page 12." for q in questions},
        }
        return {name: stack.enter_context(patch.object(practice, name, side_effect=value)) for name, value in bindings.items()}

    def answer_round(self, flags):
        for correct in flags:
            current = self.current(9)
            if current is None:
                raise AssertionError("No question available")
            response = ("A" if correct else "B") if current["kind"] == "mcq" else ("correct" if correct else "wrong")
            practice.answer_practice(1, 2, 9, current["id"], response)


class PracticeRoundsTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.memory = PracticeMemory()
        self.mocks = self.memory.patches(self.stack)

    def start(self, threshold=.8):
        return practice.start_practice(1, 2, 3, threshold)

    def test_twenty_scripted_sessions_cover_thresholds_and_final_outcomes(self):
        scenarios = [
            (.7, 7, None), (.7, 8, None), (.7, 9, None), (.7, 10, None),
            (.8, 8, None), (.8, 9, None), (.8, 10, None),
            (.9, 9, None), (.9, 10, None),
            (.7, 6, True), (.7, 5, True), (.8, 7, True),
            (.8, 6, True), (.9, 8, True), (.9, 7, True),
            (.7, 6, False), (.8, 7, False), (.9, 8, False),
            (.8, 0, False), (.9, 0, True),
        ]
        for threshold, correct, second_pass in scenarios:
            with self.subTest(threshold=threshold, correct=correct, second_pass=second_pass):
                self.memory.session = None
                self.memory.questions = []
                self.memory.answers = {}
                self.start(threshold)
                self.memory.answer_round([True] * correct + [False] * (10 - correct))
                if second_pass is not None:
                    self.assertEqual(self.memory.session["review_round"], 2)
                    weak_ids = {a["concept_id"] for a in self.memory.answers.values() if not a["correct"]}
                    second = [q for q in self.memory.questions if q["review_round"] == 2]
                    self.assertEqual({q["concept_id"] for q in second}, weak_ids)
                    self.memory.answer_round([second_pass] * len(second))
                report = self.memory.session["report"]
                self.assertEqual(self.memory.session["status"], "finished")
                self.assertEqual(len(report["rounds"]), 1 if second_pass is None else 2)
                self.assertEqual(report["outcome"], "passed_round_1" if second_pass is None else "passed_round_2" if second_pass else "failed_after_2")
                self.assertEqual(report["rounds"][0]["correct_count"], correct)
                self.assertFalse(any(q["review_round"] > 2 for q in self.memory.questions))
                if second_pass is False:
                    self.assertTrue(report["remaining_weak_concepts"])
                    self.assertEqual(report["remaining_sources"][0]["page_number"], 12)

    def test_resume_keeps_saved_question_ids_and_threshold(self):
        self.start(.9)
        original = copy.deepcopy(self.memory.questions)
        practice.save_practice_draft(1, 2, 9, 1, "A")
        self.start(.7)
        practice.open_practice(1, 2, 9)
        self.assertEqual(self.memory.questions, original)
        self.assertEqual(self.memory.session["passing_threshold"], "0.9")
        self.assertEqual(self.memory.session["drafts"]["1"], "A")
        self.assertEqual(self.mocks["_write_question"].call_count, 10)

    def test_duplicate_answer_returns_without_grading_or_changing_score(self):
        self.start()
        practice.answer_practice(1, 2, 9, 1, "A")
        practice.answer_practice(1, 2, 9, 2, "correct")
        saved = copy.deepcopy(self.memory.answers)
        calls = self.mocks["_grade_shorts"].call_count
        practice.answer_practice(1, 2, 9, 2, "wrong")
        self.assertEqual(self.memory.answers, saved)
        self.assertEqual(self.mocks["_grade_shorts"].call_count, calls)

    def test_concurrent_duplicate_short_answer_scores_once(self):
        self.start()
        practice.answer_practice(1, 2, 9, 1, "A")
        with ThreadPoolExecutor(max_workers=2) as pool:
            requests = [pool.submit(practice.answer_practice, 1, 2, 9, 2, "correct") for _ in range(2)]
            for request in requests:
                request.result()
        self.assertEqual(self.mocks["_grade_shorts"].call_count, 1)
        self.assertEqual(len(self.memory.answers), 2)

    def test_existing_questions_resume_without_new_ingestion_check(self):
        self.start()
        def load(*args, **kwargs):
            if kwargs.get("require_ready", True):
                raise RuntimeError("vector database unavailable")
            return copy.deepcopy(self.memory.chapter)
        self.mocks["load_chapter"].side_effect = load
        practice.open_practice(1, 2, 9)
        practice.answer_practice(1, 2, 9, 1, "A")
        self.assertEqual(len(self.memory.questions), 10)

    def test_malformed_model_question_is_rejected(self):
        concept = self.memory.chapter["concepts"][0]
        pages = self.memory.chapter["pages"]
        item = {"concept": concept["name"], "kind": "mcq", "prompt": "A question?",
                "options": ["One fact", "Two facts", "Three facts", "Four facts"],
                "answer": "A", "pages": [{"document_id": 6, "page_number": 12}]}
        cases = [{"answer": "Apple"}, {"options": "Four"},
                 {"options": [1, "Two facts", "Three facts", "Four facts"]},
                 {"pages": [{"document_id": "bad", "page_number": 12}]},
                 {"pages": [{"document_id": 999, "page_number": 12}]},
                 {"pages": "page 12"}]
        for change in cases:
            with self.subTest(change=change):
                self.assertIsNone(practice.question_from_reply({"question": {**item, **change}}, concept, pages, "mcq"))
        short = {**item, "kind": "short", "answer": "A fact", "rubric": ["One", "Two", "Three"]}
        for rubric in ("abc", ["One", "Two", None], ["One", "One", "One"]):
            with self.subTest(rubric=rubric):
                self.assertIsNone(practice.question_from_reply({"question": {**short, "rubric": rubric}}, concept, pages, "short"))

    def test_model_failure_keeps_draft_pending_and_no_round_score(self):
        self.start()
        practice.answer_practice(1, 2, 9, 1, "A")
        self.mocks["_grade_shorts"].side_effect = RuntimeError("timeout")
        with self.assertRaisesRegex(RuntimeError, "timeout"):
            practice.answer_practice(1, 2, 9, 2, "my saved answer")
        self.assertEqual(self.memory.session["drafts"]["2"], "my saved answer")
        self.assertNotIn(2, self.memory.answers)
        self.assertEqual(self.memory.session["round_results"], [])
        self.assertIsNone(self.memory.session["report"])

    def test_incomplete_grade_cannot_become_false_answer(self):
        self.start()
        practice.answer_practice(1, 2, 9, 1, "A")
        self.mocks["_grade_shorts"].side_effect = lambda items: {}
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            practice.answer_practice(1, 2, 9, 2, "answer")
        self.assertNotIn(2, self.memory.answers)
        self.assertEqual(self.memory.session["round_results"], [])

    def test_second_round_generation_failure_recovers_saved_first_score(self):
        self.start()
        self.memory.answer_round([False] * 9)
        first_ids = [q["id"] for q in self.memory.questions]
        self.mocks["_write_question"].side_effect = RuntimeError("generation timeout")
        with self.assertRaisesRegex(RuntimeError, "generation timeout"):
            practice.answer_practice(1, 2, 9, 10, "wrong")
        saved = copy.deepcopy(self.memory.session["round_results"])
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["correct_count"], 0)
        self.assertEqual([q["id"] for q in self.memory.questions], first_ids)
        self.mocks["_write_question"].side_effect = self.memory.write
        practice.open_practice(1, 2, 9)
        self.assertEqual(self.memory.session["round_results"], saved)
        self.assertEqual(self.memory.session["review_round"], 2)
        self.assertEqual([q["id"] for q in self.memory.questions[:10]], first_ids)

    def test_finished_report_is_immutable_on_reopening(self):
        self.start()
        self.memory.answer_round([True] * 10)
        report = copy.deepcopy(self.memory.session["report"])
        self.memory.progress.clear()
        practice.open_practice(1, 2, 9)
        self.assertEqual(self.memory.session["report"], report)
        self.assertEqual(self.mocks["publish_session_report"].call_count, 1)
        self.assertEqual(self.mocks["_write_question"].call_count, 10)

    def test_feedback_is_generated_only_for_wrong_answers_and_has_sources(self):
        self.start()
        self.memory.answer_round([True] * 8 + [False] * 2)
        self.assertEqual(self.mocks["_explain"].call_count, 2)
        report = self.memory.session["report"]
        self.assertEqual(len(report["wrong"]), 2)
        self.assertTrue(all(q["sources"][0]["document_id"] == 6 for q in report["wrong"]))

    def test_empty_round_and_third_round_are_rejected(self):
        for round_number, attempts in ((1, []), (3, [{"correct": True}])):
            with self.subTest(round_number=round_number), self.assertRaises(ValueError):
                practice.round_result(attempts, round_number)

    def test_legacy_history_is_preserved_without_an_official_score(self):
        self.start()
        self.memory.session["workflow_version"] = 1
        ids = [q["id"] for q in self.memory.questions]
        practice.open_practice(1, 2, 9)
        self.assertEqual([q["id"] for q in self.memory.questions], ids)
        self.assertEqual(self.memory.session["status"], "finished")
        self.assertEqual(self.memory.session["report"]["outcome"], "legacy")
        self.assertIsNone(self.memory.session["report"]["passed"])


class PracticeLockTest(unittest.TestCase):
    def test_named_lock_releases_on_exception(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"acquired": 1}
        with patch.object(storage, "ensure_practice_storage"), patch.object(storage, "connect", return_value=connection):
            with self.assertRaisesRegex(RuntimeError, "model failed"):
                with storage.practice_lock(1, 2, 3):
                    raise RuntimeError("model failed")
        calls = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertIn("SELECT GET_LOCK(%s, 30) AS acquired", calls)
        self.assertIn("SELECT RELEASE_LOCK(%s)", calls)
        connection.close.assert_called_once()

    def test_busy_lock_prevents_work(self):
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.fetchone.return_value = {"acquired": 0}
        with patch.object(storage, "ensure_practice_storage"), patch.object(storage, "connect", return_value=connection):
            with self.assertRaisesRegex(RuntimeError, "busy"):
                with storage.practice_lock(1, 2, 3):
                    self.fail("Busy session must not execute")
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
