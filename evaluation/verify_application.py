"""Verify a running CitePath instance using a dedicated test account."""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import secrets
from time import perf_counter
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = json.loads((ROOT / "evaluation/scenarios.json").read_text(encoding="utf-8"))
ZONE = ZoneInfo("Asia/Hong_Kong")


class Verification:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.records = []
        self.course = ""
        self.document = 0
        self.chapter = ""
        self.day = datetime.now(ZONE).date()
        dates = SCENARIOS["date_rules"]
        self.start = self.day.isoformat()
        self.end = (self.day + timedelta(days=dates["learning_window_days_after_today"])).isoformat()
        self.profile = {
            "start": self.start, "end": self.end, "daily_minutes": dates["daily_minutes"],
            "weekdays": dates["study_weekdays"], "off_dates": [], "priority_chapter_ids": [],
            "strategy": SCENARIOS["cases"]["normal"]["strategy"],
        }

    def api(self, method: str, path: str, expected: int = 200, **kwargs) -> dict:
        response = self.client.request(method, path, **kwargs)
        if response.status_code != expected:
            raise AssertionError(f"{method} {path}: HTTP {response.status_code}, expected {expected}")
        return response.json()

    def run(self, name: str, operation, *args) -> bool:
        started = perf_counter()
        try:
            observed = operation(*args)
            status = "passed"
        except (AssertionError, httpx.HTTPError, KeyError, ValueError, StopIteration) as error:
            observed = {"error_type": type(error).__name__, "message": str(error)}
            status = "failed"
        self.records.append({"case": name, "status": status,
                             "duration_ms": round((perf_counter() - started) * 1000),
                             "observed": observed})
        print(name, status, flush=True)
        return status == "passed"

    def setup(self) -> dict:
        assert self.api("GET", "/api/health")["status"] == "ok"
        self.api("POST", "/api/register", json={"username": "audit_" + uuid4().hex[:12],
                                                "password": secrets.token_urlsafe(24)})
        brief = {"schema": "citepath-course-v1", "startDate": self.start, "deadline": self.end,
                 "earlyDays": 0, "note": "Submission evaluation using the included sample PDF."}
        course = self.api("POST", "/api/courses", json={"name": SCENARIOS["course_name"],
                                                         "student_brief": json.dumps(brief)})
        self.course = f"/api/courses/{course['id']}"
        return {"service_health": "ok", "course_created": True}

    def invalid_pdf(self) -> dict:
        status = SCENARIOS["cases"]["empty_pdf"]["expected_http_status"]
        response = self.api(
            "POST", self.course + "/documents", expected=status,
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
        assert response["detail"] == "The PDF is empty"
        return {"http_status": status, "detail": response["detail"]}

    def upload_and_analyze(self) -> dict:
        sample = ROOT / SCENARIOS["sample_pdf"]
        with sample.open("rb") as stream:
            upload = self.api("POST", self.course + "/documents",
                              files={"file": (sample.name, stream, "application/pdf")})
        assert upload["milvus_segments"] > 0
        self.document = upload["document_id"]
        assert upload["usable_page_count"] == SCENARIOS["expected_readable_pages"]
        original = self.client.get(self.course + f"/documents/{self.document}/file")
        assert original.status_code == 200 and original.content == sample.read_bytes()
        opts = self.api("GET", self.course + "/chapters/options")
        self.api("POST", self.course + "/chapters/rebuild",
                 json={"token": opts["token"], "document_ids": [self.document], "confirmed": False})
        plan = self.plan()
        assert plan["chapters"] and plan["tasks"]
        self.chapter = str(plan["chapters"][0]["id"])
        return {"usable_pages": upload["usable_page_count"], "indexed_segments": upload["milvus_segments"],
                "chapters": len(plan["chapters"]), "tasks": len(plan["tasks"]),
                "original_download_matches": True}

    def plan(self) -> dict:
        return self.api("GET", self.course + "/plan")["plan"]

    def settings(self, profile: dict, deadline: str | None = None) -> None:
        self.api("PUT", self.course + "/settings", json={"name": SCENARIOS["course_name"],
                 "note": "Submission evaluation using the included sample PDF.", "events": [],
                 "startDate": self.start, "deadline": deadline or self.end, "earlyDays": 0,
                 "scheduling_profile": profile, "scheduling_mode": SCENARIOS["cases"]["normal"]["mode"]})

    def preview(self) -> dict:
        return self.api("POST", self.course + "/schedule", json={"request_id": uuid4().hex, "preview": True})

    def apply(self, preview: dict, expected: int = 200) -> dict:
        return self.api("POST", self.course + f"/schedule/{preview['run_id']}/apply", expected=expected)

    @staticmethod
    def dates(plan: dict) -> dict:
        return {task["id"]: (task.get("date"), task.get("schedule")) for task in plan["tasks"]}

    def normal(self) -> dict:
        self.settings(self.profile)
        before = self.dates(self.plan())
        preview = self.preview()
        assert preview["status"] == "preview", preview.get("message")
        assert self.dates(self.plan()) == before, "Preview changed the published calendar"
        applied = self.apply(preview)
        assert applied["status"] == "saved"
        saved = self.plan()
        daily = defaultdict(int)
        for task in saved["tasks"]:
            assert task["schedule"], f"No slots for {task['id']}"
            for slot in task["schedule"]:
                daily[slot["date"]] += slot["minutes"]
        assert daily and max(daily.values()) <= self.profile["daily_minutes"]
        assert all(self.start <= day <= self.end for day in daily)
        assert set(before) == set(self.dates(saved))
        return {"preview": preview["status"], "apply": applied["status"], "days": dict(daily),
                "version": saved["version"], "tools": preview["trace"]}

    def changed(self) -> dict:
        saved = self.plan()
        reading = next(task for task in saved["tasks"] if task["kind"] == "Reading" and task["status"] != "Completed")
        self.api("POST", self.course + f"/plan/tasks/{reading['id']}/complete")
        finished = self.plan()
        omitted = min(slot["date"] for task in finished["tasks"] if task["status"] != "Completed"
                      for slot in task["schedule"])
        self.settings({**self.profile, "off_dates": [omitted]})
        preview = self.preview()
        assert preview["status"] == "preview", preview.get("message")
        applied = self.apply(preview)
        assert applied["status"] == "saved"
        plan = self.plan()
        assert all(slot["date"] != omitted for task in plan["tasks"] if task["status"] != "Completed"
                   for slot in task["schedule"])
        old_tasks = {task["id"]: task for task in finished["tasks"]}
        assert any(task["id"] == reading["id"] and task["status"] == "Completed" for task in plan["tasks"])
        assert all(task == old_tasks[task["id"]] for task in plan["tasks"] if task["status"] == "Completed")
        return {"version": plan["version"], "added_day_off": omitted, "completed_preserved": True,
                "tools": preview["trace"]}

    def insufficient(self) -> dict:
        before = self.dates(self.plan())
        case = SCENARIOS["cases"]["insufficient_capacity"]
        self.settings({**self.profile, "end": self.start, "daily_minutes": case["daily_minutes"],
                       "weekdays": [self.day.weekday()]}, deadline=self.start)
        preview = self.preview()
        assert preview["status"] == case["expected_status"], preview.get("message")
        assert preview["budget"]["shortfall_minutes"] > 0
        assert self.dates(self.plan()) == before
        return {"response": preview["status"], "budget": preview["budget"],
                "published_dates_preserved": True, "tools": preview["trace"]}

    def stale(self) -> dict:
        before = self.dates(self.plan())
        case = SCENARIOS["cases"]["stale_preview"]
        self.settings({**self.profile, "daily_minutes": case["preview_daily_minutes"]})
        preview = self.preview()
        assert preview["status"] == "preview" and not preview["unchanged"], preview.get("message")
        self.settings({**self.profile, "daily_minutes": case["updated_daily_minutes"]})
        status = case["expected_http_status"]
        rejected = self.apply(preview, expected=status)
        assert "Create a new preview" in rejected["detail"]
        assert self.dates(self.plan()) == before
        return {"apply_http_status": status, "detail": rejected["detail"], "published_dates_preserved": True,
                "preview_trace": preview["trace"]}

    def reading(self, page: int | None = None) -> dict:
        sample = SCENARIOS["cases"]["reading_qa"]
        body = {"question": sample["question"], "include_web": False, "chat": True,
                "document_ids": [self.document], "tab_id": str(uuid4())}
        if page is not None:
            body["page_number"] = page
        invalid = page == sample["invalid_page"]
        response = self.api("POST", self.course + "/questions", expected=400 if invalid else 200, json=body)
        if invalid:
            assert response["detail"] == f"No readable text on PDF page(s): {page}."
            return {"http_status": 400, "detail": response["detail"]}
        pages = [item["page_number"] for item in response["cited_pages"] if item["document_id"] == self.document]
        answer = response["answer"]
        matched = bool(re.search(sample["answer_pattern"], answer, re.IGNORECASE))
        observed = {"http_status": 200, "answer": answer, "cited_pages": pages,
                    "origin": response["origin"], "refused": response["refused"]}
        assert matched and sample["expected_page"] in pages and not response["refused"], (
            f"Expected cleared existing contents and PDF page {sample['expected_page']}: {observed}"
        )
        return observed

    def practice(self) -> dict:
        response = self.api("POST", self.course + f"/chapters/{self.chapter}/practice", json={})
        question = response["question"]
        decision = question["decision"]
        assert question["kind"] == decision["kind"]
        assert decision["mode"] == "agent", f"Expected a model choice, observed {decision['mode']}"
        return {"kind": question["kind"], "concept": question["concept_name"],
                "decision_mode": decision["mode"], "reason": decision["reason"], "trace": decision["trace"]}

    def exam(self) -> dict:
        response = self.client.post(self.course + f"/chapters/{self.chapter}/exams")
        result = response.json()
        assert response.status_code == 200, (
            f"Exam generation HTTP {response.status_code}: {str(result.get('detail', ''))[:300]}"
        )
        questions = result["questions"]
        assert questions
        return {"generated_questions": len(questions), "kinds": sorted({q["kind"] for q in questions})}

    def cleanup(self) -> dict:
        if self.course:
            self.api("DELETE", self.course)
        self.api("POST", "/api/logout")
        return {"course_deleted": True, "logged_out": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000",
                        help="Base URL of the local instance. The script creates a test account and course.")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if httpx.URL(args.base_url).host not in ("127.0.0.1", "localhost", "::1"):
        parser.error("--base-url must refer to a local instance")
    with httpx.Client(base_url=args.base_url, timeout=210, trust_env=False) as client:
        verifier = Verification(client)
        try:
            if verifier.run("register_and_create_course", verifier.setup):
                verifier.run("empty_pdf_rejected", verifier.invalid_pdf)
                if verifier.run("upload_and_chapterization", verifier.upload_and_analyze):
                    verifier.run("normal", verifier.normal)
                    verifier.run("changed_request", verifier.changed)
                    verifier.run("insufficient_capacity", verifier.insufficient)
                    verifier.run("stale_preview", verifier.stale)
                    verifier.run("reading_qa_full_pdf", verifier.reading)
                    reading = SCENARIOS["cases"]["reading_qa"]
                    verifier.run("reading_qa_selected_page", verifier.reading, reading["expected_page"])
                    verifier.run("reading_qa_bad_page", verifier.reading, reading["invalid_page"])
                    verifier.run("practice", verifier.practice)
                    verifier.run("exam_generation", verifier.exam)
        finally:
            try:
                if verifier.course:
                    verifier.run("cleanup_test_course", verifier.cleanup)
            finally:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps({"at": datetime.now(ZONE).isoformat(),
                    "scope": "Local API, actual services and configured model. Plan workflow uses Fixed rules.",
                    "submission_version": SCENARIOS["submission_version"],
                    "sample_pdf": SCENARIOS["sample_pdf"],
                    "records": verifier.records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if any(row["status"] != "passed" for row in verifier.records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
