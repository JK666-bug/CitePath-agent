import json
import uuid

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
                WHERE d.is_active = 1 AND (d.kind = 'lecture' OR d.kind IS NULL OR d.kind = '')
                  AND p.usable = 1 AND ({clauses})
                """,
                params,
            )
            rows = cursor.fetchall()
    finally:
        connection.close()
    return {(int(row["document_id"]), int(row["page_number"])): row for row in rows}


def load_leading_pages(document_ids: list[int], limit: int = 4) -> list[dict]:
    """First usable pages from selected lecture PDFs."""
    ids = [int(item) for item in document_ids if int(item) > 0]
    if not ids or limit <= 0:
        return []
    marks = ", ".join(["%s"] * len(ids))
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT p.document_id, p.page_number, p.body, d.filename
                FROM pages p
                JOIN documents d ON d.id = p.document_id
                WHERE d.is_active = 1 AND (d.kind = 'lecture' OR d.kind IS NULL OR d.kind = '')
                  AND p.usable = 1
                  AND p.document_id IN ({marks})
                  AND p.body IS NOT NULL
                  AND TRIM(p.body) <> ''
                ORDER BY d.position, p.document_id, p.page_number
                LIMIT %s
                """,
                [*ids, int(limit)],
            )
            return list(cursor.fetchall())
    finally:
        connection.close()


