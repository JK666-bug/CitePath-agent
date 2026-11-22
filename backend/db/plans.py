import json

from db.connection import connect
from db.courses import get_course
from db.uploads import ensure_document_numbers

_column_ready = False


def ensure_plan_storage() -> None:
    global _column_ready
    if _column_ready:
        return
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS n
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'study_plans'
                  AND COLUMN_NAME = 'plan_json'
                """
            )
            if int(cursor.fetchone()["n"]) == 0:
                cursor.execute("ALTER TABLE study_plans ADD COLUMN plan_json JSON NULL")
            cursor.execute(
                """
                SELECT COUNT(*) AS n
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'pages'
                  AND COLUMN_NAME = 'chapter'
                """
            )
            if int(cursor.fetchone()["n"]) > 0:
                cursor.execute("ALTER TABLE pages DROP COLUMN chapter")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS plan_chapters (
                  id INT PRIMARY KEY AUTO_INCREMENT,
                  course_id INT NOT NULL,
                  position INT NOT NULL,
                  title VARCHAR(255) NOT NULL,
                  UNIQUE KEY uq_plan_chapter_pos (course_id, position),
                  CONSTRAINT fk_plan_chapters_course FOREIGN KEY (course_id) REFERENCES courses (id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS plan_concepts (
                  id INT PRIMARY KEY AUTO_INCREMENT,
                  chapter_id INT NOT NULL,
                  position INT NOT NULL,
                  name VARCHAR(255) NOT NULL,
                  UNIQUE KEY uq_plan_concept_pos (chapter_id, position),
                  CONSTRAINT fk_plan_concepts_chapter FOREIGN KEY (chapter_id) REFERENCES plan_chapters (id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS plan_chapter_pages (
                  id INT PRIMARY KEY AUTO_INCREMENT,
                  chapter_id INT NOT NULL,
                  document_id INT NOT NULL,
                  page_number INT NOT NULL,
                  position INT NOT NULL,
                  UNIQUE KEY uq_plan_chapter_page (chapter_id, document_id, page_number),
                  CONSTRAINT fk_plan_pages_chapter FOREIGN KEY (chapter_id) REFERENCES plan_chapters (id) ON DELETE CASCADE,
                  CONSTRAINT fk_plan_pages_document FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    _column_ready = True


def load_usable_pages(
    course_id: int,
    document_ids: list[int] | None = None,
) -> list[dict]:
    from db.uploads import ensure_document_kinds

    ensure_document_kinds()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT d.id AS document_id, d.filename,
                       p.page_number, p.body
                FROM documents d
                JOIN pages p ON p.document_id = d.id
                WHERE d.course_id = %s
                  AND d.ingest_status = 'complete'
                  AND (d.kind = 'lecture' OR d.kind IS NULL OR d.kind = '')
                  AND p.usable = 1
                  AND p.body IS NOT NULL
                  AND TRIM(p.body) <> ''
                """
            params: list[int] = [course_id]
            if document_ids is not None:
                ids = [int(item) for item in document_ids]
                if not ids:
                    return []
                marks = ", ".join(["%s"] * len(ids))
                sql += f" AND d.id IN ({marks})"
                params.extend(ids)
            sql += " ORDER BY d.id, p.page_number"
            cursor.execute(sql, params)
            return list(cursor.fetchall())
    finally:
        connection.close()


