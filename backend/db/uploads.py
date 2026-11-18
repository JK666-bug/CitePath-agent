import pymysql
import hashlib
import re
from contextlib import contextmanager

from db.connection import connect
from db.document_files import original_pdf_path, save_original_pdf


_numbers_ready = False
_kinds_ready = False


def ensure_document_kinds() -> None:
    global _kinds_ready
    if _kinds_ready:
        return
    connection = connect()
    schema_locked = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK('citepath:documents:schema', 30) AS acquired")
            schema_locked = cursor.fetchone()["acquired"] == 1
            if not schema_locked:
                raise RuntimeError("Document kinds are being initialized. Retry shortly.")
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
        try:
            if schema_locked:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT RELEASE_LOCK('citepath:documents:schema')")
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


def has_segments(document_id: int) -> bool:
    from vector.segments import has_segments as vector_has_segments

    return vector_has_segments(document_id)


def sync_pages(document_id: int, pages: list[dict]) -> int:
    from vector.segments import sync_pages as vector_sync_pages

    return vector_sync_pages(document_id, pages)


def ensure_document_numbers() -> None:
    global _numbers_ready
    if _numbers_ready:
        ensure_document_kinds()
        return
    connection = connect()
    schema_locked = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK('citepath:documents:schema', 30) AS acquired")
            schema_locked = cursor.fetchone()["acquired"] == 1
            if not schema_locked:
                raise RuntimeError("Document storage is being initialized. Retry shortly.")
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
            cursor.execute(
                """
                SELECT COUNT(*) AS n
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'documents'
                  AND COLUMN_NAME = 'ingest_error'
                """
            )
            if int(cursor.fetchone()["n"]) == 0:
                cursor.execute("ALTER TABLE documents ADD COLUMN ingest_error TEXT NULL")
            for column, definition in (("is_active", "TINYINT(1) NOT NULL DEFAULT 1"), ("removed_at", "DATETIME NULL")):
                cursor.execute(
                    "SELECT COUNT(*) AS n FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'documents' AND COLUMN_NAME = %s",
                    (column,),
                )
                if int(cursor.fetchone()["n"]) == 0:
                    cursor.execute(f"ALTER TABLE documents ADD COLUMN {column} {definition}")
            cursor.execute("ALTER TABLE documents MODIFY position INT NULL")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        try:
            if schema_locked:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT RELEASE_LOCK('citepath:documents:schema')")
        finally:
            connection.close()
    _numbers_ready = True
    ensure_document_kinds()


def existing_upload(course_id: int, content_hash: str, pdf_data: bytes | None = None, *,
                    kind: str = "lecture", parent_id: int | None = None) -> dict | None:
    ensure_document_numbers()
    row = _hash_row(course_id, content_hash)
    if row is None:
        return None
    if str(row.get("kind") or "lecture") != kind or row.get("parent_id") != parent_id:
        raise ValueError("This PDF is already stored with another role or sample case; use its existing identity")
    if not row.get("is_active", True):
        return _restore_upload(course_id, row, pdf_data)
    _store_original_pdf(int(row["id"]), pdf_data)
    usable = int(row["usable_page_count"] or 0)
    ready = False
    if usable > 0 and row["ingest_status"] == "complete":
        try:
            ready = has_segments(row["id"])
        except Exception:
            # Retry the same document below; never report an unavailable index as ready.
            pass
    if ready:
        return _payload(row, 0, True)
    count = _sync_document(int(row["id"]), _load_pages(row["id"]))
    return _payload(row, count, True)


def save_document(course_id: int, filename: str, pages: list[dict], content_hash: str,
                  pdf_data: bytes | None = None, *, kind: str = "lecture",
                  parent_id: int | None = None, answer_mode: str | None = None,
                  pdf_bytes: bytes | None = None) -> dict:
    ensure_document_numbers()
    if pdf_data is not None and pdf_bytes is not None and pdf_data != pdf_bytes:
        raise ValueError("Conflicting PDF byte arguments")
    pdf_data = pdf_data if pdf_data is not None else pdf_bytes
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
        connection.commit()
    except pymysql.err.IntegrityError:
        connection.rollback()
        row = _hash_row(course_id, content_hash)
        if row is not None and (str(row.get("kind") or "lecture") != chosen_kind
                                or row.get("parent_id") != parent_id):
            raise ValueError("This PDF is already stored with another role or sample case; use its existing identity")
        existing = existing_upload(course_id, content_hash, pdf_data=pdf_data, kind=chosen_kind, parent_id=parent_id)
        if existing is not None:
            return existing
        raise
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    _store_original_pdf(int(document_id), pdf_data)
    has_file = original_pdf_path(int(document_id)) is not None
    usable = sum(1 for page in pages if page["usable"])
    return {
        "document_id": document_id,
        "filename": filename,
        "page_count": len(pages),
        "usable_page_count": usable,
        "milvus_segments": _sync_document(int(document_id), pages),
        "ingest_status": "complete",
        "ingest_error": None,
        "duplicate": False,
        "kind": chosen_kind,
        "answer_mode": answer_mode,
        "has_file": has_file,
    }


def _store_original_pdf(document_id: int, data: bytes | None) -> None:
    if data is None:
        return
    try:
        save_original_pdf(document_id, data)
    except OSError as error:
        message = "The original PDF could not be saved. Check PDF storage and upload the same file to retry."
        _set_ingestion_status(document_id, "failed", message)
        raise RuntimeError(message) from error


def _set_ingestion_status(document_id: int, status: str, error: str | None = None) -> None:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE documents SET ingest_status = %s, ingest_error = %s WHERE id = %s",
                (status, error, document_id),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


@contextmanager
def document_ingestion_lock(document_id: int):
    connection = connect()
    name = f"citepath:document:{document_id}:ingestion"
    acquired = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK(%s, 30) AS acquired", (name,))
            acquired = cursor.fetchone()["acquired"] == 1
        if not acquired:
            raise RuntimeError("This document is already being indexed. Retry shortly.")
        yield
    finally:
        try:
            if acquired:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT RELEASE_LOCK(%s)", (name,))
        finally:
            connection.close()


def _sync_document(document_id: int, pages: list[dict]) -> int:
    with document_ingestion_lock(document_id):
        return _index_document(document_id, pages)


def _index_document(document_id: int, pages: list[dict]) -> int:
    _set_ingestion_status(document_id, "pending")
    if not any(page.get("usable") and str(page.get("body") or "").strip() for page in pages):
        message = "This PDF has no readable lecture text. Upload a text-based PDF or remove it."
        _set_ingestion_status(document_id, "failed", message)
        raise ValueError(message)
    try:
        count = sync_pages(document_id, pages)
        if count <= 0:
            raise ValueError("No lecture segments were indexed")
    except Exception as error:
        message = (
            f"Lecture vector indexing failed ({type(error).__name__}). "
            "Check Milvus and the embedding service, then upload the same PDF to retry."
        )
        _set_ingestion_status(document_id, "failed", message)
        raise RuntimeError(message) from error
    # Relational pages were committed first; readiness is published only after vector flush.
    _set_ingestion_status(document_id, "complete")
    return count


def require_ingested_documents(documents: list[dict]) -> None:
    """Reject incomplete/legacy broken indexes before any question generation."""
    for document in documents:
        label = f"Document {document['id']} ({document['filename']})"
        if "is_active" in document and document["is_active"] is None:
            raise ValueError(f"Source document {document['id']} is no longer available. Its historical identity cannot be replaced by a different upload.")
        if not document.get("is_active", True):
            raise ValueError(f"{label} was removed from this course. Restore it before generating new questions.")
        if document.get("ingest_status") != "complete":
            reason = document.get("ingest_error") or "Lecture ingestion is still pending."
            raise ValueError(f"{label} is not ready. {reason}")
        try:
            indexed = has_segments(int(document["id"]))
        except Exception as error:
            raise ValueError(f"{label}: the vector store is unavailable. Try again when Milvus is ready.") from error
        if not indexed:
            raise ValueError(f"{label} has no vector index. Upload the same PDF to retry ingestion.")


