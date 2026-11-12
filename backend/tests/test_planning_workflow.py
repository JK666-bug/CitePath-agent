import copy
import json
import unittest
from contextlib import contextmanager, nullcontext
from unittest.mock import MagicMock, patch

from agent import plan as planner
from agent.planning_support import estimate_plan, material_update, planning_profile
from db import plans
from tests.test_plan_reschedule import sample_plan


PROFILE = {"goal": "Understand graph search", "prior_knowledge": "Basic Python", "daily_minutes": 30,
           "reading_words_per_minute": 120}
BRIEF = json.dumps({"schema": "citepath-course-v1", "deadline": "2026-12-01", "earlyDays": 0, "note": ""})


def materials():
    return {"documents": [{"id": 7, "ingest_status": "complete"}, {"id": 8, "ingest_status": "complete"}],
            "pages": [{"document_id": 7, "page_number": 12, "filename": "old.pdf", "body": "tree " * 240},
                      {"document_id": 7, "page_number": 15, "filename": "old.pdf", "body": "search " * 120},
                      {"document_id": 8, "page_number": 1, "filename": "new.pdf", "body": "Graph traversal"}],
            "fingerprint": "frozen-materials"}


class PlanningInputsTest(unittest.TestCase):
    def test_explicit_missing_profile_requests_input_before_model_or_note_writes(self):
        with patch.object(planner, "get_course", return_value={"id": 3}), patch.object(
            planner, "get_plan", return_value={"plan": None}
        ), patch.object(planner, "planning_lock", return_value=nullcontext()), patch.object(
            planner, "load_planning_materials"
        ) as pages, patch.object(planner, "save_course_note") as save, patch.object(planner, "_split_pages") as split:
            result = planner.generate_plan(1, 3, "2026-11-12", "2026-11-15", "", profile={"goal": "Pass"})
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual({item["id"] for item in result["questions"]}, {"prior_knowledge", "daily_minutes"})
        pages.assert_not_called()
        save.assert_not_called()
        split.assert_not_called()

    def test_legacy_defaults_and_input_validation_are_explicit(self):
        profile, questions = planning_profile(note="Learn trees")
        self.assertEqual(profile["goal"], "Learn trees")
        self.assertEqual(profile["prior_knowledge"], "Not specified")
        self.assertEqual(profile["daily_minutes"], 60)
        self.assertEqual(questions, [])
        self.assertIn("reading_words_per_minute", profile["assumptions"])
        for value in (True, 0, 1441, 1.5, float("inf"), "30"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                planning_profile({**PROFILE, "daily_minutes": value})

    def test_stale_client_version_does_no_model_or_profile_write(self):
        with patch.object(planner, "get_course", return_value={"id": 3}), patch.object(
            planner, "get_plan", return_value={"plan": sample_plan()}
        ), patch.object(planner, "planning_lock", return_value=nullcontext()), patch.object(
            planner, "save_course_note"
        ) as save, patch.object(planner, "_split_pages") as split:
            with self.assertRaises(plans.PlanConflict):
                planner.generate_plan(1, 3, "2026-11-12", "2026-11-15", "", PROFILE, expected_version=0)
        save.assert_not_called()
        split.assert_not_called()

    def test_requirements_are_read_only_and_do_not_invoke_a_model(self):
        with patch.object(planner, "get_course", return_value={"id": 3}), patch.object(
            planner, "get_plan", return_value={"plan": None}
        ), patch.object(planner, "_split_pages") as split:
            result = planner.planning_requirements(1, 3, {})
        self.assertEqual(len(result["questions"]), 3)
        split.assert_not_called()

    def test_requirements_reuse_a_complete_saved_profile_when_request_omits_it(self):
        previous = sample_plan()
        previous["planning_profile"] = PROFILE
        with patch.object(planner, "get_course", return_value={"id": 3}), patch.object(
            planner, "get_plan", return_value={"plan": previous}
        ):
            result = planner.planning_requirements(1, 3)
            explicit = planner.planning_requirements(1, 3, {})
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["questions"], [])
        self.assertEqual(result["profile"]["goal"], PROFILE["goal"])
        self.assertEqual(explicit["status"], "needs_input")


