import json

from db.connection import connect
from db.courses import get_course

_ready = False


def ensure_exam_storage() -> None:
    global _ready
    if _ready:
        return
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS exams (
                  id INT PRIMARY KEY AUTO_INCREMENT,
                  course_id INT NOT NULL,
                  user_id INT NOT NULL,
                  chapter_id INT NOT NULL,
                  chapter_title VARCHAR(255) NOT NULL,
                  status VARCHAR(16) NOT NULL,
                  score INT NULL,
                  passed TINYINT(1) NULL,
                  report_json JSON NULL,
                  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  finished_at DATETIME NULL,
                  CONSTRAINT fk_exams_course FOREIGN KEY (course_id) REFERENCES courses (id) ON DELETE CASCADE,
                  CONSTRAINT fk_exams_user FOREIGN KEY (user_id) REFERENCES users (id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS exam_questions (
                  id INT PRIMARY KEY AUTO_INCREMENT,
                  exam_id INT NOT NULL,
                  position INT NOT NULL,
                  concept_id INT NULL,
                  concept_name VARCHAR(255) NOT NULL,
                  kind VARCHAR(16) NOT NULL,
                  prompt TEXT NOT NULL,
                  options_json JSON NULL,
                  answer TEXT NOT NULL,
                  rubric_json JSON NULL,
                  sources_json JSON NOT NULL,
                  UNIQUE KEY uq_exam_question_pos (exam_id, position),
                  CONSTRAINT fk_exam_questions_exam FOREIGN KEY (exam_id) REFERENCES exams (id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS exam_answers (
                  id INT PRIMARY KEY AUTO_INCREMENT,
                  question_id INT NOT NULL,
                  response TEXT NOT NULL,
                  correct TINYINT(1) NOT NULL,
                  points_hit INT NOT NULL,
                  points_total INT NOT NULL,
                  explanation TEXT NULL,
                  UNIQUE KEY uq_exam_answer_question (question_id),
                  CONSTRAINT fk_exam_answers_question FOREIGN KEY (question_id) REFERENCES exam_questions (id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS exam_drafts (
                  question_id INT PRIMARY KEY,
                  response TEXT NOT NULL,
                  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  CONSTRAINT fk_exam_drafts_question FOREIGN KEY (question_id) REFERENCES exam_questions (id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    _ready = True


def load_chapter(user_id: int, course_id: int, chapter_id: int) -> dict:
    if get_course(user_id, course_id) is None:
        raise LookupError("Course not found")
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
                SELECT id, name
                FROM plan_concepts
                WHERE chapter_id = %s
                ORDER BY position, id
                """,
                (chapter_id,),
            )
            concepts = [
                {"id": int(row["id"]), "name": row["name"]}
                for row in cursor.fetchall()
            ]
            cursor.execute(
                """
                SELECT p.document_id, p.page_number, d.filename, d.position, pages.body
                FROM plan_chapter_pages p
                JOIN documents d ON d.id = p.document_id
                JOIN pages ON pages.document_id = p.document_id
                  AND pages.page_number = p.page_number
                WHERE p.chapter_id = %s
                  AND pages.usable = 1
                  AND pages.body IS NOT NULL
                  AND TRIM(pages.body) <> ''
                ORDER BY p.position, p.id
                """,
                (chapter_id,),
            )
            pages = list(cursor.fetchall())
    finally:
        connection.close()
    if not concepts or not pages:
        raise ValueError("This chapter has no concepts or readable pages to examine")
    return {
        "id": int(chapter["id"]),
        "title": chapter["title"],
        "concepts": concepts,
        "pages": pages,
    }


def save_exam(user_id: int, course_id: int, chapter: dict, questions: list[dict]) -> dict:
    ensure_exam_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO exams (course_id, user_id, chapter_id, chapter_title, status)
                VALUES (%s, %s, %s, %s, 'open')
                """,
                (course_id, user_id, chapter["id"], chapter["title"]),
            )
            exam_id = int(cursor.lastrowid)
            for index, question in enumerate(questions, start=1):
                cursor.execute(
                    """
                    INSERT INTO exam_questions (
                      exam_id, position, concept_id, concept_name, kind,
                      prompt, options_json, answer, rubric_json, sources_json
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        exam_id,
                        index,
                        question.get("concept_id"),
                        question["concept_name"],
                        question["kind"],
                        question["prompt"],
                        json.dumps(question.get("options") or [], ensure_ascii=False),
                        question["answer"],
                        json.dumps(question.get("rubric") or [], ensure_ascii=False),
                        json.dumps(question["sources"], ensure_ascii=False),
                    ),
                )
                question["id"] = int(cursor.lastrowid)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return public_exam(get_owned_exam(user_id, course_id, exam_id))


def get_owned_exam(user_id: int, course_id: int, exam_id: int) -> dict:
    ensure_exam_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, course_id, chapter_id, chapter_title, status,
                       score, passed, report_json
                FROM exams
                WHERE id = %s AND course_id = %s AND user_id = %s
                """,
                (exam_id, course_id, user_id),
            )
            exam = cursor.fetchone()
            if exam is None:
                raise LookupError("Exam not found")
            cursor.execute(
                """
                SELECT q.id, q.position, q.concept_name, q.kind, q.prompt,
                       q.options_json, q.answer, q.rubric_json, q.sources_json,
                       a.response, a.correct, a.points_hit, a.points_total, a.explanation,
                       d.response AS draft_response
                FROM exam_questions q
                LEFT JOIN exam_answers a ON a.question_id = q.id
                LEFT JOIN exam_drafts d ON d.question_id = q.id
                WHERE q.exam_id = %s
                ORDER BY q.position, q.id
                """,
                (exam_id,),
            )
            exam["questions"] = list(cursor.fetchall())
    finally:
        connection.close()
    return exam


def finish_exam(user_id: int, course_id: int, exam_id: int, report: dict, graded: list[dict]) -> dict:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status
                FROM exams
                WHERE id = %s AND course_id = %s AND user_id = %s
                """,
                (exam_id, course_id, user_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise LookupError("Exam not found")
            if row["status"] != "open":
                connection.rollback()
                stored = get_owned_exam(user_id, course_id, exam_id)
                return public_exam(stored)
            cursor.executemany(
                """
                INSERT INTO exam_answers (
                  question_id, response, correct, points_hit, points_total, explanation
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        item["question_id"],
                        item["response"],
                        1 if item["correct"] else 0,
                        item["points_hit"],
                        item["points_total"],
                        item.get("explanation") or None,
                    )
                    for item in graded
                ],
            )
            cursor.execute(
                """
                DELETE drafts
                FROM exam_drafts drafts
                JOIN exam_questions questions ON questions.id = drafts.question_id
                WHERE questions.exam_id = %s
                """,
                (exam_id,),
            )
            cursor.execute(
                """
                UPDATE exams
                SET status = 'finished',
                    score = %s,
                    passed = %s,
                    report_json = %s,
                    finished_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    report["score"],
                    1 if report["passed"] else 0,
                    json.dumps(report, ensure_ascii=False),
                    exam_id,
                ),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return public_exam(get_owned_exam(user_id, course_id, exam_id))


def public_exam(exam: dict) -> dict:
    finished = exam["status"] == "finished"
    report = _json(exam.get("report_json")) if finished else None
    questions = []
    for question in exam["questions"]:
        item = {
            "id": int(question["id"]),
            "position": int(question["position"]),
            "concept_name": question["concept_name"],
            "kind": question["kind"],
            "prompt": question["prompt"],
            "options": _json(question["options_json"]) or [],
            "sources": _json(question["sources_json"]) or [],
        }
        if finished:
            item["response"] = question.get("response") or ""
            item["correct"] = bool(question.get("correct"))
            item["answer"] = question["answer"]
            item["rubric"] = _json(question["rubric_json"]) or []
            item["explanation"] = question.get("explanation") or ""
            item["points_hit"] = int(question.get("points_hit") or 0)
            item["points_total"] = int(question.get("points_total") or 0)
        elif question.get("draft_response"):
            item["response"] = question["draft_response"]
        questions.append(item)
    return {
        "id": int(exam["id"]),
        "course_id": int(exam["course_id"]),
        "chapter_id": int(exam["chapter_id"]),
        "chapter_title": exam["chapter_title"],
        "status": exam["status"],
        "score": None if exam.get("score") is None else int(exam["score"]),
        "passed": None if exam.get("passed") is None else bool(exam["passed"]),
        "report": report,
        "questions": questions,
    }


def _json(value):
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def save_drafts(user_id: int, course_id: int, exam_id: int, answers: list[dict]) -> dict:
    exam = get_owned_exam(user_id, course_id, exam_id)
    if exam["status"] != "open":
        return public_exam(exam)
    allowed = {int(question["id"]) for question in exam["questions"]}
    connection = connect()
    try:
        with connection.cursor() as cursor:
            for item in answers:
                question_id = int(item.get("question_id") or 0)
                if question_id not in allowed:
                    continue
                cursor.execute(
                    """
                    INSERT INTO exam_drafts (question_id, response)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE response = VALUES(response)
                    """,
                    (question_id, str(item.get("response") or "")[:5000]),
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return public_exam(get_owned_exam(user_id, course_id, exam_id))
