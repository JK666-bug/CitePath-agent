"""Live practice acceptance against the local API and real model.

Creates one new practice session on the dedicated integration account's course,
answers every question with deliberately weak responses, and verifies the
two-round stop, independent round scores, report data and duplicate-submission
no-rescoring rule. Saves a local JSON record without credentials.
"""
import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
FIXTURE = Path(sys.argv[1])
OUT = Path(sys.argv[2])
COURSE_ID = int(sys.argv[3]) if len(sys.argv) > 3 else 7
CHAPTER_ID = int(sys.argv[4]) if len(sys.argv) > 4 else 6


def call(client, method, path, **kwargs):
    for attempt in range(3):
        try:
            response = client.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            print(f"  request error {type(error).__name__}; retrying", flush=True)
            time.sleep(2)
            continue
        if response.status_code < 500:
            return response
        print(f"  server {response.status_code}: {response.text[:200]}; retrying", flush=True)
        time.sleep(3)
    raise RuntimeError(f"{method} {path} failed after retries")


def main():
    credentials = json.loads(FIXTURE.read_text(encoding="utf-8"))
    record = {"checks": [], "course_id": COURSE_ID, "chapter_id": CHAPTER_ID}
    with httpx.Client(base_url=BASE, timeout=300.0) as client:
        login = call(client, "POST", "/api/login", json={
            "username": credentials["username"], "password": credentials["password"],
        })
        login.raise_for_status()
        print("logged in", flush=True)

        started = call(client, "POST", f"/api/courses/{COURSE_ID}/chapters/{CHAPTER_ID}/practice",
                       json={"passing_threshold": 0.8})
        if started.status_code != 200:
            raise RuntimeError(f"start practice {started.status_code}: {started.text[:300]}")
        session = started.json()
        session_id = int(session["id"])
        record["session_id"] = session_id
        print(f"session {session_id} round {session.get('round_number')} "
              f"questions {session.get('round_question_count')} threshold {session.get('passing_threshold')}",
              flush=True)
        record["checks"].append({"name": "start_round_1", "status": started.status_code,
                                 "round": session.get("round_number"),
                                 "questions": session.get("round_question_count"),
                                 "threshold": session.get("passing_threshold")})

        answered = 0
        first_question = None
        while session.get("status") == "open":
            question = session.get("question")
            if not question:
                print("  no current question; stopping", flush=True)
                break
            if first_question is None:
                first_question = {"question_id": int(question["id"]),
                                  "response": "A" if question["kind"] == "mcq" else "I am not sure."}
            response = "A" if question["kind"] == "mcq" else "I am not sure."
            print(f"  answer {answered + 1}: round {session.get('round_number')} "
                  f"{question['kind']} q{question['id']}", flush=True)
            result = call(client, "POST",
                          f"/api/courses/{COURSE_ID}/practice/{session_id}/answer",
                          json={"question_id": question["id"], "response": response})
            if result.status_code != 200:
                raise RuntimeError(f"answer {result.status_code}: {result.text[:300]}")
            session = result.json()
            answered += 1
            if answered > 24:
                raise RuntimeError("answer loop exceeded the two-round question budget")
            if session.get("status") == "finished":
                break
            next_round = session.get("round_number")
            if next_round == 2 and record.get("round_2_started") is None:
                record["round_2_started"] = True
                record["checks"].append({"name": "round_2_started",
                                         "questions": session.get("round_question_count"),
                                         "answered": answered})
                print(f"round 2 started: {session.get('round_question_count')} questions",
                      flush=True)

        record["answered"] = answered
        report = session.get("report") or {}
        record["status"] = session.get("status")
        record["outcome"] = report.get("outcome")
        record["rounds"] = report.get("rounds")
        record["remaining_weak_concepts"] = report.get("remaining_weak_concepts")
        record["remaining_source_count"] = len(report.get("remaining_sources") or [])
        record["report_question_count"] = len(report.get("questions") or [])
        print(f"finished: status={session.get('status')} outcome={report.get('outcome')} "
              f"rounds={[r.get('score') for r in (report.get('rounds') or [])]} "
              f"weak={len(report.get('remaining_weak_concepts') or [])}", flush=True)
        record["checks"].append({
            "name": "finished_after_two_rounds",
            "status": session.get("status"),
            "outcome": report.get("outcome"),
            "rounds": len(report.get("rounds") or []),
            "passed": report.get("passed"),
            "remaining_weak": len(report.get("remaining_weak_concepts") or []),
            "remaining_sources": len(report.get("remaining_sources") or []),
        })

        if first_question is not None:
            before = json.dumps(report.get("rounds"), sort_keys=True)
            duplicate = call(client, "POST",
                             f"/api/courses/{COURSE_ID}/practice/{session_id}/answer",
                             json=first_question)
            after = json.dumps((duplicate.json().get("report") or {}).get("rounds"), sort_keys=True)
            record["checks"].append({
                "name": "duplicate_submission_no_rescore",
                "status": duplicate.status_code,
                "rounds_unchanged": duplicate.status_code == 200 and before == after,
            })
            print(f"duplicate submission: {duplicate.status_code} unchanged={before == after}", flush=True)

        reread = call(client, "GET", f"/api/courses/{COURSE_ID}/practice/{session_id}")
        reread_body = reread.json()
        record["checks"].append({
            "name": "report_persisted_after_refresh",
            "status": reread.status_code,
            "finished": reread_body.get("status") == "finished",
            "same_rounds": (reread_body.get("report") or {}).get("rounds") == report.get("rounds"),
        })
        print("refresh persistence checked", flush=True)

    record["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    OUT.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: record.get(k) for k in
                      ("session_id", "status", "outcome", "answered", "rounds",
                       "remaining_weak_concepts", "checks")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
