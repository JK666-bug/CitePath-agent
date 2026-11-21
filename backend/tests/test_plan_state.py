import unittest

from agent.plan_state import (
    normalize_chapter_status,
    normalize_completion_source,
    normalize_review_status,
    normalize_task_status,
    normalize_task_type,
)


class TaskTypeTest(unittest.TestCase):
    def test_normalizes_existing_task_names(self):
        self.assertEqual(
            normalize_task_type("Reading"),
            "read",
        )
        self.assertEqual(
            normalize_task_type("Practice"),
            "practice",
        )
        self.assertEqual(
            normalize_task_type("Review"),
            "review",
        )

    def test_accepts_canonical_task_names(self):
        self.assertEqual(
            normalize_task_type("read"),
            "read",
        )
        self.assertEqual(
            normalize_task_type("practice"),
            "practice",
        )
        self.assertEqual(
            normalize_task_type("review"),
            "review",
        )


class TaskStatusTest(unittest.TestCase):
    def test_normalizes_existing_task_statuses(self):
        self.assertEqual(
            normalize_task_status("Not started"),
            "pending",
        )
        self.assertEqual(
            normalize_task_status("In progress"),
            "in_progress",
        )
        self.assertEqual(
            normalize_task_status("Completed"),
            "completed",
        )

    def test_normalizes_exam_skip_status(self):
        self.assertEqual(
            normalize_task_status("Skipped by exam"),
            "skipped_by_exam",
        )


class ChapterStatusTest(unittest.TestCase):
    def test_normalizes_chapter_statuses(self):
        self.assertEqual(
            normalize_chapter_status("learned"),
            "learned",
        )
        self.assertEqual(
            normalize_chapter_status("complete"),
            "completed",
        )
        self.assertEqual(
            normalize_chapter_status(""),
            "planned",
        )


class ReviewStatusTest(unittest.TestCase):
    def test_normalizes_review_statuses(self):
        self.assertEqual(
            normalize_review_status(""),
            "not_assessed",
        )
        self.assertEqual(
            normalize_review_status("Needs review"),
            "required",
        )
        self.assertEqual(
            normalize_review_status("passed"),
            "passed",
        )

    def test_generic_completion_does_not_imply_exam_pass(self):
        for value in ("complete", "Completed"):
            with self.subTest(value=value):
                self.assertNotEqual(
                    normalize_review_status(value),
                    "passed",
                )


class CompletionSourceTest(unittest.TestCase):
    def test_normalizes_completion_sources(self):
        self.assertEqual(
            normalize_completion_source("user"),
            "student",
        )
        self.assertEqual(
            normalize_completion_source("exam"),
            "exam_start",
        )
        self.assertEqual(
            normalize_completion_source("practice"),
            "practice_submit",
        )


if __name__ == "__main__":
    unittest.main()
