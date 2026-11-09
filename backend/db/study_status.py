import json

from db.connection import connect
from db.courses import get_course
from db.exams import ensure_exam_storage
from db.plans import ensure_plan_storage
from db.practice import ensure_practice_storage


def course_study(user_id: int, course_id: int) -> dict:
    if get_course(user_id, course_id) is None:
        raise LookupError("Course not found")
    ensure_plan_storage()
    ensure_practice_storage()
    ensure_exam_storage()
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.id AS chapter_id, c.title AS chapter_title,
                       k.id AS concept_id, k.name AS concept_name,
                       p.level, p.streak
                FROM plan_chapters c
                LEFT JOIN plan_concepts k ON k.chapter_id = c.id
                LEFT JOIN concept_progress p
                  ON p.concept_id = k.id AND p.user_id = %s
                WHERE c.course_id = %s
                ORDER BY c.position, c.id, k.position, k.id
                """,
                (user_id, course_id),
            )
            concept_rows = list(cursor.fetchall())
            cursor.execute(
                """
                SELECT s.chapter_id, s.status,
                       COUNT(DISTINCT s.id) AS sessions,
                       COALESCE(SUM(a.correct = 1), 0) AS correct_count,
                       COALESCE(SUM(a.correct = 0), 0) AS wrong_count
                FROM practice_sessions s
                LEFT JOIN practice_questions q ON q.session_id = s.id
                LEFT JOIN practice_answers a ON a.question_id = q.id
                WHERE s.user_id = %s AND s.course_id = %s
                GROUP BY s.chapter_id, s.status
                """,
                (user_id, course_id),
            )
            practice_rows = list(cursor.fetchall())
            cursor.execute(
                """
                SELECT e.chapter_id, c.title AS chapter_title, e.passed, e.report_json
                FROM exams e
                JOIN plan_chapters c ON c.id = e.chapter_id
                WHERE e.user_id = %s AND e.course_id = %s AND e.status = 'finished'
                ORDER BY e.finished_at DESC, e.id DESC
                """,
                (user_id, course_id),
            )
            exam_rows = list(cursor.fetchall())
            cursor.execute(
                """
                SELECT c.title AS chapter_title, q.concept_name, q.kind, q.prompt,
                       q.answer, q.options_json, a.response, a.explanation
                FROM practice_answers a
                JOIN practice_questions q ON q.id = a.question_id
                JOIN practice_sessions s ON s.id = q.session_id
                JOIN plan_chapters c ON c.id = s.chapter_id
                WHERE s.user_id = %s AND s.course_id = %s AND a.correct = 0
                ORDER BY a.id DESC
                LIMIT 12
                """,
                (user_id, course_id),
            )
            practice_wrongs = list(cursor.fetchall())
    finally:
        connection.close()
    return {
        "chapters": _chapters(concept_rows, practice_rows),
        "practice_wrongs": [_practice_wrong(row) for row in practice_wrongs],
        "exam_wrongs": _exam_wrongs(exam_rows),
        "exams": _exam_counts(exam_rows),
    }


def review_report(record: dict, chapter: str) -> dict:
    chapters, note = _select(record["chapters"], chapter)
    items = []
    for item in chapters:
        counts = record["exams"].get(item["title"], {"taken": 0, "passed": 0})
        items.append(
            {
                "chapter": item["title"],
                "concepts_mastered": item["mastered_concepts"],
                "concepts_total": item["total_concepts"],
                "finished_practice_rounds": item["finished_rounds"],
                "practice_in_progress": item["practice_open"],
                "practice_correct": item["practice_correct"],
                "practice_wrong": item["practice_wrong"],
                "exams_taken": counts["taken"],
                "exams_passed": counts["passed"],
            }
        )
    return _payload(items, record, note)


def concept_report(record: dict, chapter: str) -> dict:
    chapters, note = _select(record["chapters"], chapter)
    items = [
        {
            "chapter": item["title"],
            "concepts": [
                {"name": concept["name"], "status": concept["status"], "label": concept["label"]}
                for concept in item["concepts"]
            ],
        }
        for item in chapters
    ]
    return _payload(items, record, note)


def chapter_report(record: dict, chapter: str) -> dict:
    chapters, note = _select(record["chapters"], chapter)
    items = [
        {
            "chapter": item["title"],
            "mastered_concepts": item["mastered_concepts"],
            "total_concepts": item["total_concepts"],
            "mastered": item["total_concepts"] > 0 and item["mastered_concepts"] == item["total_concepts"],
        }
        for item in chapters
    ]
    return _payload(items, record, note)


def wrong_report(record: dict, chapter: str) -> dict:
    name = chapter.strip().casefold()
    practice = [
        item
        for item in record["practice_wrongs"]
        if not name or name in item["chapter"].casefold()
    ]
    exams = [
        item
        for item in record["exam_wrongs"]
        if not name or name in item["chapter"].casefold()
    ]
    titles = [item["title"] for item in record["chapters"]]
    note = ""
    if name and not practice and not exams and not any(name in title.casefold() for title in titles):
        note = f"No chapter title contains {chapter.strip()}."
    return {
        "note": note,
        "chapters": titles,
        "practice_wrongs": practice,
        "exam_wrongs": exams,
    }


def _payload(items: list[dict], record: dict, note: str) -> dict:
    return {
        "note": note,
        "chapters": [item["title"] for item in record["chapters"]],
        "matches": items,
    }


def _select(chapters: list[dict], chapter: str) -> tuple[list[dict], str]:
    name = chapter.strip().casefold()
    if not name:
        return chapters, ""
    matched = [item for item in chapters if name in item["title"].casefold()]
    if matched:
        return matched, ""
    return [], f"No chapter title contains {chapter.strip()}."


def _chapters(concept_rows: list[dict], practice_rows: list[dict]) -> list[dict]:
    practice: dict[int, dict] = {}
    for row in practice_rows:
        state = practice.setdefault(
            int(row["chapter_id"]),
            {
                "finished_rounds": 0,
                "practice_open": False,
                "practice_correct": 0,
                "practice_wrong": 0,
            },
        )
        if row["status"] == "finished":
            state["finished_rounds"] = int(row["sessions"] or 0)
            state["practice_correct"] = int(row["correct_count"] or 0)
            state["practice_wrong"] = int(row["wrong_count"] or 0)
        elif row["status"] == "open" and int(row["sessions"] or 0) > 0:
            state["practice_open"] = True
    chapters: dict[int, dict] = {}
    order: list[int] = []
    for row in concept_rows:
        chapter_id = int(row["chapter_id"])
        if chapter_id not in chapters:
            order.append(chapter_id)
            counts = practice.get(chapter_id, {})
            chapters[chapter_id] = {
                "title": row["chapter_title"],
                "concepts": [],
                "mastered_concepts": 0,
                "total_concepts": 0,
                "finished_rounds": int(counts.get("finished_rounds") or 0),
                "practice_open": bool(counts.get("practice_open")),
                "practice_correct": int(counts.get("practice_correct") or 0),
                "practice_wrong": int(counts.get("practice_wrong") or 0),
            }
        if row["concept_id"] is None:
            continue
        status, label = mastery_label(row["level"], row["streak"])
        chapters[chapter_id]["concepts"].append(
            {"name": row["concept_name"], "status": status, "label": label}
        )
        chapters[chapter_id]["total_concepts"] += 1
        if status == 2:
            chapters[chapter_id]["mastered_concepts"] += 1
    return [chapters[chapter_id] for chapter_id in order]


def mastery_label(level, streak) -> tuple[int, str]:
    if int(level or 0) >= 2:
        return 2, "Mastered"
    if int(streak or 0) >= 1:
        return 1, "One correct, not yet mastered"
    return 0, "Not mastered"


def _exam_counts(rows: list[dict]) -> dict[str, dict]:
    counts: dict[str, dict] = {}
    for row in rows:
        state = counts.setdefault(row["chapter_title"], {"taken": 0, "passed": 0})
        state["taken"] += 1
        if row["passed"]:
            state["passed"] += 1
    return counts


def _exam_wrongs(rows: list[dict]) -> list[dict]:
    wrongs = []
    for row in rows:
        report = _json_object(row["report_json"]) or {}
        for item in report.get("wrong") or []:
            if not isinstance(item, dict):
                continue
            wrongs.append(
                {
                    "chapter": row["chapter_title"],
                    "concept": str(item.get("concept_name") or ""),
                    "prompt": _clip(item.get("prompt")),
                    "response": _clip(item.get("response")),
                    "answer": _clip(item.get("answer")),
                    "explanation": _clip(item.get("explanation")),
                }
            )
            if len(wrongs) >= 12:
                return wrongs
    return wrongs


def _practice_wrong(row: dict) -> dict:
    answer = str(row["answer"] or "")
    if row["kind"] == "mcq":
        options = _json_list(row["options_json"])
        index = ord(answer[:1].upper()) - 65 if answer else -1
        if 0 <= index < len(options):
            answer = f"{answer[:1].upper()}. {options[index]}"
    return {
        "chapter": row["chapter_title"],
        "concept": row["concept_name"],
        "prompt": _clip(row["prompt"]),
        "response": _clip(row["response"]),
        "answer": _clip(answer),
        "explanation": _clip(row["explanation"]),
    }


def _clip(value) -> str:
    return str(value or "").strip()[:500]


def _json_object(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []
