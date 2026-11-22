"""Owned-course planning snapshots, idempotent repair and schedule publication."""
import copy
import json
import uuid

from agent.learning_tasks import ensure_chapter_tasks
from agent.plan_state import normalize_task_type
from agent.scheduler import (
    completed, estimate_times, last_scheduled_date, requirements, schedule_summary, today, validate_schedule,
)
from db.chapterization import (
    ChapterizationConflict, _digest, _json_object, _read_state, _snapshot,
    ensure_chapterization_storage,
)
from db.connection import connect
from db.plan_sync import lock_learning_course, sync_learning_state

_ready = False


def ensure_scheduling_storage():
    global _ready
    ensure_chapterization_storage()
    if _ready:
        return
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS planner_runs (
                    id CHAR(36) PRIMARY KEY,
                    course_id INT NOT NULL,
                    user_id INT NOT NULL,
                    request_id VARCHAR(64) NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    result_json JSON NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_planner_request (course_id, request_id),
                    CONSTRAINT fk_planner_course FOREIGN KEY (course_id)
                        REFERENCES courses(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    _ready = True


def _read_brief(value):
    try:
        return _json_object(value) or {}
    except (ValueError, TypeError):
        return {}


def _prune_priorities(profile, chapter_ids):
    if not isinstance(profile, dict) or not isinstance(profile.get("priority_chapter_ids"), list):
        return False
    current = profile["priority_chapter_ids"]
    kept = [item for item in current if str(item) in chapter_ids]
    if kept == current:
        return False
    profile["priority_chapter_ids"] = kept
    return True


def _sources_changed(old_sources, current_sources):
    def key(item):
        return str(item.get("document_id")), str(item.get("page_number"))

    current = {key(item): item for item in current_sources}
    return any(
        key(item) not in current
        or ("position" in item and item["position"] != current[key(item)].get("position"))
        for item in old_sources or []
    )


def reconcile_active_plan(cursor, user_id, course_id, preview=False):
    """Repair active references inside the caller's owned course lock."""
    from db.plans import _load_chapters

    cursor.execute("SELECT plan_json FROM study_plans WHERE course_id=%s FOR UPDATE", (course_id,))
    row = cursor.fetchone()
    old = _json_object(row["plan_json"]) if row else None
    if not old:
        return {"added": 0, "preview": preview}

    chapters = _load_chapters(cursor, course_id)
    state = old.get("chapter_states") or {}
    sources = {str(chapter["id"]): chapter["sources"] for chapter in chapters}
    for chapter in chapters:
        chapter.update(state.get(str(chapter["id"])) or {})
    plan = copy.deepcopy(old)
    plan["chapters"] = chapters
    plan["chapter_states"] = {key: value for key, value in state.items() if key in sources}
    changed = _prune_priorities(plan.get("scheduling_profile"), sources)
    changed |= plan["chapter_states"] != state
    changed |= any(
        str(chapter["id"]) not in sources
        or _sources_changed(chapter.get("sources"), sources[str(chapter["id"])])
        for chapter in old.get("chapters") or []
    )

    active_tasks = []
    for task in plan.get("tasks") or []:
        chapter_id = str(task.get("chapterId") or task.get("chapter_id") or "")
        if chapter_id not in sources:
            changed = True
            continue
        if _sources_changed(task.get("sources"), sources[chapter_id]):
            task["sources"] = copy.deepcopy(sources[chapter_id])
            changed = True
        active_tasks.append(task)
    plan["tasks"] = active_tasks
    plan, added = ensure_chapter_tasks(plan)

    review_chapters = {
        str(task.get("chapterId") or task.get("chapter_id"))
        for task in active_tasks
        if normalize_task_type(task.get("kind") or task.get("type")) == "review"
    }
    legacy_review = any(
        normalize_task_type(task.get("kind") or task.get("type")) == "review"
        and not task.get("review_activated")
        for task in active_tasks
    ) or any(
        status.get("review_status") == "required" and key not in review_chapters
        for key, status in plan["chapter_states"].items()
    )

    cursor.execute("SELECT student_brief FROM courses WHERE id=%s", (course_id,))
    brief = _read_brief(cursor.fetchone()["student_brief"])
    brief_changed = _prune_priorities(brief.get("scheduling_profile"), sources)
    if not preview:
        if brief_changed:
            payload = json.dumps(brief, ensure_ascii=False)
            cursor.execute("UPDATE courses SET student_brief=%s WHERE id=%s", (payload, course_id))
            cursor.execute("UPDATE study_plans SET student_brief=%s WHERE course_id=%s", (payload, course_id))
        if changed or added:
            _snapshot(cursor, course_id, old, "before_material_update" if changed else "before_task_repair")
            if changed:
                # Progress can change without a new version. Preserve it before removing
                # the tasks from the active plan, even if the version already exists.
                cursor.execute(
                    "UPDATE plan_versions SET plan_json=%s WHERE course_id=%s AND version=%s",
                    (json.dumps(old, ensure_ascii=False), course_id, old.get("version")),
                )
            plan["version"] = int(old.get("version") or 1) + 1
            if changed:
                plan["reason"] = "Updated the plan to reflect the course materials."
            cursor.execute(
                "UPDATE study_plans SET plan_json=%s WHERE course_id=%s",
                (json.dumps(plan, ensure_ascii=False), course_id),
            )
            plan = sync_learning_state(cursor, user_id, course_id)
            _snapshot(cursor, course_id, plan, "materials_updated" if changed else "tasks_repaired")
        elif legacy_review:
            sync_learning_state(cursor, user_id, course_id)
    return {"added": added, "preview": preview}


def repair_tasks(user_id, course_id, preview=False):
    ensure_scheduling_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            lock_learning_course(cursor, user_id, course_id)
            result = reconcile_active_plan(cursor, user_id, course_id, preview=preview)
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _page_text(state):
    return {(int(page["document_id"]), int(page["page_number"])): page["body"]
            for page in state["pages"]}


def _context(cursor, user_id, course_id):
    state = _read_state(cursor, user_id, course_id)
    plan = state["plan"]
    if not plan or not plan.get("chapters"):
        raise ValueError("Create chapters before planning daily tasks")
    brief = _read_brief(state["brief"])
    reports = {str(c["id"]): {} for c in plan["chapters"]}
    for table, key in (("practice_sessions", "practice"), ("exams", "exam")):
        cursor.execute(
            f"SELECT chapter_id, report_json FROM {table} "
            "WHERE course_id=%s AND user_id=%s AND status='finished' "
            "ORDER BY finished_at DESC, id DESC", (course_id, user_id))
        for row in cursor.fetchall():
            bucket = reports.get(str(row["chapter_id"]))
            if bucket is not None and key not in bucket:
                report = _json_object(row.get("report_json")) or {}
                bucket[key] = {field: report[field] for field in (
                    "score", "passed", "wrong_count", "correct_count", "question_count",
                    "concepts", "remaining_weak_concepts", "outcome") if field in report}
    pending_materials = [d for d in state["documents"] if d["state"] == "unplanned"]
    cursor.execute("SELECT c.id,c.chapter_id,p.level,p.streak,p.updated_at FROM plan_concepts c "
                   "JOIN plan_chapters h ON h.id=c.chapter_id "
                   "LEFT JOIN concept_progress p ON p.concept_id=c.id AND p.user_id=%s "
                   "WHERE h.course_id=%s ORDER BY c.id", (user_id, course_id))
    progress = list(cursor.fetchall())
    for concept in progress:
        report = reports.get(str(concept["chapter_id"]))
        if report is None:
            continue
        mastery = report.setdefault("mastery", {"total": 0, "attempted": 0, "mastered": 0})
        mastery["total"] += 1
        if concept["level"] is not None:
            mastery["attempted"] += 1
            mastery["mastered"] += int(concept["level"] >= 2)
    token = _digest({"course_state": state["token"], "reports": reports, "progress": progress})
    return {"course_id": course_id, "token": token, "plan": plan,
            "brief": brief, "profile": brief.get("scheduling_profile") or {},
            "reports": reports, "new_materials": pending_materials,
            "page_text": _page_text(state)}


def get_context(user_id, course_id):
    repair_tasks(user_id, course_id)
    connection = connect()
    try:
        with connection.cursor() as cursor:
            lock_learning_course(cursor, user_id, course_id)
            result = _context(cursor, user_id, course_id)
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def save_requirements(user_id, course_id, raw):
    ensure_scheduling_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            lock_learning_course(cursor, user_id, course_id)
            cursor.execute("SELECT student_brief FROM courses WHERE id=%s", (course_id,))
            brief = _read_brief(cursor.fetchone()["student_brief"])
            profile = requirements(raw, brief)
            from db.plans import load_active_chapter_ids

            ids = {str(id_) for id_ in load_active_chapter_ids(cursor, course_id)}
            if not set(profile["priority_chapter_ids"]) <= ids:
                raise ValueError("Select priority chapters from this course")
            brief["scheduling_profile"] = profile
            payload = json.dumps(brief, ensure_ascii=False)
            cursor.execute("UPDATE courses SET student_brief=%s WHERE id=%s", (payload, course_id))
            cursor.execute("UPDATE study_plans SET student_brief=%s WHERE course_id=%s", (payload, course_id))
        connection.commit()
        return profile
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def saved_schedule_preferences(user_id, course_id):
    """Read the current settings and last-used method for an immediate replan."""
    repair_tasks(user_id, course_id)
    connection = connect()
    try:
        with connection.cursor() as cursor:
            lock_learning_course(cursor, user_id, course_id)
            cursor.execute(
                "SELECT c.student_brief, p.plan_json FROM courses c "
                "LEFT JOIN study_plans p ON p.course_id=c.id WHERE c.id=%s",
                (course_id,),
            )
            row = cursor.fetchone()
            brief = _read_brief(row["student_brief"])
            plan = _json_object(row["plan_json"]) or {}
            if not brief.get("deadline"):
                raise ValueError("Set your study dates in Course settings before replanning.")
            saved = brief.get("scheduling_profile") or plan.get("scheduling_profile") or {}
            profile = {**saved, "daily_minutes": saved.get("daily_minutes", 60)}
            profile["start"] = max(today(), brief.get("startDate") or saved.get("start") or today())
            profile.pop("end", None)
            mode = plan.get("schedule_mode")
            if mode not in ("agent", "baseline") and plan.get("schedule_run_id"):
                cursor.execute(
                    "SELECT result_json FROM planner_runs WHERE id=%s AND course_id=%s AND user_id=%s",
                    (plan["schedule_run_id"], course_id, user_id),
                )
                run = cursor.fetchone()
                mode = (_json_object(run["result_json"]) or {}).get("mode") if run else None
        connection.commit()
        return profile, mode if mode in ("agent", "baseline") else "agent"
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def workflow_status(user_id, course_id):
    repair_tasks(user_id, course_id)
    connection = connect()
    try:
        with connection.cursor() as cursor:
            lock_learning_course(cursor, user_id, course_id)
            state = _read_state(cursor, user_id, course_id)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    plan = state["plan"] or {}
    docs = state["documents"]
    tasks = plan.get("tasks") or []
    pending = [t for t in tasks if not completed(t)]
    scheduled_through = [last_scheduled_date(task) for task in pending]
    current_date = today()
    return {"documents": docs, "chapters": len(plan.get("chapters") or []),
            "tasks": len(tasks), "completed": len(tasks) - len(pending),
            "estimated_minutes": sum(
                item["minutes"] for item in estimate_times(plan, _page_text(state), {}).values()
            ) if plan.get("chapters") else 0,
            "unscheduled": scheduled_through.count(""),
            "overdue": sum(bool(date) and date < current_date for date in scheduled_through),
            "new_documents": sum(d["state"] == "unplanned" and d["eligible"] for d in docs),
            "processing": sum(d["reason"] == "document_not_ready" for d in docs),
            "profile": (_read_brief(state["brief"])).get("scheduling_profile") or {},
            "version": int(plan.get("version") or 0)}


def claim_run(user_id, course_id, request_id):
    ensure_scheduling_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            lock_learning_course(cursor, user_id, course_id)
            cursor.execute("SELECT id,status,result_json FROM planner_runs WHERE course_id=%s AND request_id=%s",
                           (course_id, request_id))
            existing = cursor.fetchone()
            if existing:
                return existing["id"], _json_object(existing["result_json"]) or {
                    "status": existing["status"], "run_id": existing["id"],
                    "message": "This request already exists. Use a new request to retry."}
            run_id = str(uuid.uuid4())
            cursor.execute("INSERT INTO planner_runs (id,course_id,user_id,request_id,status) VALUES (%s,%s,%s,%s,'running')",
                           (run_id, course_id, user_id, request_id))
        connection.commit()
        return run_id, None
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def finish_run(user_id, course_id, run_id, result):
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE planner_runs SET status=%s,result_json=%s "
                           "WHERE id=%s AND course_id=%s AND user_id=%s AND status='running'",
                           (result["status"], json.dumps(result, ensure_ascii=False), run_id, course_id, user_id))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def recent_runs(user_id, course_id):
    ensure_scheduling_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            lock_learning_course(cursor, user_id, course_id)
            cursor.execute("SELECT id,status,result_json,created_at FROM planner_runs "
                           "WHERE course_id=%s AND user_id=%s ORDER BY created_at DESC,id DESC LIMIT 10",
                           (course_id, user_id))
            rows = cursor.fetchall()
        connection.commit()
        return [{"id": r["id"], "status": r["status"], "created_at": str(r["created_at"]),
                 "result": _json_object(r["result_json"])} for r in rows]
    finally:
        connection.close()


def publish_schedule(user_id, course_id, run_id, token, profile, candidate, mode="agent", proposed_by="system"):
    """Re-read all evidence under the course lock; stale proposals cannot publish."""
    connection = connect()
    try:
        with connection.cursor() as cursor:
            lock_learning_course(cursor, user_id, course_id)
            cursor.execute("SELECT status,result_json FROM planner_runs WHERE id=%s AND course_id=%s AND user_id=%s FOR UPDATE",
                           (run_id, course_id, user_id))
            run = cursor.fetchone()
            if not run or run["status"] != "running":
                raise ChapterizationConflict("This planner run is no longer active")
            context = _context(cursor, user_id, course_id)
            if context["token"] != token:
                raise ChapterizationConflict("Learning records or materials changed; reload and replan")
            normalized = requirements(profile, context["brief"])
            estimates = estimate_times(context["plan"], context["page_text"], context["reports"])
            verdict = validate_schedule(context["plan"], normalized, estimates, candidate)
            if not verdict["valid"]:
                raise ValueError("; ".join(verdict["errors"]))
            old = context["plan"]
            plan = copy.deepcopy(old)
            for task in plan["tasks"]:
                if completed(task):
                    continue
                slots = [{"date": x["date"], "minutes": x["minutes"]}
                         for x in candidate["slots"] if x["task_id"] == task["id"]]
                task["schedule"] = slots
                task["date"] = slots[0]["date"] if slots else ""
                task["estimated_minutes"] = estimates[task["id"]]["minutes"]
                task["estimate_basis"] = estimates[task["id"]]["basis"]
            plan.update({"version": int(old.get("version") or 1) + 1,
                         "start": normalized["start"], "end": normalized["end"],
                         "scheduling_profile": normalized, "schedule_run_id": run_id, "schedule_mode": mode,
                         "reason": f"Scheduled unfinished tasks using {candidate['strategy']}; completed work preserved."})
            _snapshot(cursor, course_id, old, "before_schedule")
            cursor.execute("UPDATE study_plans SET plan_json=%s,status='ready' WHERE course_id=%s",
                           (json.dumps(plan, ensure_ascii=False), course_id))
            _snapshot(cursor, course_id, plan, "scheduled")
            # Publish marker in the SAME transaction prevents duplicate saves,
            # even if the model or the HTTP worker fails after this commit.
            saved = {"status": "saved", "run_id": run_id, "version": plan["version"],
                     "message": plan["reason"], "trace": [], "start": normalized["start"], "mode": mode,
                     "summary": schedule_summary(old, plan, normalized, candidate, proposed_by)}
            cursor.execute("UPDATE planner_runs SET status='saved',result_json=%s WHERE id=%s",
                           (json.dumps(saved), run_id))
        connection.commit()
        return saved
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def store_trace(user_id, course_id, run_id, result):
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE planner_runs SET result_json=%s WHERE id=%s AND course_id=%s AND user_id=%s AND status=%s",
                           (json.dumps(result, ensure_ascii=False), run_id, course_id, user_id, result["status"]))
        connection.commit()
    finally:
        connection.close()


def plan_history(user_id, course_id):
    ensure_scheduling_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            lock_learning_course(cursor, user_id, course_id)
            cursor.execute("SELECT version,change_type,created_at FROM plan_versions "
                           "WHERE course_id=%s ORDER BY version DESC LIMIT 50", (course_id,))
            result = [{**r, "created_at": str(r["created_at"])} for r in cursor.fetchall()]
        connection.commit()
        return result
    finally:
        connection.close()


def historical_plan(user_id, course_id, version):
    ensure_scheduling_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            lock_learning_course(cursor, user_id, course_id)
            cursor.execute("SELECT plan_json FROM plan_versions WHERE course_id=%s AND version=%s",
                           (course_id, version))
            row = cursor.fetchone()
        connection.commit()
        if not row:
            raise LookupError("Plan version not found")
        return {"plan": _json_object(row["plan_json"]), "read_only": True}
    finally:
        connection.close()