def _hash_row(course_id: int, content_hash: str) -> dict | None:
    ensure_document_kinds()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT d.id, d.course_id, d.filename, d.kind, d.parent_id, d.answer_mode, d.ingest_status, d.ingest_error, d.is_active, d.content_hash,
                       COUNT(p.id) AS page_count,
                       SUM(CASE WHEN p.usable = 1 THEN 1 ELSE 0 END) AS usable_page_count
                FROM documents d
                LEFT JOIN pages p ON p.document_id = d.id
                WHERE d.course_id = %s AND d.content_hash = %s
                GROUP BY d.id, d.course_id, d.filename, d.kind, d.parent_id, d.answer_mode, d.ingest_status, d.ingest_error, d.is_active, d.content_hash
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
    else:
        file_ready = original_pdf_path(document_id) is not None
    return {
        "document_id": document_id,
        "filename": row["filename"],
        "page_count": int(row["page_count"] or 0),
        "usable_page_count": int(row["usable_page_count"] or 0),
        "milvus_segments": segments,
        "ingest_status": "complete",
        "ingest_error": None,
        "duplicate": duplicate,
        "kind": row.get("kind") or "lecture",
        "answer_mode": row.get("answer_mode"),
        "has_file": file_ready,
    }


def restore_document(user_id: int, course_id: int, document_id: int) -> dict:
    """Restore only an owned retained identity; never match an old reference by name."""
    ensure_document_numbers()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT d.content_hash FROM documents d JOIN courses c ON c.id = d.course_id "
                "WHERE d.id = %s AND d.course_id = %s AND c.user_id = %s",
                (document_id, course_id, user_id),
            )
            document = cursor.fetchone()
            if document is None:
                raise LookupError("Material not found")
    finally:
        connection.close()
    row = _hash_row(course_id, document["content_hash"])
    if row is None or int(row["id"]) != document_id:
        raise LookupError("Material not found")
    return _restore_upload(course_id, row)


def _restore_upload(course_id: int, row: dict, pdf_data: bytes | None = None) -> dict:
    document_id = int(row["id"])
    with document_ingestion_lock(document_id):
        # A remove/restore may have finished while waiting for the document lock.
        row = _hash_row(course_id, row.get("content_hash"))
        if row is None or int(row["id"]) != document_id:
            raise LookupError("Material not found")
        expected_hash = str(row.get("content_hash") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise ValueError("This legacy document has no verifiable original hash. Its historical references cannot be reassigned to another upload.")
        from db.pdf_store import available_pdf_path
        path = original_pdf_path(document_id) or available_pdf_path(course_id, document_id)
        data = pdf_data if pdf_data is not None else (path.read_bytes() if path is not None else None)
        if data is None:
            raise ValueError("Original PDF unavailable. Upload the exact same PDF to restore this document.")
        if hashlib.sha256(data).hexdigest() != expected_hash:
            raise ValueError("The PDF does not match this document's original hash. Upload the exact original PDF; historical IDs cannot be reassigned.")
        if pdf_data is not None:
            _store_original_pdf(document_id, pdf_data)
        was_removed = not row.get("is_active", True)
        pages = _load_pages(document_id)
        # Stay inactive while pending/failed, including when partial vectors already exist.
        count = _index_document(document_id, pages)
        _activate_document(course_id, document_id)
        return {**_payload(row, count, True), "restored": was_removed}


def _activate_document(course_id: int, document_id: int) -> None:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM courses WHERE id = %s FOR UPDATE", (course_id,))
            if cursor.fetchone() is None:
                raise LookupError("Course not found")
            cursor.execute("SELECT is_active FROM documents WHERE id = %s AND course_id = %s FOR UPDATE", (document_id, course_id))
            row = cursor.fetchone()
            if row is None:
                raise LookupError("Material not found")
            if not row["is_active"]:
                cursor.execute("SELECT COALESCE(MAX(position), 0) + 1 AS n FROM documents WHERE course_id = %s AND is_active = 1", (course_id,))
                position = int(cursor.fetchone()["n"])
                cursor.execute("UPDATE documents SET is_active = 1, removed_at = NULL, position = %s WHERE id = %s AND course_id = %s", (position, document_id, course_id))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
