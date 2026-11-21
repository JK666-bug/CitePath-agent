from __future__ import annotations

import copy
import json

from agent.learning_tasks import chapter_task
from agent.plan_state import (
    normalize_task_status,
    normalize_task_type,
)
from agent.scheduler import schedule_required_review
from db.connection import connect


def ensure_learning_sync_storage() -> None:
    """
    Initialize required storage before opening a business transaction.

    Do not call ensure_* inside the business transaction:
    MySQL schema changes may cause implicit commits.
    """
    from db.plan_state import ensure_plan_state_storage
    from db.practice import ensure_practice_storage
    from db.exams import ensure_exam_storage

    ensure_plan_state_storage()
    ensure_practice_storage()
    ensure_exam_storage()


def lock_learning_course(
    cursor,
    user_id: int,
    course_id: int,
) -> None:
    """
    Serialize learning-state writes for one owned course.

    Call this before changing sessions, exams, or plan tasks.
    """
    cursor.execute(
        """
        SELECT id
        FROM courses
        WHERE id = %s AND user_id = %s
        FOR UPDATE
        """,
        (course_id, user_id),
    )

    if cursor.fetchone() is None:
        raise LookupError("Course not found")


def _object(value) -> dict:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()

    if isinstance(value, str):
        value = json.loads(value)

    return value if isinstance(value, dict) else {}


def _completed(task: dict) -> bool:
    return normalize_task_status(
        task.get("status")
    ) == "completed"


def _complete(task: dict, source: str) -> None:
    # Keep an existing completion's attribution.
    if _completed(task):
        return

    task["status"] = "Completed"
    task["completion_source"] = source


def _chapter_key(task: dict) -> str:
    return str(task.get("chapterId") or task.get("chapter_id") or "")


def _task_type(task: dict) -> str:
    return normalize_task_type(task.get("kind") or task.get("type"))


def reduce_chapter_state(
    plan: dict,
    chapter_id: int,
    facts: dict,
) -> dict:
    """
    Pure reducer: updates an existing plan without modifying its input.

    facts:
        practice_started: bool
        practice_finished: bool
        practice_mastered: bool
        exam_started: bool
        exam_open: bool
        ever_exam_passed: bool
        ever_exam_failed: bool
        latest_exam_passed: bool | None
    """
    result = copy.deepcopy(plan)
    chapter_key = str(chapter_id)

    chapter = next(
        (item for item in result.get("chapters") or [] if str(item["id"]) == chapter_key),
        None,
    )
    latest_passed = facts.get("latest_exam_passed")
    tasks = [task for task in result.get("tasks") or [] if _chapter_key(task) == chapter_key]
    review = next((task for task in tasks if _task_type(task) == "review"), None)
    if latest_passed is False and review is None and chapter is not None:
        review = chapter_task(chapter, "Review")
        result["tasks"].append(review)

    if review is not None:
        if latest_passed is not False and not facts.get("ever_exam_failed"):
            # Older plans created Review even when it had never been required.
            result["tasks"].remove(review)
        else:
            activated = review.get("review_activated", False)
            was_completed = _completed(review)
            review["review_activated"] = True
            if latest_passed is True:
                review["status"] = "Completed"
                review["completion_source"] = "exam_pass"
            elif latest_passed is False:
                review["status"] = "Not started"
                review["completion_source"] = ""
                if (not activated or was_completed) and chapter is not None:
                    schedule_required_review(result, chapter, review)

    practice_started = bool(facts.get("practice_started"))
    practice_finished = bool(facts.get("practice_finished"))
    practice_mastered = bool(facts.get("practice_mastered"))

    for task in tasks:
        kind = normalize_task_type(
            task.get("kind") or task.get("type")
        )

        if kind == "read":
            if facts.get("ever_exam_passed"):
                _complete(task, "exam_pass")

        elif kind == "practice":
            if practice_finished and practice_mastered:
                _complete(task, "practice_submit")
            elif practice_started and not _completed(task):
                task["status"] = "In progress"
                task["completion_source"] = ""

    read_done = any(
        normalize_task_type(
            task.get("kind") or task.get("type")
        ) == "read"
        and _completed(task)
        for task in tasks
    )

    practice_done = any(
        normalize_task_type(
            task.get("kind") or task.get("type")
        ) == "practice"
        and _completed(task)
        for task in tasks
    )

    review_status = "not_assessed"
    if latest_passed is True:
        review_status = "passed"
    elif latest_passed is False:
        review_status = "required"

    if facts.get("exam_open"):
        chapter_status = "exam_pending"
    elif latest_passed is True:
        chapter_status = "completed"
    elif latest_passed is False:
        chapter_status = "exam_pending"
    elif practice_done:
        chapter_status = "learned"
    elif practice_started:
        chapter_status = "practice_in_progress"
    elif read_done:
        chapter_status = "learned"
    else:
        chapter_status = "planned"

    states = result.setdefault("chapter_states", {})
    states[chapter_key] = {
        "chapter_status": chapter_status,
        "review_status": review_status,
    }

    # Also expose the state on chapter objects already in the JSON.
    for chapter in result.get("chapters") or []:
        if str(chapter.get("id")) == chapter_key:
            chapter.update(states[chapter_key])

    return result


