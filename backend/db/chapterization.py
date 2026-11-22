from __future__ import annotations

import copy
import hashlib
import json

from db.connection import connect
from db.plan_sync import (
    ensure_learning_sync_storage,
    lock_learning_course,
    sync_learning_state,
)


class ChapterizationConflict(RuntimeError):
    pass


def _json_object(value) -> dict | None:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()

    if isinstance(value, str):
        value = json.loads(value)

    return value if isinstance(value, dict) else None


def _digest(value) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).encode("utf-8")

    return hashlib.sha256(payload).hexdigest()


def ensure_chapterization_storage() -> None:
    ensure_learning_sync_storage()

    connection = connect()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS plan_versions (
                    course_id INT NOT NULL,
                    version INT NOT NULL,
                    change_type VARCHAR(32) NOT NULL,
                    plan_json JSON NOT NULL,
                    created_at DATETIME NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (course_id, version),
                    CONSTRAINT fk_chapterization_version_course
                        FOREIGN KEY (course_id)
                        REFERENCES courses(id)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB
                  DEFAULT CHARSET=utf8mb4
                  COLLATE=utf8mb4_unicode_ci
                """
            )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def _snapshot(cursor, course_id: int, plan: dict, change: str):
    cursor.execute(
        """
        INSERT IGNORE INTO plan_versions (
            course_id,
            version,
            change_type,
            plan_json
        )
        VALUES (%s, %s, %s, %s)
        """,
        (
            course_id,
            int(plan.get("version") or 1),
            change,
            json.dumps(plan, ensure_ascii=False),
        ),
    )


def _read_state(cursor, user_id: int, course_id: int) -> dict:
    """
    The caller must hold the owned course lock.

    Reconcile existing learning records before deciding whether
    a document may be rebuilt.
    """
    cursor.execute(
        """
        SELECT student_brief
        FROM courses
        WHERE id = %s AND user_id = %s
        """,
        (course_id, user_id),
    )
    course = cursor.fetchone()

    if course is None:
        raise LookupError("Course not found")

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
    plan = _json_object(
        row.get("plan_json") if row else None
    )

    from db.plans import load_active_chapter_ids

    chapter_ids = load_active_chapter_ids(cursor, course_id)

    if chapter_ids and not plan:
        raise ChapterizationConflict(
            "Saved chapters exist but the plan is missing. "
            "Repair the saved plan before rebuilding chapters."
        )

    if plan:
        # Includes historical practice/exam evidence and manual Read.
        # Locks the entire PDF when any chapter has learning activity.
        plan = sync_learning_state(
            cursor,
            user_id,
            course_id,
        )

    cursor.execute(
        """
        SELECT p.chapter_id, p.document_id
        FROM plan_chapter_pages p
        JOIN plan_chapters c ON c.id = p.chapter_id
        JOIN documents d ON d.id = p.document_id AND d.course_id = c.course_id
        WHERE c.course_id = %s
        ORDER BY p.chapter_id, p.document_id
        """,
        (course_id,),
    )

    chapter_documents: dict[int, set[int]] = {}

    for item in cursor.fetchall():
        chapter_documents.setdefault(
            int(item["chapter_id"]),
            set(),
        ).add(int(item["document_id"]))

    planned_ids = {
        document_id
        for document_ids in chapter_documents.values()
        for document_id in document_ids
    }

    # A legacy chapter may span multiple PDFs.
    # Replacing just one PDF would otherwise delete another PDF's chapter.
    shared_ids = {
        document_id
        for document_ids in chapter_documents.values()
        if len(document_ids) > 1
        for document_id in document_ids
    }

    cursor.execute(
        """
        SELECT
            d.id,
            d.filename,
            d.ingest_status,
            d.chapter_plan_status,
            d.chapterization_locked_at,
            d.chapterization_locked_reason,
            COUNT(
                CASE
                    WHEN p.usable = 1
                     AND p.body IS NOT NULL
                     AND TRIM(p.body) <> ''
                    THEN 1
                END
            ) AS usable_page_count
        FROM documents d
        LEFT JOIN pages p ON p.document_id = d.id
        WHERE d.course_id = %s
          AND (
              d.kind = 'lecture'
              OR d.kind IS NULL
              OR d.kind = ''
          )
        GROUP BY
            d.id,
            d.filename,
            d.ingest_status,
            d.chapter_plan_status,
            d.chapterization_locked_at,
            d.chapterization_locked_reason
        ORDER BY d.id
        """,
        (course_id,),
    )
    documents = []

    for row in cursor.fetchall():
        document_id = int(row["id"])
        locked = (
            row["chapter_plan_status"] == "locked"
            or row["chapterization_locked_at"] is not None
        )
        planned = (
            document_id in planned_ids
            or row["chapter_plan_status"] == "planned"
        )
        ready = (
            row["ingest_status"] == "complete"
            and int(row["usable_page_count"] or 0) > 0
        )

        state = (
            "locked" if locked
            else "planned" if planned
            else "unplanned"
        )

        reason = ""
        if locked:
            reason = (
                row["chapterization_locked_reason"]
                or "learning_started"
            )
        elif document_id in shared_ids:
            reason = "shared_chapter"
        elif not ready:
            reason = "document_not_ready"

        documents.append(
            {
                "id": document_id,
                "filename": row["filename"],
                "state": state,
                "eligible": ready and not reason,
                "reason": reason,
            }
        )

    cursor.execute(
        """
        SELECT p.document_id, p.page_number, p.body, d.filename
        FROM pages p
        JOIN documents d ON d.id = p.document_id
        WHERE d.course_id = %s
          AND d.ingest_status = 'complete'
          AND (
              d.kind = 'lecture'
              OR d.kind IS NULL
              OR d.kind = ''
          )
          AND p.usable = 1
          AND p.body IS NOT NULL
          AND TRIM(p.body) <> ''
        ORDER BY p.document_id, p.page_number
        """,
        (course_id,),
    )
    pages = list(cursor.fetchall())

    token = _digest(
        {
            "brief": course["student_brief"],
            "plan": plan,
            "documents": documents,
            "pages": pages,
            "chapter_documents": {
                str(key): sorted(value)
                for key, value in chapter_documents.items()
            },
        }
    )

    return {
        "course_id": course_id,
        "brief": course["student_brief"],
        "plan": plan,
        "documents": documents,
        "pages": pages,
        "chapter_documents": chapter_documents,
        "token": token,
    }


def prepare_chapterization(
    user_id: int,
    course_id: int,
) -> dict:
    ensure_chapterization_storage()
    connection = connect()

    try:
        with connection.cursor() as cursor:
            lock_learning_course(cursor, user_id, course_id)
            state = _read_state(cursor, user_id, course_id)

        connection.commit()
        return state

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def chapterization_options(
    user_id: int,
    course_id: int,
) -> dict:
    state = prepare_chapterization(user_id, course_id)

    return {
        "token": state["token"],
        "new_documents": [
            item for item in state["documents"]
            if item["eligible"]
            and item["state"] == "unplanned"
        ],
        "rebuildable_documents": [
            item for item in state["documents"]
            if item["eligible"]
            and item["state"] == "planned"
        ],
        "blocked_documents": [
            item for item in state["documents"]
            if not item["eligible"]
        ],
    }


def choose_documents(
    documents: list[dict],
    document_ids: list[int],
    confirmed: bool,
) -> list[int]:
    """
    New PDFs always take precedence.

    Rebuilding planned PDFs is allowed only when no eligible new PDF
    exists and the user explicitly confirms the selected PDFs.
    """
    new_ids = [
        item["id"]
        for item in documents
        if item["eligible"]
        and item["state"] == "unplanned"
    ]

    if new_ids:
        if confirmed:
            raise ChapterizationConflict(
                "New PDFs are available. Analyze them first."
            )

        selected = list(dict.fromkeys(document_ids or new_ids))

        if not set(selected) <= set(new_ids):
            raise ChapterizationConflict(
                "Only new PDFs may be analyzed in this operation."
            )

        return selected

    allowed = {
        item["id"]
        for item in documents
        if item["eligible"]
        and item["state"] == "planned"
    }

    if not allowed:
        raise ChapterizationConflict(
            "No PDF is available for chapter rebuilding."
        )

    if not confirmed:
        raise ChapterizationConflict(
            "Confirm the PDFs to reanalyze before rebuilding."
        )

    selected = list(dict.fromkeys(document_ids))

    if not selected or not set(selected) <= allowed:
        raise ChapterizationConflict(
            "Select only eligible, unlocked PDFs."
        )

    return selected


def save_document_chapters(
    user_id: int,
    course_id: int,
    document_ids: list[int],
    confirmed: bool,
    expected_token: str,
    chapters: list[dict],
    reason: str,
) -> dict:
    """
    Save only selected PDFs.

    Model calls happen before this transaction. Recheck learning state
    and material contents after the model returns.
    """
    ensure_chapterization_storage()
    connection = connect()

    try:
        with connection.cursor() as cursor:
            lock_learning_course(cursor, user_id, course_id)
            state = _read_state(cursor, user_id, course_id)

            if state["token"] != expected_token:
                raise ChapterizationConflict(
                    "The course changed during analysis. "
                    "Reload and retry."
                )

            selected = choose_documents(
                state["documents"],
                document_ids,
                confirmed,
            )
            selected_set = set(selected)

            allowed_pages = {
                (int(page["document_id"]), int(page["page_number"]))
                for page in state["pages"]
                if int(page["document_id"]) in selected_set
            }

            covered_documents = set()

            if not chapters:
                raise ValueError("No chapters were generated")

            for chapter in chapters:
                refs = {
                    (
                        int(source["document_id"]),
                        int(source["page_number"]),
                    )
                    for source in chapter["sources"]
                }

                if not refs or not refs <= allowed_pages:
                    raise ValueError("Invalid generated chapter sources")

                # Preserve the existing one-document Chapterizer boundary.
                owners = {item[0] for item in refs}
                if len(owners) != 1:
                    raise ValueError(
                        "A generated chapter must belong to one PDF"
                    )
                covered_documents.update(owners)

            if covered_documents != selected_set:
                raise ValueError(
                    "Not every selected PDF received chapters"
                )

            removed_ids = [
                chapter_id
                for chapter_id, owners
                in state["chapter_documents"].items()
                if owners and owners <= selected_set
            ]
            removed_keys = {str(item) for item in removed_ids}

            old = state["plan"]
            plan = copy.deepcopy(old) if old else {
                "version": 0,
                "start": "",
                "end": "",
                "reason": "",
                "chapters": [],
                "tasks": [],
            }

            if old:
                _snapshot(cursor, course_id, old, "before_chapters")

            # Preserve every other chapter and task.
            plan["tasks"] = [
                task for task in plan.get("tasks") or []
                if str(
                    task.get("chapterId")
                    or task.get("chapter_id")
                    or ""
                ) not in removed_keys
            ]
            plan["chapter_states"] = {
                key: value
                for key, value
                in (plan.get("chapter_states") or {}).items()
                if str(key) not in removed_keys
            }

            if removed_ids:
                marks = ", ".join(["%s"] * len(removed_ids))

                # The locked-state checks above ensure these chapters
                # have no learning sessions or exam records.
                cursor.execute(
                    f"DELETE FROM plan_chapter_pages "
                    f"WHERE chapter_id IN ({marks})",
                    removed_ids,
                )
                cursor.execute(
                    f"DELETE FROM plan_concepts "
                    f"WHERE chapter_id IN ({marks})",
                    removed_ids,
                )
                cursor.execute(
                    f"DELETE FROM plan_chapters "
                    f"WHERE id IN ({marks}) AND course_id = %s",
                    [*removed_ids, course_id],
                )

            cursor.execute(
                """
                SELECT COALESCE(MAX(position), 0) AS last_position
                FROM plan_chapters
                WHERE course_id = %s
                """,
                (course_id,),
            )
            position = int(
                cursor.fetchone()["last_position"]
            )

            for chapter in chapters:
                position += 1

                cursor.execute(
                    """
                    INSERT INTO plan_chapters (
                        course_id, position, title
                    )
                    VALUES (%s, %s, %s)
                    """,
                    (course_id, position, chapter["title"]),
                )
                chapter_id = int(cursor.lastrowid)

                cursor.executemany(
                    """
                    INSERT INTO plan_concepts (
                        chapter_id, position, name
                    )
                    VALUES (%s, %s, %s)
                    """,
                    [
                        (chapter_id, index, name)
                        for index, name
                        in enumerate(chapter["concepts"], 1)
                    ],
                )

                cursor.executemany(
                    """
                    INSERT INTO plan_chapter_pages (
                        chapter_id,
                        document_id,
                        page_number,
                        position
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    [
                        (
                            chapter_id,
                            int(source["document_id"]),
                            int(source["page_number"]),
                            index,
                        )
                        for index, source
                        in enumerate(chapter["sources"], 1)
                    ],
                )

                plan["chapter_states"][str(chapter_id)] = {
                    "chapter_status": "planned",
                    "review_status": "not_assessed",
                }

            marks = ", ".join(["%s"] * len(selected))
            cursor.execute(
                f"""
                UPDATE documents
                SET chapter_plan_status = 'planned',
                    chapter_planned_at = CURRENT_TIMESTAMP
                WHERE course_id = %s
                  AND id IN ({marks})
                  AND chapter_plan_status <> 'locked'
                  AND chapterization_locked_at IS NULL
                """,
                [course_id, *selected],
            )

            # Reuse the current chapter loading format.
            from db.plans import _load_chapters

            plan["chapters"] = _load_chapters(cursor, course_id)

            for chapter in plan["chapters"]:
                chapter.update(
                    plan["chapter_states"].get(
                        str(chapter["id"]),
                        {
                            "chapter_status": "planned",
                            "review_status": "not_assessed",
                        },
                    )
                )

            from agent.learning_tasks import ensure_chapter_tasks

            plan, _ = ensure_chapter_tasks(plan)
            plan["version"] = int(
                plan.get("version") or 0
            ) + 1
            plan["reason"] = reason

            # UPDATE first, with an explicit existence check.
            cursor.execute(
                """
                SELECT id
                FROM study_plans
                WHERE course_id = %s
                """,
                (course_id,),
            )

            if cursor.fetchone() is None:
                cursor.execute(
                    """
                    INSERT INTO study_plans (
                        course_id,
                        student_brief,
                        status,
                        plan_json
                    )
                    VALUES (%s, %s, 'ready', %s)
                    """,
                    (
                        course_id,
                        state["brief"],
                        json.dumps(plan, ensure_ascii=False),
                    ),
                )
            else:
                cursor.execute(
                    """
                    UPDATE study_plans
                    SET status = 'ready', plan_json = %s
                    WHERE course_id = %s
                    """,
                    (
                        json.dumps(plan, ensure_ascii=False),
                        course_id,
                    ),
                )

            _snapshot(cursor, course_id, plan, "chapters_updated")

        connection.commit()
        return {"status": "ready", "plan": plan}

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()