class WorkloadEstimateTest(unittest.TestCase):
    def test_estimates_use_text_size_and_preserve_every_completed_task_field(self):
        original = sample_plan()
        original["tasks"][0].update({"status": "Completed", "estimated_minutes": 47,
                                      "completed_at": "2026-11-10", "custom": {"historical": True}})
        before = copy.deepcopy(original)
        profile, _ = planning_profile(PROFILE)
        result = estimate_plan(original, materials()["pages"], profile)
        self.assertEqual(original, before)
        self.assertEqual(result["tasks"][0], before["tasks"][0])
        # 240 reading units / 120 units per minute + 2 minutes for one concept.
        self.assertEqual(result["chapters"][0]["estimated_minutes"], 14)
        self.assertEqual(result["tasks"][1]["estimated_minutes"], 6)
        self.assertEqual(result["capacity"]["available_minutes"], 90)
        self.assertIn("not a measured", result["estimate_basis"])

    def test_missing_historical_pages_retain_recorded_chapter_estimate(self):
        original = sample_plan()
        original["chapters"][0]["estimated_minutes"] = 99
        profile, _ = planning_profile(PROFILE)
        result = estimate_plan(original, [], profile)
        self.assertEqual(result["chapters"][0]["estimated_minutes"], 99)
        self.assertEqual(result["chapters"][0]["estimate_details"]["missing_page_count"], 1)

    def test_material_status_distinguishes_new_pages_and_new_documents(self):
        snapshot = materials()
        snapshot["pages"].append({"document_id": 7, "page_number": 16})
        update = material_update(sample_plan(), snapshot["pages"], snapshot["documents"])
        self.assertEqual(update, {"new_page_count": 2, "new_document_ids": [8],
                                  "missing_document_ids": [], "can_update": True})
        update = material_update(sample_plan(), [], [{"id": 8, "ingest_status": "pending"}])
        self.assertEqual(update["missing_document_ids"], [7])
        self.assertFalse(update["can_update"])


class AppendWorkflowTest(unittest.TestCase):
    def test_only_unseen_pages_go_to_upstream_split_under_the_course_lock(self):
        previous = sample_plan()
        previous["tasks"][0].update({"status": "Completed", "completed_at": "2026-11-10", "estimated_minutes": 38})
        old = copy.deepcopy(previous)
        state = {"locked": False}

        @contextmanager
        def lock(*args):
            state["locked"] = True
            try:
                yield
            finally:
                state["locked"] = False

        def split(brief, pages, start, end):
            self.assertTrue(state["locked"])
            self.assertEqual([(p["document_id"], p["page_number"]) for p in pages], [(8, 1)])
            self.assertIn("Basic Python", brief["note"])
            return [{"id": "c1", "title": "New topic", "concepts": ["Graph", "Traversal"],
                     "sources": [{"document_id": 8, "page_number": 1, "filename": "new.pdf"}]}], "New material"

        def save(course_id, plan, new_ids, **kwargs):
            self.assertTrue(state["locked"])
            self.assertEqual(kwargs, {"expected_version": 1, "material_fingerprint": "frozen-materials"})
            self.assertEqual(new_ids, ["new-c1"])
            self.assertEqual(plan["chapters"][:2][0]["id"], "11")
            self.assertEqual(next(t for t in plan["tasks"] if t["id"] == old["tasks"][0]["id"]), old["tasks"][0])
            return plan

        with patch.object(planner, "get_course", return_value={"id": 3}), patch.object(
            planner, "get_plan", return_value={"plan": previous}
        ), patch.object(planner, "planning_lock", side_effect=lock), patch.object(
            planner, "load_planning_materials", side_effect=lambda _: materials()
        ), patch.object(planner, "save_course_note", return_value=BRIEF), patch.object(
            planner, "load_plan_feedback", return_value={}
        ), patch.object(planner, "load_usable_pages", return_value=materials()["pages"]), patch.object(
            planner, "_split_pages", side_effect=split
        ), patch.object(planner, "save_appended_plan", side_effect=save):
            result = planner.generate_plan(1, 3, "2026-11-12", "2026-11-15", "", PROFILE, True, 1)
        self.assertFalse(state["locked"])
        self.assertEqual(previous, old)
        self.assertEqual(result["material_update"]["new_page_count"], 0)


