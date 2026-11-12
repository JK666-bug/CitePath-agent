"""Explicit local SQL storage smoke; authored fixtures are not model evidence.

Run only after the repository schema is initialized. All application rows created
by this script belong to its new dedicated account/course. They are retained.
No model, Milvus, lecture upload, existing account/course or external file is used.
"""
import argparse
import copy
import json
import os
import secrets
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORK = REPO.parent
BACKEND = REPO / "backend"
OUTPUT = BACKEND / "logs/database-storage.json"
sys.path.insert(0, str(BACKEND))


def now():
    return datetime.now(timezone.utc).isoformat()


def json_value(value):
    return json.loads(value) if isinstance(value, (str, bytes, bytearray)) else value


def write_report(path, report):
    path = Path(path).resolve()
    if WORK.parent.resolve() not in path.parents:
        raise ValueError("Output must stay inside this workspace")
    if REPO / "evaluation_assets" in path.parents:
        raise ValueError("Runtime outputs must stay outside protected evaluation assets")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def run(output):
    report = {
        "schema": "citepath-database-storage-smoke-v1", "started_at": now(),
        "status": "running", "database_real": True, "controller_fixture": True,
        "authored_questions_and_grades": True, "model_invoked": False,
        "milvus_mutated": False, "formal_evaluation_run": False,
        "official_accepted": None, "data_retained": True, "cleanup_performed": False,
        "checks": [], "resources": {},
        "limits": [
            "This verifies actual SQL storage using explicitly authored controller fixtures.",
            "It does not verify question generation, model grading, citation support or learning outcomes.",
            "It does not upload PDFs, mutate Milvus or restart the database container.",
            "Application process restart and database-volume restart durability remain separate checks.",
        ],
    }
    stage = "local_configuration"

    def passed(name, **detail):
        report["checks"].append({"name": name, "passed": True, **detail})
        write_report(output, report)

    try:
        from dotenv import load_dotenv
        load_dotenv(BACKEND / ".env", override=False)
        if os.environ.get("MYSQL_HOST", "127.0.0.1") not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("local_mysql_required")
        if os.environ.get("MYSQL_DATABASE", "citepath_agent") != "citepath_agent":
            raise ValueError("dedicated_project_database_required")

        import pymysql
        from db.connection import connect
        from db import auth, courses, exams, plans, practice, uploads

        def query(sql, parameters=()):
            connection = connect()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(sql, parameters)
                    return list(cursor.fetchall())
            finally:
                connection.close()

        stage = "ensure_storage"
        for ensure in (uploads.ensure_document_numbers, plans.ensure_plan_storage,
                       practice.ensure_practice_storage, exams.ensure_exam_storage):
            ensure()
        columns = query(
            "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN "
            "('documents','practice_sessions','practice_answers','exam_answers','plan_versions')"
        )
        fields = {(row["TABLE_NAME"], row["COLUMN_NAME"]): row for row in columns}
        assert fields[("documents", "position")]["IS_NULLABLE"] == "YES"
        for name in ("is_active", "removed_at", "ingest_error"):
            assert ("documents", name) in fields
        assert fields[("practice_sessions", "passing_threshold")]["DATA_TYPE"] == "varchar"
        for table in ("practice_answers", "exam_answers"):
            for name in ("explanation_status", "explanation_error", "explanation_attempts", "rubric_hits_json"):
                assert (table, name) in fields
        for name in ("draft_json", "round_results_json", "workflow_version"):
            assert ("practice_sessions", name) in fields
        passed("production_storage_initializers_and_required_columns")

        stage = "create_scoped_fixture"
        username = "citepath_it_sql_" + secrets.token_hex(7)
        user = auth.register_user(username, secrets.token_urlsafe(24))
        uid = int(user["id"])
        report["resources"].update(user_id=uid, username=username)
        course = courses.create_course(uid, "Authored SQL storage fixture — not a lecture", "Controller fixture; no model-quality evidence")
        cid = int(course["id"])
        report["resources"]["course_id"] = cid
        assert courses.get_course(uid, cid)["id"] == cid
        passed("dedicated_fixture_account_and_course_created")

        # No source document is invented. These deterministic rows exist solely
        # to exercise SQL persistence, independent of model-generated content.
        authored = {
            "version": 1, "reason": "Authored controller fixture; not a generated learning plan",
            "chapters": [{"id": "fixture-c1", "title": "SQL fixture chapter", "concepts": ["Fixture concept"], "sources": []}],
            "tasks": [
                {"id": "read-fixture-c1", "chapterId": "fixture-c1", "kind": "Read", "date": "2026-11-13", "status": "Scheduled", "sources": []},
                {"id": "practice-fixture-c1", "chapterId": "fixture-c1", "kind": "Practice", "date": "2026-11-14", "status": "Scheduled", "sources": []},
            ],
        }
        stage = "plan_persistence"
        saved = plans.save_generated_plan(cid, authored, expected_version=0)
        chapter_id = int(saved["chapters"][0]["id"])
        concept = query("SELECT id, name FROM plan_concepts WHERE chapter_id = %s ORDER BY position", (chapter_id,))[0]
        concept_id = int(concept["id"])
        report["resources"].update(chapter_id=chapter_id, concept_id=concept_id)
        initial_snapshot = plans.get_plan_version(uid, cid, 1)["plan"]
        assert plans.get_plan(uid, cid)["plan"] == saved
        passed("authored_plan_and_mapped_ids_persist_across_connections")

        stage = "named_lock_exclusion"
        lock_fixtures = [
            ("practice", f"citepath:practice:{uid}:{cid}:{chapter_id}", lambda: practice.practice_lock(uid, cid, chapter_id)),
            ("planning", f"citepath:plan:{uid}:{cid}", lambda: plans.planning_lock(uid, cid)),
        ]
        class ControlledFailure(Exception):
            pass
        for label, name, context in lock_fixtures:
            second = connect()
            try:
                with second.cursor() as cursor:
                    with context():
                        cursor.execute("SELECT GET_LOCK(%s, 0) AS acquired", (name,))
                        assert cursor.fetchone()["acquired"] == 0
                    cursor.execute("SELECT GET_LOCK(%s, 0) AS acquired", (name,))
                    assert cursor.fetchone()["acquired"] == 1
                    cursor.execute("SELECT RELEASE_LOCK(%s) AS released", (name,))
                    assert cursor.fetchone()["released"] == 1
                    try:
                        with context():
                            raise ControlledFailure()
                    except ControlledFailure:
                        pass
                    cursor.execute("SELECT GET_LOCK(%s, 0) AS acquired", (name,))
                    assert cursor.fetchone()["acquired"] == 1
                    cursor.execute("SELECT RELEASE_LOCK(%s)", (name,))
            finally:
                second.close()
            passed(label + "_lock_excludes_independent_connection_and_releases_after_exception")

        stage = "practice_fixture"
        session_id = practice.create_session(uid, cid, {"id": chapter_id, "title": "Authored SQL fixture"}, "0.795")
        report["resources"]["practice_session_id"] = session_id
        bank = [
            {"concept_id": concept_id, "concept_name": concept["name"], "kind": "mcq", "prompt": "Authored storage probe: choose A", "options": ["A", "B", "C", "D"], "answer": "A", "rubric": [], "sources": []},
            {"concept_id": concept_id, "concept_name": concept["name"], "kind": "short", "prompt": "Authored storage probe: no semantic assessment", "options": [], "answer": "Fixture", "rubric": ["Fixture point"], "sources": []},
        ]
        practice.store_round(session_id, 1, bank)
        original_questions = query("SELECT * FROM practice_questions WHERE session_id = %s ORDER BY position", (session_id,))
        changed = copy.deepcopy(bank)
        changed[0]["prompt"] = "This replacement must not be published"
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(practice.store_round, session_id, 1, changed) for _ in range(2)]
            for future in futures:
                future.result(timeout=15)
        assert query("SELECT * FROM practice_questions WHERE session_id = %s ORDER BY position", (session_id,)) == original_questions
        passed("saved_round_is_reused_and_concurrent_replacement_does_not_overwrite_questions")

        stage = "draft_persistence"
        question_ids = [int(row["id"]) for row in original_questions]
        drafts = {str(question_ids[0]): "A", str(question_ids[1]): "SQL 持久化夹具 🧪"}
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(practice.save_draft, session_id, int(identifier), response) for identifier, response in drafts.items()]
            for future in futures:
                future.result(timeout=15)
        reopened = practice.get_owned_session(uid, cid, session_id)
        assert reopened["drafts"] == drafts
        assert str(reopened["passing_threshold"]) == "0.795"
        passed("concurrent_draft_updates_and_exact_threshold_persist_on_new_connection")

        stage = "answer_uniqueness"
        practice.save_answer(question_ids[0], "A", True, 1, 1, "", [])
        original_answer = query("SELECT * FROM practice_answers WHERE question_id = %s", (question_ids[0],))
        duplicate_rejected = False
        try:
            practice.save_answer(question_ids[0], "B", False, 0, 1, "A duplicate must not replace the fixture", [])
        except pymysql.err.IntegrityError as error:
            assert error.args[0] == 1062
            duplicate_rejected = True
        assert duplicate_rejected
        assert query("SELECT * FROM practice_answers WHERE question_id = %s", (question_ids[0],)) == original_answer
        passed("unique_answer_constraint_rejects_duplicate_without_overwriting_original")

        stage = "progress_and_plan_history"
        practice.save_progress(uid, concept_id, 1, 2)
        progress_before = query("SELECT * FROM concept_progress WHERE user_id = %s AND concept_id = %s", (uid, concept_id))
        complete = plans.complete_task(uid, cid, saved["tasks"][0]["id"])["plan"]
        assert complete["version"] == 2 and complete["tasks"][0]["status"] == "Completed"
        completed_task = copy.deepcopy(complete["tasks"][0])
        proposed = copy.deepcopy(complete)
        proposed["reason"] = "Authored reschedule fixture"
        proposed["tasks"][0].update(status="Scheduled", date="2026-11-20")
        proposed["tasks"][1]["date"] = "2026-11-20"
        revised = plans.save_rescheduled_plan(cid, proposed, expected_version=2)
        assert revised["version"] == 3 and revised["tasks"][0] == completed_task
        assert revised["chapters"] == saved["chapters"]
        assert plans.get_plan_version(uid, cid, 1)["plan"] == initial_snapshot
        assert query("SELECT * FROM concept_progress WHERE user_id = %s AND concept_id = %s", (uid, concept_id)) == progress_before
        passed("completed_tasks_chapter_ids_progress_and_original_version_survive_rescheduling")

        stage = "stale_plan_write"
        before_stale = query("SELECT plan_json FROM study_plans WHERE course_id = %s", (cid,))
        stale_rejected = False
        try:
            plans.save_rescheduled_plan(cid, copy.deepcopy(revised), expected_version=1)
        except plans.PlanConflict:
            stale_rejected = True
        assert stale_rejected
        assert query("SELECT plan_json FROM study_plans WHERE course_id = %s", (cid,)) == before_stale
        assert [row["version"] for row in plans.get_plan_versions(uid, cid)["versions"]] == [3, 2, 1]
        passed("stale_version_rolls_back_without_changing_current_plan_or_snapshots")

        stage = "competing_plan_writes"
        def competing_write(number):
            candidate = copy.deepcopy(revised)
            candidate["reason"] = f"Authored competing writer {number}"
            try:
                return ("saved", plans.save_rescheduled_plan(cid, candidate, expected_version=3)["version"])
            except plans.PlanConflict:
                return ("conflict", None)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(competing_write, number) for number in (1, 2)]
            outcomes = [future.result(timeout=15) for future in futures]
        assert sorted(item[0] for item in outcomes) == ["conflict", "saved"]
        assert next(item[1] for item in outcomes if item[0] == "saved") == 4
        assert plans.get_plan_version(uid, cid, 1)["plan"] == initial_snapshot
        assert [row["version"] for row in plans.get_plan_versions(uid, cid)["versions"]] == [4, 3, 2, 1]
        passed("competing_same_version_writers_publish_once_and_preserve_all_history")

        stage = "unchanged_legacy_plan_save"
        same_plan = plans.get_plan(uid, cid)["plan"]
        versions_before = plans.get_plan_versions(uid, cid)
        plans.save_plan(cid, same_plan)
        plans.save_plan(cid, same_plan)
        assert plans.get_plan(uid, cid)["plan"] == same_plan
        assert plans.get_plan_versions(uid, cid) == versions_before
        passed("unchanged_legacy_plan_save_is_idempotent_and_preserves_versions")

        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["failure"] = {"stage": stage, "type": type(error).__name__}
        # Provider/driver exceptions may contain configuration details. Keep only
        # the stable stage and exception type in this shareable report.
    report["finished_at"] = now()
    write_report(output, report)
    print(json.dumps({"status": report["status"], "checks_passed": len(report["checks"]),
                      "controller_fixture": True, "model_invoked": False,
                      "output": str(output), "failure": report.get("failure")}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Create a new dedicated SQL fixture account/course and retain its data")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    arguments = parser.parse_args()
    if not arguments.run:
        print(json.dumps({"status": "not_run", "explicit_run_flag_required": True, "database_mutated": False}))
        raise SystemExit(2)
    raise SystemExit(run(arguments.output))
