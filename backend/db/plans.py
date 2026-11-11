import hashlib
import json
from contextlib import contextmanager

from db.connection import connect
from db.courses import get_course
from db.uploads import ensure_document_numbers, require_ingested_documents

_column_ready = False


class PlanConflict(ValueError):
    """The reviewed plan or its source material changed before publication."""


@contextmanager
def planning_lock(user_id: int, course_id: int):
    """Serialize a course's planning calls across workers, including model work."""
    ensure_plan_storage()
    connection = connect()
    name = f"citepath:plan:{user_id}:{course_id}"
    acquired = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK(%s, 30) AS acquired", (name,))
            acquired = cursor.fetchone()["acquired"] == 1
        if not acquired:
            raise RuntimeError("This study plan is busy. Retry shortly.")
        yield
    finally:
        try:
            if acquired:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT RELEASE_LOCK(%s)", (name,))
        finally:
            connection.close()


def ensure_plan_storage() -> None:
    global _column_ready
    if _column_ready:
        return
    connection = connect()
    schema_locked = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK('citepath:plan:schema', 30) AS acquired")
            schema_locked = cursor.fetchone()["acquired"] == 1
            if not schema_locked:
                raise RuntimeError("Plan storage is being initialized. Retry shortly.")
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
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS plan_versions (
                  course_id INT NOT NULL,
                  version INT NOT NULL,
                  reason TEXT NOT NULL,
                  change_type VARCHAR(32) NOT NULL,
                  plan_json JSON NOT NULL,
                  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  PRIMARY KEY (course_id, version),
                  CONSTRAINT fk_plan_versions_course FOREIGN KEY (course_id) REFERENCES courses (id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        try:
            if schema_locked:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT RELEASE_LOCK('citepath:plan:schema')")
        finally:
            connection.close()
    _column_ready = True


def load_usable_pages(course_id: int) -> list[dict]:
    ensure_document_numbers()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, filename, ingest_status, ingest_error FROM documents WHERE course_id = %s",
                (course_id,),
            )
            require_ingested_documents(list(cursor.fetchall()))
            cursor.execute(
                """
                SELECT d.id AS document_id, d.filename, d.position,
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


def load_planning_materials(course_id: int) -> dict:
    """Read text and document identity without depending on the vector service."""
    ensure_document_numbers()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            return _planning_materials(cursor, course_id)
    finally:
        connection.close()


def _planning_materials(cursor, course_id: int, locked: bool = False) -> dict:
    suffix = " FOR UPDATE" if locked else ""
    cursor.execute(
        "SELECT id, filename, position, content_hash, ingest_status FROM documents "
        "WHERE course_id = %s ORDER BY id" + suffix, (course_id,),
    )
    documents = list(cursor.fetchall())
    cursor.execute(
        """SELECT d.id AS document_id, d.filename, d.position, p.page_number, p.body
           FROM documents d JOIN pages p ON p.document_id = d.id
           WHERE d.course_id = %s AND d.ingest_status = 'complete'
             AND p.usable = 1 AND p.body IS NOT NULL AND TRIM(p.body) <> ''
           ORDER BY d.id, p.page_number""" + suffix, (course_id,),
    )
    pages = list(cursor.fetchall())
    payload = json.dumps({"documents": documents, "pages": pages}, sort_keys=True, ensure_ascii=False, default=str)
    return {"documents": documents, "pages": pages,
            "fingerprint": hashlib.sha256(payload.encode("utf-8")).hexdigest()}


def plan_response(plan: dict | None, materials: dict) -> dict:
    from agent.planning_support import material_update

    return {"status": "ready" if plan else "draft", "plan": plan,
            "material_update": material_update(plan, materials["pages"], materials["documents"])}


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
            plan = _plan_or_none(None if row is None else row["plan_json"])
            # Published JSON retains estimates and source identities even when a
            # document is subsequently removed. Relational rows are a legacy fallback.
            if plan is not None and not plan["chapters"]:
                plan["chapters"] = _load_chapters(cursor, course_id)
            materials = _planning_materials(cursor, course_id)
    finally:
        connection.close()
    if plan is not None:
        _stamp_document_numbers(plan, course_id)
    return plan_response(plan, materials)


def save_generated_plan(course_id: int, plan: dict, expected_version=None, material_fingerprint=None) -> dict:
    ensure_plan_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            _lock_course(cursor, course_id)
            cursor.execute("SELECT plan_json FROM study_plans WHERE course_id = %s FOR UPDATE", (course_id,))
            existing = cursor.fetchone()
            current = _plan_or_none(existing["plan_json"]) if existing else None
            _check_version(current, expected_version)
            if current:
                raise ValueError("A study plan already exists. Reschedule it to preserve learning history.")
            _check_materials(cursor, course_id, material_fingerprint)
            cursor.execute("SELECT id FROM plan_chapters WHERE course_id = %s", (course_id,))
            if list(cursor.fetchall()):
                raise PlanConflict("Saved chapters already exist. Repair the plan before generating another one.")
            id_map = _insert_chapters(cursor, course_id, plan["chapters"], 1)
            stored = _with_saved_ids(plan, id_map)
            _write_plan_json(cursor, course_id, stored)
            _snapshot(cursor, course_id, stored, "generated")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return stored


def load_plan_feedback(user_id: int, course_id: int) -> dict[str, list[str]]:
    from db.practice import ensure_practice_storage

    ensure_practice_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT chapter_id, report_json FROM practice_sessions
                WHERE user_id = %s AND course_id = %s AND status = 'finished'
                  AND report_json IS NOT NULL
                ORDER BY finished_at DESC, id DESC
                """,
                (user_id, course_id),
            )
            return feedback_from_reports(list(cursor.fetchall()))
    finally:
        connection.close()


def feedback_from_reports(rows: list[dict]) -> dict[str, list[str]]:
    feedback = {}
    for row in rows:
        chapter_id = str(row["chapter_id"])
        if chapter_id in feedback:
            continue
        report = row["report_json"]
        if isinstance(report, (bytes, bytearray)):
            report = report.decode()
        if isinstance(report, str):
            try:
                report = json.loads(report)
            except json.JSONDecodeError:
                report = None
        if not isinstance(report, dict):
            report = {}
        weak = report.get("remaining_weak_concepts")
        if weak is None:
            weak = [item.get("concept_name") for item in report.get("wrong") or [] if isinstance(item, dict)]
        feedback[chapter_id] = [str(item) for item in weak if isinstance(item, str) and item.strip()] if isinstance(weak, list) else []
    return feedback


def save_rescheduled_plan(course_id: int, plan: dict, expected_version=None, material_fingerprint=None) -> dict:
    """Publish a schedule without replacing chapters or losing a concurrent completion."""
    connection = connect()
    try:
        with connection.cursor() as cursor:
            _lock_course(cursor, course_id)
            cursor.execute("SELECT plan_json FROM study_plans WHERE course_id = %s FOR UPDATE", (course_id,))
            row = cursor.fetchone()
            current = _plan_or_none(row["plan_json"]) if row else None
            if not current:
                raise ValueError("The existing study plan could not be loaded")
            _check_version(current, expected_version)
            _check_materials(cursor, course_id, material_fingerprint)
            if {str(item["id"]) for item in current["chapters"]} != {str(item["id"]) for item in plan["chapters"]}:
                raise ValueError("The study chapters changed. Reload the plan and retry.")
            stored = json.loads(json.dumps(plan))
            if {task["id"] for task in current["tasks"]} != {task["id"] for task in stored["tasks"]}:
                raise PlanConflict("Existing study tasks must be preserved when rescheduling.")
            _preserve_existing(current, stored)
            stored["version"] = int(current.get("version") or 1) + 1
            _refresh_totals(stored)
            _snapshot(cursor, course_id, current, "legacy")
            _write_plan_json(cursor, course_id, stored)
            _snapshot(cursor, course_id, stored, "rescheduled")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return stored


def save_appended_plan(course_id: int, plan: dict, new_chapter_ids: list[str],
                       expected_version=None, material_fingerprint=None) -> dict:
    """Insert only new chapters; existing concepts, questions and grades stay intact."""
    connection = connect()
    try:
        with connection.cursor() as cursor:
            _lock_course(cursor, course_id)
            cursor.execute("SELECT plan_json FROM study_plans WHERE course_id = %s FOR UPDATE", (course_id,))
            row = cursor.fetchone()
            current = _plan_or_none(row["plan_json"]) if row else None
            if not current:
                raise PlanConflict("The existing study plan could not be loaded. Reload and retry.")
            _check_version(current, expected_version)
            _check_materials(cursor, course_id, material_fingerprint)
            old_ids = {str(chapter["id"]) for chapter in current["chapters"]}
            new_ids = {str(value) for value in new_chapter_ids}
            proposed_ids = {str(chapter["id"]) for chapter in plan["chapters"]}
            if (not new_ids or old_ids & new_ids or proposed_ids != old_ids | new_ids
                    or len(proposed_ids) != len(plan["chapters"])):
                raise PlanConflict("Study chapters changed. Reload the plan and retry.")
            from agent.planning_support import page_keys

            additions = [chapter for chapter in plan["chapters"] if str(chapter["id"]) in new_ids]
            if page_keys({"chapters": additions}) & page_keys(current):
                raise PlanConflict("Some new pages are already included in this plan. Reload and retry.")
            # Positions are append-only even if legacy chapter positions have gaps.
            cursor.execute("SELECT COALESCE(MAX(position), 0) AS last_position FROM plan_chapters WHERE course_id = %s", (course_id,))
            first_position = int(cursor.fetchone()["last_position"]) + 1
            id_map = _insert_chapters(cursor, course_id, additions, first_position)
            stored = _with_saved_ids(plan, id_map)
            current_task_ids = {task["id"] for task in current["tasks"]}
            if not current_task_ids <= {task["id"] for task in stored["tasks"]}:
                raise PlanConflict("Existing study tasks must be preserved when adding material.")
            _preserve_existing(current, stored)
            stored["version"] = int(current.get("version") or 1) + 1
            _refresh_totals(stored)
            _snapshot(cursor, course_id, current, "legacy")
            _write_plan_json(cursor, course_id, stored)
            _snapshot(cursor, course_id, stored, "materials_added")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return stored


def _lock_course(cursor, course_id):
    # Upload/delete also lock the course first. Acquire it before plan/document
    # rows and chapter/history foreign keys to avoid an opposing lock order.
    cursor.execute("SELECT id FROM courses WHERE id = %s FOR UPDATE", (course_id,))
    if cursor.fetchone() is None:
        raise LookupError("Course not found")


def _check_version(current, expected_version):
    if expected_version is None:
        return
    if type(expected_version) is not int or expected_version < 0:
        raise ValueError("expected_version must be a non-negative integer")
    actual = int((current or {}).get("version") or (1 if current else 0))
    if actual != expected_version:
        raise PlanConflict("The study plan changed. Reload the latest version and retry.")


def _preserve_existing(current, proposed):
    """Only schedule/estimate fields may change on existing learning content."""
    chapters = {str(chapter["id"]): chapter for chapter in current["chapters"]}
    for chapter in proposed["chapters"]:
        old = chapters.get(str(chapter["id"]))
        if old:
            for field in ("id", "title", "concepts", "sources"):
                chapter[field] = old[field]
    tasks = {task["id"]: task for task in current["tasks"]}
    preserved = []
    for task in proposed["tasks"]:
        old = tasks.get(task["id"])
        if old:
            if old.get("status") == "Completed":
                task = old
            else:
                changes = {field: task[field] for field in ("date", "estimated_minutes", "estimate_basis") if field in task}
                task = {**old, **changes}
        preserved.append(task)
    proposed["tasks"] = preserved


def _check_materials(cursor, course_id, fingerprint):
    if fingerprint is not None and _planning_materials(cursor, course_id, locked=True)["fingerprint"] != fingerprint:
        raise PlanConflict("Course material changed while planning. Reload the plan and retry.")


def _insert_chapters(cursor, course_id, chapters, first_position):
    id_map = {}
    for position, chapter in enumerate(chapters, start=first_position):
        cursor.execute("INSERT INTO plan_chapters (course_id, position, title) VALUES (%s, %s, %s)",
                       (course_id, position, chapter["title"]))
        chapter_id = int(cursor.lastrowid)
        id_map[str(chapter["id"])] = str(chapter_id)
        cursor.executemany("INSERT INTO plan_concepts (chapter_id, position, name) VALUES (%s, %s, %s)",
                           [(chapter_id, index, name) for index, name in enumerate(chapter["concepts"], start=1)])
        cursor.executemany(
            "INSERT INTO plan_chapter_pages (chapter_id, document_id, page_number, position) VALUES (%s, %s, %s, %s)",
            [(chapter_id, int(source["document_id"]), int(source["page_number"]), index)
             for index, source in enumerate(chapter["sources"], start=1)],
        )
    return id_map


def _snapshot(cursor, course_id, plan, change_type):
    # INSERT IGNORE deliberately never updates an existing version's JSON.
    cursor.execute(
        """INSERT IGNORE INTO plan_versions (course_id, version, reason, change_type, plan_json)
           VALUES (%s, %s, %s, %s, %s)""",
        (course_id, int(plan.get("version") or 1), str(plan.get("reason") or ""), change_type,
         json.dumps(plan, ensure_ascii=False)),
    )


def _refresh_totals(plan):
    if "estimated_total_minutes" not in plan:
        return
    plan["estimated_total_minutes"] = sum(int(task.get("estimated_minutes") or 0) for task in plan["tasks"])
    plan["estimated_remaining_minutes"] = sum(int(task.get("estimated_minutes") or 0) for task in plan["tasks"] if task.get("status") != "Completed")
    if isinstance(plan.get("capacity"), dict):
        plan["capacity"]["remaining_estimated_minutes"] = plan["estimated_remaining_minutes"]
        plan["capacity"]["over_capacity"] = plan["estimated_remaining_minutes"] > plan["capacity"]["available_minutes"]


def get_plan_versions(user_id: int, course_id: int) -> dict:
    if get_course(user_id, course_id) is None:
        raise LookupError("Course not found")
    ensure_plan_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version, reason, change_type, created_at FROM plan_versions WHERE course_id = %s ORDER BY version DESC", (course_id,))
            versions = [dict(row) for row in cursor.fetchall()]
            cursor.execute("SELECT plan_json FROM study_plans WHERE course_id = %s", (course_id,))
            row = cursor.fetchone()
            current = _plan_or_none(row["plan_json"]) if row else None
    finally:
        connection.close()
    if current and not any(int(row["version"]) == int(current.get("version") or 1) for row in versions):
        versions.insert(0, {"version": int(current.get("version") or 1), "reason": current.get("reason") or "",
                            "change_type": "legacy", "created_at": None})
    for row in versions:
        row["created_at"] = str(row["created_at"]) if row.get("created_at") is not None else None
    return {"versions": versions, "read_only": True}


def get_plan_version(user_id: int, course_id: int, version: int) -> dict:
    if get_course(user_id, course_id) is None:
        raise LookupError("Course not found")
    ensure_plan_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT plan_json, created_at, change_type FROM plan_versions WHERE course_id = %s AND version = %s", (course_id, version))
            row = cursor.fetchone()
            if row:
                plan = _plan_or_none(row["plan_json"])
                saved_at, change_type = str(row["created_at"]), row["change_type"]
            else:
                cursor.execute("SELECT plan_json FROM study_plans WHERE course_id = %s", (course_id,))
                current = cursor.fetchone()
                plan = _plan_or_none(current["plan_json"]) if current else None
                if plan and int(plan.get("version") or 1) != version:
                    plan = None
                saved_at, change_type = None, "legacy"
    finally:
        connection.close()
    if plan is None:
        raise LookupError("Plan version not found")
    return {"version": version, "plan": plan, "saved_at": saved_at, "change_type": change_type, "read_only": True}


def save_plan(course_id: int, plan: dict) -> None:
    ensure_plan_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            _lock_course(cursor, course_id)
            _write_plan_json(cursor, course_id, plan)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def complete_task(user_id: int, course_id: int, task_id: str) -> dict:
    if get_course(user_id, course_id) is None:
        raise LookupError("Course not found")
    ensure_plan_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            _lock_course(cursor, course_id)
            cursor.execute("SELECT plan_json FROM study_plans WHERE course_id = %s FOR UPDATE", (course_id,))
            row = cursor.fetchone()
            plan = _plan_or_none(row["plan_json"]) if row else None
            if not plan:
                raise LookupError("Task not found")
            task = next((item for item in plan["tasks"] if item.get("id") == task_id), None)
            if task is None:
                raise LookupError("Task not found")
            if task.get("status") != "Completed":
                _snapshot(cursor, course_id, plan, "legacy")
                task["status"] = "Completed"
                plan["version"] = int(plan.get("version") or 1) + 1
                _refresh_totals(plan)
                _write_plan_json(cursor, course_id, plan)
                _snapshot(cursor, course_id, plan, "task_completed")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    _stamp_document_numbers(plan, course_id)
    return plan_response(plan, load_planning_materials(course_id))


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
        if task.get("status") == "Completed":
            continue
        for source in task.get("sources") or []:
            number = numbers.get(int(source.get("document_id") or 0))
            if number is not None:
                source["position"] = number


def _with_saved_ids(plan: dict, id_map: dict[str, str]) -> dict:
    stored = json.loads(json.dumps(plan))
    for chapter in stored["chapters"]:
        chapter["id"] = id_map.get(str(chapter["id"]), chapter["id"])
    for task in stored["tasks"]:
        if str(task["chapterId"]) in id_map:
            task["chapterId"] = id_map[str(task["chapterId"])]
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
