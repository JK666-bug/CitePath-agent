"""Persist feedback separately from immutable answer grades and round scores."""
import json

from db.connection import connect

PLACEHOLDER = "Review the cited page."
ERROR_MESSAGE = "The explanation could not be generated. Your grade is saved; retry the explanation."
FEEDBACK_FIELDS = {"explanation", "explanation_status", "explanation_error", "explanation_attempts"}


def ensure_feedback_columns(cursor, table: str) -> None:
    if table not in {"practice_answers", "exam_answers"}:
        raise ValueError("Invalid feedback table")
    for name, definition in (
        ("explanation_status", "VARCHAR(16) NOT NULL DEFAULT 'pending'"),
        ("explanation_error", "VARCHAR(255) NULL"),
        ("explanation_attempts", "INT NOT NULL DEFAULT 0"),
        ("rubric_hits_json", "JSON NULL"),
    ):
        cursor.execute(
            """SELECT COUNT(*) AS n FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
            (table, name),
        )
        if int(cursor.fetchone()["n"]) == 0:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def feedback_fields(row: dict) -> dict:
    text = str(row.get("explanation") or "").strip()
    if text == PLACEHOLDER:
        text = ""
    attempts = int(row.get("explanation_attempts") or 0)
    status = row.get("explanation_status")
    if row.get("correct"):
        return {"explanation": "", "explanation_status": "not_required",
                "explanation_error": None, "explanation_attempts": attempts}
    # Pre-migration non-placeholder explanations remain usable. Blank legacy
    # placeholders are pending, not retrospectively treated as valid feedback.
    if text and (status == "ready" or (attempts == 0 and status in {None, "pending"})):
        status = "ready"
    elif status not in {"pending", "failed"}:
        status = "pending"
    return {"explanation": text if status == "ready" else "",
            "explanation_status": status,
            "explanation_error": row.get("explanation_error") if status == "failed" else None,
            "explanation_attempts": attempts}


def with_feedback(report: dict, question_id: int, fields: dict) -> dict:
    """Only explanation fields and derived prose may change after publication."""
    copied = json.loads(json.dumps(report))
    for name in ("questions", "wrong"):
        for question in copied.get(name) or []:
            if int(question.get("question_id") or question.get("id") or 0) == question_id:
                question.update({key: value for key, value in fields.items() if key in FEEDBACK_FIELDS})
    from agent.report_text import enrich_report
    return enrich_report(copied)


def begin_explanation_attempt(kind: str, question_id: int) -> None:
    answers, containers, relation = _tables(kind)
    questions = "practice_questions" if kind == "practice" else "exam_questions"
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""SELECT a.correct, a.explanation, a.explanation_status,
                           a.explanation_error, a.explanation_attempts, q.{relation} AS container_id
                    FROM {answers} a JOIN {questions} q ON q.id = a.question_id
                    WHERE a.question_id = %s FOR UPDATE""", (question_id,),
            )
            saved = cursor.fetchone()
            if saved is None:
                raise LookupError("Saved answer not found")
            if saved["correct"]:
                raise ValueError("Correct answers do not require remedial explanations")
            cursor.execute(
                f"""UPDATE {answers} SET explanation_status = 'pending',
                    explanation_error = NULL, explanation_attempts = explanation_attempts + 1
                    WHERE question_id = %s AND correct = 0""", (question_id,),
            )
            pending = {"explanation": "", "explanation_status": "pending",
                       "explanation_error": None,
                       "explanation_attempts": int(saved.get("explanation_attempts") or 0) + 1}
            _update_report(cursor, containers, int(saved["container_id"]), question_id, pending)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def complete_explanation_attempt(kind: str, container_id: int, question_id: int,
                                 explanation: str | None) -> None:
    answers, containers, relation = _tables(kind)
    questions = "practice_questions" if kind == "practice" else "exam_questions"
    text = str(explanation or "").strip()
    if text == PLACEHOLDER:
        text = ""
    status = "ready" if text else "failed"
    connection = connect()
    try:
        with connection.cursor() as cursor:
            # Guard the association here as well as at the public owned-session
            # boundary. A wrong container must never update another answer.
            cursor.execute(
                f"""SELECT a.correct FROM {answers} a
                    JOIN {questions} q ON q.id = a.question_id
                    WHERE a.question_id = %s AND q.{relation} = %s FOR UPDATE""",
                (question_id, container_id),
            )
            original = cursor.fetchone()
            if original is None:
                raise LookupError("Saved answer not found in this session")
            if original["correct"]:
                raise ValueError("Correct answers do not require remedial explanations")
            cursor.execute(
                f"""UPDATE {answers} SET explanation = %s, explanation_status = %s,
                    explanation_error = %s WHERE question_id = %s AND correct = 0""",
                (text or None, status, None if text else ERROR_MESSAGE, question_id),
            )
            cursor.execute(
                f"SELECT correct, explanation, explanation_status, explanation_error, explanation_attempts FROM {answers} WHERE question_id = %s",
                (question_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise LookupError("Saved answer not found")
            fields = feedback_fields(row)
            _update_report(cursor, containers, container_id, question_id, fields)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _update_report(cursor, containers: str, container_id: int, question_id: int, fields: dict) -> None:
    cursor.execute(f"SELECT report_json FROM {containers} WHERE id = %s FOR UPDATE", (container_id,))
    saved = cursor.fetchone()
    report = _object(saved["report_json"]) if saved else None
    if report:
        updated = with_feedback(report, question_id, fields)
        cursor.execute(f"UPDATE {containers} SET report_json = %s WHERE id = %s",
                       (json.dumps(updated, ensure_ascii=False), container_id))


def _tables(kind):
    if kind == "practice":
        return "practice_answers", "practice_sessions", "session_id"
    if kind == "exam":
        return "exam_answers", "exams", "exam_id"
    raise ValueError("Invalid feedback kind")


def _object(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()
    if isinstance(value, str):
        try:
            data = json.loads(value)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    return None