def get_plan(user_id: int, course_id: int) -> dict:
    from db.practice import chapter_practice_progress, ensure_practice_storage

    course = get_course(user_id, course_id)
    if course is None:
        raise LookupError("Course not found")
    ensure_plan_storage()
    ensure_practice_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, plan_json
                FROM study_plans
                WHERE course_id = %s
                """,
                (course_id,),
            )
            row = cursor.fetchone()
            chapters = _load_chapters(cursor, course_id)
            practice_progress = chapter_practice_progress(cursor, user_id, course_id) if chapters else {}
    finally:
        connection.close()
    plan = _plan_or_none(
        None if row is None else row["plan_json"]
    )

    if plan is not None:
        states = plan.get("chapter_states") or {}

        for chapter in chapters:
            state = states.get(
                str(chapter["id"])
            ) or {}

            chapter["chapter_status"] = str(
                state.get("chapter_status") or "planned"
            )
            chapter["review_status"] = str(
                state.get("review_status") or "not_assessed"
            )
            if chapter["id"] in practice_progress:
                chapter["practice_progress"] = practice_progress[chapter["id"]]

        plan["chapters"] = chapters

    if plan is not None:
        _stamp_document_numbers(plan, course_id)

    status = "ready" if plan else "draft"
    return {"status": status, "plan": plan}


def save_generated_plan(course_id: int, plan: dict) -> dict:
    ensure_plan_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            _delete_chapters(cursor, course_id)
            id_map = {}
            for position, chapter in enumerate(plan["chapters"], start=1):
                cursor.execute(
                    """
                    INSERT INTO plan_chapters (course_id, position, title)
                    VALUES (%s, %s, %s)
                    """,
                    (course_id, position, chapter["title"]),
                )
                chapter_id = int(cursor.lastrowid)
                id_map[chapter["id"]] = str(chapter_id)
                cursor.executemany(
                    """
                    INSERT INTO plan_concepts (chapter_id, position, name)
                    VALUES (%s, %s, %s)
                    """,
                    [
                        (chapter_id, index, name)
                        for index, name in enumerate(chapter["concepts"], start=1)
                    ],
                )
                cursor.executemany(
                    """
                    INSERT INTO plan_chapter_pages
                      (chapter_id, document_id, page_number, position)
                    VALUES (%s, %s, %s, %s)
                    """,
                    [
                        (
                            chapter_id,
                            int(source["document_id"]),
                            int(source["page_number"]),
                            index,
                        )
                        for index, source in enumerate(chapter["sources"], start=1)
                    ],
                )
            stored = _with_saved_ids(plan, id_map)
            _write_plan_json(cursor, course_id, stored)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return stored


def save_plan(course_id: int, plan: dict) -> None:
    ensure_plan_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            _write_plan_json(cursor, course_id, plan)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def complete_read_task(
    user_id: int,
    course_id: int,
    task_id: str,
) -> dict:
    from db.plan_sync import (
        ensure_learning_sync_storage,
        lock_learning_course,
        sync_learning_state,
    )

    ensure_learning_sync_storage()
    connection = connect()

    try:
        with connection.cursor() as cursor:
            lock_learning_course(
                cursor,
                user_id,
                course_id,
            )

            sync_learning_state(
                cursor,
                user_id,
                course_id,
                read_task_id=task_id,
            )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    return get_plan(user_id, course_id)


def complete_task(
    user_id: int,
    course_id: int,
    task_id: str,
) -> dict:
    """
    Keep the existing API import compatible.

    Practice and Review are completed by learning evidence,
    not by this manual endpoint.
    """
    return complete_read_task(
        user_id,
        course_id,
        task_id,
    )

def _delete_chapters(cursor, course_id: int) -> None:
    cursor.execute("SELECT id FROM plan_chapters WHERE course_id = %s", (course_id,))
    ids = [int(row["id"]) for row in cursor.fetchall()]
    if not ids:
        return
    from db.practice import delete_chapter_sessions, ensure_practice_storage

    ensure_practice_storage()
    delete_chapter_sessions(cursor, ids)
    marks = ", ".join(["%s"] * len(ids))
    cursor.execute(f"DELETE FROM plan_chapter_pages WHERE chapter_id IN ({marks})", ids)
    cursor.execute(f"DELETE FROM plan_concepts WHERE chapter_id IN ({marks})", ids)
    cursor.execute("DELETE FROM plan_chapters WHERE course_id = %s", (course_id,))


def load_active_chapter_ids(cursor, course_id: int) -> list[int]:
    """Exclude chapters whose source PDFs have all been removed."""
    cursor.execute(
        """
        SELECT c.id FROM plan_chapters c
        WHERE c.course_id = %s AND EXISTS (
            SELECT 1 FROM plan_chapter_pages p
            JOIN documents d ON d.id = p.document_id AND d.course_id = c.course_id
            WHERE p.chapter_id = c.id
        )
        ORDER BY c.position, c.id
        """,
        (course_id,),
    )
    return [int(row["id"]) for row in cursor.fetchall()]


def _load_chapters(cursor, course_id: int) -> list[dict]:
    cursor.execute(
        """
        SELECT id, title
        FROM plan_chapters
        WHERE course_id = %s
        ORDER BY position, id
        """,
        (course_id,),
    )
    rows = list(cursor.fetchall())
    if not rows:
        return []
    ids = [int(row["id"]) for row in rows]
    marks = ", ".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT chapter_id, name
        FROM plan_concepts
        WHERE chapter_id IN ({marks})
        ORDER BY chapter_id, position, id
        """,
        ids,
    )
    concepts: dict[int, list[str]] = {}
    for row in cursor.fetchall():
        concepts.setdefault(int(row["chapter_id"]), []).append(row["name"])
    cursor.execute(
        f"""
        SELECT p.chapter_id, p.document_id, p.page_number, d.filename, d.position
        FROM plan_chapter_pages p
        JOIN documents d ON d.id = p.document_id
        WHERE p.chapter_id IN ({marks})
        ORDER BY p.chapter_id, p.position, p.id
        """,
        ids,
    )
    sources: dict[int, list[dict]] = {}
    for row in cursor.fetchall():
        sources.setdefault(int(row["chapter_id"]), []).append(
            {
                "document_id": int(row["document_id"]),
                "position": int(row["position"]),
                "filename": row["filename"],
                "page_number": int(row["page_number"]),
            }
        )
    return [
        {
            "id": str(int(row["id"])),
            "title": row["title"],
            "concepts": concepts.get(int(row["id"]), []),
            "sources": sources.get(int(row["id"]), []),
        }
        for row in rows
        if int(row["id"]) in sources
    ]


