"""Inspect one live practice session's persisted grading, explanations and logs."""
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parents[1]
SESSION_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 5


def main():
    connection = pymysql.connect(
        host="127.0.0.1", port=3306, user="citepath_agent",
        password="citepath_agent", database="citepath_agent",
        charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n, SUM(a.correct = 1) AS correct, "
                "SUM(a.explanation_status = 'ready') AS ready, "
                "SUM(a.explanation_status = 'failed') AS failed, "
                "SUM(a.explanation_status = 'not_required') AS not_required, "
                "SUM(a.explanation_status = 'pending') AS pending "
                "FROM practice_answers a JOIN practice_questions q ON q.id = a.question_id "
                "WHERE q.session_id = %s", (SESSION_ID,))
            answers = cursor.fetchone()
            cursor.execute(
                "SELECT q.review_round, COUNT(*) AS n, SUM(a.correct = 1) AS correct "
                "FROM practice_questions q LEFT JOIN practice_answers a ON a.question_id = q.id "
                "WHERE q.session_id = %s GROUP BY q.review_round", (SESSION_ID,))
            rounds = cursor.fetchall()
            cursor.execute(
                "SELECT status, review_round, JSON_UNQUOTE(JSON_EXTRACT(report_json, '$.outcome')) AS outcome, "
                "JSON_UNQUOTE(JSON_EXTRACT(report_json, '$.passed')) AS passed "
                "FROM practice_sessions WHERE id = %s", (SESSION_ID,))
            session = cursor.fetchone()
    finally:
        connection.close()
    usage = []
    usage_path = ROOT / "logs" / "model-usage.jsonl"
    for line in usage_path.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        if (item.get("context") or {}).get("session_id") == SESSION_ID:
            usage.append(item)
    operations = []
    ops_path = ROOT / "logs" / "operations.jsonl"
    for line in ops_path.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        if (item.get("context") or {}).get("session_id") == SESSION_ID:
            operations.append(item)
    result = {
        "session": {key: (str(value) if isinstance(value, (bytes, bytearray)) else value)
                    for key, value in session.items()},
        "answers": {key: int(value or 0) for key, value in answers.items()},
        "rounds": [
            {"round": row["review_round"], "n": int(row["n"]), "correct": int(row["correct"] or 0)}
            for row in rounds
        ],
        "model_usage": {
            "calls": len(usage),
            "statuses": dict(Counter(item["status"] for item in usage)),
            "input_tokens": sum(int(item.get("input_tokens") or 0) for item in usage),
            "output_tokens": sum(int(item.get("output_tokens") or 0) for item in usage),
            "median_latency_ms": int(statistics.median(
                [item["latency_ms"] for item in usage if item.get("latency_ms") is not None]
            )) if usage else None,
        },
        "operations": {
            "count": len(operations),
            "operations": dict(Counter((item.get("context") or {}).get("operation") for item in operations)),
            "statuses": dict(Counter(item.get("status") for item in operations)),
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
