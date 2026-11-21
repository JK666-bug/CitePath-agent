from __future__ import annotations

from typing import Final


DOCUMENT_CHAPTER_STATES: Final = frozenset(
    {
        "unplanned",
        "planned",
        "locked",
    }
)

CHAPTER_STATES: Final = frozenset(
    {
        "planned",
        "learning",
        "learned",
        "practice_in_progress",
        "exam_pending",
        "completed",
    }
)

TASK_TYPES: Final = frozenset(
    {
        "read",
        "practice",
        "review",
    }
)

TASK_STATES: Final = frozenset(
    {
        "pending",
        "in_progress",
        "completed",
        "skipped_by_exam",
        "cancelled",
    }
)

REVIEW_STATES: Final = frozenset(
    {
        "not_assessed",
        "required",
        "passed",
    }
)

COMPLETION_SOURCES: Final = frozenset(
    {
        "",
        "student",
        "exam_start",
        "practice_submit",
        "exam_pass",
        "exam_report",
    }
)


def normalize_task_type(value: object) -> str:
    raw = _key(value)

    aliases = {
        "read": "read",
        "reading": "read",
        "practice": "practice",
        "review": "review",
    }

    return aliases.get(raw, raw or "unknown")


def normalize_task_status(value: object) -> str:
    raw = _key(value)

    aliases = {
        "": "pending",
        "pending": "pending",
        "not_started": "pending",
        "not_started_yet": "pending",
        "in_progress": "in_progress",
        "started": "in_progress",
        "open": "in_progress",
        "completed": "completed",
        "complete": "completed",
        "done": "completed",
        "skipped_by_exam": "skipped_by_exam",
        "skipped_exam": "skipped_by_exam",
        "cancelled": "cancelled",
        "canceled": "cancelled",
    }

    return aliases.get(raw, raw or "pending")


def normalize_chapter_status(value: object) -> str:
    raw = _key(value)

    aliases = {
        "": "planned",
        "planned": "planned",
        "learning": "learning",
        "learned": "learned",
        "practice_in_progress": "practice_in_progress",
        "practice_started": "practice_in_progress",
        "exam_pending": "exam_pending",
        "completed": "completed",
        "complete": "completed",
    }

    return aliases.get(raw, raw or "planned")


def normalize_review_status(value: object) -> str:
    raw = _key(value)

    aliases = {
        "": "not_assessed",
        "not_assessed": "not_assessed",
        "not_started": "not_assessed",
        "required": "required",
        "needs_review": "required",
        "review_required": "required",
        "passed": "passed",
    }

    return aliases.get(raw, raw or "not_assessed")


def normalize_completion_source(value: object) -> str:
    raw = _key(value)

    aliases = {
        "": "",
        "student": "student",
        "user": "student",
        "exam_start": "exam_start",
        "exam": "exam_start",
        "practice_submit": "practice_submit",
        "practice": "practice_submit",
        "exam_pass": "exam_pass",
        "exam_report": "exam_report",
    }

    return aliases.get(raw, raw)


def _key(value: object) -> str:
    return (
        str(value or "")
        .strip()
        .casefold()
        .replace("-", "_")
        .replace(" ", "_")
    )
