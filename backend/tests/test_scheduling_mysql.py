"""SQL acceptance including model-controlled tool traces on isolated temporary tables."""
import copy
import json
import os
import re
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage

from agent import planner
from agent.scheduler import estimate_times, propose_schedule, today
from db import chapterization, courses, scheduling
from test_plan_sync_mysql import LearningSyncMySQLTest, SharedConnection


class ObservingModel:
    """Test double selects different actions from actual tool observations."""
    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        last = messages[-1]
        value = json.loads(last.content) if last.type == "tool" else {}
        if last.type != "tool":
            name, args = "get_planning_snapshot", {}
        elif "profile" in value:
            name, args = "get_learning_report", {"chapter_id": "4"}
        elif "estimates" in value:
            name, args = "propose_daily_schedule", {"strategy": "new_first"}
        elif "candidate_id" in value:
            name, args = "validate_daily_schedule", {"candidate_id": value["candidate_id"]}
        elif "valid" in value:
            if value["valid"]:
                name, args = "save_schedule", {"candidate_id": "1"}
            else:
                name, args = "request_clarification", {"question": "Increase daily minutes or extend the finish date."}
        else:
            name, args = "estimate_task_time", {}
        return AIMessage(content="", tool_calls=[{"id": str(len(messages)), "name": name, "args": args}])


class ConfusedWeekdayModel(ObservingModel):
    """Reproduces an ungrounded objection after a successful validation."""
    def invoke(self, messages):
        last = messages[-1]
        if last.type == "tool" and json.loads(last.content).get("valid") is True:
            return AIMessage(content="", tool_calls=[{
                "id": str(len(messages)), "name": "request_clarification",
                "args": {"question": "The proposed schedule uses Tuesday, but Tuesday is outside your availability."},
            }])
        return super().invoke(messages)


