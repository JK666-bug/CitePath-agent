from __future__ import annotations

import copy
import json
from typing import Any

from agent.plan import parse_brief
from db.courses import get_course
from db.plans import get_plan
from db.study_status import course_study

from agent.plan_state import (
    normalize_completion_source,
    normalize_task_status,
    normalize_task_type,
)
from db.plan_state import (
    ensure_plan_state_storage,
    get_document_plan_states,
)


def load_planner_snapshot(
    user_id: int,
    course_id: int,
) -> dict:
    """
    Read all information needed by the future Planner Agent.

    This function must remain read-only with respect to:
    - chapters
    - tasks
    - practice records
    - exam reports
    - plan versions

    Existing database ensure_* functions may still create missing schema
    columns or tables. No learning data is changed here.
    """
    course = get_course(user_id, course_id)
    if course is None:
        raise LookupError("Course not found")

    ensure_plan_state_storage()
    document_states = get_document_plan_states(course_id)

    plan_result = get_plan(user_id, course_id)
    study = course_study(user_id, course_id)

    raw_plan = plan_result.get("plan")
    plan = copy.deepcopy(raw_plan) if isinstance(raw_plan, dict) else None

    chapters = [
        _normalize_chapter(item)
        for item in (plan or {}).get("chapters") or []
        if isinstance(item, dict)
    ]

    tasks = [
        _normalize_task(item)
        for item in (plan or {}).get("tasks") or []
        if isinstance(item, dict)
    ]

    learning_state = _normalize_learning_state(study)

    return {
        "course_id": int(course_id),
        "course": {
            "id": int(course["id"]),
            "name": str(course.get("name") or ""),
            "created_at": str(course.get("created_at") or ""),
        },
        "course_requirements": _course_requirements(
            str(course.get("student_brief") or "")
        ),
        "documents": _normalize_documents(
            course.get("documents") or [],
            document_states,
        ),
        "scheduling_profile": copy.deepcopy((plan or {}).get("scheduling_profile") or {}),
        "plan": {
            "status": str(plan_result.get("status") or "draft"),
            "version": _plan_version(plan),
            "start": str((plan or {}).get("start") or ""),
            "end": str((plan or {}).get("end") or ""),
            "reason": str((plan or {}).get("reason") or ""),
        },
        "chapters": chapters,
        "tasks": tasks,
        "learning_state": learning_state,
    }


def _course_requirements(raw_brief: str) -> dict:
    """
    Decode the existing course brief without writing it back.

    A malformed or incomplete brief is returned as invalid data so the
    future Planner Agent can ask for clarification.
    """
    raw = str(raw_brief or "")

    try:
        parsed = parse_brief(raw)
    except ValueError as error:
        return {
            "valid": False,
            "deadline": "",
            "early_days": 0,
            "note": raw.strip(),
            "error": str(error),
            "raw": raw,
        }

    return {
        "valid": True,
        "deadline": str(parsed.get("deadline") or ""),
        "early_days": int(parsed.get("early_days") or 0),
        "note": str(parsed.get("note") or ""),
        "error": "",
        "raw": raw,
    }

def _normalize_documents(
    rows: list[dict],
    states: dict[int, dict],
) -> list[dict]:
    documents = []

    for row in rows:
        document_id = _int_value(row.get("id"))
        state = states.get(document_id) or {}

        documents.append(
            {
                "id": document_id,
                "position": _int_value(row.get("position")),
                "filename": str(row.get("filename") or ""),
                "ingest_status": str(
                    row.get("ingest_status") or ""
                ),
                "kind": str(row.get("kind") or "lecture"),
                "page_count": _int_value(row.get("page_count")),
                "usable_page_count": _int_value(
                    row.get("usable_page_count")
                ),
                "has_file": bool(row.get("has_file")),

                "chapter_plan_status": str(
                    state.get("chapter_plan_status")
                    or "unplanned"
                ),
                "chapter_planned_at": state.get(
                    "chapter_planned_at"
                ),
                "chapterization_locked_at": state.get(
                    "chapterization_locked_at"
                ),
                "chapterization_locked_reason": str(
                    state.get(
                        "chapterization_locked_reason"
                    )
                    or ""
                ),
            }
        )

    return documents

def _normalize_chapter(chapter: dict) -> dict:
    sources = []

    for source in chapter.get("sources") or []:
        if not isinstance(source, dict):
            continue

        sources.append(
            {
                "document_id": _int_value(source.get("document_id")),
                "position": _int_value(source.get("position")),
                "filename": str(source.get("filename") or ""),
                "page_number": _int_value(source.get("page_number")),
            }
        )

    concepts = [
        str(item).strip()
        for item in chapter.get("concepts") or []
        if str(item).strip()
    ]

    return {
        "id": str(chapter.get("id") or ""),
        "title": str(
            chapter.get("title") or ""
        ).strip(),
        "concepts": concepts,
        "sources": sources,
        "chapter_status": str(
            chapter.get("chapter_status") or "planned"
        ),
        "review_status": str(
            chapter.get("review_status") or "not_assessed"
        ),
    }

def _normalize_task(task: dict) -> dict:
    raw_kind = task.get("kind") or task.get("type") or ""
    raw_status = task.get("status") or ""
    raw_source = task.get("completion_source") or ""

    sources = []

    for source in task.get("sources") or []:
        if isinstance(source, dict):
            sources.append(copy.deepcopy(source))

    return {
        "id": str(task.get("id") or ""),
        "chapter_id": str(
            task.get("chapterId")
            or task.get("chapter_id")
            or ""
        ),
        "type": normalize_task_type(raw_kind),
        "raw_type": str(raw_kind),
        "title": str(task.get("title") or ""),
        "date": str(task.get("date") or ""),
        "schedule": copy.deepcopy(task.get("schedule") or []),
        "status": normalize_task_status(raw_status),
        "raw_status": str(raw_status),
        "completion_source": normalize_completion_source(
            raw_source
        ),
        "concepts": [
            str(item).strip()
            for item in task.get("concepts") or []
            if str(item).strip()
        ],
        "sources": sources,
    }

def _normalize_learning_state(record: dict) -> dict:
    raw_chapters = record.get("chapters") or []
    chapter_rows = copy.deepcopy(raw_chapters)

    by_title = {}

    for item in chapter_rows:
        if not isinstance(item, dict):
            continue

        title = str(item.get("title") or "").strip()
        if title:
            by_title[title] = copy.deepcopy(item)

    return {
        "chapters": chapter_rows,
        "by_chapter_title": by_title,
        "practice_wrongs": copy.deepcopy(
            record.get("practice_wrongs") or []
        ),
        "exam_wrongs": copy.deepcopy(
            record.get("exam_wrongs") or []
        ),
        "exam_summary": copy.deepcopy(
            record.get("exams") or {}
        ),
    }


def _plan_version(plan: dict | None) -> int:
    if not isinstance(plan, dict):
        return 0

    value = plan.get("version")

    try:
        version = int(value)
    except (TypeError, ValueError):
        return 0

    return max(version, 0)


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
