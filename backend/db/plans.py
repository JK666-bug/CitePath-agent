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


def load_usable_pages(course_id: int) -> list[dict]:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT d.id AS document_id, d.filename,
                       p.page_number, p.body
                FROM documents d
                JOIN pages p ON p.document_id = d.id
                WHERE d.course_id = %s
                  AND d.ingest_status = 'complete'
                  AND p.usable = 1
                  AND p.body IS NOT NULL
                  AND TRIM(p.body) <> ''
                ORDER BY d.id, p.page_number
                """,
                (course_id,),
            )
            return list(cursor.fetchall())
    finally:
        connection.close()


def get_plan(user_id: int, course_id: int) -> dict:
    course = get_course(user_id, course_id)
    if course is None:
        raise LookupError("Course not found")
    ensure_plan_storage()
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
    finally:
        connection.close()
    plan = _plan_or_none(None if row is None else row["plan_json"])
    if plan is not None and chapters:
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


def complete_task(user_id: int, course_id: int, task_id: str) -> dict:
    current = get_plan(user_id, course_id)
    plan = current["plan"]
    if not plan:
        raise LookupError("Task not found")
    found = False
    for task in plan["tasks"]:
        if task.get("id") != task_id:
            continue
        found = True
        task["status"] = "Completed"
        break
    if not found:
        raise LookupError("Task not found")
    save_plan(course_id, plan)
    return {"status": "ready", "plan": plan}


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
