from __future__ import annotations

from datetime import datetime

from agent.plan_state import (
    DOCUMENT_CHAPTER_STATES,
)
from db.connection import connect


_READY = False


def ensure_plan_state_storage() -> None:
    """
    Add document-level chapter planning state to an existing database.

    This function is idempotent. It can be called repeatedly.
    It does not change chapters, tasks, reports, or plan versions.
    """
    global _READY

    if _READY:
        return

    # plan_chapter_pages is needed for the existing-plan backfill.
    from db.plans import ensure_plan_storage

    ensure_plan_storage()

    connection = connect()

    try:
        with connection.cursor() as cursor:
            _add_column(
                cursor,
                "chapter_plan_status",
                "VARCHAR(16) NOT NULL DEFAULT 'unplanned'",
            )
            _add_column(
                cursor,
                "chapter_planned_at",
                "DATETIME NULL",
            )
            _add_column(
                cursor,
                "chapterization_locked_at",
                "DATETIME NULL",
            )
            _add_column(
                cursor,
                "chapterization_locked_reason",
                "VARCHAR(64) NULL",
            )

            cursor.execute(
                """
                UPDATE documents
                SET chapter_plan_status = 'unplanned'
                WHERE chapter_plan_status IS NULL
                   OR TRIM(chapter_plan_status) = ''
                """
            )

            # Existing documents that already have chapter source pages
            # have already been planned. They are not locked yet because
            # learning activity is checked in a later step.
            cursor.execute(
                """
                UPDATE documents d
                SET d.chapter_plan_status = 'planned',
                    d.chapter_planned_at = COALESCE(
                        d.chapter_planned_at,
                        CURRENT_TIMESTAMP
                    )
                WHERE d.chapter_plan_status = 'unplanned'
                  AND EXISTS (
                      SELECT 1
                      FROM plan_chapter_pages p
                      WHERE p.document_id = d.id
                  )
                """
            )

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    _READY = True


def get_document_plan_states(
    course_id: int,
) -> dict[int, dict]:
    """
    Return document-level chapter planning states for one course.
    """
    ensure_plan_state_storage()

    connection = connect()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    course_id,
                    chapter_plan_status,
                    chapter_planned_at,
                    chapterization_locked_at,
                    chapterization_locked_reason
                FROM documents
                WHERE course_id = %s
                ORDER BY position, id
                """,
                (course_id,),
            )
            rows = cursor.fetchall()
    finally:
        connection.close()

    states = {}

    for row in rows:
        document_id = int(row["id"])

        states[document_id] = {
            "document_id": document_id,
            "course_id": int(row["course_id"]),
            "chapter_plan_status": _document_status(
                row.get("chapter_plan_status")
            ),
            "chapter_planned_at": _time_value(
                row.get("chapter_planned_at")
            ),
            "chapterization_locked_at": _time_value(
                row.get("chapterization_locked_at")
            ),
            "chapterization_locked_reason": str(
                row.get("chapterization_locked_reason") or ""
            ),
        }

    return states


def get_document_plan_state(
    document_id: int,
) -> dict | None:
    """
    Return one document's chapter planning state.
    """
    ensure_plan_state_storage()

    connection = connect()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    course_id,
                    chapter_plan_status,
                    chapter_planned_at,
                    chapterization_locked_at,
                    chapterization_locked_reason
                FROM documents
                WHERE id = %s
                """,
                (document_id,),
            )
            row = cursor.fetchone()
    finally:
        connection.close()

    if row is None:
        return None

    return {
        "document_id": int(row["id"]),
        "course_id": int(row["course_id"]),
        "chapter_plan_status": _document_status(
            row.get("chapter_plan_status")
        ),
        "chapter_planned_at": _time_value(
            row.get("chapter_planned_at")
        ),
        "chapterization_locked_at": _time_value(
            row.get("chapterization_locked_at")
        ),
        "chapterization_locked_reason": str(
            row.get("chapterization_locked_reason") or ""
        ),
    }


def set_document_planned(document_id: int) -> None:
    """
    Mark a document as chapter-planned.

    This helper is prepared for the next step. It is not called yet
    by Chapterizer in this step.
    """
    ensure_plan_state_storage()

    connection = connect()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE documents
                SET chapter_plan_status = 'planned',
                    chapter_planned_at = COALESCE(
                        chapter_planned_at,
                        CURRENT_TIMESTAMP
                    )
                WHERE id = %s
                  AND chapter_plan_status IN ('unplanned', 'planned')
                  AND chapterization_locked_at IS NULL
                """,
                (document_id,),
            )

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def set_document_locked(
    document_id: int,
    reason: str,
) -> None:
    """
    Lock a document after learning activity starts.

    This helper is prepared for the next step. It is not called yet
    by reading, practice, or exam flows in this step.
    """
    ensure_plan_state_storage()

    connection = connect()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE documents
                SET chapter_plan_status = 'locked',
                    chapterization_locked_at = CURRENT_TIMESTAMP,
                    chapterization_locked_reason = %s
                WHERE id = %s
                """,
                (str(reason or "")[:64], document_id),
            )

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _add_column(
    cursor,
    name: str,
    definition: str,
) -> None:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'documents'
          AND COLUMN_NAME = %s
        """,
        (name,),
    )

    row = cursor.fetchone()

    if int(row["count"]) == 0:
        cursor.execute(
            f"ALTER TABLE documents ADD COLUMN {name} {definition}"
        )


def _document_status(value: object) -> str:
    status = str(value or "").strip().casefold()

    if status in DOCUMENT_CHAPTER_STATES:
        return status

    return "unplanned"


def _time_value(value: object) -> str | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.isoformat(sep=" ")

    return str(value)
