import pymysql
from contextlib import contextmanager

from db.connection import connect
from db.document_files import save_original_pdf


_numbers_ready = False


def has_segments(document_id: int) -> bool:
    from vector.segments import has_segments as vector_has_segments

    return vector_has_segments(document_id)


def sync_pages(document_id: int, pages: list[dict]) -> int:
    from vector.segments import sync_pages as vector_sync_pages

    return vector_sync_pages(document_id, pages)


def ensure_document_numbers() -> None:
    global _numbers_ready
    if _numbers_ready:
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


def existing_upload(course_id: int, content_hash: str, pdf_data: bytes | None = None) -> dict | None:
    ensure_document_numbers()
    row = _hash_row(course_id, content_hash)
    if row is None:
        return None
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


def save_document(course_id: int, filename: str, pages: list[dict], content_hash: str, pdf_data: bytes | None = None) -> dict:
    ensure_document_numbers()
    connection = connect()
    try:
        with connection.cursor() as cursor:
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
                INSERT INTO documents (course_id, position, filename, content_hash, ingest_status)
                VALUES (%s, %s, %s, %s, 'pending')
                """,
                (course_id, position, filename, content_hash),
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
        existing = existing_upload(course_id, content_hash, pdf_data=pdf_data)
        if existing is not None:
            return existing
        raise
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    _store_original_pdf(int(document_id), pdf_data)
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
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT d.id, d.filename, d.ingest_status, d.ingest_error,
                       COUNT(p.id) AS page_count,
                       SUM(CASE WHEN p.usable = 1 THEN 1 ELSE 0 END) AS usable_page_count
                FROM documents d
                LEFT JOIN pages p ON p.document_id = d.id
                WHERE d.course_id = %s AND d.content_hash = %s
                GROUP BY d.id, d.filename, d.ingest_status, d.ingest_error
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
    return {
        "document_id": row["id"],
        "filename": row["filename"],
        "page_count": int(row["page_count"] or 0),
        "usable_page_count": int(row["usable_page_count"] or 0),
        "milvus_segments": segments,
        "ingest_status": "complete",
        "ingest_error": None,
        "duplicate": duplicate,
    }
