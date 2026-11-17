import pymysql

from db.connection import connect
from vector.segments import has_segments, sync_pages


_numbers_ready = False
_kinds_ready = False


def ensure_document_kinds() -> None:
    global _kinds_ready
    if _kinds_ready:
        return
    connection = connect()
    try:
        with connection.cursor() as cursor:
            _add_column(cursor, "kind", "VARCHAR(16) NOT NULL DEFAULT 'lecture'")
            _add_column(cursor, "parent_id", "INT NULL")
            _add_column(cursor, "answer_mode", "VARCHAR(16) NULL")
            cursor.execute(
                """
                SELECT COUNT(*) AS n
                FROM information_schema.TABLE_CONSTRAINTS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'documents'
                  AND CONSTRAINT_NAME = 'fk_documents_parent'
                """
            )
            if int(cursor.fetchone()["n"]) == 0:
                cursor.execute(
                    """
                    ALTER TABLE documents
                    ADD CONSTRAINT fk_documents_parent
                    FOREIGN KEY (parent_id) REFERENCES documents (id) ON DELETE CASCADE
                    """
                )
            cursor.execute(
                "UPDATE documents SET kind = 'lecture' WHERE kind IS NULL OR kind = ''"
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    _kinds_ready = True


def _add_column(cursor, name: str, definition: str) -> None:
    cursor.execute(
        """
        SELECT COUNT(*) AS n
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'documents'
          AND COLUMN_NAME = %s
        """,
        (name,),
    )
    if int(cursor.fetchone()["n"]) == 0:
        cursor.execute(f"ALTER TABLE documents ADD COLUMN {name} {definition}")


def ensure_document_numbers() -> None:
    global _numbers_ready
    if _numbers_ready:
        return
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS n
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'documents'
                  AND COLUMN_NAME = 'position'
                """
            )
            if int(cursor.fetchone()["n"]) == 0:
                cursor.execute("ALTER TABLE documents ADD COLUMN position INT NULL")
                cursor.execute(
                    """
                    UPDATE documents d
                    JOIN (
                      SELECT id,
                             ROW_NUMBER() OVER (PARTITION BY course_id ORDER BY id) AS n
                      FROM documents
                    ) ranked ON ranked.id = d.id
                    SET d.position = ranked.n
                    """
                )
                cursor.execute("ALTER TABLE documents MODIFY position INT NOT NULL")
                cursor.execute(
                    """
                    ALTER TABLE documents
                    ADD UNIQUE KEY uq_course_document_pos (course_id, position)
                    """
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    _numbers_ready = True


def existing_upload(course_id: int, content_hash: str) -> dict | None:
    row = _hash_row(course_id, content_hash)
    if row is None:
        return None
    usable = int(row["usable_page_count"] or 0)
    if usable > 0 and not has_segments(row["id"]):
        count = sync_pages(row["id"], _load_pages(row["id"]))
        return _payload(row, count, False)
    return _payload(row, 0, True)


def save_document(
    course_id: int,
    filename: str,
    pages: list[dict],
    content_hash: str,
    kind: str = "lecture",
    parent_id: int | None = None,
    answer_mode: str | None = None,
    pdf_bytes: bytes | None = None,
) -> dict:
    ensure_document_numbers()
    ensure_document_kinds()
    chosen_kind = str(kind or "lecture").strip() or "lecture"
    if chosen_kind not in {"lecture", "exam_case", "case_answer"}:
        raise ValueError("Unsupported document kind")
    connection = connect()
    try:
        with connection.cursor() as cursor:
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
                raise LookupError("Course not found")

            cursor.execute(
                """
                SELECT COALESCE(MAX(position), 0) + 1 AS n
                FROM documents
                WHERE course_id = %s
                """,
                (course_id,),
            )
            position = int(cursor.fetchone()["n"])
            cursor.execute(
                """
                INSERT INTO documents (
                  course_id, position, filename, content_hash, ingest_status,
                  kind, parent_id, answer_mode
                )
                VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s)
                """,
                (
                    course_id,
                    position,
                    filename,
                    content_hash,
                    chosen_kind,
                    parent_id,
                    answer_mode,
                ),
            )
            document_id = cursor.lastrowid
            cursor.executemany(
                """
                INSERT INTO pages (document_id, page_number, body, usable)
                VALUES (%s, %s, %s, %s)
                """,
                [
                    (
                        document_id,
                        page["page_number"],
                        page["body"],
                        page["usable"],
                    )
                    for page in pages
                ],
            )
            cursor.execute(
                "UPDATE documents SET ingest_status = 'complete' WHERE id = %s",
                (document_id,),
            )
        connection.commit()
    except pymysql.err.IntegrityError:
        connection.rollback()
        existing = existing_upload(course_id, content_hash)
        if existing is not None:
            return existing
        raise
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    has_file = False
    if pdf_bytes:
        from db.pdf_store import save_pdf

        save_pdf(course_id, int(document_id), pdf_bytes)
        has_file = True
    usable = sum(1 for page in pages if page["usable"])
    return {
        "document_id": document_id,
        "filename": filename,
        "page_count": len(pages),
        "usable_page_count": usable,
        "milvus_segments": sync_pages(document_id, pages),
        "duplicate": False,
        "kind": chosen_kind,
        "answer_mode": answer_mode,
        "has_file": has_file,
    }


def _hash_row(course_id: int, content_hash: str) -> dict | None:
    ensure_document_kinds()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT d.id, d.course_id, d.filename, d.kind, d.answer_mode,
                       COUNT(p.id) AS page_count,
                       SUM(CASE WHEN p.usable = 1 THEN 1 ELSE 0 END) AS usable_page_count
                FROM documents d
                LEFT JOIN pages p ON p.document_id = d.id
                WHERE d.course_id = %s AND d.content_hash = %s
                GROUP BY d.id, d.course_id, d.filename, d.kind, d.answer_mode
                """,
                (course_id, content_hash),
            )
            return cursor.fetchone()
    finally:
        connection.close()


def _load_pages(document_id: int) -> list[dict]:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT page_number, body, usable
                FROM pages
                WHERE document_id = %s
                ORDER BY page_number
                """,
                (document_id,),
            )
            return list(cursor.fetchall())
    finally:
        connection.close()


def _payload(row: dict, segments: int, duplicate: bool) -> dict:
    from db.pdf_store import has_pdf

    course_id = int(row["course_id"]) if row.get("course_id") is not None else None
    document_id = int(row["id"])
    file_ready = False
    if course_id is not None:
        file_ready = has_pdf(course_id, document_id)
    return {
        "document_id": document_id,
        "filename": row["filename"],
        "page_count": int(row["page_count"] or 0),
        "usable_page_count": int(row["usable_page_count"] or 0),
        "milvus_segments": segments,
        "duplicate": duplicate,
        "kind": row.get("kind") or "lecture",
        "answer_mode": row.get("answer_mode"),
        "has_file": file_ready,
    }