class SchedulingMySQLTest(LearningSyncMySQLTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        schema = (Path(__file__).resolve().parents[1] / "db/schema.sql").read_text()
        extra = ("pages", "plan_versions", "planner_runs")
        with cls.connection.cursor() as cursor:
            for name in extra:
                body = re.search(rf"CREATE TABLE IF NOT EXISTS {name} \((.*?)\) ENGINE=.*?;", schema, re.S)[1]
                body = "\n".join(line for line in body.splitlines() if not line.strip().startswith("CONSTRAINT ")).rstrip().rstrip(",")
                cursor.execute(f"CREATE TEMPORARY TABLE `{name}` ({body}) ENGINE=InnoDB")
        cls.tables += extra
        for module in (scheduling, chapterization, courses):
            p = patch.object(module, "connect", return_value=SharedConnection(cls.connection))
            p.start(); cls.addClassCleanup(p.stop)
        for module, name in ((scheduling, "ensure_scheduling_storage"), (chapterization, "ensure_chapterization_storage")):
            p = patch.object(module, name)
            p.start(); cls.addClassCleanup(p.stop)

    def setUp(self):
        super().setUp()
        self.end = (date.fromisoformat(today()) + timedelta(days=10)).isoformat()
        self.profile = {"start": today(), "end": self.end, "daily_minutes": 60}
        brief = {"schema": "citepath-course-v1", "deadline": self.end, "earlyDays": 0, "note": "Test"}
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE courses SET student_brief=%s WHERE id=1", (json.dumps(brief),))
            cursor.execute("UPDATE documents SET ingest_status='complete'")
            cursor.execute("INSERT INTO pages (document_id,page_number,body,usable) VALUES (7,1,'merge sort learning material',1),(8,1,'second PDF',1)")
        self.connection.commit()

    def test_repair_missing_tasks_and_preserve_existing(self):
        with self.connection.cursor() as cursor:
            broken = copy.deepcopy(self.original)
            broken["tasks"] = broken["tasks"][:1]
            cursor.execute("UPDATE study_plans SET plan_json=%s", (json.dumps(broken),))
        self.connection.commit()
        self.assertEqual(scheduling.repair_tasks(10, 1, True)["added"], 1)
        self.assertEqual(len(self.stored()["tasks"]), 1)
        self.assertEqual(scheduling.repair_tasks(10, 1)["added"], 1)
        self.assertEqual(scheduling.repair_tasks(10, 1)["added"], 0)
        self.assertEqual(self.stored()["tasks"][0], broken["tasks"][0])

    def test_agent_chooses_tools_and_publishes_once(self):
        response = planner.run_planner(10, 1, "agent-success", self.profile, model=ObservingModel())
        self.assertEqual(response["status"], "saved", response)
        names = [s["tool"] for s in response["trace"]]
        self.assertIn("get_learning_report", names)
        self.assertEqual(response["summary"]["strategy_source"], "model")
        self.assertEqual(response["summary"]["strategy"], "new_first")
        self.assertLess(names.index("validate_daily_schedule"), names.index("save_schedule"))
        stored = self.stored()
        replay = planner.run_planner(10, 1, "agent-success", self.profile, model=ObservingModel())
        self.assertEqual(replay, response)
        self.assertEqual(self.stored(), stored)
        self.assertEqual(len(stored["tasks"]), 2)

    def test_review_is_scheduled_on_failure_and_completed_on_retake(self):
        start = date.fromisoformat(today())
        first_available = (start + timedelta(days=1)).isoformat()
        profile = {**self.profile, "off_dates": [start.isoformat()]}
        response = planner.run_planner(10, 1, "schedule-before-exam", profile, mode="baseline")
        self.assertEqual(response["status"], "saved", response)
        before = self.stored()
        self.assertEqual(len(before["tasks"]), 2)
        before_workflow = scheduling.workflow_status(10, 1)
        self.assertEqual(before_workflow["estimated_minutes"], 15)

        exam = self.start_exam()
        self.finish_exam(exam, False)
        failed = self.stored()
        review = failed["tasks"][2]
        self.assertEqual(review["id"], "review-4")
        self.assertEqual(review["schedule"], [{"date": first_available, "minutes": 5}])
        self.assertEqual(failed["tasks"][:2], before["tasks"])
        self.assertEqual(failed["version"], before["version"])
        failed_workflow = scheduling.workflow_status(10, 1)
        self.assertEqual(failed_workflow["tasks"], 3)
        self.assertEqual(failed_workflow["estimated_minutes"], 20)
        self.finish_exam(exam, False)
        self.assertEqual(self.stored(), failed)

        self.finish_exam(self.start_exam(), True)
        passed = self.stored()
        self.assertEqual(passed["tasks"][2]["status"], "Completed")
        self.assertEqual(passed["tasks"][2]["schedule"], review["schedule"])
        self.assertEqual(passed["version"], before["version"])

    def test_review_stays_unscheduled_when_available_time_is_used(self):
        profile = {**self.profile, "end": today(), "daily_minutes": 15}
        response = planner.run_planner(10, 1, "full-calendar", profile, mode="baseline")
        self.assertEqual(response["status"], "saved", response)
        before = self.stored()
        self.finish_exam(self.start_exam(), False)
        failed = self.stored()
        self.assertEqual(failed["tasks"][:2], before["tasks"])
        self.assertEqual(failed["tasks"][2]["date"], "")
        self.assertEqual(failed["tasks"][2]["schedule"], [])
        workflow = scheduling.workflow_status(10, 1)
        self.assertEqual(workflow["tasks"], 3)
        self.assertEqual(workflow["unscheduled"], 1)

    def test_weak_schedule_explanation_uses_latest_exam_and_actual_slots(self):
        second = self.add_second_chapter()
        self.finish_exam(self.start_exam(), False)
        profile = {**self.profile, "strategy": "weak_first", "daily_minutes": 10}
        result = planner.run_planner(10, 1, "evidence-based-order", profile, mode="baseline")
        self.assertEqual(result["status"], "saved", result)
        summary = result["summary"]
        self.assertIn("Sorting (latest exam not passed)", summary["reason"])
        self.assertEqual(summary["strategy_source"], "preference")

        tasks = self.stored()["tasks"]
        other_start = min(task["date"] for task in tasks if task["chapterId"] == second)
        review = next(task for task in tasks if task["kind"] == "Review")
        self.assertLessEqual(review["date"], other_start)
        self.assertIn({"task_id": review["id"], "title": review["title"],
                       "before": [], "after": review["schedule"]}, summary["changes"])

    def test_infeasible_schedule_stops_before_model_call(self):
        profile = {**self.profile, "end": today(), "daily_minutes": 1}
        before = self.stored()
        with patch("agent.planner.chat_model") as model:
            response = planner.run_planner(10, 1, "agent-capacity", profile)
        model.assert_not_called()
        self.assertEqual(response["status"], "needs_input", response)
        self.assertEqual([step["tool"] for step in response["trace"]], ["check_study_capacity"])
        self.assertEqual(response["budget"], {
            "study_days": 1, "required_minutes": 15, "available_minutes": 1, "shortfall_minutes": 14,
        })
        self.assertIn("Short by 14 min", response["message"])
        self.assertEqual(self.stored()["version"], before["version"])

    def test_overdue_uses_last_slot_and_supports_legacy_tasks(self):
        early = (date.fromisoformat(today()) - timedelta(days=1)).isoformat()
        plan = self.stored()
        plan["tasks"][0].update(date=early, schedule=[
            {"date": today(), "minutes": 2}, {"date": early, "minutes": 3},
        ])
        plan["tasks"][1]["date"] = early
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE study_plans SET plan_json=%s", (json.dumps(plan),))
        self.connection.commit()

        workflow = scheduling.workflow_status(10, 1)
        self.assertEqual(workflow["overdue"], 1)
        self.assertEqual(workflow["unscheduled"], 0)

    def test_learning_change_rejects_stale_candidate(self):
        scheduling.save_requirements(10, 1, self.profile)
        context = scheduling.get_context(10, 1)
        estimates = estimate_times(context["plan"], context["page_text"], context["reports"])
        from agent.scheduler import requirements
        profile = requirements(self.profile, context["brief"])
        candidate = propose_schedule(context["plan"], profile, estimates, {})
        run_id, _ = scheduling.claim_run(10, 1, "stale")
        from db.plans import complete_read_task
        complete_read_task(10, 1, "reading-4")
        with self.assertRaises(chapterization.ChapterizationConflict):
            scheduling.publish_schedule(10, 1, run_id, context["token"], profile, candidate)
        self.assertEqual(self.stored()["tasks"][0]["completion_source"], "student")

    def test_incremental_chapters_create_tasks_preserve_old_work_and_lock(self):
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE documents SET chapter_plan_status='unplanned' WHERE id=8")
        self.connection.commit()
        state = chapterization.prepare_chapterization(10, 1)
        before = copy.deepcopy(state["plan"]["tasks"])
        result = chapterization.save_document_chapters(10, 1, [8], False, state["token"], [
            {"title": "Second", "concepts": ["One", "Two"], "sources": [{"document_id": 8, "page_number": 1}]}
        ], "New PDF")
        self.assertEqual(result["plan"]["tasks"][:2], before)
        self.assertEqual(len(result["plan"]["tasks"]), 4)
        self.assertTrue(all(not t["date"] for t in result["plan"]["tasks"][2:]))
        from db.plans import complete_read_task
        complete_read_task(10, 1, "reading-4")
        options = chapterization.chapterization_options(10, 1)
        self.assertIn(7, [d["id"] for d in options["blocked_documents"]])

    def test_model_failure_never_silently_uses_baseline(self):
        class FailedModel:
            def bind_tools(self, tools):
                raise RuntimeError("test provider failure")
        response = planner.run_planner(10, 1, "failure", self.profile, model=FailedModel())
        self.assertEqual(response["status"], "failed")
        self.assertEqual(self.stored()["version"], self.original["version"])

    def test_baseline_preserves_completed_task_and_records_history(self):
        from db.plans import complete_read_task
        complete_read_task(10, 1, "reading-4")
        read = copy.deepcopy(self.stored()["tasks"][0])
        response = planner.run_planner(10, 1, "baseline", self.profile, mode="baseline")
        self.assertEqual(response["status"], "saved", response)
        self.assertEqual(self.stored()["tasks"][0], read)
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM plan_versions")
            self.assertGreaterEqual(cursor.fetchone()["n"], 2)

    def test_same_schedule_reuses_version_even_for_old_plan_format(self):
        first = planner.run_planner(10, 1, "first", self.profile, mode="baseline")
        self.assertEqual(first["status"], "saved", first)
        self.assertFalse(first["unchanged"])
        old_plan = self.stored()
        old_plan.pop("schedule_strategy")
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE study_plans SET plan_json=%s", (json.dumps(old_plan),))
        self.connection.commit()
        history = scheduling.plan_history(10, 1)

        repeated = planner.run_planner(10, 1, "same-schedule", self.profile, mode="baseline")
        self.assertEqual(repeated["status"], "saved", repeated)
        self.assertTrue(repeated["unchanged"])
        self.assertEqual(repeated["version"], first["version"])
        self.assertEqual(self.stored(), old_plan)
        self.assertEqual(scheduling.plan_history(10, 1), history)
        self.assertEqual(planner.run_planner(10, 1, "same-schedule", self.profile, mode="baseline"), repeated)

        changed = planner.run_planner(10, 1, "new-settings", {**self.profile, "daily_minutes": 90}, mode="baseline")
        self.assertEqual(changed["status"], "saved", changed)
        self.assertEqual(changed["summary"]["changes"], [])
        self.assertFalse(changed["unchanged"])
        self.assertEqual(changed["version"], first["version"] + 1)

    def test_preview_only_publishes_after_confirmation_and_can_be_retried(self):
        from fastapi import HTTPException
        from main import CourseSettingsBody, ScheduleBody, apply_course_schedule, schedule_course, update_settings

        user = {"id": 10}
        scheduling.repair_tasks(10, 1)
        settings = dict(startDate=self.profile["start"], name="Test", deadline=self.end,
                        scheduling_profile=self.profile, scheduling_mode="baseline")
        with patch("main.get_course", return_value={"id": 1}):
            update_settings(1, CourseSettingsBody(**settings), user)
        with self.assertRaises(HTTPException) as invalid:
            update_settings(1, CourseSettingsBody(**{
                **settings, "name": "Should roll back", "scheduling_mode": "agent",
                "scheduling_profile": {**self.profile, "priority_chapter_ids": ["999"]},
            }), user)
        self.assertEqual(invalid.exception.status_code, 400)
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT name FROM courses WHERE id=1")
            self.assertEqual(cursor.fetchone()["name"], "Test")
        previous = self.stored()
        history = scheduling.plan_history(10, 1)
        request = ScheduleBody(request_id="review-schedule", preview=True)
        preview = schedule_course(1, request, user)
        self.assertEqual(preview["status"], "preview", preview)
        self.assertEqual(preview["mode"], "baseline")
        self.assertNotIn("_draft", preview)
        self.assertNotIn("_draft", scheduling.recent_runs(10, 1)[0]["result"])
        self.assertEqual(previous, self.stored())
        self.assertEqual(history, scheduling.plan_history(10, 1))
        self.assertEqual(schedule_course(1, request, user), preview)

        applied = apply_course_schedule(1, preview["run_id"], user)
        self.assertEqual(applied["status"], "saved")
        self.assertEqual(applied["version"], previous["version"] + 1)
        self.assertEqual(applied["summary"], preview["summary"])
        self.assertEqual(applied, apply_course_schedule(1, preview["run_id"], user))
        self.assertEqual(self.stored()["version"], applied["version"])
        same = schedule_course(1, ScheduleBody(request_id="same-preview", preview=True), user)
        self.assertTrue(same["unchanged"])
        self.assertEqual(self.stored()["version"], applied["version"])

    def test_logging_study_time_invalidates_preview_without_changing_plan_dates(self):
        from db.plans import complete_read_task
        from fastapi import HTTPException
        from main import ScheduleBody, StudyTimeBody, apply_course_schedule, save_task_study_time, schedule_course

        user = {"id": 10}
        scheduling.repair_tasks(10, 1)
        scheduling.save_requirements(10, 1, self.profile, mode="baseline")
        complete_read_task(10, 1, "reading-4")
        before = self.stored()
        preview = schedule_course(1, ScheduleBody(request_id="before-log", preview=True), user)
        self.assertEqual(preview["status"], "preview", preview)

        with self.assertRaises(HTTPException) as incomplete:
            save_task_study_time(1, "practice-4", StudyTimeBody(minutes=8), user)
        self.assertEqual(incomplete.exception.status_code, 400)
        saved = save_task_study_time(1, "reading-4", StudyTimeBody(minutes=14), user)
        edited = save_task_study_time(1, "reading-4", StudyTimeBody(minutes=12), user)
        self.assertEqual(edited, {**saved, "minutes": 12})
        with self.assertRaises(HTTPException) as stale:
            apply_course_schedule(1, preview["run_id"], user)
        self.assertEqual(stale.exception.status_code, 409)
        old_schedule = self.stored()
        self.assertEqual(old_schedule["tasks"][0].pop("study_time"), edited)
        self.assertEqual(old_schedule, before)

    def test_logged_time_updates_forecast_before_it_updates_calendar(self):
        from db.plans import complete_read_task

        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE documents SET chapter_plan_status='unplanned' WHERE id=8")
        self.connection.commit()
        state = chapterization.prepare_chapterization(10, 1)
        chapterization.save_document_chapters(10, 1, [8], False, state["token"], [
            {"title": title, "concepts": ["One", "Two"], "sources": [{"document_id": 8, "page_number": 1}]}
            for title in ("A", "B", "C")
        ], "New material")
        reading = [task["id"] for task in self.stored()["tasks"] if task["kind"] == "Reading"]
        for task_id in reading[:3]:
            complete_read_task(10, 1, task_id)
        first = planner.run_planner(10, 1, "published-before-learning-time", self.profile, mode="baseline")
        self.assertEqual(first["status"], "saved", first)
        old = next(task for task in self.stored()["tasks"] if task["id"] == reading[3])
        before = scheduling.workflow_status(10, 1)["estimated_minutes"]

        for task_id in reading[:3]:
            recorded = scheduling.record_study_time(10, 1, task_id, 1)
            scheduling.record_study_time(10, 1, task_id, 2 * recorded["base_minutes"])
        current = scheduling.workflow_status(10, 1)
        self.assertEqual(current["study_time_samples"], {"Reading": 3})
        self.assertEqual(current["estimated_minutes"], before + old["estimated_minutes"])
        self.assertEqual(next(task for task in self.stored()["tasks"] if task["id"] == reading[3]), old)

        preview = planner.run_planner(10, 1, "adjust-time", preview=True)
        self.assertEqual(preview["status"], "preview", preview)
        self.assertEqual(self.stored()["version"], first["version"])
        scheduling.publish_schedule(10, 1, preview["run_id"], apply=True)
        adjusted = next(task for task in self.stored()["tasks"] if task["id"] == reading[3])
        self.assertEqual(adjusted["estimated_minutes"], 2 * old["estimated_minutes"])

    def test_workflow_budget_and_published_plan_use_current_practice_mastery(self):
        from db.practice import create_session

        chapter_id = self.add_second_chapter()
        create_session(10, 1, {"id": int(chapter_id), "title": "Second"})
        before = scheduling.workflow_status(10, 1)["estimated_minutes"]
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id FROM plan_concepts WHERE chapter_id=%s ORDER BY id LIMIT 1", (chapter_id,))
            concept_id = cursor.fetchone()["id"]
            cursor.execute("INSERT INTO concept_progress (user_id,concept_id,level,streak) VALUES (10,%s,2,2)", (concept_id,))
        self.connection.commit()
        budget = scheduling.workflow_status(10, 1)["estimated_minutes"]
        self.assertEqual(budget, before - 6)

        result = planner.run_planner(10, 1, "practice-budget", self.profile, mode="baseline")
        self.assertEqual(result["status"], "saved", result)
        self.assertEqual(result["trace"][0]["observation"]["required_minutes"], budget)
        practice = next(task for task in self.stored()["tasks"] if task["id"] == f"practice-{chapter_id}")
        self.assertEqual(practice["estimated_minutes"], 6)

    def add_second_chapter(self):
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE documents SET chapter_plan_status='unplanned' WHERE id=8")
        self.connection.commit()
        state = chapterization.prepare_chapterization(10, 1)
        response = chapterization.save_document_chapters(10, 1, [8], False, state["token"], [
            {"title": "Second", "concepts": ["One", "Two"], "sources": [{"document_id": 8, "page_number": 1}]},
        ], "New PDF")
        return next(chapter["id"] for chapter in response["plan"]["chapters"] if chapter["title"] == "Second")

    def test_upload_and_replan_reschedules_all_pending_work_only(self):
        from db.plans import complete_read_task
        from main import ScheduleBody, schedule_course

        initial = planner.run_planner(10, 1, "initial", self.profile, mode="baseline")
        self.assertEqual(initial["status"], "saved", initial)
        complete_read_task(10, 1, "reading-4")
        completed = next(t for t in self.stored()["tasks"] if t["id"] == "reading-4")
        new_chapter = self.add_second_chapter()
        saved_profile, mode = scheduling.saved_schedule_preferences(10, 1)
        self.assertEqual(mode, "baseline")
        self.assertTrue(any(not t["date"] for t in self.stored()["tasks"] if t["chapterId"] == new_chapter))

        later = (date.fromisoformat(today()) + timedelta(days=1)).isoformat()
        scheduling.save_requirements(10, 1, {**saved_profile, "start": later})
        response = schedule_course(1, ScheduleBody(request_id="replan"), {"id": 10})
        self.assertEqual(response["status"], "saved", response)
        self.assertEqual(response["mode"], "baseline")
        summary = response["summary"]
        self.assertEqual(summary["strategy_source"], "rules")
        self.assertEqual(summary["first_date"], later)
        self.assertEqual(summary["completed_preserved"], 1)
        self.assertEqual(sum(not item["before"] for item in summary["changes"]), 2)
        self.assertEqual(sum(bool(item["before"]) for item in summary["changes"]), 1)
        for task in self.stored()["tasks"]:
            if task["id"] == "reading-4":
                self.assertEqual(task, completed)
            else:
                self.assertGreaterEqual(task["date"], later)

    def test_delete_material_updates_plan_and_priorities_with_history(self):
        from db.plans import complete_read_task

        new_chapter = self.add_second_chapter()
        profile = {**self.profile, "priority_chapter_ids": ["4", new_chapter]}
        response = planner.run_planner(10, 1, "prioritized", profile, mode="baseline")
        self.assertEqual(response["status"], "saved", response)

        # Completion happens after the published version was archived.
        self.assertEqual(complete_read_task(10, 1, "reading-4")["status"], "ready")
        read = next(task for task in self.stored()["tasks"] if task["id"] == "reading-4")

        with (
            patch.object(courses, "connect", return_value=SharedConnection(self.connection)),
            patch.object(courses, "ensure_document_numbers"),
            patch("db.pdf_store.delete_pdf"),
        ):
            courses.delete_document_rows(10, 1, 7)

        active = self.stored()
        self.assertEqual([c["id"] for c in active["chapters"]], [new_chapter])
        self.assertEqual({t["chapterId"] for t in active["tasks"]}, {new_chapter})
        self.assertEqual(active["scheduling_profile"]["priority_chapter_ids"], [new_chapter])
        prefs, mode = scheduling.saved_schedule_preferences(10, 1)
        self.assertEqual(prefs["priority_chapter_ids"], [new_chapter])
        self.assertEqual(mode, "baseline")
        self.assertEqual(active["chapters"][0]["sources"][0]["position"], 1)
        history = scheduling.historical_plan(10, 1, response["version"])["plan"]
        self.assertIn(read, history["tasks"])
        self.assertEqual(self.stored(), active)

    def test_repair_cleans_chapters_from_older_document_deletion(self):
        with self.connection.cursor() as cursor:
            cursor.execute("DELETE FROM plan_chapter_pages WHERE document_id=7")
            cursor.execute("DELETE FROM pages WHERE document_id=7")
            cursor.execute("DELETE FROM documents WHERE id=7")
        self.connection.commit()
        scheduling.repair_tasks(10, 1)
        active = self.stored()
        self.assertEqual(active["chapters"], [])
        self.assertEqual(active["tasks"], [])
        scheduling.repair_tasks(10, 1)
        self.assertEqual(self.stored(), active)

    def test_false_weekday_objection_does_not_block_verified_plan(self):
        start = date.fromisoformat(today())
        start += timedelta(days=(-start.weekday()) % 7)
        finish = (start + timedelta(days=14)).isoformat()
        tuesday = (start + timedelta(days=1)).isoformat()
        brief = {"schema": "citepath-course-v1", "deadline": finish, "earlyDays": 0, "note": "Test"}
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE courses SET student_brief=%s WHERE id=1", (json.dumps(brief),))
        self.connection.commit()

        for include_tuesday, weekdays in [(True, [0, 1, 4, 5, 6]), (False, [0, 4, 5, 6])]:
            with self.subTest(include_tuesday=include_tuesday):
                profile = {
                    "start": start.isoformat(), "end": finish,
                    "daily_minutes": 5, "weekdays": weekdays,
                }
                response = planner.run_planner(
                    10, 1, f"false-weekday-{include_tuesday}", profile, model=ConfusedWeekdayModel(),
                )
                self.assertEqual(response["status"], "saved", response)
                names = [step["tool"] for step in response["trace"]]
                self.assertLess(names.index("request_clarification"), names.index("save_schedule"))
                self.assertEqual(next(step["source"] for step in response["trace"] if step["tool"] == "save_schedule"), "system")
                self.assertEqual(response["summary"]["strategy_source"], "model")
                dates = {slot["date"] for task in self.stored()["tasks"] for slot in task["schedule"]}
                self.assertEqual(tuesday in dates, include_tuesday)
                self.assertTrue(all(date.fromisoformat(day).weekday() in weekdays for day in dates))
                self.assertEqual(self.stored()["scheduling_profile"]["weekdays"], weekdays)

    def test_recheck_uses_the_explicit_order_if_the_model_used_another(self):
        profile = {**self.profile, "strategy": "chapter_order"}
        response = planner.run_planner(10, 1, "recheck-order", profile, model=ObservingModel())
        self.assertEqual(response["status"], "saved", response)
        proposals = [step["observation"]["strategy"] for step in response["trace"]
                     if step["tool"] == "propose_daily_schedule"]
        self.assertEqual(proposals, ["new_first", "chapter_order"])
        self.assertEqual(response["summary"]["strategy_source"], "preference")
        self.assertIn("chapter_order", self.stored()["reason"])
