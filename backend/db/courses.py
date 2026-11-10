import json

from db.connection import connect
from db.uploads import ensure_document_numbers


def list_courses(user_id: int) -> list[dict]:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.id, c.name, c.student_brief, c.created_at,
                       COUNT(d.id) AS document_count
                FROM courses c
                LEFT JOIN documents d
                  ON d.course_id = c.id AND d.ingest_status = 'complete'
                WHERE c.user_id = %s
                GROUP BY c.id, c.name, c.student_brief, c.created_at
                ORDER BY c.id DESC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
    finally:
        connection.close()
    return [_course_summary(row) for row in rows]


def create_course(user_id: int, name: str, student_brief: str) -> dict:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO courses (user_id, name, student_brief)
                VALUES (%s, %s, %s)
                """,
                (user_id, name, student_brief),
            )
            course_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT INTO study_plans (course_id, student_brief, status)
                VALUES (%s, %s, 'draft')
                """,
                (course_id, student_brief),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return get_course(user_id, course_id)


def brief_with_note(text: str, note: str) -> str:
    cleaned = note.strip()
    if len(cleaned) > 9000:
        raise ValueError("The study brief is too long.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict) or data.get("schema") != "citepath-course-v1":
        data = {
            "schema": "citepath-course-v1",
            "deadline": "",
            "earlyDays": 0,
        }
    data["note"] = cleaned
    return json.dumps(data, ensure_ascii=False)


def save_course_note(user_id: int, course_id: int, note: str) -> str:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT student_brief
                FROM courses
                WHERE id = %s AND user_id = %s
                """,
                (course_id, user_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise LookupError("Course not found")
            updated = brief_with_note(row["student_brief"], note)
            cursor.execute(
                """
                UPDATE courses
                SET student_brief = %s
                WHERE id = %s AND user_id = %s
                """,
                (updated, course_id, user_id),
            )
            cursor.execute(
                """
                UPDATE study_plans
                SET student_brief = %s
                WHERE course_id = %s
                """,
                (updated, course_id),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return updated


def get_course(user_id: int, course_id: int) -> dict | None:
    ensure_document_numbers()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, student_brief, created_at
                FROM courses
                WHERE id = %s AND user_id = %s
                """,
                (course_id, user_id),
            )
            course = cursor.fetchone()
            if course is None:
                return None
            cursor.execute(
                """
                SELECT d.id, d.position, d.filename, d.ingest_status,
                       COUNT(p.id) AS page_count,
                       SUM(CASE WHEN p.usable = 1 THEN 1 ELSE 0 END) AS usable_page_count
                FROM documents d
                LEFT JOIN pages p ON p.document_id = d.id
                WHERE d.course_id = %s
                GROUP BY d.id, d.position, d.filename, d.ingest_status
                ORDER BY d.position, d.id
                """,
                (course_id,),
            )
            documents = cursor.fetchall()
    finally:
        connection.close()
    return {
        "id": course["id"],
        "name": course["name"],
        "student_brief": course["student_brief"],
        "created_at": _time(course["created_at"]),
        "documents": [
            {
                "id": row["id"],
                "position": int(row["position"]),
                "filename": row["filename"],
                "ingest_status": row["ingest_status"],
                "page_count": int(row["page_count"] or 0),
                "usable_page_count": int(row["usable_page_count"] or 0),
            }
            for row in documents
        ],
    }


def owns_document(user_id: int, course_id: int, document_id: int) -> bool:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT d.id
                FROM documents d
                JOIN courses c ON c.id = d.course_id
                WHERE d.id = %s AND d.course_id = %s AND c.user_id = %s
                """,
                (document_id, course_id, user_id),
            )
            return cursor.fetchone() is not None
    finally:
        connection.close()


def delete_course(user_id: int, course_id: int) -> list[int] | None:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM courses
                WHERE id = %s AND user_id = %s
                """,
                (course_id, user_id),
            )
            if cursor.fetchone() is None:
                return None
            cursor.execute(
                "SELECT id FROM documents WHERE course_id = %s",
                (course_id,),
            )
            document_ids = [int(row["id"]) for row in cursor.fetchall()]
            cursor.execute(
                """
                DELETE pages
                FROM plan_chapter_pages pages
                JOIN plan_chapters chapters ON chapters.id = pages.chapter_id
                WHERE chapters.course_id = %s
                """,
                (course_id,),
            )
            cursor.execute(
                """
                DELETE concepts
                FROM plan_concepts concepts
                JOIN plan_chapters chapters ON chapters.id = concepts.chapter_id
                WHERE chapters.course_id = %s
                """,
                (course_id,),
            )
            cursor.execute(
                "DELETE FROM plan_chapters WHERE course_id = %s",
                (course_id,),
            )
            cursor.execute(
                "DELETE FROM qa_records WHERE course_id = %s",
                (course_id,),
            )
            cursor.execute(
                "DELETE FROM study_plans WHERE course_id = %s",
                (course_id,),
            )
            if document_ids:
                marks = ", ".join(["%s"] * len(document_ids))
                cursor.execute(
                    f"DELETE FROM pages WHERE document_id IN ({marks})",
                    document_ids,
                )
            cursor.execute(
                "DELETE FROM documents WHERE course_id = %s",
                (course_id,),
            )
            cursor.execute(
                """
                DELETE FROM courses
                WHERE id = %s AND user_id = %s
                """,
                (course_id, user_id),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return document_ids

def _renumber_documents(cursor, course_id: int) -> None:
    """将课程内现存文档的显示序号整理为 1、2、3……"""
    cursor.execute(
        """
        SELECT id, position
        FROM documents
        WHERE course_id = %s
        ORDER BY position, id
        FOR UPDATE
        """,
        (course_id,),
    )
    rows = cursor.fetchall()

    # 按旧序号从小到大更新，依次填补空位。
    # 避免触发 (course_id, position) 唯一约束冲突。
    for new_position, row in enumerate(rows, start=1):
        if int(row["position"]) == new_position:
            continue

        cursor.execute(
            """
            UPDATE documents
            SET position = %s
            WHERE id = %s AND course_id = %s
            """,
            (new_position, row["id"], course_id),
        )

def delete_document_rows(document_id: int) -> None:
    ensure_document_numbers()
    connection = connect()

    try:
        with connection.cursor() as cursor:
            # 先找到文档所属课程。
            cursor.execute(
                """
                SELECT course_id
                FROM documents
                WHERE id = %s
                """,
                (document_id,),
            )
            document = cursor.fetchone()

            # 文档已经不存在时，直接结束。
            if document is None:
                connection.rollback()
                return

            course_id = int(document["course_id"])

            # 对同一课程的文档增删使用同一把数据库行锁。
            cursor.execute(
                """
                SELECT id
                FROM courses
                WHERE id = %s
                FOR UPDATE
                """,
                (course_id,),
            )
            if cursor.fetchone() is None:
                connection.rollback()
                return

            cursor.execute(
                "DELETE FROM pages WHERE document_id = %s",
                (document_id,),
            )
            cursor.execute(
                """
                DELETE FROM documents
                WHERE id = %s AND course_id = %s
                """,
                (document_id, course_id),
            )

            # 删除和重排序在同一事务中完成。
            _renumber_documents(cursor, course_id)

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

def _course_summary(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "student_brief": row["student_brief"],
        "created_at": _time(row["created_at"]),
        "document_count": int(row["document_count"] or 0),
    }


def _time(value) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M")
