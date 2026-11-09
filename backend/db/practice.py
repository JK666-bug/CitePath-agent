import json

from db.connection import connect
from db.courses import get_course

_ready = False


def ensure_practice_storage() -> None:
    global _ready
    if _ready:
        return
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS concept_progress (
                  user_id INT NOT NULL,
                  concept_id INT NOT NULL,
                  level TINYINT NOT NULL,
                  streak INT NOT NULL,
                  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  PRIMARY KEY (user_id, concept_id),
                  CONSTRAINT fk_concept_progress_user FOREIGN KEY (user_id) REFERENCES users (id),
                  CONSTRAINT fk_concept_progress_concept FOREIGN KEY (concept_id) REFERENCES plan_concepts (id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS practice_sessions (
                  id INT PRIMARY KEY AUTO_INCREMENT,
                  course_id INT NOT NULL,
                  user_id INT NOT NULL,
                  chapter_id INT NOT NULL,
                  chapter_title VARCHAR(255) NOT NULL,
                  status VARCHAR(16) NOT NULL,
                  phase VARCHAR(16) NOT NULL,
                  review_round INT NOT NULL,
                  review_queue_json JSON NOT NULL,
                  report_json JSON NULL,
                  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  finished_at DATETIME NULL,
                  CONSTRAINT fk_practice_sessions_course FOREIGN KEY (course_id) REFERENCES courses (id) ON DELETE CASCADE,
                  CONSTRAINT fk_practice_sessions_user FOREIGN KEY (user_id) REFERENCES users (id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS practice_questions (
                  id INT PRIMARY KEY AUTO_INCREMENT,
                  session_id INT NOT NULL,
                  position INT NOT NULL,
                  concept_id INT NULL,
                  concept_name VARCHAR(255) NOT NULL,
                  phase VARCHAR(16) NOT NULL,
                  review_round INT NOT NULL,
                  kind VARCHAR(16) NOT NULL,
                  prompt TEXT NOT NULL,
                  options_json JSON NULL,
                  answer TEXT NOT NULL,
                  rubric_json JSON NULL,
                  sources_json JSON NOT NULL,
                  UNIQUE KEY uq_practice_question_pos (session_id, position),
                  CONSTRAINT fk_practice_questions_session FOREIGN KEY (session_id) REFERENCES practice_sessions (id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS practice_answers (
                  id INT PRIMARY KEY AUTO_INCREMENT,
                  question_id INT NOT NULL,
                  response TEXT NOT NULL,
                  correct TINYINT(1) NOT NULL,
                  points_hit INT NOT NULL,
                  points_total INT NOT NULL,
                  explanation TEXT NULL,
                  UNIQUE KEY uq_practice_answer_question (question_id),
                  CONSTRAINT fk_practice_answers_question FOREIGN KEY (question_id) REFERENCES practice_questions (id) ON DELETE CASCADE
                )                 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                SELECT COUNT(*) AS column_count
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'practice_sessions'
                  AND COLUMN_NAME = 'report_json'
                """
            )
            if int(cursor.fetchone()["column_count"]) == 0:
                cursor.execute("ALTER TABLE practice_sessions ADD COLUMN report_json JSON NULL")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    _ready = True


def delete_chapter_sessions(cursor, chapter_ids: list[int]) -> None:
    if not chapter_ids:
        return
    marks = ", ".join(["%s"] * len(chapter_ids))
    cursor.execute(
        f"DELETE FROM practice_sessions WHERE chapter_id IN ({marks})",
        chapter_ids,
    )


def progress_map(user_id: int, concept_ids: list[int]) -> dict[int, dict]:
    if not concept_ids:
        return {}
    ensure_practice_storage()
    marks = ", ".join(["%s"] * len(concept_ids))
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT concept_id, level, streak, updated_at
                FROM concept_progress
                WHERE user_id = %s AND concept_id IN ({marks})
                """,
                [user_id, *concept_ids],
            )
            return {
                int(row["concept_id"]): {
                    "level": int(row["level"]),
                    "streak": int(row["streak"]),
                    "updated_at": row["updated_at"].isoformat(sep=" ", timespec="seconds")
                    if hasattr(row["updated_at"], "isoformat")
                    else str(row["updated_at"] or ""),
                }
                for row in cursor.fetchall()
            }
    finally:
        connection.close()


def reset_progress(user_id: int, concept_ids: list[int]) -> None:
    if not concept_ids:
        return
    ensure_practice_storage()
    marks = ", ".join(["%s"] * len(concept_ids))
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE concept_progress
                SET level = 0, streak = 0
                WHERE user_id = %s AND concept_id IN ({marks})
                """,
                [user_id, *concept_ids],
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def save_progress(user_id: int, concept_id: int, level: int, streak: int) -> None:
    ensure_practice_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO concept_progress (user_id, concept_id, level, streak)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE level = VALUES(level), streak = VALUES(streak)
                """,
                (user_id, concept_id, level, streak),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def open_session_id(user_id: int, course_id: int, chapter_id: int) -> int | None:
    ensure_practice_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM practice_sessions
                WHERE user_id = %s AND course_id = %s AND chapter_id = %s AND status = 'open'
                ORDER BY id DESC
                LIMIT 1
                """,
                (user_id, course_id, chapter_id),
            )
            row = cursor.fetchone()
    finally:
        connection.close()
    return int(row["id"]) if row else None


def create_session(user_id: int, course_id: int, chapter: dict) -> int:
    ensure_practice_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO practice_sessions (
                  course_id, user_id, chapter_id, chapter_title, status, phase, review_round, review_queue_json
                )
                VALUES (%s, %s, %s, %s, 'open', 'learn', 0, %s)
                """,
                (course_id, user_id, chapter["id"], chapter["title"], "[]"),
            )
            session_id = int(cursor.lastrowid)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return session_id


def get_owned_session(user_id: int, course_id: int, session_id: int) -> dict:
    ensure_practice_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, course_id, user_id, chapter_id, chapter_title, status, phase,
                       review_round, review_queue_json, report_json, created_at, finished_at
                FROM practice_sessions
                WHERE id = %s AND course_id = %s AND user_id = %s
                """,
                (session_id, course_id, user_id),
            )
            row = cursor.fetchone()
    finally:
        connection.close()
    if row is None:
        raise LookupError("Practice not found")
    row["review_queue"] = [
        item
        for item in _json_list(_json_value(row["review_queue_json"]))
        if isinstance(item, dict) and item.get("kind") in {"mcq", "short"}
    ]
    row["report"] = _json_object(_json_value(row["report_json"]))
    return row


def unanswered_question(session_id: int) -> dict | None:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT q.id, q.concept_id, q.concept_name, q.phase, q.review_round, q.kind,
                       q.prompt, q.options_json, q.answer, q.rubric_json, q.sources_json
                FROM practice_questions q
                LEFT JOIN practice_answers a ON a.question_id = q.id
                WHERE q.session_id = %s AND a.id IS NULL
                ORDER BY q.position, q.id
                LIMIT 1
                """,
                (session_id,),
            )
            return cursor.fetchone()
    finally:
        connection.close()


def question_in_session(session_id: int, question_id: int) -> dict | None:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT q.id, q.concept_id, q.phase, q.review_round, a.id AS answer_id
                FROM practice_questions q
                LEFT JOIN practice_answers a ON a.question_id = q.id
                WHERE q.session_id = %s AND q.id = %s
                """,
                (session_id, question_id),
            )
            return cursor.fetchone()
    finally:
        connection.close()


def insert_question(session_id: int, phase: str, review_round: int, question: dict) -> None:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COALESCE(MAX(position), 0) AS last_position FROM practice_questions WHERE session_id = %s",
                (session_id,),
            )
            position = int(cursor.fetchone()["last_position"]) + 1
            cursor.execute(
                """
                INSERT INTO practice_questions (
                  session_id, position, concept_id, concept_name, phase, review_round, kind,
                  prompt, options_json, answer, rubric_json, sources_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    session_id,
                    position,
                    question["concept_id"],
                    question["concept_name"],
                    phase,
                    review_round,
                    question["kind"],
                    question["prompt"],
                    json.dumps(question["options"], ensure_ascii=False),
                    question["answer"],
                    json.dumps(question["rubric"], ensure_ascii=False),
                    json.dumps(question["sources"], ensure_ascii=False),
                ),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def save_answer(question_id: int, response: str, correct: bool, points_hit: int, points_total: int, explanation: str) -> None:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO practice_answers (question_id, response, correct, points_hit, points_total, explanation)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (question_id, response, int(correct), points_hit, points_total, explanation),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def review_correct_count(session_id: int, review_round: int, concept_id: int) -> int | None:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT a.correct
                FROM practice_questions q
                JOIN practice_answers a ON a.question_id = q.id
                WHERE q.session_id = %s AND q.phase = 'review' AND q.review_round = %s AND q.concept_id = %s
                ORDER BY q.position, q.id
                """,
                (session_id, review_round, concept_id),
            )
            rows = cursor.fetchall()
    finally:
        connection.close()
    if len(rows) < 2:
        return None
    return sum(int(row["correct"]) for row in rows[:2])


def store_question(session_id: int, phase: str, review_round: int, queue: list[dict], question: dict) -> None:
    ensure_practice_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE practice_sessions
                SET phase = %s, review_round = %s, review_queue_json = %s
                WHERE id = %s AND status = 'open'
                """,
                (phase, review_round, json.dumps(queue), session_id),
            )
            cursor.execute(
                "SELECT COALESCE(MAX(position), 0) AS last_position FROM practice_questions WHERE session_id = %s",
                (session_id,),
            )
            position = int(cursor.fetchone()["last_position"]) + 1
            cursor.execute(
                """
                INSERT INTO practice_questions (
                  session_id, position, concept_id, concept_name, phase, review_round, kind,
                  prompt, options_json, answer, rubric_json, sources_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    session_id,
                    position,
                    question["concept_id"],
                    question["concept_name"],
                    phase,
                    review_round,
                    question["kind"],
                    question["prompt"],
                    json.dumps(question["options"], ensure_ascii=False),
                    question["answer"],
                    json.dumps(question["rubric"], ensure_ascii=False),
                    json.dumps(question["sources"], ensure_ascii=False),
                ),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def set_phase(session_id: int, phase: str, review_round: int, queue: list[dict]) -> None:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE practice_sessions
                SET phase = %s, review_round = %s, review_queue_json = %s
                WHERE id = %s AND status = 'open'
                """,
                (phase, review_round, json.dumps(queue), session_id),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def load_session_attempts(session_id: int) -> list[dict]:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT q.id, q.concept_id, q.concept_name, q.kind, q.phase, q.prompt,
                       q.answer, q.options_json, q.sources_json,
                       a.response, a.correct, a.explanation
                FROM practice_questions q
                JOIN practice_answers a ON a.question_id = q.id
                WHERE q.session_id = %s
                ORDER BY q.position, q.id
                """,
                (session_id,),
            )
            rows = cursor.fetchall()
    finally:
        connection.close()
    return [_attempt(row) for row in rows]


def _attempt(row: dict) -> dict:
    return {
        "question_id": int(row["id"]),
        "concept_id": int(row["concept_id"]) if row["concept_id"] is not None else None,
        "concept_name": row["concept_name"],
        "kind": row["kind"],
        "phase": row["phase"],
        "prompt": row["prompt"],
        "response": row["response"],
        "options": _json_list(_json_value(row["options_json"])),
        "correct": bool(row["correct"]),
        "answer": _display_answer(row),
        "explanation": row["explanation"] or "",
        "sources": _json_list(_json_value(row["sources_json"])),
    }


def mark_session_finished(session_id: int, user_id: int) -> None:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE practice_sessions
                SET status = 'finished', review_queue_json = %s, finished_at = CURRENT_TIMESTAMP
                WHERE id = %s AND user_id = %s AND status = 'open'
                """,
                ("[]", session_id, user_id),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def publish_session_report(session_id: int, report: dict) -> None:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT created_at, finished_at FROM practice_sessions WHERE id = %s",
                (session_id,),
            )
            times = cursor.fetchone()
            stored = {
                **report,
                "started_at": _clock(times["created_at"]) if times else "",
                "finished_at": _clock(times["finished_at"]) if times else "",
                "session_count": 1,
            }
            cursor.execute(
                "UPDATE practice_sessions SET report_json = %s WHERE id = %s",
                (json.dumps(stored, ensure_ascii=False), session_id),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def list_chapter_reports(user_id: int, course_id: int, chapter_id: int) -> dict:
    from db.exams import ensure_exam_storage

    if get_course(user_id, course_id) is None:
        raise LookupError("Course not found")
    ensure_practice_storage()
    ensure_exam_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, title
                FROM plan_chapters
                WHERE id = %s AND course_id = %s
                """,
                (chapter_id, course_id),
            )
            chapter = cursor.fetchone()
            if chapter is None:
                raise LookupError("Chapter not found")
            cursor.execute(
                """
                SELECT s.id, s.created_at, s.finished_at,
                       COUNT(a.id) AS question_count,
                       COALESCE(SUM(a.correct), 0) AS correct_count
                FROM practice_sessions s
                LEFT JOIN practice_questions q ON q.session_id = s.id
                LEFT JOIN practice_answers a ON a.question_id = q.id
                WHERE s.user_id = %s AND s.course_id = %s AND s.chapter_id = %s AND s.status = 'finished'
                GROUP BY s.id, s.created_at, s.finished_at
                ORDER BY s.finished_at DESC, s.id DESC
                """,
                (user_id, course_id, chapter_id),
            )
            practice_rows = cursor.fetchall()
            cursor.execute(
                """
                SELECT id, score, passed, created_at, finished_at, report_json
                FROM exams
                WHERE user_id = %s AND course_id = %s AND chapter_id = %s AND status = 'finished'
                ORDER BY finished_at DESC, id DESC
                """,
                (user_id, course_id, chapter_id),
            )
            exam_rows = cursor.fetchall()
    finally:
        connection.close()
    practice = []
    for row in practice_rows:
        question_count = int(row["question_count"] or 0)
        correct_count = int(row["correct_count"] or 0)
        practice.append(
            {
                "id": int(row["id"]),
                "started_at": _clock(row["created_at"]),
                "finished_at": _clock(row["finished_at"]),
                "question_count": question_count,
                "correct_count": correct_count,
                "wrong_count": question_count - correct_count,
            }
        )
    exams = []
    for row in exam_rows:
        report = _json_object(_json_value(row["report_json"])) or {}
        exams.append(
            {
                "id": int(row["id"]),
                "started_at": _clock(row["created_at"]),
                "finished_at": _clock(row["finished_at"]),
                "score": None if row["score"] is None else int(row["score"]),
                "passed": bool(row["passed"]),
                "correct_count": int(report.get("correct_count") or 0),
                "total": int(report.get("total") or 0),
                "wrong_count": int(report.get("wrong_count") or 0),
            }
        )
    return {
        "chapter_id": int(chapter["id"]),
        "chapter_title": chapter["title"],
        "practice": practice,
        "exams": exams,
    }


def latest_miss(user_id: int, concept_id: int) -> dict | None:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT q.prompt, a.response, a.explanation
                FROM practice_answers a
                JOIN practice_questions q ON q.id = a.question_id
                JOIN practice_sessions s ON s.id = q.session_id
                WHERE s.user_id = %s AND q.concept_id = %s AND a.correct = 0
                ORDER BY a.id DESC
                LIMIT 1
                """,
                (user_id, concept_id),
            )
            return cursor.fetchone()
    finally:
        connection.close()


def present_session(user_id: int, course_id: int, session_id: int, concepts: list[dict]) -> dict:
    if get_course(user_id, course_id) is None:
        raise LookupError("Course not found")
    session = get_owned_session(user_id, course_id, session_id)
    progress = progress_map(user_id, [int(item["id"]) for item in concepts])
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT q.id, q.concept_name, q.kind, q.prompt, q.options_json, q.sources_json
                FROM practice_questions q
                LEFT JOIN practice_answers a ON a.question_id = q.id
                WHERE q.session_id = %s AND a.id IS NULL
                ORDER BY q.position, q.id
                LIMIT 1
                """,
                (session_id,),
            )
            current = cursor.fetchone()
            cursor.execute(
                """
                SELECT q.concept_name, q.kind, q.answer, q.options_json, a.correct, a.explanation
                FROM practice_answers a
                JOIN practice_questions q ON q.id = a.question_id
                WHERE q.session_id = %s
                ORDER BY a.id DESC
                LIMIT 1
                """,
                (session_id,),
            )
            feedback = cursor.fetchone()
    finally:
        connection.close()
    question = None
    if current is not None:
        question = {
            "id": int(current["id"]),
            "concept_name": current["concept_name"],
            "kind": current["kind"],
            "prompt": current["prompt"],
            "options": _json_list(_json_value(current["options_json"])),
            "sources": _json_list(_json_value(current["sources_json"])),
        }
    last = None
    if feedback is not None:
        last = {
            "concept_name": feedback["concept_name"],
            "correct": bool(feedback["correct"]),
            "explanation": feedback["explanation"] or "",
            "answer": _display_answer(feedback),
        }
    return {
        "id": int(session["id"]),
        "course_id": int(session["course_id"]),
        "chapter_id": int(session["chapter_id"]),
        "chapter_title": session["chapter_title"],
        "status": session["status"],
        "phase": session["phase"],
        "question": question,
        "feedback": None if session["status"] == "finished" else last,
        "report": session["report"] if session["status"] == "finished" else None,
        "concepts": [
            {
                "id": int(item["id"]),
                "name": item["name"],
                "level": int(progress.get(int(item["id"]), {}).get("level") or 0),
                "streak": int(progress.get(int(item["id"]), {}).get("streak") or 0),
            }
            for item in concepts
        ],
    }


def _display_answer(question: dict) -> str:
    answer = str(question["answer"])
    if question["kind"] == "mcq":
        options = _json_list(_json_value(question["options_json"]))
        index = ord(answer[:1].upper()) - 65 if answer else -1
        if 0 <= index < len(options):
            return f"{answer[:1].upper()}. {options[index]}"
    return answer


def _json_object(value) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None
    return None


def _clock(value) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value or "")


def _json_value(value):
    if isinstance(value, (bytes, bytearray)):
        return value.decode()
    return value


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []
    return []
