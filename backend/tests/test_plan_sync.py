import copy
import unittest

from db.plan_sync import reduce_chapter_state


def make_plan():
    return {
        "version": 3,
        "start": "2026-11-19",
        "end": "2026-12-01",
        "chapters": [
            {
                "id": "4",
                "title": "Sorting",
                "concepts": ["Merge sort"],
                "sources": [{"document_id": 7}],
            }
        ],
        "tasks": [
            {
                "id": "reading-4",
                "chapterId": "4",
                "kind": "Reading",
                "status": "Not started",
                "date": "2026-11-19",
            },
            {
                "id": "practice-4",
                "chapterId": "4",
                "kind": "Practice",
                "status": "Not started",
                "date": "2026-11-20",
            },
            {
                "id": "review-4",
                "chapterId": "4",
                "kind": "Review",
                "status": "Not started",
                "date": "2026-11-21",
            },
        ],
    }


def facts(**overrides):
    result = {
        "practice_started": False,
        "practice_finished": False,
        "practice_mastered": False,
        "exam_started": False,
        "exam_open": False,
        "ever_exam_passed": False,
        "ever_exam_failed": False,
        "latest_exam_passed": None,
    }
    result.update(overrides)
    return result


class PlanSyncTest(unittest.TestCase):
    def test_manual_read_completion_is_preserved(self):
        plan = make_plan()
        plan["tasks"][0].update(
            status="Completed",
            completion_source="student",
        )

        result = reduce_chapter_state(
            plan, 4, facts()
        )

        self.assertEqual(
            result["tasks"][0]["completion_source"],
            "student",
        )
        self.assertEqual(
            result["chapter_states"]["4"]["chapter_status"],
            "learned",
        )

    def test_exam_start_does_not_complete_read_or_practice(self):
        result = reduce_chapter_state(
            make_plan(),
            4,
            facts(exam_started=True, exam_open=True),
        )

        self.assertEqual(
            result["tasks"][0]["status"],
            "Not started",
        )
        self.assertEqual(
            result["tasks"][1]["status"],
            "Not started",
        )
        self.assertEqual(
            result["chapter_states"]["4"]["chapter_status"],
            "exam_pending",
        )

    def test_practice_started(self):
        result = reduce_chapter_state(
            make_plan(),
            4,
            facts(practice_started=True),
        )

        self.assertEqual(
            result["tasks"][1]["status"],
            "In progress",
        )

    def test_practice_finished_requires_mastery(self):
        unfinished = reduce_chapter_state(
            make_plan(),
            4,
            facts(
                practice_started=True,
                practice_finished=True,
                practice_mastered=False,
            ),
        )
        self.assertEqual(
            unfinished["tasks"][1]["status"],
            "In progress",
        )

        finished = reduce_chapter_state(
            make_plan(),
            4,
            facts(
                practice_started=True,
                practice_finished=True,
                practice_mastered=True,
            ),
        )
        self.assertEqual(
            finished["tasks"][1]["status"],
            "Completed",
        )
        self.assertEqual(
            finished["tasks"][1]["completion_source"],
            "practice_submit",
        )

    def test_first_exam_pass_completes_read_and_drops_legacy_review(self):
        result = reduce_chapter_state(
            make_plan(),
            4,
            facts(
                exam_started=True,
                ever_exam_passed=True,
                latest_exam_passed=True,
            ),
        )

        self.assertEqual(
            result["tasks"][0]["status"],
            "Completed",
        )
        self.assertEqual(
            result["tasks"][1]["status"],
            "Not started",
        )
        self.assertEqual([task["kind"] for task in result["tasks"]], ["Reading", "Practice"])
        self.assertEqual(
            result["chapter_states"]["4"]["review_status"],
            "passed",
        )

    def test_failure_creates_review_and_keeps_read_completed(self):
        passed = reduce_chapter_state(
            make_plan(),
            4,
            facts(
                ever_exam_passed=True,
                latest_exam_passed=True,
            ),
        )

        failed = reduce_chapter_state(
            passed,
            4,
            facts(
                ever_exam_passed=True,
                latest_exam_passed=False,
            ),
        )

        self.assertEqual(
            failed["tasks"][0]["status"],
            "Completed",
        )
        self.assertEqual(
            failed["tasks"][2]["status"],
            "Not started",
        )
        self.assertEqual(
            failed["chapter_states"]["4"]["review_status"],
            "required",
        )

    def test_repeat_sync_preserves_plan_version_and_structure(self):
        plan = make_plan()
        original = copy.deepcopy(plan)
        evidence = facts(
            practice_started=True,
            practice_finished=True,
            practice_mastered=True,
        )

        once = reduce_chapter_state(plan, 4, evidence)
        twice = reduce_chapter_state(once, 4, evidence)

        self.assertEqual(plan, original)
        self.assertEqual(once, twice)
        self.assertEqual(twice["version"], 3)
        self.assertEqual(
            twice["chapters"][0]["concepts"],
            original["chapters"][0]["concepts"],
        )
        self.assertEqual(
            [task["date"] for task in twice["tasks"]],
            [task["date"] for task in original["tasks"][:2]],
        )


if __name__ == "__main__":
    unittest.main()