class PersistenceGuardTest(unittest.TestCase):
    def test_unchanged_existing_plan_does_not_insert_when_mysql_affected_rows_is_zero(self):
        current = sample_plan()
        connection, cursor = self.connection(current)
        cursor.fetchone.side_effect = [{"id": 3}, {"id": 17}]
        cursor.rowcount = 0
        with patch.object(plans, "connect", return_value=connection), patch.object(plans, "ensure_plan_storage"):
            plans.save_plan(3, current)
        statements = [" ".join(call.args[0].split()) for call in cursor.execute.call_args_list]
        self.assertFalse(any(sql.startswith("INSERT INTO study_plans") for sql in statements))
        self.assertIn("FROM courses", statements[0])
        self.assertIn("FROM study_plans", statements[1])
        self.assertIn("FOR UPDATE", statements[1])
        self.assertEqual(cursor.execute.call_args.args[1], (json.dumps(current, ensure_ascii=False), 3))
        connection.commit.assert_called_once()
        connection.rollback.assert_not_called()

    def test_missing_plan_row_is_created_with_original_json(self):
        current = sample_plan()
        connection, cursor = self.connection(None)
        cursor.fetchone.side_effect = [{"id": 3}, None]
        with patch.object(plans, "connect", return_value=connection), patch.object(plans, "ensure_plan_storage"):
            plans.save_plan(3, current)
        statements = [" ".join(call.args[0].split()) for call in cursor.execute.call_args_list]
        self.assertEqual(sum(sql.startswith("INSERT INTO study_plans") for sql in statements), 1)
        self.assertFalse(any(sql.startswith("UPDATE study_plans") for sql in statements))
        self.assertEqual(cursor.execute.call_args.args[1], (3, json.dumps(current, ensure_ascii=False)))
        connection.commit.assert_called_once()
        connection.rollback.assert_not_called()

    def connection(self, current):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"plan_json": json.dumps(current)}
        return connection, cursor

    def plan_writes(self):
        current = sample_plan()
        addition = {"id": "new-c1", "title": "New material", "concepts": ["A", "B"],
                    "sources": [{"document_id": 8, "page_number": 1}]}
        appended = copy.deepcopy(current)
        appended["chapters"].append(addition)
        appended["tasks"].extend(planner.schedule_tasks([addition], current["start"], current["end"]))
        return [
            ("generated", None, lambda: plans.save_generated_plan(3, current, expected_version=0, material_fingerprint="same")),
            ("rescheduled", current, lambda: plans.save_rescheduled_plan(3, current, expected_version=1, material_fingerprint="same")),
            ("appended", current, lambda: plans.save_appended_plan(3, appended, ["new-c1"], expected_version=1, material_fingerprint="same")),
            ("completed", current, lambda: plans.complete_task(1, 3, "reading-11")),
            ("legacy_save", current, lambda: plans.save_plan(3, current)),
        ]

    def test_plan_writes_follow_upload_delete_course_first_lock_order(self):
        for name, current, write in self.plan_writes():
            with self.subTest(operation=name):
                connection, cursor = self.connection(current)
                cursor.fetchall.return_value = []
                cursor.lastrowid = 19

                def fetchone():
                    sql = cursor.execute.call_args.args[0]
                    if "FROM courses" in sql:
                        return {"id": 3}
                    if "MAX(position)" in sql:
                        return {"last_position": 2}
                    return {"plan_json": json.dumps(current)}

                def material_snapshot(*args, **kwargs):
                    statements = [call.args[0] for call in cursor.execute.call_args_list]
                    self.assertIn("FROM courses", statements[0])
                    self.assertIn("FOR UPDATE", statements[0])
                    self.assertIn("FROM study_plans", statements[1])
                    return {"fingerprint": "same"}

                cursor.fetchone.side_effect = fetchone
                with patch.object(plans, "connect", return_value=connection), patch.object(
                    plans, "ensure_plan_storage"
                ), patch.object(plans, "get_course", return_value={"id": 3}), patch.object(
                    plans, "_planning_materials", side_effect=material_snapshot
                ), patch.object(plans, "_stamp_document_numbers"), patch.object(
                    plans, "load_planning_materials", return_value=materials()
                ):
                    write()
                self.assertIn("FROM courses", cursor.execute.call_args_list[0].args[0])
                self.assertIn("FOR UPDATE", cursor.execute.call_args_list[0].args[0])
                connection.commit.assert_called_once()

    def test_deleted_course_aborts_every_plan_write_before_other_locks_or_changes(self):
        for name, current, write in self.plan_writes():
            with self.subTest(operation=name):
                connection, cursor = self.connection(current)
                cursor.fetchone.return_value = None
                with patch.object(plans, "connect", return_value=connection), patch.object(
                    plans, "ensure_plan_storage"
                ), patch.object(plans, "get_course", return_value={"id": 3}):
                    with self.assertRaisesRegex(LookupError, "Course not found"):
                        write()
                self.assertEqual(len(cursor.execute.call_args_list), 1)
                self.assertIn("FROM courses", cursor.execute.call_args_list[0].args[0])
                connection.rollback.assert_called_once()
                connection.commit.assert_not_called()

    def test_stale_version_rolls_back_without_writing(self):
        connection, cursor = self.connection(sample_plan())
        with patch.object(plans, "connect", return_value=connection):
            with self.assertRaises(plans.PlanConflict):
                plans.save_rescheduled_plan(3, sample_plan(), expected_version=0)
        connection.rollback.assert_called_once()
        self.assertFalse(any(any(word in call.args[0] for word in ("INSERT", "UPDATE study_plans", "DELETE"))
                             for call in cursor.execute.call_args_list))

    def test_course_lock_is_released_after_model_failure_and_busy_calls_do_not_enter(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"acquired": 1}
        with patch.object(plans, "ensure_plan_storage"), patch.object(plans, "connect", return_value=connection):
            with self.assertRaisesRegex(RuntimeError, "model failed"):
                with plans.planning_lock(1, 3):
                    raise RuntimeError("model failed")
        self.assertIn("GET_LOCK", cursor.execute.call_args_list[0].args[0])
        self.assertIn("RELEASE_LOCK", cursor.execute.call_args_list[-1].args[0])
        connection.close.assert_called_once()
        cursor.reset_mock()
        cursor.fetchone.return_value = {"acquired": 0}
        with patch.object(plans, "ensure_plan_storage"), patch.object(plans, "connect", return_value=connection):
            with self.assertRaisesRegex(RuntimeError, "busy"):
                with plans.planning_lock(1, 3):
                    self.fail("A busy planning call must not run")
        self.assertFalse(any("RELEASE_LOCK" in call.args[0] for call in cursor.execute.call_args_list))

    def test_material_fingerprint_detects_text_changes_and_locks_both_reads(self):
        cursor = MagicMock()
        docs = [{"id": 7, "filename": "old.pdf", "position": 1, "content_hash": "abc", "ingest_status": "complete"}]
        original = [{"document_id": 7, "filename": "old.pdf", "position": 1, "page_number": 12, "body": "Original"}]
        cursor.fetchall.side_effect = [docs, original, docs, [{**original[0], "body": "Changed"}]]
        first = plans._planning_materials(cursor, 3)
        second = plans._planning_materials(cursor, 3, locked=True)
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])
        self.assertTrue(all("FOR UPDATE" in call.args[0] for call in cursor.execute.call_args_list[-2:]))

    def test_get_plan_keeps_metadata_and_sources_of_a_removed_document(self):
        current = sample_plan()
        current["chapters"][0].update({"estimated_minutes": 84, "estimate_basis": "Original estimate"})
        connection, _ = self.connection(current)
        snapshot = {"documents": [], "pages": [], "fingerprint": "empty"}
        with patch.object(plans, "get_course", return_value={"id": 3}), patch.object(
            plans, "ensure_plan_storage"
        ), patch.object(plans, "connect", return_value=connection), patch.object(
            plans, "_planning_materials", return_value=snapshot
        ), patch.object(plans, "_stamp_document_numbers"), patch.object(plans, "_load_chapters") as load:
            result = plans.get_plan(1, 3)
        load.assert_not_called()
        self.assertEqual(result["plan"], current)
        self.assertEqual(result["material_update"]["missing_document_ids"], [7])

    def test_changed_material_rolls_back_before_publication(self):
        connection, cursor = self.connection(sample_plan())
        with patch.object(plans, "connect", return_value=connection), patch.object(
            plans, "_planning_materials", return_value={"fingerprint": "changed"}
        ) as snapshot:
            with self.assertRaisesRegex(plans.PlanConflict, "material changed"):
                plans.save_rescheduled_plan(3, sample_plan(), expected_version=1, material_fingerprint="old")
        snapshot.assert_called_once_with(cursor, 3, locked=True)
        connection.rollback.assert_called_once()
        self.assertEqual(len(cursor.execute.call_args_list), 2)

    def test_append_inserts_only_new_chapters_and_keeps_old_snapshots(self):
        current = sample_plan()
        current["tasks"][0].update({"status": "Completed", "custom": {"unchanged": True}})
        addition = {"id": "new-c1", "title": "New topic", "concepts": ["A", "B"],
                    "sources": [{"document_id": 8, "page_number": 1}]}
        proposed = copy.deepcopy(current)
        proposed["chapters"].append(addition)
        proposed["tasks"].extend(planner.schedule_tasks([addition], "2026-11-12", "2026-11-15"))
        proposed["tasks"][0]["custom"] = {"tampered": True}
        connection, cursor = self.connection(current)
        cursor.fetchone.side_effect = [{"id": 3}, {"plan_json": json.dumps(current)}, {"last_position": 2}, {"id": 17}]
        cursor.lastrowid = 19
        with patch.object(plans, "connect", return_value=connection):
            result = plans.save_appended_plan(3, proposed, ["new-c1"], expected_version=1)
        self.assertEqual(result["chapters"][:2], current["chapters"])
        self.assertEqual(result["chapters"][2]["id"], "19")
        self.assertEqual(result["tasks"][0], current["tasks"][0])
        self.assertEqual(result["version"], 2)
        sql = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertFalse(any("DELETE" in item or "UPDATE plan_" in item for item in sql))
        inserts = [call for call in cursor.execute.call_args_list if "INSERT INTO plan_chapters" in call.args[0]]
        self.assertEqual(len(inserts), 1)
        self.assertEqual(inserts[0].args[1], (3, 3, "New topic"))
        snapshots = [call.args[1] for call in cursor.execute.call_args_list if "INSERT IGNORE INTO plan_versions" in call.args[0]]
        self.assertEqual(json.loads(snapshots[0][-1]), current)
        self.assertEqual(json.loads(snapshots[1][-1]), result)
        connection.commit.assert_called_once()

    def test_completion_creates_two_immutable_snapshots_and_is_idempotent(self):
        current = sample_plan()
        connection, cursor = self.connection(current)
        with patch.object(plans, "get_course", return_value={"id": 3}), patch.object(
            plans, "ensure_plan_storage"
        ), patch.object(plans, "connect", return_value=connection), patch.object(
            plans, "_stamp_document_numbers"
        ), patch.object(plans, "load_planning_materials", return_value=materials()):
            result = plans.complete_task(1, 3, "reading-11")["plan"]
        snapshots = [json.loads(call.args[1][-1]) for call in cursor.execute.call_args_list
                     if "INSERT IGNORE INTO plan_versions" in call.args[0]]
        self.assertEqual(snapshots[0], current)
        self.assertEqual(snapshots[1], result)
        self.assertEqual(result["version"], 2)
        connection, cursor = self.connection(result)
        with patch.object(plans, "get_course", return_value={"id": 3}), patch.object(
            plans, "ensure_plan_storage"
        ), patch.object(plans, "connect", return_value=connection), patch.object(
            plans, "_stamp_document_numbers"
        ), patch.object(plans, "load_planning_materials", return_value=materials()):
            repeated = plans.complete_task(1, 3, "reading-11")["plan"]
        self.assertEqual(repeated, result)
        self.assertFalse(any("INSERT" in call.args[0] or "UPDATE study_plans" in call.args[0]
                             for call in cursor.execute.call_args_list))

    def test_history_reads_are_owned_and_do_not_modify_saved_json(self):
        current = sample_plan()
        connection, cursor = self.connection(current)
        cursor.fetchone.return_value = {"plan_json": json.dumps(current), "created_at": "2026-11-12 12:00:00",
                                       "change_type": "generated"}
        with patch.object(plans, "get_course", return_value={"id": 3}), patch.object(
            plans, "ensure_plan_storage"
        ), patch.object(plans, "connect", return_value=connection), patch.object(plans, "_stamp_document_numbers") as stamp:
            result = plans.get_plan_version(1, 3, 1)
        self.assertTrue(result["read_only"])
        self.assertEqual(result["plan"], current)
        stamp.assert_not_called()
        self.assertTrue(all(call.args[0].strip().startswith("SELECT") for call in cursor.execute.call_args_list))
        with patch.object(plans, "get_course", return_value=None), patch.object(plans, "connect") as connect:
            with self.assertRaises(LookupError):
                plans.get_plan_versions(99, 3)
        connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