def _stamp_document_numbers(plan: dict, course_id: int) -> None:
    ensure_document_numbers()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, position FROM documents WHERE course_id = %s",
                (course_id,),
            )
            numbers = {int(row["id"]): int(row["position"]) for row in cursor.fetchall()}
    finally:
        connection.close()
    for chapter in plan.get("chapters") or []:
        for source in chapter.get("sources") or []:
            number = numbers.get(int(source.get("document_id") or 0))
            if number is not None:
                source["position"] = number
    for task in plan.get("tasks") or []:
        for source in task.get("sources") or []:
            number = numbers.get(int(source.get("document_id") or 0))
            if number is not None:
                source["position"] = number


def _with_saved_ids(plan: dict, id_map: dict[str, str]) -> dict:
    stored = json.loads(json.dumps(plan))
    for chapter in stored["chapters"]:
        chapter["id"] = id_map[chapter["id"]]
    for task in stored["tasks"]:
        task["chapterId"] = id_map[task["chapterId"]]
        task["id"] = f"{str(task['kind']).lower()}-{task['chapterId']}"
    return stored


def _write_plan_json(cursor, course_id: int, plan: dict) -> None:
    payload = json.dumps(plan, ensure_ascii=False)
    cursor.execute(
        """
        UPDATE study_plans
        SET plan_json = %s, status = 'ready'
        WHERE course_id = %s
        """,
        (payload, course_id),
    )
    if cursor.rowcount == 0:
        cursor.execute(
            """
            INSERT INTO study_plans (course_id, student_brief, status, plan_json)
            VALUES (%s, '', 'ready', %s)
            """,
            (course_id, payload),
        )


def _plan_or_none(raw) -> dict | None:
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    if not isinstance(raw.get("chapters"), list) or not isinstance(raw.get("tasks"), list):
        return None
    return raw
