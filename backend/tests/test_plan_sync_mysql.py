"""Opt-in SQL acceptance tests using connection-local TEMPORARY tables only.

Run from backend:
  CITEPATH_SYNC_MYSQL_TESTS=1 .venv/bin/python -B -m unittest discover -s tests -p test_plan_sync_mysql.py -v

No model calls, real courses, or persistent schema migrations are used.
"""
import copy
import json
import os
from pathlib import Path
import re
from contextlib import ExitStack
import unittest
from unittest.mock import patch

from db import exams, plans, practice, plan_sync


class SharedConnection:
    def __init__(self, connection):
        self.connection = connection

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def close(self):
        # Keep all application calls inside the same temporary-table session.
        pass


@unittest.skipUnless(
    os.environ.get("CITEPATH_SYNC_MYSQL_TESTS") == "1",
    "Opt in to connection-local MySQL temporary-table tests",
)
class LearningSyncMySQLTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from dotenv import load_dotenv
        from db.connection import connect

        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        cls.connection = connect()
        cls.addClassCleanup(cls.connection.close)
        cls.tables = (
            "courses", "documents", "study_plans", "plan_chapters",
            "plan_concepts", "plan_chapter_pages", "concept_progress",
            "practice_sessions", "exams", "exam_questions",
            "exam_answers", "exam_drafts",
        )
        schema = (Path(__file__).resolve().parents[1] / "db/schema.sql").read_text()
        with cls.connection.cursor() as cursor:
            for name in cls.tables:
                match = re.search(
                    rf"CREATE TABLE IF NOT EXISTS {name} \((.*?)\) ENGINE=.*?;",
                    schema, re.S,
                )
                if match is None:
                    raise AssertionError(f"Missing fixture schema: {name}")
                # MySQL temporary tables do not support foreign keys.
                body = "\n".join(
                    line for line in match[1].splitlines()
                    if not line.strip().startswith("CONSTRAINT ")
                ).rstrip().rstrip(",")
                cursor.execute(
                    f"CREATE TEMPORARY TABLE `{name}` ({body}) ENGINE=InnoDB"
                )

        stack = ExitStack()
        cls.addClassCleanup(stack.close)
        proxy = SharedConnection(cls.connection)
        for module in (plans, practice, exams, plan_sync):
            stack.enter_context(patch.object(module, "connect", return_value=proxy))
        for module, name in (
            (plans, "ensure_plan_storage"),
            (plans, "ensure_document_numbers"),
            (practice, "ensure_practice_storage"),
            (exams, "ensure_exam_storage"),
            (exams, "ensure_learning_sync_storage"),
            (plan_sync, "ensure_learning_sync_storage"),
        ):
            stack.enter_context(patch.object(module, name))
        stack.enter_context(patch.object(plans, "get_course", return_value={"id": 1}))

    def setUp(self):
        self.connection.rollback()
        with self.connection.cursor() as cursor:
            # These names are all shadowed by the TEMPORARY tables above.
            for name in self.tables:
                cursor.execute(f"DELETE FROM `{name}`")
            cursor.execute(
                "INSERT INTO courses (id,user_id,name,student_brief) VALUES (1,10,'Test','test')"
            )
            cursor.execute(
                "INSERT INTO documents (id,course_id,position,filename,chapter_plan_status) "
                "VALUES (7,1,1,'test.pdf','planned'), (8,1,2,'untouched.pdf','planned')"
            )
            cursor.execute(
                "INSERT INTO plan_chapters (id,course_id,position,title) VALUES (4,1,1,'Sorting')"
            )
            cursor.execute(
                "INSERT INTO plan_concepts (id,chapter_id,position,name) VALUES (5,4,1,'Merge sort')"
            )
            cursor.execute(
                "INSERT INTO plan_chapter_pages (chapter_id,document_id,page_number,position) VALUES (4,7,1,1)"
            )
            self.original = {
                "version": 3, "start": "2026-11-19", "end": "2026-12-01",
                "chapters": [{"id": "4", "title": "Sorting", "concepts": ["Merge sort"], "sources": []}],
                "tasks": [
                    {"id": f"{kind.lower()}-4", "chapterId": "4", "kind": kind,
                     "status": "Not started", "date": "2026-11-19"}
                    for kind in ("Reading", "Practice", "Review")
                ],
            }
            cursor.execute(
                "INSERT INTO study_plans (course_id,student_brief,plan_json) VALUES (1,'test',%s)",
                (json.dumps(self.original),),
            )
        self.connection.commit()
        self.chapter = {"id": 4, "title": "Sorting"}

    def stored(self):
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT plan_json FROM study_plans WHERE course_id=1")
            return json.loads(cursor.fetchone()["plan_json"])

    def assert_pdf_locked(self):
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id,chapter_plan_status,chapterization_locked_at FROM documents ORDER BY id"
            )
            rows = cursor.fetchall()
        self.assertEqual(rows[0]["chapter_plan_status"], "locked")
        self.assertIsNotNone(rows[0]["chapterization_locked_at"])
        self.assertEqual(rows[1]["chapter_plan_status"], "planned")

    def start_exam(self):
        return exams.save_exam(10, 1, self.chapter, [{
            "concept_id": 5, "concept_name": "Merge sort", "kind": "mcq",
            "prompt": "Test", "options": ["one", "two", "three", "four"],
            "answer": "A", "sources": [],
        }])

    def finish_exam(self, exam, passed):
        return exams.finish_exam(10, 1, exam["id"],
            {"score": 100 if passed else 0, "passed": passed, "total": 1},
            [{"question_id": exam["questions"][0]["id"], "response": "A" if passed else "B",
              "correct": passed, "points_hit": int(passed), "points_total": 1}])

    def test_read_done_persists_and_locks_pdf(self):
        result = plans.complete_read_task(10, 1, "reading-4")
        self.assertEqual(result["status"], "ready")
        read = result["plan"]["tasks"][0]
        self.assertEqual(read["status"], "Completed")
        self.assertEqual(read["completion_source"], "student")
        self.assertEqual(result["plan"]["chapters"][0]["chapter_status"], "learned")
        self.assert_pdf_locked()

    def test_exam_start_preserves_read_and_practice(self):
        self.start_exam()
        plan = self.stored()
        self.assertEqual([t["status"] for t in plan["tasks"][:2]], ["Not started"] * 2)
        self.assertEqual(plan["chapter_states"]["4"]["chapter_status"], "exam_pending")
        self.assertEqual(len(plan["tasks"]), 2)
        self.assert_pdf_locked()

    def test_practice_start_updates_task_and_locks_pdf(self):
        practice.create_session(10, 1, self.chapter)
        plan = self.stored()
        self.assertEqual(plan["tasks"][1]["status"], "In progress")
        self.assertEqual(plan["chapter_states"]["4"]["chapter_status"], "practice_in_progress")
        self.assert_pdf_locked()

    def test_plan_exposes_open_practice_and_mastery_even_with_an_exam_open(self):
        def chapter(plan):
            return plan["plan"]["chapters"][0]

        self.assertNotIn("practice_progress", chapter(plans.get_plan(10, 1)))

        session_id = practice.create_session(10, 1, self.chapter)
        with self.connection.cursor() as cursor:
            cursor.execute("INSERT INTO concept_progress (user_id,concept_id,level,streak) VALUES (10,5,2,2)")
        self.connection.commit()
        self.start_exam()

        current = chapter(plans.get_plan(10, 1))
        self.assertEqual(current["chapter_status"], "exam_pending")
        self.assertEqual(current["practice_progress"], {
            "open_session_id": session_id, "has_finished": False, "mastered": 1, "total": 1,
        })
        self.assertNotIn("practice_progress", chapter(plans.get_plan(11, 1)))

        practice.mark_session_finished(session_id, 10)
        self.assertEqual(chapter(plans.get_plan(10, 1))["practice_progress"], {
            "open_session_id": None, "has_finished": True, "mastered": 1, "total": 1,
        })

    def test_mastered_practice_finishes(self):
        session_id = practice.create_session(10, 1, self.chapter)
        with self.connection.cursor() as cursor:
            cursor.execute("INSERT INTO concept_progress (user_id,concept_id,level,streak) VALUES (10,5,2,2)")
        self.connection.commit()
        practice.mark_session_finished(session_id, 10)
        task = self.stored()["tasks"][1]
        self.assertEqual(task["status"], "Completed")
        self.assertEqual(task["completion_source"], "practice_submit")

    def test_unmastered_finished_session_does_not_complete_practice(self):
        session_id = practice.create_session(10, 1, self.chapter)
        practice.mark_session_finished(session_id, 10)
        self.assertEqual(self.stored()["tasks"][1]["status"], "In progress")

    def test_first_exam_pass_completes_read_without_adding_review(self):
        self.finish_exam(self.start_exam(), True)
        plan = self.stored()
        self.assertEqual(plan["tasks"][0]["completion_source"], "exam_pass")
        self.assertEqual([task["kind"] for task in plan["tasks"]], ["Reading", "Practice"])
        self.assertEqual(plan["chapter_states"]["4"]["review_status"], "passed")
        self.assert_pdf_locked()

    def test_exam_failure_requires_review(self):
        self.finish_exam(self.start_exam(), False)
        plan = self.stored()
        self.assertEqual(plan["tasks"][0]["status"], "Not started")
        self.assertEqual(plan["tasks"][2]["status"], "Not started")
        self.assertEqual(plan["chapter_states"]["4"]["review_status"], "required")

    def test_later_failure_preserves_read_and_creates_review(self):
        self.finish_exam(self.start_exam(), True)
        self.finish_exam(self.start_exam(), False)
        plan = self.stored()
        self.assertEqual(plan["tasks"][0]["status"], "Completed")
        self.assertEqual(plan["tasks"][2]["status"], "Not started")
        self.assertEqual(plan["chapter_states"]["4"]["review_status"], "required")

    def test_repeat_read_and_refresh_preserve_identity_dates_and_version(self):
        plans.complete_read_task(10, 1, "reading-4")
        once = copy.deepcopy(self.stored())
        plans.complete_read_task(10, 1, "reading-4")
        plan_sync.refresh_learning_state(10, 1)
        self.assertEqual(self.stored(), once)
        self.assertEqual(once["version"], 3)
        self.assertEqual([(t["id"], t["date"]) for t in once["tasks"]],
                         [(t["id"], t["date"]) for t in self.original["tasks"][:2]])

    def test_duplicate_exam_submission_does_not_duplicate_answers(self):
        exam = self.start_exam()
        self.finish_exam(exam, True)
        once = self.stored()
        self.finish_exam(exam, False)
        self.assertEqual(self.stored(), once)
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM exam_answers")
            self.assertEqual(cursor.fetchone()["n"], 1)

    def test_only_read_can_be_manually_completed(self):
        for task_id in ("practice-4", "review-4"):
            with self.assertRaises(ValueError):
                plans.complete_read_task(10, 1, task_id)
        self.assertEqual(self.stored(), self.original)

    def test_wrong_owner_cannot_complete_read(self):
        with self.assertRaises(LookupError):
            plans.complete_read_task(11, 1, "reading-4")
        self.assertEqual(self.stored(), self.original)

    def test_failed_sync_rolls_back_exam_creation(self):
        with patch.object(exams, "sync_learning_state", side_effect=RuntimeError("test failure")):
            with self.assertRaises(RuntimeError):
                self.start_exam()
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM exams")
            self.assertEqual(cursor.fetchone()["n"], 0)
        self.assertEqual(self.stored(), self.original)


if __name__ == "__main__":
    unittest.main()
