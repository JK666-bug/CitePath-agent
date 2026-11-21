import copy
import json
import unittest
from unittest.mock import patch

from agent.plan_snapshot import load_planner_snapshot


class PlanSnapshotTest(unittest.TestCase):
    @patch("agent.plan_snapshot.get_document_plan_states")
    @patch("agent.plan_snapshot.ensure_plan_state_storage")
    @patch("agent.plan_snapshot.course_study")
    @patch("agent.plan_snapshot.get_plan")
    @patch("agent.plan_snapshot.get_course")
    def test_loads_plan_and_learning_state(
        self,
        get_course,
        get_plan,
        course_study,
        ensure_plan_state_storage,
        get_document_plan_states,
    ):
        ensure_plan_state_storage.return_value = None
        get_document_plan_states.return_value = {
            7: {
                "document_id": 7,
                "course_id": 1,
                "chapter_plan_status": "planned",
                "chapter_planned_at": "2026-11-18 10:00:00",
                "chapterization_locked_at": None,
                "chapterization_locked_reason": "",
            }
        }

        get_course.return_value = {
            "id": 1,
            "name": "Algorithms",
            "created_at": "2026-11-18 10:00:00",
            "student_brief": json.dumps(
                {
                    "schema": "citepath-course-v1",
                    "deadline": "2026-12-01",
                    "earlyDays": 2,
                    "note": "Focus on sorting.",
                }
            ),
            "documents": [
                {
                    "id": 7,
                    "position": 1,
                    "filename": "lecture-1.pdf",
                    "ingest_status": "complete",
                    "kind": "lecture",
                    "page_count": 10,
                    "usable_page_count": 9,
                    "has_file": True,
                }
            ],
        }

        get_plan.return_value = {
            "status": "ready",
            "plan": {
                "version": 3,
                "start": "2026-11-18",
                "end": "2026-12-01",
                "reason": "Initial schedule",
                "chapters": [
                    {
                        "id": "4",
                        "title": "Sorting",
                        "concepts": [
                            "Merge sort",
                            "Running time",
                        ],
                        "sources": [
                            {
                                "document_id": 7,
                                "position": 1,
                                "filename": "lecture-1.pdf",
                                "page_number": 4,
                            }
                        ],
                    }
                ],
                "tasks": [
                    {
                        "id": "reading-4",
                        "chapterId": "4",
                        "title": "Read: Sorting",
                        "kind": "Reading",
                        "date": "2026-11-18",
                        "status": "Not started",
                        "sources": [],
                        "concepts": ["Merge sort"],
                    },
                    {
                        "id": "practice-4",
                        "chapterId": "4",
                        "title": "Practice: Sorting",
                        "kind": "Practice",
                        "date": "2026-11-19",
                        "status": "Completed",
                        "sources": [],
                        "concepts": ["Merge sort"],
                    },
                    {
                        "id": "review-4",
                        "chapterId": "4",
                        "title": "Review: Sorting",
                        "kind": "Review",
                        "date": "2026-11-20",
                        "status": "Not started",
                        "sources": [],
                        "concepts": [],
                    },
                ],
            },
        }

        course_study.return_value = {
            "chapters": [
                {
                    "title": "Sorting",
                    "concepts": [],
                    "mastered_concepts": 0,
                    "total_concepts": 1,
                    "finished_rounds": 1,
                    "practice_open": False,
                    "practice_correct": 2,
                    "practice_wrong": 1,
                }
            ],
            "practice_wrongs": [],
            "exam_wrongs": [],
            "exams": {
                "Sorting": {
                    "taken": 0,
                    "passed": 0,
                }
            },
        }

        snapshot = load_planner_snapshot(10, 1)

        self.assertEqual(snapshot["course_id"], 1)
        self.assertEqual(snapshot["plan"]["version"], 3)
        self.assertEqual(
            snapshot["course_requirements"]["deadline"],
            "2026-12-01",
        )
        self.assertEqual(
            snapshot["chapters"][0]["title"],
            "Sorting",
        )
        self.assertEqual(snapshot["tasks"][0]["type"], "read")
        self.assertEqual(
            snapshot["tasks"][0]["status"],
            "pending",
        )
        self.assertEqual(
            snapshot["tasks"][1]["type"],
            "practice",
        )
        self.assertEqual(
            snapshot["tasks"][1]["status"],
            "completed",
        )
        self.assertEqual(
            snapshot["learning_state"]["by_chapter_title"][
                "Sorting"
            ]["practice_wrong"],
            1,
        )

        document = snapshot["documents"][0]

        self.assertEqual(
            document["chapter_plan_status"],
            "planned",
        )
        self.assertEqual(
            document["chapter_planned_at"],
            "2026-11-18 10:00:00",
        )
        self.assertIsNone(
            document["chapterization_locked_at"]
        )
        self.assertEqual(
            document["chapterization_locked_reason"],
            "",
        )

        ensure_plan_state_storage.assert_called_once_with()
        get_document_plan_states.assert_called_once_with(1)

    @patch("agent.plan_snapshot.get_document_plan_states")
    @patch("agent.plan_snapshot.ensure_plan_state_storage")
    @patch("agent.plan_snapshot.course_study")
    @patch("agent.plan_snapshot.get_plan")
    @patch("agent.plan_snapshot.get_course")
    def test_snapshot_does_not_mutate_source_data(
        self,
        get_course,
        get_plan,
        course_study,
        ensure_plan_state_storage,
        get_document_plan_states,
    ):
        ensure_plan_state_storage.return_value = None

        document_states = {
            7: {
                "document_id": 7,
                "course_id": 1,
                "chapter_plan_status": "locked",
                "chapter_planned_at": "2026-11-18 10:00:00",
                "chapterization_locked_at": "2026-11-18 11:00:00",
                "chapterization_locked_reason": "practice_started",
            }
        }
        get_document_plan_states.return_value = document_states

        plan = {
            "version": 1,
            "chapters": [
                {
                    "id": "4",
                    "title": "Sorting",
                    "concepts": ["Merge sort"],
                    "sources": [],
                }
            ],
            "tasks": [],
        }

        get_course.return_value = {
            "id": 1,
            "name": "Algorithms",
            "created_at": "",
            "student_brief": json.dumps(
                {
                    "schema": "citepath-course-v1",
                    "deadline": "2026-12-01",
                    "earlyDays": 0,
                    "note": "Study.",
                }
            ),
            "documents": [
                {
                    "id": 7,
                    "filename": "lecture-1.pdf",
                }
            ],
        }
        get_plan.return_value = {
            "status": "ready",
            "plan": plan,
        }
        course_study.return_value = {
            "chapters": [],
            "practice_wrongs": [],
            "exam_wrongs": [],
            "exams": {},
        }

        original_plan = copy.deepcopy(plan)
        original_states = copy.deepcopy(document_states)

        snapshot = load_planner_snapshot(10, 1)

        self.assertEqual(
            snapshot["documents"][0]["chapter_plan_status"],
            "locked",
        )

        snapshot["chapters"][0]["title"] = "Changed"
        snapshot["documents"][0]["chapter_plan_status"] = "unplanned"

        self.assertEqual(plan, original_plan)
        self.assertEqual(document_states, original_states)

    @patch("agent.plan_snapshot.get_document_plan_states")
    @patch("agent.plan_snapshot.ensure_plan_state_storage")
    @patch("agent.plan_snapshot.course_study")
    @patch("agent.plan_snapshot.get_plan")
    @patch("agent.plan_snapshot.get_course")
    def test_invalid_brief_is_returned_for_future_clarification(
        self,
        get_course,
        get_plan,
        course_study,
        ensure_plan_state_storage,
        get_document_plan_states,
    ):
        ensure_plan_state_storage.return_value = None
        get_document_plan_states.return_value = {}

        get_course.return_value = {
            "id": 1,
            "name": "Algorithms",
            "created_at": "",
            "student_brief": "unfinished note",
            "documents": [],
        }
        get_plan.return_value = {
            "status": "draft",
            "plan": None,
        }
        course_study.return_value = {
            "chapters": [],
            "practice_wrongs": [],
            "exam_wrongs": [],
            "exams": {},
        }

        snapshot = load_planner_snapshot(10, 1)

        self.assertFalse(
            snapshot["course_requirements"]["valid"]
        )
        self.assertTrue(
            snapshot["course_requirements"]["error"]
        )
        self.assertEqual(snapshot["plan"]["version"], 0)

        ensure_plan_state_storage.assert_called_once_with()
        get_document_plan_states.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()