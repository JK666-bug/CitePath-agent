"""Bounded live API integration observations, separate from formal evaluation."""
import copy
import hashlib
import http.cookiejar
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from evaluation.live import preflight_report
from grading.score import exam_pass

ROOT = Path(__file__).resolve().parents[2]


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


class IntegrationFailure(RuntimeError):
    """Fixed identifiers are safe to write; provider/server error bodies are not."""


class ApiFailure(IntegrationFailure):
    def __init__(self, status):
        self.status = int(status)
        super().__init__(f"api_http_{self.status}")


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        # A local test origin must never redirect credentials or uploads elsewhere.
        raise IntegrationFailure("api_redirect_refused")


def local_api_url(value):
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise ValueError("Use a local API origin without credentials, query, or path")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Invalid API port")
    return value.rstrip("/")


class ApiClient:
    def __init__(self, api_url, timeout=600):
        self.origin = local_api_url(api_url)
        self.timeout = timeout
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirects(),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.requests = []

    def request(self, method, path, payload=None, pdf=None):
        headers, body = {"Accept": "application/json"}, None
        if pdf is not None:
            boundary = "citepath-" + uuid.uuid4().hex
            headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
            name = Path(pdf).name
            if any(character in name for character in '\r\n"'):
                raise IntegrationFailure("invalid_pdf_filename")
            body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
                    "Content-Type: application/pdf\r\n\r\n").encode() + Path(pdf).read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        elif payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        started, status = time.perf_counter(), None
        try:
            request = urllib.request.Request(self.origin + path, data=body, headers=headers, method=method)
            with self.opener.open(request, timeout=self.timeout) as response:
                status = response.status
                result = json.loads(response.read().decode("utf-8"))
            if not isinstance(result, (dict, list)):
                raise IntegrationFailure("unexpected_api_response")
            return result
        except urllib.error.HTTPError as error:
            status = error.code
            raise ApiFailure(error.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise IntegrationFailure("api_transport_error") from None
        except (UnicodeError, json.JSONDecodeError):
            raise IntegrationFailure("invalid_api_json") from None
        finally:
            # Never record bodies, authorization headers, cookies, passwords or answers.
            self.requests.append({"method": method, "path": path, "at": now(), "http_status": status,
                                  "latency_ms": round((time.perf_counter() - started) * 1000)})


class OwnedApiProcess:
    """Only a process created by this object is ever stopped or restarted."""
    def __init__(self, api_url):
        parsed = urllib.parse.urlsplit(local_api_url(api_url))
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise IntegrationFailure("managed_api_requires_local_http_ipv4")
        self.port = parsed.port or 80
        self.process = None

    def start(self):
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=.25):
                raise IntegrationFailure("managed_api_port_is_already_in_use")
        except OSError:
            pass
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=ROOT / "backend", stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=flags)
        client = ApiClient(f"http://127.0.0.1:{self.port}", timeout=1)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise IntegrationFailure("managed_api_exited_during_start")
            try:
                if client.request("GET", "/api/health").get("status") == "ok":
                    return
            except IntegrationFailure:
                pass
            time.sleep(.2)
        raise IntegrationFailure("managed_api_start_timeout")

    def stop(self):
        process = self.process
        if process is not None and process.poll() is None:
            if os.name == "nt":
                # A Windows venv executable is a redirector with a child Python
                # process. Terminating only the redirector leaves Uvicorn bound
                # to the port. Limit cleanup to the tree this object created.
                import psutil
                children = psutil.Process(process.pid).children(recursive=True)
                for child in reversed(children):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                _, alive = psutil.wait_procs(children, timeout=5)
                if alive:
                    raise IntegrationFailure("owned_api_child_shutdown_timeout")
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self.process = None

    def restart(self):
        if self.process is None:
            raise IntegrationFailure("no_owned_api_to_restart")
        self.stop()
        self.start()


