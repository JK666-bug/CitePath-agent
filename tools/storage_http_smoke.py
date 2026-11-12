"""Explicit real storage integration on dedicated development fixtures; no chat LLM."""
import argparse
import hashlib
import json
import secrets
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
work = repo.parent
sys.path.insert(0, str(repo / "backend"))
from dotenv import load_dotenv
load_dotenv(repo / "backend/.env", override=False)
from evaluation.integration import ApiClient, ApiFailure, OwnedApiProcess, development_documents
from db.connection import connect
from db.plans import ensure_plan_storage, load_usable_pages
from db.practice import ensure_practice_storage
from db.exams import ensure_exam_storage
from db.uploads import ensure_document_numbers
from vector import segments

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--run", action="store_true", help="Create retained dedicated development fixtures and call real PDF/vector services")
parser.add_argument("--output", type=Path, default=repo / "backend/logs/storage-http.json")
args = parser.parse_args()
if not args.run:
    print(json.dumps({"status": "not_run", "explicit_run_flag_required": True, "database_mutated": False}))
    raise SystemExit(2)
output = args.output.resolve()
if repo / "evaluation_assets" in output.parents:
    raise ValueError("Runtime outputs must stay outside protected evaluation assets")
output.parent.mkdir(parents=True, exist_ok=True)
report = {"schema": "citepath-real-storage-smoke-v1", "started_at": datetime.now(timezone.utc).isoformat(),
          "status": "running", "model_invoked": False, "formal_evaluation_run": False,
          "official_accepted": None, "test_fixture_origin": "dedicated_development_account_original_lectures_2_3",
          "checks": [], "resources": {}, "existing_data_deleted": False,
          "limits": ["Storage/retrieval behavior is distinct from generated plan quality, grader accuracy and citation support.",
                     "No human labels or formal baseline/full observations are supplied."]}
client = ApiClient("http://127.0.0.1:8018", timeout=240)
process = OwnedApiProcess(client.origin)
step = "initialization"

def save():
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def check(name, valid, details=None):
    row = {"name": name, "passed": bool(valid)}
    if details is not None:
        row["details"] = details
    report["checks"].append(row)
    save()
    print(json.dumps(row), flush=True)
    if not valid:
        raise AssertionError(name)

def raw_file(path, opener):
    with opener.open(urllib.request.Request(client.origin + path), timeout=10) as response:
        return response.read()

