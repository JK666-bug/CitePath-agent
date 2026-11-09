import json

from db.connection import connect


def load_page_bodies(pairs: list[tuple[int, int]]) -> dict[tuple[int, int], dict]:
    if not pairs:
        return {}
    clauses = " OR ".join(["(p.document_id = %s AND p.page_number = %s)"] * len(pairs))
    params: list[int] = []
    for document_id, page_number in pairs:
        params.extend([document_id, page_number])
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT p.document_id, p.page_number, p.body, d.filename
                FROM pages p
                JOIN documents d ON d.id = p.document_id
                WHERE p.usable = 1 AND ({clauses})
                """,
                params,
            )
            rows = cursor.fetchall()
    finally:
        connection.close()
    return {(int(row["document_id"]), int(row["page_number"])): row for row in rows}


def insert_record(
    course_id: int,
    user_id: int,
    question: str,
    answer: str,
    cited_pages: list[dict],
    refused: bool,
    web_sources: list[dict] | None = None,
    origin: str = "",
) -> int:
    _ensure_web_sources()
    stored_pages = None
    if cited_pages and not refused:
        stored_pages = json.dumps(
            [
                {
                    "document_id": item["document_id"],
                    "page_number": item["page_number"],
                }
                for item in cited_pages
            ],
            ensure_ascii=False,
        )
    stored_web = None
    if web_sources and not refused:
        stored_web = json.dumps(
            [{"title": item["title"], "url": item["url"]} for item in web_sources],
            ensure_ascii=False,
        )
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qa_records
                  (course_id, user_id, question, answer, cited_pages, web_sources, refused, origin)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    course_id,
                    user_id,
                    question,
                    answer,
                    stored_pages,
                    stored_web,
                    1 if refused else 0,
                    origin or None,
                ),
            )
            record_id = cursor.lastrowid
        connection.commit()
        return record_id
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _add_column(cursor, name: str, definition: str) -> None:
    cursor.execute("SHOW COLUMNS FROM qa_records LIKE %s", (name,))
    if cursor.fetchone() is not None:
        return
    try:
        cursor.execute(f"ALTER TABLE qa_records ADD COLUMN {name} {definition}")
    except Exception as error:
        if getattr(error, "args", (None,))[0] != 1060:
            raise


def _ensure_web_sources() -> None:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            _add_column(cursor, "web_sources", "TEXT NULL")
            _add_column(cursor, "origin", "VARCHAR(32) NULL")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def recent_turns(user_id: int, course_id: int, limit: int = 10) -> list[dict]:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT question, answer
                FROM qa_records
                WHERE course_id = %s AND user_id = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (course_id, user_id, limit),
            )
            rows = list(cursor.fetchall())
    finally:
        connection.close()
    rows.reverse()
    return [{"question": row["question"], "answer": row["answer"]} for row in rows]


def list_records(user_id: int, course_id: int) -> list[dict]:
    from db.courses import get_course

    course = get_course(user_id, course_id)
    if course is None:
        raise LookupError("Course not found")
    _ensure_web_sources()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, question, answer, cited_pages, web_sources, refused, origin, created_at
                FROM qa_records
                WHERE course_id = %s AND user_id = %s
                ORDER BY id DESC
                LIMIT 50
                """,
                (course_id, user_id),
            )
            rows = list(cursor.fetchall())
            cursor.execute(
                "SELECT id, filename, position FROM documents WHERE course_id = %s",
                (course_id,),
            )
            documents = {int(row["id"]): row for row in cursor.fetchall()}
    finally:
        connection.close()
    records = []
    for row in rows:
        raw = row["cited_pages"]
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode()
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = []
        else:
            parsed = raw if isinstance(raw, list) else []
        cited = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            document = documents.get(int(item.get("document_id") or 0))
            if document is None:
                continue
            cited.append(
                {
                    "document_id": int(document["id"]),
                    "position": int(document["position"]) if document.get("position") is not None else None,
                    "filename": document["filename"],
                    "page_number": int(item.get("page_number") or 0),
                }
            )
        created = row["created_at"]
        records.append(
            {
                "qa_id": int(row["id"]),
                "course_id": course_id,
                "course_name": course["name"],
                "question": row["question"],
                "answer": row["answer"],
                "cited_pages": [] if row["refused"] else cited,
                "web_sources": [] if row["refused"] else _web_sources(row.get("web_sources")),
                "refused": bool(row["refused"]),
                "origin": str(row.get("origin") or ""),
                "created_at": created.strftime("%Y-%m-%d %H:%M") if hasattr(created, "strftime") else str(created or ""),
            }
        )
    return records


def _web_sources(value) -> list[dict]:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
    else:
        parsed = value if isinstance(value, list) else []
    sources = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        if not url.startswith("https://") and not url.startswith("http://"):
            continue
        sources.append({"title": str(item.get("title") or url)[:200], "url": url})
    return sources