def development_documents(corpus_path):
    path = Path(corpus_path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    chosen = {}
    for document in data.get("documents") or []:
        if document.get("lecture") not in (2, 3):
            continue
        if document.get("split") != "development" or document["lecture"] in chosen:
            raise IntegrationFailure("invalid_development_corpus")
        pdf = (path.parent / document["pdf_path"]).resolve()
        if pdf.parent != path.parent or pdf.suffix.lower() != ".pdf":
            raise IntegrationFailure("invalid_development_pdf_path")
        if hashlib.sha256(pdf.read_bytes()).hexdigest() != document.get("sha256"):
            raise IntegrationFailure("development_pdf_checksum_mismatch")
        chosen[document["lecture"]] = pdf
    if set(chosen) != {2, 3}:
        raise IntegrationFailure("development_lectures_2_and_3_required")
    return chosen


def practice_snapshot(state):
    report = state.get("report") or {}
    feedback = state.get("feedback") or {}
    question = state.get("question") or {}
    return {
        "id": state.get("id"), "status": state.get("status"), "round_number": state.get("round_number"),
        "passing_threshold": state.get("passing_threshold"), "round_results": state.get("round_results"),
        "answered_count": state.get("answered_count"), "round_question_count": state.get("round_question_count"),
        "question": {key: (state.get("question") or {}).get(key) for key in ("id", "response")},
        "question_content_sha256": fingerprint({key: question.get(key) for key in
                                                ("prompt", "options", "sources", "concept_name", "kind")}),
        "feedback_grade": {key: feedback.get(key) for key in ("question_id", "correct", "points_hit", "points_total", "rubric_hits")},
        "report": {key: report.get(key) for key in ("passed", "outcome", "rounds", "started_at", "finished_at", "correct_count", "question_count")},
        "answer_grades": [{key: item.get(key) for key in ("question_id", "response", "correct", "points_hit", "points_total", "rubric_hits")}
                          for item in report.get("questions") or []],
        "concepts": state.get("concepts"),
    }


def check_rounds(state, threshold):
    if (state.get("status") not in ("open", "finished") or state.get("round_number") not in (1, 2)
            or state.get("passing_threshold") != threshold):
        raise IntegrationFailure("round_or_saved_threshold_changed")
    results = state.get("round_results") or []
    if len(results) > 2 or [row.get("round_number") for row in results] != list(range(1, len(results) + 1)):
        raise IntegrationFailure("invalid_or_third_round")
    for row in results:
        if row.get("passed") is not exam_pass(row["correct_count"], row["total"], threshold):
            raise IntegrationFailure("pass_status_does_not_match_unrounded_grade")
    if results and results[0]["passed"] and (state["status"] != "finished" or len(results) != 1):
        raise IntegrationFailure("continued_after_first_round_pass")
    if len(results) == 2 and state["status"] != "finished":
        raise IntegrationFailure("did_not_end_after_second_round")
    if state["status"] == "open" and ((state["round_number"] == 1 and results)
            or (state["round_number"] == 2 and (len(results) != 1 or results[0]["passed"]))):
        raise IntegrationFailure("invalid_open_round_history")
    if state["status"] == "finished":
        if not results:
            raise IntegrationFailure("finished_without_official_round_score")
        if (not results[0]["passed"] and len(results) != 2) or state["round_number"] != len(results):
            raise IntegrationFailure("finished_before_required_second_round")
        last = results[-1]
        expected = f"passed_round_{last['round_number']}" if last["passed"] else "failed_after_2"
        if state.get("report", {}).get("outcome") != expected:
            raise IntegrationFailure("incorrect_final_practice_outcome")
    if state["status"] == "open" and state["round_number"] == 2 and state.get("question"):
        if state["question"]["concept_name"] not in results[0]["weak_concepts"]:
            raise IntegrationFailure("second_round_question_not_targeting_weak_concept")


def answer_for(question, answers):
    override = (answers.get("by_prompt_sha256") or {}).get(fingerprint(question.get("prompt", "")))
    response = override if override is not None else answers.get(question["kind"], "A" if question["kind"] == "mcq" else "I am not confident about this concept yet.")
    if not isinstance(response, str) or not response.strip() or len(response) > 5000:
        raise IntegrationFailure("invalid_integration_answer_fixture")
    if question["kind"] == "mcq" and response.strip().upper() not in {"A", "B", "C", "D"}:
        raise IntegrationFailure("integration_mcq_requires_one_valid_option")
    return response.strip()


def run_integration(api_url="http://127.0.0.1:8000", *, allow_create=False,
                    corpus_path=None, answers=None, include_new_materials=False,
                    manage_api_process=False, max_answers=64, client_factory=ApiClient,
                    prerequisite_check=preflight_report, process_factory=OwnedApiProcess):
    """Always return an observation report, including blocked and failed runs."""
    report = {"schema": "citepath-live-integration-v1", "run_id": str(uuid.uuid4()), "started_at": now(),
              "status": "not_run", "mode": "live_http", "synthetic": client_factory is not ApiClient,
              "formal_evaluation_run": False, "official_accepted": None, "checks": [], "resources": {},
              "mutations_performed": False, "mutation_requests_sent": False, "cleanup_performed": False,
              "limits": ["This development integration run does not replace human labels or the formal baseline/full evaluation.",
                         "Test accounts/courses are retained for inspection; no existing user data is selected or deleted."]}
    client = owned = None

    def observed(name, passed=True, detail=None):
        report["checks"].append({"name": name, "status": "passed" if passed else "failed", "at": now(), **({"observation": detail} if detail is not None else {})})
        if not passed:
            raise IntegrationFailure(name)

    try:
        local_api_url(api_url)
        if type(max_answers) is not int or not 1 <= max_answers <= 80:
            raise IntegrationFailure("max_answers_must_be_between_1_and_80")
        if answers is not None and (not isinstance(answers, dict)
                or not isinstance(answers.get("by_prompt_sha256", {}), dict)):
            raise IntegrationFailure("invalid_integration_answer_fixture")
        report["preflight"] = prerequisite_check(api_url)
        prerequisites = report["preflight"]["checks"]
        ready_without_api = all(row["ready"] for row in prerequisites if row["name"] != "api_health")
        if not ready_without_api or not allow_create:
            report["status"] = "blocked" if not ready_without_api else "not_run"
            report["blocked_reason"] = "prerequisites_missing" if not ready_without_api else "explicit_create_test_data_flag_required"
            return report
        if manage_api_process:
            if any(row["name"] == "api_health" and row["ready"] for row in prerequisites):
                raise IntegrationFailure("managed_api_port_is_already_in_use")
            owned = process_factory(api_url)
            owned.start()
            report["preflight"] = prerequisite_check(api_url)
        if report["preflight"]["status"] != "prerequisites_available":
            report["status"], report["blocked_reason"] = "blocked", "api_unavailable"
            return report
        documents = development_documents(corpus_path or ROOT / "data/mit-6.006-spring-2020/corpus.json")
        client = client_factory(api_url)
        suffix = uuid.uuid4().hex[:12]
        # An explicit environment pair permits subsequent manual login. Without
        # it, the account is single-use and its random password is never logged.
        username = os.environ.get("CITEPATH_INTEGRATION_USERNAME") or "citepath_it_" + suffix
        password = os.environ.get("CITEPATH_INTEGRATION_PASSWORD") or secrets.token_urlsafe(30)
        if not username.startswith("citepath_it_"):
            raise IntegrationFailure("dedicated_test_username_prefix_required")
        report["mutation_requests_sent"] = True
        user = client.request("POST", "/api/register", {"username": username, "password": password})
        report["mutations_performed"] = True
        report["resources"]["user_id"] = user["id"]
        report["resources"]["username"] = username
        observed("created_new_dedicated_account")
        start = datetime.now(timezone.utc).date()
        end = start + timedelta(days=7)
        profile = {"goal": "Prepare for an algorithms assessment", "prior_knowledge": "Beginner in this course", "daily_minutes": 60, "reading_words_per_minute": 180}
        brief = {"schema": "citepath-course-v1", "deadline": end.isoformat(), "earlyDays": 0,
                 "note": profile["goal"] + "; " + profile["prior_knowledge"]}
        course = client.request("POST", "/api/courses", {"name": "CitePath integration " + suffix, "student_brief": json.dumps(brief)})
        course_id = int(course["id"])
        report["resources"]["course_id"] = course_id
        base = f"/api/courses/{course_id}"
        uploaded = client.request("POST", base + "/documents", pdf=documents[2])
        observed("development_lecture_2_ingested", uploaded.get("ingest_status") == "complete")
        request = {"start": start.isoformat(), "end": end.isoformat(), "note": brief["note"], "profile": profile}
        result = client.request("POST", base + "/plan", request)
        observed("real_plan_generated", result.get("status") == "ready" and bool((result.get("plan") or {}).get("chapters")))
        plan = result["plan"]
        chapter_id = int(plan["chapters"][0]["id"])
        state = client.request("POST", base + f"/chapters/{chapter_id}/practice", {"passing_threshold": .8})
        session_id = int(state["id"])
        report["resources"]["practice_session_id"] = session_id
        session_url = base + f"/practice/{session_id}"
        observed("nonempty_saved_question_set", bool(state.get("question")) and state.get("round_question_count", 0) > 0)
        answers = answers or {}
        first = state["question"]
        draft = answer_for(first, answers)
        client.request("PATCH", session_url + "/draft", {"question_id": first["id"], "response": draft})
        restored = client.request("GET", session_url)
        observed("draft_and_question_restored", restored["question"]["id"] == first["id"] and restored["question"].get("response") == draft)
        if owned:
            saved_snapshot = practice_snapshot(restored)
            owned.restart()
            restored = client.request("GET", session_url)
            observed("owned_api_process_restart_restores_state", practice_snapshot(restored) == saved_snapshot)
        else:
            report["checks"].append({"name": "api_process_restart", "status": "not_run", "reason": "No API process was created/owned by this runner"})
        state, submitted = restored, {}
        while state["status"] == "open":
            check_rounds(state, .8)
            question = state.get("question")
            observed("current_question_is_new_and_bounded", bool(question) and question["id"] not in submitted and len(submitted) < max_answers)
            response = answer_for(question, answers)
            started = time.perf_counter()
            state = client.request("POST", session_url + "/answer", {"question_id": question["id"], "response": response})
            elapsed = round((time.perf_counter() - started) * 1000)
            submitted[question["id"]] = response
            check_rounds(state, .8)
            report.setdefault("grading_and_feedback_latency_ms", []).append(elapsed)
            observed("submitted_answer_saved", detail={"question_id": question["id"], "round_number": state["round_number"], "snapshot_sha256": fingerprint(practice_snapshot(state))})
            if len(submitted) == 1:
                before = practice_snapshot(state)
                state = client.request("POST", session_url + "/answer", {"question_id": question["id"], "response": "D" if question["kind"] == "mcq" and response != "D" else "A" if question["kind"] == "mcq" else "An altered duplicate response."})
                observed("duplicate_submission_preserves_saved_result", practice_snapshot(state) == before)
                before = practice_snapshot(state)
                client.request("POST", base + "/questions", {"question": "According to the uploaded notes, how do sequence and set interfaces differ?"})
                state = client.request("GET", session_url)
                observed("independent_qa_preserves_practice_state", practice_snapshot(state) == before)
        check_rounds(state, .8)
        saved = practice_snapshot(state)
        observed("valid_final_two_round_outcome", state["status"] == "finished", {"outcome": state["report"]["outcome"], "rounds": state["round_results"]})
        report["actual_round_count"] = len(state["round_results"])
        report["round_2_observed"] = len(state["round_results"]) == 2
        if not report["round_2_observed"]:
            report["checks"].append({"name": "second_round_execution", "status": "not_run",
                                     "reason": "The actual first round passed; this run does not establish second-round execution"})
        for question in state["report"].get("questions") or []:
            observed("saved_answer_not_overwritten", question["response"] == submitted[question["question_id"]])
        if state["report"].get("wrong"):
            wrong = state["report"]["wrong"][0]
            state = client.request("POST", session_url + f"/questions/{wrong['question_id']}/explanation/retry")
            observed("explanation_retry_preserves_official_result", practice_snapshot(state) == saved)
        else:
            report["checks"].append({"name": "wrong_explanation_retry", "status": "not_run", "reason": "The actual grader found no incorrect answers"})
        state = client.request("GET", session_url)
        observed("finished_result_survives_reopen", practice_snapshot(state) == saved)
        if include_new_materials:
            old_ids = {str(item["id"]) for item in plan["chapters"]}
            completed = next((task for task in plan["tasks"] if task["kind"] == "Reading"), None)
            if completed:
                completed_plan = client.request("POST", base + f"/plan/tasks/{completed['id']}/complete")["plan"]
                completed = next(task for task in completed_plan["tasks"] if task["id"] == completed["id"])
            client.request("POST", base + "/documents", pdf=documents[3])
            current = client.request("GET", base + "/plan")
            observed("new_materials_detected", (current.get("material_update") or {}).get("new_page_count", 0) > 0)
            updated = client.request("POST", base + "/plan", {**request, "update_materials": True, "expected_version": current["plan"]["version"]})["plan"]
            observed("material_update_preserves_old_chapter_ids", old_ids <= {str(item["id"]) for item in updated["chapters"]})
            observed("new_development_material_included", any(source["document_id"] != uploaded["document_id"] for chapter in updated["chapters"] for source in chapter["sources"]))
            if completed:
                observed("material_update_preserves_completed_task", next(task for task in updated["tasks"] if task["id"] == completed["id"]) == completed)
            observed("material_update_preserves_finished_practice", practice_snapshot(client.request("GET", session_url)) == saved)
        report["status"] = "completed"
    except (Exception, KeyboardInterrupt) as error:
        report["status"] = "failed"
        report["failure"] = {"type": type(error).__name__, "code": str(error) if isinstance(error, IntegrationFailure) else "unexpected_integration_failure"}
    finally:
        if client is not None:
            if report["resources"].get("user_id"):
                try:
                    client.request("POST", "/api/logout")
                except Exception:
                    pass
            report["requests"] = copy.deepcopy(client.requests)
        if owned is not None:
            try:
                owned.stop()
            except Exception:
                report["checks"].append({"name": "owned_api_shutdown", "status": "failed"})
                report["status"] = "failed"
                report["failure"] = {"type": "IntegrationFailure", "code": "owned_api_shutdown_failed"}
        report["finished_at"] = now()
    return report
