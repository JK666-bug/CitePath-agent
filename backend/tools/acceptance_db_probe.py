"""Read-only acceptance probe for the local MySQL deployment.

Prints counts only: no usernames, answers, prompts or secrets.
"""
import json
import os

import pymysql


def main():
    connection = pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "citepath_agent"),
        password=os.environ.get("MYSQL_PASSWORD", "citepath_agent"),
        database=os.environ.get("MYSQL_DATABASE", "citepath_agent"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    report = {}
    try:
        with connection.cursor() as cursor:
            for table in (
                "users", "courses", "documents", "pages", "study_plans",
                "plan_versions", "practice_sessions", "practice_questions",
                "practice_answers", "qa_records",
            ):
                cursor.execute(f"SELECT COUNT(*) AS n FROM {table}")
                report[table] = int(cursor.fetchone()["n"])
            cursor.execute(
                "SELECT ingest_status, COUNT(*) AS n, "
                "SUM(is_active = 1) AS active FROM documents GROUP BY ingest_status"
            )
            report["documents_by_status"] = [
                {"status": row["ingest_status"], "count": int(row["n"]),
                 "active": int(row["active"] or 0)}
                for row in cursor.fetchall()
            ]
            cursor.execute(
                "SELECT status, COUNT(*) AS n FROM practice_sessions GROUP BY status"
            )
            report["sessions_by_status"] = {
                row["status"]: int(row["n"]) for row in cursor.fetchall()
            }
            cursor.execute(
                "SELECT JSON_UNQUOTE(JSON_EXTRACT(report_json, '$.outcome')) AS outcome, "
                "COUNT(*) AS n FROM practice_sessions "
                "WHERE report_json IS NOT NULL GROUP BY outcome"
            )
            report["sessions_by_outcome"] = {
                str(row["outcome"]): int(row["n"]) for row in cursor.fetchall()
            }
            cursor.execute(
                "SELECT SUM(workflow_version >= 2) AS v2, "
                "SUM(passing_threshold IS NOT NULL) AS with_threshold "
                "FROM practice_sessions"
            )
            row = cursor.fetchone()
            report["sessions_with_two_round_rules"] = int(row["v2"] or 0)
            report["sessions_with_saved_threshold"] = int(row["with_threshold"] or 0)
            cursor.execute(
                "SELECT MAX(version) AS v FROM plan_versions"
            )
            report["plan_max_version"] = int(cursor.fetchone()["v"] or 0)
            cursor.execute(
                "SELECT COUNT(*) AS n FROM practice_questions q "
                "LEFT JOIN practice_answers a ON a.question_id = q.id "
                "WHERE a.id IS NULL"
            )
            report["practice_questions_without_answer"] = int(cursor.fetchone()["n"])
    finally:
        connection.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
