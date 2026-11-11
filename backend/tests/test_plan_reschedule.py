import copy
import json
import unittest
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from agent import plan as planner
from db import plans


def sample_plan():
    chapters = [
        {"id": "11", "title": "Trees", "concepts": ["Traversal"], "sources": [{"document_id": 7, "page_number": 12}]},
        {"id": "12", "title": "Graphs", "concepts": ["Search"], "sources": [{"document_id": 7, "page_number": 15}]},
    ]
    return planner.assemble_plan(chapters, "2026-11-01", "2026-11-03", "Initial plan", 1)


class RescheduleTest(unittest.TestCase):
    def test_preserves_completed_snapshot_and_chapter_identity(self):
        previous = sample_plan()
        previous["tasks"][0]["status"] = "Completed"
        previous["tasks"][0]["completed_at"] = "2026-11-02"
        original = copy.deepcopy(previous)
        result = planner.reschedule_plan(previous, "2026-11-11", "2026-11-15", "Focus on search", {"12": ["Search"]})
        self.assertEqual(previous, original)
        self.assertEqual(result["chapters"], original["chapters"])
        self.assertEqual(result["tasks"][0], original["tasks"][0])
        self.assertEqual(result["version"], 2)
        self.assertEqual({task["id"] for task in result["tasks"]}, {task["id"] for task in previous["tasks"]})
        pending = [task for task in result["tasks"] if task["status"] != "Completed"]
        self.assertEqual(pending[0]["chapterId"], "12")
        self.assertEqual(pending[0]["date"], "2026-11-11")
        self.assertEqual(pending[-1]["date"], "2026-11-15")
        self.assertIn("latest practice reports: Graphs", result["reason"])

    def test_revised_note_can_prioritize_unfinished_goal_chapter(self):
        result = planner.reschedule_plan(sample_plan(), "2026-11-11", "2026-11-15", "Review graphs search", {})
        self.assertEqual(result["tasks"][0]["chapterId"], "12")
        self.assertEqual(result["tasks"][0]["date"], "2026-11-11")

    def test_recorded_weakness_takes_priority_over_note_keyword(self):
        result = planner.reschedule_plan(sample_plan(), "2026-11-11", "2026-11-15", "Review graphs", {"11": ["Traversal"]})
        self.assertEqual(result["tasks"][0]["chapterId"], "11")

    def test_all_completed_tasks_keep_their_dates(self):
        previous = sample_plan()
        for task in previous["tasks"]:
            task["status"] = "Completed"
        result = planner.reschedule_plan(previous, "2026-12-01", "2026-12-01", "", {})
        self.assertEqual(result["tasks"], previous["tasks"])

    def test_rejects_invalid_calendar_dates(self):
        with self.assertRaisesRegex(ValueError, "valid study dates"):
            planner.reschedule_plan(sample_plan(), "2026-02-30", "2026-12-01", "", {})

    def test_existing_plan_reschedules_without_model_or_vector_access(self):
        brief = json.dumps({"schema": "citepath-course-v1", "deadline": "2026-12-01", "earlyDays": 0, "note": ""})
        with patch.object(planner, "get_course", return_value={"id": 3}), patch.object(
            planner, "save_course_note", return_value=brief
        ), patch.object(planner, "get_plan", return_value={"plan": sample_plan()}), patch.object(
            planner, "load_plan_feedback", return_value={"12": ["Search"]}
        ), patch.object(planner, "save_rescheduled_plan", side_effect=lambda _, plan, **kwargs: plan) as save, patch.object(
            planner, "_split_pages"
        ) as split, patch.object(planner, "load_usable_pages") as pages, patch.object(
            planner, "save_generated_plan"
        ) as generate, patch.object(planner, "planning_lock", return_value=nullcontext()), patch.object(
            planner, "load_planning_materials", return_value={"documents": [], "pages": [], "fingerprint": "same"}
        ):
            result = planner.generate_plan(1, 3, "2026-11-11", "2026-11-15", "Review graphs")
        split.assert_not_called()
        pages.assert_not_called()
        generate.assert_not_called()
        save.assert_called_once()
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["plan"]["chapters"][0]["id"], "11")


class PlanFeedbackTest(unittest.TestCase):
    def test_latest_report_replaces_older_weakness_and_is_not_combined(self):
        feedback = plans.feedback_from_reports([
            {"chapter_id": 11, "report_json": json.dumps({"remaining_weak_concepts": []})},
            {"chapter_id": 12, "report_json": {"remaining_weak_concepts": ["Search"]}},
            {"chapter_id": 11, "report_json": {"remaining_weak_concepts": ["Traversal"]}},
        ])
        self.assertEqual(feedback, {"11": [], "12": ["Search"]})

    def test_legacy_report_uses_recorded_wrong_concepts(self):
        self.assertEqual(plans.feedback_from_reports([
            {"chapter_id": 11, "report_json": {"wrong": [{"concept_name": "Traversal"}]}},
        ]), {"11": ["Traversal"]})


class PlanPersistenceTest(unittest.TestCase):
    def connection(self, stored):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"plan_json": json.dumps(stored)}
        return connection, cursor

    def test_reschedule_keeps_concurrent_completion_and_does_not_replace_chapters(self):
        before = sample_plan()
        updated = planner.reschedule_plan(before, "2026-11-11", "2026-11-15", "", {})
        concurrent = copy.deepcopy(before)
        concurrent["version"] = 3
        concurrent["tasks"][1]["status"] = "Completed"
        connection, cursor = self.connection(concurrent)
        with patch.object(plans, "connect", return_value=connection), patch.object(
            plans, "_delete_chapters"
        ) as delete:
            saved = plans.save_rescheduled_plan(3, updated)
        self.assertEqual(saved["version"], 4)
        self.assertEqual(next(task for task in saved["tasks"] if task["id"] == "practice-11"), concurrent["tasks"][1])
        self.assertIn("FOR UPDATE", cursor.execute.call_args_list[0].args[0])
        self.assertFalse(any("DELETE" in item.args[0] for item in cursor.execute.call_args_list))
        delete.assert_not_called()
        connection.commit.assert_called_once()

    def test_existing_plan_cannot_be_overwritten_with_new_chapter_ids(self):
        connection, _ = self.connection(sample_plan())
        with patch.object(plans, "ensure_plan_storage"), patch.object(
            plans, "connect", return_value=connection
        ), patch.object(plans, "_delete_chapters") as delete:
            with self.assertRaisesRegex(ValueError, "preserve learning history"):
                plans.save_generated_plan(3, sample_plan())
        delete.assert_not_called()
        connection.rollback.assert_called_once()

    def test_task_completion_uses_current_locked_schedule(self):
        latest = planner.reschedule_plan(sample_plan(), "2026-12-01", "2026-12-09", "", {})
        connection, cursor = self.connection(latest)
        with patch.object(plans, "get_course", return_value={"id": 3}), patch.object(
            plans, "ensure_plan_storage"
        ), patch.object(plans, "connect", return_value=connection), patch.object(plans, "_stamp_document_numbers"), patch.object(
            plans, "load_planning_materials", return_value={"documents": [], "pages": []}
        ):
            saved = plans.complete_task(1, 3, "reading-11")["plan"]
        self.assertEqual(saved["tasks"][0]["status"], "Completed")
        self.assertEqual(saved["tasks"][0]["date"], "2026-12-01")
        self.assertEqual(saved["end"], "2026-12-09")
        self.assertIn("FOR UPDATE", cursor.execute.call_args_list[0].args[0])


if __name__ == "__main__":
    unittest.main()
