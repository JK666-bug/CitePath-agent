"""Read-only live API acceptance probe (no mutations, no model calls).

Reads the private integration fixture only from its local path. Prints status
codes and counts; never prints the password, cookie value, prompts or answers.
"""
import json
import sys
from pathlib import Path

import httpx

FIXTURE = Path(sys.argv[1])
REPORT = Path(sys.argv[2])


def main():
    credentials = json.loads(FIXTURE.read_text(encoding="utf-8"))
    integration = json.loads(REPORT.read_text(encoding="utf-8"))
    base = "http://127.0.0.1:8000"
    out = {"checks": [], "resources": {}}
    with httpx.Client(base_url=base, timeout=20.0, follow_redirects=False) as client:
        response = client.post(
            "/api/login",
            json={"username": credentials["username"], "password": credentials["password"]},
        )
        out["checks"].append({"name": "login", "status": response.status_code})
        response.raise_for_status()
        me = client.get("/api/me")
        out["checks"].append({"name": "session", "status": me.status_code,
                              "user_matches": me.json().get("username") == credentials["username"]})
        courses = client.get("/api/courses").json()["courses"]
        out["resources"]["courses"] = len(courses)
        resources = integration.get("resources") or {}
        course_id = int(resources["course_id"])
        course = next((item for item in courses if int(item["id"]) == course_id), None)
        out["resources"]["target_course_present"] = course is not None
        detail = client.get(f"/api/courses/{course_id}")
        out["checks"].append({"name": "course_detail", "status": detail.status_code})
        plan = client.get(f"/api/courses/{course_id}/plan")
        plan_body = plan.json()
        chapters = (plan_body.get("plan") or {}).get("chapters") or []
        out["checks"].append({"name": "plan", "status": plan.status_code,
                              "chapters": len(chapters)})
        inventory = client.get(f"/api/courses/{course_id}/documents/inventory")
        docs = inventory.json().get("documents") or []
        out["checks"].append({
            "name": "inventory", "status": inventory.status_code,
            "documents": len(docs),
            "all_complete": all(item.get("ingest_status") == "complete" for item in docs),
            "active": sum(1 for item in docs if item.get("active")),
        })
        versions = client.get(f"/api/courses/{course_id}/plan/versions")
        out["checks"].append({"name": "plan_versions", "status": versions.status_code,
                              "versions": len(versions.json().get("versions") or [])})
        chapter_id = int(resources.get("chapter_id") or (chapters[0]["id"] if chapters else 0))
        if chapter_id:
            reports = client.get(f"/api/courses/{course_id}/chapters/{chapter_id}/reports")
            out["checks"].append({"name": "reports", "status": reports.status_code,
                                  "practice_sessions": len(reports.json().get("practice") or [])})
        session_id = resources.get("practice_session_id")
        if session_id:
            practice = client.get(f"/api/courses/{course_id}/practice/{int(session_id)}")
            body = practice.json()
            out["checks"].append({
                "name": "practice_session", "status": practice.status_code,
                "finished": body.get("status") == "finished",
                "has_report": bool(body.get("report")),
                "rounds": len((body.get("report") or {}).get("rounds") or []),
                "outcome": (body.get("report") or {}).get("outcome"),
                "questions": len((body.get("report") or {}).get("questions") or []),
            })
        questions = client.get(f"/api/courses/{course_id}/questions")
        out["checks"].append({"name": "qa_history", "status": questions.status_code,
                              "records": len(questions.json().get("questions") or []) if isinstance(questions.json(), dict) else len(questions.json() or [])})
        runtime = client.get(f"/api/courses/{course_id}/evaluation/runtime")
        out["checks"].append({"name": "runtime_identity", "status": runtime.status_code,
                              "provider": runtime.json().get("provider") if runtime.status_code == 200 else None})
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
