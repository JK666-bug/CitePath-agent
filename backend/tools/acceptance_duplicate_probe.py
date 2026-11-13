"""Verify duplicate submission on an already finished live practice session."""
import json
import sys
from pathlib import Path

import httpx

FIXTURE = Path(sys.argv[1])
COURSE_ID = int(sys.argv[2])
SESSION_ID = int(sys.argv[3])
OUT = Path(sys.argv[4])


def main():
    credentials = json.loads(FIXTURE.read_text(encoding="utf-8"))
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=60.0) as client:
        login = client.post("/api/login", json={
            "username": credentials["username"], "password": credentials["password"],
        })
        login.raise_for_status()
        before = client.get(f"/api/courses/{COURSE_ID}/practice/{SESSION_ID}").json()
        report = before.get("report") or {}
        question_id = int(report["questions"][0]["question_id"])
        rounds_before = report.get("rounds")
        duplicate = client.post(
            f"/api/courses/{COURSE_ID}/practice/{SESSION_ID}/answer",
            json={"question_id": question_id, "response": "A"},
        )
        body = duplicate.json()
        rounds_after = (body.get("report") or {}).get("rounds")
        after = client.get(f"/api/courses/{COURSE_ID}/practice/{SESSION_ID}").json()
        result = {
            "duplicate_status": duplicate.status_code,
            "already_finished_returned": body.get("status") == "finished",
            "rounds_unchanged": rounds_before == rounds_after,
            "refresh_rounds_unchanged": rounds_before == (after.get("report") or {}).get("rounds"),
            "answered_count": body.get("answered_count"),
            "round_question_count": body.get("round_question_count"),
        }
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