try:
    for migrate in (ensure_document_numbers, ensure_plan_storage, ensure_practice_storage, ensure_exam_storage):
        migrate()
    check("production_schema_migrations", True)
    documents = development_documents(repo / "data/mit-6.006-spring-2020/corpus.json")
    process.start()
    check("owned_api_started", True)
    suffix = uuid.uuid4().hex[:10]
    user = client.request("POST", "/api/register", {"username": "citepath_it_s_" + suffix,
                                                    "password": secrets.token_urlsafe(24)})
    report["resources"]["user_id"] = user["id"]
    course = client.request("POST", "/api/courses", {"name": "Storage integration " + suffix,
        "student_brief": "Development storage verification using original MIT Lectures 2 and 3; not formal evaluation."})
    course_id = int(course["id"])
    report["resources"]["course_id"] = course_id
    base = f"/api/courses/{course_id}"
    saved = {}
    for lecture in (2, 3):
        step = f"upload_lecture_{lecture}"
        print(json.dumps({"step": step, "status": "started"}), flush=True)
        uploaded = client.request("POST", base + "/documents", pdf=documents[lecture])
        identifier = int(uploaded["document_id"])
        saved[lecture] = identifier
        report["resources"][f"lecture_{lecture}_document_id"] = identifier
        inventory = client.request("GET", base + "/documents/inventory")["documents"]
        row = next(item for item in inventory if int(item["id"]) == identifier)
        expected_sha = hashlib.sha256(documents[lecture].read_bytes()).hexdigest()
        check(f"lecture_{lecture}_actual_pdf_sql_vector_ingestion", row["ingest_status"] == "complete"
              and row["sha256"] == expected_sha and row["page_count"] == (5 if lecture == 2 else 6)
              and row["usable_page_count"] == (4 if lecture == 2 else 5), {"document_id": identifier, "pages": row["page_count"]})
        check(f"lecture_{lecture}_actual_vector_rows", segments.has_segments(identifier))
        data = raw_file(base + f"/documents/{identifier}/file", client.opener)
        check(f"lecture_{lecture}_original_pdf_exact_bytes", hashlib.sha256(data).hexdigest() == expected_sha)
    step = "retrieval"
    hits = segments.search([saved[2]], "How do sequence interfaces differ from set interfaces?")
    check("actual_dense_bm25_hybrid_retrieval", bool(hits) and all(int(hit["document_id"]) == saved[2]
        and 1 <= int(hit["page_number"]) <= 4 and bool(hit["text"].strip()) for hit in hits), {"hit_count": len(hits)})
    step = "archive"
    identifier = saved[2]
    original_url = base + f"/documents/{identifier}/file"
    client.request("DELETE", base + f"/documents/{identifier}")
    inventory = client.request("GET", base + "/documents/inventory")["documents"]
    archived = next(row for row in inventory if int(row["id"]) == identifier)
    active = next(row for row in inventory if int(row["id"]) == saved[3])
    check("archive_retains_id_pages_and_original", archived["active"] is False and archived["page_count"] == 5
          and hashlib.sha256(raw_file(original_url, client.opener)).hexdigest() == hashlib.sha256(documents[2].read_bytes()).hexdigest())
    check("active_material_renumbered", active["position"] == 1)
    check("archived_pages_excluded_from_new_planning", all(int(page["document_id"]) != identifier for page in load_usable_pages(course_id)))
    check("archived_document_vector_rows_removed", not segments.has_segments(identifier))
    check("archived_document_not_retrieved", not segments.search([identifier], "sequence and set"))
    step = "restore"
    restored = client.request("POST", base + f"/documents/{identifier}/restore")
    check("restore_uses_original_identity", int(restored["document_id"]) == identifier and segments.has_segments(identifier))
    replay = client.request("POST", base + "/documents", pdf=documents[2])
    check("same_pdf_reupload_is_idempotent", int(replay["document_id"]) == identifier
          and len(client.request("GET", base + "/documents/inventory")["documents"]) == 2)
    expected_inventory = client.request("GET", base + "/documents/inventory")
    step = "restart"
    process.restart()
    check("sql_inventory_survives_api_restart", client.request("GET", base + "/documents/inventory") == expected_inventory)
    check("original_pdf_survives_api_restart", raw_file(original_url, client.opener) == documents[2].read_bytes())
    check("vector_index_survives_api_restart", bool(segments.search([identifier], "sequence and set")))
    step = "access_control"
    unauthorized = ApiClient(client.origin)
    try:
        raw_file(original_url, unauthorized.opener)
        denied = False
    except urllib.error.HTTPError as error:
        denied = error.code == 401
    check("original_pdf_requires_authentication", denied)
    stranger = ApiClient(client.origin)
    stranger.request("POST", "/api/register", {"username": "citepath_it_x_" + suffix, "password": secrets.token_urlsafe(24)})
    for name, path in (("file", original_url), ("inventory", base + "/documents/inventory")):
        try:
            raw_file(path, stranger.opener)
            denied = False
        except urllib.error.HTTPError as error:
            denied = error.code == 404
        check("cross_owner_" + name + "_denied", denied)
    report["status"] = "passed"
except Exception as error:
    report.update(status="failed", failure={"step": step, "type": type(error).__name__})
    if isinstance(error, ApiFailure):
        report["failure"]["http_status"] = error.status
    print(json.dumps(report.get("failure")), flush=True)
finally:
    try:
        process.stop()
    except Exception as error:
        report.update(status="failed", cleanup_failure=type(error).__name__)
    report["requests"] = client.requests
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    save()
    print(json.dumps({"status": report["status"], "checks": len(report["checks"]), "output": str(output)}), flush=True)

raise SystemExit(0 if report["status"] == "passed" else 1)