def load_overview_pages(document_ids: list[int], limit: int = 8) -> list[dict]:
    """Sample pages across selected PDFs for a course/PPT overview (not keyword search)."""
    ids = [int(item) for item in document_ids if int(item) > 0]
    if not ids or limit <= 0:
        return []
    marks = ", ".join(["%s"] * len(ids))
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT p.document_id, p.page_number, d.filename, d.position
                FROM pages p
                JOIN documents d ON d.id = p.document_id
                WHERE d.is_active = 1 AND (d.kind = 'lecture' OR d.kind IS NULL OR d.kind = '')
                  AND p.usable = 1
                  AND p.document_id IN ({marks})
                  AND p.body IS NOT NULL
                  AND TRIM(p.body) <> ''
                ORDER BY d.position, p.document_id, p.page_number
                """,
                ids,
            )
            catalog = list(cursor.fetchall())
    finally:
        connection.close()
    if not catalog:
        return []

    by_doc: dict[int, list[dict]] = {}
    for row in catalog:
        by_doc.setdefault(int(row["document_id"]), []).append(row)

    per_doc = max(2, limit // max(len(by_doc), 1))
    chosen_keys: list[tuple[int, int]] = []
    for pages in by_doc.values():
        count = len(pages)
        if count <= per_doc:
            picks = pages
        else:
            # Evenly spaced samples: start → early → mid → later
            indexes = sorted(
                {
                    0,
                    count // 4,
                    count // 2,
                    (3 * count) // 4,
                    count - 1,
                }
            )[:per_doc]
            while len(indexes) < per_doc and len(indexes) < count:
                nxt = min(indexes[-1] + 1, count - 1)
                if nxt in indexes:
                    break
                indexes.append(nxt)
            picks = [pages[i] for i in indexes[:per_doc]]
        for row in picks:
            chosen_keys.append((int(row["document_id"]), int(row["page_number"])))
        if len(chosen_keys) >= limit:
            break

    chosen_keys = chosen_keys[:limit]
    bodies = load_page_bodies(chosen_keys)
    overview = []
    for key in chosen_keys:
        row = bodies.get(key)
        if row is None:
            continue
        overview.append(row)
    return overview


def insert_record(
    course_id: int,
    user_id: int,
    question: str,
    answer: str,
    cited_pages: list[dict],
    refused: bool,
    web_sources: list[dict] | None = None,
    origin: str = "",
    tab_id: str | None = None,
    tab_title: str | None = None,
) -> dict:
    ensure_qa_tabs()
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
    chosen_tab = str(tab_id or "").strip() or str(uuid.uuid4())
    title = str(tab_title or "").strip() or _title_from_question(question)
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tab_title
                FROM qa_records
                WHERE course_id = %s AND user_id = %s AND tab_id = %s
                  AND tab_title IS NOT NULL AND TRIM(tab_title) <> ''
                ORDER BY id ASC
                LIMIT 1
                """,
                (course_id, user_id, chosen_tab),
            )
            existing = cursor.fetchone()
            if existing and existing.get("tab_title"):
                title = str(existing["tab_title"])
            cursor.execute(
                """
                INSERT INTO qa_records
                  (course_id, user_id, question, answer, cited_pages, web_sources,
                   refused, origin, tab_id, tab_title)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    chosen_tab,
                    title[:255],
                ),
            )
            record_id = cursor.lastrowid
        connection.commit()
        return {
            "qa_id": int(record_id),
            "tab_id": chosen_tab,
            "tab_title": title[:255],
        }
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


def ensure_qa_tabs() -> None:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            _add_column(cursor, "web_sources", "TEXT NULL")
            _add_column(cursor, "origin", "VARCHAR(32) NULL")
            _add_column(cursor, "tab_id", "VARCHAR(64) NULL")
            _add_column(cursor, "tab_title", "VARCHAR(255) NULL")
            cursor.execute(
                """
                SELECT id, question
                FROM qa_records
                WHERE tab_id IS NULL OR tab_id = ''
                """
            )
            missing = list(cursor.fetchall())
            for row in missing:
                cursor.execute(
                    """
                    UPDATE qa_records
                    SET tab_id = %s, tab_title = %s
                    WHERE id = %s
                    """,
                    (
                        str(uuid.uuid4()),
                        _title_from_question(str(row["question"] or "")),
                        int(row["id"]),
                    ),
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _ensure_web_sources() -> None:
    ensure_qa_tabs()


def recent_turns(
    user_id: int,
    course_id: int,
    limit: int = 10,
    tab_id: str | None = None,
) -> list[dict]:
    if str(tab_id or "").strip():
        ensure_qa_tabs()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT question, answer, cited_pages FROM qa_records
                WHERE course_id = %s AND user_id = %s
                """
            params: list = [course_id, user_id]
            chosen = str(tab_id or "").strip()
            if chosen:
                sql += " AND tab_id = %s"
                params.append(chosen)
            sql += " ORDER BY id DESC LIMIT %s"
            params.append(limit)
            cursor.execute(sql, params)
            rows = list(cursor.fetchall())
            cursor.execute("SELECT id FROM documents WHERE course_id = %s AND is_active = 1 AND (kind = 'lecture' OR kind IS NULL OR kind = '')", (course_id,))
            active = {int(row["id"]) for row in cursor.fetchall()}
    finally:
        connection.close()
    rows.reverse()
    memory = []
    for row in rows:
        references = row.get("cited_pages")
        if isinstance(references, (bytes, bytearray)):
            references = references.decode("utf-8", errors="replace")
        if isinstance(references, str):
            try:
                references = json.loads(references)
            except ValueError:
                continue
        references = references or []
        if not isinstance(references, list):
            continue
        try:
            available = all(isinstance(source, dict) and int(source["document_id"]) in active for source in references)
        except (KeyError, ValueError, TypeError):
            available = False
        if available:
            memory.append({"question": row["question"], "answer": row["answer"]})
    return memory


def delete_tab(user_id: int, course_id: int, tab_id: str) -> None:
    from db.courses import get_course

    course = get_course(user_id, course_id)
    if course is None:
        raise LookupError("Course not found")
    chosen = str(tab_id or "").strip()
    if not chosen:
        raise ValueError("Chat not found")
    ensure_qa_tabs()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM qa_records
                WHERE course_id = %s AND user_id = %s AND tab_id = %s
                """,
                (course_id, user_id, chosen),
            )
            if cursor.rowcount == 0:
                raise LookupError("Chat not found")
        connection.commit()
    finally:
        connection.close()


def list_records(user_id: int, course_id: int) -> list[dict]:
    from db.courses import get_course

    course = get_course(user_id, course_id)
    if course is None:
        raise LookupError("Course not found")
    ensure_qa_tabs()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, question, answer, cited_pages, web_sources, refused, origin,
                       tab_id, tab_title, created_at
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
                document = {"id": int(item.get("document_id") or 0), "position": None, "filename": "Unavailable original document"}
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
                "tab_id": str(row.get("tab_id") or ""),
                "tab_title": str(row.get("tab_title") or _title_from_question(row["question"])),
                "created_at": created.strftime("%Y-%m-%d %H:%M") if hasattr(created, "strftime") else str(created or ""),
            }
        )
    return records


def _title_from_question(question: str) -> str:
    text = " ".join(str(question or "").split())
    if not text:
        return "New chat"
    return text[:72]


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