def sync_learning_state(
    cursor,
    user_id: int,
    course_id: int,
    read_task_id: str | None = None,
) -> dict:
    """
    Reconcile plan state from stored learning evidence.

    The caller must:
      1. initialize storage before opening the transaction;
      2. lock the owned course before business writes;
      3. pass the same cursor used by those writes;
      4. commit or roll back after this function returns.

    This does not regenerate the plan. An exam failure can add or reopen a dated Review.
    """
    cursor.execute(
        """
        SELECT plan_json
        FROM study_plans
        WHERE course_id = %s
        FOR UPDATE
        """,
        (course_id,),
    )
    row = cursor.fetchone()

    if row is None:
        raise LookupError("Plan not found")

    plan = _object(row.get("plan_json"))

    if not isinstance(plan.get("tasks"), list):
        raise ValueError("Plan has no valid tasks")

    if read_task_id is not None:
        task = next(
            (
                item
                for item in plan["tasks"]
                if str(item.get("id")) == str(read_task_id)
            ),
            None,
        )

        if task is None:
            raise LookupError("Task not found")

        if normalize_task_type(
            task.get("kind") or task.get("type")
        ) != "read":
            raise ValueError(
                "Only Reading tasks can be completed manually"
            )

        _complete(task, "student")

    from db.plans import load_active_chapter_ids

    chapter_ids = load_active_chapter_ids(cursor, course_id)

    # Reject a stale task referencing a removed chapter.
    if read_task_id is not None:
        chapter_id = int(
            task.get("chapterId")
            or task.get("chapter_id")
            or 0
        )
        if chapter_id not in chapter_ids:
            raise LookupError("Chapter not found")

    for chapter_id in chapter_ids:
        cursor.execute(
            """
            SELECT status, report_json
            FROM practice_sessions
            WHERE user_id = %s
              AND course_id = %s
              AND chapter_id = %s
            ORDER BY id
            """,
            (user_id, course_id, chapter_id),
        )
        sessions = list(cursor.fetchall())

        cursor.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(
                    CASE WHEN COALESCE(p.level, 0) >= 2
                    THEN 1 ELSE 0 END
                ) AS mastered,
                SUM(
                    CASE WHEN p.concept_id IS NOT NULL
                    THEN 1 ELSE 0 END
                ) AS progress_count
            FROM plan_concepts c
            LEFT JOIN concept_progress p
              ON p.concept_id = c.id
             AND p.user_id = %s
            WHERE c.chapter_id = %s
            """,
            (user_id, chapter_id),
        )
        progress = cursor.fetchone() or {}

        total = int(progress.get("total") or 0)
        mastered = int(progress.get("mastered") or 0)

        # A completed report is useful when a later practice session
        # has reset the current concept progress.
        report_mastered = False
        for session in sessions:
            if session["status"] != "finished":
                continue

            report = _object(session.get("report_json"))
            concepts = report.get("concepts") or []

            if concepts and all(
                int(item.get("level") or 0) >= 2
                for item in concepts
            ):
                report_mastered = True
                break

        cursor.execute(
            """
            SELECT id, status, passed, finished_at
            FROM exams
            WHERE user_id = %s
              AND course_id = %s
              AND chapter_id = %s
            ORDER BY finished_at DESC, id DESC
            """,
            (user_id, course_id, chapter_id),
        )
        exams = list(cursor.fetchall())
        finished = [
            item
            for item in exams
            if item["status"] == "finished"
            and item.get("passed") is not None
        ]

        latest_passed = (
            bool(int(finished[0]["passed"]))
            if finished
            else None
        )

        facts = {
            "practice_started": bool(sessions),
            "practice_finished": any(
                item["status"] == "finished"
                for item in sessions
            ),
            "practice_mastered": (
                report_mastered
                or (total > 0 and mastered == total)
            ),
            "exam_started": bool(exams),
            "exam_open": any(
                item["status"] == "open"
                for item in exams
            ),
            "ever_exam_passed": any(
                bool(int(item["passed"]))
                for item in finished
            ),
            "ever_exam_failed": any(not bool(int(item["passed"])) for item in finished),
            "latest_exam_passed": latest_passed,
        }

        plan = reduce_chapter_state(
            plan,
            chapter_id,
            facts,
        )

        read_done = any(
            str(
                item.get("chapterId")
                or item.get("chapter_id")
                or ""
            ) == str(chapter_id)
            and normalize_task_type(
                item.get("kind") or item.get("type")
            ) == "read"
            and _completed(item)
            for item in plan["tasks"]
        )

        has_progress = int(
            progress.get("progress_count") or 0
        ) > 0

        if facts["exam_started"]:
            reason = "exam_started"
        elif facts["practice_started"] or has_progress:
            reason = "practice_started"
        elif read_done:
            reason = "read_completed"
        else:
            reason = ""

        if reason:
            cursor.execute(
                """
                UPDATE documents d
                JOIN plan_chapter_pages p
                  ON p.document_id = d.id
                SET
                    d.chapter_plan_status = 'locked',
                    d.chapterization_locked_at = COALESCE(
                        d.chapterization_locked_at,
                        CURRENT_TIMESTAMP
                    ),
                    d.chapterization_locked_reason = COALESCE(
                        NULLIF(
                            d.chapterization_locked_reason,
                            ''
                        ),
                        %s
                    )
                WHERE p.chapter_id = %s
                  AND d.course_id = %s
                """,
                (reason, chapter_id, course_id),
            )

    # UPDATE only: do not use the existing insert fallback,
    # and do not increment plan["version"].
    cursor.execute(
        """
        UPDATE study_plans
        SET plan_json = %s
        WHERE course_id = %s
        """,
        (
            json.dumps(plan, ensure_ascii=False),
            course_id,
        ),
    )

    return plan


def refresh_learning_state(
    user_id: int,
    course_id: int,
) -> dict:
    """
    Reconcile existing historical records explicitly.
    """
    ensure_learning_sync_storage()
    connection = connect()

    try:
        with connection.cursor() as cursor:
            lock_learning_course(
                cursor,
                user_id,
                course_id,
            )
            plan = sync_learning_state(
                cursor,
                user_id,
                course_id,
            )

        connection.commit()
        return {"status": "ready", "plan": plan}

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()