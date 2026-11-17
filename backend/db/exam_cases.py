import hashlib

from db.connection import connect
from db.courses import get_course
from db.uploads import (
    ensure_document_kinds,
    ensure_document_numbers,
    existing_upload,
    save_document,
)
from vector.segments import delete_segments


ANSWER_MODES = {"none", "in_case", "file"}


def list_exam_cases(user_id: int, course_id: int) -> list[dict]:
    ensure_document_kinds()
    course = get_course(user_id, course_id)
    if course is None:
        raise LookupError("Course not found")
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT d.id, d.position, d.filename, d.ingest_status, d.answer_mode,
                       COUNT(p.id) AS page_count,
                       SUM(CASE WHEN p.usable = 1 THEN 1 ELSE 0 END) AS usable_page_count
                FROM documents d
                LEFT JOIN pages p ON p.document_id = d.id
                WHERE d.course_id = %s AND d.kind = 'exam_case'
                GROUP BY d.id, d.position, d.filename, d.ingest_status, d.answer_mode
                ORDER BY d.position, d.id
                """,
                (course_id,),
            )
            cases = list(cursor.fetchall())
            answers = {}
            if cases:
                marks = ", ".join(["%s"] * len(cases))
                cursor.execute(
                    f"""
                    SELECT id, parent_id, filename, ingest_status,
                           (SELECT COUNT(*) FROM pages WHERE document_id = documents.id) AS page_count,
                           (SELECT SUM(usable = 1) FROM pages WHERE document_id = documents.id) AS usable_page_count
                    FROM documents
                    WHERE course_id = %s AND kind = 'case_answer' AND parent_id IN ({marks})
                    """,
                    [course_id, *[int(row["id"]) for row in cases]],
                )
                for row in cursor.fetchall():
                    answers[int(row["parent_id"])] = {
                        "id": int(row["id"]),
                        "filename": row["filename"],
                        "ingest_status": row["ingest_status"],
                        "page_count": int(row["page_count"] or 0),
                        "usable_page_count": int(row["usable_page_count"] or 0),
                    }
    finally:
        connection.close()
    return [
        {
            "id": int(row["id"]),
            "position": int(row["position"]),
            "filename": row["filename"],
            "ingest_status": row["ingest_status"],
            "answer_mode": row["answer_mode"] or "none",
            "page_count": int(row["page_count"] or 0),
            "usable_page_count": int(row["usable_page_count"] or 0),
            "answer_file": answers.get(int(row["id"])),
        }
        for row in cases
    ]


def save_exam_case(
    user_id: int,
    course_id: int,
    filename: str,
    pages: list[dict],
    content_hash: str,
    answer_mode: str,
    answer_filename: str | None = None,
    answer_pages: list[dict] | None = None,
    answer_hash: str | None = None,
    pdf_bytes: bytes | None = None,
    answer_pdf_bytes: bytes | None = None,
) -> dict:
    if get_course(user_id, course_id) is None:
        raise LookupError("Course not found")
    mode = str(answer_mode or "none").strip()
    if mode not in ANSWER_MODES:
        raise ValueError("Choose whether this case has no answers, answers in the case, or an answer file")
    if mode == "file" and (not answer_pages or not answer_hash or not answer_filename):
        raise ValueError("Upload an answer PDF for this case")
    if mode != "file":
        answer_pages = None
        answer_hash = None
        answer_filename = None
        answer_pdf_bytes = None

    case = save_document(
        course_id,
        filename,
        pages,
        content_hash,
        kind="exam_case",
        answer_mode=mode,
        pdf_bytes=pdf_bytes,
    )
    if case.get("duplicate"):
        return {**case, "answer_mode": mode, "answer_file": None}

    answer_file = None
    if mode == "file" and answer_pages is not None and answer_hash and answer_filename:
        answer = save_document(
            course_id,
            answer_filename,
            answer_pages,
            answer_hash,
            kind="case_answer",
            parent_id=int(case["document_id"]),
            pdf_bytes=answer_pdf_bytes,
        )
        answer_file = {
            "id": int(answer["document_id"]),
            "filename": answer["filename"],
            "ingest_status": "complete",
            "page_count": int(answer["page_count"]),
            "usable_page_count": int(answer["usable_page_count"]),
            "duplicate": bool(answer.get("duplicate")),
        }
    return {
        **case,
        "answer_mode": mode,
        "answer_file": answer_file,
    }


def delete_exam_case(user_id: int, course_id: int, document_id: int) -> None:
    ensure_document_kinds()
    if get_course(user_id, course_id) is None:
        raise LookupError("Course not found")
    remove_ids: list[int] = []
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM documents
                WHERE id = %s AND course_id = %s AND kind = 'exam_case'
                """,
                (document_id, course_id),
            )
            if cursor.fetchone() is None:
                raise LookupError("Exam case not found")
            cursor.execute(
                "SELECT id FROM documents WHERE parent_id = %s AND kind = 'case_answer'",
                (document_id,),
            )
            child_ids = [int(row["id"]) for row in cursor.fetchall()]
            remove_ids = child_ids + [int(document_id)]
            marks = ", ".join(["%s"] * len(remove_ids))
            cursor.execute(
                f"DELETE FROM pages WHERE document_id IN ({marks})",
                remove_ids,
            )
            cursor.execute(
                f"DELETE FROM documents WHERE id IN ({marks})",
                remove_ids,
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    from db.pdf_store import delete_pdf

    for item in remove_ids:
        delete_pdf(course_id, item)
        try:
            delete_segments(item)
        except Exception:
            pass


def load_case_pages(
    course_id: int,
    document_ids: list[int] | None = None,
    include_answers: bool = False,
) -> list[dict]:
    ensure_document_kinds()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT d.id AS document_id, d.filename, d.kind, d.parent_id, d.answer_mode,
                       d.position, p.page_number, p.body
                FROM documents d
                JOIN pages p ON p.document_id = d.id
                WHERE d.course_id = %s
                  AND d.ingest_status = 'complete'
                  AND p.usable = 1
                  AND p.body IS NOT NULL
                  AND TRIM(p.body) <> ''
                """
            params: list[int | str] = [course_id]
            if include_answers:
                sql += " AND d.kind IN ('exam_case', 'case_answer')"
            else:
                sql += " AND d.kind = 'exam_case'"
            if document_ids is not None:
                ids = [int(item) for item in document_ids]
                if not ids:
                    return []
                marks = ", ".join(["%s"] * len(ids))
                if include_answers:
                    sql += (
                        f" AND (d.id IN ({marks}) OR d.parent_id IN ({marks}))"
                    )
                    params.extend(ids)
                    params.extend(ids)
                else:
                    sql += f" AND d.id IN ({marks})"
                    params.extend(ids)
            sql += " ORDER BY d.position, d.id, p.page_number"
            cursor.execute(sql, params)
            return list(cursor.fetchall())
    finally:
        connection.close()


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
